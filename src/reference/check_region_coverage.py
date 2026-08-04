"""
소스별 행정동 커버리지 진단.

기준 코드표(build_region_master.py 산출)를 기준으로, 각 산출물이 어느 행정동을
갖고 있고 어디가 비었는지 확인한다. 비어 있는 것이 버그인지 데이터 성격인지를
가르는 것이 목적이다. 예를 들어 표면주거비에 없는 7개 동은 전부 대단지 아파트
지역으로, 비아파트 임차 거래가 아예 없어서 빠진 것이지 누락이 아니다.

기준표에 없는 코드가 나오면 폐지코드 매핑으로 설명되는지 대조한다. 설명되지 않는
코드가 남으면 새 개편이 발생했거나 매핑이 낡은 것이므로 확인이 필요하다.

산출물이 다 나온 뒤 실행한다. 기준표 자체는 KIKmix만으로 만들어지므로 이 스크립트가
실패해도 기준표에는 영향이 없다.

입력: data/행정동_기준코드표.csv, data/행정동_폐지코드_매핑.csv
      + 각 산출물(없으면 건너뜀)
출력: data/행정동_소스별_커버리지.csv
"""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

MASTER_PATH = DATA_DIR / "행정동_기준코드표.csv"
LEGACY_PATH = DATA_DIR / "행정동_폐지코드_매핑.csv"
OUT_PATH = DATA_DIR / "행정동_소스별_커버리지.csv"

# (라벨, 파일명 glob 패턴, 코드컬럼 후보, 코드자릿수). 자릿수 10이면 앞 8자리를 취한다.
# 파일명이 소스·시점마다 달라 정확한 이름 대신 패턴으로 찾는다.
SOURCES = [
    ("표면주거비", "표면주거비_행정동_통합*.csv", ["행정동코드_최종"], 10),
    ("생활소비부담지수", "생활소비부담지수_행정동별*.csv", ["행정동_코드", "행정동코드"], 8),
    ("통근부담", "commute_burden_by_home_dong*.csv", ["거주동 코드", "거주동코드"], 8),
    ("생활인구", "*청년생활인구*.csv", ["행정동코드", "행정기관코드"], 8),
    ("청년1인세대", "*청년1인세대*.csv", ["행정기관코드", "행정동코드"], 10),
]

# 코드 컬럼이 없는 산출물은 이름으로 대조한다(차선책).
NAME_SOURCES = [
    ("생활소비부담지수(이름)", "생활소비부담지수_행정동별*.csv", "시군구명", "행정동_코드_명"),
]


def to_code8(s: pd.Series, width: int) -> pd.Series:
    return (pd.to_numeric(s, errors="coerce").astype("Int64")
            .astype(str).str.zfill(width).str[:8])


def main():
    if not MASTER_PATH.exists():
        sys.exit(f"{MASTER_PATH} 이 없습니다. build_region_master.py를 먼저 실행하세요.")

    master = pd.read_csv(MASTER_PATH, encoding="utf-8-sig", dtype=str)
    codes = set(master["행정동코드8"])
    print(f"기준 행정동 {len(master)}개")

    legacy_codes = set()
    if LEGACY_PATH.exists():
        legacy_codes = set(pd.read_csv(LEGACY_PATH, encoding="utf-8-sig", dtype=str)["폐지코드8"])

    for label, pattern, col_candidates, width in SOURCES:
        hits = sorted(DATA_DIR.glob(pattern))
        if not hits:
            print(f"  [{label}] '{pattern}' 에 맞는 파일 없음 - 건너뜀")
            master[f"in_{label}"] = pd.NA
            continue
        path = hits[0]
        df = pd.read_csv(path, encoding="utf-8-sig")
        col = next((c for c in col_candidates if c in df.columns), None)
        if col is None:
            print(f"  [{label}] {path.name}: 코드 컬럼 {col_candidates} 없음 - 건너뜀")
            master[f"in_{label}"] = pd.NA
            continue

        s = set(to_code8(df[col], width))
        master[f"in_{label}"] = master["행정동코드8"].isin(s)
        extra = sorted(s - codes)
        unexplained = [c for c in extra if c not in legacy_codes and c != "<NA>"]
        note = ""
        if extra and not unexplained:
            note = " (전부 폐지코드로 설명됨)"
        print(f"  [{label}] {path.name}\n    보유 {len(s & codes)} / 기준 미포함 {len(extra)}{note}")
        if unexplained:
            print(f"    설명 안 되는 코드 {len(unexplained)}개: {unexplained[:10]}")
            print("    -> 새 행정동 개편이 발생했거나 LEGACY_MAP이 낡았을 수 있음")

    # 코드가 없는 산출물은 이름 대조로 보완하되, 표기 차이가 있으므로 참고용이다
    for label, pattern, gu_col, name_col in NAME_SOURCES:
        hits = sorted(DATA_DIR.glob(pattern))
        if not hits:
            continue
        df = pd.read_csv(hits[0], encoding="utf-8-sig")
        if gu_col not in df.columns or name_col not in df.columns:
            continue
        pairs = set(zip(df[gu_col], df[name_col]))
        hit = [(g, n) in pairs for g, n in zip(master["시군구명"], master["행정동명"])]
        print(f"  [{label}] 이름 기준 매칭 {sum(hit)} / 파일 {len(pairs)}개"
              f" - 표기 차이로 실제보다 낮게 나올 수 있어 참고용")

    flag_cols = [c for c in master.columns if c.startswith("in_")]
    print("\n[요약]")
    for c in flag_cols:
        if master[c].notna().any():
            have = int(master[c].sum())
            print(f"  {c}: 보유 {have} / 누락 {len(master) - have}")

    if "in_표면주거비" in master.columns and master["in_표면주거비"].notna().any():
        gap = master[~master["in_표면주거비"].fillna(False)]
        if len(gap):
            print(f"\n표면주거비 표본이 없는 {len(gap)}개 "
                  "(대단지 아파트 지역 등 비아파트 임차 거래 부재 - 버그 아님)")
            print(gap[["행정동코드8", "시군구명", "행정동명"]].to_string(index=False))

    master.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_PATH}")


if __name__ == "__main__":
    main()