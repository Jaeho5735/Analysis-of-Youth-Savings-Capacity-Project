"""
대표경로 재선택 — 심야버스 제외

재조회(searchDttm=08:00) 후에도 심야버스 경로가 559건(1.8%) 남았다.
후보가 평균 9.8개 있는데도 선택된 것이라, Tmap이 08:00 조회에도
N버스를 후보에 포함시킨 것으로 보인다.

후보 전량이 commute_routes_alternatives.jsonl 에 저장돼 있으므로
API 재호출 없이 다시 고를 수 있다. 비용 0원.

선택 규칙은 재조회와 동일하되 심야 노선만 배제한다.

    1. 심야버스(N##) 포함 후보 제외
    2. 남은 후보 중 최단 + 15분 이내
    3. 일반화비용(편도 교통비 + 통근시간 x 시간가치) 최소
    4. 심야 아닌 후보가 하나도 없으면 원래 선택을 유지하고 플래그

사용법
    python reselect_routes.py --dry-run     바뀌는 건수만 확인
    python reselect_routes.py               실제 반영
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

TIME_VALUE_PER_HOUR_WON = 10_320
ROUTE_MAX_EXTRA_MINUTES = 15
NIGHT_BUS = re.compile(r"N\d{2}")

IN_CSV = "data/commute_routes_requeried.csv"
IN_JSONL = "data/commute_routes_alternatives.jsonl"
OUT_CSV = "data/commute_routes_requeried_reselected.csv"
REPORT = "docs/재선택_결과.csv"


def log(m=""):
    print(m, flush=True)


def section(t):
    log()
    log("=" * 66)
    log(t)
    log("=" * 66)


def read_csv_any(path, **kw):
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"{path} 읽기 실패")


def is_night(line):
    return bool(NIGHT_BUS.search(str(line or "")))


def gen_cost(c):
    """저장된 후보에 일반화비용이 없으면 계산해서 채운다."""
    g = c.get("편도일반화비용_원")
    if g is not None:
        return float(g)
    t, f = c.get("편도통근시간_분"), c.get("편도교통비_원")
    if t is None or f is None:
        return None
    return float(f) + (float(t) / 60) * TIME_VALUE_PER_HOUR_WON


def pick(cands):
    """심야 제외 후 재선택. (선택, 사유) 반환."""
    usable = [c for c in cands
              if c.get("편도통근시간_분") is not None
              and c.get("편도교통비_원") is not None
              and gen_cost(c) is not None]
    if not usable:
        return None, "후보없음"

    clean = [c for c in usable if not is_night(c.get("이용노선"))]
    if not clean:
        return None, "심야만존재"

    fastest = min(float(c["편도통근시간_분"]) for c in clean)
    realistic = [c for c in clean
                 if float(c["편도통근시간_분"]) <= fastest + ROUTE_MAX_EXTRA_MINUTES] or clean

    def key(c):
        tr = c.get("환승횟수")
        tr = float(tr) if tr is not None else 999
        return (gen_cost(c), float(c["편도통근시간_분"]),
                float(c["편도교통비_원"]), tr, int(c.get("API경로순위") or 99))

    return sorted(realistic, key=key)[0], "재선택"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=IN_CSV)
    ap.add_argument("--jsonl", default=IN_JSONL)
    ap.add_argument("--out", default=OUT_CSV)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    section("[1단계] 입력 확인")
    for lb, p in [("CSV", args.csv), ("JSONL", args.jsonl)]:
        ok = Path(p).exists()
        log(f"  {lb:6s} {p}  {'OK' if ok else '(없음)'}")
        if not ok:
            return

    df = read_csv_any(args.csv)
    df.columns = [c.strip() for c in df.columns]
    df["_night"] = df["이용노선"].astype(str).str.contains(NIGHT_BUS, na=False)
    n_night = int(df["_night"].sum())
    log(f"\n  전체 {len(df):,}건 / 심야버스 {n_night:,}건 ({n_night/len(df)*100:.1f}%)")
    if n_night == 0:
        log("  심야버스가 없다. 재선택할 것이 없다.")
        return

    section("[2단계] 후보 로드")
    targets = set(df.loc[df["_night"], "OD_KEY"].astype(str))
    alts = {}
    bad = 0
    with open(args.jsonl, encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            k = str(o.get("OD_KEY"))
            if k in targets:
                alts[k] = o.get("candidates") or []
    log(f"  대상 {len(targets):,}건 중 후보 확보 {len(alts):,}건")
    if bad:
        log(f"  [주의] 파싱 실패 라인 {bad:,}개")
    missing = targets - set(alts)
    if missing:
        log(f"  [주의] 후보가 없는 OD {len(missing):,}건 — 원래 값 유지")

    section("[3단계] 재선택")
    stats = {"재선택": 0, "심야만존재": 0, "후보없음": 0, "후보미보유": 0}
    rows, changes = [], []

    cols = [c for c in df.columns if not c.startswith("_")]
    for _, r in df.iterrows():
        if not r["_night"]:
            rows.append(r[cols].to_dict())
            continue
        key = str(r["OD_KEY"])
        cands = alts.get(key)
        if not cands:
            stats["후보미보유"] += 1
            d = r[cols].to_dict()
            d["선택방식"] = str(d.get("선택방식", "")) + "|심야유지_후보없음"
            rows.append(d)
            continue

        sel, why = pick(cands)
        stats[why] = stats.get(why, 0) + 1
        d = r[cols].to_dict()
        if sel is None:
            d["선택방식"] = str(d.get("선택방식", "")) + f"|심야유지_{why}"
        else:
            before_t = r.get("편도통근시간_분")
            before_l = r.get("이용노선")
            for k, v in sel.items():
                if k in d:
                    d[k] = v
            d["선택방식"] = "night_excluded_reselect_v1"
            changes.append({
                "OD_KEY": key,
                "거주동 코드": r.get("거주동 코드"), "근무동 코드": r.get("근무동 코드"),
                "전_시간_분": before_t, "후_시간_분": sel.get("편도통근시간_분"),
                "차이_분": round(float(sel.get("편도통근시간_분", 0)) - float(before_t or 0), 1),
                "전_노선": before_l, "후_노선": sel.get("이용노선"),
                "전_요금": r.get("편도교통비_원"), "후_요금": sel.get("편도교통비_원"),
            })
        rows.append(d)

    out = pd.DataFrame(rows)
    out["_night2"] = out["이용노선"].astype(str).str.contains(NIGHT_BUS, na=False)

    section("[4단계] 결과")
    for k, v in stats.items():
        if v:
            log(f"  {k:14s} {v:>6,}건")
    log()
    log(f"  심야버스  {n_night:,}건  →  {int(out['_night2'].sum()):,}건")

    if changes:
        ch = pd.DataFrame(changes)
        log()
        log(f"  통근시간 변화 (재선택 {len(ch):,}건)")
        log(f"    평균 {ch['차이_분'].mean():+.1f}분 / 중앙 {ch['차이_분'].median():+.1f}분")
        log(f"    최대 증가 {ch['차이_분'].max():+.1f}분 / 최대 감소 {ch['차이_분'].min():+.1f}분")
        log()
        log("  변화가 큰 5건")
        log(ch.reindex(ch["차이_분"].abs().sort_values(ascending=False).index)
              .head(5)[["전_시간_분", "후_시간_분", "차이_분", "전_노선", "후_노선"]]
              .to_string(index=False))

    if args.dry_run:
        section("dry-run 종료")
        log("  파일을 쓰지 않았다. 결과가 타당하면 --dry-run 없이 다시 실행해라.")
        return

    out.drop(columns=["_night2"]).to_csv(args.out, index=False, encoding="utf-8-sig")
    log(f"\n  저장: {args.out}")
    if changes:
        Path(REPORT).parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(changes).to_csv(REPORT, index=False, encoding="utf-8-sig")
        log(f"  변경 내역: {REPORT}")

    section("완료")
    log("  다음: 실패 63건 재조회 후 정제·적재")


if __name__ == "__main__":
    main()