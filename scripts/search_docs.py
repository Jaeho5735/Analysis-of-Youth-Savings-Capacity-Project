"""인덱스에 무엇이 들어 있고 어떤 질문에 무엇이 걸리는지 확인한다.

    python scripts/search_docs.py "교통비가 왜 지역마다 똑같아요?"
    python scripts/search_docs.py --check          # 점검용 질문 한 벌 실행
    python scripts/search_docs.py --list           # 색인된 문서와 조각 수
    python scripts/search_docs.py "..." --show     # 조각 본문까지

챗봇 답변이 이상할 때 검색이 문제인지 모델이 문제인지 먼저 갈라야 한다.
그러려면 검색만 따로 눈으로 볼 수 있어야 한다.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.doc_search import DocSearch        # noqa: E402

# 점검용 질문. 앞의 여섯은 문서에 근거가 있어야 하고,
# 뒤의 셋은 없어야 한다. 있어야 할 것이 나오는지보다
# 없어야 할 것이 안 나오는지가 더 중요하다.
CHECK = [
    ("보증금을 왜 월세로 환산했나요?", True),
    ("결측 동은 어떻게 처리했나요?", True),
    ("교통비가 왜 지역마다 똑같아요?", True),
    ("z-score를 왜 바꿨어요?", True),
    ("어떤 모델을 안 쓰기로 했나요?", True),
    ("동명이인 문제는 어떻게 해결했나요?", True),
    ("혼잡도는 어떻게 계산했나요?", False),
    ("오늘 점심 뭐 먹지?", False),
    ("날씨 알려줘", False),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*", help="검색할 질문")
    ap.add_argument("--index", default="data/doc_index.json")
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--show", action="store_true", help="조각 본문도 출력")
    ap.add_argument("--check", action="store_true", help="점검용 질문 실행")
    ap.add_argument("--list", action="store_true", help="색인 내용 요약")
    args = ap.parse_args()

    path = ROOT / args.index
    if not path.exists():
        print(f"인덱스가 없습니다: {args.index}\n"
              f"먼저 python scripts/build_doc_index.py 를 실행하세요.")
        return 1
    idx = DocSearch.load(path)

    if args.list:
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = Counter(c["doc"] for c in data["chunks"])
        print(f"문서 {len(counts)}편 / 조각 {len(data['chunks'])}개\n")
        for doc, n in sorted(counts.items()):
            print(f"  {n:3}조각  {doc}")
        return 0

    if args.check:
        bad = 0
        for q, should_hit in CHECK:
            hits = idx.search(q, k=1)
            ok = bool(hits) == should_hit
            bad += 0 if ok else 1
            mark = "OK  " if ok else "문제"
            top = (f"{hits[0]['score']:6.2f} {hits[0]['path'][:50]}"
                   if hits else "(근거 없음)")
            print(f"[{mark}] {q:28} {top}")
        print(f"\n{len(CHECK) - bad}/{len(CHECK)} 기대대로")
        # 근거가 없어야 하는 질문에 무언가 걸리는 것이 더 위험하다.
        # 챗봇이 엉뚱한 문서를 성실하게 요약하고, 숫자 게이트는 통과시킨다.
        return 0 if bad == 0 else 2

    if not args.query:
        ap.print_help()
        return 1

    q = " ".join(args.query)
    hits = idx.search(q, k=args.k)
    print(f"Q. {q}\n")
    if not hits:
        print("  (근거 없음) — 이 질문은 문서로 답할 수 없습니다.")
        return 0
    for c in hits:
        print(f"  {c['score']:6.2f}  {c['id']}")
        print(f"          {c['path']}")
        print(f"          맞은 조각: {', '.join(c['hits'])}")
        if args.show:
            body = c["text"].split("\n", 1)[-1].strip()
            print("          " + body[:400].replace("\n", "\n          "))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
