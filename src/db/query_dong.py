"""
LOCA 조회 계층

응답 계약(docs/LOCA_응답계약.md)의 status 4종을 그대로 돌려준다.
웹(app.py)은 이 모듈의 함수만 호출하면 되고 SQL을 몰라도 된다.

    from src.db.query_dong import get_dong

    result = get_dong("11710566")
    # {"status": "no_data", "dong": {...}, "alternatives": [...]}

사용법
    1) 점검   python src/db/query_dong.py --inspect
              실제 테이블 스키마를 찍는다. 아래 COLS 를 확인/수정한다.
    2) 접속   python src/db/query_dong.py --env
              .env 에서 접속 정보를 제대로 읽었는지 확인한다.

    3) 시험   python src/db/query_dong.py 11710566
              python src/db/query_dong.py 마장동

주의
    컬럼명을 추측하지 않는다. 반드시 --inspect 로 확인하고 COLS 를 맞춘 뒤 쓴다.
"""

import json
import os
import sys
from pathlib import Path

import pymysql

try:
    from dotenv import load_dotenv
    # 프로젝트 루트의 .env 를 찾아 읽는다. 이 파일 위치가 바뀌어도 따라간다.
    _here = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
    for _p in [_here] + list(_here.parents):
        _cand = _p / ".env"
        if _cand.is_file():
            load_dotenv(_cand)
            break
except ImportError:
    load_dotenv = None


def env_any(*names, default=None, cast=str):
    """.env 의 키 이름이 프로젝트마다 다르므로 후보를 순서대로 찾는다."""
    for n in names:
        v = os.getenv(n)
        if v not in (None, ""):
            return cast(v)
    return default


# ─────────────────────────────────────────────────────────────
# 접속 정보
#   .env 에서 읽는다. 비밀번호를 이 파일에 절대 적지 마라.
#   키 이름이 아래 후보에 없으면 --env 로 확인하고 후보를 추가하면 된다.
# ─────────────────────────────────────────────────────────────
DB = {
    "host": env_any("MYSQL_HOST", "DB_HOST", "DATABASE_HOST", default="localhost"),
    "port": env_any("MYSQL_PORT", "DB_PORT", default=3306, cast=int),
    "user": env_any("MYSQL_USER", "DB_USER", "DATABASE_USER", default="root"),
    "password": env_any("MYSQL_PASSWORD", "MYSQL_PW", "DB_PASSWORD", "DB_PW",
                        "MYSQL_ROOT_PASSWORD", "DATABASE_PASSWORD", default=""),
    "database": env_any("MYSQL_DATABASE", "MYSQL_DB", "DB_NAME", "DATABASE_NAME",
                        default="multicam"),
    "charset": "utf8mb4",
}


def env_check():
    """어떤 키를 찾았는지 보여준다. 비밀번호 값 자체는 찍지 않는다."""
    print("접속 설정")
    for k, v in DB.items():
        shown = "(설정됨)" if k == "password" and v else ("(비어 있음)" if k == "password" else v)
        print(f"  {k:10s} {shown}")
    if not DB["password"]:
        print()
        print("  비밀번호를 못 찾았다. .env 에 아래 중 하나로 적혀 있어야 한다.")
        print("    MYSQL_PASSWORD / MYSQL_PW / DB_PASSWORD / DB_PW / DATABASE_PASSWORD")
        print("  다른 이름을 쓰고 있다면 env_any(...) 의 후보 목록에 추가해라.")
        if load_dotenv is None:
            print()
            print("  python-dotenv 가 설치돼 있지 않다:  pip install python-dotenv")


# ─────────────────────────────────────────────────────────────
# 컬럼 매핑
#   --inspect 결과를 보고 오른쪽 값을 실제 컬럼명으로 고쳐라.
#   왼쪽 키는 코드가 쓰는 이름이니 바꾸지 마라.
# ─────────────────────────────────────────────────────────────
COLS = {
    "region": {"table": "dim_region", "code": "dong_code8",
               "name": "dong_name", "gu": "sigungu_name"},
    "burden": {"table": "fact_dong_burden", "code": "dong_code8",
               "housing": "surface_housing_cost",
               "fare_actual": "monthly_transport_cost",   # 실지출
               "fare_pass": "monthly_transport_pass",     # 정기권(기후동행카드 캡)
               "commute_hour": "monthly_commute_hour",
               "commute_min": "oneway_commute_min",
               "burden_type": "burden_type_src"},
    "dtype": {"table": "fact_dong_type", "code": "dong_code8",
              "type_name": "type_name", "k": "k_value"},
}

# 시간가치 단가(원/시간). 최저임금 기준, 팀 확정값.
TIME_VALUE_PER_HOUR = 10320

# 총부담 계산에 쓸 교통비. "pass"(정기권) 또는 "actual"(실지출).
FARE_MODE = "pass"

# fact_dong_type 은 (dong_code8, k_value) 복합키라 k 를 지정해야 한다.
K_VALUE = 6

# 근무지 기본값. 시연 시나리오의 역삼1동(삼정KPMG).
# work_code 를 넘기면 fact_commute_route 에서 그 근무지 기준 경로를 쓴다.
# 넘기지 않으면 fact_dong_burden 의 거주동 전체 평균을 쓰는데,
# 근무지 기준 화면에서는 쓰면 안 된다.
DEFAULT_WORK_DONG = "11680640"

# 월 출근일수. 팀 산출 파라미터가 21일이고 화면 2페이지 입력 기본값도 21일이다.
# (시안 검산: 17.2분 x 2 x 21 / 60 = 12.04h x 10,320원 = 124,253원 = 화면 12.4만원)
WORK_DAYS_PER_MONTH = 21

# 정기권 월 상한. DB 의 dim_transport_pass_assumption 기본 가정(youth_regular)과
# 같은 값이어야 한다. 여기만 옛 값이면 조회 결과가 화면·CSV 와 어긋난다.
TRANSIT_PASS_CAP = 55000

REASON_TEXT = {
    "no_data": "대단지 아파트 위주로 비아파트 임차 거래가 거의 없어 주거비를 산출하지 못했습니다.",
    "unreliable": "이 지역은 주거비 산출 과정에서 인접 동의 값이 섞였을 가능성이 높습니다. 참고용으로만 확인해주세요.",
    "low_confidence": "표본이 적어 참고용으로 보시는 것을 권합니다.",
}


def _num(v):
    """DECIMAL 은 Decimal 객체로 오는데 jsonify 가 직렬화하지 못한다.
    정수면 int, 아니면 float 으로 바꾼다."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f.is_integer() else round(f, 2)


def connect():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB)


# ═════════════════════════════════════════════════════════════
# 점검
# ═════════════════════════════════════════════════════════════

def inspect():
    tables = ["dim_region", "fact_dong_burden", "fact_dong_type",
              "dim_dong_reliability", "dim_fallback_candidate"]
    with connect() as conn, conn.cursor() as cur:
        for t in tables:
            print("=" * 60)
            print(t)
            print("=" * 60)
            try:
                cur.execute(f"DESCRIBE `{t}`")
                for r in cur.fetchall():
                    print(f"  {r['Field']:24s} {r['Type']}")
                cur.execute(f"SELECT COUNT(*) AS n FROM `{t}`")
                print(f"  -- 행수 {cur.fetchone()['n']:,}")
            except Exception as e:
                print(f"  [없음] {e}")
            print()
    print("위 결과를 보고 이 파일 상단의 COLS 를 실제 컬럼명으로 맞춰라.")


# ═════════════════════════════════════════════════════════════
# 조회
# ═════════════════════════════════════════════════════════════

def _fare_col():
    b = COLS["burden"]
    return b["fare_pass"] if FARE_MODE == "pass" else b["fare_actual"]


def _burden_sql():
    r, b, t = COLS["region"], COLS["burden"], COLS["dtype"]
    fare = _fare_col()
    # 시간비용과 총부담은 컬럼으로 저장돼 있지 않다.
    # 시간가치 가정을 테이블에 박지 않기로 해서 조회 시점에 계산한다.
    return f"""
        SELECT r.`{r['code']}`  AS code,
               r.`{r['name']}`  AS name,
               r.`{r['gu']}`    AS gu,
               rel.status       AS status,
               rel.reason       AS reason,
               rel.tx_count     AS tx_count,
               b.`{b['housing']}`      AS housing_cost,
               b.`{b['fare_actual']}`  AS fare_actual,
               b.`{b['fare_pass']}`    AS fare_pass,
               b.`{fare}`              AS fare,
               ROUND(b.`{b['commute_hour']}` * {TIME_VALUE_PER_HOUR}) AS time_value,
               ( b.`{b['housing']}` + b.`{fare}`
                 + ROUND(b.`{b['commute_hour']}` * {TIME_VALUE_PER_HOUR}) ) AS total,
               b.`{b['commute_min']}`  AS commute_min,
               b.`{b['burden_type']}`  AS burden_type,
               t.`{t['type_name']}`    AS dong_type
        FROM `{r['table']}` r
        LEFT JOIN dim_dong_reliability rel ON rel.dong_code8 = r.`{r['code']}`
        LEFT JOIN `{b['table']}` b         ON b.`{b['code']}` = r.`{r['code']}`
        LEFT JOIN `{t['table']}` t         ON t.`{t['code']}` = r.`{r['code']}`
                                          AND t.`{t['k']}`    = {K_VALUE}
        WHERE r.`{r['code']}` = %s
    """


def _route_sql():
    """근무지를 지정했을 때. 통근 값은 fact_commute_route 에서 가져온다."""
    r, b, t = COLS["region"], COLS["burden"], COLS["dtype"]
    return f"""
        SELECT r.`{r['code']}`  AS code,
               r.`{r['name']}`  AS name,
               r.`{r['gu']}`    AS gu,
               rel.status       AS status,
               rel.reason       AS reason,
               rel.tx_count     AS tx_count,
               b.`{b['housing']}`   AS housing_cost,
               cr.oneway_min        AS commute_min,
               cr.oneway_km         AS oneway_km,
               cr.route_lines       AS route_lines,
               cr.mode_sequence     AS mode_sequence,
               cr.fare              AS oneway_fare,
               cr.transfer_cnt      AS transfer,
               cr.has_route         AS has_route,
               cr.has_fare          AS has_fare,
               cr.route_type        AS route_type,
               b.`{b['burden_type']}` AS burden_type,
               t.`{t['type_name']}`   AS dong_type
        FROM `{r['table']}` r
        LEFT JOIN dim_dong_reliability rel ON rel.dong_code8 = r.`{r['code']}`
        LEFT JOIN `{b['table']}` b         ON b.`{b['code']}` = r.`{r['code']}`
        LEFT JOIN fact_commute_route cr    ON cr.home_code8  = r.`{r['code']}`
                                          AND cr.work_code8  = %s
        LEFT JOIN `{t['table']}` t         ON t.`{t['code']}` = r.`{r['code']}`
                                          AND t.`{t['k']}`    = {K_VALUE}
        WHERE r.`{r['code']}` = %s
    """


def _derive(row):
    """경로 한 건에서 월 단위 파생값을 만든다.
    시간가치 가정을 테이블에 박지 않기로 해서 여기서 계산한다."""
    mn = _num(row.get("commute_min"))
    hours = round(mn * 2 * WORK_DAYS_PER_MONTH / 60, 2) if mn is not None else None
    time_value = round(hours * TIME_VALUE_PER_HOUR) if hours is not None else None

    f = _num(row.get("oneway_fare"))
    if f is None or not row.get("has_fare"):
        # 내부통근은 요금이 산출되지 않는다. 걸어가는 거리라 0원으로 본다.
        fare_actual = 0 if str(row.get("route_type") or "").startswith("내부통근") else None
    else:
        fare_actual = f * 2 * WORK_DAYS_PER_MONTH
    fare_pass = min(fare_actual, TRANSIT_PASS_CAP) if fare_actual is not None else None
    fare = fare_pass if FARE_MODE == "pass" else fare_actual

    housing = _num(row.get("housing_cost"))
    total = None
    if None not in (housing, fare, time_value):
        total = housing + fare + time_value
    return {
        "housing_cost": housing,
        "oneway_km": _num(row.get("oneway_km")),
        "route_lines": row.get("route_lines"),
        "mode_sequence": row.get("mode_sequence"),
        "oneway_fare": f,
        "fare": fare,
        "fare_actual": fare_actual,
        "fare_pass": fare_pass,
        "fare_mode": FARE_MODE,
        "time_value": time_value,
        "monthly_commute_hour": hours,
        "total": total,
        "commute_min": mn,
        "transfer": _num(row.get("transfer")),
        "work_days": WORK_DAYS_PER_MONTH,
    }


def _fallback_sql():
    r, b = COLS["region"], COLS["burden"]
    fare = _fare_col()
    return f"""
        SELECT cr.`{r['code']}` AS code,
               cr.`{r['name']}` AS name,
               c.shared_bjd_name AS shared_bjd,
               ( b.`{b['housing']}` + b.`{fare}`
                 + ROUND(b.`{b['commute_hour']}` * {TIME_VALUE_PER_HOUR}) ) AS total,
               b.`{b['commute_min']}` AS commute_min,
               rel.tx_count           AS tx_count
        FROM dim_fallback_candidate c
        JOIN `{r['table']}` cr ON cr.`{r['code']}` = c.candidate_dong_code
        JOIN `{b['table']}` b  ON b.`{b['code']}`  = c.candidate_dong_code
        LEFT JOIN dim_dong_reliability rel ON rel.dong_code8 = c.candidate_dong_code
        WHERE c.missing_dong_code = %s
        ORDER BY c.display_order
    """


def get_dong(dong_code, conn=None, work_code=DEFAULT_WORK_DONG):
    """행정동코드 하나를 조회해 응답 계약 형태로 돌려준다.

    work_code 를 주면 그 근무지 기준 경로(fact_commute_route)를 쓴다.
    None 을 주면 거주동 전체 평균(fact_dong_burden)을 쓰는데,
    "이 직장까지 몇 분" 화면에서는 쓰면 안 된다.
    """
    own = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
            if work_code:
                cur.execute(_route_sql(), (work_code, dong_code))
            else:
                cur.execute(_burden_sql(), (dong_code,))
            row = cur.fetchone()
            if not row:
                return {"status": "not_found", "dong": {"code": dong_code}}

            dong = {"code": row["code"], "name": row["name"], "gu": row["gu"]}
            status = row["status"] or "ok"

            if status == "no_data":
                cur.execute(_fallback_sql(), (dong_code,))
                alts = cur.fetchall()
                return {
                    "status": "no_data",
                    "dong": dong,
                    "reason": REASON_TEXT["no_data"],
                    "shared_bjd": alts[0]["shared_bjd"] if alts else None,
                    "alternatives": [
                        {"code": a["code"], "name": a["name"], "total": _num(a["total"]),
                         "commute_min": _num(a["commute_min"]), "tx_count": _num(a["tx_count"])}
                        for a in alts
                    ],
                }

            if work_code:
                if not row.get("has_route"):
                    return {"status": "no_route", "dong": dong, "work_code": work_code,
                            "reason": "이 지역에서 해당 근무지로 가는 경로 데이터가 없습니다."}
                burden = _derive(row)
                burden["work_code"] = work_code
            else:
                burden = {
                    "housing_cost": _num(row["housing_cost"]),
                    "fare": _num(row["fare"]),
                    "fare_actual": _num(row["fare_actual"]),
                    "fare_pass": _num(row["fare_pass"]),
                    "fare_mode": FARE_MODE,
                    "time_value": _num(row["time_value"]),
                    "total": _num(row["total"]),
                    "commute_min": _num(row["commute_min"]),
                }
            res = {
                "status": status,
                "dong": dong,
                "burden": burden,
                "burden_type": row["burden_type"],
                "dong_type": row["dong_type"],
                "tx_count": _num(row["tx_count"]),
            }
            if status == "unreliable":
                res["warning"] = REASON_TEXT["unreliable"]
            elif status == "low_confidence":
                res["notice"] = REASON_TEXT["low_confidence"]
                res["reasons"] = (row["reason"] or "").split(" / ")
            return res
    finally:
        if own:
            conn.close()


def nearest_routed_work(home_code, work_code, conn=None):
    """요청한 근무동으로 가는 경로가 없을 때, 대신 쓸 인근 근무동을 찾는다.

    경로는 거주동별 누적 80% 목적지만 수집해서 흐름이 적은 조합은 빠져 있다.
    그렇다고 "자료 없음"으로 끝내면 다섯 중 한 명은 아무 결과도 못 본다.
    같은 자치구 -> 같은 권역 순으로 경로가 있는 근무동을 찾아 대체하고,
    무엇으로 대체했는지 호출한 쪽에 돌려준다. 화면에 반드시 밝혀야 한다.

    같은 구 안에서는 통근 방향과 소요시간이 크게 다르지 않다는 가정이며,
    정확한 값이 필요하면 그 조합을 직접 조회해야 한다.
    """
    own = conn is None
    conn = conn or connect()
    r = COLS["region"]
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT `{r['gu']}` AS gu, `{r['name']}` AS name "
                f"FROM `{r['table']}` WHERE `{r['code']}` = %s", (str(work_code),))
            want = cur.fetchone()
            if not want:
                return None

            # 1순위 같은 자치구, 2순위 같은 권역. 각 후보는 이동량 많은 순.
            for clause, params in (
                (f"r.`{r['gu']}` = %s", (str(home_code), want["gu"])),
                (f"r.`{r['gu']}` <> %s", (str(home_code), want["gu"])),
            ):
                cur.execute(
                    f"SELECT cr.work_code8 AS code, r.`{r['name']}` AS name, "
                    f"r.`{r['gu']}` AS gu "
                    "FROM fact_commute_route cr "
                    f"JOIN `{r['table']}` r ON r.`{r['code']}` = cr.work_code8 "
                    "LEFT JOIN fact_commute_od od "
                    "  ON od.home_code8 = cr.home_code8 AND od.work_code8 = cr.work_code8 "
                    "WHERE cr.home_code8 = %s AND cr.oneway_min IS NOT NULL "
                    f"  AND {clause} "
                    "ORDER BY COALESCE(od.flow, 0) DESC LIMIT 1",
                    params,
                )
                hit = cur.fetchone()
                if hit:
                    hit["requested_name"] = want["name"]
                    hit["same_gu"] = (hit["gu"] == want["gu"])
                    return hit
            return None
    except Exception:
        return None
    finally:
        if own:
            conn.close()


def recommend_dongs(work_code, exclude=(), limit=3, work_days=WORK_DAYS_PER_MONTH,
                    conn=None):
    """그 근무지로 통근 가능한 거주동 중 월 총부담이 낮은 곳을 추천한다.

    같은 유형이 연달아 나오면 선택지가 사실상 하나가 되므로 행정동 유형별로
    한 곳씩만 남긴다. 총부담은 화면과 같은 산식(주거비 + 정기권 교통비 +
    통근시간 가치)으로 여기서 계산한다. 테이블에는 시간가치 가정을 넣지 않았다.
    """
    own = conn is None
    conn = conn or connect()
    r, b, t = COLS["region"], COLS["burden"], COLS["dtype"]
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT r.`{r['code']}` AS code, r.`{r['name']}` AS name, "
                f"r.`{r['gu']}` AS gu, b.`{b['housing']}` AS housing, "
                "cr.oneway_min AS commute_min, cr.fare AS oneway_fare, "
                f"cr.transfer_cnt AS transfer, t.`{t['type_name']}` AS dong_type, "
                "rel.status AS status "
                "FROM fact_commute_route cr "
                f"JOIN `{r['table']}` r ON r.`{r['code']}` = cr.home_code8 "
                f"JOIN `{b['table']}` b ON b.`{b['code']}` = cr.home_code8 "
                f"LEFT JOIN `{t['table']}` t ON t.`{t['code']}` = cr.home_code8 "
                f"                          AND t.`{t['k']}` = {K_VALUE} "
                "LEFT JOIN dim_dong_reliability rel ON rel.dong_code8 = cr.home_code8 "
                "WHERE cr.work_code8 = %s AND cr.home_code8 <> cr.work_code8 "
                "  AND cr.oneway_min IS NOT NULL AND cr.fare IS NOT NULL "
                f"  AND b.`{b['housing']}` IS NOT NULL",
                (str(work_code),),
            )
            rows = cur.fetchall()
    except Exception:
        return []
    finally:
        if own:
            conn.close()

    skip = {str(x) for x in exclude if x}
    out = []
    for row in rows:
        if str(row["code"]) in skip:
            continue
        # 표본이 부실한 동은 추천으로 내세우지 않는다. 참고용 딱지가 붙은 값을
        # "여기가 더 낫습니다"로 제시하면 안 된다.
        if row.get("status") in ("no_data", "unreliable"):
            continue
        mn, f, h = _num(row["commute_min"]), _num(row["oneway_fare"]), _num(row["housing"])
        if None in (mn, f, h):
            continue
        fare = min(f * 2 * work_days, TRANSIT_PASS_CAP)
        time_value = round(mn * 2 * work_days / 60 * TIME_VALUE_PER_HOUR)
        out.append({**row, "fare": fare, "time_value": time_value,
                    "commute_min": mn, "total": h + fare + time_value,
                    "housing": h})

    out.sort(key=lambda x: x["total"])
    picked, seen = [], set()
    for row in out:
        key = row.get("dong_type") or f"__{row['code']}"
        if key in seen:
            continue
        seen.add(key)
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def list_home_options(work_code, limit=20, q=None, conn=None):
    """그 근무지로 통근 경로가 있는 거주동을 이동량 많은 순으로 돌려준다.

    대안 탐색에서 후보 거주지를 입력받을 때 쓴다. 전체 행정동을 열어두면
    경로가 없는 동을 고르게 되고, 결과 화면에서야 실패를 알게 된다.
    """
    own = conn is None
    conn = conn or connect()
    r = COLS["region"]
    try:
        with conn.cursor() as cur:
            sql = (
                f"SELECT cr.home_code8 AS code, r.`{r['name']}` AS name, "
                f"r.`{r['gu']}` AS gu "
                "FROM fact_commute_route cr "
                f"JOIN `{r['table']}` r ON r.`{r['code']}` = cr.home_code8 "
                "LEFT JOIN fact_commute_od od "
                "  ON od.home_code8 = cr.home_code8 AND od.work_code8 = cr.work_code8 "
                "WHERE cr.work_code8 = %s AND cr.home_code8 <> cr.work_code8"
            )
            params = [str(work_code)]
            if q:
                sql += (f" AND (REPLACE(r.`{r['name']}`, '제', '') LIKE REPLACE(%s, '제', '') "
                        f"      OR r.`{r['gu']}` LIKE %s)")
                params += [f"%{q}%", f"%{q}%"]
            sql += " ORDER BY COALESCE(od.flow, 0) DESC LIMIT %s"
            params.append(int(limit))
            cur.execute(sql, tuple(params))
            return cur.fetchall()
    except Exception:
        return []
    finally:
        if own:
            conn.close()


def list_work_options(home_code, limit=6, q=None, conn=None):
    """그 거주동에서 경로 데이터가 있는 근무동을 이동량 많은 순으로 돌려준다.

    fact_commute_route 는 거주동별 누적 80% 목적지만 Tmap 호출한 결과라
    427x427 조합이 다 있지 않다(거주동당 평균 72곳, 약 17%). 근무지 자동완성을
    전체 행정동으로 열어두면 사용자가 없는 조합을 고르게 되므로, 갈 수 있는 곳만
    제안하는 데 쓴다. q 를 주면 부분일치로 좁힌다.
    """
    own = conn is None
    conn = conn or connect()
    r = COLS["region"]
    try:
        with conn.cursor() as cur:
            sql = (
                f"SELECT cr.work_code8 AS code, r.`{r['name']}` AS name, "
                f"r.`{r['gu']}` AS gu "
                "FROM fact_commute_route cr "
                f"JOIN `{r['table']}` r ON r.`{r['code']}` = cr.work_code8 "
                "LEFT JOIN fact_commute_od od "
                "  ON od.home_code8 = cr.home_code8 AND od.work_code8 = cr.work_code8 "
                "WHERE cr.home_code8 = %s AND cr.work_code8 <> cr.home_code8"
            )
            params = [str(home_code)]
            if q:
                # '창신1동'과 '창신제1동' 표기 차이를 흡수한다(get_dong_by_name 과 같은 규칙)
                sql += (f" AND (REPLACE(r.`{r['name']}`, '제', '') LIKE REPLACE(%s, '제', '') "
                        f"      OR r.`{r['gu']}` LIKE %s)")
                params += [f"%{q}%", f"%{q}%"]
            sql += " ORDER BY COALESCE(od.flow, 0) DESC LIMIT %s"
            params.append(int(limit))
            cur.execute(sql, tuple(params))
            return cur.fetchall()
    except Exception:
        return []
    finally:
        if own:
            conn.close()


def list_dongs(q=None, limit=20, conn=None):
    """행정동 목록을 돌려준다. 입력 자동완성용.

    q 가 있으면 부분일치로 거른다. "창신1동"과 "창신제1동"처럼 '제' 유무로
    표기가 갈리므로 양쪽에서 '제'를 뺀 뒤 비교한다(get_dong_by_name 과 같은 규칙).
    q 가 없으면 전체를 자치구·동명 순으로 돌려준다.
    """
    own = conn is None
    conn = conn or connect()
    r = COLS["region"]
    try:
        with conn.cursor() as cur:
            base = (f"SELECT `{r['code']}` AS code, `{r['name']}` AS name, "
                    f"`{r['gu']}` AS gu FROM `{r['table']}`")
            order = f" ORDER BY `{r['gu']}`, `{r['name']}`"
            if q:
                cur.execute(
                    base
                    + f" WHERE REPLACE(`{r['name']}`, '제', '') LIKE REPLACE(%s, '제', '')"
                      f" OR `{r['gu']}` LIKE %s"
                    + order + " LIMIT %s",
                    (f"%{q}%", f"%{q}%", int(limit)),
                )
            else:
                cur.execute(base + order + " LIMIT %s", (int(limit),))
            return cur.fetchall()
    finally:
        if own:
            conn.close()


def get_dong_by_name(name, conn=None, work_code=DEFAULT_WORK_DONG):
    """행정동명으로 조회. 여러 개면 ambiguous 를 돌려준다."""
    own = conn is None
    conn = conn or connect()
    r = COLS["region"]
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT `{r['code']}` AS code, `{r['name']}` AS name, `{r['gu']}` AS gu "
                f"FROM `{r['table']}` WHERE REPLACE(`{r['name']}`, '제', '') = REPLACE(%s, '제', '')",
                (name,),
            )
            hits = cur.fetchall()
        if not hits:
            return {"status": "not_found", "query": name}
        if len(hits) > 1:
            return {"status": "ambiguous", "query": name,
                    "query_type": "행정동", "candidates": hits}
        return get_dong(hits[0]["code"], conn=conn, work_code=work_code)
    finally:
        if own:
            conn.close()


# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--env" in sys.argv:
        env_check()
    elif "--inspect" in sys.argv:
        inspect()
    elif "--list" in sys.argv:
        i = sys.argv.index("--list")
        q = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        rows = list_dongs(q, limit=500)
        print(f"{len(rows)}건")
        for row in rows[:50]:
            print(f"  {row['code']} {row['gu']} {row['name']}")
    elif len(sys.argv) > 1:
        key = sys.argv[1]
        out = get_dong(key) if key.isdigit() else get_dong_by_name(key)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(__doc__)