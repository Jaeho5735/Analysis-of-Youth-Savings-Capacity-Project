"""LocaContext v1 계약 테스트.

DB 없이 돈다. 두 가지를 지킨다.

  1. web/service.py 의 _calc 네 벌이 계약 키를 전부 가지는가 (소스 검사)
     - 값 검사로는 "네 페이지가 다 같이 빠뜨린" 경우를 못 잡는다.
       app.py 배선 검사(test_app_wiring)와 같은 이유로 소스를 직접 본다.
  2. 컨텍스트와 숫자 게이트가 규칙대로 동작하는가 (단위 검사)
"""

import ast
import datetime
import json
from decimal import Decimal

import pytest

from web.chat_context import (CONTEXT_VERSION, REQUIRED_CALC_KEYS,
                              build_chat_context, collect_numbers,
                              verify_numbers)


# ─────────────────────────────────────────────────────────────
# 1. 소스 검사 — _calc 네 벌이 같은 계약을 내놓는가
# ─────────────────────────────────────────────────────────────

def _calc_key_sets(source):
    """service.py 안의 data["_calc"] = {...} 네 벌에서 키를 뽑는다."""
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if (isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "_calc"
                and isinstance(node.value, ast.Dict)):
            found.append({k.value for k in node.value.keys
                          if isinstance(k, ast.Constant)})
    return found


def test_calc_blocks_are_four(service_source):
    """3·4·5·6 네 페이지 모두 _calc 를 남겨야 한다.

    하나라도 빠지면 그 페이지에서는 챗봇을 켤 수 없다.
    """
    assert len(_calc_key_sets(service_source)) == 4


@pytest.mark.consistency
def test_every_calc_block_satisfies_contract(service_source):
    """어느 페이지에서 물어봐도 같은 종류의 답을 할 수 있어야 한다.

    특히 status 가 빠지면, 표본이 적어 화면에 '참고용' 라벨이 붙은 동을
    챗봇만 확신하며 설명하게 된다. 화면과 챗봇이 다른 말을 하는 상태다.
    """
    for i, keys in enumerate(_calc_key_sets(service_source), start=1):
        missing = REQUIRED_CALC_KEYS - keys
        assert not missing, f"{i}번째 _calc 에 없는 키: {sorted(missing)}"


# ─────────────────────────────────────────────────────────────
# 2. 단위 검사 — 컨텍스트
# ─────────────────────────────────────────────────────────────

def _fake_calc(**over):
    """실제 조회값과 같은 모양의 최소 한 벌. 잠원동 시연 케이스 기준."""
    base = {
        "housing": 795_000, "fare": 55_000, "fare_actual": 94_000,
        "time_value": 124_000, "total": 974_000,
        "work_days": 21, "commute_min": 17.2, "transit_pass_cap": 55_000,
        "home": "잠원동", "work": "역삼1동",
        "home_code": "11650540", "work_code": "11680640",
        "status": "ok", "reasons": [], "burden_type": "A 실질 저부담",
        "dong_type": "고주거비·직주근접형", "substitute_work": None,
    }
    base.update(over)
    return base


FORM = {"residence": "잠원동", "workplace": "역삼역", "deposit": "1000",
        "rent": "75", "work_days": "21", "age": "29", "depart_time": "08:10"}


def _ctx(**over):
    return build_chat_context(3, _fake_calc(**over), FORM, with_policy=False)


def test_contract_version_is_stamped():
    assert _ctx()["version"] == CONTEXT_VERSION


def test_missing_calc_key_raises():
    """조용히 빈 컨텍스트를 주면 챗봇이 아무 말이나 하게 된다."""
    broken = _fake_calc()
    del broken["status"]
    with pytest.raises(ValueError, match="status"):
        build_chat_context(3, broken, FORM, with_policy=False)


def test_no_calc_raises():
    with pytest.raises(ValueError):
        build_chat_context(3, None, FORM, with_policy=False)


def test_share_is_derived_not_invented():
    """구성비는 컨텍스트 값끼리의 나눗셈이어야 한다."""
    home = _ctx()["home"]
    assert home["share_housing"] == pytest.approx(795_000 / 974_000, abs=1e-4)


def test_display_strings_carry_their_unit():
    """단위를 문자열 안에 넣는다. 숫자만 주면 모델이 단위를 붙이다 틀린다.
    통근시간 가치 10.8만원을 "10.8시간"이라고 답한 적이 있는데, 숫자가
    맞아서 게이트를 통과했다. 숫자 게이트는 단위를 보지 못한다."""
    d = _ctx()["home"]["display"]
    assert d["housing"] == "79.5만원"
    assert d["total"] == "97.4만원"
    assert d["time_value"] == "12.4만원"
    assert d["commute_min"] == "17.2분"


def test_fare_and_fare_actual_are_both_present():
    """'왜 9.4만이 아니라 5.5만인가'에 답하려면 두 값이 다 필요하다."""
    home = _ctx()["home"]
    assert home["fare_won"] == 55_000
    assert home["fare_actual_won"] == 94_000


# ─────────────────────────────────────────────────────────────
# 3. 단위 검사 — 모르는 것
# ─────────────────────────────────────────────────────────────

def _unknown_fields(ctx):
    return {u["field"] for u in ctx["unknown"]}


def test_always_unknown_fields():
    """폼에 없는 것은 페이지와 무관하게 늘 모른다."""
    fields = _unknown_fields(_ctx())
    assert {"income", "savings", "housing_type", "congestion"} <= fields


def test_missing_route_is_marked_unknown():
    fields = _unknown_fields(_ctx(commute_min=None, fare=None,
                                  fare_actual=None, time_value=None))
    assert "commute_min" in fields


def test_internal_commute_is_explained_not_hidden():
    """교통비 0원은 값이 빠진 게 아니라 걸어갈 거리라는 뜻이다."""
    ctx = _ctx(fare=0, fare_actual=0, commute_min=13.7)
    reason = next(u["reason"] for u in ctx["unknown"] if u["field"] == "fare")
    assert "0원" in reason


def test_candidate_basis_is_disclosed():
    """현재 집은 실제 계약 금액, 후보는 동네 중앙값이다. 섞어 비교하면 안 된다."""
    calc = _fake_calc(candidate={"name": "신길1동", "total": 1_028_000,
                                 "housing": 649_000, "fare": 55_000,
                                 "fare_actual": 69_000, "time_value": 324_000,
                                 "commute_min": 42.9, "transfer": 1,
                                 "status": "ok", "reasons": [],
                                 "burden_type": None, "dong_type": None})
    ctx = build_chat_context(5, calc, FORM, with_policy=False)
    assert "candidate_housing_basis" in _unknown_fields(ctx)


def test_page5_and_page6_candidates_have_same_shape():
    """한쪽에만 있는 필드를 상대편에도 있다고 착각하지 않게 한다."""
    one = {"name": "신길1동", "total": 1_028_000, "housing": 649_000,
           "fare": 55_000, "fare_actual": 69_000, "time_value": 324_000,
           "commute_min": 42.9, "transfer": 1, "status": "ok", "reasons": []}
    c5 = build_chat_context(5, _fake_calc(candidate=dict(one)), FORM,
                            with_policy=False)["candidates"]
    c6 = build_chat_context(6, _fake_calc(candidates=[dict(one)]), FORM,
                            with_policy=False)["candidates"]
    assert c5[0].keys() == c6[0].keys()
    assert c5[0]["delta_total_won"] == c6[0]["delta_total_won"]


# ─────────────────────────────────────────────────────────────
# 4. 단위 검사 — 숫자 게이트
# ─────────────────────────────────────────────────────────────

def test_context_number_passes():
    ctx = _ctx()
    ok, bad = verify_numbers("주거비는 79.5만원이에요.", ctx)
    assert ok, bad


def test_invented_number_is_caught():
    ok, bad = verify_numbers("주거비는 88.8만원이에요.", _ctx())
    assert not ok and "88.8" in bad


def test_won_and_man_are_both_allowed():
    ctx = _ctx()
    assert verify_numbers("795,000원", ctx)[0]
    assert verify_numbers("79.5만원", ctx)[0]
    assert verify_numbers("약 80만원", ctx)[0]


def test_share_percent_is_allowed():
    """구성비를 퍼센트로 말하는 것까지는 허용한다."""
    assert verify_numbers("주거비가 81.6%를 차지해요.", _ctx())[0]


def test_arithmetic_result_is_not_allowed():
    """뺄셈 결과는 서버가 미리 넣어줘야 한다. LLM 에게 계산을 허용하면
    컨텍스트 값들의 조합이 전부 통과해 게이트가 헐거워진다."""
    ok, bad = verify_numbers("주거비에서 교통비를 빼면 74.0만원이에요.", _ctx())
    assert not ok and "74.0" in bad


def test_precomputed_delta_is_allowed():
    """화면에 뜨는 절감액은 컨텍스트에 담겨 있으므로 통과해야 한다."""
    calc = _fake_calc(candidates=[{"name": "청림동", "total": 768_000,
                                   "housing": 503_000, "fare": 55_000,
                                   "fare_actual": 69_000,
                                   "time_value": 196_000, "commute_min": 27.1,
                                   "transfer": 1, "delta_total": 230_000,
                                   "status": "ok", "reasons": []}])
    ctx = build_chat_context(6, calc, FORM, with_policy=False)
    assert verify_numbers("청림동으로 옮기면 23.0만원 줄어요.", ctx)[0]


# ─────────────────────────────────────────────────────────────
# 5. DB 타입 정규화
# ─────────────────────────────────────────────────────────────

def _decimal_ctx():
    """MySQL 이 실제로 돌려주는 모양. 수치 컬럼이 Decimal 로 온다."""
    calc = _fake_calc(housing=Decimal("802000"), fare=Decimal("55000"),
                      fare_actual=Decimal("69000"),
                      time_value=Decimal("204000"),
                      total=Decimal("1061000"),
                      commute_min=Decimal("28.3"))
    return build_chat_context(6, calc, FORM, with_policy=False)


def test_context_is_json_serializable():
    """컨텍스트는 그대로 프롬프트에 실려 나간다. 직렬화가 안 되면
    LLM 호출이 시작도 못 하고 매번 폴백으로 떨어진다."""
    assert json.dumps(_decimal_ctx(), ensure_ascii=False)


def test_decimal_values_join_the_allowed_set():
    """이쪽이 더 위험하다. Decimal 은 isinstance(v, (int, float)) 를
    통과하지 못해 허용 숫자 집합에서 조용히 빠진다. 그러면 화면에 뜬
    맞는 값이 '지어낸 숫자'로 차단된다. 터지지 않고 틀린다."""
    ctx = _decimal_ctx()
    assert verify_numbers("주거비 80.2만원, 총부담 106.1만원이에요.", ctx)[0]


def test_date_values_are_stringified():
    """정책 as_of 같은 날짜도 그대로 두면 직렬화에서 걸린다."""
    from web.chat_context import _plain
    out = _plain({"as_of": datetime.date(2026, 8, 5)})
    assert out["as_of"] == "2026-08-05"


def test_list_markers_and_ranks_are_not_claims():
    """목록 번호와 순위는 값 주장이 아니다.

    평가에서 두 번 연속 이것 때문에 막혔는데 두 번 다 답변의 금액은
    전부 맞았다. 정작 위험했던 오류(다른 동네 값을 붙이는 것)는 숫자
    게이트로 잡히지 않는 종류였다.
    """
    ctx = _ctx()
    assert verify_numbers("1) 첫째 79.5만원, 2) 둘째 97.4만원", ctx)[0]
    assert verify_numbers("총부담 2위예요.", ctx)[0]


def test_unit_bearing_numbers_are_still_claims():
    """서수를 봐준다고 단위가 붙은 값까지 봐주지는 않는다.

    한 자리 정수라도 뒤에 ")" 나 "위" 가 없으면 그대로 검사한다.
    """
    ctx = _ctx()
    assert not verify_numbers("환승은 7회예요.", ctx)[0]
    assert not verify_numbers("월세는 88만원이에요.", ctx)[0]


def test_booleans_are_not_counted_as_numbers():
    """True 를 1 로 세면 게이트에 1 이 무조건 뚫린다."""
    assert 1 not in collect_numbers({"flag": True, "other": False})
