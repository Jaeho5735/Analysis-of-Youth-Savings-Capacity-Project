-- =====================================================================
-- MULTICAM_PROJECT : 02_analysis_queries.sql
-- 대표 분석 쿼리 6종 + 적재 직후 QC 4종
--
-- 이 파일이 SQL 트랙의 본체다. 적재는 반나절이면 끝나고,
-- 보여줄 것이 있는 쪽은 "그래서 무엇을 어떻게 뽑았나" 쪽이다.
-- =====================================================================
USE multicam;


-- =====================================================================
-- [QC] 적재 직후 반드시 돌리는 4종
-- =====================================================================

-- QC1. 테이블별 행수 - 기대치와 대조
SELECT 'dim_region' AS tbl, COUNT(*) AS cnt, 427 AS expected FROM dim_region
UNION ALL SELECT 'fact_dong_burden', COUNT(*), 420 FROM fact_dong_burden
UNION ALL SELECT 'fact_dong_type',   COUNT(*), 420 FROM fact_dong_type WHERE k_value = 7
UNION ALL SELECT 'dim_business_district', COUNT(*), 9 FROM dim_business_district
UNION ALL SELECT 'bridge_district_dong', COUNT(*), 40 FROM bridge_district_dong
UNION ALL SELECT 'fact_commute_od', COUNT(*), 164860 FROM fact_commute_od
UNION ALL SELECT 'fact_commute_route', COUNT(*), 30839 FROM fact_commute_route
UNION ALL SELECT 'fact_rent_transaction', COUNT(*), 577761 FROM fact_rent_transaction;

-- QC1b. Python 산출 순위(rank_burden_src, 통합부담_정기권_원 기준)와
--       SQL RANK() 결과가 일치하는지 대조. 시간비용(시급10,320원)까지 반영해야 맞는다.
SELECT COUNT(*) AS mismatch_cnt FROM (
    SELECT dong_code8, rank_burden_src,
           RANK() OVER (ORDER BY surface_housing_cost + monthly_transport_pass
                        + ROUND(monthly_commute_hour * 10320)) AS rank_sql
    FROM fact_dong_burden
) x WHERE rank_burden_src <> rank_sql;

-- QC2. 기준표에 없는 코드가 남아 있는가 (있으면 안 됨)
SELECT 'od_home' AS src, o.home_code8 AS orphan_code
FROM fact_commute_od o LEFT JOIN dim_region r ON r.dong_code8 = o.home_code8
WHERE r.dong_code8 IS NULL
UNION ALL
SELECT 'od_work', o.work_code8
FROM fact_commute_od o LEFT JOIN dim_region r ON r.dong_code8 = o.work_code8
WHERE r.dong_code8 IS NULL;

-- QC3. 업무지구 가중치 합이 지구별로 1인가
SELECT d.district_name, ROUND(SUM(br.weight), 6) AS weight_sum
FROM bridge_district_dong br
JOIN dim_business_district d USING (district_id)
GROUP BY d.district_name
HAVING ABS(weight_sum - 1) > 0.001;  -- 지구내_가중치가 소수 4자리 반올림이라 여유를 둔다

-- QC4. 경로 커버리지 - OD 대비 Tmap 경로가 없는 쌍
SELECT
    SUM(o.is_top80)                                   AS top80_od,
    COUNT(rt.home_code8)                              AS routed,
    SUM(o.is_top80) - COUNT(rt.home_code8)            AS missing_route
FROM fact_commute_od o
LEFT JOIN fact_commute_route rt
       ON rt.home_code8 = o.home_code8 AND rt.work_code8 = o.work_code8
WHERE o.is_top80 = 1;


-- =====================================================================
-- [Q1] 월세착시 - 주거비 순위와 통합부담 순위의 괴리
--   순위는 1 = 저부담. rank_gap = 주거비순위 - 통합부담순위.
--   음수 = 월세만 보면 싸 보이는데 실제로는 더 무거운 동 (착시)
--   양수 = 월세는 비싼 편인데 통근을 합치면 유리해지는 동 (숨은효율)
-- 기법: CTE + RANK() OVER
--
-- ※ 아래 CASE 의 -50/+50 컷은 이 쿼리에서만 쓰는 임시 구간이다.
--   확정 부담유형은 build_total_burden.py 가 계산해 fact_dong_burden.burden_type_src
--   컬럼에 들어 있다(A 197 / B 13 / C 13 / D 197). 화면·발표에는 그쪽을 쓸 것.
--   이 쿼리의 목적은 파이썬이 낸 순위를 SQL 윈도우 함수로 동일하게 재현하는 것이다.
-- =====================================================================
WITH ranked AS (
    SELECT
        v.dong_code8,
        v.sigungu_name,
        v.dong_name,
        v.region_group,
        v.surface_housing_cost,
        v.total_burden_pass,
        RANK() OVER (ORDER BY v.surface_housing_cost) AS rank_housing,
        RANK() OVER (ORDER BY v.total_burden_pass)    AS rank_total
    FROM v_dong_burden v
    WHERE v.time_value_code = 'minwage'
      AND v.surface_housing_cost IS NOT NULL
)
SELECT
    sigungu_name,
    dong_name,
    region_group,
    surface_housing_cost,
    total_burden_pass,
    rank_housing,
    rank_total,
    -- RANK() 는 UNSIGNED 라 그대로 빼면 음수에서 오버플로가 난다. 반드시 CAST.
    CAST(rank_housing AS SIGNED) - CAST(rank_total AS SIGNED) AS rank_gap,
    CASE
        WHEN CAST(rank_housing AS SIGNED) - CAST(rank_total AS SIGNED) <= -50 THEN 'B_월세착시'
        WHEN CAST(rank_housing AS SIGNED) - CAST(rank_total AS SIGNED) >=  50 THEN 'C_숨은효율'
        WHEN rank_total <= 210                THEN 'A_실질저부담'
        ELSE 'D_종합고부담'
    END AS burden_type
FROM ranked
ORDER BY rank_gap ASC
LIMIT 20;


-- =====================================================================
-- [Q2] 업무지구별 추천 주거지 상위 10
--   점수 방식: A안(통합부담 최소) + 청년밀집 필터
--   - 지구 대표 통근값은 구성동 유입량 가중평균 (v_district_commute)
--   - 교통비는 정기권 캡 62,000원 적용
--   - 청년1인세대비율 하위 10% 동은 후보에서 제외
--     ("싸지만 청년이 실제로 살지 않는 동"이 상위를 차지하는 것 방지)
-- 기법: 다중 CTE + NTILE + ROW_NUMBER() OVER (PARTITION BY)
-- =====================================================================
WITH params AS (
    SELECT 21 AS work_days, 62000 AS pass_cap,
           (SELECT hourly_wage FROM dim_time_value WHERE time_value_code = 'minwage') AS wage
),
candidate AS (   -- 청년밀집 하위 10% 제외
    SELECT b.dong_code8,
           NTILE(10) OVER (ORDER BY b.youth_single_ratio) AS youth_decile
    FROM fact_dong_burden b
    WHERE b.youth_single_ratio IS NOT NULL
      AND b.surface_housing_cost IS NOT NULL
      AND b.flag_small_sample = 0
),
scored AS (
    SELECT
        dc.district_id,
        dc.district_name,
        r.sigungu_name,
        r.dong_name,
        b.surface_housing_cost,
        ROUND(dc.commute_min, 1)                                        AS commute_min,
        LEAST(ROUND(dc.oneway_fare) * 2 * p.work_days, p.pass_cap)      AS monthly_transport,
        ROUND(dc.commute_min * 2 * p.work_days / 60 * p.wage)           AS monthly_time_cost,
        b.surface_housing_cost
          + LEAST(ROUND(dc.oneway_fare) * 2 * p.work_days, p.pass_cap)
          + ROUND(dc.commute_min * 2 * p.work_days / 60 * p.wage)       AS total_burden,
        dc.route_coverage,
        t.type_name
    FROM v_district_commute dc
    JOIN candidate        c ON c.dong_code8 = dc.home_code8 AND c.youth_decile > 1
    JOIN fact_dong_burden b ON b.dong_code8 = dc.home_code8
    JOIN dim_region       r ON r.dong_code8 = dc.home_code8
    LEFT JOIN fact_dong_type t ON t.dong_code8 = dc.home_code8 AND t.k_value = 7
    CROSS JOIN params p
    WHERE dc.route_coverage >= 0.7          -- 지구 구성동 경로 확보율
),
ranked AS (
    SELECT s.*,
           ROW_NUMBER() OVER (PARTITION BY s.district_id ORDER BY s.total_burden) AS rn
    FROM scored s
)
SELECT district_name, rn AS 순위, sigungu_name, dong_name,
       surface_housing_cost, commute_min, monthly_transport,
       monthly_time_cost, total_burden, type_name
FROM ranked
WHERE rn <= 10
ORDER BY district_name, rn;


-- =====================================================================
-- [Q3] 지구 간 추천 중복률 매트릭스
--   "근무지가 바뀌면 최적 주거지가 얼마나 달라지는가"
--   중복 수가 작을수록 근무지 개인화의 실익이 크다는 근거가 된다.
-- 기법: CTE 재사용 + self join
-- =====================================================================
WITH params AS (
    SELECT 21 AS work_days, 62000 AS pass_cap,
           (SELECT hourly_wage FROM dim_time_value WHERE time_value_code = 'minwage') AS wage
),
top10 AS (
    SELECT district_id, district_name, home_code8, rn
    FROM (
        SELECT dc.district_id, dc.district_name, dc.home_code8,
               ROW_NUMBER() OVER (
                   PARTITION BY dc.district_id
                   ORDER BY b.surface_housing_cost
                          + LEAST(ROUND(dc.oneway_fare) * 2 * p.work_days, p.pass_cap)
                          + ROUND(dc.commute_min * 2 * p.work_days / 60 * p.wage)
               ) AS rn
        FROM v_district_commute dc
        JOIN fact_dong_burden b ON b.dong_code8 = dc.home_code8
        CROSS JOIN params p
        WHERE dc.route_coverage >= 0.7
          AND b.surface_housing_cost IS NOT NULL
          AND b.flag_small_sample = 0
    ) x
    WHERE rn <= 10
)
SELECT
    a.district_name AS 지구A,
    b.district_name AS 지구B,
    COUNT(*)        AS 공통_동수,
    ROUND(COUNT(*) / 10 * 100, 1) AS 중복률_pct
FROM top10 a
JOIN top10 b
  ON a.home_code8 = b.home_code8
 AND a.district_id < b.district_id
GROUP BY a.district_name, b.district_name
ORDER BY 공통_동수 DESC;


-- =====================================================================
-- [Q4] 소득 시나리오별 저축여력 - 저축률 20% 달성 가능 행정동 수
--   소득·시간가치·생활비를 전부 파라미터 테이블에서 가져오므로
--   가정을 바꾸는 민감도 분석이 WHERE 절 수정만으로 끝난다.
-- 기법: CROSS JOIN (파라미터 격자) + 조건부 집계
-- =====================================================================
SELECT
    i.label                                    AS 소득시나리오,
    t.label                                    AS 시간가치기준,
    COUNT(*)                                   AS 대상_행정동,
    SUM(CASE WHEN i.monthly_net_income
                  - v.total_burden_pass
                  - (lc.base_amount + lc.index_slope * v.consumption_index)
                  >= i.monthly_net_income * 0.20
             THEN 1 ELSE 0 END)                AS 저축률20_달성동수,
    ROUND(AVG(i.monthly_net_income
              - v.total_burden_pass
              - (lc.base_amount + lc.index_slope * v.consumption_index))) AS 평균_잔여액
FROM v_dong_burden v
JOIN dim_time_value t ON t.time_value_code = v.time_value_code
CROSS JOIN dim_income_scenario i
CROSS JOIN dim_living_cost_assumption lc
WHERE v.surface_housing_cost IS NOT NULL
  AND v.consumption_index IS NOT NULL
  AND lc.assumption_code = 'base'
GROUP BY i.label, i.monthly_net_income, t.label
ORDER BY i.monthly_net_income, t.label;


-- =====================================================================
-- [Q5] 7개 유형별 프로파일 - 유형이 실제로 서로 다른가
--   군집에 쓰지 않은 변수(권역 구성)까지 같이 보여 외적 타당성을 겸한다.
-- 기법: GROUP BY + JOIN + 조건부 집계
-- =====================================================================
SELECT
    t.type_name                                       AS 유형,
    COUNT(*)                                          AS 동수,
    ROUND(AVG(b.surface_housing_cost))                AS 평균_주거비,
    ROUND(AVG(b.oneway_commute_min), 1)               AS 평균_통근분,
    ROUND(AVG(b.monthly_transport_cost))              AS 평균_교통비,
    ROUND(AVG(b.consumption_index), 2)                AS 평균_소비지수,
    ROUND(AVG(b.youth_single_ratio) * 100, 1)         AS 청년1인세대_pct,
    SUM(t.assign_method = 'post')                     AS 사후배정_동수,
    GROUP_CONCAT(DISTINCT r.region_group ORDER BY r.region_group SEPARATOR ',') AS 분포권역
FROM fact_dong_type t
JOIN fact_dong_burden b ON b.dong_code8 = t.dong_code8
JOIN dim_region       r ON r.dong_code8 = t.dong_code8
WHERE t.k_value = 7
GROUP BY t.type_name
ORDER BY 동수 DESC;


-- =====================================================================
-- [Q6] 정책·금융상품 매칭 - 특정 행정동 거주 가정 시 적용 가능 목록
--   조건 컬럼은 "NULL = 제한 없음" 규칙이라 조인 한 벌로 끝난다.
--   ※ 금융상품 담당 팀원과 컬럼 확정 후 category 확장 필요
-- 기법: 조건 조인 + COALESCE 기본값
-- =====================================================================
SELECT
    r.dong_name,
    p.category,
    p.policy_name,
    p.provider,
    p.benefit_amount,
    b.surface_housing_cost,
    ROUND(b.surface_housing_cost - COALESCE(p.benefit_amount, 0)) AS 지원후_주거비
FROM fact_dong_burden b
JOIN dim_region r ON r.dong_code8 = b.dong_code8
JOIN dim_policy p
  ON (p.target_sigungu IS NULL OR p.target_sigungu = r.sigungu_name)
 AND (p.rent_max       IS NULL OR p.rent_max      >= b.surface_housing_cost)
 AND (p.age_min        IS NULL OR p.age_min       <= 29)      -- 사용자 나이 파라미터
 AND (p.age_max        IS NULL OR p.age_max       >= 29)
 AND (p.income_max     IS NULL OR p.income_max    >= 2800000) -- 사용자 소득 파라미터
WHERE r.dong_name = '노량진제1동'
ORDER BY p.category, COALESCE(p.benefit_amount, 0) DESC;