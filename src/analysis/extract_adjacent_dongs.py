"""
extract_adjacent_dongs.py — kakao_cache.json 기반 인접 행정동 후보 추출 (도로 공유 방식)

배경
----
행정동 좌표 소스가 레포 안에 없다는 건 이미 확인됐다(check_fallback_candidates.py).
대신 kakao_cache.json(도로명주소 -> 행정동명, 약 6만 건)을 역이용한다. 도로는
동 경계를 가로질러 이어지는 경우가 많으므로, 같은 (자치구, 도로명)이 여러
행정동에 걸쳐 나타나면 그 동들은 서로 맞닿아 있을 가능성이 높다고 본다.

한계: 이 방법은 "같은 도로를 공유"를 "물리적으로 인접"의 근사치로 쓴다. 테헤란로처럼
긴 도로가 여러 동을 순서대로 지나가면, 실제로는 사이에 다른 동이 끼어 있어도
전부 "인접"으로 잡힐 수 있다. 이건 방법 자체의 한계이며, 후보 채택 여부는
사람이 판단한다 — 이 스크립트는 초안(원시 후보 목록)만 만든다.

이 스크립트는 어떤 파일도 수정하지 않는다 (읽기 전용).

사용법
------
    python src/analysis/extract_adjacent_dongs.py
    python src/analysis/extract_adjacent_dongs.py <PROJECT_ROOT>

흐름
----
1) kakao_cache.json 로드. key = "시도|||구|||도로명" -> value = 행정동명 (또는 null)
2) (자치구, 도로명) -> {정규화된 행정동명, ...} 으로 묶는다.
3) 원소가 2개 이상인 (자치구, 도로명)을 "동 경계 도로"로 채택해 인접 그래프를 만든다.
4) norm_dong()으로 정규화한 뒤 커버리지 표(행정동_소스별_커버리지.csv)의 공식
   행정동명 목록과 대조한다. 매칭 안 되는 이름은 경고로 모아 그대로 보여준다.
   -> 표기 변이(공백/제N동 등)면 norm_dong()만 보완해서 재실행할 것.
      그 외 로직(그래프 구성, 후보 산출)은 건드리지 말 것.
5) 결측 7개 동마다, 인접 그래프에서 연결된 동 중 표면주거비를 보유한
   (in_표면주거비 == True) 동만 후보로 추려 출력한다.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

COVERAGE_FILE = "행정동_소스별_커버리지.csv"
COVERAGE_FLAG_COL = "in_표면주거비"
COVERAGE_GU_COL = "시군구명"
COVERAGE_NAME_COL = "행정동명"
KAKAO_CACHE_FILE = "kakao_cache.json"


def find_root(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1]).resolve()
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "data").is_dir() and (parent / "src").is_dir():
            return parent
    return Path.cwd()


def norm_dong(name) -> str:
    """행정동명 표기 변이를 흡수하기 위한 정규화.
    커버리지 표와 매칭이 안 되는 이름이 발견되면 이 함수만 보완해서 재실행할 것."""
    if name is None:
        return ""
    s = str(name).strip()
    s = s.replace(" ", "")
    s = s.replace("제", "")  # "제1동" 같은 표기를 "1동"으로 흡수
    return s


def load_kakao_pairs(data_dir: Path):
    """kakao_cache.json에서 (자치구, 도로명, 행정동명) 세 쌍을 뽑는다."""
    path = data_dir / KAKAO_CACHE_FILE
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    pairs = []
    skipped_null = 0
    skipped_malformed = 0
    for key, value in raw.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            skipped_null += 1
            continue
        parts = key.split("|||")
        if len(parts) != 3:
            skipped_malformed += 1
            continue
        _sido, gu, road = parts
        pairs.append((gu, road, value))
    return pairs, skipped_null, skipped_malformed, len(raw), raw


def build_road_groups(pairs):
    """(자치구, 도로명) -> {정규화된 행정동명, ...}"""
    groups = defaultdict(set)
    for gu, road, dong in pairs:
        groups[(gu, road)].add(norm_dong(dong))
    return groups


def build_adjacency(groups):
    """정규화된 행정동명 기준 인접 그래프. key = (자치구, norm_dong), value = {norm_dong, ...}"""
    adjacency = defaultdict(set)
    for (gu, _road), dongs in groups.items():
        if len(dongs) < 2:
            continue
        for d1 in dongs:
            for d2 in dongs:
                if d1 != d2:
                    adjacency[(gu, d1)].add(d2)
    return adjacency


def main():
    root = find_root(sys.argv)
    data_dir = root / "data"
    if not data_dir.is_dir():
        sys.exit(f"data/ 폴더를 찾지 못했습니다: {data_dir}")

    print(f"[루트] {root}")

    print("\n[STEP 1] kakao_cache.json 로드 중...")
    pairs, skipped_null, skipped_malformed, total_keys, raw_cache = load_kakao_pairs(data_dir)
    print(f"  전체 키 {total_keys}개 중 값 없음(null) {skipped_null}개, 형식 이상 {skipped_malformed}개 제외")
    print(f"  (자치구, 도로명, 행정동) 쌍 {len(pairs)}건 추출")

    if len(pairs) == 0:
        print("\n=== 추출 0건 — kakao_cache 구조가 예상과 다릅니다 ===")
        print("샘플 키/값 5건:")
        for i, (k, v) in enumerate(raw_cache.items()):
            if i >= 5:
                break
            print(f"  {k!r} -> {v!r}")
        sys.exit(1)

    print("\n[STEP 2] (자치구, 도로명) 단위로 묶는 중 (정규화된 행정동명 기준)...")
    groups = build_road_groups(pairs)
    multi_dong_roads = {k: v for k, v in groups.items() if len(v) >= 2}
    print(f"  고유 (자치구, 도로명) 조합 {len(groups)}개")
    print(f"  2개 이상 행정동에 걸친 도로 {len(multi_dong_roads)}개")

    print("\n[STEP 3] 인접 그래프 구성 중...")
    adjacency = build_adjacency(groups)
    n_dongs_with_neighbor = len(adjacency)
    print(f"  인접 관계를 하나 이상 가진 (자치구, 동) {n_dongs_with_neighbor}개")

    print("\n[STEP 4] 커버리지 표와 행정동명 대조 중...")
    coverage_path = data_dir / COVERAGE_FILE
    coverage_df = pd.read_csv(coverage_path, encoding="utf-8-sig")
    official_names = set(coverage_df[COVERAGE_NAME_COL].map(norm_dong))

    raw_dongs = sorted({d for _gu, _road, d in pairs})
    unmatched = [d for d in raw_dongs if norm_dong(d) not in official_names]
    if unmatched:
        print(f"  경고: 커버리지 표에 없는 행정동명 {len(unmatched)}개")
        for name in unmatched:
            print(f"    {name!r}  (정규화 -> {norm_dong(name)!r})")
    else:
        print("  전부 매칭됨")

    print("\n[STEP 5] 결측 7개 동별 인접 후보 (표면주거비 보유 동만)")
    missing_df = coverage_df[coverage_df[COVERAGE_FLAG_COL] == False]  # noqa: E712
    covered_names = set(
        coverage_df.loc[coverage_df[COVERAGE_FLAG_COL] == True, COVERAGE_NAME_COL].map(norm_dong)  # noqa: E712
    )

    zero_candidate_dongs = []
    for _, row in missing_df.iterrows():
        gu = row[COVERAGE_GU_COL]
        name = row[COVERAGE_NAME_COL]
        neighbors = adjacency.get((gu, norm_dong(name)), set())
        candidates = sorted(n for n in neighbors if n in covered_names)
        excluded = sorted(n for n in neighbors if n not in covered_names)

        print(f"\n  [{gu} {name}]")
        print(f"    전체 인접 동(도로 공유 기준): {sorted(neighbors) if neighbors else '없음'}")
        print(f"    표면주거비 보유 후보: {candidates if candidates else '없음'}")
        if excluded:
            print(f"    (제외 — 표면주거비 미보유 또는 결측 동: {excluded})")
        if not candidates:
            zero_candidate_dongs.append(f"{gu} {name}")

    print("\n[요약] 후보가 하나도 없는 결측 동:")
    if zero_candidate_dongs:
        for d in zero_candidate_dongs:
            print(f"  {d}")
    else:
        print("  없음 (전부 후보 1개 이상)")


if __name__ == "__main__":
    main()
