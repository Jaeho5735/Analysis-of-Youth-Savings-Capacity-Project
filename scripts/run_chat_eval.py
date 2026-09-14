"""골든셋 20문항을 실제 모델로 돌려 채점하고 결과를 문서로 남긴다.

    python scripts/run_chat_eval.py
    python scripts/run_chat_eval.py --model exaone3.5:7.8b
    python scripts/run_chat_eval.py --provider anthropic --model claude-sonnet-4-6

pytest 로 돌리지 않는 이유
-------------------------
LLM 호출은 비결정적이고 문항당 20~100초가 걸린다. 이걸 250건짜리 회귀
테스트에 섞으면 매번 30분을 기다리게 되고, 실패해도 "모델이 그날 그랬다"
인지 "코드가 깨졌다"인지 구분이 안 된다. 회귀는 pytest 가 보고, 답변
품질은 여기서 측정한다.

무엇을 보는가
-------------
점수 자체보다 축별 분포가 중요하다. 축에 따라 고칠 데가 다르다.
    numbers  실패 -> 컨텍스트에 값이 없어서 지어냈다. 컨텍스트를 본다.
    citation 실패 -> 값은 있는데 안 썼다. 프롬프트를 본다.
    refusal  실패 -> 모를 것을 아는 척했다. 가장 위험하다.
    blocked  (게이트 차단) -> 거짓이 사용자에게 못 갔다는 뜻이다. 실패지만
             안전 쪽 실패다. 통과율과 따로 세어 둔다.

결과는 docs/chatbot-eval.md 에 이어붙는다. 모델을 바꿔 다시 돌리면
같은 문항으로 비교한 표가 쌓인다.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="OLLAMA_MODEL / ANTHROPIC_MODEL 로 넘긴다")
    ap.add_argument("--provider", choices=["ollama", "anthropic"],
                    help="LLM_PROVIDER")
    ap.add_argument("--limit", type=int, help="앞에서 N 문항만 (빠른 확인용)")
    ap.add_argument("--only", help="특정 문항 id 하나만. 예: p6-04")
    ap.add_argument("--out", default="docs/chatbot-eval.md")
    ap.add_argument("--raw", default="docs/chatbot-eval-raw.json",
                    help="답변 원문 저장 위치. 사람이 읽고 판단할 때 쓴다")
    args = ap.parse_args()

    # 환경변수는 모듈을 import 하기 전에 세팅해야 한다.
    # chat_llm 이 import 시점에 os.getenv 로 읽기 때문이다.
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        key = ("ANTHROPIC_MODEL"
               if os.getenv("LLM_PROVIDER", "ollama") == "anthropic"
               else "OLLAMA_MODEL")
        os.environ[key] = args.model

    from tests.eval.golden_set import GOLDEN_SET, demo_context
    from web.chat_eval import AXES, grade, summarize
    from web import chat_llm

    # 문서 검색기. 없으면 방법론 문항이 전부 doc 축에서 실패하는데,
    # 그것 자체가 "인덱스를 안 만들었다"는 신호라 조용히 넘기지 않는다.
    searcher = None
    try:
        from web.doc_search import DocSearch
        searcher = DocSearch.load(ROOT / "data" / "doc_index.json")
        print(f"문서 인덱스: 조각 {len(searcher.chunks)}개")
    except Exception as e:
        print(f"문서 인덱스 없음({type(e).__name__}). "
              f"python scripts/build_doc_index.py 로 만드세요.")

    items = list(GOLDEN_SET)
    if args.only:
        items = [q for q in items if q["id"] == args.only]
        if not items:
            print(f"그런 id 가 없습니다: {args.only}")
            return 1
    if args.limit:
        items = items[:args.limit]

    model = (chat_llm.ANTHROPIC_MODEL if chat_llm.PROVIDER == "anthropic"
             else chat_llm.OLLAMA_MODEL)
    print(f"제공자 {chat_llm.PROVIDER} / 모델 {model} / {len(items)}문항\n")

    results, rows, raw = [], [], []
    started = time.time()

    for i, item in enumerate(items, start=1):
        ctx = demo_context(item["page"], question=item["question"],
                           searcher=searcher)
        t0 = time.time()
        try:
            out = chat_llm.ask(ctx, item["question"])
        except Exception as e:                       # 스크립트가 죽지 않게
            out = {"answer": "", "cited": [], "refused": False,
                   "unknown_used": [], "source": "error",
                   "blocked_reason": f"{type(e).__name__}: {e}"}
        took = time.time() - t0

        # 반드시 모델이 실제로 한 말을 채점한다. 폴백 문장을 채점하면
        # 화면 값을 그대로 나열한 문장이라 근거 기준을 항상 만족해서,
        # 차단된 문항이 통과로 집계된다. 실제로 그렇게 새고 있었다.
        blocked = out["source"] != "llm"
        res = grade(item, ctx, {
            "answer": out.get("model_answer", out["answer"]),
            "cited": out.get("model_cited", out["cited"]),
            "refused": out.get("model_refused", out["refused"]),
            "unknown_used": out.get("model_unknown_used", out["unknown_used"]),
        })
        if blocked:
            # 게이트가 막았다는 것 자체가 그 답변이 기준 미달이라는 뜻이다.
            res["passed"] = False
        results.append(res)

        mark = "BLOCK" if blocked else ("PASS" if res["passed"] else "FAIL")
        failed = [a for a in AXES if not res["axes"][a]]
        ndoc = len(ctx.get("docs") or [])
        print(f"[{i:2}/{len(items)}] {item['id']:7} {mark:5} {took:5.1f}초"
              + (f" 문서{ndoc}" if item.get("expect_docs") is not None else "")
              + (f"  실패축: {','.join(failed)}" if failed else "")
              + (f"  ({out['blocked_reason']})" if blocked else ""))

        rows.append({
            "id": item["id"], "page": item["page"], "kind": item["kind"],
            "docs": len(ctx.get("docs") or []),
            "origin": item["origin"], "mark": mark, "took": round(took, 1),
            "failed": failed, "source": out["source"],
            "blocked_reason": out.get("blocked_reason"),
        })
        raw.append({
            "id": item["id"], "question": item["question"],
            "docs": [d["id"] for d in (ctx.get("docs") or [])],
            "answer": out.get("model_answer") or out["answer"],
            "shown_to_user": out["answer"],
            "cited": out.get("model_cited", out["cited"]),
            "refused": out["refused"], "unknown_used": out["unknown_used"],
            "source": out["source"], "blocked_reason": out.get("blocked_reason"),
            "grade": res,
        })

    total_time = time.time() - started
    summary = summarize(results)
    blocked_n = sum(1 for r in rows if r["mark"] == "BLOCK")

    print(f"\n통과 {summary['passed']}/{summary['total']} "
          f"({summary['rate']:.0%}) / 게이트 차단 {blocked_n}건 / "
          f"{total_time / 60:.1f}분")
    print("축별 통과:", ", ".join(f"{a} {summary['by_axis'][a]}"
                               for a in AXES))

    _write_report(ROOT / args.out, model, chat_llm.PROVIDER, rows, summary,
                  blocked_n, total_time)
    _write_raw(ROOT / args.raw, model, raw)
    print(f"\n기록: {args.out} / 답변 원문: {args.raw}")
    return 0


def _write_report(path, model, provider, rows, summary, blocked_n, total_time):
    """실행 결과를 표로 이어붙인다. 모델을 바꿔 돌리면 비교표가 쌓인다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"\n## {stamp} · {provider} · `{model}`\n",
        f"- 통과 **{summary['passed']}/{summary['total']}** "
        f"({summary['rate']:.0%}), 게이트 차단 {blocked_n}건, "
        f"총 {total_time / 60:.1f}분",
        "- 축별 통과: "
        + ", ".join(f"{a} {n}" for a, n in summary["by_axis"].items()),
        "",
        "| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        note = (r["blocked_reason"] or "")[:60]
        lines.append(
            f"| {r['id']} | {r['page']}p | {r['kind']} | **{r['mark']}** | "
            f"{r['took']} | {', '.join(r['failed']) or '-'} | {note} |")

    if not path.exists():
        path.write_text(
            "# 챗봇 답변 평가\n\n"
            "골든셋 20문항 실행 기록. `python scripts/run_chat_eval.py`\n\n"
            "- **PASS** 여섯 축을 모두 통과\n"
            "- **BLOCK** 게이트가 답변을 차단하고 폴백으로 대체. "
            "실패이지만 거짓이 사용자에게 가지 않았다는 뜻이다.\n"
            "- **FAIL** 답변은 나갔으나 채점 기준에 못 미침\n",
            encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _write_raw(path, model, raw):
    """답변 원문. 점수만으로는 '엉뚱한 질문에 답했다'를 알 수 없다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = []
    if path.exists():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            blob = []
    blob.append({"at": datetime.now().isoformat(timespec="seconds"),
                 "model": model, "items": raw})
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=1),
                    encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
