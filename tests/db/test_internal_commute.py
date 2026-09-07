"""내부통근(거주지 == 근무지) 조합을 어떻게 계산하는지 고정한다.

배경
----
fact_commute_route 에는 거주동과 근무동이 같은 행이 있다.
    route_type   '내부통근_원본OD'
    fare_method  '내부통근_요금미산출'
    oneway_min   있음        fare  NULL

같은 동 안 이동이라 Tmap 대중교통 경로를 뽑지 않았다.
네이버지도도 가까운 거리는 대중교통 경로를 주지 않는다. 실제로 걸어가는 경우가 많다.

**교통비는 0 으로 보되 통근시간 가치는 계산한다.**
걸어가도 시간은 든다. "주거비만 보지 말고 통근까지 합쳐서 보자"가
이 서비스의 논지이므로, 교통비가 없다고 통근 부담 전체를 0 으로 만들면 안 된다.
그러면 내부통근 동이 구조적으로 가장 유리한 후보가 되어 추천이 왜곡된다.

_monthly 가 commute_min 과 oneway_fare 를 애초에 분리해 다루므로
지금도 그렇게 동작한다. 이 파일은 그 동작이 유지되는지를 본다.
나중에 "교통비가 없으니 통근 부담도 없다"고 정리하다 시간가치까지 지우면
여기가 실패한다.

DB 가 필요하다.
"""

import pytest

pytest.importorskip("pymysql", reason="DB 접속에 pymysql 이 필요하다")

from src.db.query_dong import get_dong, list_dongs  # noqa: E402
from web.service import (TIME_VALUE_PER_HOUR, _burden,  # noqa: E402
                         _monthly)

pytestmark = pytest.mark.db

DONG_NAME = "역삼1동"
WORK_DAYS = 21
CAP = 55_000


@pytest.fixture(scope="module")
def internal():
    """거주지와 근무지가 같은 조합의 burden."""
    rows = list_dongs(DONG_NAME, limit=5)
    hit = next((r for r in rows
                if r["name"].replace("제", "") == DONG_NAME), None)
    if not hit:
        pytest.skip(f"'{DONG_NAME}' 을 찾지 못했다")

    res = get_dong(hit["code"], work_code=hit["code"])
    b = _burden(res)
    if not b or b.get("commute_min") is None:
        pytest.skip("내부통근 행에 통근시간 자료가 없다")
    return b


def test_fare_is_not_computed(internal):
    """내부통근은 요금을 산출하지 않았다.

    0 이 아니라 None 이어야 '계산 안 함'과 '0원'을 구분할 수 있다.
    화면에서 0 으로 보이는 것은 표시 단계의 선택이다.
    """
    assert internal.get("oneway_fare") is None, (
        "내부통근 행에 요금이 생겼다. fare_method 를 확인할 것"
    )


def test_commute_time_exists(internal):
    """요금은 없어도 통근시간은 있다.

    이게 있어야 시간가치를 계산할 수 있다.
    """
    minutes = internal["commute_min"]
    assert minutes > 0, f"통근시간이 {minutes} 이다"
    assert minutes < 60, (
        f"같은 동 안 이동이 {minutes}분이다. 자료를 확인할 것"
    )


def test_time_value_is_counted(internal):
    """**핵심.** 교통비가 없어도 통근시간 가치는 총부담에 들어간다.

    걸어가도 시간은 든다. 이 값을 0 으로 만들면 내부통근 동이
    구조적으로 가장 유리한 후보가 되어 5·6페이지 추천이 왜곡된다.
    """
    m = _monthly(internal, WORK_DAYS, CAP)

    assert m["fare"] is None, "요금 자료가 없는데 교통비가 계산됐다"
    assert m["time_value"] is not None, (
        "교통비가 없다고 통근시간 가치까지 사라졌다. "
        "_monthly 가 commute_min 과 oneway_fare 를 분리해 다루는지 확인할 것"
    )
    assert m["time_value"] > 0


def test_time_value_matches_formula(internal):
    """시간가치가 통근시간 × 왕복 × 출근일수 × 시급인지."""
    m = _monthly(internal, WORK_DAYS, CAP)
    expected = round(
        round(internal["commute_min"] * 2 * WORK_DAYS / 60, 2)
        * TIME_VALUE_PER_HOUR)
    assert m["time_value"] == expected


def test_time_value_responds_to_work_days(internal):
    """출근일수를 바꾸면 내부통근도 시간가치가 움직여야 한다.

    교통비가 없다고 출근일수 입력이 무시되면 안 된다.
    """
    few = _monthly(internal, 15, CAP)["time_value"]
    many = _monthly(internal, 25, CAP)["time_value"]
    assert many > few, (
        f"출근일수 15 -> 25 로 바꿨는데 시간가치가 {few} -> {many} 로 그대로다"
    )


def test_cap_does_not_affect_internal(internal):
    """정기권 상한은 내부통근 총부담에 영향을 주지 않는다.

    요금 자체가 없으므로 상한을 적용할 대상도 없다.
    나이를 바꿔도 내부통근 부담은 그대로여야 한다.
    """
    youth = _monthly(internal, WORK_DAYS, 55_000)
    general = _monthly(internal, WORK_DAYS, 62_000)
    assert youth["fare"] == general["fare"] is None
    assert youth["time_value"] == general["time_value"]
