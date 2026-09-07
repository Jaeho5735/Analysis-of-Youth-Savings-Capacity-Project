"""U1: _pass_for_age 가 나이별로 올바른 정기권 기준을 고르는지 검사한다.

배경
----
모두의카드 정액형은 기준선을 넘는 금액을 환급하므로 기준선이 곧 실질 상한이다.
  청년(만 19~39세) 55,000원 / 일반 62,000원
이 값이 총부담에 그대로 들어가므로, 경계를 하나 틀리면
만 39세와 40세의 총부담이 7,000원씩 어긋난다.

2026-09-07 에 carry_qs 의 age 누락으로 4·5·6페이지가 청년 기준으로
되돌아간 사고가 있었다. 그때 3페이지와 나머지의 차이가 정확히 7,000원이었다.
이 함수가 경계를 제대로 가르는지가 그 차이의 근거다.

DB 가 필요 없다. pytest -m "not db" 로도 돈다.
"""

import re

import pytest

from web.service import (TRANSIT_PASS_CAP, TRANSIT_PASS_CAP_GENERAL,
                         YOUTH_AGE_MAX, YOUTH_AGE_MIN, _pass_for_age)


# ── 경계값 ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "age, expect_youth",
    [
        (18, False),   # 청년 진입 직전
        (19, True),    # 청년 시작
        (20, True),
        (29, True),    # 시연 페르소나
        (38, True),
        (39, True),    # 청년 마지막
        (40, False),   # 청년 이탈
        (41, False),
        (45, False),   # 2026-09-07 실측 케이스
    ],
)
def test_youth_boundary(age, expect_youth):
    """만 19~39세만 청년 기준이어야 한다.

    경계 네 개(18/19, 39/40)가 핵심이다.
    부등호를 하나 잘못 쓰면(< vs <=) 여기서 걸린다.
    """
    r = _pass_for_age(age)
    assert r["is_youth"] is expect_youth, (
        f"만 {age}세의 청년 여부가 {r['is_youth']} 다. "
        f"기준은 만 {YOUTH_AGE_MIN}~{YOUTH_AGE_MAX}세"
    )

    expected_cap = TRANSIT_PASS_CAP if expect_youth else TRANSIT_PASS_CAP_GENERAL
    assert r["cap"] == expected_cap, (
        f"만 {age}세의 상한이 {r['cap']:,}원인데 {expected_cap:,}원이어야 한다"
    )


def test_boundary_matches_declared_constants():
    """경계가 YOUTH_AGE_MIN/MAX 상수와 실제로 연동되는지.

    상수는 19/39 인데 함수 안에 숫자를 직접 적어두면
    상수만 고쳤을 때 동작이 안 따라온다.
    """
    assert _pass_for_age(YOUTH_AGE_MIN)["is_youth"] is True
    assert _pass_for_age(YOUTH_AGE_MAX)["is_youth"] is True
    assert _pass_for_age(YOUTH_AGE_MIN - 1)["is_youth"] is False
    assert _pass_for_age(YOUTH_AGE_MAX + 1)["is_youth"] is False


def test_cap_difference_is_7000():
    """청년과 일반의 상한 차이.

    2026-09-07 에 페이지 간 총부담이 정확히 이 금액만큼 갈렸다.
    test_cross_page.py 의 test_youth_cap_difference_is_exact 가
    이 값을 기대값으로 쓰므로 여기서 근거를 고정한다.
    """
    assert TRANSIT_PASS_CAP == 55_000
    assert TRANSIT_PASS_CAP_GENERAL == 62_000
    assert TRANSIT_PASS_CAP_GENERAL - TRANSIT_PASS_CAP == 7_000


# ── 나이를 못 받은 경우 ─────────────────────────────────────

@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "모름", "미입력"],
    ids=["None", "빈문자열", "공백", "한글", "미입력"],
)
def test_missing_age_falls_back_to_youth(value):
    """나이를 못 받으면 청년 기준을 쓴다.

    분석 대상이 청년 1인가구라 그게 기본 가정이고, 화면에도 그 사실을 밝힌다.
    다만 이 폴백 때문에 age 가 전달되지 않아도 크래시가 안 난다.
    2026-09-07 의 age 누락이 오래 안 보였던 이유가 이것이다.
    """
    r = _pass_for_age(value)
    assert r["is_youth"] is True
    assert r["cap"] == TRANSIT_PASS_CAP
    assert r["age"] is None, (
        f"나이를 못 받았는데 age 에 {r['age']!r} 가 들어 있다. "
        "None 이어야 화면에서 '기본 가정'임을 구분할 수 있다"
    )


# ── 문자열 입력 ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "value, expected_age",
    [
        ("29", 29),
        ("만 29세", 29),
        ("29세", 29),
        (" 29 ", 29),
        ("29.9", 29),      # int() 는 버린다. 만 나이라 올림하지 않는 게 맞다
        ("39.9", 39),      # 청년 경계를 넘지 않는다
        ("40.0", 40),      # 일반으로 넘어간다
        (29, 29),          # 숫자 그대로도 받는다
        (29.0, 29),
    ],
)
def test_string_input_is_parsed(value, expected_age):
    """폼에서 오는 값은 문자열이다.

    app.py 가 request.args 값을 그대로 넘기므로 "29" 처럼 들어온다.
    _num_only 가 숫자만 뽑고 int() 로 내린다.
    """
    r = _pass_for_age(value)
    assert r["age"] == expected_age, (
        f"{value!r} 를 만 {r['age']}세로 읽었다. {expected_age}세여야 한다"
    )


# ── 반환값 정합성 ───────────────────────────────────────────

@pytest.mark.parametrize("age", [None, 18, 19, 29, 39, 40, 45])
def test_return_shape(age):
    """호출부가 기대하는 키가 모두 있는지.

    service.py 안에서 ["cap"] 만 쓰는 곳(_monthly 인자)과
    전체를 쓰는 곳(3페이지 카드 문구)이 나뉘어 있어
    키 하나가 빠지면 한쪽만 조용히 깨진다.
    """
    r = _pass_for_age(age)
    for key in ("cap", "is_youth", "age", "name", "code", "note"):
        assert key in r, f"만 {age}세 결과에 {key} 가 없다"

    assert isinstance(r["cap"], int)
    assert isinstance(r["is_youth"], bool)


@pytest.mark.parametrize("age", [None, 18, 19, 29, 39, 40, 45])
def test_is_youth_and_cap_agree(age):
    """is_youth 와 cap 이 서로 어긋나지 않는지.

    둘은 같은 판정에서 나오는데 반환 지점이 세 곳이라
    한 곳만 고치면 '청년인데 일반 상한' 같은 상태가 만들어진다.
    """
    r = _pass_for_age(age)
    expected = TRANSIT_PASS_CAP if r["is_youth"] else TRANSIT_PASS_CAP_GENERAL
    assert r["cap"] == expected, (
        f"만 {age}세: is_youth={r['is_youth']} 인데 cap={r['cap']:,} 이다"
    )


@pytest.mark.parametrize("age", [19, 29, 39, 40, 45])
def test_note_number_matches_cap(age):
    """화면 문구에 적힌 금액이 실제 계산에 쓰는 cap 과 같은지.

    note 는 사용자가 읽는 문장이고 cap 은 계산에 들어가는 숫자다.
    둘이 어긋나면 "월 55,000원까지만 부담해요"라고 안내하면서
    실제로는 62,000원으로 계산하는 상태가 된다. 화면만 봐서는 못 찾는다.

    2026-09-07 에 dim_time_value 의 "2025년 최저임금" 오기를 겪었는데,
    그건 값이 아니라 라벨이라 테스트로 못 잡았다.
    이 경우는 문구 안에 숫자가 있어서 잡을 수 있다.
    """
    r = _pass_for_age(age)
    amounts = {
        int(m.replace(",", ""))
        for m in re.findall(r"([\d,]+)원", r["note"])
    }
    assert r["cap"] in amounts, (
        f"만 {age}세 안내 문구의 금액 {amounts} 에 "
        f"실제 상한 {r['cap']:,}원이 없다.\n  문구: {r['note']}"
    )


# ── 현재 동작 기록 ──────────────────────────────────────────

@pytest.mark.parametrize("age", [0, 10, 15, 18])
def test_under_youth_age_uses_general_cap(age):
    """만 19세 미만은 일반 기준이 적용된다.

    이 테스트는 '고쳐라'가 아니라 '현재 이렇다'를 기록한다.
    청년 정책 대상이 만 19세부터이므로 그 아래가 일반인 것은 규정상 맞다.
    다만 서비스 대상이 청년 1인가구이므로 미성년 입력을 애초에
    받을지 말지는 별개 판단이다. 동작이 바뀌면 여기가 실패하면서 검토를 강제한다.
    """
    r = _pass_for_age(age)
    assert r["is_youth"] is False
    assert r["cap"] == TRANSIT_PASS_CAP_GENERAL
