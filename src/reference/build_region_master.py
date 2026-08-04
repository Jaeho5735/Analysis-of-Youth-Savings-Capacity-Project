"""
행정동 기준 코드표 생성.

데이터 소스마다 행정동 코드 체계와 기준 시점이 달라 그대로는 결합이 안 된다.
  코드 자릿수  KIKmix 10자리 vs 상권분석·생활이동·생활인구 8자리
  이름 표기    "창신제1동"(KIKmix) vs "창신1동"(생활이동) 등
  기준 시점    소스마다 행정동 개편 반영 시점이 다름

10자리 코드의 앞 8자리가 8자리 코드와 일치하므로(표면주거비 420개 전수 검증, 불일치 0)
코드를 결합축으로 쓴다. 이름 결합은 표기 변이 때문에 금지.

이 스크립트는 KIKmix 원본만 읽는다. 다른 산출물에 의존하지 않으므로 파이프라인
최상단에서 실행할 수 있다. 소스별 보유 현황 진단은 산출물이 다 나온 뒤
check_region_coverage.py에서 따로 한다.

폐지된 행정동은 LEGACY_MAP으로 현행 코드에 연결한다. 매핑 근거는 KIKmix 생성일자다.
신설동·용두동의 생성일자가 20250701이므로, 그 이전 체계의 용신동(11230536)이 이 둘로
분동된 것이다.

출력은 DB의 dim_region 테이블 원본으로도 쓴다.

입력: data/대한민국 법정동 행정동_코드.xlsx (KIKmix)
출력: data/행정동_기준코드표.csv, data/행정동_폐지코드_매핑.csv
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

KIKMIX_PATH = DATA_DIR / "대한민국 법정동 행정동 코드.xlsx"
OUT_MASTER = DATA_DIR / "행정동_기준코드표.csv"
OUT_LEGACY = DATA_DIR / "행정동_폐지코드_매핑.csv"

REGION_MAP = {
    "도심권": ["종로구", "중구", "용산구"],
    "동북권": ["성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구", "노원구"],
    "서북권": ["은평구", "서대문구", "마포구"],
    "서남권": ["양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구"],
    "동남권": ["서초구", "강남구", "송파구", "강동구"],
}
GU_TO_REGION = {gu: r for r, gus in REGION_MAP.items() for gu in gus}

# 폐지코드 -> 현행코드. 분동(1:N)은 세미콜론으로 나열한다.
LEGACY_MAP = [
    ("11230536", "용신동", "11230515;11230533", "2025-07-01 용신동이 신설동·용두동으로 분동"),
    ("11740520", "상일동", "11740525;11740526", "2021-07-01 상일동이 상일제1·2동으로 분동"),
    ("11680740", "일원2동", "11680675", "2022-12-23 개포3동 생성, 일원2동에서 개편"),
    ("11305590", "번1동(구)", "11305595", "2019-01-01 강북구 행정동 코드 재부여"),
    ("11305600", "번2동(구)", "11305603", "2019-01-01 강북구 행정동 코드 재부여"),
    ("11305606", "번3동(구)", "11305608", "2019-01-01 강북구 행정동 코드 재부여"),
    ("11305610", "수유1동(구)", "11305615", "2019-01-01 강북구 행정동 코드 재부여"),
    ("11305620", "수유2동(구)", "11305625", "2019-01-01 강북구 행정동 코드 재부여"),
    ("11305630", "수유3동(구)", "11305635", "2019-01-01 강북구 행정동 코드 재부여"),
]


def load_official() -> pd.DataFrame:
    if not KIKMIX_PATH.exists():
        sys.exit(f"{KIKMIX_PATH} 이 없습니다. 행정안전부 KIKmix 파일을 data 폴더에 넣어주세요.")

    k = pd.read_excel(KIKMIX_PATH, sheet_name="KIKmix", dtype=str)
    seoul = k[(k["시도명"] == "서울특별시") & k["읍면동명"].notna()]
    dong = seoul.drop_duplicates(subset=["행정동코드"])[
        ["행정동코드", "시군구명", "읍면동명", "생성일자"]
    ].copy()
    dong.columns = ["행정동코드10", "시군구명", "행정동명", "생성일자"]
    dong["행정동코드8"] = dong["행정동코드10"].str[:8]
    dong["권역"] = dong["시군구명"].map(GU_TO_REGION)

    unmapped = dong["권역"].isna().sum()
    if unmapped:
        missing = dong.loc[dong["권역"].isna(), "시군구명"].unique()
        sys.exit(f"권역 매핑 실패 {unmapped}건 ({list(missing)}). REGION_MAP 확인 필요")

    dup = dong["행정동코드8"].duplicated().sum()
    if dup:
        sys.exit(f"8자리 코드 중복 {dup}건. 앞 8자리를 결합축으로 쓸 수 없음")

    print(f"서울 현행 행정동: {len(dong)}개")
    print(dong.groupby("권역").size().to_string())
    return dong.sort_values("행정동코드10").reset_index(drop=True)


def build_legacy(dong: pd.DataFrame) -> pd.DataFrame:
    name_by_code = dict(zip(dong["행정동코드8"], dong["시군구명"] + " " + dong["행정동명"]))
    rows = []
    for old_code, old_name, new_codes, note in LEGACY_MAP:
        targets = new_codes.split(";")
        unknown = [c for c in targets if c not in name_by_code]
        if unknown:
            print(f"[경고] {old_name}의 현행 코드 {unknown} 가 기준표에 없음")
        rows.append({
            "폐지코드8": old_code,
            "폐지시점_명칭": old_name,
            "현행코드8": new_codes,
            "현행명칭": " + ".join(name_by_code.get(c, "?") for c in targets),
            "관계": "1:N 분동" if len(targets) > 1 else "1:1 개편",
            "근거": note,
        })
    return pd.DataFrame(rows)


def main():
    dong = load_official()

    recent = dong[pd.to_numeric(dong["생성일자"], errors="coerce") >= 20240101]
    if len(recent):
        print(f"\n2024년 이후 생성된 행정동 {len(recent)}개 (개편 반영 확인용)")
        print(recent[["행정동코드8", "시군구명", "행정동명", "생성일자"]].to_string(index=False))

    legacy = build_legacy(dong)

    cols = ["행정동코드10", "행정동코드8", "시군구명", "행정동명", "권역", "생성일자"]
    dong[cols].to_csv(OUT_MASTER, index=False, encoding="utf-8-sig")
    legacy.to_csv(OUT_LEGACY, index=False, encoding="utf-8-sig")

    print(f"\n저장 완료: {OUT_MASTER} ({len(dong)}행)")
    print(f"저장 완료: {OUT_LEGACY} ({len(legacy)}행)")
    print("\n소스별 보유 현황은 산출물이 나온 뒤 check_region_coverage.py로 확인한다.")


if __name__ == "__main__":
    main()