"""
생활소비부담지수 산출.

기반 변수는 청년(20~30대) 매출의 건당 결제금액. 총매출액은 상권 규모·점포 수에
좌우돼 가격 수준을 대표하지 못하고, 전연령 매출은 직장인·방문객 소비가 섞여
업무지구 편향이 생긴다(주야간 인구비 상관 전연령 0.378 vs 청년 0.213).

건당 결제금액은 (행정동, 업종)별 매출금액 합계 ÷ 매출건수 합계. 행별 비율을 먼저
낸 뒤 평균내면 50건짜리 분기와 1만건짜리 분기가 같은 발언권을 갖는다.

집계 키는 (시군구명, 행정동_코드_명). 이름만 쓰면 신사동 같은 동명이인이 섞이고,
행정동_코드까지 넣으면 코드 개편 전후가 같은 동네를 둘로 쪼갠다. 상권분석(8자리)과
KIKmix(10자리)는 앞 5자리 시군구코드만 공유하므로 이걸로 구를 붙인다.

z-score는 median/MAD 기반 계산 후 ±3 클리핑. mean/std는 청담동 같은 극단치가
통계량 자체를 오염시킨다.

입력: data/서울시_상권분석서비스_추정매출-행정동*.csv (2023~2026, 4개)
산출물에는 `행정동_코드`(8자리)를 함께 저장한다. 집계 키는 (구, 동)이지만 후속 결합을
이름으로 하면 "창신제1동" vs "창신1동" 같은 표기 차이로 조용히 누락된다.

출력: data/생활소비부담지수_행정동별.csv, data/표면주거비_생활소비부담지수_결합.csv
"""

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from utils.dong_names import load_official_ref, normalize_dong_name  # noqa: E402

FILE_PATTERN = str(DATA_DIR / "서울시_상권분석서비스_추정매출-행정동*.csv")
SURFACE_COST_POOLED_PATH = DATA_DIR / "표면주거비_행정동_통합.csv"
OFFICIAL_DONG_LIST_PATH = DATA_DIR / "행정동_공식명_목록.csv"
OUT_INDEX = DATA_DIR / "생활소비부담지수_행정동별.csv"
OUT_MERGED = DATA_DIR / "표면주거비_생활소비부담지수_결합.csv"

TARGET_INDUSTRIES = [
    "한식음식점", "중식음식점", "일식음식점", "제과점",
    "분식전문점", "치킨전문점", "패스트푸드점",
    "커피-음료", "슈퍼마켓", "편의점",
]

YOUTH_AMT = ["연령대_20_매출_금액", "연령대_30_매출_금액"]
YOUTH_CNT = ["연령대_20_매출_건수", "연령대_30_매출_건수"]
ALL_AMT = ["당월_매출_금액"]
ALL_CNT = ["당월_매출_건수"]

COUNT_OUTLIER_Q_LOW = 0.05
ZSCORE_CLIP = 3.0
MIN_INDUSTRY_COUNT = 5
DONG_KEY = ["시군구명", "행정동_코드_명"]


def load_sigungu_map(official_ref: pd.DataFrame) -> dict:
    codes = official_ref["행정동코드"].astype(str).str.zfill(10)
    return dict(zip(codes.str[:5], official_ref["시군구명"]))


def load_all_files(official_set: set) -> pd.DataFrame:
    files = sorted(glob.glob(FILE_PATTERN))
    if not files:
        raise FileNotFoundError(f"{FILE_PATTERN} 에 해당하는 파일이 없습니다.")
    print(f"찾은 파일: {len(files)}개")

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, encoding="cp949", low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        print(f"  {Path(f).name}: {len(df)}행, 분기 {sorted(df['기준_년분기_코드'].unique())}")
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    print(f"\n병합 전 총 행 수: {len(combined)}")

    before = len(combined)
    combined = combined.drop_duplicates(subset=["기준_년분기_코드", "행정동_코드", "서비스_업종_코드"])
    print(f"중복 제거 후: {len(combined)}행 (-{before - len(combined)})")

    before_unique = combined["행정동_코드_명"].nunique()
    combined["행정동_코드_명"] = combined["행정동_코드_명"].apply(
        lambda v: normalize_dong_name(v, official_set)
    )
    print(f"행정동명 정규화: 고유 {before_unique}개 -> {combined['행정동_코드_명'].nunique()}개")
    return combined


def zscore_mean_std_clipped(s: pd.Series) -> pd.Series:
    return ((s - s.mean()) / s.std()).clip(-ZSCORE_CLIP, ZSCORE_CLIP)


def zscore_robust_raw(s: pd.Series) -> pd.Series:
    med = s.median()
    mad = (s - med).abs().median()
    if not mad or pd.isna(mad):
        std = s.std()
        if not std or pd.isna(std):
            return pd.Series(0.0, index=s.index)
        return (s - med) / std
    return (s - med) / (1.4826 * mad)


def zscore_robust_clipped(s: pd.Series) -> pd.Series:
    return zscore_robust_raw(s).clip(-ZSCORE_CLIP, ZSCORE_CLIP)


def build_index(sub_df, amt_cols, cnt_cols, label,
                index_col="생활소비부담지수", count_col="반영업종수"):
    """건당 결제금액 기반 지수. 건수 컷오프는 기준마다 분포가 달라 그 안에서 다시 잡는다."""
    work = sub_df.copy()
    work["_금액"] = work[amt_cols].sum(axis=1)
    work["_건수"] = work[cnt_cols].sum(axis=1)

    cutoff = work.loc[work["_건수"] > 0, "_건수"].quantile(COUNT_OUTLIER_Q_LOW)
    before = len(work)
    work = work[work["_건수"] >= max(cutoff, 1)]
    print(f"  [{label}] 건수 하위 {COUNT_OUTLIER_Q_LOW*100:.0f}%(={cutoff:.0f}건) 제거: "
          f"{len(work)}행 (-{before - len(work)})")

    agg = (
        work.groupby(DONG_KEY + ["서비스_업종_코드_명"])
        .agg(매출금액_합=("_금액", "sum"), 매출건수_합=("_건수", "sum"))
        .reset_index()
    )
    zero_denom = (agg["매출건수_합"] <= 0).sum()
    if zero_denom:
        print(f"  [{label}] 건수 합 0인 (동,업종) {zero_denom}건 제외")
    agg = agg[agg["매출건수_합"] > 0]
    agg["건당_결제금액"] = agg["매출금액_합"] / agg["매출건수_합"]
    agg["zscore"] = agg.groupby("서비스_업종_코드_명")["건당_결제금액"].transform(zscore_robust_clipped)

    idx = (
        agg.groupby(DONG_KEY)
        .agg(**{index_col: ("zscore", "mean"), count_col: ("zscore", "count")})
        .reset_index()
    )
    return idx, agg


def compare_rank(df, col_a, col_b, title):
    ok = df.dropna(subset=[col_a, col_b])
    corr = np.corrcoef(ok[col_a], ok[col_b])[0, 1]
    diff = (ok[col_a].rank() - ok[col_b].rank()).abs()
    top_a = set(map(tuple, ok.nlargest(10, col_a)[DONG_KEY].values))
    top_b = set(map(tuple, ok.nlargest(10, col_b)[DONG_KEY].values))
    print(f"\n[검증] {title}: 상관 {corr:.3f}, 순위차 평균 {diff.mean():.1f}/최대 {diff.max():.0f}, "
          f"상위10 겹침 {len(top_a & top_b)}/10")


def main():
    if not OFFICIAL_DONG_LIST_PATH.exists():
        sys.exit(f"{OFFICIAL_DONG_LIST_PATH} 이 없습니다. dong_matcher.py를 먼저 실행하세요.")
    official_ref = load_official_ref(OFFICIAL_DONG_LIST_PATH)
    official_set = set(official_ref["행정동명"])
    sigungu_map = load_sigungu_map(official_ref)

    df = load_all_files(official_set)

    missing = [c for c in YOUTH_AMT + YOUTH_CNT if c not in df.columns]
    if missing:
        sys.exit(f"연령대별 매출 컬럼이 없습니다: {missing}")

    df["행정동_코드"] = pd.to_numeric(df["행정동_코드"], errors="coerce").astype("Int64").astype(str).str.zfill(8)
    df["시군구명"] = df["행정동_코드"].str[:5].map(sigungu_map)
    gu_missing = df["시군구명"].isna().sum()
    if gu_missing:
        print(f"[경고] 시군구 매핑 실패: {gu_missing}행")

    # 파일 간 dedup은 행정동_코드 기준인데 집계 키는 DONG_KEY라 전환기 분기가 이중 카운트될 수 있다
    dup_mask = df.duplicated(subset=["기준_년분기_코드"] + DONG_KEY + ["서비스_업종_코드"], keep=False)
    if dup_mask.sum() > 0:
        print(f"\n[경고] 같은 (분기,구,동,업종)에 코드만 다른 행 {dup_mask.sum()}건:")
        print(
            df.loc[dup_mask, ["기준_년분기_코드"] + DONG_KEY + ["행정동_코드", "서비스_업종_코드_명"]]
            .sort_values(["기준_년분기_코드"] + DONG_KEY).head(20).to_string(index=False)
        )
        before_n = len(df)
        df = df.drop_duplicates(subset=["기준_년분기_코드"] + DONG_KEY + ["서비스_업종_코드"], keep="last")
        print(f"재중복제거: {len(df)}행 (-{before_n - len(df)})")
    else:
        print("\n[진단] 전환기 분기 이중 카운트: 0건")

    df = df[df["서비스_업종_코드_명"].isin(TARGET_INDUSTRIES)].copy()
    print(f"\n타겟 업종({len(TARGET_INDUSTRIES)}개) 필터링 후: {len(df)}행")

    code_per_dong = df.groupby(DONG_KEY)["행정동_코드"].nunique()
    multi_code = code_per_dong[code_per_dong > 1]
    if len(multi_code) > 0:
        print(f"\n행정동코드가 2개 이상인 (구,동) {len(multi_code)}개 (자동 풀링됨):")
        print(multi_code.to_string())

    print("\n[산출]")
    # 집계 키는 (구, 동)이지만 후속 결합은 코드로 해야 표기 차이에 안 걸린다.
    # 같은 (구, 동)에 코드가 여럿이면 개편 전후이므로 최신 코드를 대표로 붙인다.
    code_map = (df.sort_values("기준_년분기_코드")
                .groupby(DONG_KEY)["행정동_코드"].last().rename("행정동_코드").reset_index())

    index_df, agg = build_index(df, YOUTH_AMT, YOUTH_CNT, "청년")
    all_df, _ = build_index(df, ALL_AMT, ALL_CNT, "전연령",
                            index_col="생활소비부담지수_전연령", count_col="반영업종수_전연령")
    index_df["업종부족"] = index_df["반영업종수"] < MIN_INDUSTRY_COUNT
    index_df = index_df.merge(all_df, on=DONG_KEY, how="left")

    compare_rank(index_df, "생활소비부담지수", "생활소비부담지수_전연령", "청년 vs 전연령")
    print(index_df.sort_values("생활소비부담지수", ascending=False).head(10)[
        DONG_KEY + ["생활소비부담지수", "생활소비부담지수_전연령"]].to_string(index=False))

    agg["z_방식1"] = agg.groupby("서비스_업종_코드_명")["건당_결제금액"].transform(zscore_mean_std_clipped)
    agg["z_방식2"] = agg.groupby("서비스_업종_코드_명")["건당_결제금액"].transform(zscore_robust_raw)
    zcmp = index_df.merge(
        agg.groupby(DONG_KEY)
        .agg(방식1_meanstd클리핑=("z_방식1", "mean"), 방식2_medianMAD클리핑전=("z_방식2", "mean"))
        .reset_index(),
        on=DONG_KEY, how="left",
    )
    cols = DONG_KEY + ["생활소비부담지수", "방식2_medianMAD클리핑전", "방식1_meanstd클리핑"]
    print("\n[검증] z-score 방식 비교 (①mean/std+클리핑 / ②median-MAD / ③최종=median-MAD+클리핑) 상위 10:")
    print(zcmp.sort_values("생활소비부담지수", ascending=False).head(10)[cols].to_string(index=False))
    print("\n[검증] 하위 10:")
    print(zcmp.sort_values("생활소비부담지수").head(10)[cols].to_string(index=False))
    t1 = set(map(tuple, zcmp.nlargest(10, "방식1_meanstd클리핑")[DONG_KEY].values))
    t3 = set(map(tuple, zcmp.nlargest(10, "생활소비부담지수")[DONG_KEY].values))
    print(f"\n①③ 상위 10 겹침: {len(t1 & t3)}/10")

    print(f"\n[전체기간] 행정동 수: {len(index_df)}개")
    print(f"업종부족({MIN_INDUSTRY_COUNT}개 미만): {index_df['업종부족'].sum()}개")

    latest_quarters = sorted(df["기준_년분기_코드"].unique())[-4:]
    print(f"\n[민감도 체크] 최근 구간({latest_quarters})...")
    recent_index, _ = build_index(
        df[df["기준_년분기_코드"].isin(latest_quarters)], YOUTH_AMT, YOUTH_CNT, "청년-최근1년",
        index_col="생활소비부담지수_최근1년", count_col="반영업종수_최근1년",
    )
    index_df = index_df.merge(recent_index, on=DONG_KEY, how="left")
    index_df = index_df.merge(code_map, on=DONG_KEY, how="left")
    no_code = index_df["행정동_코드"].isna().sum()
    if no_code:
        print(f"[경고] 행정동_코드를 못 붙인 행 {no_code}개")

    comparable = index_df.dropna(subset=["생활소비부담지수", "생활소비부담지수_최근1년"])
    if len(comparable) > 2:
        corr = np.corrcoef(comparable["생활소비부담지수"], comparable["생활소비부담지수_최근1년"])[0, 1]
        rank_diff = (comparable["생활소비부담지수"].rank() - comparable["생활소비부담지수_최근1년"].rank()).abs()
        print(f"전체기간 vs 최근1년 상관계수: {corr:.3f}, "
              f"순위차 평균 {rank_diff.mean():.1f}/최대 {rank_diff.max():.0f}")

    index_df.to_csv(OUT_INDEX, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_INDEX}")

    if not SURFACE_COST_POOLED_PATH.exists():
        print(f"\n[경고] {SURFACE_COST_POOLED_PATH} 이 없어 결합은 건너뜁니다.")
        return

    surface = pd.read_csv(SURFACE_COST_POOLED_PATH, encoding="utf-8-sig")
    try:
        merged = surface.merge(
            index_df,
            left_on=["시군구명", "행정동명_최종"],
            right_on=DONG_KEY,
            how="left",
            validate="many_to_one",
        )
    except pd.errors.MergeError as e:
        sys.exit(f"merge 검증 실패: {e}")

    unmatched = merged["생활소비부담지수"].isna().sum()
    print(f"\n표면 주거비(pooled)와 결합: {len(merged)}행 중 매칭 실패 {unmatched}행")
    if unmatched > 0:
        print(merged.loc[merged["생활소비부담지수"].isna(), ["시군구명", "행정동명_최종"]]
              .drop_duplicates().to_string(index=False))
    merged.to_csv(OUT_MERGED, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUT_MERGED}")


if __name__ == "__main__":
    main()