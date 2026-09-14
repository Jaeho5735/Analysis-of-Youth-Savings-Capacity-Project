"""마지막 평가 실행의 답변 원문과 실패 사유를 꺼내 본다.

    python scripts/show_eval_detail.py                # 실패한 문항 전부
    python scripts/show_eval_detail.py --axis citation # 특정 축만
    python scripts/show_eval_detail.py --id p6-01      # 한 문항
    python scripts/show_eval_detail.py --cited         # 인용 경로만 모아 보기

점수만 보면 "무엇을 고쳐야 하는지"를 알 수 없다. citation 축이 낮을 때
모델이 근거를 안 쓴 것인지, 채점기가 멀쩡한 인용을 못 알아본 것인지는
실제로 무엇을 인용했는지 봐야 갈린다. 지금까지 채점기 쪽이 다섯 번 틀렸다.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="docs/chatbot-eval-raw.json")
    ap.add_argument("--axis", help="이 축이 실패한 문항만")
    ap.add_argument("--id", help="이 문항만")
    ap.add_argument("--cited", action="store_true",
                    help="인용 경로만 모아서 빈도순으로")
    ap.add_argument("--run", type=int, default=-1,
                    help="몇 번째 실행인지. 기본은 마지막")
    args = ap.parse_args()

    path = ROOT / args.raw
    if not path.exists():
        print(f"파일이 없습니다: {args.raw}")
        return 1
    runs = json.loads(path.read_text(encoding="utf-8"))
    run = runs[args.run]
    items = run["items"]
    print(f"실행 {run['at']} · 모델 {run['model']} · {len(items)}문항\n")

    if args.cited:
        cnt = Counter()
        for it in items:
            for c in it.get("cited") or []:
                cnt[c] += 1
        print("인용된 경로 (빈도순)")
        for c, n in cnt.most_common():
            print(f"  {n:3}회  {c}")
        return 0

    for it in items:
        if args.id and it["id"] != args.id:
            continue
        axes = it["grade"]["axes"]
        failed = [a for a, ok in axes.items() if not ok]
        if not args.id:
            if not failed:
                continue
            if args.axis and args.axis not in failed:
                continue

        print(f"── {it['id']}  실패축: {', '.join(failed) or '-'}")
        print(f"   Q. {it['question']}")
        if it.get("docs"):
            print(f"   문서: {', '.join(it['docs'])}")
        print(f"   인용: {it.get('cited')}")
        print(f"   거절: {it.get('refused')} / {it.get('unknown_used')}")
        for axis, why in (it["grade"].get("detail") or {}).items():
            print(f"   [{axis}] {why}")
        print(f"   답변: {(it.get('answer') or '')[:260]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
