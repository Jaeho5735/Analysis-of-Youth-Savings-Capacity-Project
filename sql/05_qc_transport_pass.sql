-- 05_qc_transport_pass.sql
-- 정기권 가정 적재 후 검증 7종. 각 쿼리는 result 컬럼이 OK 여야 통과.

-- QC1. 기본 가정이 정확히 1행인가
SELECT 'QC1 기본가정 유일성' AS qc, COUNT(*) AS cnt,
       IF(COUNT(*) = 1, 'OK', 'FAIL') AS result
FROM dim_transport_pass_assumption WHERE is_default = 1;

-- QC2. 상한이 전부 양수인가 (0 이면 교통비가 사라져 부담 순위가 뒤집힌다)
SELECT 'QC2 상한 양수' AS qc, COUNT(*) AS bad_cnt,
       IF(COUNT(*) = 0, 'OK', 'FAIL') AS result
FROM dim_transport_pass_assumption WHERE monthly_cap <= 0;

-- QC3. 연령 범위가 뒤집힌 행이 없는가
SELECT 'QC3 연령범위' AS qc, COUNT(*) AS bad_cnt,
       IF(COUNT(*) = 0, 'OK', 'FAIL') AS result
FROM dim_transport_pass_assumption
WHERE target_age_min IS NOT NULL AND target_age_max IS NOT NULL
  AND target_age_min > target_age_max;

-- QC4. fact_dong_burden 의 가정코드가 전부 dim 에 등재돼 있는가
SELECT 'QC4 가정코드 참조무결성' AS qc, COUNT(*) AS orphan_cnt,
       IF(COUNT(*) = 0, 'OK', 'FAIL') AS result
FROM fact_dong_burden b
LEFT JOIN dim_transport_pass_assumption a ON b.transport_pass_code = a.assumption_code
WHERE b.transport_pass_code IS NOT NULL AND a.assumption_code IS NULL;

-- QC5. 한 적재본 안에 가정이 섞여 있지 않은가 (섞이면 동 간 비교가 무의미)
SELECT 'QC5 가정 단일성' AS qc, COUNT(DISTINCT transport_pass_code) AS kinds,
       IF(COUNT(DISTINCT transport_pass_code) = 1, 'OK', 'FAIL') AS result
FROM fact_dong_burden;

-- QC6. 정기권 교통비가 상한을 넘는 동이 없는가 (clip 이 제대로 걸렸는지)
SELECT 'QC6 상한 초과' AS qc, COUNT(*) AS over_cnt,
       IF(COUNT(*) = 0, 'OK', 'FAIL') AS result
FROM fact_dong_burden b
JOIN dim_transport_pass_assumption a ON b.transport_pass_code = a.assumption_code
WHERE b.monthly_transport_pass > a.monthly_cap;

-- QC7. 정기권 값이 실지출보다 큰 동이 없는가 (캡은 낮추기만 해야 한다.
--      단 결측 대체 동은 실지출도 상한으로 채웠으므로 같은 값이 정상)
SELECT 'QC7 정기권<=실지출' AS qc, COUNT(*) AS bad_cnt,
       IF(COUNT(*) = 0, 'OK', 'FAIL') AS result
FROM fact_dong_burden
WHERE monthly_transport_pass > monthly_transport_cost;


-- 참고. 적재 결과 요약 (판정 아님)
SELECT a.assumption_code, a.assumption_name, a.monthly_cap, a.is_default,
       COUNT(b.dong_code8) AS 적용_동수,
       SUM(b.flag_fare_imputed) AS 요금결측_대체동수,
       SUM(b.monthly_transport_cost > a.monthly_cap) AS 정기권_유리_동수
FROM dim_transport_pass_assumption a
LEFT JOIN fact_dong_burden b ON b.transport_pass_code = a.assumption_code
GROUP BY a.assumption_code, a.assumption_name, a.monthly_cap, a.is_default
ORDER BY a.is_default DESC, a.monthly_cap DESC;
