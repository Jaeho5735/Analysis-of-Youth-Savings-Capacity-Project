"""답변 평가 골든셋 20문항.

고르는 기준
-----------
20문항 중 12문항이 **화면에 실제로 박혀 있는 질문 칩**이다. 억지로 만든
평가 문항이 아니라, 사용자가 실제로 누르게 되는 버튼을 그대로 옮겼다.
그래서 여기서 실패하는 문항은 곧 화면의 결함이다.

거절 문항이 6개인 이유
---------------------
그중 3개(혼잡도·정렬 요청·인기도)는 **화면에 있는 칩인데 답할 근거가 없는**
것들이다. 챗봇을 붙이면 이 칩들이 가장 먼저 환각을 만든다.
"모른다고 말하는 것"은 답을 잘하는 것보다 중요하고, 그래서 배점이 같다.

필드
----
  page          : 어느 화면에서 물어보는가
  question      : 사용자가 누르는 문장 그대로
  origin        : "칩" 이면 실제 화면에 있는 것, "추가" 면 평가용으로 보탠 것
  must_refuse   : 거절해야 하는가
  unknown_field : 거절 시 어느 사유를 들어야 하는가 (context.unknown 의 field)
  must_cite     : 답변 문장에 반드시 나와야 하는 컨텍스트 경로
  must_mention  : 반드시 짚어야 하는 표현
  forbid        : 나오면 안 되는 표현
"""

GOLDEN_SET = [
    # ── 3페이지 · 현재 부담 진단 ────────────────────────────
    {
        "id": "p3-01", "page": 3, "origin": "칩",
        "question": "지금 제 부담에서 가장 큰 항목은 뭐예요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": ["home.display.housing", "home.display.total"],
        "must_mention": ["주거비"],
    },
    {
        "id": "p3-02", "page": 3, "origin": "칩",
        "question": "통근시간 가치는 실제로 내는 돈인가요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": ["home.display.time_value"],
        # 이 질문은 발표 Q&A 에서도 나왔던 것이다. 실지출이 아니라는 점을
        # 빼면 사용자는 시간가치를 청구서로 읽는다.
        "must_mention": ["실제로 내는 돈은 아니"],
        "forbid": ["지출", "청구"],
    },
    {
        "id": "p3-03", "page": 3, "origin": "추가",
        "question": "어느 구간이 가장 혼잡해요?",
        "kind": "refuse", "must_refuse": True, "unknown_field": "congestion",
    },
    {
        "id": "p3-04", "page": 3, "origin": "추가",
        "question": "계산해보면 교통비가 더 나올 것 같은데 왜 이 금액이에요?",
        "kind": "explain", "must_refuse": False,
        # fare 와 fare_actual 을 둘 다 실어 보낸 이유가 이 문항이다.
        "must_cite": ["home.display.fare", "home.display.fare_actual"],
        "must_mention": ["정기권"],
    },
    {
        "id": "p3-05", "page": 3, "origin": "추가",
        "question": "이 동네 값은 믿을 만해요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": [], "must_mention": [],
        # 화면이 status_note 로 띄우는 라벨과 챗봇이 다른 말을 하면 안 된다.
        "check_reliability_consistent": True,
    },

    # ── 4페이지 · 대안 탐색 ─────────────────────────────────
    {
        "id": "p4-01", "page": 4, "origin": "칩",
        "question": "이 세 지역은 어떤 기준으로 추천하나요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": [], "must_mention": ["통근"],
        "forbid": ["인기", "많이 찾"],
    },
    {
        "id": "p4-02", "page": 4, "origin": "추가",
        "question": "통근시간이 짧은 후보를 우선해서 보고 싶어요",
        # 질문이 아니라 화면 조작 요청이다. 챗봇은 정렬을 바꿀 수 없다.
        "kind": "refuse", "must_refuse": True, "unknown_field": "sort_request",
    },
    {
        "id": "p4-03", "page": 4, "origin": "추가",
        "question": "이 지역은 왜 많이 찾는 후보예요?",
        # 조회수·선호도 자료가 없다. 숫자가 없어 게이트로는 못 잡는 환각.
        "kind": "refuse", "must_refuse": True, "unknown_field": "popularity",
    },

    # ── 5페이지 · 후보 비교 ─────────────────────────────────
    {
        "id": "p5-01", "page": 5, "origin": "칩",
        "question": "이 지역은 왜 월세 착시예요?",
        # 화면 칩이지만 _refresh_chips() 가 지역명을 바꿔 넣으므로
        # SCREEN_CHIPS 와 글자 그대로 맞지 않는다.
        "chip_dynamic": True,
        "kind": "explain", "must_refuse": False,
        "must_cite": ["candidates.0.display.housing",
                      "candidates.0.display.total", "home.display.total"],
        "must_mention": ["통근"],
    },
    {
        "id": "p5-02", "page": 5, "origin": "칩",
        "question": "현재 집이랑 후보 주거비를 그대로 비교해도 되나요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": [],
        # 현재는 실제 계약 금액, 후보는 동네 중앙값이다. 이걸 안 밝히면
        # 사용자는 같은 기준의 두 값으로 읽는다.
        "must_mention": ["중앙값"],
    },
    {
        "id": "p5-03", "page": 5, "origin": "추가",
        "question": "여기로 이사하면 매달 얼마나 저축할 수 있어요?",
        "kind": "refuse", "must_refuse": True, "unknown_field": "savings",
    },
    {
        "id": "p5-04", "page": 5, "origin": "추가",
        "question": "후보동은 통근시간이 왜 이렇게 길어요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": ["candidates.0.display.commute_min",
                      "home.display.commute_min"],
    },

    # ── 6페이지 · 상세 비교 ─────────────────────────────────
    {
        "id": "p6-01", "page": 6, "origin": "칩",
        "question": "세 후보 중 총부담이 가장 낮은 곳은 어디에요?",
        "kind": "compare", "must_refuse": False,
        "must_cite": ["candidates.0.display.total"],
    },
    {
        "id": "p6-02", "page": 6, "origin": "칩",
        "question": "환승 없는 후보만 자세히 설명해줘",
        "kind": "compare", "must_refuse": False,
        "must_cite": [],
    },
    {
        "id": "p6-03", "page": 6, "origin": "추가",
        "question": "혼잡까지 고려하면 어디가 괜찮아요?",
        "kind": "refuse", "must_refuse": True, "unknown_field": "congestion",
    },
    {
        "id": "p6-04", "page": 6, "origin": "칩",
        "question": "제가 확인해볼 수 있는 지원은 뭐가 있어요?",
        "kind": "policy", "must_refuse": False,
        "must_cite": [],
        # 소득 칸이 없어 소득 요건은 늘 미확인이다. 이걸 빼고 안내하면
        # "받을 수 있다"고 단정하는 꼴이 된다.
        "must_mention": ["소득"],
        "forbid": ["받으실 수 있습니다", "지원 대상입니다"],
    },
    {
        "id": "p6-05", "page": 6, "origin": "칩",
        "question": "왜 그렇게 판단했어?",
        "kind": "explain", "must_refuse": False,
        "must_cite": ["candidates.0.display.delta_total"],
    },

    # ── 공통 · 방법론 근거 ──────────────────────────────────
    {
        "id": "cm-01", "page": 3, "origin": "추가",
        "question": "보증금이 왜 월 얼마로 환산돼요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": [], "must_mention": ["전환율"],
    },
    {
        "id": "cm-02", "page": 3, "origin": "추가",
        "question": "시간가치 기준 금액은 어디서 나온 숫자예요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": ["params.time_value_per_hour"],
        "must_mention": ["최저임금"],
        # 2026년 최저임금이다. dim_time_value.source_note 가 "2025년"으로
        # 잘못 적혀 있던 것을 3단계에서 정정했다. 같은 오류를 챗봇이
        # 되살리지 않는지 본다.
        "forbid": ["2025년 최저임금"],
    },
    {
        "id": "cm-03", "page": 3, "origin": "추가",
        "question": "판교로 이사하면 어떨까요?",
        "kind": "refuse", "must_refuse": True, "unknown_field": "scope",
    },

    {
        "id": "p4-04", "page": 4, "origin": "칩",
        "question": "총부담은 어떻게 계산한 값이에요?",
        "kind": "explain", "must_refuse": False,
        "must_cite": ["home.display.total"], "must_mention": ["주거비"],
    },

    # ── 방법론 (문서 검색이 필요한 문항) ────────────────────
    # expect_docs 로 "문서가 붙었는가"를 따로 채점한다. 답변이 나쁠 때
    # 검색이 못 찾은 것인지 모델이 못 쓴 것인지 구분해야 고칠 데를 안다.
    {
        "id": "rag-01", "page": 3, "origin": "칩",
        "question": "보증금은 왜 월세로 환산하나요?",
        "kind": "doc", "must_refuse": False, "expect_docs": True,
        "must_cite": [], "must_mention": ["전환율"],
    },
    {
        "id": "rag-02", "page": 4, "origin": "칩",
        "question": "표본이 적은 동은 어떻게 표시하나요?",
        "kind": "doc", "must_refuse": False, "expect_docs": True,
        "must_cite": [], "must_mention": ["표본"],
    },
    {
        "id": "rag-03", "page": 6, "origin": "칩",
        "question": "교통비가 왜 지역마다 똑같아요?",
        "kind": "doc", "must_refuse": False, "expect_docs": True,
        "must_cite": [], "must_mention": ["정기권"],
    },
    # ②의 관문. 문서를 못 찾았을 때 이유를 지어내지 않아야 한다.
    # 숫자가 없는 환각이라 숫자 게이트로는 잡히지 않는다.
    {
        "id": "rag-04", "page": 3, "origin": "추가",
        # 문구를 고르는 데도 근거가 필요하다. 검색 골든셋(d-17)에서
        # "근거 없음"이 확인된 문구를 그대로 쓴다. "어떤 방법으로 쟀나요?"는
        # "방법"이 엉뚱한 문서에 걸려 문서가 2건 붙었다.
        "question": "혼잡도는 어떻게 계산했나요?",
        "kind": "refuse", "must_refuse": True, "expect_docs": False,
        # 둘 다 맞는 사유다. 혼잡도 자료가 없다는 것도, 그에 대한 방법론
        # 문서가 없다는 것도 사실이다. 하나만 정답으로 두면 옳은 거절이
        # 감점된다(실제로 모델이 "혼잡도"라고 답해 실패 처리됐다).
        "unknown_field": ["doc_not_found", "congestion"],
    },
]

# 지금 화면에 실제로 떠 있는 질문 칩. loca_pageN_data.json 과 맞춰야 한다.
#
# 이걸 박아 두는 이유는, 칩 문구를 바꿨을 때 골든셋이 따라오지 않으면
# "화면이 묻는데 아무도 측정하지 않는 질문"이 생기기 때문이다. 실제로
# 답할 근거가 없는 칩 5개를 화면에서 뺐는데 골든셋은 그대로였다.
SCREEN_CHIPS = (
    "지금 제 부담에서 가장 큰 항목은 뭐예요?",
    "통근시간 가치는 실제로 내는 돈인가요?",
    "보증금은 왜 월세로 환산하나요?",
    "이 세 지역은 어떤 기준으로 추천하나요?",
    "총부담은 어떻게 계산한 값이에요?",
    "표본이 적은 동은 어떻게 표시하나요?",
    "현재 집이랑 후보 주거비를 그대로 비교해도 되나요?",
    # 5페이지 첫 칩("…은 왜 월세 착시에요?")은 _refresh_chips() 가 실행 중에
    # 지역명을 갈아끼워서 문구가 고정돼 있지 않다. 그 문항은 chip_dynamic
    # 으로 표시해 이 목록 대조에서 뺀다.
    "세 후보 중 총부담이 가장 낮은 곳은 어디에요?",
    "환승 없는 후보만 자세히 설명해줘",
    "교통비가 왜 지역마다 똑같아요?",
    "제가 확인해볼 수 있는 지원은 뭐가 있어요?",
    "왜 그렇게 판단했어?",
)


# 정렬 요청 같은 "권한이 없는 것"은 web.chat_context.CANNOT_DO 가 원천이다.
# 여기서 따로 정의하면 두 벌이 되어 한쪽만 고쳐지는 사고가 난다.


# ─────────────────────────────────────────────────────────────
# 평가용 고정 컨텍스트
#
# DB 를 타지 않는다. 여기서 보려는 것은 "DB 값이 맞는가"(이미 다른 테스트가
# 본다)가 아니라 "같은 사실을 줬을 때 모델이 지어내는가"다. 입력이 흔들리면
# 프롬프트 문제인지 데이터 문제인지 구분할 수 없게 된다.
# 실측으로 바꾸려면 demo_context 하나만 갈아끼우면 된다.
# ─────────────────────────────────────────────────────────────

FORM = {"residence": "잠원동", "workplace": "역삼역", "deposit": "1000",
        "rent": "75", "work_days": "21", "age": "29", "depart_time": "08:10"}

_HOME = {
    "housing": 795_000, "fare": 55_000, "fare_actual": 94_000,
    "time_value": 124_000, "total": 974_000,
    "work_days": 21, "commute_min": 17.2, "transit_pass_cap": 55_000,
    "home": "잠원동", "work": "역삼1동",
    "home_code": "11650540", "work_code": "11680640",
    "status": "ok", "reasons": [], "burden_type": "A 실질 저부담",
    "dong_type": "고주거비·직주근접형", "substitute_work": None,
}

_CANDS = [
    {"name": "청림동", "type": "저주거비·지역연계형",
     "housing": 503_000, "fare": 69_000, "fare_actual": 69_000,
     "time_value": 196_000, "total": 768_000, "commute_min": 27.1,
     "transfer": 1, "delta_total": 206_000, "status": "ok", "reasons": []},
    {"name": "난향동", "type": "주거절감·장거리통근형",
     "housing": 428_000, "fare": 69_000, "fare_actual": 69_000,
     "time_value": 293_000, "total": 790_000, "commute_min": 40.5,
     "transfer": 1, "delta_total": 184_000, "status": "ok", "reasons": []},
    {"name": "신대방1동", "type": "광역분산 통근형",
     "housing": 505_000, "fare": 69_000, "fare_actual": 69_000,
     "time_value": 218_000, "total": 793_000, "commute_min": 30.2,
     "transfer": 0, "delta_total": 181_000, "status": "ok", "reasons": []},
]


def demo_context(page, with_policy=False, question=None, searcher=None):
    """페이지별 대표 컨텍스트. 골든셋 경로 검증과 실제 평가가 같이 쓴다."""
    from web.chat_context import build_chat_context

    calc = dict(_HOME)
    if page == 5:
        calc["candidate"] = dict(_CANDS[0])
    elif page == 6:
        calc["candidates"] = [dict(c) for c in _CANDS]
    ctx = build_chat_context(page, calc, FORM, with_policy=with_policy)
    if question is not None:
        # searcher 가 없으면 문서는 빈 목록이 되고, 방법론 질문이면
        # doc_not_found 사유가 붙는다. 인덱스 없이도 계약을 검증할 수 있다.
        from web.chat_context import attach_docs
        attach_docs(ctx, question, searcher)
    return ctx
