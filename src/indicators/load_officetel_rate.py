"""
한국부동산원 '오피스텔 전월세전환율' CSV를 정리한다.
단독다가구/연립다세대와 달리 권역별 + 면적구간별(40㎡이하 / 40㎡초과~60㎡이하)로 나뉘어 있다.

원본 구조: 1행=헤더, 2행='전월세전환율' 라벨행, 3행='%' 단위행 -> 둘 다 건너뜀

입력: data/오피스텔 전월세전환율.csv 
출력: data/전월세전환율_오피스텔_권역별.csv
"""

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

FILE_NAME = "오피스텔 전월세전환율.csv"
IN_PATH = DATA_DIR / FILE_NAME
OUT_PATH = DATA_DIR / "전월세전환율_오피스텔_권역별.csv"

VALID_ZONES = ["도심권", "동남권", "동북권", "서남권", "서북권"]
VALID_SIZES = ["40㎡이하", "40㎡초과 60㎡이하"]


def parse_yearmonth(col: str) -> int:
    year = col.split("년")[0].strip()
    month = col.split("년")[1].replace("월", "").strip()
    return int(year) * 100 + int(month)


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"{IN_PATH} 이 없습니다. 파일명을 확인하거나 FILE_NAME을 수정하세요.")

    df = pd.read_csv(IN_PATH, encoding="cp949")
    df.columns = [c.strip() for c in df.columns]
    df = df.iloc[2:].reset_index(drop=True)  # 라벨행, 단위행 제거

    seoul = df[
        (df["지역"] == "서울")
        & (df["지역.1"].isin(VALID_ZONES))
        & (df["규모"].isin(VALID_SIZES))
    ].copy()
    print(f"필터링된 행 수: {len(seoul)} (기대값: 권역 5개 x 면적구간 2개 = 10행)")

    month_cols = [c for c in df.columns if "년" in c and "월" in c]

    long_df = seoul.melt(
        id_vars=["지역.1", "규모"], value_vars=month_cols,
        var_name="연월_raw", value_name="전환율_pct",
    )
    long_df = long_df.rename(columns={"지역.1": "권역", "규모": "면적구간"})
    long_df["연월"] = long_df["연월_raw"].apply(parse_yearmonth)
    long_df["전환율_pct"] = pd.to_numeric(long_df["전환율_pct"], errors="coerce")
    long_df["전환율"] = long_df["전환율_pct"] / 100

    result = long_df[["권역", "면적구간", "연월", "전환율_pct", "전환율"]]
    result.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print(f"저장 완료: {OUT_PATH} ({len(result)}행)")
    print(f"연월 범위: {result['연월'].min()} ~ {result['연월'].max()}")
    print(result.head(10).to_string(index=False))


if __name__ == "__main__":
    main()