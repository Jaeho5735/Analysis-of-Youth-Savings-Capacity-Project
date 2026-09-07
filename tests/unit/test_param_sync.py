"""같은 파라미터가 여러 곳에 정의돼 있을 때 값이 어긋나지 않는지 검사한다.

2026-09-07 배경
--------------
총부담 산식에 쓰이는 파라미터가 세 곳에 흩어져 있다.

    web/service.py      사용자 입력 기준으로 화면 값을 만든다
    src/db/query_dong.py  조회 계층. 21일·청년 상한 고정으로 427개 동을 비교한다
    DB dim_time_value   뷰 v_dong_burden 이 CROSS JOIN 해 조회 시점에 계산한다

역할이 다르므로 분리 자체는 의도된 것이다.
문제는 같은 파라미터를 각자 따로 적어두었다는 점이다.
게다가 이름이 다른 것도 있어서(WORK_DAYS_DEFAULT vs WORK_DAYS_PER_MONTH)
한쪽을 고칠 때 다른 쪽을 검색으로 찾지도 못한다.

한쪽만 바꾸면 웹 화면과 SQL 분석 결과가 조용히 어긋난다.
2026-09-06 전월세전환율 3.48% 건과 같은 유형이고, 파일이 갈려 더 안 보인다.

import 로 한쪽이 다른 쪽을 참조하게 만드는 것이 정석이지만
web 이 src.db 에 의존하게 되어 지금 구조를 흔든다.
값이 어긋나는 순간 잡는 쪽이 비용 대비 낫다고 보고 테스트로 고정한다.
"""

import pytest

from src.analysis import build_total_burden
from src.db import query_dong
from web import service

# (설명, service.py 의 이름, query_dong.py 의 이름)
# 이름이 다른 것은 그 자체가 위험 신호라 여기에 대응표를 남겨둔다.
SHARED_PARAMS = [
    ("시간가치 시급", "TIME_VALUE_PER_HOUR", "TIME_VALUE_PER_HOUR"),
    ("청년 정기권 상한", "TRANSIT_PASS_CAP", "TRANSIT_PASS_CAP"),
    ("월 출근일수 기본값", "WORK_DAYS_DEFAULT", "WORK_DAYS_PER_MONTH"),
    ("기본 근무지 동코드", "WORK_DONG_CODE", "DEFAULT_WORK_DONG"),
]


@pytest.mark.parametrize(
    "label, service_name, query_name",
    SHARED_PARAMS,
    ids=[p[0] for p in SHARED_PARAMS],
)
def test_param_matches_across_modules(label, service_name, query_name):
    """web/service.py 와 src/db/query_dong.py 의 값이 같은지."""
    assert hasattr(service, service_name), (
        f"web/service.py 에 {service_name} 이 없다. 이름이 바뀌었으면 대응표를 갱신할 것"
    )
    assert hasattr(query_dong, query_name), (
        f"src/db/query_dong.py 에 {query_name} 이 없다. "
        "이름이 바뀌었으면 대응표를 갱신할 것"
    )

    a = getattr(service, service_name)
    b = getattr(query_dong, query_name)

    assert a == b, (
        f"{label}이 두 파일에서 다르다.\n"
        f"  web/service.py      {service_name} = {a!r}\n"
        f"  src/db/query_dong.py {query_name} = {b!r}\n"
        "한쪽만 고치면 웹 화면과 SQL 분석 결과가 어긋난다. 양쪽을 함께 고칠 것"
    )


@pytest.mark.db
def test_time_value_matches_db():
    """파이썬 상수와 DB dim_time_value 가 같은지.

    뷰 v_dong_burden 이 dim_time_value 를 CROSS JOIN 해 조회 시점에 시간비용을 만든다.
    즉 DB 쪽 값만 바꾸면 SQL 결과는 움직이는데 웹 화면은 그대로다.

    DB 가 필요하므로 db 마커를 붙였다. 기본 실행에서 빼려면:
        pytest -m "not db"
    """
    with query_dong.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT time_value_code, hourly_wage FROM dim_time_value "
            "WHERE is_default = 1"
        )
        rows = cur.fetchall()

    assert len(rows) == 1, (
        f"dim_time_value 의 is_default=1 행이 {len(rows)}개다. "
        "기본 시간가치는 하나여야 어느 값이 쓰이는지 확정된다"
    )

    db_wage = int(rows[0]["hourly_wage"])
    assert db_wage == service.TIME_VALUE_PER_HOUR, (
        f"시간가치가 파이썬과 DB 에서 다르다.\n"
        f"  web/service.py TIME_VALUE_PER_HOUR = {service.TIME_VALUE_PER_HOUR:,}\n"
        f"  DB dim_time_value.hourly_wage       = {db_wage:,}\n"
        "웹 화면과 SQL 분석 결과가 서로 다른 기준 위에 있다"
    )


def test_time_value_matches_pipeline():
    """파이프라인 상수와도 같은지.

    src/analysis/build_total_burden.py 의 HOURLY_VALUE 는
    fact_dong_burden 에 적재되는 총부담을 만드는 값이다.
    여기만 바뀌면 DB 에 쌓인 값과 웹 화면이 서로 다른 기준 위에 선다.
    파이프라인은 한 번 돌리고 잊기 쉬워서 어긋나도 오래 안 보인다.

    시간가치는 이로써 네 곳에 있다.
        web/service.py        TIME_VALUE_PER_HOUR
        src/db/query_dong.py  TIME_VALUE_PER_HOUR
        src/analysis/build_total_burden.py  HOURLY_VALUE
        DB dim_time_value.hourly_wage
    역할이 달라 합치지 않고, 값이 어긋나는지만 감시한다.
    """
    assert build_total_burden.HOURLY_VALUE == service.TIME_VALUE_PER_HOUR, (
        f"시간가치가 파이프라인과 웹에서 다르다.\n"
        f"  build_total_burden.HOURLY_VALUE = {build_total_burden.HOURLY_VALUE:,}\n"
        f"  service.TIME_VALUE_PER_HOUR     = {service.TIME_VALUE_PER_HOUR:,}\n"
        "DB 에 적재된 총부담과 화면 값이 서로 다른 기준 위에 있다. "
        "파이프라인을 다시 돌려야 할 수 있다"
    )

