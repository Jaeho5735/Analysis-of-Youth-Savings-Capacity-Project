"""
재조회 결과를 analysis_ready 형식으로 정제

재선택본(23컬럼)을 기존 commute_routes_analysis_ready.csv(35컬럼) 형식에 맞춘다.
컬럼은 세 갈래로 나뉜다.

    OD에서 그대로   OD_KEY, 거주동/근무동 코드·이름, 목적지_순위, 출근_이동량,
                   가중치, 평균_이동시간_분 등  -> 재조회와 무관하므로 원본 유지
    재조회로 갱신   분석용_편도시간/거리/요금, 도보, 환승, 구간수, 노선 등
    내부통근        API 대상이 아니므로 기존 값을 그대로 승계

경로없음 62건(도보권 추정)은 격리한다. 0분·0원으로 채우면
"대중교통이 공짜인 동"이 되어 부담 계산이 왜곡된다.

사용법
    python rebuild_analysis_ready.py --dry-run
    python rebuild_analysis_ready.py
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

OD_CSV = "data/all_age_commute_od_selected_80.csv"
OLD_CSV = "data/commute_routes_analysis_ready.csv"
NEW_CSV = "data/commute_routes_requeried_reselected.csv"
OUT_CSV = "data/commute_routes_analysis_ready.csv"
QUAR_CSV = "data/quarantine/commute_routes_no_route.csv"

# 재조회 결과 -> analysis_ready 컬럼
RENAME = {
    "편도통근시간_분": "분석용_편도시간_분",
    "편도거리_km": "분석용_편도거리_km",
    "편도교통비_원": "분석용_편도요금_원",
    "편도도보시간_분": "총도보시간_분",
    "편도도보거리_m": "총도보거리_m",
    "환승횟수": "환승횟수",
    "버스_이용구간수": "버스_이용구간수",
    "지하철_이용구간수": "지하철_이용구간수",
    "도보_구간수": "도보_구간수",
    "기차_이용구간수": "기차_이용구간수",
    "교통수단_순서": "교통수단_순서",
    "이용노선": "이용노선",
    "현실후보수": "추천경로수",
    "후보수": "전체추천경로수",
}

# OD 원본에서 그대로 가져오는 컬럼
OD_KEEP = ["OD_KEY", "거주동 코드", "거주동 이름", "근무동 코드", "근무동 이름",
           "목적지_순위", "출근_이동량", "거주동_전체_출근량", "목적지_출근비중",
           "누적_출근비중", "선택목적지_출근량합", "최종_가중치",
           "평균_이동시간_분", "평균_이동거리_m", "내부통근여부"]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--od", default=OD_CSV)
    ap.add_argument("--old", default=OLD_CSV)
    ap.add_argument("--new", default=NEW_CSV)
    ap.add_argument("--out", default=OUT_CSV)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    section("[1단계] 입력 확인")
    for lb, p in [("OD", args.od), ("기존", args.old), ("재선택본", args.new)]:
        ok = Path(p).exists()
        log(f"  {lb:8s} {p}  {'OK' if ok else '(없음)'}")
        if not ok:
            return

    od = read_csv_any(args.od)
    old = read_csv_any(args.old)
    new = read_csv_any(args.new)
    od.columns = [c.strip() for c in od.columns]
    old.columns = [c.strip() for c in old.columns]
    new.columns = [c.strip() for c in new.columns]
    log(f"\n  OD {len(od):,}행 / 기존 {len(old):,}행 / 재선택본 {len(new):,}행")

    # OD 에 OD_KEY 가 없으면 만든다 (재조회 때와 같은 규칙)
    if "OD_KEY" not in od.columns:
        od["OD_KEY"] = (od["거주동 코드"].astype(str).str.strip()
                        + "_" + od["근무동 코드"].astype(str).str.strip())
        log("  OD_KEY 를 '거주동_근무동'으로 생성했다")

    target_cols = list(old.columns)
    log(f"  목표 형식: {len(target_cols)}컬럼")

    # OD_KEY 가 중복이면 결합에서 행이 폭증한다. 먼저 막는다.
    for lb, df in [("OD", od), ("기존", old), ("재선택본", new)]:
        if "OD_KEY" not in df.columns:
            continue
        dup = int(df["OD_KEY"].duplicated().sum())
        if dup:
            log(f"  [주의] {lb} OD_KEY 중복 {dup:,}건 -> 첫 행만 남긴다")
            df.drop_duplicates(subset="OD_KEY", keep="first", inplace=True)

    section("[2단계] 결합")

    # 내부통근 판정
    inner_col = "내부통근여부" if "내부통근여부" in od.columns else None
    if inner_col:
        is_inner = od[inner_col].astype(str).str.lower().isin(["true", "1", "y"])
    else:
        is_inner = od["거주동 코드"].astype(str) == od["근무동 코드"].astype(str)
    log(f"  내부통근 {int(is_inner.sum()):,}건 (API 대상 아님, 기존 값 승계)")

    base = od[[c for c in OD_KEEP if c in od.columns]].copy()

    new2 = new.rename(columns=RENAME)
    keep_new = ["OD_KEY"] + [v for v in RENAME.values() if v in new2.columns]
    merged = base.merge(new2[keep_new], on="OD_KEY", how="left", suffixes=("", "_새값"))

    if len(merged) != len(base):
        log(f"  [중단] 결합 후 행수가 변했다: {len(base):,} -> {len(merged):,}")
        log("         OD_KEY 중복을 확인해라.")
        return
    n_new = merged["분석용_편도시간_분"].notna().sum()
    log(f"  재조회로 채워진 행: {n_new:,}건")

    # 내부통근 + 재조회 실패분은 기존 값에서 승계
    old_idx = old.drop_duplicates(subset="OD_KEY", keep="first").set_index("OD_KEY")
    fill_cols = [c for c in target_cols if c not in base.columns]
    need = merged["분석용_편도시간_분"].isna()
    log(f"  기존 값 승계 대상: {int(need.sum()):,}건 (내부통근 + 경로없음)")

    for c in fill_cols:
        if c not in merged.columns:
            merged[c] = pd.NA
        if c not in old_idx.columns:
            continue
        # 기존 열의 dtype 이 문자열이면 숫자 대입에서 TypeError 가 난다.
        # object 로 올려서 안전하게 채운다.
        merged[c] = merged[c].astype("object")
        src = merged.loc[need, "OD_KEY"].map(old_idx[c])
        merged.loc[need, c] = src.values

    # 메타 컬럼 갱신
    for c in ["요금산출방식", "최종경로유형", "경로값_산출방식"]:
        if c in merged.columns:
            merged[c] = merged[c].astype("object")
    merged.loc[~need, "요금산출방식"] = "TMAP_재조회_08시"
    merged.loc[~need, "최종경로유형"] = "대중교통"
    merged.loc[~need, "경로값_산출방식"] = "TMAP_재조회_대표경로선택_v2"
    merged["경로정보존재여부"] = merged["분석용_편도시간_분"].notna().astype(int)
    merged["요금정보존재여부"] = merged["분석용_편도요금_원"].notna().astype(int)

    # 격리 — 경로도 없고 기존 값도 없는 행
    no_route = merged["분석용_편도시간_분"].isna() & ~is_inner.values
    quar = merged[no_route]
    keep = merged[~no_route]
    log(f"\n  격리(경로없음): {len(quar):,}건")
    log(f"  최종 유지: {len(keep):,}건")

    out = keep.reindex(columns=target_cols)

    section("[3단계] 검증")
    miss = [c for c in target_cols if c not in merged.columns]
    log(f"  누락 컬럼: {miss if miss else '없음'}")
    log(f"  결측 현황")
    for c in ["분석용_편도시간_분", "분석용_편도요금_원", "환승횟수", "이용노선"]:
        if c in out.columns:
            log(f"    {c:<22} 결측 {int(out[c].isna().sum()):>6,}")

    both = out.merge(old[["OD_KEY", "분석용_편도시간_분"]].rename(
        columns={"분석용_편도시간_분": "구값"}), on="OD_KEY", how="inner")
    both = both.dropna(subset=["분석용_편도시간_분", "구값"])
    if len(both):
        diff = both["분석용_편도시간_분"] - both["구값"]
        log(f"\n  구값 대비 편도시간 변화 (n={len(both):,})")
        log(f"    평균 {diff.mean():+.2f}분 / 중앙 {diff.median():+.2f}분")
        log(f"    최대 {diff.max():+.1f} / 최소 {diff.min():+.1f}")
        log(f"    5분 이상 변한 행: {int((diff.abs() >= 5).sum()):,}건 "
            f"({(diff.abs() >= 5).mean()*100:.1f}%)")

    night = out["이용노선"].astype(str).str.contains(r"N\d{2}", na=False)
    nosub = pd.to_numeric(out["지하철_이용구간수"], errors="coerce").fillna(0) == 0
    log(f"\n  심야버스 {int(night.sum()):,}건 / 지하철 미사용 {int(nosub.sum()):,}건 "
        f"({nosub.mean()*100:.1f}%)")

    if args.dry_run:
        section("dry-run 종료")
        log("  파일을 쓰지 않았다. 결과가 타당하면 --dry-run 없이 실행해라.")
        return

    # 기존 파일 백업 후 교체
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    bak = Path(args.old).with_name(f"commute_routes_analysis_ready_{stamp}.bak.csv")
    shutil.copy(args.old, bak)
    out.to_csv(args.out, index=False, encoding="utf-8-sig")
    Path(QUAR_CSV).parent.mkdir(parents=True, exist_ok=True)
    quar.to_csv(QUAR_CSV, index=False, encoding="utf-8-sig")

    section("완료")
    log(f"  백업: {bak}")
    log(f"  저장: {args.out}  ({len(out):,}행 {len(out.columns)}컬럼)")
    log(f"  격리: {QUAR_CSV}  ({len(quar):,}행)")
    log()
    log("  다음: python src/db/load_to_db.py 로 재적재")


if __name__ == "__main__":
    main()