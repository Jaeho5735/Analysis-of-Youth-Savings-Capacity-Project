"""챗봇에 넘길 컨텍스트를 만든다. LOCA 답변의 유일한 사실 원천.

왜 이 파일이 따로 있는가
------------------------
챗봇이 숫자를 지어내는 것을 프롬프트로 막을 수는 없다. 대신 이렇게 한다.

    1. 화면이 이미 계산해 둔 값(_calc)만 모아서 프롬프트에 넣는다.
    2. 답변에 나온 숫자가 그 집합 밖이면 답변을 버린다(collect_numbers).

그래서 "무엇이 사실인가"와 "무엇을 허용할 것인가"가 한 파일에 있어야 한다.
둘을 떼어놓으면 한쪽만 고쳤을 때 검증이 조용히 헐거워진다. 3단계에서 찾은
버그 7건 중 4건이 "짝이 되는 두 자리의 방어가 한 줄 다른" 형태였고,
여기가 딱 그 구조라서 같은 파일에 붙여 둔다.

계산은 하지 않는다
------------------
이 파일은 _calc 에 있는 값을 옮겨 담기만 한다. 산식을 다시 적으면
web/service.py 의 _monthly 와 두 벌이 되고, 그게 이 프로젝트가 2단계에서
없앤 문제다. 여기서 새로 만드는 수치는 두 가지뿐이며 둘 다 나눗셈·뺄셈이다.

    share_housing = housing / total          (구성비)
    delta_total   = home.total - cand.total  (절감액, 6페이지는 _calc 에 이미 있음)

모르는 것을 남긴다
------------------
unknown 배열이 이 계약의 핵심이다. 값이 없는 것을 조용히 빼면 챗봇은
"없다"는 사실 자체를 모른 채 답한다. 무엇을 왜 모르는지까지 실어 보낸다.
query_dong._judge_policy 가 unchecked 로 하는 것과 같은 원칙이다.
"""

import datetime as _dt
import re
from decimal import Decimal

from web.service import (DEPOSIT_RATE_BY_REGION, DEPOSIT_RATE_DEFAULT,
                         TIME_VALUE_PER_HOUR, _num_only, _pass_for_age,
                         status_note)

CONTEXT_VERSION = "loca-context-v1"

# _calc 네 벌이 공통으로 가져야 하는 키. 하나라도 없으면 그 페이지는
# 챗봇을 켤 수 없다. 테스트가 이 목록을 그대로 쓴다.
REQUIRED_CALC_KEYS = frozenset({
    "housing", "fare", "fare_actual", "time_value", "total",
    "work_days", "commute_min", "transit_pass_cap",
    "home", "work", "home_code", "work_code",
    "status", "reasons", "burden_type", "dong_type", "substitute_work",
})

# 화면에 아예 없거나 이 서비스가 다루지 않는 것. 페이지와 무관하게 항상 모른다.
# 문구는 그대로 답변에 쓰이므로 "왜 없는지"까지 적는다.
ALWAYS_UNKNOWN = (
    ("income", "월 소득은 입력받지 않아요. 소득으로 갈리는 정책이 적어 "
               "입력을 하나 더 늘리지 않기로 했어요."),
    ("savings", "소득을 모르기 때문에 저축 여력이나 잔여액은 계산하지 않아요."),
    ("housing_type", "주택 유형(오피스텔·연립 등)은 입력받지 않아서 "
                     "보증금 월환산은 권역 중앙값으로만 계산해요."),
    ("congestion", "혼잡도는 일부 노선·구간만 자료가 있어서 "
                   "모든 경로에 대해 답할 수 없어요."),
    # 골든셋을 쓰다가 4페이지 칩("왜 많이 찾는 후보예요?")이 답할 수 없는
    # 질문임을 발견해서 넣었다. 인기도는 이 서비스에 없는 축이고, 숫자가
    # 없어서 verify_numbers 로도 못 잡는다. 사실로 막아야 하는 자리다.
    ("popularity", "얼마나 많이 찾는 지역인지는 자료가 없어요. 추천은 인기가 "
                   "아니라 주거비·통근시간·교통비로 계산한 결과예요."),
    ("scope", "분석 범위는 서울시 행정동이에요. 서울 밖 지역은 답할 수 없어요."),
)


# 사실이 없는 것(unknown)과 권한이 없는 것은 다르다. 정렬을 바꿔달라는
# 요청은 자료가 없어서가 아니라 챗봇이 할 수 없는 일이라 거절한다.
# 둘을 한 목록에 섞으면 "자료가 없어서 정렬을 못 바꾼다"는 이상한 답이 나온다.
# unknown 중 "답할 수 없는 것"이 아니라 "말할 때 함께 밝혀야 하는 것".
# 후보 주거비의 기준 차이는 거절 사유가 아니라 단서다. 이걸 거절 목록에
# 섞으면 비교 질문까지 refused=true 로 나온다.
CAVEAT_FIELDS = frozenset({"candidate_housing_basis"})

CANNOT_DO = (
    ("sort_request", "화면의 정렬이나 필터를 바꾸는 건 제가 할 수 없어요. "
                     "값을 설명해 드리는 것까지만 할 수 있어요."),
    ("booking", "집을 구해 드리거나 지원 사업을 대신 신청해 드릴 수는 없어요."),
)


# 추천 3곳이 어떻게 뽑혔는지. 값이 아니라 규칙이라 숫자 게이트로는 막을 수
# 없는 자리다. 이게 없으면 챗봇이 "주거비와 통근을 종합해서" 같은 그럴듯한
# 일반론을 지어낸다. src.db.query_dong.recommend_dongs 의 실제 동작이다.
RECOMMEND_RULE = (
    "총부담(주거비 + 교통비 + 통근시간 가치)이 낮은 순으로 고른다.",
    "행정동 유형별로 한 곳씩만 남긴다. 같은 유형이 연달아 나오면 "
    "선택지가 사실상 하나가 되기 때문이다.",
    "현재 집, 지금 비교 중인 후보, 표본이 부실한 동은 후보에서 뺀다.",
    "그래서 화면의 '1위'는 서울 전체 순위가 아니라 "
    "이 규칙으로 고른 세 곳 안에서의 순위다.",
)


def _plain(node):
    """DB 가 돌려준 값을 순수 파이썬 타입으로 바꾼다.

    MySQL 커넥터는 수치 컬럼을 Decimal 로 준다. 이걸 그대로 두면 두 군데가
    조용히 망가진다.
      1) json.dumps 가 TypeError 를 내서 LLM 호출이 시작도 못 한다.
      2) collect_numbers 의 isinstance(v, (int, float)) 를 Decimal 이 통과하지
         못해, 화면에 뜬 값이 허용 숫자 집합에서 빠진다. 그러면 맞는 답변이
         "지어낸 숫자"로 차단된다.
    2번이 더 무섭다. 터지지 않고 조용히 틀리기 때문이다.

    컨텍스트는 그대로 JSON 으로 나가는 계약이므로, 여기서 한 번에 정리한다.
    """
    if isinstance(node, dict):
        return {k: _plain(v) for k, v in node.items()}
    if isinstance(node, (list, tuple, set)):
        return [_plain(v) for v in node]
    if isinstance(node, Decimal):
        # 원 단위 금액은 정수다. 소수가 남는 값(통근시간)만 float 로 둔다.
        return int(node) if node == node.to_integral_value() else float(node)
    if isinstance(node, (_dt.date, _dt.datetime)):
        return node.isoformat()
    return node


def _man(won, digits=1):
    """원 -> 만원 문자열. service.man1 과 같은 규칙."""
    if won is None:
        return None
    return f"{won / 10_000:.{digits}f}"


def _unit(value, unit):
    """표시 문자열에 단위를 붙인다. 값이 없으면 None 그대로."""
    return None if value is None else f"{value}{unit}"


def _ratio(part, whole):
    if not whole or part is None:
        return None
    return round(part / whole, 4)


def _place(calc, prefix="", slim=False):
    """home / candidate 한 곳을 같은 모양으로 만든다.

    현재 집과 후보를 다른 모양으로 담으면 챗봇이 둘을 비교할 때
    한쪽에만 있는 필드를 상대편에도 있다고 착각한다.
    """
    total = calc.get("total")
    # 후보는 슬림하게 싣는다. CPU 추론에서 입력 길이가 곧 대기 시간이고,
    # 후보 세 곳이 현재 집과 같은 밀도로 들어가면 컨텍스트가 배로 늘어난다.
    # 화면 표에 없는 값(정기권 적용 전 실지출, 행정동 코드)은 뺀다.
    out = {
        "name": calc.get("name") or calc.get(prefix or "home"),
        "dong_type": calc.get("dong_type") or calc.get("type") or None,
        "burden_type": calc.get("burden_type"),
        "housing_won": calc.get("housing"),
        "fare_won": calc.get("fare"),
        "time_value_won": calc.get("time_value"),
        "total_won": total,
        "commute_min": calc.get("commute_min"),
        "transfer": calc.get("transfer"),
        "share_housing": _ratio(calc.get("housing"), total),
        # 화면에 찍히는 문자열. 챗봇은 이 표기를 그대로 인용하면 된다.
        # 여기서 만들어 주지 않으면 LLM 이 나눗셈을 하다가 틀린다.
        #
        # 단위를 문자열 안에 넣는다. 숫자만 주면 모델이 단위를 붙이다 틀린다.
        # 실제로 통근시간 가치 10.8만원을 "10.8시간"이라고 답한 적이 있다.
        # 숫자는 맞아서 게이트를 통과했다. 숫자 게이트는 단위를 보지 못한다.
        # 원 단위 값을 프롬프트에서 뺐을 때와 같다 — 붙일 일이 없으면 틀릴 일도 없다.
        "display": {
            "housing": _unit(_man(calc.get("housing")), "만원"),
            "fare": _unit(_man(calc.get("fare")), "만원"),
            "time_value": _unit(_man(calc.get("time_value")), "만원"),
            "total": _unit(_man(total), "만원"),
            "commute_min": (None if calc.get("commute_min") is None
                            else f"{calc['commute_min']:.1f}분"),
        },
    }
    if not slim:
        out["code"] = calc.get("code") or calc.get("home_code")
        out["fare_actual_won"] = calc.get("fare_actual")
        out["display"]["fare_actual"] = _unit(
            _man(calc.get("fare_actual")), "만원")
    return out


def _candidates_of(calc):
    """페이지마다 후보가 담긴 자리가 다르다. 여기서 한 모양으로 모은다.

    5페이지는 사용자가 입력한 후보 한 곳(candidate),
    6페이지는 비교 표의 열들(candidates)이다.
    """
    raw = calc.get("candidates")
    if raw is None:
        one = calc.get("candidate")
        raw = [one] if one else []

    out = []
    home_total = calc.get("total")
    for c in raw:
        item = _place(dict(c), slim=True)
        item["name"] = c.get("name")
        delta = c.get("delta_total")
        if delta is None and None not in (home_total, c.get("total")):
            delta = home_total - c["total"]
        item["delta_total_won"] = delta
        item["display"]["delta_total"] = (_unit(_man(delta), "만원")
                                          if delta is not None else None)
        item["status"] = c.get("status")
        item["reasons"] = c.get("reasons") or []
        out.append(item)
    return out


def _policy_block(age=None, rent_won=None, conn=None):
    """정책 매칭 결과. 조회 실패는 치명적이지 않으므로 None 으로 넘긴다.

    matched 만 주면 "왜 저 정책은 안 뜨나"에 답할 수 없다. excluded 의
    탈락 사유까지 실어야 2단계에서 목적을 재정의한 그 질문에 답이 된다.
    """
    try:
        from src.db.query_dong import get_policies
        res = get_policies(age=age, income=None, rent=rent_won, conn=conn)
    except Exception:
        return None

    # 정책은 열두 개가 넘게 붙어서 컨텍스트에서 가장 무거운 자리다.
    # CPU 추론에서는 입력 길이가 그대로 대기 시간이라, 답변에 쓰이지 않는
    # 필드는 싣지 않는다. source_url 은 화면 링크용이고 answer 에 나올 일이
    # 없으며, 신청기간 안내문은 길기만 하고 어차피 각 기관에서 확인해야 한다.
    def _short(text, limit=40):
        text = (text or "").strip().replace("\n", " ")
        return text[:limit] + ("…" if len(text) > limit else "")

    return {
        "as_of": res.get("as_of"),
        "matched": [
            {"name": p.get("policy_name"),
             "benefit": _short(p.get("benefit_text")),
             "apply_type": p.get("apply_type"),
             # 조회 계층이 확인하지 못한 조건. 이걸 빼면 소득 요건이 있는
             # 정책을 "받을 수 있다"고 단정하게 된다. 절대 줄이지 않는다.
             "unchecked": p.get("unchecked") or []}
            for p in (res.get("matched") or [])
        ],
        # 탈락 사유는 "왜 저 정책은 안 뜨나"에 답하려고 남긴다.
        # 다만 전부 실을 필요는 없어 앞쪽 몇 개만 둔다.
        "excluded": [
            {"name": p.get("policy_name"),
             "reasons": (p.get("reasons") or [])[:2]}
            for p in (res.get("excluded") or [])[:3]
        ],
    }


def _unknowns(page, calc, user_input, candidates):
    """이 화면이 모르는 것을 모은다. 답변 거절의 근거가 된다."""
    out = [{"field": f, "reason": r} for f, r in ALWAYS_UNKNOWN]

    if calc.get("commute_min") is None:
        out.append({"field": "commute_min",
                    "reason": "이 구간은 통근 경로 자료가 없어서 "
                              "통근시간과 시간가치를 계산하지 못했어요."})

    # _derive 가 내부통근에만 요금 0 을 넣는다. 걸어갈 거리라 대중교통
    # 경로가 안 나오는 것이며, 값이 빠진 것과는 다르다. 구분해서 밝힌다.
    if calc.get("fare_actual") == 0 and calc.get("commute_min") is not None:
        out.append({"field": "fare",
                    "reason": "거주지와 근무지가 같은 동이라 대중교통 요금이 "
                              "산출되지 않았어요. 교통비 0원은 값이 빠진 게 "
                              "아니라 걸어갈 거리라는 뜻이에요."})

    if page in (5, 6) and not (user_input or {}).get("depart_time"):
        out.append({"field": "depart_time",
                    "reason": "이 화면은 출발 시간을 쓰지 않아서 "
                              "시간대별 차이는 답할 수 없어요."})

    if candidates:
        out.append({"field": "candidate_housing_basis",
                    "reason": "후보 지역 주거비는 그 동네 청년 1인가구 "
                              "중앙값이에요. 현재 집처럼 실제 계약 금액이 "
                              "아니라서 그대로 비교하면 안 돼요."})
    return out


def build_chat_context(page, calc, user_input=None, conn=None,
                       with_policy=True):
    """LocaContext v1 을 만든다.

    page       : 3 | 4 | 5 | 6
    calc       : build_pageN 이 남긴 data["_calc"]
    user_input : app.read_form() 결과
    with_policy: False 면 정책 조회를 건너뛴다(DB 없이 도는 테스트용)

    계약을 못 지키면 조용히 빈 컨텍스트를 주지 않고 예외를 던진다.
    빈 채로 넘기면 챗봇이 "자료가 없다"가 아니라 아무 말이나 하게 된다.
    """
    if page not in (3, 4, 5, 6):
        raise ValueError(f"지원하지 않는 페이지: {page}")
    if not isinstance(calc, dict):
        raise ValueError("_calc 가 없습니다. build_pageN 이 실패한 화면입니다.")

    missing = REQUIRED_CALC_KEYS - set(calc)
    if missing:
        raise ValueError(f"_calc 에 없는 키: {sorted(missing)}")

    ui = dict(user_input or {})
    age = _num_only(ui.get("age"), None)
    rent_won = (_num_only(ui.get("rent"), 0) or 0) * 10_000 or None
    deposit_won = (_num_only(ui.get("deposit"), 0) or 0) * 10_000 or None

    home = _place(calc)
    home["name"] = calc.get("home")
    cands = _candidates_of(calc)

    pass_info = _pass_for_age(ui.get("age"))

    ctx = {
        "version": CONTEXT_VERSION,
        "page": page,
        "user_input": {
            "residence": ui.get("residence"),
            "workplace": ui.get("workplace"),
            "deposit_won": deposit_won,
            "rent_won": rent_won,
            "work_days": calc.get("work_days"),
            "age": age,
            "depart_time": ui.get("depart_time"),
        },
        "home": home,
        "workplace": {"name": calc.get("work"), "code": calc.get("work_code")},
        "candidates": cands,
        "params": {
            "time_value_per_hour": TIME_VALUE_PER_HOUR,
            "time_value_basis": "2026년 최저임금",
            "transit_pass_cap": calc.get("transit_pass_cap"),
            "transit_pass_is_youth": pass_info["is_youth"],
            "work_days": calc.get("work_days"),
            "deposit_rate_default": DEPOSIT_RATE_DEFAULT,
            "deposit_rate_note": "보증금은 권역별 전월세전환율로 월환산한다.",
        },
        "reliability": {
            "status": calc.get("status"),
            "reasons": calc.get("reasons") or [],
            # 화면이 띄우는 라벨 그대로. 챗봇과 화면이 다른 말을 하면 안 된다.
            "notice": status_note({"status": calc.get("status"),
                                   "reasons": calc.get("reasons") or []}),
            "substitute_work": calc.get("substitute_work"),
        },
        "policy": _policy_block(age, rent_won, conn) if with_policy else None,
    }
    ctx["unknown"] = _unknowns(page, calc, ui, cands)
    ctx["cannot_do"] = [{"field": f, "reason": r} for f, r in CANNOT_DO]
    ctx["recommend_rule"] = list(RECOMMEND_RULE)
    return _plain(ctx)


# 방법·기준·이유를 묻는 신호. 이게 없으면 문서를 붙이지 않는다.
#
# "세 후보 중 총부담이 가장 낮은 곳은?" 같은 계산 질문에도 문서가 붙었다.
# 두 가지가 나빠진다. 프롬프트가 1,000자 늘어 CPU 추론이 그만큼 느려지고,
# 더 중요하게는 허용 숫자 집합에 문서의 숫자(819,166원, 31.0%, 4.3분 …)가
# 통째로 들어가 게이트가 헐거워진다. 관련 없는 근거는 안전을 깎는다.
# 한계: 이 단서만으로는 "화면 값을 묻는 질문"과 "방법론을 묻는 질문"을
# 완전히 가르지 못한다. "왜 그렇게 판단했어?"는 화면의 추천 이유를 묻는
# 것이지만 단서에 걸린다. 점수·맞은 토큰 수로 갈라 보려 했으나 두 집단이
# 겹쳤다(나쁜 질문 10.0점 vs 좋은 질문 5.2점). 어휘 검색은 단어가 맞았는지만
# 알지 질문의 성격은 모른다. 그래서 1차로만 거르고 나머지는 프롬프트가
# "문서는 방법·기준 질문에만 쓴다"로 처리한다.
DOC_CUES = ("왜", "어떻게", "기준", "근거", "방법", "이유", "어디서",
            "무슨", "어떤", "계산", "산출", "환산", "뜻", "의미",
            "판단", "정했", "골랐", "뽑았", "믿을")


def needs_docs(question):
    return any(c in (question or "") for c in DOC_CUES)


def attach_docs(context, question, searcher, k=2, force=False,
                min_score=None):
    """질문에 맞는 방법론 문서 조각을 컨텍스트에 붙인다.

    계산 컨텍스트는 "얼마인가"에 답하고, 문서는 "왜 그렇게 계산하는가"에
    답한다. 둘을 한 컨텍스트에 담아야 하는 이유는 허용 숫자 집합 때문이다.
    문서에 있는 전환율 5.39%, 거래 수 103,894 같은 값이 컨텍스트 밖에 있으면,
    모델이 문서를 정확히 인용해도 숫자 게이트가 차단한다.
    ①에서 원 단위 값을 컨텍스트에 안 넣어 맞는 답을 막을 뻔한 것과 같다.

    점수는 싣지 않는다. 12.73 같은 검색 점수가 허용 숫자에 섞이면
    답변에 근거 없는 숫자가 통과할 여지가 생긴다.

    검색 결과가 없으면 빈 목록이 된다. 그 자체가 "이 질문은 문서로
    답할 수 없다"는 사실이고, 프롬프트가 그때 거절하도록 돼 있다.

    방법·기준을 묻는 질문에만 붙인다(needs_docs). force=True 면 무조건
    검색한다 — 검색 평가에서 쓴다.
    """
    hits = []
    if searcher is not None and question and (force or needs_docs(question)):
        try:
            kw = {} if min_score is None else {"min_score": min_score}
            hits = searcher.search(question, k=k, **kw)
        except Exception:
            hits = []
    context["docs"] = [{"id": h["id"], "text": h["text"]} for h in hits]

    # 방법·기준을 물었는데 문서를 못 찾았으면 그 사실을 거절 사유로 남긴다.
    # 빈 목록만 주면 모델은 문서가 없다는 것을 모른 채 이유를 지어낸다.
    # unknown 목록은 프롬프트 맨 앞에 실리므로 거절 근거가 된다.
    if needs_docs(question) and not context["docs"]:
        entry = {"field": "doc_not_found",
                 "reason": "이 질문에 맞는 방법론 문서를 찾지 못했어요. "
                           "방법이나 기준은 문서에 있는 것만 말할 수 있어요."}
        unknown = context.setdefault("unknown", [])
        if all(u["field"] != "doc_not_found" for u in unknown):
            unknown.append(entry)
    return context


def fallback_answer(context):
    """LLM 답변을 버렸을 때 대신 보여줄 문장.

    화면이 이미 하고 있는 말로 돌아간다. "지금은 설명해 드릴 수 없어요"
    한 줄보다, 값을 그대로 읽어 주는 쪽이 사용자에게 쓸모 있다.

    여기서 쓰는 숫자는 전부 context 의 display 문자열이므로, 이 함수의
    출력은 자기 자신의 게이트를 항상 통과한다(테스트로 고정해 둔다).
    폴백이 게이트에 걸리면 보여줄 것이 아무것도 없어진다.
    """
    home = context["home"]
    d = home["display"]
    work = (context.get("workplace") or {}).get("name")

    head = f"{home['name']}에서 {work} 출근 기준이에요." if work else \
           f"{home['name']} 기준이에요."

    parts = []
    if d.get("housing"):
        parts.append(f"주거비 {d['housing']}")
    if d.get("fare"):
        parts.append(f"교통비 {d['fare']}")
    if d.get("time_value"):
        parts.append(f"통근시간 가치 {d['time_value']}")

    lines = [head]
    if parts and d.get("total"):
        lines.append(" + ".join(parts) + f"을 더하면 월 총부담이 "
                                         f"{d['total']}이에요.")
    if d.get("commute_min"):
        lines.append(f"편도 통근시간은 {d['commute_min']}이에요.")

    for c in context.get("candidates") or []:
        cd = c["display"]
        if cd.get("total"):
            line = f"{c['name']}은 월 총부담 {cd['total']}이에요."
            gap = c.get("delta_total_won")
            if gap:
                # 부호를 말로 푼다. "-20.6만원 차이"는 읽는 사람이
                # 어느 쪽이 싼지 한 번 더 생각해야 한다.
                line += (f" 현재보다 {_man(abs(gap))}만원 "
                         + ("적어요." if gap > 0 else "많아요."))
            lines.append(line)

    notice = (context.get("reliability") or {}).get("notice")
    if notice:
        lines.append(notice)

    lines.append("자세한 설명은 지금 드리기 어려워 화면의 값을 그대로 "
                 "정리해 드렸어요.")
    return " ".join(lines)


# ─────────────────────────────────────────────────────────────
# 숫자 검증 게이트
# ─────────────────────────────────────────────────────────────

# 답변에서 숫자를 뽑는다. 천단위 콤마와 소수점을 함께 받는다.
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# 목록 번호와 순위는 값에 대한 주장이 아니다.
#   "1) 청림동, 2) 신대방1동", "총부담 2위"
# 평가에서 두 번 연속으로 이것 때문에 막혔는데, 두 번 다 답변의 금액은
# 전부 맞았다. 정작 위험했던 것(다른 동네 값을 붙이거나 없는 동네를
# 지어내는 것)은 숫자 게이트로 잡히지 않는 종류였다.
# 서수를 계속 막으면 게이트가 엉뚱한 곳에서만 울린다.
_ORDINAL_RE = re.compile(r"^[)\.·]|^\s*(위|번째|번)\b|^(위|번째|번)")


def _walk_numbers(node, out):
    if isinstance(node, dict):
        for v in node.values():
            _walk_numbers(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _walk_numbers(v, out)
    elif isinstance(node, bool):
        pass                      # True/False 를 1/0 으로 세지 않는다
    elif isinstance(node, (int, float)):
        out.append(float(node))
    elif isinstance(node, str):
        for m in _NUM_RE.finditer(node):
            try:
                out.append(float(m.group().replace(",", "")))
            except ValueError:
                pass


def collect_numbers(context):
    """답변에 나와도 되는 숫자 집합.

    컨텍스트 값 자체와, 화면이 실제로 쓰는 표기 변환만 허용한다.
    변환 범위를 넓히면 게이트가 헐거워지므로 여기 없는 변환은 통과시키지 않는다.
      - 원 단위 그대로            779000
      - 만원 소수 첫째자리        77.9
      - 만원 정수 반올림          78
      - 비율 -> 퍼센트            0.699 -> 69.9 / 70
    뺄셈·덧셈 결과는 넣지 않는다. 절감액처럼 화면에 뜨는 차이값은
    서버가 미리 계산해 컨텍스트에 담아야 한다(delta_total_won).
    """
    raw = []
    _walk_numbers(context, raw)

    allowed = set()
    for v in raw:
        allowed.add(round(v, 2))
        allowed.add(round(v))
        if abs(v) >= 1000:                       # 원 단위로 보이는 값
            allowed.add(round(v / 10_000, 1))
            allowed.add(round(v / 10_000))
        if 0 < abs(v) <= 1:                      # 비율
            allowed.add(round(v * 100, 1))
            allowed.add(round(v * 100))
        allowed.add(round(v, 1))
    return allowed


def verify_numbers(answer, context, tolerance=0.05):
    """답변의 숫자가 전부 허용 집합 안에 있는지 본다.

    돌려주는 것: (통과여부, 걸린 숫자 목록)
    걸린 숫자를 함께 주는 이유는, 평가에서 "무엇을 지어냈는가"를 봐야
    프롬프트가 아니라 컨텍스트를 고쳐야 할 때를 알 수 있기 때문이다.
    """
    allowed = collect_numbers(context)
    text_all = answer or ""
    bad = []
    for m in _NUM_RE.finditer(text_all):
        text = m.group()
        try:
            v = float(text.replace(",", ""))
        except ValueError:
            continue
        if any(abs(v - a) <= tolerance for a in allowed):
            continue
        # 목록 번호·순위는 건너뛴다. 한 자리 정수이면서 뒤에 ")" 나
        # "위" 같은 표식이 붙은 경우만이라 값 주장과 헷갈리지 않는다.
        if v < 10 and float(v).is_integer():
            if _ORDINAL_RE.match(text_all[m.end():m.end() + 4]):
                continue
        bad.append(text)
    return (not bad), bad
