"""
분동 케이스를 카카오 API로 정밀 매칭 (혼자 실행용 - 병렬처리 + 체크포인트 + 결과 검증)

결과 검증: API가 반환한 첫 번째 결과를 무조건 신뢰하지 않는다.
  - 주소 검색: 응답의 region_2depth_name(시군구)이 우리가 물어본 구와 실제로
    일치하는 문서만 채택한다. (동일한 도로명이 다른 구에도 존재할 수 있어,
    검증 없이 1등 결과를 그대로 쓰면 엉뚱한 지역의 도로가 섞일 위험이 있다)
  - 키워드 검색: 키워드 검색은 도로명이 아니라 '장소명'에 가까운 검색이라
    엉뚱한 동명(道路名) 장소가 1등으로 잡힐 위험이 상대적으로 더 크므로,
    상위 5개 문서를 순회하며 구 이름이 일치하는 첫 번째 결과만 채택한다.

중단/재시작:
  중간에 Ctrl+C로 멈추거나 오류로 끊겨도, data/kakao_cache.json 에 저장된
  결과는 남아있어서, 다시 실행하면 이미 처리한 조합은 건너뛰고 이어서 진행한다.

입력: data/전월세_실거래가_통합_행정동.csv (dong_matcher.py 결과물)
출력: data/전월세_실거래가_통합_행정동_보정.csv
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
import os

MAX_WORKERS = 8
SAVE_EVERY = 100

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")
KAKAO_API_KEY = os.environ.get("KAKAO_API_KEY")
if not KAKAO_API_KEY:
    sys.exit("KAKAO_API_KEY를 찾지 못했습니다. .env 파일을 확인하세요.")

INPUT_PATH = DATA_DIR / "전월세_실거래가_통합_행정동.csv"
OUTPUT_PATH = DATA_DIR / "전월세_실거래가_통합_행정동_보정.csv"
CACHE_PATH = DATA_DIR / "kakao_cache.json"

HEADERS = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
COORD2REGION_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"

session = requests.Session()
session.headers.update(HEADERS)


def try_address_search(query: str, expected_gu: str):
    res = session.get(ADDRESS_URL, params={"query": query}, timeout=5)
    res.raise_for_status()
    docs = res.json().get("documents", [])
    for doc in docs[:5]:
        addr = doc.get("address") or doc.get("road_address")
        if not addr:
            continue
        # 검증: 실제로 우리가 물어본 구와 일치하는 결과만 채택
        if addr.get("region_2depth_name") == expected_gu:
            return addr.get("region_3depth_h_name")
    return None


def try_keyword_to_dong(query: str, expected_gu: str):
    res = session.get(KEYWORD_URL, params={"query": query}, timeout=5)
    res.raise_for_status()
    docs = res.json().get("documents", [])
    for doc in docs[:5]:
        x, y = doc.get("x"), doc.get("y")
        if not x or not y:
            continue
        res2 = session.get(COORD2REGION_URL, params={"x": x, "y": y}, timeout=5)
        res2.raise_for_status()
        regions = res2.json().get("documents", [])
        gu_ok = any(
            r.get("region_type") == "B" and r.get("region_2depth_name") == expected_gu
            for r in regions
        )
        if not gu_ok:
            continue  # 구가 다르면 이 후보는 버리고 다음 후보 확인
        for r in regions:
            if r.get("region_type") == "H":
                return r.get("region_3depth_name")
    return None


def geocode_one(key):
    시도, 구, 도로명 = key
    query = f"{시도} {구} {도로명}".strip()
    try:
        dong = try_address_search(query, 구)
        if dong:
            return key, dong
    except requests.RequestException:
        pass
    try:
        return key, try_keyword_to_dong(query, 구)
    except requests.RequestException:
        return key, None


def load_cache() -> dict:
    if CACHE_PATH.exists():
        with open(CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return {tuple(k.split("|||")): v for k, v in raw.items()}
    return {}


def save_cache(cache: dict):
    raw = {"|||".join(k): v for k, v in cache.items()}
    tmp_path = CACHE_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    tmp_path.replace(CACHE_PATH)


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"{INPUT_PATH} 이 없습니다. dong_matcher.py를 먼저 실행하세요.")

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    ambiguous_mask = df["행정동_추정필요"] == True
    print(f"전체 {len(df)}행 중 분동 애매 케이스: {ambiguous_mask.sum()}행")

    targets = (
        df.loc[ambiguous_mask, ["시도명", "시군구명", "도로명"]]
        .dropna()
        .drop_duplicates()
    )
    all_keys = list(targets.itertuples(index=False, name=None))
    print(f"조회할 고유 (시도명, 시군구명, 도로명) 조합: {len(all_keys)}개")

    cache = load_cache()
    print(f"캐시에서 이미 처리된 조합: {len(cache)}개 (이어서 진행)")

    todo = [k for k in all_keys if k not in cache]
    print(f"이번에 처리할 조합: {len(todo)}개\n")

    if todo:
        done_count = 0
        start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(geocode_one, k): k for k in todo}
            for future in as_completed(futures):
                key, dong = future.result()
                cache[key] = dong
                done_count += 1

                if done_count % SAVE_EVERY == 0 or done_count == len(todo):
                    save_cache(cache)
                    elapsed = time.time() - start
                    rate = done_count / elapsed
                    remaining_sec = (len(todo) - done_count) / rate if rate > 0 else 0
                    print(
                        f"  {done_count}/{len(todo)} 처리 "
                        f"(속도 {rate:.2f}건/초, 예상 남은 시간 {remaining_sec/60:.1f}분) - 캐시 저장됨"
                    )
    else:
        print("모든 조합이 이미 캐시에 있습니다. API 호출 없이 바로 결과를 생성합니다.")

    def apply_resolved(row):
        if row["행정동_추정필요"] != True:
            return row["행정동명"]
        key = (row["시도명"], row["시군구명"], row["도로명"])
        return cache.get(key) or row["행정동명"]

    df["행정동명_최종"] = df.apply(apply_resolved, axis=1)

    resolved_row_count = df.loc[ambiguous_mask].apply(
        lambda r: bool(cache.get((r["시도명"], r["시군구명"], r["도로명"]))), axis=1
    ).sum()
    print(f"\n보정 적용된 행: {resolved_row_count} / {ambiguous_mask.sum()}")
    print(f"여전히 추정값으로 남은 행: {ambiguous_mask.sum() - resolved_row_count}")

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_PATH}")
    print("※ 다음 단계부터는 이 파일의 '행정동명_최종' 컬럼을 기준 행정동으로 사용하세요.")


if __name__ == "__main__":
    main()