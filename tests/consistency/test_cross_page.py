"""C1: 네 페이지가 같은 입력에 같은 총부담을 내는지 검사한다.

2026-09-06 사고
--------------
같은 총부담 계산이 3페이지 / 4·6페이지 / 5페이지 세 군데에 따로 적혀 있었고
각자 다른 출근일수·정기권 상한을 써서 같은 조건에 141.6만 / 139.4만이 나왔다.

2026-09-07 사고
--------------
산식은 하나로 합쳤는데, 3페이지가 다음 페이지로 가는 링크를 만들 때
age 를 빼먹어서 4·5·6페이지가 청년 기준으로 되돌아갔다.
만 45세 사용자에게 3페이지는 103.8만, 나머지는 103.1만이 나왔다.

두 사고의 결말은 같지만 원인이 다르다. 그래서 검사도 두 축이 필요하다.

  일치  네 페이지가 같은 값을 내는가          -> 산식이 갈리는 것을 잡는다
  반응  입력을 바꾸면 네 페이지가 다 움직이는가 -> 입력이 새는 것을 잡는다

일치만 보면 '네 페이지가 똑같이 무시하는' 경우를 놓친다.
2026-09-07 건이 정확히 그랬다. 나이를 다 같이 무시했으므로 값은 일치했다.

DB 가 필요하므로 db 마커를 붙였다. 기본 실행에서 빼려면:
    pytest -m "not db"
"""

import copy
import json

import pytest

pytest.importorskip("pymysql", reason="DB 접속에 pymysql 이 필요하다")

from web.service import (build_page3, build_page4, build_page5,  # noqa: E402
                         build_page6, recommend_dongs, resolve_place)

pytestmark = pytest.mark.db

# 2026-09-07 에 화면으로 직접 확인한 케이스.
# 만 22세 -> 103.1만 / 만 45세 -> 103.8만 (정기권 상한 55,000 vs 62,000 차이)
RESIDENCE = "역삼1동"
WORKPLACE = "삼성역"
DEPOSIT = "1000"      # 만원 단위. 화면 입력과 같은 형태(문자열)로 넣는다.
RENT = "75"           # 만원 단위
WORK_DAYS = "21"
DEPART_TIME = "08:10"

# 총부담 비교 허용 오차(원).
# 화면은 0.1만원(=1,000원) 단위로 반올림하므로 1,000원 미만 차이는 눈에 안 보인다.
# 하지만 안 보이는 차이도 산식이 갈렸다는 신호이므로 1원까지 본다.
TOLERANCE_WON = 1

PAGES = ("page3", "page4", "page5", "page6")


@pytest.fixture(scope="module")
def base_jsons(project_root):
    """각 페이지의 시연용 기본 JSON. app.py 가 load_data 로 넣어주는 것과 같다."""
    static = project_root / "web" / "static"
    out = {}
    for name in PAGES:
        path = static / f"loca_{name}_data.json"
        if not path.exists():
            pytest.skip(f"{path} 가 없다")
        out[name] = json.loads(path.read_text(encoding="utf-8-sig"))
    return out


@pytest.fixture(scope="module")
def candidate_dong():
    """5·6페이지가 비교할 후보 동을 DB 에서 고른다.

    상수로 박아두면 그 동이 하필 특수한 경우일 때 테스트가 엉뚱한 데서 깨진다.
    실제로 2026-09-07 에 후보를 '삼성1동'으로 박았다가 그게 근무지와 같은 동이라
    직주일치가 되어 통근 자료가 없었고, build_page5 가 터졌다.
    (그 자체는 진짜 버그여서 고쳤지만, C1 이 봐야 하는 것은 정상 비교 경로다.)

    거주지와 근무지를 모두 제외해 평범한 후보 하나를 받는다.
    """
    work = resolve_place(WORKPLACE)
    if not work or work.get("status") != "ok" or not work.get("dong_code"):
        pytest.skip(f"근무지 '{WORKPLACE}' 를 행정동으로 해석하지 못했다")

    home = resolve_place(RESIDENCE)
    exclude = tuple(
        code for code in (home.get("dong_code") if home else None,
                          work["dong_code"])
        if code
    )

    picks = recommend_dongs(work["dong_code"], exclude=exclude, limit=1)
    if not picks:
        pytest.skip(f"'{WORKPLACE}' 기준 추천 후보를 못 찾았다")
    return picks[0]["name"]


def _totals(base_jsons, candidate, age, work_days=WORK_DAYS):
    """네 페이지를 같은 입력으로 돌려 '현재 집' 총부담을 꺼낸다.

    app.py 의 각 라우트가 부르는 방식을 그대로 흉내낸다.
    페이지마다 인터페이스가 달라서(3·4 는 residence/workplace,
    5 는 base_place/work_place + area, 6 은 base_place/work_place + dong)
    호출 형태는 다르지만 넘기는 입력의 의미는 같다.

    5페이지는 후보동이 주인공이지만, 여기서 비교하는 것은 '현재 집' 값이다.
    후보가 무엇이든 현재 집 총부담은 같아야 한다.
    """
    calls = {
        "page3": lambda d: build_page3(
            d, residence=RESIDENCE, workplace=WORKPLACE,
            deposit=DEPOSIT, rent=RENT, work_days=work_days,
            depart_time=DEPART_TIME, age=age),
        "page4": lambda d: build_page4(
            d, residence=RESIDENCE, workplace=WORKPLACE,
            deposit=DEPOSIT, rent=RENT, work_days=work_days,
            depart_time=DEPART_TIME, age=age),
        "page5": lambda d: build_page5(
            d, area=candidate, base_place=RESIDENCE, work_place=WORKPLACE,
            deposit=DEPOSIT, rent=RENT, work_days=work_days, age=age),
        "page6": lambda d: build_page6(
            d, base_place=RESIDENCE, work_place=WORKPLACE, dong=candidate,
            deposit=DEPOSIT, rent=RENT, work_days=work_days, age=age),
    }

    totals = {}
    for name in PAGES:
        result = calls[name](copy.deepcopy(base_jsons[name]))
        calc = result.get("_calc")
        assert calc is not None, (
            f"{name} 가 _calc 를 안 남겼다. 정상 경로를 못 탔다는 뜻이다.\n"
            f"입력: {RESIDENCE} -> {WORKPLACE}, 후보 {candidate}\n"
            "그 페이지가 계산 전에 먼저 return 하는 갈래가 있는지 확인할 것"
        )
        totals[name] = calc["total"]
    return totals


# ── 축 1: 일치 ──────────────────────────────────────────────

@pytest.mark.parametrize("age", ["22", "45"])
def test_all_pages_same_total(base_jsons, candidate_dong, age):
    """같은 입력이면 네 페이지의 총부담이 같아야 한다.

    22세(청년 상한)와 45세(일반 상한) 둘 다 본다.
    청년만 보면 2026-09-07 의 age 누락을 못 잡는다.
    나이가 사라져도 기본값이 청년이라 값이 그대로이기 때문이다.
    """
    totals = _totals(base_jsons, candidate_dong, age=age)
    ref = totals["page3"]

    mismatched = {
        name: t for name, t in totals.items()
        if abs(t - ref) > TOLERANCE_WON
    }
    assert not mismatched, (
        f"만 {age}세 기준 총부담이 페이지마다 다르다.\n"
        + "\n".join(f"  {n}: {t:,.0f}원" for n, t in totals.items())
        + "\n같은 산식·같은 입력이면 같은 값이 나와야 한다"
    )


# ── 축 2: 반응 ──────────────────────────────────────────────

def test_age_moves_every_page(base_jsons, candidate_dong):
    """나이를 청년 밖으로 바꾸면 네 페이지가 전부 움직여야 한다.

    정기권 상한이 55,000 -> 62,000 으로 바뀌므로 총부담은 7,000원 늘어난다.
    한 페이지라도 안 움직이면 그 페이지까지 나이가 전달되지 않는 것이다.
    2026-09-07 에 3페이지 CTA 의 carry_qs 에서 age 가 빠져 있었던 건이
    바로 이 형태였고, 일치 테스트만으로는 잡히지 않았다.
    """
    youth = _totals(base_jsons, candidate_dong, age="22")
    general = _totals(base_jsons, candidate_dong, age="45")

    frozen = [n for n in PAGES if abs(general[n] - youth[n]) <= TOLERANCE_WON]
    assert not frozen, (
        f"나이를 22 -> 45 로 바꿨는데 {frozen} 의 총부담이 그대로다.\n"
        + "\n".join(f"  {n}: {youth[n]:,.0f} -> {general[n]:,.0f}" for n in PAGES)
        + "\n해당 페이지까지 age 가 전달되지 않는다. carry_qs 를 확인할 것"
    )


def test_work_days_moves_every_page(base_jsons, candidate_dong):
    """출근일수를 바꾸면 네 페이지가 전부 움직여야 한다.

    2026-09-06 에 5페이지가 work_days 를 받고도 쓰지 않았던 건을 잡는다.
    받고도 안 쓰는 버그는 값 비교로는 안 잡힌다. 우연히 같으면 통과한다.
    """
    few = _totals(base_jsons, candidate_dong, age="29", work_days="15")
    many = _totals(base_jsons, candidate_dong, age="29", work_days="25")

    frozen = [n for n in PAGES if abs(many[n] - few[n]) <= TOLERANCE_WON]
    assert not frozen, (
        f"출근일수를 15 -> 25 로 바꿨는데 {frozen} 의 총부담이 그대로다.\n"
        + "\n".join(f"  {n}: {few[n]:,.0f} -> {many[n]:,.0f}" for n in PAGES)
        + "\n해당 페이지가 work_days 를 받고도 쓰지 않는다"
    )


def test_youth_cap_difference_is_exact(base_jsons, candidate_dong):
    """22세와 45세의 총부담 차이가 정기권 상한 차이와 정확히 같은지.

    다른 것은 다 같고 상한만 달라지므로 차이는 62,000 - 55,000 = 7,000원이어야 한다.
    (통근이 잦아 상한에 실제로 걸리는 경로일 때. 역삼1동 -> 삼성역 21일이 그렇다.)
    값이 다르면 나이가 상한 말고 다른 곳에도 영향을 주고 있다는 뜻이다.
    """
    from web.service import TRANSIT_PASS_CAP, TRANSIT_PASS_CAP_GENERAL

    youth = _totals(base_jsons, candidate_dong, age="22")
    general = _totals(base_jsons, candidate_dong, age="45")
    expected = TRANSIT_PASS_CAP_GENERAL - TRANSIT_PASS_CAP

    for name in PAGES:
        diff = general[name] - youth[name]
        assert abs(diff - expected) <= TOLERANCE_WON, (
            f"{name}: 22세->45세 총부담 차이가 {diff:,.0f}원인데 "
            f"정기권 상한 차이는 {expected:,}원이다. "
            "나이가 상한 외의 곳에도 영향을 주고 있는지 확인할 것"
        )
