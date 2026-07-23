"""
법정동(시군구 필드) -> 행정동명 / 행정동코드 매칭 스크립트
입력: data/전월세_실거래가_통합.csv, data/대한민국_법정동_행정동_코드.xlsx
출력: data/전월세_실거래가_통합_행정동.csv
"""

from pathlib import Path

import pandas as pd

# ── 경로 설정: 이 파일(src/dong_matcher.py) 기준으로 프로젝트 루트를 찾는다.
# 팀원 누구의 PC에서, 터미널 어느 위치에서 실행해도 항상 같은 data 폴더를 가리킨다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

MERGED_CSV_PATH = DATA_DIR / "전월세_실거래가_통합.csv"
CODE_XLSX_NAME = "대한민국_법정동_행정동_코드.xlsx"  # 팀 공유 드라이브 파일명과 반드시 동일하게 유지
OUTPUT_PATH = DATA_DIR / "전월세_실거래가_통합_행정동.csv"
OFFICIAL_DONG_LIST_PATH = DATA_DIR / "행정동_공식명_목록.csv"


def find_code_xlsx() -> Path:
    """지정된 파일명을 우선 찾고, 없으면 '법정동'이 포함된 xlsx를 대신 찾아
    파일명 표기 차이(공백/언더바, 다운로드 시 (1) 접미사 등)로 인한 실패를 줄인다."""
    exact = DATA_DIR / CODE_XLSX_NAME
    if exact.exists():
        return exact

    candidates = sorted(DATA_DIR.glob("*법정동*.xlsx"))
    if not candidates:
        raise FileNotFoundError(
            f"'{CODE_XLSX_NAME}' 파일을 {DATA_DIR}에서 찾지 못했습니다.\n"
            f"팀 공유 드라이브에서 받은 코드표 xlsx를 data 폴더에 넣어주세요."
        )
    if len(candidates) > 1:
        print(f"경고: '법정동'이 포함된 xlsx가 여러 개 있습니다. 그중 첫 번째를 사용합니다: {candidates[0].name}")
    return candidates[0]


def load_code_table(path: Path) -> pd.DataFrame:
    """법정동-행정동 코드표를 정제한다. 현재 유효한 매핑만 남기고,
    동 단위 정보가 없는 행(구 단위 요약행)은 제외한다."""
    code_df = pd.read_excel(path, sheet_name="KIKmix")
    code_df = code_df[code_df["말소일자"].isna()]
    code_df = code_df.dropna(subset=["읍면동명", "동리명"])
    code_df["행정동코드"] = code_df["행정동코드"].astype(str)
    return code_df


def build_lookup(code_df: pd.DataFrame) -> pd.DataFrame:
    """(시도명, 시군구명, 동리명) 기준으로 행정동 후보를 집계한다.
    법정동 1개가 행정동 여러 개로 쪼개진 경우 후보가 2개 이상 남는다."""
    grouped = (
        code_df.groupby(["시도명", "시군구명", "동리명"])
        .agg(행정동_후보=("읍면동명", lambda s: sorted(set(s))),
             행정동코드_후보=("행정동코드", lambda s: sorted(set(s))))
        .reset_index()
    )
    grouped["후보수"] = grouped["행정동_후보"].apply(len)

    def pick_primary(row):
        # 후보가 1개면 그대로, 여러 개면 법정동명과 이름이 같은 행정동을
        # 우선 채택하고(분동 전 원래 동), 없으면 첫 번째 후보를 임시 채택한다.
        if row["후보수"] == 1:
            return row["행정동_후보"][0], row["행정동코드_후보"][0], False
        exact = [d for d in row["행정동_후보"] if d == row["동리명"]]
        if exact:
            idx = row["행정동_후보"].index(exact[0])
            return row["행정동_후보"][idx], row["행정동코드_후보"][idx], True
        return row["행정동_후보"][0], row["행정동코드_후보"][0], True

    picked = grouped.apply(pick_primary, axis=1, result_type="expand")
    picked.columns = ["행정동명", "행정동코드", "행정동_추정필요"]
    return pd.concat([grouped, picked], axis=1)


def split_address(addr):
    """'서울특별시 종로구 혜화동' -> (시도명, 시군구명, 법정동명)"""
    if pd.isna(addr):
        return pd.Series([None, None, None])
    parts = str(addr).split()
    if len(parts) < 3:
        return pd.Series([parts[0] if parts else None,
                           parts[1] if len(parts) > 1 else None, None])
    시도, 구 = parts[0], parts[1]
    법정동 = " ".join(parts[2:])
    return pd.Series([시도, 구, 법정동])


def main():
    if not MERGED_CSV_PATH.exists():
        raise FileNotFoundError(
            f"{MERGED_CSV_PATH} 이 없습니다. housing_preprocessor.py를 먼저 실행하세요."
        )

    df = pd.read_csv(MERGED_CSV_PATH, encoding="utf-8-sig")
    print(f"원본 행 수: {len(df)}")

    df[["시도명", "시군구명", "법정동명"]] = df["시군구"].apply(split_address)

    code_path = find_code_xlsx()
    print(f"코드표 파일: {code_path.name}")
    code_df = load_code_table(code_path)
    lookup = build_lookup(code_df)

    # 공식 행정동 참조표(시군구명,행정동명,행정동코드). 서울로 한정하고
    # code_df 원본 읍면동명 전체를 쓴다(lookup의 대표값만 쓰면 가양2동 등
    # 대표로 안 뽑힌 동이 누락되고, 전국 단위로 하면 다른 지역 동명이인
    # 때문에 정규화가 잘못 건너뛰어짐).
    seoul_code_df = code_df[code_df["시도명"] == "서울특별시"].copy()
    official_ref = (
        seoul_code_df[["시군구명", "읍면동명", "행정동코드"]]
        .dropna(subset=["읍면동명"])
        .drop_duplicates()
        .rename(columns={"읍면동명": "행정동명"})
        .sort_values(["시군구명", "행정동명"])
    )
    official_ref["행정동코드"] = official_ref["행정동코드"].astype(str)
    official_ref.to_csv(OFFICIAL_DONG_LIST_PATH, index=False, encoding="utf-8-sig")
    print(f"공식 행정동 참조표 저장: {OFFICIAL_DONG_LIST_PATH} "
          f"({official_ref['행정동명'].nunique()}개 고유 이름, {len(official_ref)}행 - "
          f"이름 겹치는 행정동이 있으면 행 수가 이름 수보다 많음)")
    dup_names = official_ref["행정동명"].value_counts()
    dup_names = dup_names[dup_names > 1]
    if len(dup_names) > 0:
        print(f"⚠️ 서울 안에서 이름이 겹치는 행정동 {len(dup_names)}개 발견 (반드시 구까지 같이 봐야 함):")
        for name, cnt in dup_names.items():
            gus = official_ref.loc[official_ref["행정동명"] == name, "시군구명"].tolist()
            print(f"   {name}: {gus}")

    merged = df.merge(
        lookup[["시도명", "시군구명", "동리명", "행정동명", "행정동코드", "후보수", "행정동_추정필요"]],
        left_on=["시도명", "시군구명", "법정동명"],
        right_on=["시도명", "시군구명", "동리명"],
        how="left",
    )

    total = len(merged)
    unmatched = merged["행정동명"].isna().sum()
    ambiguous = (merged["행정동_추정필요"] == True).sum()

    print(f"\n매칭 결과")
    print(f"  전체 행: {total}")
    print(f"  매칭 성공: {total - unmatched} ({(total-unmatched)/total*100:.1f}%)")
    print(f"  매칭 실패: {unmatched}")
    print(f"  분동(법정동 1개 -> 행정동 여러 개)로 추정 채택된 행: {ambiguous}")

    if unmatched > 0:
        print("\n매칭 실패한 법정동 상위 목록 (표기 차이 등 확인 필요):")
        fail_summary = merged[merged["행정동명"].isna()]["시군구"].value_counts().head(20)
        print(fail_summary)

    if ambiguous > 0:
        print("\n분동으로 대표값을 채택한 법정동 목록 (방법론 문서에 한계로 명시 권장):")
        amb_summary = (
            merged[merged["행정동_추정필요"] == True][["시군구", "행정동명"]]
            .drop_duplicates()
        )
        print(amb_summary.to_string(index=False))

    merged = merged.drop(columns=["동리명"])
    merged.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()