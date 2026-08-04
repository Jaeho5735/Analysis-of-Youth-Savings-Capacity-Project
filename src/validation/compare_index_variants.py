"""
생활소비부담지수 변형 비교 — 업무지구 편향 대응 진단.

상권 매출에는 거주자뿐 아니라 직장인·방문객 소비가 섞인다. 원자료가 시간대·요일·
연령대별로 쪼개져 있으므로, 거주자 소비 비중이 높을 것으로 기대되는 구간만 뽑아
지수를 다시 만들고 순위가 얼마나 달라지는지, 업무중심성과의 상관이 실제로 줄어드는지
확인한다.

변형 4종:
  전체   - 당월 매출 (현행 지수, 기준선)
  주말   - 주말 매출. 직장인 소비는 평일에 몰리므로 거주자 비중이 높다
  청년   - 20대+30대 매출. 프로젝트 분석 대상과 직접 일치
  저녁   - 17~21시 매출. 퇴근 후 소비라 거주지 소비 비중이 높다

판정:
  변형과 전체의 순위상관이 높으면 -> 편향이 순위를 바꾸지 않는다는 실증 근거
  변형에서 주야간인구비 상관이 뚜렷이 낮아지면 -> 그 변형을 메인으로 교체 검토

사용법: python compare_index_variants.py
"""

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from utils.dong_names import load_official_ref, normalize_dong_name  # noqa: E402

FILE_PATTERN = str(DATA_DIR / "서울시_상권분석서비스_추정매출-행정동*.csv")
OFFICIAL_DONG_LIST_PATH = DATA_DIR / "행정동_공식명_목록.csv"
POP_PATH = DATA_DIR / "2023~2025_행정동별_청년생활인구_지표.csv"  # 없으면 편향 진단만 생략
OUT_PATH = DATA_DIR / "생활소비부담지수_변형비교.csv"

TARGET_INDUSTRIES = [
    "한식음식점", "중식음식점", "일식음식점", "제과점",
    "분식전문점", "치킨전문점", "패스트푸드점",
    "커피-음료", "슈퍼마켓", "편의점",
]
COUNT_OUTLIER_Q_LOW = 0.05
ZSCORE_CLIP = 3.0
MIN_INDUSTRY_COUNT = 5
DONG_KEY = ["시군구명", "행정동_코드_명"]

# 변형별 (매출금액 컬럼들, 매출건수 컬럼들)
VARIANTS = {
    "전체": (["당월_매출_금액"], ["당월_매출_건수"]),
    "주말": (["주말_매출_금액"], ["주말_매출_건수"]),
    "청년": (["연령대_20_매출_금액", "연령대_30_매출_금액"],
             ["연령대_20_매출_건수", "연령대_30_매출_건수"]),
    "저녁": (["시간대_17~21_매출_금액"], None),  # 건수 컬럼명이 손상돼 있어 런타임에 탐색
}


def find_evening_count_col(df: pd.DataFrame):
    """시간대 건수 컬럼명이 '시간대_건수~21_매출_건수'처럼 깨져 있어 상한값으로 찾는다."""
    for c in df.columns:
        if c.startswith("시간대_") and c.endswith("_매출_건수") and "~21" in c:
            return c
    return None


def zscore_robust_clipped(s: pd.Series) -> pd.Series:
    med = s.median()
    mad = (s - med).abs().median()
    if not mad or pd.isna(mad):
        std = s.std()
        if not std or pd.isna(std):
            return pd.Series(0.0, index=s.index)
        return ((s - med) / std).clip(-ZSCORE_CLIP, ZSCORE_CLIP)
    return ((s - med) / (1.4826 * mad)).clip(-ZSCORE_CLIP, ZSCORE_CLIP)


def build_variant(df: pd.DataFrame, amt_cols, cnt_cols, label: str) -> pd.DataFrame:
    """변형별 지수 산출. 건당 단가는 반드시 합산 후 나눈다."""
    work = df.copy()
    work["_금액"] = work[amt_cols].sum(axis=1)
    work["_건수"] = work[cnt_cols].sum(axis=1)

    # 변형마다 건수 분포가 다르므로 컷오프도 변형 기준으로 다시 잡는다
    cutoff = work.loc[work["_건수"] > 0, "_건수"].quantile(COUNT_OUTLIER_Q_LOW)
    before = len(work)
    work = work[work["_건수"] >= max(cutoff, 1)]

    agg = (
        work.groupby(DONG_KEY + ["서비스_업종_코드_명"])
        .agg(금액=("_금액", "sum"), 건수=("_건수", "sum"))
        .reset_index()
    )
    agg = agg[agg["건수"] > 0]
    agg["단가"] = agg["금액"] / agg["건수"]
    agg["z"] = agg.groupby("서비스_업종_코드_명")["단가"].transform(zscore_robust_clipped)

    idx = (
        agg.groupby(DONG_KEY)
        .agg(**{f"지수_{label}": ("z", "mean"), f"업종수_{label}": ("z", "count")})
        .reset_index()
    )
    print(f"  [{label}] 건수컷 {cutoff:.0f}건({before - len(work)}행 제외) "
          f"-> 행정동 {len(idx)}개, 업종부족 {(idx[f'업종수_{label}'] < MIN_INDUSTRY_COUNT).sum()}개")
    return idx


def main():
    official_ref = load_official_ref(OFFICIAL_DONG_LIST_PATH)
    official_set = set(official_ref["행정동명"])
    codes = official_ref["행정동코드"].astype(str).str.zfill(10)
    sigungu_map = dict(zip(codes.str[:5], official_ref["시군구명"]))

    files = sorted(glob.glob(FILE_PATTERN))
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_csv(f, encoding="cp949", low_memory=False))
        except UnicodeDecodeError:
            dfs.append(pd.read_csv(f, encoding="utf-8-sig", low_memory=False))
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["기준_년분기_코드", "행정동_코드", "서비스_업종_코드"])
    df["행정동_코드_명"] = df["행정동_코드_명"].apply(lambda v: normalize_dong_name(v, official_set))

    df["행정동_코드"] = (pd.to_numeric(df["행정동_코드"], errors="coerce")
                     .astype("Int64").astype(str).str.zfill(8))
    df["시군구명"] = df["행정동_코드"].str[:5].map(sigungu_map)
    df = df.drop_duplicates(subset=["기준_년분기_코드"] + DONG_KEY + ["서비스_업종_코드"], keep="last")
    df = df[df["서비스_업종_코드_명"].isin(TARGET_INDUSTRIES)].copy()
    print(f"필터 후 {len(df)}행\n")

    ev_cnt = find_evening_count_col(df)
    if ev_cnt:
        VARIANTS["저녁"] = (VARIANTS["저녁"][0], [ev_cnt])
        print(f"저녁 건수 컬럼: {ev_cnt}")
    else:
        VARIANTS.pop("저녁")
        print("저녁 건수 컬럼을 못 찾아 '저녁' 변형은 건너뜁니다")

    print("\n[변형별 산출]")
    result = None
    for label, (amt, cnt) in VARIANTS.items():
        missing = [c for c in amt + cnt if c not in df.columns]
        if missing:
            print(f"  [{label}] 컬럼 없음: {missing} -> 건너뜀")
            continue
        part = build_variant(df, amt, cnt, label)
        result = part if result is None else result.merge(part, on=DONG_KEY, how="outer")

    labels = [c.replace("지수_", "") for c in result.columns if c.startswith("지수_")]

    print("\n[1] 전체 지수와의 순위상관 / 상위 10 겹침")
    base = "지수_전체"
    for lb in labels:
        if lb == "전체":
            continue
        col = f"지수_{lb}"
        sub = result.dropna(subset=[base, col])
        rho, _ = spearmanr(sub[base], sub[col])
        t1 = set(map(tuple, sub.nlargest(10, base)[DONG_KEY].values))
        t2 = set(map(tuple, sub.nlargest(10, col)[DONG_KEY].values))
        print(f"  전체 vs {lb}: ρ={rho:.3f}, 상위10 겹침 {len(t1 & t2)}/10 (n={len(sub)})")

    if POP_PATH.exists():
        pop = pd.read_csv(POP_PATH, encoding="utf-8-sig")
        pop["행정동_코드"] = pop["행정동코드"].astype(str).str.zfill(8)
        dong_code = df.drop_duplicates(DONG_KEY)[DONG_KEY + ["행정동_코드"]]
        merged = result.merge(dong_code, on=DONG_KEY, how="left").merge(
            pop[["행정동_코드", "주야간_인구비", "주간_순유입_규모"]], on="행정동_코드", how="left")

        print("\n[2] 업무중심성과의 상관 (낮을수록 편향이 적다)")
        for lb in labels:
            sub = merged.dropna(subset=[f"지수_{lb}", "주야간_인구비"])
            r1, _ = spearmanr(sub[f"지수_{lb}"], sub["주야간_인구비"])
            r2, _ = spearmanr(sub[f"지수_{lb}"], sub["주간_순유입_규모"])
            print(f"  {lb:4s}: 주야간인구비 ρ={r1:+.3f} / 주간순유입 ρ={r2:+.3f}")

        print("\n[3] 변형별 상위 10 행정동")
        for lb in labels:
            top = merged.nlargest(10, f"지수_{lb}")["행정동_코드_명"].tolist()
            print(f"  {lb:4s}: {', '.join(top)}")
        merged.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    else:
        print(f"\n{POP_PATH} 없음 -> 편향 진단 생략")
        result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"\n저장 완료: {OUT_PATH}")


if __name__ == "__main__":
    main()