"""
사용자 입력 해석 — 주소 · 지하철역 · 건물명 -> 행정동

서비스 입력창에 무엇을 넣든 행정동코드8 로 바꿔준다.
우리 분석이 행정동 단위이므로, 개인 좌표까지 내려가지 않고
"그 주소가 속한 행정동" 까지만 해석한다.

    "역삼동 123-4"        -> 11680640 역삼1동
    "강남역"              -> 11680640 역삼1동
    "테헤란로 152"        -> 11680640 역삼1동
    "여의도 IFC"          -> 11560540 여의동

카카오 로컬 API 두 가지를 순서대로 쓴다.

    1. 주소검색  address.json   도로명 · 지번 주소에 강하다
    2. 키워드검색 keyword.json  역명 · 건물명 · 상호에 강하다

응답의 region_3depth_h_name(행정동명)을 우선 쓰고,
없으면 좌표를 coord2regioncode 로 역지오코딩한다.
최종적으로 행정동명을 우리 기준표의 코드8 에 맞춘다.

사용법
    from resolve_place import resolve, suggest

    resolve("강남역")
    # {"status":"ok","dong_code":"11680640","dong_name":"역삼1동", ...}

    suggest("역삼")   # 자동완성용 후보 목록

    python resolve_place.py 강남역        # 단건 시험
    python resolve_place.py --self-test   # 대표 입력 일괄 시험
"""

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    _here = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
    for _p in [_here] + list(_here.parents):
        if (_p / ".env").is_file():
            load_dotenv(_p / ".env")
            break
except ImportError:
    pass

KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
KAKAO_COORD2REGION_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"

# 서울 중심 좌표 — 키워드 검색을 서울로 유도한다
SEOUL_LON, SEOUL_LAT, SEOUL_RADIUS = 126.9780, 37.5665, 20000

# 실행 위치가 프로젝트 루트든 web/ 든 상관없이 찾도록 위로 올라가며 탐색한다.
_CSV_NAMES = [
    "commute_dong_geocoded_kakao.csv",
    "행정동_기준코드표.csv",
    "행정동_소스별_커버리지.csv",
]


def _find_coord_csv():
    here = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
    roots = [Path.cwd()] + [here.parent] + list(here.parents)
    seen = []
    for root in roots:
        for name in _CSV_NAMES:
            for cand in (root / "data" / name, root / name):
                if cand not in seen:
                    seen.append(cand)
                if cand.is_file():
                    return cand
    return None, seen


def _key():
    for n in ("KAKAO_REST_API_KEY", "KAKAO_API_KEY", "KAKAO_KEY",
              "KAKAO_REST_KEY", "KAKAO_APP_KEY"):
        v = os.getenv(n)
        if v:
            return v.strip()
    return None


def _headers():
    k = _key()
    if not k:
        raise RuntimeError(
            ".env 에서 카카오 키를 찾지 못했다. "
            "KAKAO_REST_API_KEY 등으로 넣어라.")
    return {"Authorization": f"KakaoAK {k}"}


# ─────────────────────────────────────────────────────────────
# 행정동명 -> 코드8
# ─────────────────────────────────────────────────────────────

def norm_dong(s):
    """표기변이 흡수. 창신제1동 -> 창신1동, 종로5·6가동 -> 종로56가동"""
    if not s:
        return ""
    s = str(s).strip()
    s = re.sub(r"제(\d+)", r"\1", s)
    s = re.sub(r"[·.\s]", "", s)
    return s


@lru_cache(maxsize=1)
def _dong_table():
    """(정규화 행정동명, 자치구) -> (코드8, 표시명) 사전을 만든다."""
    import pandas as pd
    found = _find_coord_csv()
    paths = [found] if isinstance(found, Path) else []
    for p in paths:
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                df = pd.read_csv(p, encoding=enc, dtype=str)
                break
            except UnicodeDecodeError:
                continue
        else:
            continue
        code = next((c for c in df.columns if "코드" in c), None)
        name = next((c for c in df.columns if "행정동" in c and "코드" not in c), None)
        gu = next((c for c in df.columns if "자치구" in c or "시군구" in c), None)
        if not code or not name:
            continue
        by_gu, by_name = {}, {}
        for _, r in df.iterrows():
            c8 = str(r[code]).strip().split(".")[0][:8]
            nm = str(r[name]).strip()
            g = str(r[gu]).strip() if gu else ""
            if len(c8) != 8:
                continue
            by_gu[(norm_dong(nm), g)] = (c8, nm, g)
            by_name.setdefault(norm_dong(nm), []).append((c8, nm, g))
        return by_gu, by_name
    raise RuntimeError(
        "행정동 기준표를 찾지 못했다. 아래 중 하나가 있어야 한다:\n  "
        + "\n  ".join(_CSV_NAMES)
        + "\n프로젝트 루트 또는 그 아래 data/ 에 두어라.")


def to_dong_code(dong_name, gu_name=""):
    """행정동명(+자치구)을 코드8 로 바꾼다."""
    by_gu, by_name = _dong_table()
    k = norm_dong(dong_name)
    if gu_name and (k, gu_name) in by_gu:
        return by_gu[(k, gu_name)]
    hits = by_name.get(k, [])
    if len(hits) == 1:
        return hits[0]
    if hits and gu_name:
        for h in hits:
            if h[2] == gu_name:
                return h
    return None


# ─────────────────────────────────────────────────────────────
# 카카오 호출
# ─────────────────────────────────────────────────────────────

def _get(url, params, timeout=5):
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=timeout)
        if not r.ok:
            return None
        return r.json()
    except requests.RequestException:
        return None


def _search_address(q, size=5):
    d = _get(KAKAO_ADDRESS_URL, {"query": q, "size": size})
    return (d or {}).get("documents", []) or []


def _search_keyword(q, size=8):
    d = _get(KAKAO_KEYWORD_URL, {
        "query": q, "size": size,
        "x": SEOUL_LON, "y": SEOUL_LAT, "radius": SEOUL_RADIUS, "sort": "accuracy"})
    return (d or {}).get("documents", []) or []


def _coord_to_region(lon, lat):
    d = _get(KAKAO_COORD2REGION_URL, {"x": lon, "y": lat})
    for doc in (d or {}).get("documents", []):
        if doc.get("region_type") == "H":     # H = 행정동
            return doc.get("region_3depth_name"), doc.get("region_2depth_name")
    return None, None


def _from_address_doc(doc):
    """주소검색 응답 1건에서 (행정동명, 자치구, 표시주소, 좌표)를 뽑는다."""
    road, addr = doc.get("road_address"), doc.get("address")
    src = addr or road or {}
    gu = src.get("region_2depth_name", "")
    dong = src.get("region_3depth_h_name") or ""   # 행정동명
    label = (road or {}).get("address_name") or (addr or {}).get("address_name") or ""
    lon, lat = doc.get("x"), doc.get("y")
    return dong, gu, label, lon, lat


def _from_keyword_doc(doc):
    gu = ""
    addr = doc.get("road_address_name") or doc.get("address_name") or ""
    m = re.search(r"(\S+구)\s", addr)
    if m:
        gu = m.group(1)
    return doc.get("place_name", ""), gu, addr, doc.get("x"), doc.get("y")


# ─────────────────────────────────────────────────────────────
# 공개 함수
# ─────────────────────────────────────────────────────────────

def resolve(query):
    """입력 한 건을 행정동으로 해석한다."""
    q = (query or "").strip()
    if not q:
        return {"status": "empty"}

    # 1) 우리 기준표에 바로 있는 행정동명인가
    hit = to_dong_code(q)
    if hit:
        return {"status": "ok", "dong_code": hit[0], "dong_name": hit[1],
                "gu": hit[2], "matched_by": "행정동명", "label": q}

    # 2) 주소검색 -> 3) 키워드검색
    for finder, extract, how in (
            (_search_address, _from_address_doc, "주소"),
            (_search_keyword, _from_keyword_doc, "장소명")):
        for doc in finder(q):
            dong, gu, label, lon, lat = extract(doc)
            if how == "주소" and dong:
                h = to_dong_code(dong, gu)
                if h:
                    return {"status": "ok", "dong_code": h[0], "dong_name": h[1],
                            "gu": h[2], "matched_by": how, "label": label or q,
                            "lon": lon, "lat": lat}
            # 좌표 역지오코딩
            if lon and lat:
                dn, dg = _coord_to_region(lon, lat)
                if dn:
                    h = to_dong_code(dn, dg or gu)
                    if h:
                        return {"status": "ok", "dong_code": h[0], "dong_name": h[1],
                                "gu": h[2], "matched_by": f"{how}+좌표",
                                "label": label or dong or q, "lon": lon, "lat": lat}

    return {"status": "not_found", "query": q,
            "reason": "서울 행정동으로 해석하지 못했습니다. "
                      "지하철역명, 도로명주소, 지번주소로 다시 입력해보세요."}


def suggest(query, limit=8):
    """자동완성 후보. 화면에 보여줄 최소 정보만 담는다."""
    q = (query or "").strip()
    if len(q) < 2:
        return []

    out, seen = [], set()

    # 우리 행정동명 부분일치 우선
    _, by_name = _dong_table()
    nq = norm_dong(q)
    for k, hits in by_name.items():
        if nq in k:
            for c8, nm, g in hits:
                if c8 in seen:
                    continue
                seen.add(c8)
                out.append({"label": nm, "sub": g, "dong_code": c8,
                            "dong_name": nm, "kind": "행정동"})
    # 카카오 장소·주소
    for doc in _search_keyword(q, size=limit):
        name, gu, addr, lon, lat = _from_keyword_doc(doc)
        key = f"{name}|{addr}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": name, "sub": addr, "kind": "장소"})
    for doc in _search_address(q, size=3):
        dong, gu, label, lon, lat = _from_address_doc(doc)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append({"label": label, "sub": f"{gu} {dong}".strip(), "kind": "주소"})

    return out[:limit]


# ─────────────────────────────────────────────────────────────

SELF_TEST = ["강남역", "역삼동", "테헤란로 152", "여의도 IFC", "삼성전자 서초사옥",
             "신사샤르망S", "판교 테크노밸리", "상암월드컵파크", "없는곳12345"]


def main():
    if "--self-test" in sys.argv:
        print(f"카카오 키: {'설정됨' if _key() else '(없음)'}\n")
        for q in SELF_TEST:
            r = resolve(q)
            if r["status"] == "ok":
                print(f"  {q:<18} -> {r['dong_name']:<12} {r['gu']:<8} "
                      f"{r['dong_code']}  [{r['matched_by']}]")
            else:
                print(f"  {q:<18} -> {r['status']}")
        return
    if len(sys.argv) > 1:
        print(json.dumps(resolve(" ".join(sys.argv[1:])),
                         ensure_ascii=False, indent=2))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()