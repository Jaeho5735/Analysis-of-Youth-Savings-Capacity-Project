"""문서 검색과 컨텍스트 결합 테스트. 인덱스 파일 없이 돈다."""

import pytest

from tests.eval.golden_set import demo_context
from web.chat_context import attach_docs, needs_docs
from web.chat_llm import build_messages
from web.doc_chunks import split_markdown
from web.doc_search import DocSearch, tokenize

SAMPLE = """\ufeff# 보증금 월환산 근거

## 문제

보증금과 월세는 단위가 다르다. 그대로 더할 수 없는데 한 숫자로 보여주려면
합쳐야 한다. 그래서 전월세전환율로 보증금을 월 단위로 바꾼다.

## 적용 전환율

| 권역 | 전환율 |
|---|---|
| 동남권 | 5.39% |
| 서남권 | 5.90% |
"""


# ── 청킹 ─────────────────────────────────────────────

def test_bom_does_not_swallow_the_title():
    """윈도우 편집기가 붙인 BOM 때문에 첫 줄이 헤딩으로 인식되지 않아
    문서 제목이 통째로 사라진 적이 있다. 에러는 나지 않는다."""
    chunks = split_markdown(SAMPLE, "보증금")
    assert all("보증금 월환산 근거" in c["path"] for c in chunks)


def test_heading_path_is_prefixed_to_body():
    """조각 하나만 봐도 무슨 문서의 어느 절인지 알 수 있어야 한다."""
    c = split_markdown(SAMPLE, "보증금")[0]
    assert c["text"].startswith("[보증금 월환산 근거")


def test_table_is_not_split():
    joined = "\n".join(c["text"] for c in split_markdown(SAMPLE, "보증금"))
    assert "| 동남권 | 5.39% |" in joined


# ── 검색 ─────────────────────────────────────────────

@pytest.fixture
def index():
    return DocSearch(split_markdown(SAMPLE, "보증금"))


def test_question_words_are_stripped():
    """'어떻게' 같은 말은 문서에 드물어 IDF 가 높게 잡히는데 의미는 없다.
    이것 때문에 관련 없는 문서가 1위로 올라온 적이 있다."""
    assert "어떻" not in tokenize("어떻게 계산해요?", is_query=True)
    assert "어떻" in tokenize("어떻게 계산해요?")      # 문서 쪽은 그대로


def test_relevant_question_hits(index):
    # 표본이 세 조각뿐이라 IDF 가 작다. 임계값은 실제 인덱스 기준이므로
    # 여기서는 낮춰서 순위만 본다.
    hits = index.search("보증금을 왜 월세로 환산했나요?", min_score=0)
    assert hits and "보증금" in hits[0]["text"]


def test_unrelated_question_returns_nothing(index):
    """근거가 없는데 뭔가를 돌려주는 검색기는 환각의 재료를 만든다.
    모델은 엉뚱한 문서를 성실히 요약하고 숫자 게이트는 통과시킨다."""
    assert index.search("오늘 점심 뭐 먹지?") == []
    assert index.search("날씨 알려줘") == []


def test_single_token_coincidence_is_not_relevance(index):
    """'오늘' 하나가 맞아 문서가 걸린 적이 있다."""
    assert index.search("단위", min_hits=2) == []


# ── 컨텍스트 결합 ────────────────────────────────────

def test_docs_attach_only_for_method_questions(index):
    # 표본 문서가 세 조각뿐이라 IDF 가 작다. 임계값은 실제 인덱스 기준이므로
    # 여기서는 낮춰서 "붙는가 안 붙는가"만 본다.
    ctx = attach_docs(demo_context(6), "보증금을 왜 월세로 환산했나요?",
                      index, min_score=0)
    assert ctx["docs"]

    ctx = attach_docs(demo_context(6), "세 후보 중 총부담이 가장 낮은 곳은?",
                      index, min_score=0)
    assert ctx["docs"] == []       # 단서가 없어 검색 자체를 하지 않는다


def test_needs_docs_cue():
    assert needs_docs("이 값은 어떤 기준으로 정했나요?")
    assert not needs_docs("환승 없는 후보만 보여줘")


def test_doc_numbers_join_the_allowed_set(index):
    """문서의 5.39% 가 허용 숫자에 없으면, 모델이 문서를 정확히 인용해도
    숫자 게이트가 차단한다. ①에서 원 단위 값으로 겪은 함정과 같다."""
    from web.chat_context import verify_numbers
    ctx = attach_docs(demo_context(6), "전월세전환율은 어떤 기준이에요?",
                      index, min_score=0)
    assert verify_numbers("동남권은 5.39%를 적용해요.", ctx)[0]


def test_docs_are_rendered_readably_not_as_json(index):
    """줄글을 JSON 문자열로 밀어 넣으면 줄바꿈이 escape 되어 작은 모델이
    표를 못 읽는다. 이 문서들은 표에 결론이 들어 있다."""
    ctx = attach_docs(demo_context(6), "전월세전환율은 어떤 기준이에요?",
                      index, min_score=0)
    msg = build_messages(ctx, "전월세전환율은 어떤 기준이에요?")[0]["content"]
    assert "# 문서 근거" in msg
    assert "| 동남권 | 5.39% |" in msg


def test_missing_docs_are_announced(index):
    """문서를 못 찾았다는 사실 자체를 프롬프트에 실어야 모델이 거절한다."""
    ctx = attach_docs(demo_context(6), "혼잡도는 어떤 방법으로 쟀나요?", index)
    msg = build_messages(ctx, "혼잡도는 어떤 방법으로 쟀나요?")[0]["content"]
    assert ctx["docs"] == []
    assert "(없음)" in msg


def test_search_failure_does_not_break_the_context():
    """인덱스가 없거나 검색이 터져도 계산 설명은 계속돼야 한다."""
    class Broken:
        def search(self, *a, **k):
            raise RuntimeError("index broken")
    ctx = attach_docs(demo_context(6), "왜 이렇게 계산했나요?", Broken())
    assert ctx["docs"] == []


# ── 인용 판정 ────────────────────────────────────────

def test_doc_id_counts_as_a_valid_citation(index):
    """문서 조각은 프롬프트에 "[보증금#01]" 형태로 실린다. 모델이 그 id 를
    근거로 드는 것은 정확한 인용이다. 경로 문법이 아니라는 이유로
    "없는 경로"로 세면, 문서를 제대로 쓴 답변이 감점된다."""
    from web.chat_eval import resolve_path
    ctx = attach_docs(demo_context(3), "보증금을 왜 월세로 환산했나요?",
                      index, min_score=0)
    did = ctx["docs"][0]["id"]
    assert resolve_path(ctx, did)["id"] == did
    assert resolve_path(ctx, f"docs.{did}")["id"] == did


def test_citation_ignores_unit_spacing():
    """display 에 단위가 붙어 있어("79.5만원") 답변이 "79.5만 원"처럼
    띄어 쓰면 글자 비교로는 틀린다. 값이 쓰였는지만 본다."""
    from web.chat_eval import grade
    item = {"id": "t", "must_refuse": False,
            "must_cite": ["home.display.total"]}
    ctx = demo_context(6)
    for ans in ["총부담은 97.4만원이에요.", "총부담은 97.4만 원이에요."]:
        assert grade(item, ctx, {"answer": ans, "cited": []})["axes"]["citation"]


def test_bracketed_and_indexed_paths_resolve(index):
    """모델이 쓰는 표기가 제각각이다. 가리키는 값이 같으면 인정한다.
    실제 평가에서 인용 실패 15건 중 11건이 표기 문제였고 값은 맞았다."""
    from web.chat_eval import resolve_path
    ctx = attach_docs(demo_context(6), "보증금을 왜 월세로 환산했나요?",
                      index, min_score=0)
    did = ctx["docs"][0]["id"]
    for path in (f"[{did}]", "candidates[0].display.housing",
                 "home.candidates.0.display", "home.recommend_rule"):
        resolve_path(ctx, path)


def test_wrong_paths_are_still_wrong(index):
    """표기를 봐준다고 아무거나 통과시키지는 않는다.
    문서 안에 적힌 파일명이나 함수명은 컨텍스트 경로가 아니다."""
    import pytest as _pytest
    from web.chat_eval import resolve_path
    ctx = attach_docs(demo_context(6), "보증금을 왜 월세로 환산했나요?",
                      index, min_score=0)
    for path in ("docs/행정동_신뢰도.csv", "status_note()",
                 "home.display.totall"):
        with _pytest.raises((KeyError, IndexError, ValueError)):
            resolve_path(ctx, path)
