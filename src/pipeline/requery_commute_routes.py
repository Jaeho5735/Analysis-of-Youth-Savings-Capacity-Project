"""
통근경로 전체 재조회 — 17번 대표경로 선택 로직 적용

기존 08~10번 산출물(commute_routes_analysis_ready.csv)에 두 가지 결함이 있다.

    ① 요청에 searchDttm 이 없어 호출 시점 기준으로 경로가 계산됐다
       -> 심야버스 포함 경로 1,233건(4.0%)
    ② 응답 10개 중 itineraries[0] 을 무비판 채택했다
       -> 지하철 미사용 경로 68.4%

17번 노트북(ROUTE_SELECTION_FIXED)이 시연 6개 동에 적용한 보정을
전체 OD에 그대로 적용한다. 선택 규칙과 상수는 17번과 동일하다.

    searchDttm  2026-07-15(수) 08:00 출발
    후보 범위    최단 경로 + 15분 이내
    선택 기준    편도 교통비 + 편도 시간가치(10,320원/시간) 최소
    동률 처리    시간 -> 요금 -> 환승 -> API 순위

사용법
    python requery_commute_routes.py --dry-run          연결·비용만 확인
    python requery_commute_routes.py --limit 20         20건만 시험
    python requery_commute_routes.py                    전체 실행

    중단되면 같은 명령으로 다시 실행하면 이어서 진행한다.

주의
    TMAP 대중교통 Free 요금제는 10건/일이라 전체 실행이 불가능하다.
    Premium(0.88원/건, 후불 종량제)으로 전환된 계정에서 실행할 것.
    외부 OD 약 30,209건 기준 예상 비용 약 26,600원.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ═════════════════════════════════════════════════════════════
# 기준값 — 17번 노트북과 동일하게 유지할 것
# ═════════════════════════════════════════════════════════════

TMAP_TRANSIT_URL = "https://apis.openapi.sk.com/transit/routes"

TIME_VALUE_PER_HOUR_WON = 10_320
WORK_DAYS_PER_MONTH = 21

# 일반 평일(수요일) 오전 8시 출발
ANALYSIS_DATE = "20260715"
SEARCH_TIME = "0800"
SEARCH_DATETIME = f"{ANALYSIS_DATE}{SEARCH_TIME}"

# 대표경로 선택
ROUTE_MAX_EXTRA_MINUTES = 15
ROUTE_SELECTION_METHOD = "generalized_cost_within_fastest_plus_15m_v1"

ROUTE_COUNT = 10          # 후보 개수
REQUEST_INTERVAL_SEC = 0.20
SAVE_EVERY = 100          # 중간 저장 간격
UNIT_PRICE_WON = 0.88     # Premium 단가

IN_CSV = "data/all_age_commute_od_selected_80.csv"
COORD_CSV = "data/commute_dong_geocoded_kakao.csv"   # 없으면 --coord 로 지정
OUT_CSV = "data/commute_routes_requeried.csv"
ALT_JSONL = "data/commute_routes_alternatives.jsonl"


def log(m=""):
    print(m, flush=True)


def section(t):
    log()
    log("=" * 68)
    log(t)
    log("=" * 68)


def read_csv_any(path, **kw):
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"{path} 읽기 실패")


def find_col(df, *keywords, exclude=()):
    for c in df.columns:
        s = str(c)
        if all(k in s for k in keywords) and not any(x in s for x in exclude):
            return c
    return None


# ═════════════════════════════════════════════════════════════
# TMAP 호출 · 대표경로 선택 (17번 로직)
# ═════════════════════════════════════════════════════════════

def request_route(start_lon, start_lat, end_lon, end_lat, app_key, timeout=30):
    payload = {
        "startX": str(start_lon),
        "startY": str(start_lat),
        "endX": str(end_lon),
        "endY": str(end_lat),
        "lang": 0,
        "format": "json",
        "count": ROUTE_COUNT,
        "searchDttm": SEARCH_DATETIME,   # ① 결함 수정
    }
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "appKey": app_key,
    }
    try:
        r = requests.post(TMAP_TRANSIT_URL, headers=headers, json=payload, timeout=timeout)
        try:
            data = r.json()
        except ValueError:
            data = {"raw_text": r.text}
        return {"success": bool(r.ok), "status_code": r.status_code,
                "response": data, "error": None if r.ok else str(data)[:500]}
    except Exception as e:
        return {"success": False, "status_code": None, "response": None, "error": str(e)}


def _route_name(leg):
    info = leg.get("route")
    if isinstance(info, str):
        return info
    if isinstance(info, dict):
        return info.get("name") or info.get("routeName") or info.get("id")
    return None


def summarize_itinerary(route, api_rank):
    """itinerary 1개를 요약하고 일반화비용을 붙인다."""
    if not isinstance(route, dict):
        return None
    tt = route.get("totalTime")
    if tt is None or float(tt) <= 0:
        return None

    fare = (route.get("fare") or {}).get("regular") or {}
    total_fare = fare.get("totalFare")
    total_fare = float(total_fare) if total_fare is not None else None

    modes, lines = [], []
    bus = subway = walk = train = 0
    for leg in route.get("legs", []) or []:
        mode = str(leg.get("mode") or "UNKNOWN")
        modes.append(mode)
        up = mode.upper()
        bus += up == "BUS"
        subway += up == "SUBWAY"
        walk += up == "WALK"
        train += up == "TRAIN"
        nm = _route_name(leg)
        if nm:
            lines.append(str(nm))

    minutes = round(float(tt) / 60, 1)
    gen_cost = (total_fare + (minutes / 60) * TIME_VALUE_PER_HOUR_WON
                if total_fare is not None else None)

    return {
        "API경로순위": int(api_rank),
        "편도통근시간_분": minutes,
        "편도거리_km": round((route.get("totalDistance") or 0) / 1000, 2),
        "편도교통비_원": total_fare,
        "편도시간가치_원": round((minutes / 60) * TIME_VALUE_PER_HOUR_WON, 1),
        "편도일반화비용_원": round(gen_cost, 1) if gen_cost is not None else None,
        "편도도보시간_분": round((route.get("totalWalkTime") or 0) / 60, 1),
        "편도도보거리_m": route.get("totalWalkDistance"),
        "환승횟수": route.get("transferCount"),
        "교통수단_순서": " → ".join(modes),
        "이용노선": " | ".join(dict.fromkeys(lines)),
        "버스_이용구간수": bus,
        "지하철_이용구간수": subway,
        "도보_구간수": walk,
        "기차_이용구간수": train,
    }


def select_representative(result):
    """
    ② 결함 수정 — itineraries[0] 대신 규칙으로 고른다.
      1) 시간·요금이 모두 있는 후보만
      2) 최단 + 15분 이내만 현실 후보
      3) 일반화비용(요금 + 시간가치) 최소
      4) 동률이면 시간 -> 요금 -> 환승 -> API 순위
    """
    if not result.get("success"):
        return None, []

    its = ((result.get("response") or {}).get("metaData", {})
           .get("plan", {}).get("itineraries", []))
    if not isinstance(its, list):
        return None, []

    summaries = [s for s in (summarize_itinerary(r, i)
                             for i, r in enumerate(its, start=1)) if s]
    valid = [s for s in summaries
             if s["편도통근시간_분"] is not None
             and s["편도교통비_원"] is not None
             and s["편도일반화비용_원"] is not None]
    if not valid:
        return None, summaries

    fastest = min(float(s["편도통근시간_분"]) for s in valid)
    realistic = [s for s in valid
                 if float(s["편도통근시간_분"]) <= fastest + ROUTE_MAX_EXTRA_MINUTES] or valid

    def key(s):
        tr = s.get("환승횟수")
        tr = float(tr) if tr is not None else 999
        return (float(s["편도일반화비용_원"]), float(s["편도통근시간_분"]),
                float(s["편도교통비_원"]), tr, int(s["API경로순위"]))

    sel = sorted(realistic, key=key)[0].copy()
    sel["후보수"] = len(summaries)
    sel["현실후보수"] = len(realistic)
    sel["선택방식"] = ROUTE_SELECTION_METHOD
    sel["조회기준시각"] = SEARCH_DATETIME
    sel["실제호출시각"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return sel, summaries


# ═════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--od", default=IN_CSV)
    ap.add_argument("--coord", default=COORD_CSV)
    ap.add_argument("--out", default=OUT_CSV)
    ap.add_argument("--limit", type=int, default=0, help="시험용 건수 제한")
    ap.add_argument("--dry-run", action="store_true", help="호출 없이 준비 상태만 점검")
    args = ap.parse_args()

    section("[1단계] 준비 점검")

    app_key = os.getenv("TMAP_APP_KEY") or os.getenv("TMAP_APP_KEY_1")
    log(f"  앱키: {'설정됨' if app_key else '(없음)'}")
    if not app_key and not args.dry_run:
        log("\n  .env 에 TMAP_APP_KEY 를 넣어라. 값은 코드에 적지 마라.")
        return

    od_path, coord_path = Path(args.od), Path(args.coord)
    for lb, p in [("OD", od_path), ("좌표", coord_path)]:
        log(f"  {lb:4s}: {p}  {'OK' if p.exists() else '(없음)'}")
    if not od_path.exists() or not coord_path.exists():
        log("\n  파일 경로를 --od / --coord 로 지정해라.")
        return

    od = read_csv_any(od_path, dtype=str)
    coord = read_csv_any(coord_path, dtype=str)
    log(f"\n  OD {len(od):,}행 / 좌표 {len(coord):,}행")

    c_home = find_col(od, "거주동", "코드")
    c_work = find_col(od, "근무동", "코드")
    c_key = find_col(od, "OD_KEY") or find_col(od, "OD", "KEY") or find_col(od, "od_key")
    c_inner = find_col(od, "내부통근")
    # 키 컬럼이 없으면 거주동_근무동으로 만든다. 이어받기 판정에 쓴다.
    if not c_key:
        od["_od_key"] = (od[c_home].astype(str).str.strip()
                         + "_" + od[c_work].astype(str).str.strip())
        c_key = "_od_key"
        log("  OD_KEY 컬럼이 없어 '거주동_근무동'으로 생성했다")
    log(f"  OD 컬럼: 거주동={c_home} / 근무동={c_work} / 키={c_key} / 내부통근={c_inner}")

    k_code = find_col(coord, "코드")
    k_lat = (find_col(coord, "대표", "위도") or find_col(coord, "위도")
             or find_col(coord, "lat"))
    k_lon = (find_col(coord, "대표", "경도") or find_col(coord, "경도")
             or find_col(coord, "lon"))
    log(f"  좌표 컬럼: 코드={k_code} / 위도={k_lat} / 경도={k_lon}")
    if not all([c_home, c_work, k_code, k_lat, k_lon]):
        log("\n  컬럼을 특정하지 못했다. 전체 컬럼:")
        log(f"    OD   : {list(od.columns)}")
        log(f"    좌표 : {list(coord.columns)}")
        return

    # OD 와 좌표표의 코드 자릿수가 다를 수 있다(8자리 통계청 / 10자리 KIKmix).
    # 양쪽 앞 8자리로 맞춘다.
    def code8(v):
        return str(v).strip().split(".")[0][:8]

    cmap = {code8(r[k_code]): (float(r[k_lon]), float(r[k_lat]))
            for _, r in coord.iterrows()
            if pd.notna(r[k_lat]) and pd.notna(r[k_lon])}
    log(f"  좌표 확보 행정동: {len(cmap)}개")

    # 내부통근은 API 대상이 아니다
    if c_inner:
        target = od[~od[c_inner].astype(str).str.lower().isin(["true", "1", "y"])].copy()
    else:
        target = od[od[c_home].astype(str) != od[c_work].astype(str)].copy()
    log(f"\n  API 대상(외부 OD): {len(target):,}건")

    miss_h = set(target[c_home].map(code8)) - set(cmap)
    miss_w = set(target[c_work].map(code8)) - set(cmap)
    miss = miss_h | miss_w
    if miss:
        log(f"  [주의] 좌표가 없는 행정동코드 {len(miss)}개: {sorted(miss)[:10]}")
        skip = target[target[c_home].map(code8).isin(miss)
                      | target[c_work].map(code8).isin(miss)]
        log(f"         이 코드가 걸린 OD {len(skip):,}건은 건너뛴다")
    else:
        log("  좌표 매칭: 전건 확보")

    # 이어받기
    done = set()
    out_path = Path(args.out)
    if out_path.exists():
        prev = read_csv_any(out_path, dtype=str)
        if "OD_KEY" in prev.columns:
            done = set(prev["OD_KEY"].dropna())
        log(f"  이미 완료: {len(done):,}건 (이어서 진행)")

    todo = target[~target[c_key].isin(done)]
    if args.limit:
        todo = todo.head(args.limit)
    log(f"  이번 실행 대상: {len(todo):,}건")
    log(f"  예상 비용: 약 {int(len(todo) * UNIT_PRICE_WON):,}원 (Premium {UNIT_PRICE_WON}원/건)")

    log()
    log(f"  조회 기준시각: {SEARCH_DATETIME}  (2026-07-15 수요일 08:00)")
    log(f"  대표경로 선택: 최단+{ROUTE_MAX_EXTRA_MINUTES}분 이내 중 일반화비용 최소")
    log(f"  시간가치: {TIME_VALUE_PER_HOUR_WON:,}원/시간 · 월 출근 {WORK_DAYS_PER_MONTH}일")

    if args.dry_run:
        section("dry-run 종료")
        log("  실제 호출 없이 준비 상태만 확인했다.")
        log("  이상 없으면 --limit 20 으로 시험한 뒤 전체 실행해라.")
        return

    section("[2단계] 재조회")

    rows, alts, fail = [], [], []
    t0 = time.time()
    for i, (_, r) in enumerate(todo.iterrows(), start=1):
        h = code8(r[c_home])
        w = code8(r[c_work])
        if h not in cmap or w not in cmap:
            fail.append({"OD_KEY": r[c_key], "사유": "좌표없음"})
            continue

        (slon, slat), (elon, elat) = cmap[h], cmap[w]
        res = request_route(slon, slat, elon, elat, app_key)
        sel, cands = select_representative(res)

        if sel is None:
            fail.append({"OD_KEY": r[c_key], "사유": res.get("error") or "경로없음"})
        else:
            sel["OD_KEY"] = r[c_key]
            sel["거주동 코드"] = r[c_home]
            sel["근무동 코드"] = r[c_work]
            rows.append(sel)
            alts.append({"OD_KEY": r[c_key],
                         "candidates": [{k: c.get(k) for k in
                                         ("API경로순위", "편도통근시간_분", "편도교통비_원",
                                          "편도일반화비용_원", "환승횟수", "이용노선")}
                                        for c in cands]})

        if i % SAVE_EVERY == 0 or i == len(todo):
            mode = "a" if out_path.exists() else "w"
            pd.DataFrame(rows).to_csv(out_path, mode=mode, header=(mode == "w"),
                                      index=False, encoding="utf-8-sig")
            with open(ALT_JSONL, "a", encoding="utf-8") as f:
                for a in alts:
                    f.write(json.dumps(a, ensure_ascii=False) + "\n")
            rows, alts = [], []
            el = time.time() - t0
            eta = el / i * (len(todo) - i)
            log(f"  {i:>6,}/{len(todo):,}  실패 {len(fail):>4}  경과 {el/60:.1f}분  남은 {eta/60:.1f}분")

        time.sleep(REQUEST_INTERVAL_SEC)

    if fail:
        pd.DataFrame(fail).to_csv("data/requery_failures.csv", index=False, encoding="utf-8-sig")

    section("완료")
    log(f"  저장: {out_path}")
    log(f"  후보 감사 로그: {ALT_JSONL}")
    log(f"  실패: {len(fail):,}건" + (" -> data/requery_failures.csv" if fail else ""))
    log()
    log("  다음: 심야버스가 사라졌는지 확인")
    log("    python -c \"import pandas as pd; d=pd.read_csv('%s',encoding='utf-8-sig');"
        " print((d['이용노선'].astype(str).str.contains(r'N\\\\d{2}')).sum())\"" % out_path)


if __name__ == "__main__":
    main()