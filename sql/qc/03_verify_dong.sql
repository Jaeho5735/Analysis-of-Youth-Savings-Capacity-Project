-- 06_verify_dong.sql
-- 화면에 뜬 값이 DB와 맞는지 한 행정동에 대해 대조한다.
-- 사용: 아래 @home / @work 만 바꿔서 실행.

SET @home = '청림동';
SET @work = '남영동';
SET @days = 20;        -- 화면에서 입력한 월 출근일수
SET @deposit = 1000;   -- 만원
SET @rent = 70;        -- 만원

-- ① 부담 유형·지역 유형 (진단 카드 1·2번)
SELECT r.dong_name          AS 행정동,
       r.sigungu_name       AS 자치구,
       b.burden_type_src    AS 부담유형,
       t.type_name          AS 지역유형,
       t.max_membership     AS 유형_소속확률,
       t.flag_boundary      AS 경계모호,
       b.rank_housing_src   AS 주거비순위,
       b.rank_burden_src    AS 통합부담순위,
       b.rank_housing_src - b.rank_burden_src AS 월세착시_순위차,
       b.flag_small_sample  AS 표본부족,
       b.flag_low_fare_coverage AS 교통비커버리지부족
FROM dim_region r
JOIN fact_dong_burden b ON b.dong_code8 = r.dong_code8
LEFT JOIN fact_dong_type t ON t.dong_code8 = r.dong_code8 AND t.k_value = 6
WHERE REPLACE(r.dong_name, '제', '') = REPLACE(@home, '제', '');

-- ② 통근 경로 실측값 (편도·거리·환승·요금·노선)
SELECT hr.dong_name  AS 거주동,
       wr.dong_name  AS 근무동,
       cr.oneway_min AS 편도_분,
       cr.oneway_km  AS 거리_km,
       cr.transfer_cnt AS 환승,
       cr.fare       AS 편도요금_원,
       cr.route_lines  AS 이용노선,
       cr.mode_sequence AS 수단순서,
       -- 화면 계산 재현
       LEAST(cr.fare * 2 * @days, 55000) AS 월교통비_정기권,
       ROUND(cr.oneway_min * 2 * @days / 60, 2) AS 월통근시간_시간,
       ROUND(cr.oneway_min * 2 * @days / 60 * 10320) AS 시간가치_원,
       ROUND(@rent * 10000 + @deposit * 10000 * 0.0348 / 12) AS 주거비_원,
       ROUND(@rent * 10000 + @deposit * 10000 * 0.0348 / 12
             + LEAST(cr.fare * 2 * @days, 55000)
             + cr.oneway_min * 2 * @days / 60 * 10320) AS 총부담_원
FROM fact_commute_route cr
JOIN dim_region hr ON hr.dong_code8 = cr.home_code8
JOIN dim_region wr ON wr.dong_code8 = cr.work_code8
WHERE REPLACE(hr.dong_name, '제', '') = REPLACE(@home, '제', '')
  AND REPLACE(wr.dong_name, '제', '') = REPLACE(@work, '제', '');

-- ③ 부담유형 판정 근거 재현 (중앙값 대비 위치)
--    MySQL 은 LIMIT/OFFSET 에 서브쿼리를 못 쓴다. 윈도우 함수로 중앙값을 낸다.
WITH h AS (
  SELECT surface_housing_cost AS v,
         ROW_NUMBER() OVER (ORDER BY surface_housing_cost) AS rn,
         COUNT(*) OVER () AS n
  FROM fact_dong_burden WHERE surface_housing_cost IS NOT NULL
), t AS (
  SELECT (surface_housing_cost + monthly_transport_pass
          + monthly_commute_hour * 10320) AS v,
         ROW_NUMBER() OVER (ORDER BY surface_housing_cost + monthly_transport_pass
                                     + monthly_commute_hour * 10320) AS rn,
         COUNT(*) OVER () AS n
  FROM fact_dong_burden
  WHERE surface_housing_cost IS NOT NULL AND monthly_transport_pass IS NOT NULL
), med AS (
  SELECT (SELECT AVG(v) FROM h WHERE rn IN (FLOOR((n+1)/2), FLOOR((n+2)/2))) AS h_med,
         (SELECT AVG(v) FROM t WHERE rn IN (FLOOR((n+1)/2), FLOOR((n+2)/2))) AS t_med
)
SELECT b.burden_type_src                     AS 저장된_유형,
       ROUND(b.surface_housing_cost)         AS 표면주거비,
       ROUND(med.h_med)                      AS 주거비_중앙값,
       IF(b.surface_housing_cost < med.h_med, '중앙값 미만', '중앙값 이상') AS 주거비_위치,
       ROUND(b.surface_housing_cost + b.monthly_transport_pass
             + b.monthly_commute_hour * 10320) AS 통합부담,
       ROUND(med.t_med)                      AS 통합부담_중앙값,
       IF(b.surface_housing_cost + b.monthly_transport_pass
          + b.monthly_commute_hour * 10320 < med.t_med,
          '중앙값 미만', '중앙값 이상')       AS 통합부담_위치,
       -- 둘 다 미만이면 A, 주거비만 미만이면 B, 주거비만 이상이면 C, 둘 다 이상이면 D
       CASE
         WHEN b.surface_housing_cost < med.h_med
          AND b.surface_housing_cost + b.monthly_transport_pass
              + b.monthly_commute_hour * 10320 < med.t_med THEN 'A 실질 저부담'
         WHEN b.surface_housing_cost < med.h_med           THEN 'B 월세 착시'
         WHEN b.surface_housing_cost + b.monthly_transport_pass
              + b.monthly_commute_hour * 10320 < med.t_med THEN 'C 숨은 효율'
         ELSE 'D 종합 고부담'
       END                                   AS 재현된_유형
FROM dim_region r
JOIN fact_dong_burden b ON b.dong_code8 = r.dong_code8
CROSS JOIN med
WHERE REPLACE(r.dong_name, '제', '') = REPLACE(@home, '제', '');