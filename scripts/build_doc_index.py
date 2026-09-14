"""docs/ 의 방법론 문서를 검색 인덱스로 만든다.

    python scripts/build_doc_index.py
    python scripts/build_doc_index.py --stats      # 조각 분포만 보기

산출: data/doc_index.json

무엇을 넣고 무엇을 빼는가
------------------------
방법론 근거만 넣는다. 평가 기록(chatbot-eval*)과 테스트 결과는 프로젝트의
자기 기록이지 사용자 질문의 답이 아니다. 색인에 넣으면 "왜 이 필터를
썼나"라는 질문에 테스트 통과 건수가 딸려 나온다.

CSV 는 넣지 않는다. 표 자체는 이미 DB 에 있고, 문서에는 그 표를 왜 그렇게
만들었는지가 적혀 있다. 챗봇이 문서에서 얻어야 하는 것은 후자다.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.doc_chunks import split_markdown        # noqa: E402

# 자기 기록은 제외한다.
#
# 이게 왜 중요한지 실제로 겪었다. docs/doc-search-eval.md 가 색인에 들어갔는데,
# 그 파일에는 검색 골든셋 질문 20개가 표로 그대로 적혀 있다. 그래서 모든
# 평가 질문에 1위로 걸렸고 recall@1 이 93% -> 14% 로 떨어졌다.
# 평가 기록이 자기가 평가할 인덱스를 오염시킨 것이다.
#
# 접두사 목록만으로는 파일이 하나 늘 때마다 또 당한다. 이름에 "eval" 이
# 들어간 것은 전부 뺀다. 평가 산출물은 docs/eval/ 아래로 쓰는 것이 더
# 확실하다 — 이 인덱서는 docs/*.md 만 보므로 하위 폴더는 자동으로 빠진다.
EXCLUDE_PREFIXES = ("chatbot-eval", "doc-search-eval", "pytest-results")
EXCLUDE_CONTAINS = ("eval", "평가결과")

# 사본은 제외한다. 실제로 "디버깅이력_지표산출 - 복사본.md" 가 함께 색인돼
# 전체 74조각 중 24조각이 원본과 완전히 같았다. 검색 상위 3개가 원본과
# 사본으로 채워지면 챗봇이 참고할 자리를 하나 버리는 셈이다.
COPY_MARKERS = (" - 복사본", " - copy", "(1)", "_bak", "_backup", "사본")


def collect(docs_dir, include_all=False):
    paths = sorted(p for p in Path(docs_dir).glob("*.md"))
    skipped = []
    kept = []
    for p in paths:
        if not include_all and (p.name.startswith(EXCLUDE_PREFIXES)
                                or any(m in p.stem.lower()
                                       for m in EXCLUDE_CONTAINS)):
            skipped.append((p.name, "자기 기록"))
            continue
        if any(m in p.stem for m in COPY_MARKERS):
            skipped.append((p.name, "사본"))
            continue
        kept.append(p)
    return kept, skipped


def drop_duplicate_chunks(chunks):
    """본문이 완전히 같은 조각을 뺀다.

    파일명 규칙만으로는 사본을 다 거를 수 없다. 이름을 바꿔 저장했거나
    같은 내용이 두 문서에 복사돼 있을 수도 있다. 내용으로 한 번 더 본다.
    """
    seen, out, dropped = set(), [], []
    for c in chunks:
        key = c["text"].strip()
        if key in seen:
            dropped.append(c["id"])
            continue
        seen.add(key)
        out.append(c)
    return out, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--out", default="data/doc_index.json")
    ap.add_argument("--include-all", action="store_true",
                    help="평가·테스트 기록까지 전부 색인")
    ap.add_argument("--stats", action="store_true",
                    help="파일로 쓰지 않고 분포만 출력")
    args = ap.parse_args()

    paths, skipped = collect(ROOT / args.docs, args.include_all)
    for name, why in skipped:
        print(f"제외 ({why}): {name}")
    if skipped:
        print()
    if not paths:
        print(f"색인할 문서가 없습니다: {args.docs}")
        return 1

    chunks = []
    for p in paths:
        # 반드시 utf-8-sig 로 읽는다. BOM 이 남으면 첫 줄 "# 제목"이
        # 헤딩으로 인식되지 않아 문서 제목이 통째로 사라진다.
        text = p.read_text(encoding="utf-8-sig")
        got = split_markdown(text, p.stem)
        chunks += got
        sizes = [c["chars"] for c in got] or [0]
        print(f"{p.stem:28} {len(got):3}조각  "
              f"최소{min(sizes):5} 중앙{sorted(sizes)[len(sizes) // 2]:5} "
              f"최대{max(sizes):5}")

    chunks, dropped = drop_duplicate_chunks(chunks)
    if dropped:
        print(f"\n내용 중복으로 제외한 조각 {len(dropped)}개: "
              f"{', '.join(dropped[:5])}{' ...' if len(dropped) > 5 else ''}")

    sizes = [c["chars"] for c in chunks]
    print(f"\n총 {len(chunks)}조각 / 평균 {sum(sizes) // len(sizes)}자 / "
          f"350자 미만 {sum(1 for s in sizes if s < 350)}")

    if args.stats:
        return 0

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"docs": [p.stem for p in paths], "chunks": chunks},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"기록: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
