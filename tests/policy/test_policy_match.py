"""P1·P3: 정책 조건 판정과 화면 표시가 실제 데이터와 맞는지 검사한다.

배경
----
dim_policy 12건. NULL 은 "제한 없음"이다.
0 으로 채웠다면 "0원 이하만 가능"으로 읽혀 아무도 해당되지 않았을 것이다.

사용자 값이 None 이면 그 조건은 **검사하지 않고 unchecked 에 남긴다.**
모르는 값을 통과로 처리하면 "받을 수 있다"고 잘못 안내하게 된다.

기준 케이스(2026-09-07 실측)
    만 29세 · 월소득 280만 · 월세 75만 -> 12건 중 9건 통과, 탈락 3건 전부 소득

DB 가 필요하다. pytest -m "not db" 로 빼면 이 파일 전체가 제외된다.
"""

import pytest

pytest.importorskip("pymysql", reason="DB 접속에 pymysql 이 필요하다")

from src.db.query_dong import get_policies  # noqa: E402
from web.service import _support_items  # noqa: E402

pytestmark = pytest.mark.db

AGE, INCOME, RENT = 29, 2_800_000, 750_000

# 기준 케이스에서 소득 상한에 걸려 탈락하는 세 건.
EXPECTED_EXCLUDED = {
    "청년월세 지원사업",                    # 월 1,538,543원 이하
    "희망두배 청년통장",                    # 월 2,550,000원 이하
    "자산형성지원사업(청년내일저축계좌)",     # 월 1,282,119원 이하
}


@pytest.fixture(scope="module")
def baseline():
    res = get_policies(age=AGE, income=INCOME, rent=RENT)
    if res.get("unavailable"):
        pytest.skip(f"정책 테이블을 읽지 못했다: {res['unavailable']}")
    return res


@pytest.fixture(scope="module")
def all_policies():
    """조건을 하나도 안 걸었을 때의 전체 목록."""
    res = get_policies()
    if res.get("unavailable"):
        pytest.skip("정책 테이블을 읽지 못했다")
    return res


# ── P1: 조건 판정 ───────────────────────────────────────────

def test_baseline_case(baseline):
    """기준 케이스가 실측과 같은 결과를 내는지.

    이 숫자가 발표 자료와 방법론 문서에 들어간다.
    데이터가 바뀌면 여기가 먼저 실패해야 문서를 같이 고칠 수 있다.
    """
    matched, excluded = baseline["matched"], baseline["excluded"]
    assert len(matched) + len(excluded) == 12, "정책 건수가 12건이 아니다"
    assert len(matched) == 9, (
        f"통과 {len(matched)}건. 9건이어야 한다.\n  "
        + "\n  ".join(p["policy_name"] for p in matched)
    )
    assert len(excluded) == 3


def test_excluded_are_all_income(baseline):
    """탈락 세 건이 모두 소득 상한 때문인지."""
    names = {p["policy_name"] for p in baseline["excluded"]}
    assert names == EXPECTED_EXCLUDED, f"탈락 목록이 다르다: {names}"

    for p in baseline["excluded"]:
        reasons = p.get("reasons") or []
        assert reasons, f"{p['policy_name']} 에 탈락 사유가 없다"
        assert all("월소득" in r for r in reasons), (
            f"{p['policy_name']} 의 사유가 소득이 아니다: {reasons}"
        )


def test_reason_is_readable(baseline):
    """탈락 사유가 '왜 안 뜨나'에 답할 수 있는 문장인지.

    기준값과 입력값이 함께 있어야 사용자가 판단할 수 있다.
    """
    p = next(x for x in baseline["excluded"]
             if x["policy_name"] == "희망두배 청년통장")
    reason = p["reasons"][0]
    assert "2,550,000" in reason and "2,800,000" in reason, (
        f"기준값과 입력값이 함께 안 보인다: {reason}"
    )


def test_null_means_no_limit(all_policies):
    """NULL 인 조건은 제한 없음으로 읽는지.

    0 으로 채웠다면 '0원 이하만 가능'이 되어 아무도 통과 못 한다.
    """
    # 모두의카드는 소득 제한이 없다
    high = get_policies(age=29, income=100_000_000, rent=RENT)
    names = {p["policy_name"] for p in high["matched"]}
    assert "모두의카드(기후동행패스)" in names, (
        "소득 제한(NULL)이 있는 정책이 고소득에서 탈락했다"
    )

    # 전세보증금반환보증은 나이 제한이 없다
    old = get_policies(age=70, income=INCOME, rent=RENT)
    names = {p["policy_name"] for p in old["matched"]}
    assert "전세보증금반환보증" in names, (
        "나이 제한(NULL)이 있는 정책이 고연령에서 탈락했다"
    )


@pytest.mark.parametrize(
    "income, should_pass",
    [(2_550_000, True), (2_550_001, False)],
)
def test_income_boundary_is_inclusive(income, should_pass):
    """소득 상한은 '이하'다. 딱 맞으면 통과해야 한다.

    희망두배 청년통장 월 2,550,000원 기준.
    """
    res = get_policies(age=29, income=income, rent=RENT)
    names = {p["policy_name"] for p in res["matched"]}
    assert ("희망두배 청년통장" in names) is should_pass


@pytest.mark.parametrize(
    "age, should_pass",
    [(19, True), (34, True), (35, False), (18, False)],
)
def test_age_boundary_is_inclusive(age, should_pass):
    """나이 범위는 양끝 포함이다. 청년월세 지원사업 만 19~34세 기준."""
    res = get_policies(age=age, income=1_000_000, rent=RENT)
    names = {p["policy_name"] for p in res["matched"]}
    assert ("청년월세 지원사업" in names) is should_pass


@pytest.mark.parametrize(
    "rent, should_pass",
    [(900_000, True), (900_001, False)],
)
def test_rent_boundary_is_inclusive(rent, should_pass):
    """월세 상한도 '이하'다. 서울시 청년 월세 지원 90만원 기준."""
    res = get_policies(age=29, income=INCOME, rent=rent)
    names = {p["policy_name"] for p in res["matched"]}
    assert ("서울시 청년 월세 지원" in names) is should_pass


def test_unknown_value_is_unchecked_not_passed():
    """모르는 값은 통과가 아니라 '미확인'으로 남는지.

    이게 핵심이다. 소득을 모르는데 통과로 처리하면
    월 128만원 이하 대상 정책을 월 280만원 버는 사람에게
    아무 표시 없이 '받을 수 있다'고 안내하게 된다.
    """
    res = get_policies(age=29, income=None, rent=RENT)
    target = next(p for p in res["matched"]
                  if p["policy_name"] == "자산형성지원사업(청년내일저축계좌)")
    assert "소득" in (target.get("unchecked") or []), (
        "소득을 모르는데 unchecked 표시가 없다. "
        "화면이 조건 확인 없이 받을 수 있다고 안내하게 된다"
    )


# ── P3: 표시 ────────────────────────────────────────────────

def test_apply_type_counts(all_policies):
    """상시 8건 / 기간제 4건.

    기간제는 이미 모집이 끝났을 수 있어 상시와 같이 취급하면 안 된다.
    """
    rows = all_policies["matched"] + all_policies["excluded"]
    counts = {}
    for p in rows:
        counts[p.get("apply_type")] = counts.get(p.get("apply_type"), 0) + 1
    assert counts.get("상시") == 8, f"상시 건수가 다르다: {counts}"
    assert counts.get("기간제") == 4, f"기간제 건수가 다르다: {counts}"


def test_period_limited_has_note(all_policies):
    """기간제 정책은 모집 시기 안내 문구가 있어야 한다."""
    rows = all_policies["matched"] + all_policies["excluded"]
    for p in rows:
        if p.get("apply_type") == "기간제":
            assert p.get("apply_period_note"), (
                f"{p['policy_name']} 은 기간제인데 시기 안내가 없다"
            )


def test_info_category_is_flagged(all_policies):
    """제도 안내(info)는 지원사업과 구분되는지.

    전세보증금반환보증은 돈을 주는 사업이 아니라 가입할 수 있는 제도다.
    같이 놓으면 '700,000,000원 지원'으로 읽힌다.
    """
    rows = all_policies["matched"] + all_policies["excluded"]
    infos = [p["policy_name"] for p in rows if p.get("is_info")]
    assert infos == ["전세보증금반환보증"], f"info 분류가 다르다: {infos}"


def test_support_items_order():
    """화면 목록에서 기간제와 제도 안내가 뒤로 가는지.

    기간제를 앞세우면 이미 마감된 사업이 첫 칸에 온다.
    """
    base_col = {"total": 1_000_000, "housing": 800_000,
                "commute_min": 45, "region_group": "동남권"}
    items, as_of = _support_items(base_col, age=AGE, deposit="1000", rent="75")

    assert items, "정책 목록이 비었다"
    assert as_of, "기준 시점(as_of)이 없다"

    labels = [i["label"].replace("\n", "") for i in items]
    assert "전세보증금반환보증" in labels[-1], (
        f"제도 안내가 마지막이 아니다: {labels}"
    )


def test_support_items_have_real_links():
    """모든 항목이 공식 페이지로 연결되는지.

    시안은 전부 '#' 이라 눌러도 아무 일이 없었다.
    """
    items, _ = _support_items({"total": 1_000_000, "housing": 700_000,
                               "commute_min": 30, "region_group": "서남권"},
                              age=AGE, deposit="1000", rent="75")
    dead = [i["label"] for i in items if i["href"] in ("#", "", None)]
    assert not dead, f"링크가 없는 항목: {dead}"


def test_unchecked_reaches_the_screen():
    """확인 못 한 조건이 화면 항목까지 전달되는지.

    2페이지 폼에 소득 칸이 없어 _support_items 는 income=None 으로 조회한다.
    _judge_policy 는 이를 올바르게 처리해 unchecked=["소득"] 을 남기지만,
    그 표시를 화면으로 안 넘기면 월소득 128만원 이하 대상 정책이
    월 280만원 버는 사용자에게 아무 표시 없이 뜬다.

    조회 계층이 옳게 만들어져 있어도 표시 계층에서 끊기면 결과는 같다.
    """
    base_col = {"total": 1_000_000, "housing": 700_000,
                "commute_min": 30, "region_group": "서남권"}
    items, _ = _support_items(base_col, age=AGE, deposit="1000", rent="75")

    assert items, "정책 목록이 비었다"
    noted = [i for i in items if i.get("note")]
    assert noted, (
        "소득을 안 넘기고 조회했는데 '확인 필요' 표시가 붙은 항목이 하나도 없다. "
        "_support_items 가 unchecked 를 버리고 있다"
    )
    assert all("소득" in i["note"] for i in noted)
    assert all("확인 필요" in i["note"] for i in noted)


def test_no_note_when_all_conditions_checked():
    """조건을 다 확인한 정책에는 표시가 붙지 않는지.

    모두의카드는 소득 제한이 없어 소득을 몰라도 확인할 것이 없다.
    표시가 아무 데나 붙으면 사용자가 무시하게 된다.
    """
    res = get_policies(age=AGE, income=None, rent=RENT)
    target = next(p for p in res["matched"]
                  if p["policy_name"] == "모두의카드(기후동행패스)")
    assert not (target.get("unchecked") or []), (
        "소득·월세 제한이 없는 정책에 미확인 표시가 붙었다"
    )

