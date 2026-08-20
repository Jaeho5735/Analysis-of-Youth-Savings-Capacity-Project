"""
도로명 근사 배정 정확도 검증

배경
    표면주거비 거래의 46.6%가 '도로명 근사'로 행정동에 배정됐다.
    이 47%는 '노출률'이지 '오류율'이 아니다. 도로명 근사도 대부분은 맞는다.
    도로가 행정동 경계를 넘을 때만 틀린다.

    그런데 우리는 정답을 아는 거래를 30만 건 갖고 있다.
    그 거래들에 도로명 근사를 일부러 적용해보고 정답과 대조하면
    "위험이 있다"를 "오배정 N%다"로 바꿀 수 있다.

측정 설계
    검증 표본 A - 비분동확정 거래
        법정동이 행정동 하나에만 대응하는 거래.
        정답이 캐시와 무관하게 결정되므로 검증에 쓸 수 있다.

    검증 표본 B - 지번 정밀 거래 (선택)
        분동이 애매한데 지번으로 정밀 해결된 거래.
        '실제로 헷갈리는 구역'의 정확도라 A보다 보수적이고 현실에 가깝다.
        jibun_cache 키 형식을 config에 지정해야 측정된다.

    재가중 추정
        검증 표본과 실제 적용 대상(2순위)의 도로 구성이 다르다.
        도로유형(로/길)별 정확도를 구한 뒤 2순위 모집단 구성비로 재가중한다.

주의
    이 스크립트는 컬럼을 정규식으로 추측하지 않는다.
    앞선 집계 스크립트가 부분문자열 오매칭으로 통째로 틀린 결과를 냈기 때문이다.
    반드시 점검 모드로 실제 구조를 확인하고 config를 채운 뒤 실행한다.

사용법
    1) 점검      python src/analysis/verify_road_accuracy.py
                 -> docs/verify_config.json 템플릿 생성, 구조 덤프 출력
    2) config 작성 (컬럼명을 직접 적는다)
    3) 실행      python src/analysis/verify_road_accuracy.py --run
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ENCODINGS = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]
CONFIG_REL = Path("docs") / "verify_config.json"

CONFIG_TEMPLATE = {
    "_설명": "값이 null 인 항목을 실제 컬럼명으로 채운 뒤 --run 으로 실행한다.",
    "tx_csv": None,
    "kakao_cache": None,
    "jibun_cache": None,
    "bjd_xlsx": None,

    "_거래파일_컬럼": "아래 4개는 필수",
    "col_dong_code_final": None,
    "col_bjd_name": None,
    "col_road_name": None,
    "col_sigungu": None,

    "_선택": "없으면 null 로 두면 된다",
    "col_sido": None,
    "col_housing_type": None,
    "col_dong_name_final": None,

    "_캐시": "kakao_cache 키 형식",
    "kakao_key_sep": "|||",
    "kakao_key_order": ["sido", "sigungu", "road"],
    "kakao_default_sido": "서울특별시",

    "_표본B": "지번 정밀 거래를 식별할 수 있으면 채운다. 못 하면 null 로 두고 표본 A만 쓴다",
    "col_jibun_key": None,
}


def log(m=""):
    print(m, flush=True)


def section(t):
    log()
    log("=" * 72)
    log(t)
    log("=" * 72)


def read_csv_any(path, **kw):
    last = None
    for enc in ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError as e:
            last = e
        except Exception as e:
            last = e
            break
    raise RuntimeError(f"{Path(path).name} 읽기 실패: {last}")


def find_one(root, pattern):
    hits = [p for p in root.rglob(pattern) if p.is_file()
            and not any(x in {".git", "__pycache__", "web", "flask_sample"} for x in p.parts)]
    hits.sort(key=lambda p: len(str(p)))
    return hits[0] if hits else None


def road_type(road):
    """도로 유형. 간선급(로)과 지선급(길)은 경계를 넘을 확률이 다르다."""
    s = str(road).strip()
    if re.search(r"길\d*$", s):
        return "길"
    if re.search(r"로\d*$", s):
        return "로"
    return "기타"


# ═════════════════════════════════════════════════════════════
# 점검 모드
# ═════════════════════════════════════════════════════════════

def inspect(root):
    section("[점검] 파일 탐색")

    tx = find_one(root, "*표면주거비_거래단위*.csv")
    kakao = find_one(root, "*kakao_cache*.json")
    jibun = find_one(root, "*jibun_cache*.json")
    xlsx = find_one(root, "*법정동*행정동*코드*.xlsx")

    for label, p in [("거래단위 CSV", tx), ("kakao_cache", kakao),
                     ("jibun_cache", jibun), ("법정동 xlsx", xlsx)]:
        log(f"  {label:14s} : {p if p else '(못 찾음)'}")

    if tx:
        section("[점검] 거래단위 CSV 전체 컬럼")
        head = read_csv_any(tx, nrows=200, dtype=str)
        log(f"  컬럼 {len(head.columns)}개\n")
        for i, c in enumerate(head.columns):
            s = head[c].dropna()
            nuniq = s.nunique()
            samples = " | ".join(str(x)[:26] for x in s.unique()[:3])
            log(f"   {i:>3d}  {str(c)[:34]:36s} 고유{nuniq:>5d}  {samples}")

        log()
        log("  ── 채워야 할 항목과 고르는 법 ──")
        log("   col_dong_code_final : 보정이 끝난 최종 행정동코드.")
        log("                         '_최종' 같은 접미사가 붙은 쪽이다.")
        log("                         고유값이 420 근처면 맞고, 215 근처면 보정 전 임시값이다.")
        log("   col_bjd_name        : 법정동명 (예: 상계동, 반포동)")
        log("   col_road_name       : 도로명 (예: 노해로, 신반포로)")
        log("   col_sigungu         : 자치구명 (예: 노원구)")
        log("   col_housing_type    : 주택유형 (단독다가구 / 연립다세대 / 오피스텔)")

    if kakao:
        section("[점검] kakao_cache 구조")
        with open(kakao, encoding="utf-8") as f:
            raw = json.load(f)
        log(f"  타입 {type(raw).__name__} / 항목 {len(raw):,}개")
        if isinstance(raw, dict):
            for k in list(raw.keys())[:5]:
                log(f"    {k!r}  ->  {raw[k]!r}")
            sep_guess = "|||" if "|||" in next(iter(raw)) else "(확인 필요)"
            log(f"\n  구분자 추정: {sep_guess}")
            parts = next(iter(raw)).split("|||")
            log(f"  키 조각 수: {len(parts)}  -> {parts}")
            log("  이 순서를 config 의 kakao_key_order 에 반영해라.")

    if jibun:
        section("[점검] jibun_cache 구조")
        with open(jibun, encoding="utf-8") as f:
            raw = json.load(f)
        log(f"  타입 {type(raw).__name__} / 항목 {len(raw):,}개")
        if isinstance(raw, dict):
            for k in list(raw.keys())[:5]:
                log(f"    {k!r}  ->  {raw[k]!r}")
            log("\n  표본 B(지번 정밀)를 쓰려면 거래 행에서 이 키를 만들 수 있어야 한다.")
            log("  가능하면 col_jibun_key 에 그 키가 이미 들어있는 컬럼명을 적어라.")
            log("  만들 수 없으면 null 로 두고 표본 A만 쓴다. 결과는 여전히 유효하다.")

    cfg_path = root / CONFIG_REL
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if cfg_path.exists():
        log(f"\n  config 이미 있음: {cfg_path} (덮어쓰지 않음)")
    else:
        tpl = dict(CONFIG_TEMPLATE)
        tpl["tx_csv"] = str(tx) if tx else None
        tpl["kakao_cache"] = str(kakao) if kakao else None
        tpl["jibun_cache"] = str(jibun) if jibun else None
        tpl["bjd_xlsx"] = str(xlsx) if xlsx else None
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(tpl, f, ensure_ascii=False, indent=2)
        log(f"\n  config 템플릿 생성: {cfg_path}")

    section("다음")
    log("  위 컬럼 목록을 보고 config 의 null 을 채운 뒤")
    log("  python src/analysis/verify_road_accuracy.py --run")


# ═════════════════════════════════════════════════════════════
# 실행 모드
# ═════════════════════════════════════════════════════════════

def load_bjd_map(xlsx_path):
    """법정동코드 -> 행정동 개수. 1이면 비분동확정(표본 A)."""
    df = pd.read_excel(xlsx_path, dtype=str)
    sido_c = next((c for c in df.columns if "시도명" in c), None)
    live_c = next((c for c in df.columns if "말소" in c), None)
    bjd_c = next((c for c in df.columns if "법정동코드" in c), None)
    hjd_c = next((c for c in df.columns if "행정동코드" in c), None)
    dong_c = next((c for c in df.columns if "동리명" in c), None)
    gu_c = next((c for c in df.columns if "시군구명" in c), None)
    if not all([sido_c, bjd_c, hjd_c, dong_c, gu_c]):
        raise RuntimeError(f"xlsx 컬럼 확인 필요: {list(df.columns)}")

    df = df[df[sido_c].astype(str).str.contains("서울", na=False)]
    if live_c:
        df = df[df[live_c].isna() | (df[live_c].astype(str).str.strip() == "")]

    cnt = df.groupby([gu_c, dong_c])[hjd_c].nunique()
    return {(str(g).strip(), str(d).strip()): int(n) for (g, d), n in cnt.items()}


def run(root):
    cfg_path = root / CONFIG_REL
    if not cfg_path.exists():
        log(f"config 가 없다. 먼저 점검 모드로 실행해라.\n  {cfg_path}")
        return
    cfg = json.load(open(cfg_path, encoding="utf-8"))

    required = ["tx_csv", "kakao_cache", "bjd_xlsx",
                "col_dong_code_final", "col_bjd_name", "col_road_name", "col_sigungu"]
    miss = [k for k in required if not cfg.get(k)]
    if miss:
        log("config 에 아직 안 채운 필수 항목이 있다:")
        for k in miss:
            log(f"  - {k}")
        return

    section("[1단계] 데이터 로드")

    use = [cfg[k] for k in ["col_dong_code_final", "col_bjd_name", "col_road_name", "col_sigungu"]]
    for k in ["col_housing_type", "col_sido", "col_jibun_key", "col_dong_name_final"]:
        if cfg.get(k):
            use.append(cfg[k])
    tx = read_csv_any(cfg["tx_csv"], usecols=list(dict.fromkeys(use)), dtype=str)
    log(f"  거래 {len(tx):,}행")

    tx["_truth"] = tx[cfg["col_dong_code_final"]].astype(str).str.strip().str[:8]
    tx = tx[tx["_truth"].str.len() == 8]
    log(f"  최종코드 유효 {len(tx):,}행 / 고유 행정동 {tx['_truth'].nunique()}개")
    if tx["_truth"].nunique() < 400:
        log("  [경고] 고유 행정동이 400개 미만이다. 보정 전 임시 코드 컬럼일 수 있다.")
        log("         config 의 col_dong_code_final 을 다시 확인해라.")

    with open(cfg["kakao_cache"], encoding="utf-8") as f:
        kakao = json.load(f)
    log(f"  kakao_cache {len(kakao):,}건")

    bjd_cnt = load_bjd_map(cfg["bjd_xlsx"])
    log(f"  법정동-행정동 관계 {len(bjd_cnt):,}건")

    section("[2단계] 도로명 근사 예측 재현")

    sep = cfg.get("kakao_key_sep", "|||")
    order = cfg.get("kakao_key_order", ["sido", "sigungu", "road"])
    default_sido = cfg.get("kakao_default_sido", "서울특별시")

    def make_key(row):
        part = {
            "sido": str(row[cfg["col_sido"]]).strip() if cfg.get("col_sido") else default_sido,
            "sigungu": str(row[cfg["col_sigungu"]]).strip(),
            "road": str(row[cfg["col_road_name"]]).strip(),
        }
        return sep.join(part[o] for o in order)

    tx["_key"] = tx.apply(make_key, axis=1)
    tx["_pred_name"] = tx["_key"].map(lambda k: kakao.get(k))
    hit = tx["_pred_name"].notna()
    log(f"  캐시 적중 {int(hit.sum()):,}행 ({hit.mean():.1%})")
    if hit.mean() < 0.5:
        log("  [경고] 적중률이 낮다. kakao_key_order 나 구분자를 확인해라.")
        log(f"         생성 키 예시: {tx['_key'].iloc[0]!r}")
        log(f"         캐시 키 예시: {next(iter(kakao))!r}")
        return

    # 정답 행정동명
    name_col = cfg.get("col_dong_name_final")
    if name_col:
        tx["_truth_name"] = tx[name_col].astype(str).str.strip()
    else:
        cov = find_one(root, "*행정동_소스별_커버리지*.csv")
        if not cov:
            log("  행정동명을 얻을 수 없다. col_dong_name_final 을 채워라.")
            return
        c = read_csv_any(cov, dtype=str)
        cc = next(x for x in c.columns if "코드" in x)
        cn = next(x for x in c.columns if "행정동명" in x)
        m = dict(zip(c[cc].astype(str).str[:8], c[cn]))
        tx["_truth_name"] = tx["_truth"].map(m)

    def norm(s):
        return re.sub(r"[·.\s]", "", re.sub(r"제(\d+)", r"\1", str(s)))

    tx = tx[hit & tx["_truth_name"].notna()].copy()
    tx["_correct"] = tx["_pred_name"].map(norm) == tx["_truth_name"].map(norm)
    tx["_rtype"] = tx[cfg["col_road_name"]].map(road_type)

    section("[3단계] 검증 표본 분리")

    gu = tx[cfg["col_sigungu"]].astype(str).str.strip()
    bjd = tx[cfg["col_bjd_name"]].astype(str).str.strip()
    tx["_nhjd"] = [bjd_cnt.get((g, b)) for g, b in zip(gu, bjd)]
    tx["_stratum"] = "판정불가"
    tx.loc[tx["_nhjd"] == 1, "_stratum"] = "A_비분동확정"
    tx.loc[tx["_nhjd"].fillna(0) > 1, "_stratum"] = "분동애매"

    if cfg.get("col_jibun_key") and cfg.get("jibun_cache"):
        with open(cfg["jibun_cache"], encoding="utf-8") as f:
            jibun = json.load(f)
        jk = tx[cfg["col_jibun_key"]].astype(str).str.strip()
        isB = (tx["_stratum"] == "분동애매") & jk.isin(jibun.keys())
        tx.loc[isB, "_stratum"] = "B_지번정밀"

    log(tx["_stratum"].value_counts().to_string())

    section("[4단계] 정확도")

    for st in ["A_비분동확정", "B_지번정밀"]:
        sub = tx[tx["_stratum"] == st]
        if len(sub) == 0:
            log(f"\n  {st}: 표본 없음")
            continue
        log(f"\n  ── {st}  n={len(sub):,} ──")
        log(f"     전체 정확도 {sub['_correct'].mean():.1%}")
        log("     도로유형별")
        for rt, g in sub.groupby("_rtype"):
            log(f"       {rt:4s} n={len(g):>8,}  정확도 {g['_correct'].mean():.1%}")

    # 재가중: 2순위 모집단(캐시로만 배정된 거래)의 도로유형 구성비
    section("[5단계] 재가중 추정")

    pop = tx[tx["_stratum"] == "분동애매"]
    if len(pop) and len(tx[tx["_stratum"].str.startswith(("A_", "B_"))]):
        w = pop["_rtype"].value_counts(normalize=True)
        log("  적용 대상(분동애매) 도로유형 구성")
        for rt, p in w.items():
            log(f"    {rt:4s} {p:.1%}")
        for st in ["A_비분동확정", "B_지번정밀"]:
            sub = tx[tx["_stratum"] == st]
            if len(sub) == 0:
                continue
            acc = sub.groupby("_rtype")["_correct"].mean()
            shared = [rt for rt in w.index if rt in acc.index]
            if not shared:
                log(f"\n  {st}: 도로유형이 겹치지 않아 재가중 불가")
                continue
            wsum = sum(w[rt] for rt in shared)
            est = sum(w[rt] / wsum * acc[rt] for rt in shared)
            dropped = [rt for rt in w.index if rt not in acc.index]
            log(f"\n  {st} 기준 재가중 정확도 추정: {est:.1%}")
            if dropped:
                log(f"    (검증표본에 없어 제외한 도로유형: {dropped}, 모집단 비중 {1 - wsum:.1%})")
            log(f"    -> 도로명 근사 노출 46.6% 가정 시 전체 오배정 추정 {(1 - est) * 0.466:.1%}")

    section("[6단계] 동별 정확도")

    base = tx[tx["_stratum"].str.startswith(("A_", "B_"))]
    by = base.groupby("_truth").agg(검증표본수=("_correct", "size"),
                                    정확도=("_correct", "mean")).reset_index()
    by["정확도"] = by["정확도"].round(4)
    by = by.rename(columns={"_truth": "행정동코드"})
    nm = base.drop_duplicates("_truth").set_index("_truth")["_truth_name"]
    by["행정동명"] = by["행정동코드"].map(nm)

    out = root / "docs" / "도로명근사_정확도_동별.csv"
    by.sort_values("정확도").to_csv(out, index=False, encoding="utf-8-sig")
    log(f"  저장: {out}")
    log()
    log("  정확도 하위 15개 (검증표본 30건 이상)")
    log(by[by["검증표본수"] >= 30].sort_values("정확도").head(15).to_string(index=False))

    section("완료")
    log("  이 정확도로 low_confidence 기준을 다시 잡으면 된다.")
    log("  노출률(46.6%)이 아니라 추정 오배정률로 기준을 세우는 쪽이 정직하다.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0]) if args else Path.cwd()
    log(f"프로젝트 루트: {root.resolve()}")
    if "--run" in sys.argv:
        run(root)
    else:
        inspect(root)


if __name__ == "__main__":
    main()