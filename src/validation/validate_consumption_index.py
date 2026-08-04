"""
생활소비부담지수 타당성 검증.

행정동 단위 외부 소비물가 통계가 없어 외적 대조 대신 두 축으로 검증한다.
  1. 판별 타당성 - 표면주거비와 다른 것을 측정하는가
  2. 업무지구 편향 - 상권 매출에 섞인 직장인·방문객 소비가 지수를 끌어올리는가

편향 판정에는 청년 생활인구 지표를 쓴다. 주야간 인구비가 높고 주간 순유입이
양수면 업무 중심 행정동으로 본다(기획안 7-1과 동일 기준).

입력: data/표면주거비_생활소비부담지수_결합.csv
      data/2023_2025_행정동별_청년생활인구_지표.csv
출력: data/지수검증_행정동별.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr, mannwhitneyu

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

MERGED_PATH = DATA_DIR / "표면주거비_생활소비부담지수_결합.csv"
POP_PATH = DATA_DIR / "2023~2025_행정동별_청년생활인구_지표.csv"
OUT_PATH = DATA_DIR / "지수검증_행정동별.csv"

INDEX_COL = "생활소비부담지수"
ALL_AGE_COL = "생활소비부담지수_전연령"
COST_COL = "표면주거비_중앙값"


def load_data() -> pd.DataFrame:
    for p in (MERGED_PATH, POP_PATH):
        if not p.exists():
            sys.exit(f"{p} 이 없습니다.")

    idx = pd.read_csv(MERGED_PATH, encoding="utf-8-sig")
    pop = pd.read_csv(POP_PATH, encoding="utf-8-sig")

    # 결합 파일은 10자리 KIKmix 코드, 생활인구는 8자리 통계청 코드
    idx["code8"] = (pd.to_numeric(idx["행정동코드_최종"], errors="coerce")
                    .astype("Int64").astype(str).str.zfill(10).str[:8])
    pop["code8"] = pop["행정동코드"].astype(str).str.zfill(8)

    keep = ["code8", "주야간_인구비", "주간_순유입_규모", "평일_집중도", "출근_유입_변화율"]
    df = idx.merge(pop[[c for c in keep if c in pop.columns]], on="code8", how="inner")
    print(f"결합: {len(df)}행 (지표 {len(idx)} / 생활인구 {len(pop)})")

    valid = df[(~df["업종부족"]) & (~df["표본부족"])].dropna(subset=[INDEX_COL, COST_COL])
    print(f"유효 표본(업종부족·표본부족 제외): {len(valid)}행\n")
    return valid.copy()


def check_discriminant(df: pd.DataFrame) -> pd.DataFrame:
    print("=" * 60)
    print("1. 판별 타당성 - 표면주거비와 다른 것을 측정하는가")
    print("=" * 60)
    rho, p_rho = spearmanr(df[COST_COL], df[INDEX_COL])
    r, _ = pearsonr(df[COST_COL], df[INDEX_COL])
    print(f"스피어만 {rho:.3f} (p={p_rho:.2e}) / 피어슨 {r:.3f} / r² {r**2:.3f}")
    print(f"지수 변동의 {(1 - r**2) * 100:.0f}%는 주거비로 설명되지 않음")

    mh, mi = df[COST_COL].median(), df[INDEX_COL].median()
    df["유형"] = np.select(
        [(df[COST_COL] >= mh) & (df[INDEX_COL] >= mi),
         (df[COST_COL] < mh) & (df[INDEX_COL] >= mi),
         (df[COST_COL] >= mh) & (df[INDEX_COL] < mi)],
        ["고주거비·고소비", "저주거비·고소비", "고주거비·저소비"],
        default="저주거비·저소비",
    )
    print("\n사분면 분포(중앙값 기준):")
    print(df["유형"].value_counts().to_string())
    mismatch = df["유형"].isin(["저주거비·고소비", "고주거비·저소비"]).mean()
    print(f"불일치 사분면 비중: {mismatch * 100:.1f}%")

    cols = ["시군구명", "행정동명_최종", COST_COL, INDEX_COL]
    print("\n[저주거비·고소비] 상위 8")
    print(df[df["유형"] == "저주거비·고소비"].nlargest(8, INDEX_COL)[cols].round(2).to_string(index=False))
    print("\n[고주거비·저소비] 상위 8")
    print(df[df["유형"] == "고주거비·저소비"].nsmallest(8, INDEX_COL)[cols].round(2).to_string(index=False))
    return df


def check_workplace_bias(df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("2. 업무지구 편향")
    print("=" * 60)

    targets = [INDEX_COL] + ([ALL_AGE_COL] if ALL_AGE_COL in df.columns else [])
    for col in targets:
        line = []
        for pop_col in ["주야간_인구비", "주간_순유입_규모", "평일_집중도", "출근_유입_변화율"]:
            if pop_col in df.columns:
                rho, _ = spearmanr(df[col], df[pop_col], nan_policy="omit")
                line.append(f"{pop_col} {rho:+.3f}")
        print(f"  {col}: " + " / ".join(line))

    df["업무중심"] = (df["주야간_인구비"] > 1) & (df["주간_순유입_규모"] > 0)
    hi, lo = df[df["업무중심"]][INDEX_COL], df[~df["업무중심"]][INDEX_COL]
    u, p = mannwhitneyu(hi, lo, alternative="greater")
    rbc = abs(1 - 2 * u / (len(hi) * len(lo)))
    print(f"\n업무중심 {len(hi)}개(중앙값 {hi.median():.3f}) vs 주거형 {len(lo)}개({lo.median():.3f})")
    print(f"Mann-Whitney p={p:.2e}, rank-biserial={rbc:.3f}")

    df["주거비_분위"] = pd.qcut(df[COST_COL], 4, labels=["Q1저", "Q2", "Q3", "Q4고"])
    print("\n주거비 분위별 (업무중심 / 주거형 / 차이):")
    for q in ["Q1저", "Q2", "Q3", "Q4고"]:
        s = df[df["주거비_분위"] == q]
        a, b = s[s["업무중심"]][INDEX_COL], s[~s["업무중심"]][INDEX_COL]
        if len(a) > 2 and len(b) > 2:
            print(f"  {q}: {a.median():+.3f}(n={len(a)}) / {b.median():+.3f}(n={len(b)}) "
                  f"/ {a.median() - b.median():+.3f}")

    top20 = df.nlargest(20, INDEX_COL)
    print(f"\n지수 상위 20개 중 업무중심: {top20['업무중심'].sum()}개")
    return df


def check_rank_gap(df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("3. 두 지표 순위 괴리")
    print("=" * 60)
    df["순위_주거비"] = df[COST_COL].rank(ascending=False)
    df["순위_지수"] = df[INDEX_COL].rank(ascending=False)
    df["순위차"] = df["순위_주거비"] - df["순위_지수"]

    out = df.reindex(df["순위차"].abs().sort_values(ascending=False).index).head(10)
    cols = ["시군구명", "행정동명_최종", COST_COL, INDEX_COL, "순위_주거비", "순위_지수", "순위차", "주야간_인구비"]
    print(out[cols].round(1).to_string(index=False))
    return df


def main():
    df = load_data()
    df = check_discriminant(df)
    df = check_workplace_bias(df)
    df = check_rank_gap(df)

    cols = ["시군구명", "행정동명_최종", COST_COL, INDEX_COL]
    if ALL_AGE_COL in df.columns:
        cols.append(ALL_AGE_COL)
    cols += ["유형", "주야간_인구비", "업무중심", "순위_주거비", "순위_지수", "순위차", "반영업종수", "표본수"]
    df[[c for c in cols if c in df.columns]].round(3).to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_PATH}")


if __name__ == "__main__":
    main()