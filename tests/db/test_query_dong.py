"""5순위: 조회 계층이 화면 기대와 맞는 결과를 돌려주는지 검사한다.

배경
----
list_work_options / list_home_options / nearest_routed_work / policy_coverage 는
모두 `except Exception: return []` 로 감싸여 있다.
화면이 죽는 것보다 자동완성만 안 되는 편이 낫다는 판단이고 그건 옳지만,
컬럼명이 바뀌거나 SQL 이 깨져도 **조용히 빈 목록**이 된다.
화면에서는 "갈 수 있는 곳이 없다"로 보여 원인을 찾기 어렵다.

2026-09-07 에 app.py 가 list_work_options 를 import 하지 않은 채 호출해
근무지 자동완성 범위 제한이 한 번도 동작하지 않았다. 같은 방식으로 숨었다.

그래서 이 파일은 **알려진 입력에서 결과가 비어 있지 않은지**를 먼저 본다.
빈 목록이 정상인 경우와 고장인 경우를 구분하는 것이 요점이다.

DB 가 필요하다. pytest -m "not db" 로 빼면 이 파일 전체가 제외된다.
"""

import pytest

pytest.importorskip("pymysql", reason="DB 접속에 pymysql 이 필요하다")

from src.db.query_dong import (list_dongs, list_home_options,  # noqa: E402
                               list_work_options, nearest_routed_work,
                               policy_coverage)

pytestmark = pytest.mark.db

HOME_NAME = "역삼1동"
WORK_NAME = "소공동"


def _code_of(name):
    rows = list_dongs(name, limit=5)
    hit = next((r for r in rows
                if r["name"].replace("제", "") == name.replace("제", "")), None)
    if not hit:
        pytest.skip(f"'{name}' 을 행정동 목록에서 찾지 못했다")
    return hit["code"]


@pytest.fixture(scope="module")
def home_code():
    return _code_of(HOME_NAME)


@pytest.fixture(scope="module")
def work_code():
    return _code_of(WORK_NAME)


# ── list_dongs ──────────────────────────────────────────────

def test_list_dongs_returns_rows():
    rows = list_dongs(limit=1000)
    assert rows, "행정동 목록이 비었다"
    assert len(rows) > 400, f"행정동이 {len(rows)}개뿐이다. 서울 전체가 아니다"


def test_list_dongs_shape():
    """화면이 쓰는 세 칸이 다 있는지.

    app.py 가 f"{r['gu']} {r['name']}" 로 라벨을 만들고 r['code'] 를 값으로 쓴다.
    """
    row = list_dongs(limit=1)[0]
    assert set(row) >= {"code", "name", "gu"}
    assert row["gu"], "자치구가 비었다"
    assert len(str(row["code"])) == 8, f"행정동 코드가 8자리가 아니다: {row['code']}"


def test_list_dongs_codes_are_unique():
    rows = list_dongs(limit=1000)
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes)), "행정동 코드가 중복된다"


def test_list_dongs_sorted_by_gu_then_name():
    rows = list_dongs(limit=1000)
    pairs = [(r["gu"], r["name"]) for r in rows]
    assert pairs == sorted(pairs), "자치구·동명 순으로 정렬돼 있지 않다"


@pytest.mark.parametrize("query", ["역삼1동", "역삼제1동"])
def test_je_notation_is_absorbed(query):
    """'창신1동'과 '창신제1동' 표기 차이를 흡수하는지.

    사용자는 자기 동네를 '제' 없이 부르는데 DB 표기는 '제'가 붙어 있다.
    양쪽에서 '제'를 뺀 뒤 비교한다.
    """
    rows = list_dongs(query, limit=5)
    names = {r["name"].replace("제", "") for r in rows}
    assert "역삼1동" in names, f"'{query}' 로 역삼1동을 못 찾았다: {rows}"


def test_list_dongs_by_gu():
    """자치구명으로도 찾을 수 있는지."""
    rows = list_dongs("강남구", limit=30)
    assert rows and all(r["gu"] == "강남구" for r in rows)


def test_list_dongs_unknown_returns_empty():
    """없는 이름은 빈 결과. 이건 정상적인 빈 결과다.

    pymysql 의 fetchall() 은 리스트가 아니라 튜플을 돌려주므로
    == [] 로 비교하면 안 된다. 비어 있는지만 본다.
    """
    assert not list_dongs("존재하지않는동네이름", limit=5)


# ── list_work_options ───────────────────────────────────────

def test_work_options_not_empty(home_code):
    """알려진 거주동에서 갈 수 있는 근무동이 있어야 한다.

    **이 파일에서 가장 중요한 검사다.**
    이 함수는 except Exception 으로 감싸여 있어 SQL 이 깨져도 [] 를 돌려준다.
    화면에서는 자동완성이 전체 목록으로 폴백해 정상처럼 보인다.
    2026-09-07 에 그 상태로 한 번도 동작한 적이 없었다.
    """
    rows = list_work_options(home_code, limit=6)
    assert rows, (
        f"{HOME_NAME}({home_code})에서 갈 수 있는 근무동이 하나도 없다. "
        "경로 자료가 있는데 빈 목록이면 SQL 이 깨졌을 수 있다"
    )


def test_work_options_shape(home_code):
    row = list_work_options(home_code, limit=1)[0]
    assert set(row) >= {"code", "name", "gu"}


def test_work_options_exclude_self(home_code):
    """거주동 자신은 근무지 후보에서 뺀다."""
    rows = list_work_options(home_code, limit=100)
    assert home_code not in [r["code"] for r in rows]


def test_work_options_respect_limit(home_code):
    assert len(list_work_options(home_code, limit=3)) <= 3


def test_work_options_query_narrows(home_code):
    """q 를 주면 부분일치로 좁혀지는지."""
    wide = list_work_options(home_code, limit=100)
    if len(wide) < 2:
        pytest.skip("후보가 적어 좁히기를 확인할 수 없다")

    gu = wide[0]["gu"]
    narrow = list_work_options(home_code, limit=100, q=gu)
    assert narrow, f"'{gu}' 로 좁혔더니 결과가 없다"
    assert all(gu in (r["gu"] + r["name"]) for r in narrow)
    assert len(narrow) <= len(wide)


def test_work_options_are_a_subset_of_all_dongs(home_code):
    """경로 자료가 있는 조합만 나오는지.

    거주동별 누적 80% 목적지만 수집했으므로 전체보다 훨씬 적어야 한다.
    전체와 같은 개수가 나오면 필터가 안 걸린 것이다.
    """
    options = list_work_options(home_code, limit=1000)
    total = len(list_dongs(limit=1000))
    assert len(options) < total, (
        f"근무지 후보가 {len(options)}개로 전체 {total}개와 다르지 않다. "
        "경로 필터가 안 걸렸다"
    )


def test_work_options_unknown_home_returns_empty():
    """없는 거주동 코드는 빈 결과. 정상적인 빈 결과다."""
    assert not list_work_options("00000000")


# ── list_home_options ───────────────────────────────────────

def test_home_options_not_empty(work_code):
    """알려진 근무지로 통근 경로가 있는 거주동이 있어야 한다."""
    rows = list_home_options(work_code, limit=20)
    assert rows, (
        f"{WORK_NAME}({work_code})로 통근하는 거주동이 하나도 없다"
    )


def test_home_options_shape(work_code):
    row = list_home_options(work_code, limit=1)[0]
    assert set(row) >= {"code", "name", "gu"}


def test_home_options_exclude_self(work_code):
    rows = list_home_options(work_code, limit=100)
    assert work_code not in [r["code"] for r in rows]


def test_home_options_unknown_work_returns_empty():
    assert not list_home_options("00000000")


# ── nearest_routed_work ─────────────────────────────────────

def test_nearest_returns_none_for_unknown_work(home_code):
    """없는 근무동 코드면 None. 대체할 대상 자체를 모른다."""
    assert nearest_routed_work(home_code, "00000000") is None


def test_nearest_finds_substitute(home_code):
    """경로가 없는 조합에 대체 근무동을 찾아주는지.

    경로는 거주동별 누적 80% 목적지만 수집해 흐름이 적은 조합은 빠져 있다.
    "자료 없음"으로 끝내면 다섯 중 한 명은 아무 결과도 못 본다.
    """
    routed = {r["code"] for r in list_work_options(home_code, limit=1000)}
    missing = next(
        (r["code"] for r in list_dongs(limit=1000)
         if r["code"] not in routed and r["code"] != home_code), None)
    if missing is None:
        pytest.skip("경로가 없는 조합을 찾지 못했다")

    hit = nearest_routed_work(home_code, missing)
    assert hit is not None, f"{missing} 에 대한 대체 근무동을 못 찾았다"
    assert set(hit) >= {"code", "name", "gu", "requested_name", "same_gu"}
    assert hit["code"] != home_code, (
        "대체 근무동으로 거주동 자신을 돌려줬다. "
        "fact_commute_route 의 내부통근 행(home=work)이 후보에 섞였다. "
        "list_work_options 처럼 work_code8 <> home_code8 조건이 필요하다"
    )
    assert hit["code"] in routed, "대체 근무동에 경로 자료가 없다"
    assert hit["code"] != missing


def test_nearest_reports_what_it_substituted(home_code):
    """무엇을 무엇으로 바꿨는지 호출한 쪽에 알려주는지.

    화면에 반드시 밝혀야 하는 정보다.
    조용히 다른 동 값을 보여주면 사용자는 자기가 입력한 곳의 값으로 읽는다.
    """
    routed = {r["code"] for r in list_work_options(home_code, limit=1000)}
    all_dongs = list_dongs(limit=1000)
    missing = next((r for r in all_dongs
                    if r["code"] not in routed and r["code"] != home_code), None)
    if missing is None:
        pytest.skip("경로가 없는 조합을 찾지 못했다")

    hit = nearest_routed_work(home_code, missing["code"])
    if hit is None:
        pytest.skip("대체 근무동이 없다")

    assert hit["requested_name"] == missing["name"], (
        "요청한 동 이름을 안 돌려준다. 화면이 '무엇 대신'인지 못 밝힌다"
    )
    assert isinstance(hit["same_gu"], bool), (
        "같은 자치구 여부를 안 돌려준다. 대체의 신뢰도를 화면이 판단할 수 없다"
    )
    assert hit["same_gu"] == (hit["gu"] == missing["gu"])


# ── policy_coverage ─────────────────────────────────────────

def test_policy_coverage_totals():
    """부담요인별 정책 수. 합계가 dim_policy 전체와 같아야 한다."""
    rows = policy_coverage()
    assert rows, "정책 보유 현황이 비었다"
    assert sum(r["count"] for r in rows) == 12


def test_policy_coverage_by_tag():
    """태그별 건수. 발표 자료에 들어가는 숫자다.

    태그3(높은 통근 교통비)이 1건뿐인 것은 데이터 부족이 아니라
    서울 청년 통근비를 줄여주는 제도가 거의 없어서 생긴 결과다.
    억지로 채우면 "탐색 우선순위이지 자격 판정이 아니다"라는 원칙과 어긋난다.
    숨기지 않고 밝히기 위해 여기에 고정해 둔다.
    """
    counts = {r["burden_tag"]: r["count"] for r in policy_coverage()}
    assert counts == {1: 2, 2: 2, 3: 1, 4: 2, 5: 3, 6: 2}, (
        f"태그별 정책 수가 바뀌었다: {counts}. 발표 자료도 함께 갱신할 것"
    )


def test_policy_coverage_shape():
    """태그 이름과 정책 목록이 함께 오는지."""
    for row in policy_coverage():
        assert row["burden_tag_name"], f"태그 {row['burden_tag']} 의 이름이 없다"
        assert len(row["policies"]) == row["count"], (
            f"태그 {row['burden_tag']}: 건수 {row['count']} 와 "
            f"목록 {len(row['policies'])} 개가 다르다"
        )
        assert all(row["policies"]), "정책 이름에 빈 값이 있다"


def test_policy_coverage_sorted_by_tag():
    tags = [r["burden_tag"] for r in policy_coverage()]
    assert tags == sorted(tags)
