"""
표면주거비 행정동 배정방식 비중 집계

목적
    전월세 거래를 행정동에 배정할 때 3단계 우선순위를 썼다.

        1순위  법정동 + 지번 정밀   (연립다세대 · 오피스텔)
        2순위  도로명 근사          (단독다가구는 지번 마스킹으로 여기밖에 못 씀)
        3순위  텍스트 매칭 추정

    2·3순위는 하나의 도로 전체에 결과 하나를 복사하는 방식이라
    행정동 경계 근처 거래가 잘못 분류될 위험이 남는다.
    이 위험은 src/preprocessing/README.md 에 한계로 기록돼 있으나
    "얼마나"가 정량화돼 있지 않고, 특히 동별 편차가 보이지 않는다.

    이 스크립트는 동별로 배정방식 비중을 집계해
    서비스의 low_confidence 라벨 기준을 정하는 근거를 만든다.

산출
    docs/표면주거비_배정방식_동별.csv
    콘솔에 임계값별 해당 동 수와 권고안

사용법
    프로젝트 루트에서
    python src/analysis/aggregate_assign_method.py

    경로가 다르면
    python src/analysis/aggregate_assign_method.py C:\\MULTICAM_PROJECT
"""

import re
import sys
from pathlib import Path

import pandas as pd

ENCODINGS = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]

# 표면주거비 산출에 실제로 쓰인 거래단위 파일 후보 (앞쪽이 우선)
TX_CANDIDATES = [
    "표면주거비_거래단위",
    "표면주거비_행정동_통합",
    "전월세_실거래가_통합_행정동_보정",
    "전월세_실거래가_통합",
]
COVERAGE_NAME = "행정동_소스별_커버리지"
BURDEN_NAME = "주거통근_통합부담_행정동별"

CODE_PAT = re.compile(r"(행정동코드|dong_?code|adm_?cd)", re.I)
NAME_PAT = re.compile(r"(행정동명|dong_?name)", re.I)
RENT_PAT = re.compile(r"(표면주거비|월환산|monthly_rent)", re.I)
TYPE_PAT = re.compile(r"(주택유형|건물용도|housing_?type|건물유형)", re.I)
METHOD_PAT = re.compile(r"(매칭|배정|보정|해석|resolve|method|출처|우선순위|tier|방식|단계|source)", re.I)
COV_PAT = re.compile(r"(커버리지|coverage)", re.I)

# 배정방식 값 -> 순위 정규화
TIER1 = re.compile(r"(지번|본번|부번|정밀|precise|jubun)", re.I)
TIER2 = re.compile(r"(도로명|road|ambiguous|근사)", re.I)
TIER3 = re.compile(r"(텍스트|추정|fallback|이름|name|guess)", re.I)

THRESHOLDS = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]


def log(m=""):
    print(m, flush=True)


def section(t):
    log()
    log("=" * 70)
    log(t)
    log("=" * 70)


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
    raise RuntimeError(f"{path.name} 읽기 실패: {last}")


def find_one(root, pattern):
    hits = [p for p in root.rglob(pattern) if p.is_file()
            and not any(x in {".git", "__pycache__", "web", "flask_sample"} for x in p.parts)]
    hits.sort(key=lambda p: len(str(p)))
    return hits[0] if hits else None


def pick(cols, pat):
    for c in cols:
        if pat.search(str(c)):
            return c
    return None


def to_tier(v):
    s = str(v)
    if TIER1.search(s):
        return "1순위_지번정밀"
    if TIER2.search(s):
        return "2순위_도로명근사"
    if TIER3.search(s):
        return "3순위_텍스트추정"
    return "미분류"


# ─────────────────────────────────────────────────────────────

def step1_locate(root):
    section("[1단계] 거래단위 파일 탐색")

    found = []
    for key in TX_CANDIDATES:
        p = find_one(root, f"*{key}*.csv")
        if p:
            found.append((key, p))

    if not found:
        log("  거래단위 CSV를 찾지 못했다. 루트 경로를 인자로 넘겨라.")
        return None

    log("  후보")
    chosen = None
    for key, p in found:
        head = read_csv_any(p, nrows=3, dtype=str)
        code_c = pick(head.columns, CODE_PAT)
        rent_c = pick(head.columns, RENT_PAT)
        meth_c = pick(head.columns, METHOD_PAT)
        type_c = pick(head.columns, TYPE_PAT)
        ok = code_c is not None
        log(f"    - {key}")
        log(f"        경로   : {p}")
        log(f"        컬럼수 : {len(head.columns)}")
        log(f"        코드   : {code_c} / 표면주거비: {rent_c} / 배정방식: {meth_c} / 주택유형: {type_c}")
        if ok and chosen is None:
            chosen = (p, code_c, rent_c, meth_c, type_c)

    if chosen is None:
        log("\n  행정동코드 컬럼을 가진 파일이 없다. 전체 컬럼을 확인해라.")
        for key, p in found:
            head = read_csv_any(p, nrows=1, dtype=str)
            log(f"\n    [{key}]\n      {list(head.columns)}")
        return None

    log(f"\n  >>> 채택: {chosen[0].name}")
    return chosen


def step2_load(chosen):
    section("[2단계] 배정방식 컬럼 확인")

    path, code_c, rent_c, meth_c, type_c = chosen
    use = [c for c in [code_c, rent_c, meth_c, type_c] if c]
    df = read_csv_any(path, usecols=use, dtype=str)
    log(f"  {len(df):,}행 로드")

    df["_code"] = df[code_c].astype(str).str.strip().str[:8]
    df = df[df["_code"].str.len() == 8]
    log(f"  8자리 행정동코드 유효: {len(df):,}행")

    if meth_c:
        log(f"\n  배정방식 컬럼: '{meth_c}'")
        vc = df[meth_c].fillna("(빈값)").value_counts()
        log("  원본 값 분포")
        for v, n in vc.items():
            log(f"    {str(v)[:40]:42s} {n:>9,}  ({n / len(df) * 100:5.1f}%)")
        df["_tier"] = df[meth_c].map(to_tier)
        unmapped = df.loc[df["_tier"] == "미분류", meth_c].value_counts()
        if len(unmapped):
            log("\n  [주의] 순위로 분류하지 못한 값")
            for v, n in unmapped.items():
                log(f"    {str(v)[:40]:42s} {n:>9,}")
            log("    TIER1/TIER2/TIER3 정규식 보완이 필요할 수 있다.")
    elif type_c:
        log("\n  [대체] 배정방식 컬럼이 없어 주택유형으로 추정한다.")
        log("         단독다가구는 국토부 지번 마스킹으로 1순위를 못 쓰므로")
        log("         도로명 근사 전용으로 간주한다.")
        vc = df[type_c].fillna("(빈값)").value_counts()
        log("  주택유형 분포")
        for v, n in vc.items():
            log(f"    {str(v)[:40]:42s} {n:>9,}  ({n / len(df) * 100:5.1f}%)")
        is_single = df[type_c].astype(str).str.contains("단독|다가구", na=False)
        df["_tier"] = pd.Series("1순위_지번정밀", index=df.index).mask(is_single, "2순위_도로명근사")
    else:
        log("\n  배정방식도 주택유형도 없다. 집계 불가.")
        return None, None

    return df, type_c


def step3_aggregate(df, type_c, root):
    section("[3단계] 동별 집계")

    piv = df.pivot_table(index="_code", columns="_tier", values=df.columns[0],
                         aggfunc="count", fill_value=0)
    piv.columns.name = None
    for c in ["1순위_지번정밀", "2순위_도로명근사", "3순위_텍스트추정", "미분류"]:
        if c not in piv.columns:
            piv[c] = 0

    piv["총거래수"] = piv[["1순위_지번정밀", "2순위_도로명근사", "3순위_텍스트추정", "미분류"]].sum(axis=1)
    piv["근사배정_건수"] = piv["2순위_도로명근사"] + piv["3순위_텍스트추정"]
    piv["근사배정_비중"] = (piv["근사배정_건수"] / piv["총거래수"]).round(4)

    if type_c and type_c in df.columns:
        single = df[df[type_c].astype(str).str.contains("단독|다가구", na=False)]
        cnt = single.groupby("_code").size()
        piv["단독다가구_건수"] = piv.index.map(cnt).fillna(0).astype(int)
        piv["단독다가구_비중"] = (piv["단독다가구_건수"] / piv["총거래수"]).round(4)

    piv = piv.reset_index().rename(columns={"_code": "행정동코드"})

    # 행정동명·커버리지 붙이기
    cov_p = find_one(root, f"*{COVERAGE_NAME}*.csv")
    if cov_p:
        cov = read_csv_any(cov_p, dtype=str)
        cc = pick(cov.columns, CODE_PAT)
        cn = pick(cov.columns, NAME_PAT)
        gu = next((c for c in cov.columns if "자치구" in c), None)
        if cc:
            cov["_c"] = cov[cc].astype(str).str.strip().str[:8]
            keep = ["_c"] + [c for c in [cn, gu] if c]
            piv = piv.merge(cov[keep].rename(columns={"_c": "행정동코드"}),
                            on="행정동코드", how="left")

    # 교통비 커버리지 플래그 붙이기
    bur_p = find_one(root, f"*{BURDEN_NAME}*.csv")
    if bur_p:
        bur = read_csv_any(bur_p, dtype=str)
        bc = pick(bur.columns, CODE_PAT)
        cov_c = pick(bur.columns, COV_PAT)
        if bc and cov_c:
            bur["_c"] = bur[bc].astype(str).str.strip().str[:8]
            bur["_cov"] = pd.to_numeric(bur[cov_c], errors="coerce")
            piv = piv.merge(bur[["_c", "_cov"]].rename(
                columns={"_c": "행정동코드", "_cov": "교통비_커버리지"}), on="행정동코드", how="left")
            log(f"  교통비 커버리지 병합 완료 (컬럼 '{cov_c}')")

    log(f"  집계 대상 행정동 {len(piv)}개")
    log()
    log("  근사배정 비중 분포")
    d = piv["근사배정_비중"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99])
    for k in ["min", "50%", "75%", "90%", "95%", "99%", "max"]:
        log(f"    {k:>4s} : {d[k]:.3f}")

    out = root / "docs" / "표면주거비_배정방식_동별.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    piv.sort_values("근사배정_비중", ascending=False).to_csv(out, index=False, encoding="utf-8-sig")
    log(f"\n  저장: {out}")
    return piv


def step4_threshold(piv):
    section("[4단계] low_confidence 임계값 진단")

    n = len(piv)
    log(f"  전체 {n}개 동 기준, 임계값별 low_confidence 해당 수")
    log()
    log(f"    {'임계값':>8s}  {'해당 동':>7s}  {'비율':>7s}")
    for t in THRESHOLDS:
        k = int((piv["근사배정_비중"] >= t).sum())
        log(f"    {t:>8.0%}  {k:>7d}  {k / n:>6.1%}")

    log()
    log("  상위 15개 동 (근사배정 비중 높은 순)")
    cols = [c for c in ["행정동명", "자치구", "총거래수", "근사배정_건수", "근사배정_비중",
                        "단독다가구_비중", "교통비_커버리지"] if c in piv.columns]
    log(piv.sort_values("근사배정_비중", ascending=False).head(15)[cols].to_string(index=False))

    # 표본 자체가 적은 동은 별도 관리
    small = piv[piv["총거래수"] < 30]
    log()
    log(f"  거래 30건 미만 동: {len(small)}개")
    if len(small):
        log(small.sort_values("총거래수")[cols].head(10).to_string(index=False))

    if "교통비_커버리지" in piv.columns:
        low_cov = piv[piv["교통비_커버리지"] < 0.7]
        log()
        log(f"  교통비 커버리지 0.7 미만: {len(low_cov)}개")
        both = low_cov[low_cov["근사배정_비중"] >= 0.30]
        log(f"    그중 근사배정 30% 이상도 함께 해당: {len(both)}개")
        if len(both):
            log(both[cols].to_string(index=False))

    log()
    log("  임계값 정하는 법")
    log("   - 너무 낮으면 대부분의 동에 '참고용' 라벨이 붙어 경고가 무의미해진다.")
    log("   - 너무 높으면 실제로 부정확한 동이 정상처럼 보인다.")
    log("   - 전체의 10~15% 안쪽이 걸리는 지점을 권한다.")
    log("     교통비 커버리지 미달이 9개(약 2%)이므로, 비슷한 규모면 균형이 맞는다.")
    log("   - 거래 30건 미만 동은 비중과 무관하게 별도 플래그를 권한다.")


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    log(f"프로젝트 루트: {root.resolve()}")

    chosen = step1_locate(root)
    if not chosen:
        return
    df, type_c = step2_load(chosen)
    if df is None:
        return
    piv = step3_aggregate(df, type_c, root)
    step4_threshold(piv)

    section("완료")
    log("  이 결과로 low_confidence 임계값을 확정하면")
    log("  status 4종(ok / ambiguous / no_data / low_confidence) 정의가 끝난다.")


if __name__ == "__main__":
    main()