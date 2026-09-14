"""게이트와 폴백 배선 테스트. API 를 부르지 않는다.

모델을 가짜 함수로 갈아끼워서, "지어낸 답변이 사용자에게 도달하지
못하는가"만 본다. 모델이 실제로 얼마나 잘 답하는지는 골든셋 평가
(tests/eval/) 의 몫이고, 여기서는 배선만 고정한다.
"""

import json

import pytest

from web.chat_context import (RECOMMEND_RULE, build_chat_context,
                              fallback_answer, verify_numbers)
from web.chat_llm import SYSTEM_PROMPT, ask, build_messages, check

FORM = {"residence": "잠원동", "workplace": "역삼역", "deposit": "1000",
        "rent": "75", "work_days": "21", "age": "29", "depart_time": "08:10"}

CALC = {
    "housing": 795_000, "fare": 55_000, "fare_actual": 94_000,
    "time_value": 124_000, "total": 974_000,
    "work_days": 21, "commute_min": 17.2, "transit_pass_cap": 55_000,
    "home": "잠원동", "work": "역삼1동",
    "home_code": "11650540", "work_code": "11680640",
    "status": "ok", "reasons": [], "burden_type": "A 실질 저부담",
    "dong_type": "고주거비·직주근접형", "substitute_work": None,
    "candidates": [{"name": "청림동", "type": "저주거비·지역연계형",
                    "housing": 503_000, "fare": 69_000, "fare_actual": 69_000,
                    "time_value": 196_000, "total": 768_000,
                    "commute_min": 27.1, "transfer": 1,
                    "delta_total": 206_000, "status": "ok", "reasons": []}],
}


@pytest.fixture
def ctx():
    return build_chat_context(6, dict(CALC), FORM, with_policy=False)


def _reply(**over):
    body = {"answer": "월 총부담은 97.4만원이에요.",
            "cited": ["home.display.total"], "refused": False,
            "unknown_used": []}
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
# 게이트
# ─────────────────────────────────────────────────────────────

def test_clean_answer_passes(ctx):
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: _reply())
    assert out["source"] == "llm"
    assert out["blocked_reason"] is None


def test_invented_number_is_blocked(ctx):
    """지어낸 숫자가 사용자에게 도달하면 안 된다."""
    bad = _reply(answer="월 총부담은 123.4만원이에요.")
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: bad)
    assert out["source"] == "fallback"
    assert "123.4" in out["blocked_reason"]


def test_ghost_citation_does_not_block(ctx):
    """근거 경로가 틀려도 답변은 내보낸다.

    차단 조건으로 뒀을 때 실제로 걸린 세 건이 전부 옳은 답변이었고,
    거짓을 잡은 적은 없었다. 사용자를 오도하는 것은 답변 문장이지
    cited 배열이 아니며, 문장은 숫자·언어 게이트가 이미 막는다.
    근거 표기의 품질은 골든셋 평가에서 따로 채점한다.
    """
    bad = _reply(cited=["home.display.totall"])
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: bad)
    assert out["source"] == "llm"


def test_context_prefix_in_path_is_tolerated(ctx):
    """모델이 프롬프트 머리말("# CONTEXT")을 경로에 붙이는 일이 잦다.
    사람이 보기엔 맞는 경로라 이것 때문에 답변을 버리면 손해가 크다."""
    ok = _reply(cited=["CONTEXT.home.display.total"])
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: ok)
    assert out["source"] == "llm"


def test_list_item_by_name_is_tolerated(ctx):
    """unknown 은 리스트인데 모델은 'unknown.congestion' 처럼 부른다."""
    ok = _reply(cited=["candidates.청림동.display.total"])
    out = ask(ctx, "청림동은 얼마예요?", call=lambda m: ok)
    assert out["source"] == "llm"


def test_grader_still_scores_citations(ctx):
    """런타임에서 안 막는다고 평가에서도 봐주는 것은 아니다.
    골든셋 채점기는 없는 경로를 여전히 감점한다."""
    from web.chat_eval import grade
    item = {"id": "t", "must_refuse": False,
            "must_cite": ["home.display.total"]}
    res = grade(item, ctx, _reply(cited=["없는.경로"]))
    assert not res["axes"]["citation"]


def test_correct_refusal_survives_bad_citation(ctx):
    """실제로 있었던 사고. 모델이 혼잡도 질문을 정확히 거절했는데
    경로 표기가 어긋났다는 이유로 그 거절이 폐기됐다.
    거절 답변은 값을 주장하지 않으므로 근거 경로로 막지 않는다."""
    bad = _reply(answer="혼잡도는 일부 구간만 자료가 있어 답해드리기 어려워요.",
                 cited=["없는.경로"], refused=True,
                 unknown_used=["congestion"])
    out = ask(ctx, "어느 구간이 가장 혼잡해요?", call=lambda m: bad)
    assert out["source"] == "llm" and out["refused"]


def test_refusal_still_cannot_invent_numbers(ctx):
    """거절이라고 다 봐주는 것은 아니다. 숫자 게이트는 그대로 적용된다."""
    bad = _reply(answer="혼잡도는 몰라요. 다만 총부담은 555.5만원이에요.",
                 cited=[], refused=True, unknown_used=["congestion"])
    out = ask(ctx, "어느 구간이 가장 혼잡해요?", call=lambda m: bad)
    assert out["source"] == "fallback"


def test_broken_json_is_blocked(ctx):
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: "JSON 아님")
    assert out["source"] == "fallback"


def test_empty_answer_is_blocked(ctx):
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: _reply(answer="  "))
    assert out["source"] == "fallback"


def test_api_failure_falls_back(ctx):
    """키가 없거나 네트워크가 죽어도 화면은 떠야 한다."""
    def boom(_):
        raise RuntimeError("ANTHROPIC_API_KEY 가 없습니다.")
    out = ask(ctx, "총부담이 얼마예요?", call=boom)
    assert out["source"] == "fallback"
    assert out["answer"]


def test_code_fence_is_tolerated(ctx):
    """모델이 ```json 을 붙여 오는 건 흔하다. 그것 때문에 버리지 않는다."""
    fenced = "```json\n" + _reply() + "\n```"
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: fenced)
    assert out["source"] == "llm"


def test_refusal_is_carried_through(ctx):
    out = ask(ctx, "제 저축 여력은요?",
              call=lambda m: _reply(answer="소득을 입력받지 않아 계산할 수 없어요.",
                                    cited=[], refused=True,
                                    unknown_used=["savings"]))
    assert out["source"] == "llm" and out["refused"]
    assert out["unknown_used"] == ["savings"]


def test_chinese_answer_is_blocked(ctx):
    """로컬 모델이 한국어로 물어도 중국어로 답하는 일이 잦다.
    프롬프트로 부탁하는 것만으로는 안 막혀서 게이트에서 검사한다."""
    bad = _reply(answer="97.4这个数值表示每月总负担。")
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: bad)
    assert out["source"] == "fallback"
    assert "한국어" in out["blocked_reason"]


def test_hanja_is_blocked(ctx):
    """숫자도 근거도 맞는데 한자가 섞인 경우. 다른 게이트로는 안 잡힌다."""
    bad = _reply(answer="월 총부담은 97.4萬원이에요.")
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: bad)
    assert out["source"] == "fallback"


def test_prompt_requires_korean():
    assert "한국어로 쓴다" in SYSTEM_PROMPT


def test_fallback_is_korean(ctx):
    """게이트가 한국어를 요구하는데 폴백이 걸리면 보여줄 것이 없어진다."""
    assert check(ctx, {"answer": fallback_answer(ctx), "cited": []})[0]


def test_check_is_usable_alone(ctx):
    assert check(ctx, {"answer": "97.4만원이에요.", "cited": []})[0]
    assert not check(ctx, {"answer": "999.9만원이에요.", "cited": []})[0]


# ─────────────────────────────────────────────────────────────
# 폴백
# ─────────────────────────────────────────────────────────────

def test_fallback_passes_its_own_gate(ctx):
    """폴백이 게이트에 걸리면 보여줄 것이 아무것도 없어진다.

    이 테스트가 이 파일에서 가장 중요하다. 마지막 방어선이
    스스로 무너지지 않는지 본다.
    """
    ok, bad = verify_numbers(fallback_answer(ctx), ctx)
    assert ok, bad


@pytest.mark.parametrize("page", [3, 4, 5, 6])
def test_fallback_works_on_every_page(page):
    calc = dict(CALC)
    if page in (3, 4):
        calc.pop("candidates")
    elif page == 5:
        calc["candidate"] = calc.pop("candidates")[0]
    ctx = build_chat_context(page, calc, FORM, with_policy=False)
    text = fallback_answer(ctx)
    assert verify_numbers(text, ctx)[0]
    assert "97.4" in text


def test_fallback_survives_missing_route():
    """통근 자료가 없는 동에서도 터지지 않아야 한다."""
    calc = dict(CALC)
    calc.update(commute_min=None, fare=None, fare_actual=None,
                time_value=None, total=None)
    calc.pop("candidates")
    ctx = build_chat_context(3, calc, FORM, with_policy=False)
    assert fallback_answer(ctx)


def test_fallback_shows_reliability_notice():
    """화면이 '참고용' 라벨을 띄우면 폴백도 같은 말을 해야 한다."""
    calc = dict(CALC)
    calc.pop("candidates")
    calc.update(status="low_confidence", reasons=["거래 30건 미만"])
    ctx = build_chat_context(3, calc, FORM, with_policy=False)
    assert "참고용" in fallback_answer(ctx)


# ─────────────────────────────────────────────────────────────
# 프롬프트
# ─────────────────────────────────────────────────────────────

def test_prompt_forbids_arithmetic():
    """계산을 허용하면 게이트가 잡지 못하는 값이 생긴다."""
    assert "계산하지 않는다" in SYSTEM_PROMPT


def test_prompt_carries_recommend_rule_into_context(ctx):
    """추천 기준은 숫자가 아니라 규칙이라 게이트로 못 막는다.
    컨텍스트에 실려 있어야 지어내지 않는다."""
    assert ctx["recommend_rule"] == list(RECOMMEND_RULE)
    assert "recommend_rule" in SYSTEM_PROMPT


def test_won_values_are_hidden_from_the_prompt(ctx):
    """컨텍스트에는 795000(원)과 "79.5"(만원)가 함께 있는데, 작은 모델이
    앞의 숫자를 집어 "주거비 795만원"이라고 말했다. 20문항 평가에서 차단된
    12건 중 대부분이 이 한 가지 실수였다. 보여 주지 않으면 말할 수 없다."""
    msg = build_messages(ctx, "총부담이 얼마예요?")[0]["content"]
    assert "795000" not in msg and "974000" not in msg
    assert '"79.5만원"' in msg and '"97.4만원"' in msg
    # 원으로 말해야 하는 값(시간가치 단가)은 남아 있어야 한다.
    assert "10320" in msg


def test_context_itself_keeps_won_values(ctx):
    """프롬프트에서만 가린다. 폴백 문장과 허용 숫자 집합은 그대로 쓴다."""
    assert ctx["home"]["housing_won"] == 795_000


def test_blocked_answer_is_kept_for_evaluation(ctx):
    """폴백을 채점하면 안 된다. 화면 값을 그대로 나열한 문장이라 근거
    기준을 항상 만족해서, 차단된 문항이 통과로 집계된다(실제로 그랬다)."""
    bad = _reply(answer="총부담은 555.5만원이에요.")
    out = ask(ctx, "총부담이 얼마예요?", call=lambda m: bad)
    assert out["source"] == "fallback"
    assert "555.5" in out["model_answer"]
    assert "555.5" not in out["answer"]


def test_limits_are_listed_before_the_context(ctx):
    """평가에서 거절 문항 6개가 전부 실패했는데 사유는 모두 컨텍스트에
    있었다. 작은 모델이 긴 JSON 가운데의 unknown 배열을 못 본 것이다.
    읽어야 하는 것은 읽기 좋은 자리에 둔다."""
    msg = build_messages(ctx, "혼잡까지 고려하면 어디가 괜찮아요?")[0]["content"]
    assert msg.index("# 답할 수 없는 것") < msg.index("# CONTEXT")
    assert "congestion:" in msg and "sort_request:" in msg


def test_caveats_are_not_refusal_reasons(ctx):
    """후보 주거비의 기준 차이는 단서지 거절 사유가 아니다.
    거절 목록에 섞으면 비교 질문까지 refused=true 로 나온다."""
    msg = build_messages(ctx, "이 지역은 왜 월세 착시예요?")[0]["content"]
    head = msg[:msg.index("# 답할 때 함께 밝힐 것")]
    assert "candidate_housing_basis" not in head
    assert "중앙값" in msg


def test_messages_include_whole_context(ctx):
    msg = build_messages(ctx, "총부담이 얼마예요?")[0]["content"]
    assert "총부담이 얼마예요?" in msg
    assert "recommend_rule" in msg and "답할 수 없는 것" in msg


def test_no_calc_rule_is_repeated_next_to_the_question(ctx):
    """컨텍스트 창이 넘치면 앞쪽(시스템 프롬프트)부터 잘린다.
    계산 금지가 사라지면 모델이 원 단위 값을 직접 나눠 없는 숫자를 만든다."""
    msg = build_messages(ctx, "총부담이 얼마예요?")[0]["content"]
    # 질문은 앞뒤에 모두 놓이므로 마지막 등장 위치와 비교한다.
    assert msg.index("직접 계산하지 않는다") < msg.rindex("총부담이 얼마예요?")


def test_question_is_placed_before_and_after_context(ctx):
    """작은 모델은 긴 JSON 가운데를 흘려보고 엉뚱한 질문에 답한다.
    실제로 정책을 물었는데 추천 이유를 답한 적이 있다."""
    msg = build_messages(ctx, "지원은 뭐가 있어요?")[0]["content"]
    assert msg.count("지원은 뭐가 있어요?") == 2
    assert msg.index("지원은 뭐가 있어요?") < msg.index("# CONTEXT")
