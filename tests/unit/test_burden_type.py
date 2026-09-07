"""U3: 부담유형(A~D) 판정이 DB 표기와 어긋나지 않는지 검사한다.

배경
----
DB fact_dong_burden.burden_type_src 에는 코드 한 글자가 아니라
'A 실질 저부담' 처럼 **한글 이름이 붙은 문자열**이 들어 있다.

    A 실질 저부담   196
    B 월세 착시      14
    C 숨은 효율      14
    D 종합 고부담   196

그래서 `burden_type == "B"` 로 비교하면 아무것도 안 잡힌다.
값이 비어 보이는 게 아니라 **조건이 조용히 거짓이 되는** 형태라
화면에서는 카드가 그냥 안 뜨는 것으로만 보인다.
실제로 예전 코드가 burden 안에서 찾다가 카드 두 개가 통째로 빠진 적이 있다
(service.py 1453행 주석).

_burden_type_key 가 앞 글자만 뽑아 그 함정을 흡수한다.
이 파일은 그 흡수가 유지되는지, 그리고 원시 문자열을 직접 비교하는 코드가
다시 생기지 않는지를 본다.

DB 가 필요 없다. pytest -m "not db" 로도 돈다.
"""

import ast

import pytest

from web.service import _BURDEN_TYPE_COPY, _burden_type_key

# DB 에 실제로 들어 있는 표기와 건수(2026-09-07 실측, 합계 420).
# 표기가 바뀌면 판정이 통째로 무너지므로 여기에 못을 박는다.
DB_LABELS = {
    "A 실질 저부담": 196,
    "B 월세 착시": 14,
    "C 숨은 효율": 14,
    "D 종합 고부담": 196,
}


# ── DB 표기를 제대로 읽는가 ─────────────────────────────────

@pytest.mark.parametrize("label", sorted(DB_LABELS))
def test_db_label_maps_to_key(label):
    """DB 표기 네 가지가 각각 A/B/C/D 로 뽑히는지.

    이게 이 함수의 존재 이유다.
    """
    assert _burden_type_key(label) == label[0]


def test_bare_code_comparison_would_fail():
    """왜 _burden_type_key 가 필요한지를 코드로 남긴다.

    실패시키는 테스트가 아니라 함정을 기록하는 테스트다.
    누군가 `burden_type == "B"` 로 고쳐 쓰려 할 때 여기를 보면 된다.
    """
    label = "B 월세 착시"
    assert label != "B", "DB 값은 코드 한 글자가 아니다"
    assert _burden_type_key(label) == "B"


def test_distribution_labels_are_complete():
    """네 유형 모두 문구 표에 있는지.

    _conclusion 호출부가 _BURDEN_TYPE_COPY[key] 로 바로 꺼내므로
    키가 하나 빠지면 KeyError 가 난다. 그 자리는 try/except 안이라
    카드가 조용히 사라진다.
    """
    keys = {label[0] for label in DB_LABELS}
    missing = keys - set(_BURDEN_TYPE_COPY)
    assert not missing, f"{missing} 유형의 화면 문구가 없다"

    extra = set(_BURDEN_TYPE_COPY) - keys
    assert not extra, (
        f"{extra} 는 DB 에 없는 유형이다. "
        "분류 체계가 바뀌었으면 DB_LABELS 도 함께 갱신할 것"
    )


@pytest.mark.parametrize("key", sorted(_BURDEN_TYPE_COPY))
def test_copy_shape(key):
    """문구 표가 (제목, 설명) 두 칸으로 되어 있는지.

    호출부가 `title, desc = _BURDEN_TYPE_COPY[key]` 로 풀어서 받는다.
    칸 수가 달라지면 언패킹에서 터진다.
    """
    value = _BURDEN_TYPE_COPY[key]
    assert isinstance(value, tuple) and len(value) == 2, (
        f"{key} 의 문구가 (제목, 설명) 형태가 아니다: {value!r}"
    )
    title, desc = value
    assert title and desc, f"{key} 의 제목이나 설명이 비어 있다"


def test_db_label_and_copy_agree():
    """DB 표기의 한글 이름과 화면 문구 제목이 같은 것을 가리키는지.

    DB 는 'B 월세 착시', 화면은 '월세 착시 지역'이다.
    한쪽만 바뀌면 같은 동을 두 이름으로 부르게 된다.
    표기가 완전히 같을 필요는 없고, DB 이름이 화면 제목에 들어 있으면 된다.
    """
    for label in DB_LABELS:
        key, name = label[0], label[2:].strip()
        title = _BURDEN_TYPE_COPY[key][0]
        assert name in title, (
            f"DB 는 '{name}', 화면은 '{title}' 로 부른다. "
            "한쪽만 바뀌었는지 확인할 것"
        )


# ── 경계와 방어 ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "E 없는유형", "미분류", "0", "a 소문자"],
    ids=["None", "빈문자열", "공백", "E유형", "한글만", "숫자", "소문자"],
)
def test_unknown_returns_none(value):
    """A~D 가 아니면 None 을 돌려준다.

    호출부가 `if key:` 로 감싸고 있으므로 None 이면 카드를 안 만든다.
    소문자 'a' 도 None 이다. DB 표기가 대문자라 현재는 문제가 없지만,
    표기 규칙이 바뀌면 조용히 카드가 사라지므로 기록해 둔다.
    """
    assert _burden_type_key(value) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("A", "A"),                  # 코드만 있어도 읽는다
        ("  B 월세 착시  ", "B"),     # 앞뒤 공백
        ("C숨은효율", "C"),           # 공백 없는 표기
        ("D 종합 고부담", "D"),
    ],
)
def test_tolerant_formats(value, expected):
    """표기가 조금 달라도 읽히는지.

    DB 표기가 바뀌더라도 앞 글자만 대문자 A~D 면 계속 동작한다.
    """
    assert _burden_type_key(value) == expected


def test_prefix_matching_is_loose():
    """앞 글자만 보므로 A~D 로 시작하는 아무 문자열이나 통과한다.

    'Apple' 이 'A' 로 읽힌다. 현재 입력원이 DB 한 곳뿐이라 실害는 없지만,
    나중에 사용자 입력이나 외부 데이터를 이 함수에 넣으면 오탐이 난다.
    '고쳐라'가 아니라 '이 함수는 느슨하다'를 기록하는 테스트다.
    """
    assert _burden_type_key("Apple") == "A"
    assert _burden_type_key("Debug") == "D"


# ── 소스 검사: 원시 문자열 직접 비교 금지 ───────────────────

def test_no_bare_burden_type_comparison(service_source):
    """burden_type 을 코드 한 글자와 직접 비교하는 곳이 없는지.

    `burden_type == "B"` 는 DB 값이 'B 월세 착시' 라 항상 거짓이다.
    에러가 안 나고 조건만 조용히 안 걸리므로 화면에서는
    "카드가 원래 없는 것"처럼 보인다.
    반드시 _burden_type_key 를 거쳐야 한다.
    """
    codes = {"A", "B", "C", "D"}
    offenders = []

    for node in ast.walk(ast.parse(service_source)):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        # burden_type 이라는 이름이나 ...["burden_type"] 형태를 찾는다
        is_burden = (
            (isinstance(left, ast.Name) and "burden_type" in left.id)
            or (isinstance(left, ast.Subscript)
                and isinstance(left.slice, ast.Constant)
                and left.slice.value == "burden_type")
        )
        if not is_burden:
            continue
        for comp in node.comparators:
            if isinstance(comp, ast.Constant) and comp.value in codes:
                offenders.append(node.lineno)

    assert not offenders, (
        f"burden_type 을 코드 한 글자와 직접 비교하는 곳이 있다: {offenders} 행\n"
        "DB 값은 'B 월세 착시' 형태라 항상 거짓이 된다. "
        "_burden_type_key() 를 거칠 것"
    )
