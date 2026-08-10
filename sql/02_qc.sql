-- =====================================================================
-- MULTICAM_PROJECT : 02_qc.sql  -  적재 직후 검증
--
-- 실행: mysql 접속 후  SOURCE C:/MULTICAM_PROJECT/sql/02_qc.sql;
-- 각 쿼리의 판정 컬럼만 보면 된다. 전부 OK 면 분석 쿼리로 넘어간다.
-- =====================================================================
USE multicam;

SELECT '===== QC1. 테이블별 행수 =====' AS '';

SELECT tbl, cnt, expected,
       CASE WHEN cnt = expected THEN 'OK' ELSE '!! 불일치' END AS 판정
FROM (
    SELECT 'dim_region' AS tbl, COUNT(*) AS cnt, 427 AS expected FROM dim_region
    UNION ALL SELECT 'dim_business_district', COUNT(*),      9 FROM dim_business_district
    UNION ALL SELECT 'bridge_district_dong',  COUNT(*),     40 FROM bridge_district_dong
    UNION ALL SELECT 'fact_dong_burden',      COUNT(*),    420 FROM fact_dong_burden
    UNION ALL SELECT 'fact_dong_type',        COUNT(*),    420 FROM fact_dong_type
    UNION ALL SELECT 'fact_commute_od',       COUNT(*), 164032 FROM fact_commute_od
    UNION ALL SELECT 'fact_commute_route',    COUNT(*),  30636 FROM fact_commute_route
    UNION ALL SELECT 'fact_rent_transaction', COUNT(*), 577745 FROM fact_rent_transaction
    UNION ALL SELECT 'dim_time_value',        COUNT(*),      1 FROM dim_time_value
    UNION ALL SELECT 'dim_income_scenario',   COUNT(*),      5 FROM dim_income_scenario
) x;


SELECT '===== QC2. 기준표 미등재 코드 (0행이어야 정상) =====' AS '';

SELECT src, orphan_code, COUNT(*) AS cnt FROM (
    SELECT 'od_home' AS src, o.home_code8 AS orphan_code
      FROM fact_commute_od o LEFT JOIN dim_region r ON r.dong_code8 = o.home_code8
     WHERE r.dong_code8 IS NULL
    UNION ALL
    SELECT 'od_work', o.work_code8
      FROM fact_commute_od o LEFT JOIN dim_region r ON r.dong_code8 = o.work_code8
     WHERE r.dong_code8 IS NULL
    UNION ALL
    SELECT 'burden', b.dong_code8
      FROM fact_dong_burden b LEFT JOIN dim_region r ON r.dong_code8 = b.dong_code8
     WHERE r.dong_code8 IS NULL
) y GROUP BY src, orphan_code;


SELECT '===== QC3. 업무지구 가중치 합 (0행이어야 정상) =====' AS '';

SELECT d.district_name, ROUND(SUM(br.weight), 6) AS weight_sum
FROM bridge_district_dong br
JOIN dim_business_district d USING (district_id)
GROUP BY d.district_name
HAVING ABS(weight_sum - 1) > 0.001;


SELECT '===== QC4. 경로 커버리지 =====' AS '';

SELECT
    SUM(o.is_top80)                        AS top80_od,
    COUNT(rt.home_code8)                   AS routed,
    SUM(o.is_top80) - COUNT(rt.home_code8) AS missing_route,
    CONCAT(ROUND(COUNT(rt.home_code8) / SUM(o.is_top80) * 100, 2), '%') AS 커버리지
FROM fact_commute_od o
LEFT JOIN fact_commute_route rt
       ON rt.home_code8 = o.home_code8 AND rt.work_code8 = o.work_code8
WHERE o.is_top80 = 1;

-- 업무지구별 커버리지 - 분석 3(업무지구별 추천)의 실행 가능 여부가 여기서 갈린다
SELECT district_name,
       COUNT(*)                                  AS 거주동수,
       ROUND(AVG(route_coverage), 3)             AS 평균_경로확보율,
       SUM(route_coverage >= 0.7)                AS 확보율70이상
FROM v_district_commute
GROUP BY district_name
ORDER BY 평균_경로확보율;


SELECT '===== QC5. 순위 재현 (Python 산출값 vs SQL RANK) =====' AS '';

SELECT COUNT(*) AS 불일치_동수,
       CASE WHEN COUNT(*) = 0 THEN 'OK'
            WHEN COUNT(*) <= 5 THEN '허용 (반올림 차이)'
            ELSE '!! 확인 필요' END AS 판정
FROM (
    SELECT dong_code8, rank_burden_src,
           RANK() OVER (ORDER BY surface_housing_cost + monthly_transport_pass
                        + ROUND(monthly_commute_hour * 10320)) AS rank_sql
    FROM fact_dong_burden
) z WHERE rank_burden_src <> rank_sql;


SELECT '===== QC6. 결측 대입 동 (5개여야 정상) =====' AS '';

SELECT r.sigungu_name, r.dong_name, t.type_name, t.assign_method
FROM fact_dong_type t
JOIN dim_region r ON r.dong_code8 = t.dong_code8
WHERE t.flag_imputed = 1
ORDER BY r.sigungu_name;


SELECT '===== QC7. 한글·금액 단위 육안 확인 =====' AS '';

SELECT r.sigungu_name, r.dong_name,
       FORMAT(b.surface_housing_cost, 0)   AS 표면주거비,
       FORMAT(b.monthly_transport_pass, 0) AS 월교통비_정기권,
       ROUND(b.oneway_commute_min, 1)      AS 편도분,
       t.type_name                          AS 유형
FROM fact_dong_burden b
JOIN dim_region r    ON r.dong_code8 = b.dong_code8
JOIN fact_dong_type t ON t.dong_code8 = b.dong_code8
ORDER BY b.surface_housing_cost DESC
LIMIT 5;

-- 거래 단위 금액이 원 단위로 들어갔는지 (보증금 수천만원, 월세 수십만원대여야 정상)
SELECT COUNT(*) AS 거래수,
       FORMAT(ROUND(AVG(deposit_krw)), 0) AS 평균보증금,
       FORMAT(ROUND(AVG(rent_krw)), 0)    AS 평균월세,
       FORMAT(ROUND(AVG(surface_housing_cost)), 0) AS 평균표면주거비
FROM fact_rent_transaction;