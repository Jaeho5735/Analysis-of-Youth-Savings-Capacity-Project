"""
kakao_cache.json / jibun_cache.json 안에 저장된 값들 중,
'서울특별시 강남구 개포2동'처럼 시/구가 붙어있는 값을 '개포2동'(동 이름만)으로 정리한다.

원인: 검증 로직을 추가하기 전 초기 버전의 API 응답이 일부 캐시에 그대로 남아있었고,
     '이미 처리된 조합은 건너뛴다'는 이어하기 로직 때문에 재검증 없이 계속 남아있었음.

이 스크립트는 API를 다시 호출하지 않고, 이미 저장된 캐시 파일의 값만 정리한다.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

CACHE_FILES = ["kakao_cache.json", "jibun_cache.json"]


def normalize_dong_name(value):
    """'서울특별시 강남구 개포2동' -> '개포2동' / 이미 동 이름만 있으면 그대로."""
    if not value or not isinstance(value, str):
        return value
    return value.strip().split()[-1]


def main():
    for filename in CACHE_FILES:
        path = DATA_DIR / filename
        if not path.exists():
            print(f"⚠️ {filename} 없음, 건너뜀")
            continue

        with open(path, encoding="utf-8") as f:
            cache = json.load(f)

        changed = 0
        for k, v in cache.items():
            normalized = normalize_dong_name(v)
            if normalized != v:
                cache[k] = normalized
                changed += 1

        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)

        print(f"{filename}: 전체 {len(cache)}개 중 {changed}개 값 정리됨")


if __name__ == "__main__":
    main()