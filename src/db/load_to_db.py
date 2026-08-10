"""
MULTICAM_PROJECT : CSV -> MySQL 적재 (v2, 실제 파일 구조 반영)

실행 순서: dim_region -> dim_business_district/bridge -> fact_dong_burden
          -> fact_dong_type -> fact_commute_od -> fact_commute_route
          -> fact_rent_transaction

환경변수: MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DB
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "data"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "quarantine"

LOAD_ORDER = [
    "dim_region", "dim_business_district", "bridge_district_dong",
    "fact_dong_burden", "fact_dong_type",
    "fact_commute_od", "fact_commute_route", "fact_rent_transaction",
]


def engine():
    for k in ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB"):
        if not os.getenv(k):
            sys.exit(f"[중단] 환경변수 {k} 없음")
    url = (f"mysql+pymysql://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}"
           f"@{os.getenv('MYSQL_HOST','localhost')}:{os.getenv('MYSQL_PORT','3306')}"
           f"/{os.getenv('MYSQL_DB')}?charset=utf8mb4")
    return create_engine(url, pool_pre_ping=True)


def read(name: str, **kw) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        sys.exit(f"[중단] 파일 없음: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig", **kw)
    print(f"  읽음 {name}: {len(df):,}행")
    return df


def code10_to_8(series: pd.Series) -> pd.Series:
    """1111065000.0 형태의 실수/문자 코드10을 정수->10자리 문자열->앞8자리로."""
    return series.astype(float).astype("int64").astype(str).str.zfill(10).str[:8]


def truncate_all(eng):
    with eng.begin() as c:
        c.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in reversed(LOAD_ORDER):
            c.execute(text(f"TRUNCATE TABLE {t}"))
        c.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    print("기존 데이터 비움\n")


def insert(eng, df: pd.DataFrame, table: str):
    df.to_sql(table, eng, if_exists="append", index=False, chunksize=2000, method="multi")
    print(f"  -> {table} {len(df):,}행 적재\n")


def quarantine(df: pd.DataFrame, mask: pd.Series, table: str, key_col):
    if (~mask).any():
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        out = QUARANTINE_DIR / f"{table}_orphan.csv"
        df[~mask].to_csv(out, index=False, encoding="utf-8-sig")
        print(f"  ! 기준표 미등재 {(~mask).sum():,}행 격리 -> {out.name}")
    return df[mask].copy()


def main():
    eng = engine()
    truncate_all(eng)

    # 1. dim_region
    print("[dim_region]")
    r = read("행정동_기준코드표.csv")
    dim_region = pd.DataFrame({
        "dong_code8": r["행정동코드8"].astype(str).str.zfill(8),
        "dong_code10": r["행정동코드10"].astype(str).str.zfill(10),
        "sigungu_name": r["시군구명"],
        "dong_name": r["행정동명"],
        "region_group": r["권역"],
        "created_date": pd.to_datetime(r["생성일자"].astype(str), format="%Y%m%d", errors="coerce"),
    })
    insert(eng, dim_region, "dim_region")
    valid = set(dim_region["dong_code8"])

    # 2. dim_business_district + bridge (업무지구_정의.csv 40행, 지구별 그룹)
    print("[dim_business_district / bridge_district_dong]")
    bd = read("업무지구_정의.csv")
    bd["dong_code8"] = bd["행정동코드8"].astype(str).str.zfill(8)
    bd = quarantine(bd, bd["dong_code8"].isin(valid), "bridge_district_dong", None)

    total_inflow = bd["출근_유입량"].sum()
    districts = (bd.groupby("업무지구")
                   .agg(inflow=("출근_유입량", "sum"), dong_count=("dong_code8", "count"))
                   .reset_index())
    districts["inflow_share"] = (districts["inflow"] / total_inflow * 100).round(3)
    dim_bd = districts.rename(columns={"업무지구": "district_name"})[
        ["district_name", "inflow_share", "dong_count"]]
    insert(eng, dim_bd, "dim_business_district")

    # district_id 매핑을 DB에서 다시 읽어와야 함(AUTO_INCREMENT)
    id_map = pd.read_sql("SELECT district_id, district_name FROM dim_business_district", eng)
    bridge = bd.merge(id_map, left_on="업무지구", right_on="district_name")[
        ["district_id", "dong_code8", "지구내_가중치", "출근_유입량"]
    ].rename(columns={"지구내_가중치": "weight", "출근_유입량": "inflow"})
    insert(eng, bridge, "bridge_district_dong")

    # 3. fact_dong_burden (통합부담 + 업무중심성 + 유형화의 청년비율 병합)
    print("[fact_dong_burden]")
    burden = read("주거통근_통합부담_행정동별.csv")
    burden["dong_code8"] = burden["행정동코드8"].astype(str).str.zfill(8)

    center = read("업무중심성_행정동별.csv")
    center["dong_code8"] = center["행정동코드8"].astype(str).str.zfill(8)
    center = center[["dong_code8", "주야간_인구비", "업무중심"]]

    typ = read("행정동_유형화_결과.csv")
    typ["dong_code8"] = typ["행정동코드8"].astype(str).str.zfill(8)
    youth = typ[["dong_code8", "청년1인세대_비율"]]

    m = burden.merge(center, on="dong_code8", how="left").merge(youth, on="dong_code8", how="left")
    m = quarantine(m, m["dong_code8"].isin(valid), "fact_dong_burden", None)

    fact_burden = pd.DataFrame({
        "dong_code8": m["dong_code8"],
        "surface_housing_cost": m["표면주거비_원"],
        "consumption_index": m["생활소비부담지수"],
        "oneway_commute_min": m["대표_편도통근시간_분"],
        "monthly_commute_hour": m["월_통근시간_시간"],
        "monthly_transport_cost": m["월교통비_실지출_원"],
        "monthly_transport_pass": m["월교통비_정기권_원"],
        "internal_commute_ratio": m["내부통근비중"],
        "zone_internal_ratio": m["동일통근권_내부출근비율"],
        "dest_entropy": m["목적지_정규화엔트로피"],
        "youth_single_ratio": m["청년1인세대_비율"] / 100,
        "inflow_outflow_ratio": m["출근_유입유출비"],
        "day_night_pop_ratio": m["주야간_인구비"],
        "is_business_center": m["업무중심"].fillna(False).astype(int),
        "flag_small_sample": m["표본부족"].fillna(False).astype(int),
        "flag_few_industry": m["업종부족"].fillna(False).astype(int),
        "flag_low_fare_coverage": m["교통비_커버리지부족"].fillna(False).astype(int),
        "rank_housing_src": m["순위_주거비"],
        "rank_burden_src": m["순위_통합부담"],
        "burden_type_src": m["부담유형"],
    })
    insert(eng, fact_burden, "fact_dong_burden")

    # 4. fact_dong_type
    print("[fact_dong_type]")
    fact_type = pd.DataFrame({
        "dong_code8": typ["dong_code8"],
        "k_value": 7,
        "cluster_id": typ["군집"],
        "type_name": typ["행정동_유형"],
        "assign_method": typ["군집_사후배정"].map({True: "post", False: "train"}),
        # 입력 변수 자체가 없어 학습 평균으로 메워 배정된 동. 서비스에서 참고용 표시가 필요하다.
        "flag_imputed": (typ["유형_결측대입"].fillna(False).astype(int)
                         if "유형_결측대입" in typ.columns else 0),
    })
    fact_type = quarantine(fact_type, fact_type["dong_code8"].isin(valid), "fact_dong_type", None)
    insert(eng, fact_type, "fact_dong_type")

    # 5. fact_commute_od (전체 + 80%컷 병합)
    print("[fact_commute_od]")
    od_all = read("all_age_commute_od_aggregated.csv")
    od_all["home_code8"] = od_all["거주동 코드"].astype(str).str.zfill(8)
    od_all["work_code8"] = od_all["근무동 코드"].astype(str).str.zfill(8)

    od_top = read("all_age_commute_od_selected_80.csv")
    od_top["home_code8"] = od_top["거주동 코드"].astype(str).str.zfill(8)
    od_top["work_code8"] = od_top["근무동 코드"].astype(str).str.zfill(8)
    od_top["is_top80"] = 1

    od = od_all.merge(
        od_top[["home_code8", "work_code8", "is_top80", "목적지_순위", "최종_가중치"]],
        on=["home_code8", "work_code8"], how="left")
    od["is_top80"] = od["is_top80"].fillna(0).astype(int)
    od["is_internal"] = (od["home_code8"] == od["work_code8"]).astype(int)

    od = quarantine(od, od["home_code8"].isin(valid) & od["work_code8"].isin(valid),
                     "fact_commute_od", None)
    fact_od = pd.DataFrame({
        "home_code8": od["home_code8"], "work_code8": od["work_code8"],
        "flow": od["출근_이동량"], "obs_time_min": od["평균_이동시간_분"],
        "obs_dist_km": od["평균_이동거리_km"], "is_internal": od["is_internal"],
        "is_top80": od["is_top80"], "dest_rank": od["목적지_순위"],
        "final_weight": od["최종_가중치"],
    })
    insert(eng, fact_od, "fact_commute_od")

    # 6. fact_commute_route
    print("[fact_commute_route]")
    rt = read("commute_routes_analysis_ready.csv")
    rt["home_code8"] = rt["거주동 코드"].astype(str).str.zfill(8)
    rt["work_code8"] = rt["근무동 코드"].astype(str).str.zfill(8)
    rt = quarantine(rt, rt["home_code8"].isin(valid) & rt["work_code8"].isin(valid),
                     "fact_commute_route", None)
    fact_route = pd.DataFrame({
        "home_code8": rt["home_code8"], "work_code8": rt["work_code8"],
        "oneway_min": rt["분석용_편도시간_분"], "oneway_km": rt["분석용_편도거리_km"],
        "fare": rt["분석용_편도요금_원"], "fare_method": rt["요금산출방식"],
        "walk_min": rt["총도보시간_분"], "walk_ratio": rt["도보시간비중"],
        "transfer_cnt": rt["환승횟수"], "bus_legs": rt["버스_이용구간수"],
        "subway_legs": rt["지하철_이용구간수"], "walk_legs": rt["도보_구간수"],
        "mode_sequence": rt["교통수단_순서"], "route_lines": rt["이용노선"],
        "route_type": rt["최종경로유형"],
        "has_route": rt["경로정보존재여부"].fillna(False).astype(int),
        "has_fare": rt["요금정보존재여부"].fillna(False).astype(int),
    })
    insert(eng, fact_route, "fact_commute_route")

    # 7. fact_rent_transaction (표면주거비_거래단위.csv, 이미 표면주거비 계산됨)
    print("[fact_rent_transaction]")
    txn = read("표면주거비_거래단위.csv", low_memory=False)
    txn = txn[txn["행정동코드_최종"].notna()].copy()
    txn["dong_code8"] = code10_to_8(txn["행정동코드_최종"])
    txn = quarantine(txn, txn["dong_code8"].isin(valid), "fact_rent_transaction", None)

    # 보증금(만원)에 천단위 콤마("1,000")가 섞여 있어 문자열로 읽힌다.
    # 그대로 * 10000을 하면 파이썬 문자열 반복(str * int)이 실행돼 MemoryError가 난다.
    deposit_manwon = pd.to_numeric(
        txn["보증금(만원)"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    if deposit_manwon.isna().any():
        sys.exit(f"[중단] 보증금(만원) 숫자 변환 실패 {deposit_manwon.isna().sum():,}행")

    # 월세금도 같은 CSV의 같은 위험(천단위 콤마 -> 문자열)을 갖는다.
    rent_manwon = pd.to_numeric(
        txn["월세금(만원)"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    if rent_manwon.isna().any():
        sys.exit(f"[중단] 월세금(만원) 숫자 변환 실패 {rent_manwon.isna().sum():,}행")

    fact_txn = pd.DataFrame({
        "dong_code8": txn["dong_code8"],
        "contract_ym": txn["계약년월"].astype(str),
        "deposit_krw": (deposit_manwon * 10000).astype("int64"),
        "rent_krw": (rent_manwon * 10000).astype("int64"),
        "area_m2": txn["면적"],
        "housing_type": txn["주택유형"],
        "contract_type": txn["계약구분"],
        "surface_housing_cost": txn["표면_주거비"] * 10000,
        "flag_small_area": txn["초소형_추정"].fillna(False).astype(int),
        "flag_small_sample_dong": txn["표본부족_행정동"].fillna(False).astype(int),
    })
    insert(eng, fact_txn, "fact_rent_transaction")

    print("적재 완료. sql/02_analysis_queries.sql 의 QC1~QC4 실행할 것.")


if __name__ == "__main__":
    main()