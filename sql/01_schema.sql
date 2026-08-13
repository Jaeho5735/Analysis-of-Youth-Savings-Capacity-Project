-- =====================================================================
-- MULTICAM_PROJECT : 01_schema.sql (v2 - 실제 CSV 구조 반영)
-- =====================================================================
CREATE DATABASE IF NOT EXISTS multicam
  DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci;
USE multicam;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS fact_rent_transaction;
DROP TABLE IF EXISTS fact_commute_route;
DROP TABLE IF EXISTS fact_commute_od;
DROP TABLE IF EXISTS fact_dong_type_features;
DROP TABLE IF EXISTS fact_dong_type;
DROP TABLE IF EXISTS fact_dong_burden;
DROP TABLE IF EXISTS bridge_district_dong;
DROP TABLE IF EXISTS dim_business_district;
DROP TABLE IF EXISTS dim_policy;
DROP TABLE IF EXISTS dim_income_scenario;
DROP TABLE IF EXISTS dim_time_value;
DROP TABLE IF EXISTS dim_living_cost_assumption;
DROP TABLE IF EXISTS map_region_legacy;
DROP TABLE IF EXISTS dim_region;
SET FOREIGN_KEY_CHECKS = 1;

-- 행정동 기준표 (427행)
CREATE TABLE dim_region (
    dong_code8     CHAR(8)     NOT NULL,
    dong_code10    CHAR(10)    NOT NULL,
    sigungu_name   VARCHAR(20) NOT NULL,
    dong_name      VARCHAR(40) NOT NULL,
    region_group   VARCHAR(10) NOT NULL COMMENT '도심권/동남권/동북권/서남권/서북권',
    created_date   DATE            NULL,
    PRIMARY KEY (dong_code8),
    UNIQUE KEY uk_region_code10 (dong_code10)
) ENGINE=InnoDB;

CREATE TABLE map_region_legacy (
    legacy_code8   CHAR(8)     NOT NULL,
    current_code8  CHAR(8)     NOT NULL,
    legacy_name    VARCHAR(40)     NULL,
    relation_type  VARCHAR(20)     NULL COMMENT '1:N 분동 등',
    note           VARCHAR(200)    NULL,
    PRIMARY KEY (legacy_code8, current_code8)
) ENGINE=InnoDB;

-- 파라미터 (가정을 데이터로 분리)
CREATE TABLE dim_time_value (
    time_value_code VARCHAR(20) NOT NULL,
    label           VARCHAR(40) NOT NULL,
    hourly_wage     INT         NOT NULL,
    is_default      TINYINT(1)  NOT NULL DEFAULT 0,
    source_note     VARCHAR(100)    NULL,
    PRIMARY KEY (time_value_code)
) ENGINE=InnoDB;

CREATE TABLE dim_income_scenario (
    income_code        VARCHAR(20) NOT NULL,
    label              VARCHAR(40) NOT NULL,
    monthly_net_income INT         NOT NULL,
    PRIMARY KEY (income_code)
) ENGINE=InnoDB;

CREATE TABLE dim_living_cost_assumption (
    assumption_code VARCHAR(20) NOT NULL,
    label           VARCHAR(40) NOT NULL,
    base_amount     INT         NOT NULL,
    index_slope     INT         NOT NULL,
    source_note     VARCHAR(200)    NULL,
    PRIMARY KEY (assumption_code)
) ENGINE=InnoDB;

-- 업무지구 (지구 40행은 bridge에서 GROUP BY로 집계해 만든다)
CREATE TABLE dim_business_district (
    district_id   SMALLINT    NOT NULL AUTO_INCREMENT,
    district_name VARCHAR(30) NOT NULL,
    inflow_share  DECIMAL(6,3)    NULL COMMENT '전체 유입 대비 비중(%)',
    dong_count    SMALLINT        NULL,
    PRIMARY KEY (district_id),
    UNIQUE KEY uk_district_name (district_name)
) ENGINE=InnoDB;

CREATE TABLE bridge_district_dong (
    district_id  SMALLINT     NOT NULL,
    dong_code8   CHAR(8)      NOT NULL,
    weight       DECIMAL(8,6) NOT NULL COMMENT '지구내_가중치',
    inflow       DECIMAL(14,2)    NULL COMMENT '출근_유입량',
    PRIMARY KEY (district_id, dong_code8),
    KEY idx_bridge_dong (dong_code8),
    CONSTRAINT fk_bridge_district FOREIGN KEY (district_id) REFERENCES dim_business_district (district_id),
    CONSTRAINT fk_bridge_region   FOREIGN KEY (dong_code8)  REFERENCES dim_region (dong_code8)
) ENGINE=InnoDB;

-- 행정동 부담 마스터 (주거통근_통합부담_행정동별.csv + 업무중심성 병합)
CREATE TABLE fact_dong_burden (
    dong_code8              CHAR(8)      NOT NULL,
    surface_housing_cost    INT              NULL COMMENT '표면주거비_원',
    consumption_index       DECIMAL(8,4)     NULL,
    oneway_commute_min      DECIMAL(6,2)     NULL COMMENT '대표_편도통근시간_분',
    monthly_commute_hour    DECIMAL(7,2)     NULL COMMENT '월_통근시간_시간',
    monthly_transport_cost  INT              NULL COMMENT '월교통비_실지출_원',
    monthly_transport_pass  INT              NULL COMMENT '월교통비_정기권_원',
    internal_commute_ratio  DECIMAL(6,4)     NULL,
    zone_internal_ratio     DECIMAL(6,4)     NULL COMMENT '동일통근권_내부출근비율',
    dest_entropy            DECIMAL(6,4)     NULL COMMENT '목적지_정규화엔트로피',
    youth_single_ratio      DECIMAL(6,4)     NULL COMMENT '청년1인세대_비율/100',
    inflow_outflow_ratio    DECIMAL(8,4)     NULL COMMENT '출근_유입유출비',
    day_night_pop_ratio     DECIMAL(8,4)     NULL COMMENT '주야간_인구비(업무중심성 파일)',
    is_business_center      TINYINT(1)   NOT NULL DEFAULT 0,
    flag_small_sample       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '표본부족',
    flag_few_industry       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '업종부족',
    flag_low_fare_coverage  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '교통비_커버리지부족',
    rank_housing_src        SMALLINT         NULL COMMENT '순위_주거비 (Python 산출, QC 대조용)',
    rank_burden_src         SMALLINT         NULL COMMENT '순위_통합부담 (Python 산출, QC 대조용)',
    burden_type_src         VARCHAR(20)      NULL COMMENT '부담유형 (Python 산출, QC 대조용)',
    PRIMARY KEY (dong_code8),
    CONSTRAINT fk_burden_region FOREIGN KEY (dong_code8) REFERENCES dim_region (dong_code8)
) ENGINE=InnoDB;

-- 행정동 유형화 (FuzzyCMeans k=6, 427행)
--
-- 427행 전체를 넣는다. 유형이 없는 7개 동도 행은 존재하고 type_name 만 NULL 이다.
-- 빼버리면 서비스에서 "왜 이 동은 조회가 안 되나"를 구분할 수 없다.
-- 데이터 부족인지 코드 오류인지는 flag_insufficient 로 판별한다.
--
-- 군집 변수는 5개(부담 3 + 구조 2). 청년1인세대비율과 생활소비부담지수는
-- 군집에 넣지 않고 사후 해석에만 쓴다 - 둘 다 부담구조의 원인이 아니라 결과라,
-- 넣으면 "청년이 많아서 청년밀집형" 같은 동어반복이 된다.
CREATE TABLE fact_dong_type (
    dong_code8         CHAR(8)      NOT NULL,
    k_value            TINYINT      NOT NULL DEFAULT 6,
    cluster_id         TINYINT          NULL COMMENT '데이터 부족 동은 NULL',
    type_name          VARCHAR(40)      NULL COMMENT '데이터 부족 동은 NULL',
    -- FuzzyCMeans 소속도. 경계에 걸친 동을 서비스에서 구분하기 위한 값
    max_membership     DECIMAL(6,4)     NULL COMMENT '최대 소속확률. 낮을수록 두 유형 성격을 함께 가짐',
    flag_boundary      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '군집경계 모호(63개). 유형 단정 금지',
    -- 데이터 부족 표시. kNN 대체를 하지 않기로 해 결측을 그대로 남긴다
    flag_insufficient  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '유형화 데이터부족(7개). 추천 후보에서 제외',
    missing_count      TINYINT      NOT NULL DEFAULT 0,
    missing_columns    VARCHAR(200)     NULL COMMENT '결측 변수명',
    PRIMARY KEY (dong_code8, k_value),
    KEY idx_type_cluster (k_value, cluster_id),
    CONSTRAINT fk_type_region FOREIGN KEY (dong_code8) REFERENCES dim_region (dong_code8)
) ENGINE=InnoDB COMMENT='행정동 유형화 결과 (군집 변수 5개, 사후해석 변수는 fact_dong_burden 참조)';

-- 군집 입력 변수 스냅샷. 유형화에 실제로 들어간 값을 그대로 보관한다.
-- fact_dong_burden 에도 같은 이름의 컬럼이 있지만 집계 기준이 다를 수 있어
-- (표면주거비는 거래단위 pooled 중앙값) 재현성을 위해 따로 둔다.
CREATE TABLE fact_dong_type_features (
    dong_code8              CHAR(8)      NOT NULL,
    surface_housing_cost    DECIMAL(12,2)    NULL COMMENT '거래단위 pooled 중앙값',
    txn_count               INT              NULL COMMENT '표면주거비 산출 거래수',
    oneway_commute_min      DECIMAL(8,4)     NULL,
    monthly_transport_cost  DECIMAL(12,2)    NULL,
    zone_internal_ratio     DECIMAL(8,6)     NULL,
    dest_entropy            DECIMAL(8,6)     NULL,
    dest_hhi                DECIMAL(8,6)     NULL COMMENT '보조지표. 내부통근비중과 상관 0.87이라 군집 미사용',
    youth_single_ratio      DECIMAL(6,2)     NULL COMMENT '사후해석용(%). 군집 미사용',
    PRIMARY KEY (dong_code8),
    CONSTRAINT fk_typefeat_region FOREIGN KEY (dong_code8) REFERENCES dim_region (dong_code8)
) ENGINE=InnoDB COMMENT='군집 입력 변수 스냅샷 (재현성)';

-- 출근 OD 전체 + 80%컷 병합
CREATE TABLE fact_commute_od (
    home_code8    CHAR(8)      NOT NULL,
    work_code8    CHAR(8)      NOT NULL,
    flow          DECIMAL(14,2) NOT NULL COMMENT '출근_이동량',
    obs_time_min  DECIMAL(6,2)     NULL,
    obs_dist_km   DECIMAL(7,3)     NULL,
    is_internal   TINYINT(1)   NOT NULL DEFAULT 0,
    is_top80      TINYINT(1)   NOT NULL DEFAULT 0,
    dest_rank     SMALLINT         NULL,
    final_weight  DECIMAL(9,8)     NULL,
    PRIMARY KEY (home_code8, work_code8),
    KEY idx_od_work (work_code8),
    KEY idx_od_top80 (is_top80)
) ENGINE=InnoDB;

-- Tmap 경로 (commute_routes_analysis_ready.csv, 30,839쌍)
CREATE TABLE fact_commute_route (
    home_code8    CHAR(8)      NOT NULL,
    work_code8    CHAR(8)      NOT NULL,
    oneway_min    DECIMAL(6,2)     NULL COMMENT '분석용_편도시간_분',
    oneway_km     DECIMAL(7,3)     NULL,
    fare          INT              NULL COMMENT '분석용_편도요금_원',
    fare_method   VARCHAR(30)      NULL,
    walk_min      DECIMAL(6,2)     NULL,
    walk_ratio    DECIMAL(6,4)     NULL,
    transfer_cnt  DECIMAL(4,2)     NULL,
    bus_legs      TINYINT          NULL,
    subway_legs   TINYINT          NULL,
    walk_legs     TINYINT          NULL,
    mode_sequence VARCHAR(100)     NULL,
    route_lines   VARCHAR(200)     NULL,
    route_type    VARCHAR(20)      NULL,
    has_route     TINYINT(1)   NOT NULL DEFAULT 1,
    has_fare      TINYINT(1)   NOT NULL DEFAULT 1,
    PRIMARY KEY (home_code8, work_code8),
    KEY idx_route_work (work_code8)
) ENGINE=InnoDB;

-- 거래 단위 (표면주거비_거래단위.csv, 577,761행) - 조건 필터링용
CREATE TABLE fact_rent_transaction (
    txn_id                BIGINT       NOT NULL AUTO_INCREMENT,
    dong_code8             CHAR(8)      NOT NULL,
    contract_ym            CHAR(6)          NULL,
    deposit_krw             BIGINT           NULL COMMENT '보증금(원)',
    rent_krw                INT              NULL COMMENT '월세금(원)',
    area_m2                 DECIMAL(6,2)     NULL,
    housing_type            VARCHAR(20)      NULL COMMENT '단독다가구/연립다세대/오피스텔',
    contract_type           VARCHAR(10)      NULL COMMENT '신규/갱신',
    surface_housing_cost    DECIMAL(10,2)    NULL COMMENT '표면_주거비(원, 이미 계산됨)',
    flag_small_area         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '초소형_추정',
    flag_small_sample_dong  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '표본부족_행정동',
    PRIMARY KEY (txn_id),
    KEY idx_txn_dong (dong_code8),
    KEY idx_txn_deposit (dong_code8, deposit_krw),
    CONSTRAINT fk_txn_region FOREIGN KEY (dong_code8) REFERENCES dim_region (dong_code8)
) ENGINE=InnoDB;

CREATE TABLE dim_policy (
    policy_id      INT          NOT NULL AUTO_INCREMENT,
    policy_name    VARCHAR(100) NOT NULL,
    provider       VARCHAR(50)      NULL,
    category       ENUM('housing_subsidy','loan','deposit_product','info') NOT NULL,
    age_min        TINYINT          NULL,
    age_max        TINYINT          NULL,
    income_max     INT              NULL,
    rent_max       INT              NULL,
    target_sigungu VARCHAR(20)      NULL,
    benefit_amount INT              NULL,
    source_url     VARCHAR(300)     NULL,
    PRIMARY KEY (policy_id)
) ENGINE=InnoDB;

-- 뷰
CREATE OR REPLACE VIEW v_dong_burden AS
SELECT b.dong_code8, r.sigungu_name, r.dong_name, r.region_group,
       t.time_value_code,
       b.surface_housing_cost, b.monthly_transport_pass, b.monthly_transport_cost,
       ROUND(b.monthly_commute_hour * t.hourly_wage) AS monthly_time_cost,
       b.surface_housing_cost + b.monthly_transport_pass
         + ROUND(b.monthly_commute_hour * t.hourly_wage) AS total_burden_pass,
       b.consumption_index, b.youth_single_ratio, b.is_business_center,
       (b.flag_small_sample + b.flag_few_industry + b.flag_low_fare_coverage) AS flag_count
FROM fact_dong_burden b
JOIN dim_region r ON r.dong_code8 = b.dong_code8
CROSS JOIN dim_time_value t;

CREATE OR REPLACE VIEW v_district_commute AS
SELECT br.district_id, d.district_name, rt.home_code8,
       SUM(rt.oneway_min * br.weight) / SUM(br.weight) AS commute_min,
       SUM(rt.fare       * br.weight) / SUM(br.weight) AS oneway_fare,
       SUM(br.weight) AS route_coverage
FROM bridge_district_dong br
JOIN dim_business_district d  ON d.district_id = br.district_id
JOIN fact_commute_route   rt ON rt.work_code8 = br.dong_code8
GROUP BY br.district_id, d.district_name, rt.home_code8;