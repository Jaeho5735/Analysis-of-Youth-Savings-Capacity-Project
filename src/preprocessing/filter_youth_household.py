"""
청년 1인가구로 추정되는 거래만 필터링하는 스크립트.

적용 기준 (근거는 팀 노션 '청년_1인가구_필터링_기준' 문서 참고):
  - 전월세구분: 월세/준월세/반전세만 (전세 제외)
  - 전용면적(계약면적): 60㎡ 이하
  - 임차보증금: 1억원(10,000만원) 이하
  - 월세: 상한을 임의의 라운드넘버로 정하지 않고, '전세 제외+면적+보증금' 조건을
          통과한 표본의 월세 분포에서 상위 1% 지점을 이상치 컷오프로 사용한다.
          (특정 클러스터 표본을 늘리려고 상한을 조정하는 것은 선택 편향이므로,
           목표 결과를 보지 않고 분포 자체에서 객관적으로 컷오프를 도출한다.)
  - 14㎡ 미만은 제외하지 않되 '초소형_추정' 컬럼으로 표시(고시원 등 비정형 주거 가능성 -> 별도 검토용)
  - 필터링 후 표본이 30건 미만인 행정동은 제외하지 않고 '표본부족_행정동'으로 표시
    (표본이 적은 건 필터 기준의 결함이 아니라, 해당 지역에 청년 1인가구용 소형
     임대 매물 자체가 드물다는 현실을 반영하는 것일 수 있음 -> 군집화/해석 단계에서 참고)

입력: data/전월세_실거래가_통합_행정동_보정.csv (resolve_ambiguous.py 결과물)
출력: data/전월세_실거래가_청년1인가구.csv
"""

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

INPUT_PATH = DATA_DIR / "전월세_실거래가_통합_행정동_보정.csv"
OUTPUT_PATH = DATA_DIR / "전월세_실거래가_청년1인가구.csv"

AREA_MAX = 60          # ㎡
AREA_MIN_WARN = 14     # ㎡ (미만이면 초소형 주거로 표시만, 제외는 안 함)
DEPOSIT_MAX = 10000    # 만원 (보증금 1억원, 청년전용 버팀목전세자금 대출 기준)
RENT_OUTLIER_Q = 0.99  # 월세 상한을 이 분위수로 객관적으로 도출 (임의의 라운드넘버 사용 안 함)
MIN_SAMPLE_PER_DONG = 30  # 행정동당 최소 표본 수 (미만이면 표본부족으로 표시만, 제외 안 함)


def find_col(df: pd.DataFrame, keyword: str) -> str | None:
    """컬럼명에 keyword가 포함된 첫 번째 컬럼을 찾는다.
    ('계약면적(㎡)'처럼 정확한 이름을 몰라도 부분 일치로 찾기 위함)"""
    matches = [c for c in df.columns if keyword in c]
    return matches[0] if matches else None


def to_numeric(series: pd.Series | None, index=None) -> pd.Series:
    """콤마가 섞인 문자열('1,000' 등)도 숫자로 안전하게 변환.
    series가 None(해당 컬럼이 없는 경우)이면 전부 NaN인 시리즈를 반환."""
    if series is None:
        return pd.Series([pd.NA] * len(index), index=index, dtype="float64")
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False), errors="coerce"
    )


def infer_housing_type(source_file) -> str | None:
    """원본 오피스텔 파일에는 '주택유형' 컬럼이 비어있는 경우가 있어,
    출처파일명(단독다가구/연립다세대/오피스텔이 파일명에 명시됨)에서 직접 추론한다."""
    if not isinstance(source_file, str):
        return None
    if "단독다가구" in source_file:
        return "단독다가구"
    if "연립다세대" in source_file:
        return "연립다세대"
    if "오피스텔" in source_file:
        return "오피스텔"
    return None


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"{INPUT_PATH} 이 없습니다. resolve_ambiguous.py를 먼저 실행하세요.")

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig", low_memory=False)
    before = len(df)
    print(f"필터링 전 전체 행: {before}")

    print("전체 컬럼 목록:", list(df.columns))

    # ── 주택유형 재계산: 원본 오피스텔 파일에 이 컬럼이 비어있는 문제 보정
    df["주택유형"] = df["출처파일"].apply(infer_housing_type)
    print("\n주택유형 재계산 후 분포 (전체 데이터 기준):")
    print(df["주택유형"].value_counts(dropna=False))

    계약면적_col = find_col(df, "계약면적")
    전용면적_col = find_col(df, "전용면적")
    보증금_col = find_col(df, "보증금")
    월세_col = find_col(df, "월세금")  # '월세'만 쓰면 '전월세구분' 컬럼과 잘못 매칭됨
    print(f"사용할 컬럼 -> 계약면적: {계약면적_col}, 전용면적: {전용면적_col}, "
          f"보증금: {보증금_col}, 월세: {월세_col}")

    # ── 면적 컬럼 통일: 단독다가구는 계약면적, 연립다세대/오피스텔은 전용면적
    df["면적"] = to_numeric(df[계약면적_col] if 계약면적_col else None, df.index)
    if 전용면적_col:
        전용 = to_numeric(df[전용면적_col], df.index)
        df["면적"] = df["면적"].fillna(전용)

    df["보증금_num"] = to_numeric(df[보증금_col] if 보증금_col else None, df.index)
    df["월세금_num"] = to_numeric(df[월세_col] if 월세_col else None, df.index)

    # ── 단계별 필터링 (각 단계마다 몇 건씩 줄어드는지 확인용으로 순차 출력)
    step = df.copy()

    step = step[step["전월세구분"] != "전세"]
    print(f"  전세 제외 후: {len(step)}행 (-{before - len(step)})")

    n1 = len(step)
    step = step[step["면적"].notna() & (step["면적"] <= AREA_MAX)]
    print(f"  면적 {AREA_MAX}㎡ 이하 필터 후: {len(step)}행 (-{n1 - len(step)})")

    n2 = len(step)
    step = step[step["보증금_num"].notna() & (step["보증금_num"] <= DEPOSIT_MAX)]
    print(f"  보증금 {DEPOSIT_MAX}만원 이하 필터 후: {len(step)}행 (-{n2 - len(step)})")

    # ── 월세 상한: 임의의 라운드넘버 대신, 여기까지 걸러진 표본의 상위 1%를
    #    이상치로 간주하고 그 지점을 컷오프로 사용한다 (클러스터 결과를 보고
    #    역산해서 정한 값이 아니라, 분포 자체에서 기계적으로 도출한 값)
    rent_q99 = step["월세금_num"].quantile(RENT_OUTLIER_Q)
    rent_max = round(rent_q99, -1) if pd.notna(rent_q99) else None
    print(f"  월세 상한 산출: 상위 {(1-RENT_OUTLIER_Q)*100:.0f}% 지점 = {rent_q99:.1f}만원 "
          f"-> 반올림하여 컷오프 {rent_max}만원 적용")

    n3 = len(step)
    step = step[step["월세금_num"].notna() & (step["월세금_num"] <= rent_max)]
    print(f"  월세 {rent_max}만원 이하 필터 후: {len(step)}행 (-{n3 - len(step)})")

    step["초소형_추정"] = step["면적"] < AREA_MIN_WARN

    print(f"\n최종 남은 행: {len(step)} / {before} ({len(step)/before*100:.1f}%)")
    print(f"이 중 {AREA_MIN_WARN}㎡ 미만 초소형 추정: {step['초소형_추정'].sum()}행 (제외하지 않고 표시만 함)")

    # ── 표본부족 행정동 표시: 제외하지 않고 플래그만 남긴다.
    #    (표본이 적다는 것 자체가 "그 지역엔 청년 1인가구용 소형 임대가 드물다"는
    #     실질적 인사이트일 수 있어, 필터를 더 느슨하게 바꿔 억지로 채우지 않는다)
    dong_counts = step["행정동명_최종"].value_counts()
    low_sample_dongs = dong_counts[dong_counts < MIN_SAMPLE_PER_DONG].index
    step["표본부족_행정동"] = step["행정동명_최종"].isin(low_sample_dongs)
    print(f"표본 {MIN_SAMPLE_PER_DONG}건 미만인 행정동: {len(low_sample_dongs)} / {dong_counts.shape[0]}개 "
          f"(행 기준 {step['표본부족_행정동'].sum()}행, 제외하지 않고 표시만 함)")

    print("\n주택유형별 분포 (필터링 후):")
    print(step["주택유형"].value_counts(dropna=False))

    step = step.drop(columns=["보증금_num", "월세금_num"])
    step.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()