"""
연립다세대·오피스텔의 분동 애매 케이스를 '지번 주소' 기반으로 정밀 재매칭.

배경:
  - 단독다가구: 번지가 마스킹(1*, 2*)되어 있어 도로명 기반 근사 매칭이 한계
    (기존 resolve_ambiguous.py 결과 유지, 방법론 문서에 한계 명시)
  - 연립다세대/오피스텔: 본번·부번(지번)이 채워져 있음
    -> "시도 구 법정동 본번-부번" 완전한 지번 주소로 조회하면 한 지점이 정확히
       특정되므로, '같은 도로가 여러 행정동에 걸치는' 문제가 원천적으로 해소됨

실행 순서: resolve_ambiguous.py (도로명 기반) 실행 후에 이 스크립트를 실행.
          이 스크립트가 최종본 전월세_실거래가_통합_행정동_보정.csv 를 갱신한다.

우선순위: 지번 기반 결과(정밀) > 도로명 기반 결과(근사) > 텍스트 매칭 추정값
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
ROAD_CACHE_PATH = DATA_DIR / "kakao_cache.json"        # 도로명 기반 (resolve_ambiguous.py 산출)
JIBUN_CACHE_PATH = DATA_DIR / "jibun_cache.json"       # 지번 기반 (이 스크립트 산출)
OUTPUT_PATH = DATA_DIR / "전월세_실거래가_통합_행정동_보정.csv"

ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"

session = requests.Session()
session.headers.update({"Authorization": f"KakaoAK {KAKAO_API_KEY}"})


def norm_bunji(v) -> str | None:
    """본번/부번 값을 '1423' 같은 정수 문자열로 정규화. 0이나 결측이면 None."""
    if pd.isna(v):
        return None
    try:
        n = int(float(v))
        return str(n) if n > 0 else None
    except (ValueError, TypeError):
        return None


def geocode_jibun(key):
    """지번 주소로 조회. key = (시도, 구, 법정동, 본번, 부번문자열또는None)"""
    시도, 구, 법정동, 본번, 부번 = key
    jibun = f"{본번}-{부번}" if 부번 else 본번
    query = f"{시도} {구} {법정동} {jibun}"
    try:
        res = session.get(ADDRESS_URL, params={"query": query}, timeout=5)
        res.raise_for_status()
        docs = res.json().get("documents", [])
        for doc in docs[:5]:
            addr = doc.get("address")
            if not addr:
                continue
            # 검증: 구와 법정동이 모두 일치하는 결과만 채택
            if addr.get("region_2depth_name") == 구 and addr.get("region_3depth_name") == 법정동:
                return key, addr.get("region_3depth_h_name")
        return key, None
    except requests.RequestException:
        return key, None


def load_cache(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {tuple(k.split("|||")): v for k, v in raw.items()}
    return {}


def save_cache(cache: dict, path: Path):
    raw = {"|||".join(str(p) for p in k): v for k, v in cache.items()}
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    tmp.replace(path)


def normalize_dong_name(value):
    """'서울특별시 강남구 개포2동' 처럼 시/구가 붙어있어도 '개포2동'(동 이름만) 반환.
    캐시에 예전 버전의 값이 남아있어도, 최종 출력만큼은 항상 동 이름만 나오도록 하는 안전장치."""
    if not value or not isinstance(value, str):
        return value
    return value.strip().split()[-1]


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"{INPUT_PATH} 이 없습니다. dong_matcher.py를 먼저 실행하세요.")

    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig", low_memory=False)

    # 주택유형은 출처파일명으로 판별 (오피스텔 원본의 주택유형 컬럼 결측 문제 회피)
    def housing_type(s):
        if not isinstance(s, str):
            return None
        for t in ("단독다가구", "연립다세대", "오피스텔"):
            if t in s:
                return t
        return None

    df["_유형"] = df["출처파일"].apply(housing_type)

    ambiguous = df["행정동_추정필요"] == True
    jibun_target = ambiguous & df["_유형"].isin(["연립다세대", "오피스텔"])
    print(f"분동 애매 전체: {ambiguous.sum()}행")
    print(f"  ├ 지번 정밀 재조회 대상 (연립다세대/오피스텔): {jibun_target.sum()}행")
    print(f"  └ 도로명 근사 유지 (단독다가구, 번지 마스킹): {(ambiguous & ~jibun_target).sum()}행")

    df["_본번"] = df["본번"].apply(norm_bunji) if "본번" in df.columns else None
    df["_부번"] = df["부번"].apply(norm_bunji) if "부번" in df.columns else None

    targets = (
        df.loc[jibun_target & df["_본번"].notna(),
               ["시도명", "시군구명", "법정동명", "_본번", "_부번"]]
        .drop_duplicates()
    )
    all_keys = [
        (r[0], r[1], r[2], r[3], r[4])
        for r in targets.itertuples(index=False, name=None)
    ]
    print(f"조회할 고유 지번 조합: {len(all_keys)}개")

    cache = load_cache(JIBUN_CACHE_PATH)
    print(f"캐시에서 이미 처리된 조합: {len(cache)}개")

    # 캐시 키는 문자열 튜플이므로 None 부번은 'None' 문자열로 저장됨 -> 통일
    def to_cache_key(k):
        return tuple(str(p) for p in k)

    todo = [k for k in all_keys if to_cache_key(k) not in cache]
    print(f"이번에 처리할 조합: {len(todo)}개\n")

    if todo:
        done = 0
        start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(geocode_jibun, k): k for k in todo}
            for fut in as_completed(futures):
                key, dong = fut.result()
                cache[to_cache_key(key)] = dong
                done += 1
                if done % SAVE_EVERY == 0 or done == len(todo):
                    save_cache(cache, JIBUN_CACHE_PATH)
                    el = time.time() - start
                    rate = done / el
                    rem = (len(todo) - done) / rate if rate > 0 else 0
                    print(f"  {done}/{len(todo)} (속도 {rate:.2f}건/초, 남은 시간 {rem/60:.1f}분) - 저장됨")

    road_cache = load_cache(ROAD_CACHE_PATH)

    def apply_final(row):
        if row["행정동_추정필요"] != True:
            return row["행정동명"]
        # 1순위: 지번 정밀 결과 (연립다세대/오피스텔)
        if row["_유형"] in ("연립다세대", "오피스텔") and row["_본번"]:
            k = (str(row["시도명"]), str(row["시군구명"]), str(row["법정동명"]),
                 str(row["_본번"]), str(row["_부번"]))
            v = cache.get(k)
            if v:
                return v
        # 2순위: 도로명 근사 결과
        rk = (row["시도명"], row["시군구명"], row["도로명"])
        v = road_cache.get(rk)
        if v:
            return v
        # 3순위: 텍스트 매칭 추정값
        return row["행정동명"]

    df["행정동명_최종"] = df.apply(apply_final, axis=1)
    df["행정동명_최종"] = df["행정동명_최종"].apply(normalize_dong_name)

    # 통계
    jibun_hit = df.loc[jibun_target].apply(
        lambda r: bool(cache.get((str(r["시도명"]), str(r["시군구명"]), str(r["법정동명"]),
                                   str(r["_본번"]), str(r["_부번"])))) if r["_본번"] else False,
        axis=1,
    ).sum()
    print(f"\n지번 정밀 매칭 성공: {jibun_hit} / {jibun_target.sum()}행 (연립다세대/오피스텔)")

    df = df.drop(columns=["_유형", "_본번", "_부번"])
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUTPUT_PATH}")
    print("※ 다음 단계부터는 이 파일의 '행정동명_최종' 컬럼을 기준 행정동으로 사용하세요.")


if __name__ == "__main__":
    main()