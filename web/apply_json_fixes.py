"""
LOCA JSON 라벨 수정 스크립트

제가 파일을 받지 못한 JSON 3종(loca_data / loca_page5_data / loca_page6_data)의
라벨을 자동으로 고친다. 여러 번 실행해도 안전하다(이미 고쳐져 있으면 건너뜀).

사용법
    web 폴더에서
    python apply_json_fixes.py

    다른 위치라면
    python apply_json_fixes.py <static 폴더 경로>
"""

import json
import shutil
import sys
from collections import OrderedDict
from pathlib import Path


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=OrderedDict)


def save(path, data):
    shutil.copy(path, str(path) + ".bak")          # 원본은 .bak으로 보관
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fix_page1(static):
    """1페이지 - 420개 항목 라벨. 420은 유형화(427)가 아니라 통합부담 산출 대상."""
    path = static / "loca_data.json"
    if not path.exists():
        return "loca_data.json 없음 - 건너뜀"
    data = load(path)
    hits = 0
    for stat in data.get("methodology", {}).get("stats", []):
        if str(stat.get("value", "")).replace(",", "") == "420":
            if stat.get("label") == "행정동 통합부담 산출 완료":
                return "1페이지: 이미 수정됨"
            stat["label"] = "행정동 통합부담 산출 완료"
            hits += 1
    if not hits:
        return "1페이지: value=420 항목을 찾지 못함 - 직접 확인 필요"
    save(path, data)
    return "1페이지: 420개 라벨 -> '행정동 통합부담 산출 완료'"


def fix_page5(static):
    """5페이지 - 77.9만원은 월세가 아니라 월세 + 보증금 월환산."""
    path = static / "loca_page5_data.json"
    if not path.exists():
        return "loca_page5_data.json 없음 - 건너뜀"
    data = load(path)
    rent = data.get("verdict", {}).get("rent")
    if rent is None:
        return "5페이지: verdict.rent 경로를 찾지 못함 - 직접 확인 필요"
    if rent.get("title") == "주거비 비교" and rent.get("note"):
        return "5페이지: 이미 수정됨"
    rent["title"] = "주거비 비교"
    rent["note"] = "월세 + 보증금 월환산 기준"
    save(path, data)
    return "5페이지: '월세 비교' -> '주거비 비교' + 부제 추가"


def fix_page6(static):
    """6페이지 - 첫 카드만 퍼센트라 나머지 카드(분)와 비교가 안 된다."""
    path = static / "loca_page6_data.json"
    if not path.exists():
        return "loca_page6_data.json 없음 - 건너뜀"
    data = load(path)
    cards = data.get("transit", {}).get("cards", [])
    if not cards:
        return "6페이지: transit.cards 경로를 찾지 못함 - 직접 확인 필요"
    note = cards[0].get("note", "")
    if note == "혼잡 노출 약 1.3분":
        return "6페이지: 이미 수정됨"
    if "혼잡" not in note:
        return f"6페이지: 첫 카드 note가 예상과 다름({note!r}) - 직접 확인 필요"
    cards[0]["note"] = "혼잡 노출 약 1.3분"
    save(path, data)
    return "6페이지: '최대 혼잡 81.1%' -> '혼잡 노출 약 1.3분'"


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("static")
    if not base.exists():
        print(f"[중단] {base.resolve()} 폴더가 없다. static 폴더 경로를 인자로 넘겨라.")
        sys.exit(1)

    print(f"대상 폴더: {base.resolve()}\n")
    for fn in (fix_page1, fix_page5, fix_page6):
        print(" -", fn(base))
    print("\n원본은 같은 폴더에 .bak 으로 남겨뒀다.")


if __name__ == "__main__":
    main()
