"""
check_fallback_candidates.py — 결측 표면주거비 행정동 fallback 후보 진단

배경
----
LOCA 서비스에서 표면주거비가 결측인 행정동(427개 중 7개)을 사용자가 조회했을 때,
값을 임의로 대체하지 않고 "같은 자치구 + 직선거리 N km 이내"의 인근 동을 후보로
제시하려 한다. 이 스크립트는 그게 실제로 가능한지(좌표 소스가 있는지), 가능하다면
반경을 몇 km로 잡아야 하는지를 읽기 전용으로 진단한다.

이 스크립트는 어떤 파일도 수정하지 않는다 (읽기 전용 진단).

사용법
------
    python src/analysis/check_fallback_candidates.py
    python src/analysis/check_fallback_candidates.py <PROJECT_ROOT>

흐름
----
1) data/ 아래 모든 csv를 스캔해 위도/경도로 보이는 컬럼(LAT_PAT / LNG_PAT)이
   함께 있는 파일을 찾는다.
   -> 명백히 좌표 컬럼인데 정규식이 못 잡는 경우, 아래 LAT_PAT / LNG_PAT만
      수정해서 재실행할 것. 그 외 로직은 건드리지 말 것.
   -> 못 찾으면: 스캔한 모든 csv의 컬럼 목록을 출력하고, data/ 안의
      geojson/shp류 파일 존재 여부, src/ 안의 Tmap API·좌표 처리 코드
      존재 여부를 추가로 확인한 뒤 멈춘다.
2) 좌표를 확보했으면, 행정동_소스별_커버리지.csv의 in_표면주거비 == False로
   결측 7개 동을 특정하고, 각 결측 동마다 "같은 자치구(시군구명)" 안에서
   표면주거비가 있는 다른 동까지의 하버사인 직선거리를 계산해
   반경별[1, 2, 3, 5km] 후보 수 표를 만든다.
"""

import re
import sys
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# 좌표 컬럼 판별용 정규식. 명백히 좌표 컬럼인데 못 잡히는 경우에만 이 두 줄을
# 수정해서 재실행할 것. 그 외 로직(반경 계산 등)은 건드리지 말 것.
LAT_PAT = re.compile(r"(위도|lat(itude)?)", re.IGNORECASE)
LNG_PAT = re.compile(r"(경도|lng|lon(gitude)?)", re.IGNORECASE)

# 좌표 파일을 행정동코드에 join하기 위한 코드 컬럼 판별용
DONG_CODE_PAT = re.compile(r"행정동.?코드|adm.?dong.?cd", re.IGNORECASE)

RADII_KM = [1, 2, 3, 5]

# 결측 7개 동을 정확히 판정하는 기준 파일 (전수 427개, 소스별 포함 여부 플래그 보유)
COVERAGE_FILE = "행정동_소스별_커버리지.csv"
COVERAGE_FLAG_COL = "in_표면주거비"
COVERAGE_CODE_COL = "행정동코드10"
COVERAGE_NAME_COL = "행정동명"
COVERAGE_GU_COL = "시군구명"


def find_root(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1]).resolve()
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "data").is_dir() and (parent / "src").is_dir():
            return parent
    return Path.cwd()


def read_csv_safely(path: Path, **kwargs):
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, **kwargs)
        except UnicodeDecodeError:
            continue
        except Exception:
            return None
    return None


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0088  # 지구 평균 반경(km)
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def scan_for_coordinates(data_dir: Path):
    """data/ 안의 모든 csv에서 위도/경도로 보이는 컬럼을 찾는다.

    반환: (hits, all_columns)
      hits        = [(path, lat_cols, lng_cols), ...]
      all_columns = [(파일명, [컬럼...]), ...]  (스캔한 전체 파일, 진단용)
    """
    hits = []
    all_columns = []
    for p in sorted(data_dir.glob("*.csv")):
        df = read_csv_safely(p, nrows=1)
        if df is None:
            all_columns.append((p.name, ["<읽기 실패>"]))
            continue
        cols = list(df.columns)
        all_columns.append((p.name, cols))
        lat_cols = [c for c in cols if LAT_PAT.search(c)]
        lng_cols = [c for c in cols if LNG_PAT.search(c)]
        if lat_cols and lng_cols:
            hits.append((p, lat_cols, lng_cols))
    return hits, all_columns


def report_no_coordinates(root: Path, all_columns):
    """좌표가 아예 없을 때: geojson/shp, xlsx, Tmap 관련 코드 존재 여부를 추가 확인."""
    print("\n=== 좌표 소스를 찾지 못했습니다 ===")
    print(f"data/ 아래 csv {len(all_columns)}개를 스캔했지만 위도/경도로 보이는")
    print("컬럼(LAT_PAT / LNG_PAT 매칭)이 함께 있는 파일이 없습니다.\n")

    print("--- 스캔한 전체 컬럼 목록 ---")
    for name, cols in all_columns:
        print(f"[{name}]")
        print(f"  {cols}")

    print("\n--- data/ 안의 geojson/shp류 파일 확인 ---")
    geo_files = []
    for ext in ("*.geojson", "*.shp", "*.gpkg"):
        geo_files += list((root / "data").rglob(ext))
    if geo_files:
        for f in geo_files:
            print(f"  {f.relative_to(root)}")
    else:
        print("  없음")

    print("\n--- data/ 안의 xlsx 파일 (openpyxl 미설치 시 컬럼 확인은 생략, 존재만 보고) ---")
    xlsx_files = list((root / "data").glob("*.xlsx"))
    if xlsx_files:
        for f in xlsx_files:
            print(f"  {f.relative_to(root)}  <- 좌표 포함 여부 수동 확인 필요")
    else:
        print("  없음")

    print("\n--- src/ 안의 Tmap API / 좌표 처리 코드 확인 ---")
    src_dir = root / "src"
    pattern = re.compile(
        r"tmap|위도|경도|latitude|longitude|geopy|geopandas", re.IGNORECASE
    )
    found_any = False
    for py in sorted(src_dir.rglob("*.py")):
        try:
            text = py.read_text(encoding="utf-8")
        except Exception:
            continue
        if pattern.search(text):
            found_any = True
            print(f"  {py.relative_to(root)}")
    if not found_any:
        print("  없음 — src/ 안에 Tmap API 호출이나 좌표 처리 코드가 없습니다.")

    print("\n결론: 이 저장소 안에서 곧바로 쓸 수 있는 행정동 좌표 소스가 없습니다.")
    print("(직접 다운로드하거나 패키지를 설치하지는 않았습니다.)")


def choose_coordinate_source(hits, coverage_df: pd.DataFrame):
    """여러 파일이 걸릴 경우, 커버리지 파일의 행정동코드와 매칭되는 행이
    가장 많은 (파일, lat컬럼, lng컬럼, code컬럼) 조합을 채택한다."""
    best = None
    best_matches = -1
    for path, lat_cols, lng_cols in hits:
        df = read_csv_safely(path)
        if df is None:
            continue
        code_cols = [c for c in df.columns if DONG_CODE_PAT.search(c)]
        lat_col, lng_col = lat_cols[0], lng_cols[0]
        if code_cols:
            code_col = code_cols[0]
            matches = coverage_df[COVERAGE_CODE_COL].isin(df[code_col]).sum()
        else:
            code_col = None
            matches = 0
        if matches > best_matches:
            best = (path, df, lat_col, lng_col, code_col)
            best_matches = matches
    return best, best_matches


def build_radius_table(coverage_df: pd.DataFrame, coord_df: pd.DataFrame,
                        lat_col: str, lng_col: str, code_col: str) -> pd.DataFrame:
    merged = coverage_df.merge(
        coord_df[[code_col, lat_col, lng_col]],
        left_on=COVERAGE_CODE_COL, right_on=code_col, how="left",
    )
    missing = merged[merged[COVERAGE_FLAG_COL] == False]  # noqa: E712
    covered = merged[merged[COVERAGE_FLAG_COL] == True]  # noqa: E712

    rows = []
    for _, m in missing.iterrows():
        row = {
            "행정동코드": m[COVERAGE_CODE_COL],
            "행정동명": m[COVERAGE_NAME_COL],
            "자치구": m[COVERAGE_GU_COL],
        }
        if pd.isna(m[lat_col]) or pd.isna(m[lng_col]):
            row["자치구내_후보총수"] = None
            row["최근접_거리_km"] = None
            for r in RADII_KM:
                row[f"{r}km_이내_후보수"] = None
            row["비고"] = "결측 동 자체의 좌표가 없어 거리 계산 불가"
            rows.append(row)
            continue

        same_gu = covered[covered[COVERAGE_GU_COL] == m[COVERAGE_GU_COL]].dropna(
            subset=[lat_col, lng_col]
        )
        dists = same_gu.apply(
            lambda r: haversine_km(m[lat_col], m[lng_col], r[lat_col], r[lng_col]),
            axis=1,
        )
        row["자치구내_후보총수"] = len(same_gu)
        row["최근접_거리_km"] = round(dists.min(), 3) if len(dists) else None
        for r in RADII_KM:
            row[f"{r}km_이내_후보수"] = int((dists <= r).sum()) if len(dists) else 0
        row["비고"] = ""
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    root = find_root(sys.argv)
    data_dir = root / "data"
    if not data_dir.is_dir():
        sys.exit(f"data/ 폴더를 찾지 못했습니다: {data_dir}")

    print(f"[루트] {root}")
    print("[STEP 1] data/ 안에서 위도/경도 컬럼 스캔 중...")
    hits, all_columns = scan_for_coordinates(data_dir)

    coverage_path = data_dir / COVERAGE_FILE
    coverage_df = read_csv_safely(coverage_path)
    if coverage_df is None:
        sys.exit(f"{COVERAGE_FILE}을 읽지 못했습니다: {coverage_path}")

    total = len(coverage_df)
    missing_n = int((coverage_df[COVERAGE_FLAG_COL] == False).sum())  # noqa: E712
    print(f"[참고] {COVERAGE_FILE} 기준 전체 {total}개 동 중 표면주거비 결측 {missing_n}개")

    if not hits:
        report_no_coordinates(root, all_columns)
        sys.exit(1)

    print(f"[STEP 1] 좌표로 보이는 컬럼을 가진 파일 {len(hits)}개 발견. 최적 소스 선택 중...")
    best, best_matches = choose_coordinate_source(hits, coverage_df)
    if best is None or best[4] is None or best_matches == 0:
        print("좌표 컬럼은 있으나 행정동코드로 join할 수 있는 컬럼을 찾지 못했습니다.")
        print("아래 후보들을 직접 확인해 주세요:")
        for path, lat_cols, lng_cols in hits:
            print(f"  {path} : lat={lat_cols} lng={lng_cols}")
        sys.exit(1)

    path, coord_df, lat_col, lng_col, code_col = best
    print(f"[STEP 1] 좌표 소스 채택: {path.relative_to(root)}")
    print(f"          lat={lat_col!r} lng={lng_col!r} code={code_col!r}")
    print(f"          커버리지 대상 {total}개 동 중 {best_matches}개 좌표 매칭")

    print("\n[STEP 2] 결측 7개 동 목록")
    missing_df = coverage_df[coverage_df[COVERAGE_FLAG_COL] == False]  # noqa: E712
    print(missing_df[[COVERAGE_CODE_COL, COVERAGE_GU_COL, COVERAGE_NAME_COL]].to_string(index=False))

    print("\n[STEP 2] 반경별 후보 수 계산 중...")
    table = build_radius_table(coverage_df, coord_df, lat_col, lng_col, code_col)
    print(table.to_string(index=False))

    print("\n[요약] 자치구내 최근접 거리가 2km를 넘는 동:")
    over_2km = table[table["최근접_거리_km"] > 2]
    if len(over_2km):
        print(over_2km[["행정동명", "자치구", "최근접_거리_km"]].to_string(index=False))
    else:
        print("  없음 (전부 2km 이내)")


if __name__ == "__main__":
    main()
