"""검색 골든셋을 돌려 recall 과 오탐을 잰다.

    python scripts/run_doc_eval.py
    python scripts/run_doc_eval.py -k 5
    python scripts/run_doc_eval.py --out docs/doc-search-eval.md

무엇을 보는가
------------
    recall@1 / @3   맞는 문서를 몇 위 안에 가져왔는가
    오탐            근거가 없어야 하는 질문에 무언가 걸린 횟수
    문서 공백       나와야 마땅한데 문서가 없는 질문

오탐이 0 인지가 먼저다. 근거 없는 질문에 문서가 걸리면 챗봇은 그것을
성실하게 요약하고, 답변의 숫자 게이트는 그걸 통과시킨다. 가져온 문서에
실제로 있는 숫자이기 때문이다. 못 찾는 것보다 엉뚱한 걸 찾는 게 위험하다.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.eval.doc_golden_set import DOC_GOLDEN_SET        # noqa: E402
from web.doc_search import DocSearch                        # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="data/doc_index.json")
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--out", default="docs/eval/doc-search-eval.md",
                    help="결과를 이어붙일 마크다운 경로. "
                         "docs/ 바로 아래에 두면 색인에 섞인다")
    args = ap.parse_args()

    path = ROOT / args.index
    if not path.exists():
        print(f"인덱스가 없습니다: {args.index}")
        return 1
    idx = DocSearch.load(path)

    hit1 = hit_k = need = 0
    false_hits, gaps, rows = [], [], []

    for item in DOC_GOLDEN_SET:
        hits = idx.search(item["q"], k=args.k)
        docs = [h["doc"] for h in hits]
        expect = item["expect"]

        if expect is None:
            ok = not hits
            mark = "OK" if ok else "오탐"
            if not ok:
                false_hits.append((item["id"], docs[0], hits[0]["score"]))
        elif expect == "GAP":
            # 문서가 없어서 못 찾는 것은 검색기의 실패가 아니다.
            # 다만 무언가 걸렸다면 엉뚱한 문서를 끌어온 것이므로 오탐이다.
            ok = not hits
            mark = "공백" if ok else "공백·오탐"
            gaps.append((item["id"], item["q"], item.get("note", "")))
            if not ok:
                false_hits.append((item["id"], docs[0], hits[0]["score"]))
        else:
            need += 1
            in_k = expect in docs
            at_1 = bool(docs) and docs[0] == expect
            hit1 += at_1
            hit_k += in_k
            mark = "OK" if at_1 else ("k내" if in_k else "실패")

        top = f"{hits[0]['score']:6.2f} {hits[0]['doc']}" if hits else "(없음)"
        print(f"[{mark:8}] {item['id']:5} {item['q'][:30]:32} {top}")
        rows.append((item["id"], item["q"], expect, mark, top))

    print(f"\nrecall@1 {hit1}/{need} ({hit1 / need:.0%})   "
          f"recall@{args.k} {hit_k}/{need} ({hit_k / need:.0%})")
    print(f"오탐 {len(false_hits)}건   문서 공백 {len(gaps)}건")
    for i, doc, sc in false_hits:
        print(f"  오탐: {i} -> {doc} ({sc:.2f})")
    for i, q, note in gaps:
        print(f"  공백: {i} {q}" + (f" — {note}" if note else ""))

    if args.out:
        _write(ROOT / args.out, args.k, hit1, hit_k, need,
               false_hits, gaps, rows)
        print(f"\n기록: {args.out}")
    return 0 if not false_hits else 2


def _write(path, k, hit1, hit_k, need, false_hits, gaps, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"\n## {stamp} · BM25 (2-gram)\n",
        f"- recall@1 **{hit1}/{need}** ({hit1 / need:.0%}), "
        f"recall@{k} **{hit_k}/{need}** ({hit_k / need:.0%})",
        f"- 오탐 {len(false_hits)}건 / 문서 공백 {len(gaps)}건",
        "",
        "| 문항 | 질문 | 기대 | 결과 | 1위 |",
        "|---|---|---|---|---|",
    ]
    for i, q, expect, mark, top in rows:
        exp = expect if expect else "(없어야 함)"
        lines.append(f"| {i} | {q} | {exp} | **{mark}** | {top} |")
    if gaps:
        lines += ["", "### 문서 공백", ""]
        lines += [f"- {q}" + (f" — {n}" if n else "") for _, q, n in gaps]

    if not path.exists():
        path.write_text(
            "# 문서 검색 평가\n\n"
            "`python scripts/run_doc_eval.py --out docs/doc-search-eval.md`\n\n"
            "- **OK** 기대한 문서가 1위\n"
            "- **k내** 상위 k 안에는 있으나 1위가 아님\n"
            "- **오탐** 근거가 없어야 하는 질문에 문서가 걸림\n"
            "- **공백** 답할 문서가 아직 없음 (검색기 문제가 아님)\n",
            encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
