"""
카카오 API로도 해결 안 된 도로명(kakao_cache.json에서 값이 None인 항목)을
도로명주소 안내시스템(juso.go.kr) API로 재조회한다.

결과 검증: 응답의 sggNm(시군구명)이 우리가 물어본 구와 실제로 일치하는
결과만 채택한다 (동일 도로명이 다른 구에도 있을 수 있어 1등 결과를
검증 없이 그대로 쓰지 않는다).

사전 준비:
  1. https://www.juso.go.kr -> 오픈API -> 검색 API -> 신청 (즉시 발급)
  2. .env에 JUSO_API_KEY=발급받은_승인키 추가

실행 후: 이 스크립트는 kakao_cache.json을 직접 업데이트한다.
        그 다음 python src/resolve_ambiguous.py 를 다시 실행하면
        (이미 캐시에 다 있으므로 API 재호출 없이) 최종 CSV가 갱신된다.
"""

import json
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_PATH = DATA_DIR / "kakao_cache.json"

load_dotenv(PROJECT_ROOT / ".env")
JUSO_API_KEY = os.environ.get("JUSO_API_KEY")
if not JUSO_API_KEY:
    sys.exit(
        "JUSO_API_KEY를 찾지 못했습니다.\n"
        f".env 파일({PROJECT_ROOT / '.env'})에 JUSO_API_KEY=승인키 를 추가하세요."
    )

JUSO_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"


def query_juso(query: str, expected_gu: str) -> tuple:
    """반환값: (행정동명 또는 None, 에러메시지 또는 None)"""
    params = {
        "confmKey": JUSO_API_KEY,
        "currentPage": 1,
        "countPerPage": 5,   # 검증을 위해 5건까지 받아서 그중 구가 맞는 걸 고른다
        "keyword": query,
        "resultType": "json",
        "addInfoYn": "Y",  # hemdNm(행정동명) 필드를 받기 위해 필수
    }
    res = requests.get(JUSO_URL, params=params, timeout=5)
    res.raise_for_status()
    data = res.json()

    common = data.get("results", {}).get("common", {})
    if common.get("errorCode") != "0":
        return None, f"{common.get('errorCode')}: {common.get('errorMessage')}"

    for juso in data.get("results", {}).get("juso", []):
        # 검증: 실제로 우리가 물어본 구와 일치하는 결과만 채택
        if juso.get("sggNm") == expected_gu:
            hemdNm = juso.get("hemdNm")
            if hemdNm:
                return hemdNm, None
    return None, "구 불일치 또는 hemdNm 없음 (결과는 있으나 조건 미충족)"


def main():
    if not CACHE_PATH.exists():
        sys.exit(f"{CACHE_PATH} 이 없습니다. resolve_ambiguous.py를 먼저 실행하세요.")

    with open(CACHE_PATH, encoding="utf-8") as f:
        raw_cache = json.load(f)

    failed_keys = [k for k, v in raw_cache.items() if not v]
    print(f"카카오 API로 실패했던 조합: {len(failed_keys)}개 -> juso.go.kr로 재조회")

    updated = 0
    for i, raw_key in enumerate(failed_keys, 1):
        시도, 구, 도로명 = raw_key.split("|||")
        query = f"{시도} {구} {도로명}".strip()

        try:
            dong, error_msg = query_juso(query, 구)
        except requests.RequestException as e:
            print(f"  [{i}/{len(failed_keys)}] 요청 실패: {query} -> {e}")
            dong, error_msg = None, str(e)

        if dong:
            raw_cache[raw_key] = dong
            updated += 1
            print(f"  [{i}/{len(failed_keys)}] {구} {도로명} -> {dong}")
        else:
            print(f"  [{i}/{len(failed_keys)}] {구} {도로명} -> 매칭 실패 ({error_msg})")

        if i % 100 == 0:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(raw_cache, f, ensure_ascii=False)
            print(f"  ... {i}건 처리, 캐시 저장됨")

        time.sleep(0.05)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(raw_cache, f, ensure_ascii=False)

    print(f"\njuso.go.kr로 추가 해결된 조합: {updated} / {len(failed_keys)}")
    print("캐시 저장 완료. 이제 python src/resolve_ambiguous.py 를 다시 실행해 최종 CSV를 갱신하세요.")


if __name__ == "__main__":
    main()