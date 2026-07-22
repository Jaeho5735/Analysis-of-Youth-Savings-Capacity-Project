"""
생활소비부담지수 산출 스크립트.

개념: 청년 생활밀착 업종(외식·카페·유통) 10종의 '건당 결제금액'을
     업종별로 표준화(z-score)한 뒤 평균 내어, 행정동별 생활물가 체감도를 지수화한다.

산식 (기획서 원안 기준):
  생활소비부담지수 = 업종별 건당 매출액 z-score의 평균
  (업종을 먼저 표준화하지 않고 전부 섞어 평균 내면, 거래건수가 많은 업종이
   결과를 지배하게 되어 왜곡이 생기므로 반드시 '업종별 표준화 -> 평균' 순서를 지킨다)

입력: data/서울시_상권분석서비스_추정매출-행정동_*.csv (2023~2026년, 분기 데이터 롤링 수집)
출력:
  data/생활소비부담지수_행정동별.csv
  data/표면주거비_생활소비부담지수_결합.csv (표면 주거비와 병합한 최종본)
"""

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# 파일명 패턴: '서울시_상권분석서비스_추정매출-행정동_*.csv' 형태로 저장해주세요
FILE_PATTERN = str(DATA_DIR / "서울시_상권분석서비스_추정매출-행정동*.csv")

SURFACE_COST_PATH = DATA_DIR / "표면주거비_행정동별.csv"
OFFICIAL_DONG_LIST_PATH = DATA_DIR / "행정동_공식명_목록.csv"  # dong_matcher.py 산출

OUT_INDEX = DATA_DIR / "생활소비부담지수_행정동별.csv"
OUT_MERGED = DATA_DIR / "표면주거비_생활소비부담지수_결합.csv"

# 청년 생활밀접 업종 (기획서 원안 6개 + 논의 후 추가한 분식/치킨/패스트푸드 3개)
TARGET_INDUSTRIES = [
    "한식음식점", "중식음식점", "일식음식점", "제과점",   # 외식류
    "분식전문점", "치킨전문점", "패스트푸드점",           # 외식류(추가)
    "커피-음료",                                          # 카페/기호품
    "슈퍼마켓", "편의점",                                 # 유통/생필품
]

# 매출건수가 너무 적어 단가가 왜곡된 행을 제거하는 분위수 컷오프
# (임의의 숫자 대신, 월세 필터링 때와 동일하게 데이터 분포에서 객관적으로 도출)
COUNT_OUTLIER_Q_LOW = 0.05


def normalize_dong_name(value, official_set: set):
    """상권분석서비스 데이터의 행정동_코드_명 표기(주로 '제'가 빠져있음)를
    KIKmix 공식 표기(우리 표면주거비 데이터가 이미 이 기준으로 통일되어 있음)로 되돌린다.
    resolve_precise_jibun.py에서 쓴 것과 동일한 로직 - 별도 스크립트라 재사용 대신 복제."""
    if not value or not isinstance(value, str):
        return value
    # 원본 파일 인코딩 문제로 '.'이 '?'로 깨져 들어오는 경우가 있어(예: '금호2?3가동'),
    # 숫자 사이의 '?'는 원래 '.'이었을 가능성이 매우 높으므로 먼저 되돌린다.
    value = re.sub(r"(?<=\d)\?(?=\d)", ".", value)
    candidate = value.strip().split()[-1]
    if candidate in official_set:
        return candidate
    inserted = re.sub(r"^(.+?)([\d.]+가?동)$", r"\1제\2", candidate)
    if inserted in official_set:
        return inserted
    stripped = re.sub(r"제([\d.]+가?동)$", r"\1", candidate)
    if stripped in official_set:
        return stripped
    return candidate


def load_all_files() -> pd.DataFrame:
    files = sorted(glob.glob(FILE_PATTERN))
    if not files:
        raise FileNotFoundError(
            f"{FILE_PATTERN} 에 해당하는 파일이 없습니다. "
            f"2023~2026년 상권분석서비스 CSV를 data 폴더에 넣어주세요."
        )
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

    # 파일 간 분기가 겹칠 수 있어(롤링 수집), (분기,행정동,업종) 기준 중복 제거
    before = len(combined)
    combined = combined.drop_duplicates(
        subset=["기준_년분기_코드", "행정동_코드", "서비스_업종_코드"]
    )
    print(f"중복 제거 후: {len(combined)}행 (-{before - len(combined)}, 파일 간 겹치는 분기 제거됨)")

    # ── 행정동명 '제' 표기를 우리 데이터 기준(KIKmix 공식 표기)으로 통일 ──
    if OFFICIAL_DONG_LIST_PATH.exists():
        official_set = set(pd.read_csv(OFFICIAL_DONG_LIST_PATH, encoding="utf-8-sig")["행정동명"])
        before_unique = combined["행정동_코드_명"].nunique()
        combined["행정동_코드_명"] = combined["행정동_코드_명"].apply(
            lambda v: normalize_dong_name(v, official_set)
        )
        after_unique = combined["행정동_코드_명"].nunique()
        print(f"행정동명 정규화: 고유 {before_unique}개 -> {after_unique}개 "
              f"('제' 표기 등 우리 데이터 기준으로 통일)")
    else:
        print(f"⚠️ {OFFICIAL_DONG_LIST_PATH} 이 없어 행정동명 정규화를 건너뜁니다 (매칭 실패 위험).")

    return combined


def main():
    df = load_all_files()

    df = df[df["서비스_업종_코드_명"].isin(TARGET_INDUSTRIES)].copy()
    print(f"\n타겟 업종({len(TARGET_INDUSTRIES)}개) 필터링 후: {len(df)}행")
    print(df["서비스_업종_코드_명"].value_counts())

    # ── 건당 결제금액 산출 ──────────────────────────────────
    df["건당_결제금액"] = df["당월_매출_금액"] / df["당월_매출_건수"]

    # ── 매출건수 이상치(너무 적어 단가가 왜곡된 행) 제거 ──────
    count_cutoff = df["당월_매출_건수"].quantile(COUNT_OUTLIER_Q_LOW)
    before = len(df)
    df = df[df["당월_매출_건수"] >= count_cutoff]
    print(f"\n매출건수 하위 {COUNT_OUTLIER_Q_LOW*100:.0f}%(={count_cutoff:.0f}건) 미만 제거: "
          f"{len(df)}행 (-{before - len(df)})")

    # ── 업종 x 행정동별 평균 건당 결제금액 (분기 전체 기간 평균) ─
    agg = (
        df.groupby(["행정동_코드", "행정동_코드_명", "서비스_업종_코드_명"])["건당_결제금액"]
        .mean()
        .reset_index()
    )
    print(f"\n업종x행정동 조합: {len(agg)}개 (기대값: 행정동수 x {len(TARGET_INDUSTRIES)})")

    # ── 업종별로 z-score 계산 (반드시 업종 안에서만 비교, 다른 업종과 섞지 않음) ─
    agg["zscore"] = agg.groupby("서비스_업종_코드_명")["건당_결제금액"].transform(
        lambda s: (s - s.mean()) / s.std()
    )

    # ── 행정동별로 업종 z-score 평균 -> 최종 생활소비부담지수 ─
    index_df = (
        agg.groupby(["행정동_코드", "행정동_코드_명"])
        .agg(
            생활소비부담지수=("zscore", "mean"),
            반영업종수=("zscore", "count"),
        )
        .reset_index()
    )
    incomplete = (index_df["반영업종수"] < len(TARGET_INDUSTRIES)).sum()
    print(f"\n10개 업종이 전부 반영 안 된 행정동: {incomplete}개 "
          f"(해당 업종 자체가 존재하지 않는 동네일 수 있음 - 값이 있는 업종만으로 평균)")

    index_df.to_csv(OUT_INDEX, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_INDEX}")
    print(index_df.sort_values("생활소비부담지수", ascending=False).head(10).to_string(index=False))
    print("\n(하위 10개, 즉 생활비 부담이 가장 낮은 동네)")
    print(index_df.sort_values("생활소비부담지수").head(10).to_string(index=False))

    # ── 표면 주거비와 결합 ──────────────────────────────────
    if SURFACE_COST_PATH.exists():
        surface = pd.read_csv(SURFACE_COST_PATH, encoding="utf-8-sig")
        merged = surface.merge(
            index_df, left_on="행정동명_최종", right_on="행정동_코드_명", how="left"
        )
        unmatched = merged["생활소비부담지수"].isna().sum()
        print(f"\n표면 주거비와 결합: {len(merged)}행 중 매칭 실패 {unmatched}행")
        if unmatched > 0:
            print("매칭 실패한 행정동명(표기 차이 확인 필요):")
            print(merged.loc[merged["생활소비부담지수"].isna(), "행정동명_최종"].unique()[:20])
        merged.to_csv(OUT_MERGED, index=False, encoding="utf-8-sig")
        print(f"저장 완료: {OUT_MERGED}")
    else:
        print(f"\n⚠️ {SURFACE_COST_PATH} 이 없어 결합은 건너뜁니다.")


if __name__ == "__main__":
    main()