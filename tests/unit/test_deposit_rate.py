"""전월세전환율(보증금 월환산)이 한 가지 기준으로만 계산되는지 검사한다.

2026-09-06 배경
--------------
DEPOSIT_ANNUAL_RATE = 0.0348 하나로 전체를 계산하던 시절,
같은 비교표의 두 열이 서로 다른 산식 위에 놓여 있었다.
보증금이 클수록 어긋나서(1억이면 월 12.7만원) 이사 이득이 과소평가됐다.
권역별 중앙값으로 바꾸고 헬퍼 하나(_deposit_monthly)로 통합했다.

2026-09-07 배경
--------------
헬퍼는 하나인데 호출부 다섯 곳 중 _support_rank 만 권역을 안 넘기고 있었다.
그래서 화면에는 권역별 전환율로 계산한 월환산액이 뜨는데
정책 추천 순위는 전체 중앙값 5.9% 로 판단했다.
크래시가 없어 안 보이고 추천 순서만 조용히 달라지는 형태였다.

교훈: 산식을 한 곳으로 모아도 **인자를 빼먹으면 같은 결과**가 된다.
값 검사만으로는 못 잡으므로 호출부 전수 검사를 함께 둔다.

DB 가 필요 없다. pytest -m "not db" 로도 돈다.
"""

import ast
import re

import pytest

from web.service import (DEPOSIT_RATE_BY_REGION, DEPOSIT_RATE_DEFAULT,
                         _deposit_monthly, _region_of)

# 거래단위 산출물의 권역별 중앙값. 값을 바꾸려면 근거 자료도 함께 바꿔야 한다.
EXPECTED_RATES = {
    "도심권": 0.0610,
    "동남권": 0.0539,
    "동북권": 0.0620,
    "서남권": 0.0590,
    "서북권": 0.0620,
}

# 2026-09-06 에 걷어낸 단일 전환율. 소스에 다시 나타나면 안 된다.
RETIRED_RATE = 0.0348


def _dong(region):
    """get_dong() 결과 중 _deposit_monthly 가 실제로 보는 부분만 만든다."""
    return {"dong": {"region_group": region}}


# ── 권역별 값 ───────────────────────────────────────────────

def test_region_rate_table():
    """권역 다섯 개의 전환율이 근거 자료와 같은지."""
    assert DEPOSIT_RATE_BY_REGION == EXPECTED_RATES, (
        "권역별 전환율이 바뀌었다. 근거 자료(거래단위 산출물 권역별 중앙값)와 "
        "방법론 문서도 함께 갱신됐는지 확인할 것"
    )


def test_default_rate_is_overall_median():
    """권역을 모를 때 쓰는 전체 중앙값."""
    assert DEPOSIT_RATE_DEFAULT == 0.0590


@pytest.mark.parametrize("region, rate", sorted(EXPECTED_RATES.items()))
def test_rate_applied_by_region(region, rate):
    """권역을 넘기면 그 권역의 전환율이 실제로 쓰이는지.

    표에만 값이 있고 함수가 안 쓰면 표는 장식이 된다.
    """
    deposit_man = 10_000                      # 1억
    monthly, applied, dep = _deposit_monthly(deposit_man, _dong(region))

    assert applied == rate, f"{region} 에 {applied} 가 적용됐다. {rate} 여야 한다"
    assert dep == 100_000_000
    assert monthly == pytest.approx(dep * rate / 12)


@pytest.mark.parametrize(
    "dong_result",
    [None, {}, {"dong": None}, {"dong": {}}, {"dong": {"region_group": None}},
     {"dong": {"region_group": "없는권역"}}, "문자열", 123],
    ids=["None", "빈dict", "dong=None", "dong빈dict", "region=None",
         "미지의권역", "문자열", "숫자"],
)
def test_unknown_region_falls_back(dong_result):
    """권역을 알 수 없으면 전체 중앙값으로 물러선다.

    query_dong 이 region_group 을 안 돌려주는 구버전이어도 화면이 멈추면 안 된다.
    다만 이 폴백 때문에 인자를 빼먹어도 크래시가 안 난다.
    2026-09-07 의 _support_rank 누락이 오래 안 보인 이유가 이것이다.
    """
    _, applied, _ = _deposit_monthly(1_000, dong_result)
    assert applied == DEPOSIT_RATE_DEFAULT


def test_region_makes_a_difference():
    """권역을 넘기는 것과 안 넘기는 것이 실제로 다른 값을 내는지.

    이 차이가 0 이면 권역별 표가 무의미하고,
    _support_rank 의 인자 누락도 애초에 문제가 아니었다는 뜻이 된다.
    동남권(5.39%)은 전체 중앙값(5.9%)과 가장 크게 벌어진다.
    """
    with_region = _deposit_monthly(10_000, _dong("동남권"))[0]
    without = _deposit_monthly(10_000)[0]

    gap = abs(with_region - without)
    assert gap > 40_000, (
        f"보증금 1억 기준 권역 반영 여부의 차이가 월 {gap:,.0f}원뿐이다. "
        "권역별 표가 실제로 적용되고 있는지 확인할 것"
    )


# ── 입력 처리 ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "value, expected_won",
    [
        (1_000, 10_000_000),        # 만원 단위 입력
        ("1000", 10_000_000),       # 폼에서 오는 문자열
        ("1,000", 10_000_000),      # 쉼표
        ("1,000만 원", 10_000_000),
        (0, 0),
        ("", 0),
        (None, 0),
        ("모름", 0),
    ],
)
def test_deposit_input_parsing(value, expected_won):
    """보증금은 만원 단위 문자열로 들어온다.

    app.py 가 폼 값을 그대로 넘기므로 "1,000만 원" 같은 형태가 온다.
    """
    _, _, dep = _deposit_monthly(value, _dong("서남권"))
    assert dep == expected_won, f"{value!r} 를 {dep:,}원으로 읽었다"


def test_zero_deposit_gives_zero():
    """보증금이 없으면 월환산도 0 이어야 한다. 전세가 아닌 월세만 사는 경우다."""
    monthly, _, dep = _deposit_monthly(0, _dong("동남권"))
    assert dep == 0
    assert monthly == 0


# ── _region_of 방어 ─────────────────────────────────────────

@pytest.mark.parametrize(
    "value, expected",
    [
        ({"dong": {"region_group": "도심권"}}, "도심권"),
        ({"dong": {}}, None),
        ({"dong": None}, None),
        ({}, None),
        (None, None),
        ("문자열", None),
        ([], None),
    ],
)
def test_region_of(value, expected):
    """조회 결과에서 권역을 꺼낼 때 어떤 입력에도 터지지 않는지."""
    assert _region_of(value) == expected


# ── 소스 검사: 호출부 전수 ──────────────────────────────────

def test_retired_rate_is_gone(service_source):
    """2026-09-06 에 걷어낸 0.0348 이 소스에 남아 있지 않은지."""
    hits = [
        node.lineno
        for node in ast.walk(ast.parse(service_source))
        if isinstance(node, ast.Constant) and node.value == RETIRED_RATE
    ]
    assert not hits, (
        f"{RETIRED_RATE} 가 {hits} 행에 남아 있다. "
        "권역별 표(DEPOSIT_RATE_BY_REGION)로 대체된 값이다"
    )


def test_every_call_passes_region(service_source):
    """_deposit_monthly 호출이 전부 조회 결과를 함께 넘기는지.

    **이 파일에서 가장 중요한 검사다.**

    산식을 헬퍼 하나로 모아도 인자를 빼먹으면 결과는 갈린다.
    2026-09-07 에 _support_rank 가 `_deposit_monthly(deposit)` 로만 불러
    화면(권역별)과 순위 판단(전체 중앙값)이 서로 다른 전환율 위에 있었다.
    두 번째 인자가 없으면 조용히 기본값으로 물러서므로 크래시도 안 난다.
    값 비교로는 절대 못 잡는다.
    """
    offenders = []
    for node in ast.walk(ast.parse(service_source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_deposit_monthly"):
            continue

        has_positional = len(node.args) >= 2
        has_keyword = any(kw.arg == "dong_result" for kw in node.keywords)
        if not (has_positional or has_keyword):
            offenders.append(node.lineno)

    assert not offenders, (
        f"_deposit_monthly 를 조회 결과 없이 부르는 곳이 있다: {offenders} 행\n"
        "권역을 모르면 전체 중앙값 5.9% 가 쓰여, 그 경로만 다른 전환율로 계산된다.\n"
        "의도적으로 권역을 안 쓰는 자리라면 명시적으로 None 을 넘길 것"
    )


def test_deposit_conversion_written_once(service_source):
    """보증금을 월환산하는 계산이 _deposit_monthly 안에만 있는지.

    `deposit * rate / 12` 형태를 다른 곳에서 직접 쓰면
    헬퍼를 고쳐도 그 자리는 안 따라온다. 2026-09-06 사고의 원래 형태다.

    AST 로 '12 로 나누는 연산'만 찾는다.
    소스를 문자열로 훑으면 주석에 적힌 검산 기록까지 걸린다.
    (실제로 153행의 시안 검산 주석이 잡혔다. 그건 지우면 안 되는 기록이다.)
    """
    tree = ast.parse(service_source)

    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_deposit_monthly"
    )
    inside = range(fn.lineno, (fn.end_lineno or fn.lineno) + 1)

    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant)
        and node.right.value == 12
        and node.lineno not in inside
    ]

    assert not offenders, (
        f"_deposit_monthly 밖에서 월환산(/12)을 직접 계산하는 곳이 있다: "
        f"{offenders} 행\n헬퍼를 거치도록 바꿀 것"
    )
