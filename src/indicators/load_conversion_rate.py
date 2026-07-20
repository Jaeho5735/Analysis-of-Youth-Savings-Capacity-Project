"""
한국부동산원 '지역별 전월세 전환율' (단독주택 / 연립·다세대) CSV를
표면 주거비 계산에 바로 쓸 수 있는 롱포맷 표로 정리한다.

원본 CSV 구조:
  1행: 진짜 헤더 (No, 지역, 지역.1, 2023년 5월, 2023년 6월, ... 2026년 5월)
  2행: '전월세 전환율' 라벨만 반복된 쓸모없는 행 -> skiprows로 건너뜀
  3행부터: 실제 데이터. '지역'=상위(전국/수도권/서울 등), '지역.1'=하위(권역)

서울 하위 항목 7개 중 '강북지역'(도심+동북+서북 합산), '강남지역'(동남+서남 합산)은
요약행이라 제외하고, 실제 5개 권역(도심권/동남권/동북권/서남권/서북권)만 사용한다.

입력: data/지역별_전월세_전환율_단독주택.csv, data/지역별_전월세_전환율_연립_다세대.csv
출력: data/전월세전환율_권역별.csv  (컬럼: 주택유형, 자치구, 권역, 연월, 전환율_pct, 전환율)
"""

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

FILES = {
    "단독다가구": DATA_DIR / "지역별 전월세 전환율_단독주택.csv",
    "연립다세대": DATA_DIR / "지역별 전월세 전환율_연립_다세대.csv",
}

# 서울시 5대 권역 <-> 자치구 매핑 (요약행 강북지역/강남지역은 제외하고 이 5개만 사용)
GU_TO_ZONE = {
    "종로구": "도심권", "중구": "도심권", "용산구": "도심권",
    "서초구": "동남권", "강남구": "동남권", "송파구": "동남권", "강동구": "동남권",
    "성동구": "동북권", "광진구": "동북권", "동대문구": "동북권", "중랑구": "동북권",
    "성북구": "동북권", "강북구": "동북권", "도봉구": "동북권", "노원구": "동북권",
    "양천구": "서남권", "강서구": "서남권", "구로구": "서남권", "금천구": "서남권",
    "영등포구": "서남권", "동작구": "서남권", "관악구": "서남권",
    "은평구": "서북권", "서대문구": "서북권", "마포구": "서북권",
}
VALID_ZONES = ["도심권", "동남권", "동북권", "서남권", "서북권"]


def parse_yearmonth(col: str):
    """'2023년 5월' -> 202305 (int)"""
    year = col.split("년")[0].strip()
    month = col.split("년")[1].replace("월", "").strip()
    return int(year) * 100 + int(month)


def load_one(path: Path, housing_type: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="cp949", header=0, skiprows=[1])
    df.columns = [c.strip() for c in df.columns]

    seoul = df[(df["지역"] == "서울") & (df["지역.1"].isin(VALID_ZONES))].copy()
    if len(seoul) != 5:
        print(f"⚠️ 경고: {path.name}에서 서울 5개 권역이 아니라 {len(seoul)}개 행이 걸림. 확인 필요.")

    month_cols = [c for c in df.columns if "년" in c and "월" in c]

    long_df = seoul.melt(
        id_vars=["지역.1"], value_vars=month_cols,
        var_name="연월_raw", value_name="전환율_pct",
    )
    long_df = long_df.rename(columns={"지역.1": "권역"})
    long_df["연월"] = long_df["연월_raw"].apply(parse_yearmonth)
    long_df["전환율_pct"] = pd.to_numeric(long_df["전환율_pct"], errors="coerce")
    long_df["전환율"] = long_df["전환율_pct"] / 100  # 연 5.7% -> 0.057
    long_df["주택유형"] = housing_type

    return long_df[["주택유형", "권역", "연월", "전환율_pct", "전환율"]]


def main():
    all_long = []
    for housing_type, path in FILES.items():
        if not path.exists():
            print(f"⚠️ 파일 없음: {path}")
            continue
        long_df = load_one(path, housing_type)
        print(f"{housing_type}: {len(long_df)}행 로드 (권역 {long_df['권역'].nunique()}개 x "
              f"연월 {long_df['연월'].nunique()}개)")
        all_long.append(long_df)

    result = pd.concat(all_long, ignore_index=True)

    # 자치구 -> 권역 매핑을 별도 테이블로도 저장 (다른 스크립트에서 구->권역 변환할 때 재사용)
    gu_zone_df = pd.DataFrame(
        [(gu, zone) for gu, zone in GU_TO_ZONE.items()], columns=["자치구", "권역"]
    )

    out_rate = DATA_DIR / "전월세전환율_권역별.csv"
    out_map = DATA_DIR / "자치구_권역_매핑.csv"
    result.to_csv(out_rate, index=False, encoding="utf-8-sig")
    gu_zone_df.to_csv(out_map, index=False, encoding="utf-8-sig")

    print(f"\n저장 완료: {out_rate} ({len(result)}행)")
    print(f"저장 완료: {out_map} ({len(gu_zone_df)}행, 25개 자치구 중 {len(gu_zone_df)}개 매핑)")
    print("\n미리보기:")
    print(result.head(10).to_string(index=False))


if __name__ == "__main__":
    main()