"""
표면 주거비 산출 스크립트.

표면 주거비 = 월세금(만원) + 보증금(만원) x 전월세전환율 / 12

전환율 적용 방식:
  - 단독다가구/연립다세대: (권역, 연월, 주택유형) 기준으로 전환율을 붙인다.
  - 오피스텔: 권역별 데이터에 더해 면적구간(40㎡이하 / 40㎡초과~60㎡이하)까지
    나뉘어 있어, (권역, 면적구간, 연월) 기준으로 붙인다.
  - 전환율 데이터 범위 밖의 계약년월은 가장 가까운 달의 값으로 채우고,
    '전환율_범위외_보정' 컬럼에 표시한다.

입력:
  data/전월세_실거래가_청년1인가구.csv
  data/전월세전환율_권역별.csv           (단독다가구/연립다세대, load_conversion_rate.py 산출물)
  data/전월세전환율_오피스텔_권역별.csv  (오피스텔, load_officetel_rate.py 산출물)
  data/자치구_권역_매핑.csv

출력:
  data/표면주거비_거래단위.csv
  data/표면주거비_행정동별.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

MAIN_PATH = DATA_DIR / "전월세_실거래가_청년1인가구.csv"
RATE_PATH = DATA_DIR / "전월세전환율_권역별.csv"
OFFICETEL_RATE_PATH = DATA_DIR / "전월세전환율_오피스텔_권역별.csv"
MAP_PATH = DATA_DIR / "자치구_권역_매핑.csv"

OUT_TXN = DATA_DIR / "표면주거비_거래단위.csv"
OUT_DONG = DATA_DIR / "표면주거비_행정동별.csv"


def nearest_month_rate(target_ym: int, rate_lookup: dict) -> tuple:
    if not rate_lookup:
        return np.nan, False
    if target_ym in rate_lookup:
        return rate_lookup[target_ym], False
    available = sorted(rate_lookup.keys())
    closest = min(available, key=lambda ym: abs(ym - target_ym))
    return rate_lookup[closest], True


def size_bucket(area) -> str:
    """오피스텔 전환율 데이터의 면적구간 라벨과 맞춘다 (60㎡ 이하 데이터만 다루므로 2구간이면 충분)."""
    if pd.isna(area):
        return None
    return "40㎡이하" if area <= 40 else "40㎡초과 60㎡이하"


def main():
    for p in [MAIN_PATH, RATE_PATH, MAP_PATH]:
        if not p.exists():
            raise FileNotFoundError(f"{p} 이 없습니다. 이전 단계 스크립트를 먼저 실행하세요.")

    df = pd.read_csv(MAIN_PATH, encoding="utf-8-sig", low_memory=False)
    rate_df = pd.read_csv(RATE_PATH, encoding="utf-8-sig")
    gu_zone = pd.read_csv(MAP_PATH, encoding="utf-8-sig")

    print(f"원본 거래 행 수: {len(df)}")

    # ── 자치구 -> 권역 매핑 ──────────────────────────────────
    gu_to_zone = dict(zip(gu_zone["자치구"], gu_zone["권역"]))
    df["권역"] = df["시군구명"].map(gu_to_zone)
    unmapped = df["권역"].isna().sum()
    if unmapped > 0:
        print(f"⚠️ 권역 매핑 실패: {unmapped}행")
        print(df.loc[df["권역"].isna(), "시군구명"].value_counts().head(10))

    # ── 단독다가구/연립다세대 lookup: {(주택유형,권역): {연월: 전환율}} ──
    rate_lookup = {}
    for (h_type, zone), g in rate_df.groupby(["주택유형", "권역"]):
        rate_lookup[(h_type, zone)] = dict(zip(g["연월"], g["전환율"]))

    # ── 오피스텔 lookup: {(권역,면적구간): {연월: 전환율}} ──────
    officetel_lookup = {}
    if OFFICETEL_RATE_PATH.exists():
        off_df = pd.read_csv(OFFICETEL_RATE_PATH, encoding="utf-8-sig")
        for (zone, size), g in off_df.groupby(["권역", "면적구간"]):
            officetel_lookup[(zone, size)] = dict(zip(g["연월"], g["전환율"]))
        print("오피스텔 전용(권역x면적구간) 전환율 적용됨.")
    else:
        print("⚠️ 오피스텔 전환율 파일이 없어, 연립다세대 권역값을 임시 대체값으로 사용합니다.")

    # ── 면적 컬럼 확보 (필터링 스크립트에서 만든 '면적' 컬럼 재사용, 없으면 계산) ──
    if "면적" not in df.columns:
        def to_numeric(s):
            return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")
        df["면적"] = to_numeric(df.get("계약면적", pd.Series(dtype=float)))
        if "전용면적" in df.columns:
            df["면적"] = df["면적"].fillna(to_numeric(df["전용면적"]))

    df["면적구간"] = df["면적"].apply(size_bucket)

    # ── 행 단위로 전환율 적용 ──────────────────────────────────
    def get_rate(row):
        ym = int(row["계약년월"])
        if row["주택유형"] == "오피스텔":
            key = (row["권역"], row["면적구간"])
            lookup = officetel_lookup.get(key)
            if lookup:
                return nearest_month_rate(ym, lookup)
            # 오피스텔 전용 데이터 없을 때의 대체값
            fallback = rate_lookup.get(("연립다세대", row["권역"]), {})
            rate, out_of_range = nearest_month_rate(ym, fallback)
            return rate, True  # 대체값 사용 자체를 '보정'으로 표시
        else:
            key = (row["주택유형"], row["권역"])
            lookup = rate_lookup.get(key, {})
            return nearest_month_rate(ym, lookup)

    results = df.apply(get_rate, axis=1, result_type="expand")
    df["전환율"] = results[0]
    df["전환율_범위외_보정"] = results[1]

    missing_rate = df["전환율"].isna().sum()
    print(f"전환율 매칭 실패: {missing_rate}행")
    print(f"전환율 범위외/대체 적용된 행: {df['전환율_범위외_보정'].sum()}행")

    # ── 표면 주거비 계산 ──────────────────────────────────
    def to_numeric(s):
        return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False), errors="coerce")

    월세 = to_numeric(df["월세금(만원)"]) if "월세금(만원)" in df.columns else to_numeric(df["월세금"])
    보증금 = to_numeric(df["보증금(만원)"]) if "보증금(만원)" in df.columns else to_numeric(df["보증금"])

    df["표면_주거비"] = 월세 + (보증금 * df["전환율"] / 12)

    valid = df["표면_주거비"].notna().sum()
    print(f"\n표면 주거비 계산 성공: {valid} / {len(df)}행")

    df.to_csv(OUT_TXN, index=False, encoding="utf-8-sig")
    print(f"거래 단위 결과 저장: {OUT_TXN}")

    # ── 행정동 x 주택유형별 중앙값 집계 ──────────────────────
    agg = (
        df.dropna(subset=["표면_주거비"])
        .groupby(["행정동명_최종", "주택유형"])["표면_주거비"]
        .agg(중앙값="median", 표본수="count")
        .reset_index()
    )
    agg["표본부족"] = agg["표본수"] < 30

    agg.to_csv(OUT_DONG, index=False, encoding="utf-8-sig")
    print(f"행정동별 집계 결과 저장: {OUT_DONG} ({len(agg)}개 행정동x유형 조합)")
    print(f"표본 30건 미만 조합: {agg['표본부족'].sum()}개")

    print("\n미리보기:")
    print(agg.sort_values("표본수", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()