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


def get_dong(dong_code, conn=None):
    """행정동코드 하나를 조회해 응답 계약 형태로 돌려준다."""
    own = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
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

            res = {
                "status": status,
                "dong": dong,
                "burden": {
                    "housing_cost": _num(row["housing_cost"]),
                    "fare": _num(row["fare"]),
                    "fare_actual": _num(row["fare_actual"]),
                    "fare_pass": _num(row["fare_pass"]),
                    "fare_mode": FARE_MODE,
                    "time_value": _num(row["time_value"]),
                    "total": _num(row["total"]),
                    "commute_min": _num(row["commute_min"]),
                },
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


def get_dong_by_name(name, conn=None):
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
        return get_dong(hits[0]["code"], conn=conn)
    finally:
        if own:
            conn.close()


# ═════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "--env" in sys.argv:
        env_check()
    elif "--inspect" in sys.argv:
        inspect()
    elif len(sys.argv) > 1:
        key = sys.argv[1]
        out = get_dong(key) if key.isdigit() else get_dong_by_name(key)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(__doc__)