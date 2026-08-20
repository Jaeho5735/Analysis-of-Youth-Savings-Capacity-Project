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
    "fact_dong_burden", "fact_dong_type", "fact_dong_type_features",
    "fact_commute_od", "fact_commute_route", "fact_rent_transaction",
    "dim_policy",
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


# 정책 조건표 정규화. 엑셀 원본을 직접 넣을 때만 쓴다(정제 CSV가 있으면 그쪽 우선).
_ANNUAL_INCOME = {"햇살론유스", "청년미래적금", "전세보증금 반환보증 보증료 지원"}
_CATEGORY_FIX = {"K-패스": "transport", "서울 청년수당 지원": "living_subsidy"}
_BENEFIT_UNIT = {
    "서울시 청년 월세 지원": "month", "청년월세 지원사업": "month",
    "청년 부동산 중개보수 및 이사비 지원": "once", "서울 청년수당 지원": "month",
    "햇살론유스": "limit", "희망두배 청년통장": "month",
    "자산형성지원사업(청년내일저축계좌)": "month", "청년미래적금": "month",
    "전세보증금 반환보증 보증료 지원": "once", "전세보증금반환보증": "limit",
}
_BURDEN_TAG = {1: "높은 월세 부담", 2: "높은 보증금 부담", 3: "높은 통근 교통비",
               4: "낮은 현금흐름 잔여액", 5: "자산형성 여력", 6: "보증금 반환 위험"}


def normalize_policy(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["income_period_src"] = d["policy_name"].apply(
        lambda n: "year" if n in _ANNUAL_INCOME else "month")
    d["income_max"] = d.apply(
        lambda r: round(r["income_max"] / 12)
        if r["income_period_src"] == "year" and pd.notna(r["income_max"]) else r["income_max"],
        axis=1)
    d["category"] = d.apply(
        lambda r: _CATEGORY_FIX.get(r["policy_name"], r["category"]), axis=1)
    d["benefit_unit"] = d["policy_name"].map(_BENEFIT_UNIT)
    d["burden_tag_name"] = d["burden_tag"].map(_BURDEN_TAG)
    return d


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

    # 청년1인세대비율은 유형화 산출물에서 가져온다(군집 변수는 아니고 사후해석용)
    youth_src = read("dong_typology_final.csv")
    youth_src["dong_code8"] = code10_to_8(youth_src["행정동코드"])
    youth = youth_src[["dong_code8", "청년1인세대_비율"]]

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

    # 4. fact_dong_type + features (dong_typology_final.csv, 427행)
    #    팀원A의 FuzzyCMeans k=6 결과. 427행 전체를 넣고 유형 없는 7개 동은
    #    type_name NULL + flag_insufficient=1 로 남긴다. 빼면 서비스에서
    #    "데이터 부족"인지 "코드 오류"인지 구분할 수 없다.
    print("[fact_dong_type]")
    typo = read("dong_typology_final.csv")
    typo["dong_code8"] = code10_to_8(typo["행정동코드"])
    typo = quarantine(typo, typo["dong_code8"].isin(valid), "fact_dong_type", None)

    fact_type = pd.DataFrame({
        "dong_code8": typo["dong_code8"],
        "k_value": 6,
        "cluster_id": typo["군집"],
        "type_name": typo["행정동_유형"],
        "max_membership": typo["최대소속확률"],
        # 데이터 부족 동은 경계 판정 자체가 없으므로 0 으로 채운다
        "flag_boundary": typo["군집경계_모호"].fillna(False).astype(bool).astype(int),
        "flag_insufficient": typo["유형화_데이터부족"].fillna(False).astype(bool).astype(int),
        "missing_count": typo["유형화_결측수"].fillna(0).astype(int),
        "missing_columns": typo["유형화_결측목록"],
    })
    insert(eng, fact_type, "fact_dong_type")

    print("[fact_dong_type_features]")
    feat = pd.DataFrame({
        "dong_code8": typo["dong_code8"],
        "surface_housing_cost": typo["표면주거비_원"],
        "txn_count": typo["표면주거비_거래수"],
        "oneway_commute_min": typo["대표_편도통근시간_분"],
        "monthly_transport_cost": typo["월통근교통비_원"],
        "zone_internal_ratio": typo["동일통근권_내부출근비율"],
        "dest_entropy": typo["목적지_정규화엔트로피"],
        "dest_hhi": typo["목적지_HHI"],
        "youth_single_ratio": typo["청년1인세대_비율"],
    })
    insert(eng, feat, "fact_dong_type_features")

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

    # 8. dim_policy (팀원B 조건표)
    #    엑셀 원본을 그대로 넣지 않고 세 가지를 정규화한다.
    #      ① 연소득 기준 3건을 12로 나눠 월 기준으로 통일
    #      ② 교통·생활 지원이 housing_subsidy로 들어와 있어 재분류
    #      ③ 지원액 단위(월/1회/한도)가 섞여 있어 benefit_unit 신설
    print("[dim_policy]")
    pol_path = next((p for p in [DATA_DIR / "정책_조건표_정제.csv",
                                 DATA_DIR / "서울_청년_1인가구_정책_조건표.xlsx"] if p.exists()), None)
    if pol_path is None:
        print("  ! 정책 조건표 없음 - dim_policy 건너뜀\n")
    else:
        pol = (pd.read_csv(pol_path, encoding="utf-8-sig") if pol_path.suffix == ".csv"
               else normalize_policy(pd.read_excel(pol_path)))
        keep = ["policy_name", "provider", "burden_tag", "burden_tag_name", "category",
                "age_min", "age_max", "income_max", "income_period_src", "rent_max",
                "benefit_amount", "benefit_unit", "source_url"]
        insert(eng, pol[keep], "dim_policy")

    print("적재 완료. sql/02_qc.sql 실행할 것.")


if __name__ == "__main__":
    main()