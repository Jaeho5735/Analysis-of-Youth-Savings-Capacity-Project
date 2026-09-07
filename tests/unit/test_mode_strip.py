"""U2: 경로 띠(_mode_strip)가 실제 데이터 형태를 제대로 읽는지 검사한다.

배경
----
fact_commute_route 에는 승하차역 이름이 없다. 역을 지어내면 실제와 다른 역이
화면에 뜨므로, mode_sequence 의 비도보 구간과 route_lines 를 순서대로 짝지어
"어느 구간이 어느 노선인지"만 보여준다.

실제 데이터 형태(2026-09-07 확인)
    mode_sequence  'WALK → BUS → WALK'      (화살표는 U+2192, 앞뒤 공백)
    route_lines    '지선:1711' / '순환:01A' / '지선:0411 | 수도권9호선'
    둘 다 NULL 인 행이 있다(route_type='내부통근_원본OD')

화면에만 쓰이는 값이라 틀려도 총부담은 안 바뀐다. 대신 사용자가 보는 것이
실제 경로와 달라지므로, 조용히 틀린 상태가 오래 갈 수 있다.

DB 가 필요 없다. pytest -m "not db" 로도 돈다.
"""

import pytest

from web.service import (_BUS_COLOR, _LINE_COLOR, _MODE_KO, _line_color,
                         _mode_strip, _short_line)

WALK_BUS_WALK = "WALK → BUS → WALK"
TWO_LEG = "WALK → BUS → WALK → SUBWAY → WALK"


# ── 실제 데이터 ─────────────────────────────────────────────

def test_simple_bus_route():
    """가장 흔한 형태. 도보-버스-도보 한 번 환승 없음."""
    strip = _mode_strip(WALK_BUS_WALK, "지선:1711")

    assert [s["name"] for s in strip] == ["도보", "지선 1711", "도보"]
    assert [s["sub"] for s in strip] == ["", "버스", ""]
    assert not any(s["transfer"] for s in strip), "환승 0회인데 환승 표시가 있다"


def test_transfer_route():
    """비도보 구간이 둘이면 두 번째가 환승 지점이다."""
    strip = _mode_strip(TWO_LEG, "지선:0411 | 수도권9호선")

    assert [s["name"] for s in strip] == [
        "도보", "지선 0411", "도보", "9호선", "도보"]
    transfers = [s["name"] for s in strip if s["transfer"]]
    assert transfers == ["9호선"], f"환승 지점이 {transfers} 로 잡혔다"


@pytest.mark.parametrize(
    "mode_seq, lines",
    [(None, None), ("", ""), ("   ", None), (None, "")],
    ids=["둘다None", "둘다빈문자열", "공백", "혼합"],
)
def test_no_route_data_returns_empty(mode_seq, lines):
    """경로 자료가 없으면 빈 목록.

    내부통근(route_type='내부통근_원본OD') 행은 두 컬럼이 모두 NULL 이다.
    화면은 띠를 아예 안 그리면 되고, 여기서 터지면 안 된다.
    """
    assert _mode_strip(mode_seq, lines) == []


def test_falls_back_to_route_lines():
    """mode_sequence 가 없고 route_lines 만 있으면 그것으로 만든다."""
    strip = _mode_strip(None, "지선:1711")
    assert len(strip) == 1
    assert strip[0]["name"] == "지선 1711"


# ── 개수가 어긋날 때 ────────────────────────────────────────

def test_more_segments_than_lines():
    """비도보 구간보다 노선 목록이 적으면 수단명으로 표시한다.

    두 컬럼이 따로 채워지므로 개수가 안 맞는 행이 있을 수 있다.
    빈칸을 두거나 터지는 대신 '버스'/'지하철' 이라도 보여준다.
    """
    strip = _mode_strip(TWO_LEG, "지선:0411")
    names = [s["name"] for s in strip]
    assert names == ["도보", "지선 0411", "도보", "지하철", "도보"], (
        f"노선이 모자랄 때 수단명으로 물러서지 않았다: {names}"
    )


def test_more_lines_than_segments():
    """노선 목록이 더 많으면 남는 것은 버려진다.

    '고쳐라'가 아니라 '이렇게 동작한다'를 기록한다.
    조용한 누락이므로, 화면에 노선이 덜 나온다는 제보가 오면 여기를 본다.
    """
    strip = _mode_strip(WALK_BUS_WALK, "지선:0411 | 수도권9호선 | 간선:152")
    names = [s["name"] for s in strip]
    assert names == ["도보", "지선 0411", "도보"]
    assert "9호선" not in names


# ── 수단 이름 ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "token, expected",
    [
        ("WALK", "도보"),
        ("BUS", "버스"),
        ("SUBWAY", "지하철"),
        ("TRAIN", "기차"),
        ("EXPRESSBUS", "고속버스"),
    ],
)
def test_mode_name_longest_match_first(token, expected):
    """부분일치라 긴 키가 먼저 와야 한다.

    2026-09-07 에 _MODE_KO 에서 "BUS" 가 "EXPRESSBUS" 보다 앞에 있어
    고속버스 구간이 '버스'로 표시됐다. 표에 "고속버스" 값이 있는데
    그 값이 나올 길이 없는 상태였다.
    바로 아래 _LINE_COLOR 는 "수인분당"을 "분당"보다 앞에 두어
    같은 함정을 피하고 있었다. 같은 파일에서 한쪽만 틀렸다.
    """
    up = token.upper()
    got = next((v for k, v in _MODE_KO.items() if k in up or k in token), None)
    assert got == expected, (
        f"{token} 이 '{got}' 로 읽힌다. '{expected}' 여야 한다. "
        "_MODE_KO 에서 긴 키를 앞에 둘 것"
    )


def test_walk_has_no_sub_label():
    """도보 구간은 부제를 비운다. '도보 / 도보' 로 두 번 쓰지 않는다."""
    strip = _mode_strip(WALK_BUS_WALK, "지선:1711")
    walks = [s for s in strip if s["name"] == "도보"]
    assert walks and all(s["sub"] == "" for s in walks)


# ── 노선 라벨 ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "label, expected",
    [
        ("수도권2호선", "2호선"),
        ("수도권9호선", "9호선"),
        ("지선:1711", "지선 1711"),
        ("순환:01A", "순환 01A"),
        ("간선:152", "간선 152"),
        ("", ""),
        (None, ""),
    ],
)
def test_short_line(label, expected):
    """긴 노선명을 한 줄에 들어가게 줄인다."""
    assert _short_line(label) == expected


# ── 노선 색 ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "label, expected",
    [
        ("수도권2호선", "#00A84D"),
        ("수도권9호선", "#BDB092"),
        ("신분당", "#D4003B"),
        ("지선:1711", "#5BB025"),
        ("간선:152", "#3D5BAB"),
        ("순환:01A", "#F99D1C"),
        ("광역:1000", "#E60012"),
        ("마을:01", "#53B332"),
    ],
)
def test_line_color(label, expected):
    assert _line_color(label) == expected


def test_line_color_falls_back():
    """모르는 노선은 서비스 기본색. 색이 없어 띠가 끊기면 안 된다."""
    assert _line_color("듣도보도못한선") == "#7aa9a3"
    assert _line_color(None) == "#7aa9a3"


def test_subway_keys_are_longest_first():
    """지하철 노선 색 표도 긴 키가 먼저 와야 한다.

    '수인분당' 이 '분당' 뒤에 오면 수인분당선이 분당선 색으로 칠해진다.
    _MODE_KO 와 같은 종류의 함정이라 여기서도 못을 박는다.
    """
    keys = [k for k, _ in _LINE_COLOR]
    for i, key in enumerate(keys):
        longer = [k for k in keys[i + 1:] if key in k and k != key]
        assert not longer, (
            f"'{key}' 가 더 긴 키 {longer} 보다 앞에 있다. "
            f"{longer} 는 영원히 안 잡힌다"
        )


def test_bus_and_subway_keys_do_not_collide():
    """버스 종류 이름이 지하철 노선명에 걸리지 않는지.

    _line_color 는 지하철 표를 먼저 보므로, 버스 키가 지하철 키에 걸리면
    버스가 지하철 색으로 칠해진다.
    """
    subway_keys = [k for k, _ in _LINE_COLOR]
    for bus_key, _ in _BUS_COLOR:
        hit = [k for k in subway_keys if k in bus_key]
        assert not hit, f"버스 '{bus_key}' 가 지하철 키 {hit} 에 먼저 걸린다"


# ── 띠 연결선 ───────────────────────────────────────────────

def test_last_segment_has_no_connector():
    """마지막 구간에는 다음으로 잇는 선이 없어야 한다."""
    strip = _mode_strip(TWO_LEG, "지선:0411 | 수도권9호선")
    assert strip[-1]["line_color"] is None
    assert all(s["line_color"] is not None for s in strip[:-1])


def test_long_route_is_truncated_at_nine():
    """구간이 아주 많으면 9개까지만 그린다.

    현재 동작을 기록한다. 10개 이상이면 9번째가 마지막처럼 그려지므로
    뒤가 더 있다는 사실이 화면에서 사라진다.
    서울 시내 통근에서 9구간을 넘는 경로가 실제로 있는지 확인이 필요하다.
    """
    long_seq = " → ".join(["WALK", "BUS"] * 6)
    strip = _mode_strip(long_seq, " | ".join(["지선:1711"] * 6))
    assert len(strip) == 9
    assert strip[-1]["line_color"] is None
