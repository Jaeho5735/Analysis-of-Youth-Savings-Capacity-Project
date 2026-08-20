"""
extract_adjacent_by_bjd.py — 법정동 공유 기반 인접 행정동 후보 추출

배경
----
도로명 공유 방식(extract_adjacent_dongs.py)은 kakao_cache.json의 구조상
(자치구,도로명) 1키에 값이 1개만 저장돼 있어 원천적으로 작동하지 않았다.
대신 "법정동 분동" 관계를 이용한다 — 하나의 법정동이 여러 행정동으로
쪼개진 경우(예: 봉천동 -> 보라매동/청림동/.../인헌동 9개), 그 행정동들은
전부 원래 하나였던 동네이므로 물리적으로 서로 인접해 있을 가능성이 높다.
반대로 하나의 행정동이 여러 법정동을 포함하는 경우도 있어, 그 경로로도
인접 후보를 찾을 수 있다.

이 스크립트는 초안(원시 후보 목록)만 만든다. 채택 여부는 사람이 판단한다.
읽기 전용 — 어떤 파일도 수정하지 않는다.

사용법
------
    python src/analysis/extract_adjacent_by_bjd.py
    python src/analysis/extract_adjacent_by_bjd.py <PROJECT_ROOT>

흐름
----
1) xlsx(KIKmix)에서 시도명==서울특별시 & 말소일자 비어있음 & 읍면동명/법정동코드
   있는 행만 남긴다.
2) 행정동코드(10자리) 앞 8자리를 결합키(행정동코드8)로 쓴다.
3) 법정동코드 -> {행정동코드8, ...} , 행정동코드8 -> {법정동코드, ...} 양방향
   그룹을 만든다.
4) 커버리지 CSV의 in_표면주거비 == False 7개 동을 결측 동으로 잡는다.
5) 결측 동마다: 그 동이 속한 법정동들을 찾고, 그 법정동들을 공유하는 다른
   행정동을 후보로 모아 공유_법정동수 내림차순 정렬. 결측 동끼리는 후보에서
   제외(둘 다 값이 없으므로), in_표면주거비 == True인 동만 후보로 남긴다.
"""

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

COVERAGE_FILE = "행정동_소스별_커버리지.csv"
XLSX_FILE = "대한민국 법정동 행정동 코드.xlsx"
XLSX_SHEET = "KIKmix"
OUTPUT_FILE = "fallback_후보_법정동기반.csv"

COVERAGE_FLAG_COL = "in_표면주거비"
COVERAGE_CODE8_COL = "행정동코드8"
COVERAGE_GU_COL = "시군구명"
COVERAGE_NAME_COL = "행정동명"


def find_root(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1]).resolve()
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "data").is_dir() and (parent / "src").is_dir():
            return parent
    return Path.cwd()


def norm_dong(name) -> str:
    """행정동명 표기 변이를 흡수하기 위한 정규화. (xlsx쪽 이름과 커버리지쪽
    이름이 다르게 표기된 경우를 잡아내는 QC 대조에만 쓴다. join 키는 코드다.)"""
    if name is None:
        return ""
    s = str(name).strip()
    s = s.replace(" ", "").replace("·", "")
    s = s.replace("제", "")
    return s


def load_xlsx(data_dir: Path) -> pd.DataFrame:
    path = data_dir / XLSX_FILE
    df = pd.read_excel(path, sheet_name=XLSX_SHEET)
    before = len(df)
    df = df[df["시도명"] == "서울특별시"]
    df = df[df["말소일자"].isna()]
    df = df.dropna(subset=["읍면동명", "법정동코드"])
    print(f"[STEP 1] xlsx 원본 {before}행 -> 서울/유효/동단위 필터 후 {len(df)}행")

    df = df.copy()
    df["행정동코드8"] = df["행정동코드"].astype("int64").astype(str).str.slice(0, 8)
    df["법정동코드"] = df["법정동코드"].astype("int64")
    return df


def build_groups(xlsx_df: pd.DataFrame):
    bjd_to_hjd = defaultdict(set)   # 법정동코드 -> {행정동코드8}
    hjd_to_bjd = defaultdict(set)   # 행정동코드8 -> {법정동코드}
    hjd_name = {}                   # 행정동코드8 -> 읍면동명 (xlsx쪽)
    hjd_gu = {}                     # 행정동코드8 -> 시군구명 (xlsx쪽)
    bjd_name = {}                   # 법정동코드 -> 동리명

    for row in xlsx_df.itertuples(index=False):
        h8 = row.행정동코드8
        b = row.법정동코드
        bjd_to_hjd[b].add(h8)
        hjd_to_bjd[h8].add(b)
        hjd_name[h8] = row.읍면동명
        hjd_gu[h8] = row.시군구명
        bjd_name[b] = row.동리명

    return bjd_to_hjd, hjd_to_bjd, hjd_name, hjd_gu, bjd_name


def main():
    root = find_root(sys.argv)
    data_dir = root / "data"
    docs_dir = root / "docs"
    if not data_dir.is_dir():
        sys.exit(f"data/ 폴더를 찾지 못했습니다: {data_dir}")

    print(f"[루트] {root}")

    xlsx_df = load_xlsx(data_dir)

    print("\n[STEP 2/3] 행정동코드8 결합키 생성 및 법정동<->행정동 양방향 그룹 구성 중...")
    bjd_to_hjd, hjd_to_bjd, hjd_name, hjd_gu, bjd_name = build_groups(xlsx_df)
    unique_h8 = len(hjd_to_bjd)
    unique_bjd = len(bjd_to_hjd)
    print(f"  고유 행정동코드8: {unique_h8}개")
    print(f"  고유 법정동코드: {unique_bjd}개")
    multi_bjd_hjd = {h: bs for h, bs in hjd_to_bjd.items() if len(bs) >= 2}
    multi_hjd_bjd = {b: hs for b, hs in bjd_to_hjd.items() if len(hs) >= 2}
    print(f"  법정동을 2개 이상 포함하는 행정동: {len(multi_bjd_hjd)}개")
    print(f"  행정동으로 2개 이상 쪼개진 법정동: {len(multi_hjd_bjd)}개")

    print("\n[STEP 4] 커버리지 CSV 로드 및 결측 7개 동 특정")
    coverage_path = data_dir / COVERAGE_FILE
    coverage_df = pd.read_csv(coverage_path, encoding="utf-8-sig")
    coverage_df["행정동코드8_str"] = coverage_df[COVERAGE_CODE8_COL].astype("int64").astype(str)

    total_coverage = len(coverage_df)
    print(f"  커버리지 CSV 전체 행: {total_coverage}개")
    print(f"  xlsx 필터 후 고유 행정동코드8: {unique_h8}개 "
          f"({'일치' if unique_h8 == total_coverage else '불일치 -- 확인 필요'})")

    # QC: xlsx 쪽 이름과 커버리지 쪽 공식 이름이 (정규화 후에도) 다른 코드가 있는지
    name_mismatch = []
    for _, row in coverage_df.iterrows():
        h8 = row["행정동코드8_str"]
        if h8 in hjd_name and norm_dong(hjd_name[h8]) != norm_dong(row[COVERAGE_NAME_COL]):
            name_mismatch.append((h8, hjd_name[h8], row[COVERAGE_NAME_COL]))
    if name_mismatch:
        print(f"  경고: xlsx 읍면동명과 커버리지 행정동명이 다른 코드 {len(name_mismatch)}개")
        for h8, xlsx_name, cov_name in name_mismatch:
            print(f"    {h8}: xlsx={xlsx_name!r} vs 커버리지={cov_name!r}")
    else:
        print("  xlsx 읍면동명과 커버리지 행정동명 전부 일치 (정규화 기준)")

    missing_df = coverage_df[coverage_df[COVERAGE_FLAG_COL] == False]  # noqa: E712
    covered_codes = set(
        coverage_df.loc[coverage_df[COVERAGE_FLAG_COL] == True, "행정동코드8_str"]  # noqa: E712
    )
    print(f"  결측 동(in_표면주거비=False): {len(missing_df)}개")

    print("\n[STEP 5] 결측 동별 인접 후보(법정동 공유 기준) 추출 중...")
    out_rows = []
    zero_candidate = []
    not_in_xlsx = []

    for _, row in missing_df.iterrows():
        h8 = row["행정동코드8_str"]
        gu = row[COVERAGE_GU_COL]
        name = row[COVERAGE_NAME_COL]

        own_bjd = hjd_to_bjd.get(h8)
        if not own_bjd:
            not_in_xlsx.append(f"{gu} {name} ({h8})")
            print(f"\n  [{gu} {name}] -- xlsx에서 이 행정동코드8을 찾지 못했습니다. 코드 불일치 의심.")
            continue

        # 후보동코드 -> 공유하는 법정동코드 집합
        shared = defaultdict(set)
        for b in own_bjd:
            for h8_c in bjd_to_hjd.get(b, set()):
                if h8_c == h8:
                    continue
                shared[h8_c].add(b)

        rows_for_this = []
        for h8_c, shared_bjd in shared.items():
            if h8_c not in covered_codes:
                # 결측 동이거나(둘 다 값 없음 -> 후보 불가), 커버리지 표에 아예 없는 코드
                continue
            cand_row = coverage_df.loc[coverage_df["행정동코드8_str"] == h8_c].iloc[0]
            rows_for_this.append({
                "결측동": name,
                "결측동코드": h8,
                "자치구": gu,
                "후보동": cand_row[COVERAGE_NAME_COL],
                "후보동코드": h8_c,
                "공유_법정동수": len(shared_bjd),
                "공유_법정동명": ",".join(sorted(bjd_name.get(b, str(b)) for b in shared_bjd)),
                "같은자치구": "Y" if cand_row[COVERAGE_GU_COL] == gu else "N",
                "주거비산출": "Y",
                "채택": "",
                "메모": "",
            })

        rows_for_this.sort(key=lambda r: r["공유_법정동수"], reverse=True)
        out_rows.extend(rows_for_this)

        print(f"\n  [{gu} {name}] (행정동코드8={h8})")
        print(f"    속한 법정동: {sorted(bjd_name.get(b, str(b)) for b in own_bjd)}")
        if rows_for_this:
            for r in rows_for_this:
                print(f"    후보: {r['후보동']} (공유법정동수={r['공유_법정동수']}, "
                      f"같은자치구={r['같은자치구']}, 공유법정동={r['공유_법정동명']})")
        else:
            print("    후보: 없음")
            zero_candidate.append(f"{gu} {name}")

    print("\n[요약] 후보가 하나도 없는 결측 동:")
    if zero_candidate:
        for d in zero_candidate:
            print(f"  {d}")
    else:
        print("  없음 (전부 후보 1개 이상)")

    if not_in_xlsx:
        print("\n[경고] xlsx에서 행정동코드8을 못 찾은 결측 동:")
        for d in not_in_xlsx:
            print(f"  {d}")

    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / OUTPUT_FILE
    out_df = pd.DataFrame(out_rows, columns=[
        "결측동", "결측동코드", "자치구", "후보동", "후보동코드", "공유_법정동수",
        "공유_법정동명", "같은자치구", "주거비산출", "채택", "메모",
    ])
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {out_path} ({len(out_df)}행)")


if __name__ == "__main__":
    main()
