"""답변 채점기. 골든셋 한 문항을 규칙으로 채점한다.

왜 LLM 심판을 쓰지 않는가
-------------------------
"이 답변이 환각인가"를 다시 LLM 에게 물으면 그 판정도 환각일 수 있다.
검증으로 관통되는 프로젝트에서 검증 도구만 검증되지 않는 셈이라 앞뒤가 안 맞는다.
그래서 1차 채점은 전부 규칙이고, LLM 심판은 나중에 보조로만 붙인다.

규칙으로 채점하려면 답변이 자유 문장이면 안 된다
------------------------------------------------
"이 답변이 거절인가"를 한국어 문장에서 키워드로 알아내려 하면 오탐이 난다.
("답변드릴 수 없는 부분은 빼고 말씀드리면…" 은 거절인가 아닌가)
그래서 챗봇은 반드시 아래 형태의 JSON 으로 답한다. 이 계약이 곧 프롬프트 사양이다.

    {
      "answer":  "사용자에게 보일 문장",
      "cited":   ["home.display.total", "params.time_value_per_hour"],
      "refused": false,
      "unknown_used": ["income"]
    }

cited 를 요구하는 이유가 핵심이다. 챗봇이 "무엇을 근거로 삼았는지" 스스로
경로로 밝히게 하고, 채점기가 (1) 그 경로가 실제로 있는지 (2) 그 값이 답변
문장에 실제로 나오는지를 대조한다. 근거를 지어내면 여기서 걸린다.
"""

import json
import re

from web.chat_context import verify_numbers

# 채점 축. 하나라도 실패하면 그 문항은 실패다.
AXES = ("json", "numbers", "refusal", "citation", "mention", "forbid", "doc")


def resolve_path(context, path):
    """'candidates.0.display.total' 같은 경로로 값을 꺼낸다.

    없으면 KeyError 를 낸다. 조용히 None 을 주면 골든셋이 오타난 경로를
    가리켜도 전부 통과해버려서, 채점기가 아무것도 채점하지 않게 된다.

    모델이 쓰는 표기를 두 가지 받아 준다. 둘 다 사람이 보기엔 맞는 경로인데
    기계적으로만 틀린 것이라, 이것 때문에 옳은 답변을 버리면 손해가 크다.
      1) "CONTEXT.unknown" — 프롬프트의 "# CONTEXT" 머리말을 경로에 붙인 것
      2) "unknown.congestion" — 리스트 원소를 번호가 아니라 이름으로 부른 것.
         unknown/cannot_do 는 field 로, candidates 는 name 으로 찾는다.
    """
    # candidates[].display.total, candidates.*.display.total 처럼 자리표시자를
    # 쓰는 모델이 있다. "아무 후보나"라는 뜻이므로 첫 번째로 읽는다.
    # 대괄호 표기를 정규화한다.
    #   [보증금#01]              프롬프트에 그렇게 적혀 있어서 그대로 옮긴 것
    #   candidates[0].display    배열 색인을 대괄호로 쓴 것
    #   candidates[].display     자리표시자
    path = path.strip()
    if path.startswith("[") and path.endswith("]"):
        path = path[1:-1]
    path = re.sub(r"\[(\d+)\]", r".\1", path)
    path = path.replace("[]", ".0").replace(".*", ".0")

    # 문서 조각은 프롬프트에 "[보증금_월환산_근거#01]" 형태로 실린다.
    # id 로 부르든 헤딩 경로로 부르든 정확한 인용이다. 경로 문법이 아니라는
    # 이유로 "없는 경로"로 세면, 문서를 제대로 쓴 답변이 감점된다.
    for d in (context.get("docs") or []):
        did = d.get("id")
        if path in (did, f"docs.{did}"):
            return d
        # "SQL 분석 결과 > Q7 — 추천 전환점" 처럼 헤딩 경로로 부른 경우.
        # 조각 본문 첫 줄이 "[헤딩 경로]" 이므로 그걸로 대조한다.
        if (d.get("text") or "").startswith(f"[{path}]"):
            return d

    parts = [p for p in path.split(".") if p]
    if parts and parts[0].lower() == "context":
        parts = parts[1:]

    try:
        return _walk(context, parts, path)
    except (KeyError, IndexError, ValueError):
        # "home.candidates.0.display", "home.recommend_rule" 처럼 최상위
        # 항목을 home 아래로 넣어 부르는 일이 잦다. 현재 집과 후보가
        # 형제인 구조를 모델이 "후보는 현재 집에 딸린 것"으로 읽는 것이라,
        # 가리키려는 값 자체는 맞다. home 이 실제로 존재해서 먼저 들어가
        # 버리므로, 한 번 실패한 뒤에 벗겨서 다시 본다.
        if len(parts) > 1 and parts[0] == "home":
            return _walk(context, parts[1:], path)
        raise


def _walk(context, parts, path):
    node = context
    for part in parts:
        if isinstance(node, (list, tuple)):
            if part.isdigit():
                node = node[int(part)]
                continue
            hit = next((x for x in node if isinstance(x, dict)
                        and part in (x.get("field"), x.get("name"),
                                     x.get("id"))), None)
            if hit is None:
                raise KeyError(path)
            node = hit
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(path)
    return node


def parse_response(raw):
    """모델 출력에서 JSON 을 꺼낸다.

    형식만 봐준다. 내용 검사(숫자·근거)는 그대로 두므로 게이트가
    느슨해지지 않는다. 작은 로컬 모델은 코드펜스를 붙이거나 "네, 답변
    드릴게요:" 같은 말을 앞에 다는 일이 잦은데, 그것 때문에 멀쩡한
    답을 버리면 폴백만 계속 나온다.
    """
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 앞뒤에 군말이 붙은 경우. 바깥 중괄호 한 쌍만 떼어 본다.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def grade(item, context, raw_response):
    """골든셋 한 문항을 채점한다.

    돌려주는 것: {"passed": bool, "axes": {축: bool}, "detail": {...}}
    실패 사유를 축별로 남기는 이유는, 프롬프트를 고쳐야 하는지
    컨텍스트를 고쳐야 하는지가 축에 따라 갈리기 때문이다.
      numbers 실패  -> 컨텍스트에 값이 없어서 지어낸 것. 컨텍스트를 본다.
      citation 실패 -> 값은 있는데 안 쓴 것. 프롬프트를 본다.
    """
    axes = dict.fromkeys(AXES, True)
    detail = {}

    try:
        res = parse_response(raw_response)
    except Exception as e:
        return {"passed": False,
                "axes": {**dict.fromkeys(AXES, False), "json": False},
                "detail": {"json": f"{type(e).__name__}: {e}"}}

    answer = res.get("answer") or ""
    refused = bool(res.get("refused"))

    # ① 숫자 정합 — 컨텍스트 밖 숫자가 하나라도 있으면 실패
    ok, bad = verify_numbers(answer, context)
    axes["numbers"] = ok
    if not ok:
        detail["numbers"] = bad

    # ② 거절 정확도 — 모르는 것을 아는 척했는가, 아는 것을 모른 척했는가
    axes["refusal"] = (refused == item["must_refuse"])
    if not axes["refusal"]:
        detail["refusal"] = f"기대 {item['must_refuse']} / 실제 {refused}"

    # 거절해야 하는 문항은 근거를 대면 안 된다. 거절 사유만 밝히면 된다.
    if item["must_refuse"]:
        if refused and item.get("unknown_field"):
            # 사유가 여러 개 맞을 수 있다. "혼잡도는 어떻게 계산했나요?"는
            # congestion(자료 없음)도 doc_not_found(문서 없음)도 맞는 답이다.
            # 하나만 정답으로 두면 옳은 거절을 감점하게 된다.
            want = item["unknown_field"]
            want = [want] if isinstance(want, str) else list(want)
            got = res.get("unknown_used") or []
            axes["citation"] = any(w in got for w in want)
            if not axes["citation"]:
                detail["citation"] = (f"{' 또는 '.join(want)} 를 사유로 "
                                      f"들지 않음 (실제: {got})")
    else:
        # ③ 근거 인용 — 밝힌 경로가 실제로 있고, 그 값이 문장에 나오는가
        missing = []
        for path in item.get("must_cite", []):
            try:
                value = resolve_path(context, path)
            except KeyError:
                missing.append(f"{path}(경로 없음)")
                continue
            # 값 자체가 쓰였는지만 본다. display 문자열에는 단위가 붙어
            # 있는데("79.5만원"), 답변이 "79.5만 원"처럼 띄어 쓰면 글자
            # 비교로는 틀린다. 단위 표기는 여기서 볼 축이 아니다.
            core = re.sub(r"[^\d.]", "", str(value)) if value is not None else ""
            if not core or core not in re.sub(r"\s", "", answer):
                missing.append(f"{path}({value})")
        axes["citation"] = not missing
        if missing:
            detail["citation"] = missing

        # 답변이 인용했다고 주장한 경로가 실제로 존재하는지도 본다.
        ghosts = []
        for path in res.get("cited") or []:
            try:
                resolve_path(context, path)
            except (KeyError, IndexError, ValueError):
                ghosts.append(path)
        if ghosts:
            axes["citation"] = False
            detail.setdefault("citation", []).append(f"없는 경로 인용: {ghosts}")

    # ④ 반드시 짚어야 하는 말 (단위 기준·한계 등)
    lack = [s for s in item.get("must_mention", []) if s not in answer]
    axes["mention"] = not lack
    if lack:
        detail["mention"] = lack

    # ⑤ 문서 근거가 기대대로 붙었는가
    # 방법론 질문인데 문서가 안 붙었으면 모델이 아니라 검색이 실패한 것이다.
    # 답변 점수만 보면 둘을 구분할 수 없어서 축을 따로 둔다.
    expect_docs = item.get("expect_docs")
    if expect_docs is not None:
        got = bool(context.get("docs"))
        axes["doc"] = (got == expect_docs)
        if not axes["doc"]:
            detail["doc"] = f"기대 {expect_docs} / 실제 {got}"

    # ⑥ 하면 안 되는 말
    hit = [s for s in item.get("forbid", []) if s in answer]
    axes["forbid"] = not hit
    if hit:
        detail["forbid"] = hit

    return {"passed": all(axes.values()), "axes": axes, "detail": detail}


def summarize(results):
    """문항별 결과를 표로 요약한다. docs/chatbot-eval.md 에 붙일 형태."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    by_axis = {a: sum(1 for r in results if r["axes"][a]) for a in AXES}
    return {"total": total, "passed": passed,
            "rate": round(passed / total, 3) if total else 0.0,
            "by_axis": by_axis}
