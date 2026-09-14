"""골든셋 자체를 검증한다. LLM 을 부르지 않으므로 항상 돈다.

왜 이런 테스트가 필요한가
-------------------------
골든셋이 틀리면 채점기는 아무것도 채점하지 않으면서 전부 통과시킨다.
must_cite 에 오타난 경로("home.display.totall")를 적어두면, 그 문항은
영원히 "근거를 잘 인용했다"고 판정된다. 채점기를 채점하는 자리다.

3단계에서 얻은 교훈과 같은 종류다 — 값 검사만으로는 "다 같이 무시하는"
경우를 못 잡는다. 그래서 골든셋의 경로가 실제 컨텍스트에 있는지를 본다.
"""

import ast

import pytest

from web.chat_context import CANNOT_DO, REQUIRED_CALC_KEYS
from web.chat_eval import resolve_path

from tests.eval.golden_set import (GOLDEN_SET, SCREEN_CHIPS,
                                   demo_context)

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
    """3·4·5·6 네 페이지 모두 _calc 를 남겨야 한다."""
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
# 2. 골든셋 검사
# ─────────────────────────────────────────────────────────────

def test_golden_set_size_and_unique_ids():
    # 계산 21문항 + 방법론(RAG) 4문항
    assert len(GOLDEN_SET) == 25
    ids = [q["id"] for q in GOLDEN_SET]
    assert len(set(ids)) == len(ids)


def test_refusal_items_are_a_meaningful_share():
    """거절을 못 하는 것이 답을 못 하는 것보다 위험하다.

    개수를 고정하는 이유는, 문항을 늘리다가 답하기 쉬운 것만 남으면
    점수는 오르는데 실제 위험은 그대로이기 때문이다.
    """
    refuse = [q for q in GOLDEN_SET if q["must_refuse"]]
    assert len(refuse) == 7


def test_every_screen_chip_is_measured():
    """화면이 묻는 질문은 전부 골든셋에 있어야 한다.

    칩 문구를 바꿨을 때 골든셋이 따라오지 않으면 "화면이 묻는데 아무도
    측정하지 않는 질문"이 생긴다. 실제로 답할 근거가 없는 칩 5개를
    화면에서 뺐는데 골든셋은 그대로였다.
    """
    asked = {q["question"] for q in GOLDEN_SET}
    missing = [c for c in SCREEN_CHIPS if c not in asked]
    assert not missing, f"측정되지 않는 화면 칩: {missing}"


def test_chip_origin_matches_the_screen():
    """origin='칩'은 지금 화면에 있는 것만이어야 한다.
    화면에서 뺀 질문을 칩으로 남겨 두면 "화면이 답 못 할 질문을 권한다"는
    지적이 사실과 달라진다."""
    for q in GOLDEN_SET:
        if q.get("chip_dynamic"):
            # _refresh_chips() 가 지역명을 갈아끼우는 칩. 문구가 고정돼
            # 있지 않아 글자 대조에서 뺀다.
            assert q["origin"] == "칩"
            continue
        on_screen = q["question"] in SCREEN_CHIPS
        assert (q["origin"] == "칩") == on_screen, (
            f"{q['id']}: origin={q['origin']} 인데 화면에 "
            f"{'있음' if on_screen else '없음'}")


def test_no_chip_asks_what_cannot_be_answered():
    """화면이 권하는 질문은 답할 수 있어야 한다.

    예전에는 칩 5개(혼잡도 2건·인기도·정렬 2건)가 답할 근거 없는 질문이었다.
    골든셋에서 거절 문항으로 잡아 두긴 했지만, 거절은 사용자가 물었을 때
    하는 것이지 화면이 먼저 권할 일이 아니다. 지금은 전부 뺐다.
    """
    bad = [q["id"] for q in GOLDEN_SET
           if q["origin"] == "칩" and q["must_refuse"]]
    assert not bad, f"화면이 권하는데 거절해야 하는 질문: {bad}"


def test_refusal_items_are_still_measured():
    """칩에서 뺐다고 거절 능력을 안 재는 것은 아니다.
    사용자가 직접 물어볼 수 있으므로 문항은 남겨 둔다."""
    kept = {q["question"] for q in GOLDEN_SET if q["must_refuse"]}
    assert "어느 구간이 가장 혼잡해요?" in kept
    assert "통근시간이 짧은 후보를 우선해서 보고 싶어요" in kept


def test_rag_items_declare_doc_expectation():
    """방법론 문항은 문서가 붙어야 하는지를 반드시 밝혀야 한다.
    안 밝히면 검색 실패와 모델 실패를 구분할 수 없다."""
    rag = [q for q in GOLDEN_SET if q["id"].startswith("rag-")]
    assert len(rag) == 4
    assert all("expect_docs" in q for q in rag)
    # 문서를 못 찾았을 때 거절하는지 보는 문항이 반드시 있어야 한다.
    assert any(q["expect_docs"] is False and q["must_refuse"] for q in rag)


@pytest.mark.parametrize("item", GOLDEN_SET, ids=lambda q: q["id"])
def test_cite_paths_exist_in_context(item):
    """must_cite 의 경로가 실제 컨텍스트에 있고 값이 비어 있지 않아야 한다."""
    ctx = demo_context(item["page"])
    for path in item.get("must_cite", []):
        value = resolve_path(ctx, path)      # 없으면 KeyError 로 실패
        assert value is not None, f"{item['id']}: {path} 값이 비어 있음"


@pytest.mark.parametrize("item", [q for q in GOLDEN_SET if q["must_refuse"]],
                         ids=lambda q: q["id"])
def test_refusal_reason_is_available_in_context(item):
    """거절하라고 해놓고 근거를 안 주면 챗봇은 사유 없이 거절하거나 지어낸다.

    질문을 함께 넘긴다. 검색기가 없어도 방법론 질문이면 doc_not_found 가
    붙으므로, 인덱스 파일 없이 계약을 검증할 수 있다.
    """
    ctx = demo_context(item["page"], question=item["question"])
    available = ({u["field"] for u in ctx["unknown"]}
                 | {c["field"] for c in ctx["cannot_do"]})
    # 사유가 여러 개일 수 있다. 하나라도 컨텍스트에 있으면 된다.
    want = item["unknown_field"]
    want = [want] if isinstance(want, str) else list(want)
    assert any(w in available for w in want), (
        f"{item['id']}: {want} 중 어느 것도 컨텍스트에 없음")


def test_cannot_do_is_single_sourced():
    """권한 한계는 chat_context 한 곳에서만 정의한다."""
    assert {f for f, _ in CANNOT_DO} >= {"sort_request"}


@pytest.mark.parametrize("item", GOLDEN_SET, ids=lambda q: q["id"])
def test_item_shape(item):
    assert item["question"].strip()
    assert item["origin"] in ("칩", "추가")
    assert isinstance(item["must_refuse"], bool)
    if item["must_refuse"]:
        assert item.get("unknown_field"), "거절 문항은 사유 필드가 있어야 한다"
        assert not item.get("must_cite"), "거절 문항은 근거를 대지 않는다"
