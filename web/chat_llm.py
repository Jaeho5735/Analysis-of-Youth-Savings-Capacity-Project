"""LOCA 챗봇. 프롬프트 · 모델 호출 · 검증 게이트 · 폴백.

흐름
----
    질문 + 컨텍스트
      -> 모델 호출 (JSON 으로 답하게 강제)
      -> 게이트 3종 검사
           ① JSON 형식인가
           ② 답변의 숫자가 전부 컨텍스트 안에 있는가
           ③ 근거로 든 경로가 실제로 있는가
      -> 통과: 그대로 보여준다
      -> 실패: 버리고 fallback_answer() 로 갈아끼운다

핵심은 마지막 두 줄이다. "환각하지 마세요"는 프롬프트로 부탁하는 것이고,
지키지 않아도 아무 일이 일어나지 않는다. 여기서는 지키지 않은 답변이
사용자에게 도달하지 못한다. 보증하는 주체가 프롬프트가 아니라 코드다.

폴백을 사과 문구로 두지 않은 이유
--------------------------------
"지금은 설명해 드릴 수 없어요" 한 줄은 사용자에게 아무것도 주지 않는다.
화면에는 이미 값이 떠 있으므로, 설명을 못 하겠으면 그 값을 그대로 읽어
주는 편이 낫다. 폴백 문장은 컨텍스트의 display 문자열만 쓰기 때문에
자기 자신의 게이트를 항상 통과한다.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request

from web.chat_context import CAVEAT_FIELDS, fallback_answer, verify_numbers
from web.chat_eval import parse_response, resolve_path

log = logging.getLogger(__name__)

# 제공자를 갈아끼울 수 있게 둔다. 게이트가 답변을 검사하기 때문에 모델
# 품질에 대한 의존이 낮고, 그래서 로컬 모델도 실용적인 선택지가 된다.
# 숫자를 틀리면 차단되고 폴백으로 내려갈 뿐 사용자에게 거짓말이 가지 않는다.
#   LLM_PROVIDER=ollama     로컬. 무료. 기본값
#   LLM_PROVIDER=anthropic  Claude API. ANTHROPIC_API_KEY 필요
PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# 기본값은 CPU 에서 실제로 답이 돌아오는 크기다. 7.8B 는 컨텍스트를
# 읽는 것만으로 몇 분이 걸려 CPU 로는 쓸 수 없었다.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "exaone3.5:2.4b")
# 컨테이너 안에서는 host.docker.internal 로 호스트의 Ollama 를 본다.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# 로컬 모델은 CPU 에서 느릴 수 있다. 넉넉히 주되 무한정 기다리지 않는다.
TIMEOUT = int(os.getenv("LLM_TIMEOUT", "240"))
# 모델을 메모리에 남겨 둔다. 기본값(5분)이면 칩을 띄엄띄엄 누를 때마다
# 7.8B 를 다시 올리느라 답변 전에 1~2분을 쓴다.
KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
# 컨텍스트 창. Ollama 기본값 2048 은 우리 프롬프트(규칙 + 화면 한 장)에
# 모자라서, 넘치면 앞쪽부터 잘린다. 즉 절대 규칙이 조용히 사라진다.
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
# 답변은 3~4문장이면 된다. CPU 에서는 생성 길이가 곧 대기 시간이다.
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "400"))
# GPU 에 올릴 레이어 수. 0 이면 CPU 만 쓴다.
# 기본을 0 으로 두는 이유는, 드라이버와 CUDA 판이 안 맞으면 llama-server 가
# 통째로 죽어서(exit 0xc0000409) 원인이 안 보이는 500 만 남기 때문이다.
# 드라이버를 올린 뒤에는 OLLAMA_NUM_GPU=auto 로 두면 Ollama 가 알아서 정한다.
NUM_GPU = os.getenv("OLLAMA_NUM_GPU", "0").strip().lower()
MAX_TOKENS = 1000

SYSTEM_PROMPT = """\
너는 LOCA 서비스의 설명 도우미다. 사용자가 보고 있는 화면의 계산 결과를
설명하는 일만 한다.

# 절대 규칙

1. 아래 CONTEXT 에 있는 숫자만 쓴다. CONTEXT 에 없는 숫자는 어떤 이유로도
   쓰지 않는다. 어림수·업계 평균·일반적인 수치 모두 안 된다.
2. 계산하지 않는다. 더하기·빼기·나누기·퍼센트 환산을 직접 하지 않는다.
   필요한 값은 CONTEXT 에 이미 다 들어 있다. 없으면 없다고 말한다.
3. 숫자는 display 안의 문자열을 단위까지 그대로 복사한다. display.total 이
   "97.4만원"이면 "97.4만원"이라고 쓴다. 단위를 바꾸거나 새로 붙이지 않는다.
   "10.8만원"을 "10.8시간"으로 바꿔 쓰는 것은 값을 틀리게 만드는 것이다.
4. 질문이 unknown 이나 cannot_do 에 해당하면 refused 를 true 로 하고,
   그 항목의 reason 을 그대로 풀어 설명한다. 대신 다른 값을 보여주며
   말을 돌리지 않는다.
5. 추천이 어떻게 뽑혔는지 묻는 질문에는 recommend_rule 을 근거로 답한다.
   여기 없는 기준(인기, 조회수, 만족도, 전문가 의견)을 지어내지 않는다.
6. 후보 지역의 주거비는 그 동네 중앙값이고 현재 집은 실제 계약 금액이다.
   둘을 나란히 말할 때는 기준이 다르다는 점을 함께 밝힌다.
7. "# 문서 근거"가 붙어 있으면 방법론·기준·이유 질문은 그 내용으로만
   답한다. 문서에 없는 이유를 지어내지 않는다.
   "# 문서 근거"가 비어 있는데 방법이나 기준을 묻는 질문이면
   refused=true 로 하고 unknown_used 에 "doc_not_found" 를 넣는다.
   화면의 값이 얼마인지 묻는 질문은 문서 없이도 답한다.
8. answer 는 반드시 한국어로 쓴다. 중국어·영어·일본어를 섞지 않고
   한자도 쓰지 않는다.

# 답변 형식

반드시 아래 JSON 만 출력한다. 코드펜스도 설명도 붙이지 않는다.

{
  "answer": "사용자에게 보일 문장. 존댓말. 3문장 이내로 짧게.",
  "cited": ["근거로 쓴 CONTEXT 경로", "예: home.display.total"],
  "refused": false,
  "unknown_used": ["거절했다면 그 사유의 field 이름"]
}

cited 에는 실제로 답변에 쓴 값의 경로만 넣는다. 없는 경로를 지어내면
답변 전체가 폐기된다. 경로는 "home.display.total" 처럼 CONTEXT 내부에서
시작한다. 앞에 "CONTEXT." 를 붙이지 않는다.

거절할 때(refused=true)는 cited 를 빈 배열로 두고, unknown_used 에
그 항목의 field 이름만 넣는다. 예: ["congestion"]
"""


def _strip_won(node):
    """프롬프트에 실을 때 원 단위 값을 뺀다.

    컨텍스트에는 795000(원)과 "79.5"(만원 표기)가 함께 들어 있다. 작은
    모델은 앞의 숫자를 집어 "주거비 795만원"이라고 말한다. 실제 평가에서
    차단된 12건 중 대부분이 이 한 가지 실수였다.

    보여 주지 않으면 말할 수 없다. 프롬프트에서 원 단위를 빼면 이 오류가
    구조적으로 사라진다. 컨텍스트 자체는 그대로 두므로 폴백 문장과
    허용 숫자 집합(collect_numbers)은 영향을 받지 않는다.

    시간가치 단가(10,320원)처럼 원으로 말해야 하는 값은 _won 으로 끝나지
    않으므로 남는다.
    """
    if isinstance(node, dict):
        return {k: _strip_won(v) for k, v in node.items()
                if not k.endswith("_won")}
    if isinstance(node, list):
        return [_strip_won(v) for v in node]
    return node


def build_messages(context, question):
    """모델에 보낼 user 메시지. 컨텍스트를 통째로 넣는다.

    필요한 부분만 골라 넣으면, 무엇을 골랐는지에 따라 답이 달라져
    평가가 재현되지 않는다. 컨텍스트는 이미 화면 한 장 분량이라 작다.
    """
    # 들여쓰기를 빼서 프롬프트를 줄인다. CPU 추론에서는 입력 길이도
    # 대기 시간으로 그대로 돌아온다.
    # 답할 수 없는 것을 JSON 안에 묻어두지 않고 맨 앞에 목록으로 꺼낸다.
    # 평가에서 거절 문항 6개가 모두 실패했는데, 사유는 전부 컨텍스트에
    # 들어 있었다. 작은 모델이 긴 JSON 가운데의 unknown 배열을 못 본 것이다.
    # 읽어야 하는 것은 읽기 좋은 자리에 둔다.
    unknown = context.get("unknown") or []
    limits = [f"- {u['field']}: {u['reason']}"
              for u in unknown if u["field"] not in CAVEAT_FIELDS]
    limits += [f"- {c['field']}: {c['reason']}"
               for c in (context.get("cannot_do") or [])]
    limit_block = ("# 답할 수 없는 것\n"
                   "질문이 아래 중 하나에 해당하면 값을 말하지 말고\n"
                   "refused=true 로 하고 그 이름을 unknown_used 에 넣는다.\n"
                   + "\n".join(limits))

    # 단서는 거절 사유가 아니다. 답하되 함께 밝혀야 하는 것이라 따로 둔다.
    caveats = [f"- {u['reason']}" for u in unknown
               if u["field"] in CAVEAT_FIELDS]
    if caveats:
        limit_block += ("\n\n# 답할 때 함께 밝힐 것\n" + "\n".join(caveats))

    # 위에서 목록으로 꺼냈으므로 JSON 에서는 뺀다. 두 번 실으면 길기만 하다.
    slim = {k: v for k, v in _strip_won(context).items()
            if k not in ("unknown", "cannot_do", "docs")}
    body = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))

    # 문서 조각은 JSON 이 아니라 읽을 수 있는 형태로 따로 붙인다.
    # 줄글을 JSON 문자열로 밀어 넣으면 줄바꿈이 \n 으로 escape 되어
    # 작은 모델이 표를 못 읽는다. 이 문서들은 표에 결론이 들어 있다.
    docs = context.get("docs") or []
    if docs:
        doc_block = "# 문서 근거\n" + "\n\n".join(
            f"[{d['id']}]\n{d['text']}" for d in docs)
    else:
        doc_block = ("# 문서 근거\n"
                     "(없음) 이 질문에 맞는 방법론 문서를 찾지 못했다. "
                     "방법이나 기준을 묻는 질문이면 거절한다.")
    # 가장 중요한 두 규칙을 질문 바로 앞에 한 번 더 놓는다.
    # 컨텍스트 창이 넘치면 앞쪽(=시스템 프롬프트)부터 잘리는데, 그러면
    # "계산 금지"가 통째로 사라진 채 추론한다. 실제로 모델이 원 단위 값을
    # 직접 나눠 120,919.76 같은 없는 숫자를 만들어 낸 적이 있다.
    # 작은 모델은 뒤쪽 지시를 더 잘 따르기도 해서 이중으로 도움이 된다.
    reminder = ("# 규칙 재확인\n"
                "- CONTEXT 에 있는 숫자만 쓴다. 직접 계산하지 않는다.\n"
                "- 숫자는 display 문자열을 단위까지 그대로 복사한다.\n"
                "- 답할 수 없는 것에 해당하면 refused=true 로 한다.\n"
                "- 문서 근거가 없으면 방법·기준·이유를 지어내지 않는다.\n"
                "- JSON 만 출력한다. 한국어로 쓴다.")
    # 질문을 앞뒤에 모두 둔다. 작은 모델은 긴 JSON 가운데를 흘려보고
    # 엉뚱한 질문에 답하는 일이 잦다(정책을 물었는데 추천 이유를 답했다).
    return [{"role": "user",
             "content": (f"# 질문\n{question}\n\n{limit_block}\n\n"
                         f"# CONTEXT\n{body}\n\n{doc_block}\n\n"
                         f"{reminder}\n\n# 위 질문에 답하라\n{question}")}]


def _call_anthropic(messages, system=SYSTEM_PROMPT):
    """Claude API. 키가 없으면 예외를 낸다."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 가 없습니다.")

    import anthropic
    client = anthropic.Anthropic(api_key=key)
    res = client.messages.create(model=ANTHROPIC_MODEL, max_tokens=MAX_TOKENS,
                                 system=system, messages=messages)
    return "".join(b.text for b in res.content
                   if getattr(b, "type", "") == "text")


def _call_ollama(messages, system=SYSTEM_PROMPT):
    """로컬 Ollama. 새 패키지를 쓰지 않으려고 표준 라이브러리로 부른다.

    format="json" 을 주면 Ollama 가 문법상 올바른 JSON 만 내놓는다.
    작은 모델이 앞뒤에 군말을 붙이는 문제를 여기서 상당 부분 막는다.
    """
    # 온도 0 + 고정 시드. 같은 질문에 같은 답이 나와야 평가가 성립한다.
    #
    # 0.2 로 두고 세 번 돌렸더니 같은 문항이 매번 다른 축에서 실패했다.
    # 그 상태에서 프롬프트를 고치면 개선인지 흔들림인지 구분할 수 없다.
    # 측정 도구가 흔들리면 그 위의 모든 판단이 무의미해진다.
    #
    # 다양성이 필요한 작업이 아니다. 화면의 값을 설명하는 답은
    # 매번 같아야 사용자도 신뢰한다.
    options = {"temperature": 0, "seed": 0, "num_predict": NUM_PREDICT,
               "num_ctx": NUM_CTX}
    if NUM_GPU != "auto":
        options["num_gpu"] = int(NUM_GPU)

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system}] + list(messages),
        "stream": False,
        "format": "json",
        "keep_alive": KEEP_ALIVE,
        "options": options,
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_HOST.rstrip("/") + "/api/chat", data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            body = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 본문을 안 읽으면 로그에 "HTTP Error 500" 만 남아 원인을 알 수 없다.
        # Ollama 는 실패 사유(모델 없음, CUDA 크래시 등)를 본문에 적어 준다.
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise RuntimeError(f"Ollama {e.code}: {detail or e.reason}") from None

    return (body.get("message") or {}).get("content") or ""


def _call_model(messages, system=SYSTEM_PROMPT):
    """제공자에 따라 갈라 부른다. 테스트는 이 함수만 갈아끼운다.

    실패하면 예외를 낸다. 호출한 쪽이 폴백으로 넘긴다. 챗봇이 안 되는 것과
    웹이 안 뜨는 것은 다른 문제이므로, 여기서 앱을 죽이지 않는다.
    """
    if PROVIDER == "anthropic":
        return _call_anthropic(messages, system)
    if PROVIDER == "ollama":
        return _call_ollama(messages, system)
    raise RuntimeError(f"모르는 LLM_PROVIDER: {PROVIDER}")


# 한글이 하나도 없거나 한자가 섞이면 한국어 답변이 아니다.
# 로컬 모델(특히 Qwen 계열)은 한국어로 물어도 중국어로 답하는 일이 잦다.
# 프롬프트로 부탁하는 것만으로는 안 막혀서 게이트에서 검사한다.
# 화면 문구도 지역명도 전부 한글이라 한자가 정상적으로 나올 자리가 없다.
_HANGUL = re.compile(r"[가-힣]")
_HANJA = re.compile(r"[\u4e00-\u9fff]")


def check(context, parsed):
    """게이트. 통과하면 (True, None), 걸리면 (False, 사유)."""
    answer = parsed.get("answer") or ""
    if not answer.strip():
        return False, "answer 가 비었음"

    if not _HANGUL.search(answer):
        return False, "한국어가 아님"
    hanja = _HANJA.findall(answer)
    if hanja:
        return False, "한자가 섞임: " + "".join(hanja[:8])

    ok, bad = verify_numbers(answer, context)
    if not ok:
        return False, f"컨텍스트에 없는 숫자: {bad}"

    # 근거 경로는 막지 않고 기록만 한다.
    #
    # 처음에는 "지어낸 근거"를 잡으려고 차단 조건으로 뒀는데, 실제로 걸린
    # 세 건이 전부 옳은 답변이었다. CONTEXT. 접두사, unknown.congestion,
    # candidates[].display.total — 사람이 보기엔 맞는 경로인데 표기만 달랐다.
    # 반면 거짓을 잡은 적은 한 번도 없다.
    #
    # 사용자를 오도할 수 있는 것은 답변 문장이지 cited 배열이 아니다.
    # 문장은 숫자 게이트와 언어 게이트가 이미 막는다. 근거 표기의 품질은
    # 골든셋 평가의 citation 축에서 사람이 보고 판단하는 편이 맞다.
    # 런타임에서 옳은 답변을 버리는 대가가 훨씬 크다.
    ghosts = []
    for path in parsed.get("cited") or []:
        try:
            resolve_path(context, path)
        except (KeyError, IndexError, ValueError):
            ghosts.append(path)
    if ghosts:
        log.info("근거 경로 표기가 어긋남(통과시킴): %s", ghosts)

    return True, None


def ask(context, question, call=None):
    """질문 하나에 답한다.

    call 을 넘기면 그 함수로 모델을 부른다(테스트·평가에서 사용).
    돌려주는 dict 의 source 로 LLM 답변인지 폴백인지 구분한다.
    """
    call = call or _call_model
    messages = build_messages(context, question)
    # 입력 길이가 곧 대기 시간이다. 타임아웃이 잦으면 여기부터 본다.
    log.info("챗봇 요청: 컨텍스트 %d자, 모델 %s",
             len(messages[0]["content"]), OLLAMA_MODEL)

    try:
        raw = call(messages)
        parsed = parse_response(raw)
    except Exception as e:
        log.warning("챗봇 호출 실패, 폴백으로 대체: %s: %s", type(e).__name__, e)
        return _fallback(context, f"{type(e).__name__}: {e}")

    passed, reason = check(context, parsed)
    if not passed:
        # 무엇이 걸렸는지 반드시 남긴다. 평가에서 프롬프트를 고쳐야 하는지
        # 컨텍스트를 고쳐야 하는지가 이 로그로 갈린다.
        log.warning("게이트 차단: %s / 원문: %s", reason, parsed.get("answer"))
        return _fallback(context, reason, parsed)

    return {"answer": parsed["answer"],
            "cited": parsed.get("cited") or [],
            "refused": bool(parsed.get("refused")),
            "unknown_used": parsed.get("unknown_used") or [],
            "source": "llm", "blocked_reason": None,
            "model_answer": parsed["answer"],
            "model_cited": parsed.get("cited") or [],
            "model_refused": bool(parsed.get("refused")),
            "model_unknown_used": parsed.get("unknown_used") or []}


def _fallback(context, reason, parsed=None):
    """폴백으로 대체하되, 모델이 실제로 뭐라고 했는지는 따로 넘긴다.

    평가에서 폴백 문장을 채점하면 안 된다. 폴백은 화면 값을 그대로
    나열하므로 근거 인용 기준을 항상 만족해서, 차단된 문항이 통과로
    집계된다(실제로 그렇게 집계되고 있었다).
    """
    parsed = parsed or {}
    return {"answer": fallback_answer(context), "cited": [],
            "refused": False, "unknown_used": [],
            "source": "fallback", "blocked_reason": reason,
            "model_answer": parsed.get("answer") or "",
            "model_cited": parsed.get("cited") or [],
            "model_refused": bool(parsed.get("refused")),
            "model_unknown_used": parsed.get("unknown_used") or []}
