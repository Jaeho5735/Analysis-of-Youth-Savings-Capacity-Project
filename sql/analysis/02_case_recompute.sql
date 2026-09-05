-- =====================================================================
-- MULTICAM_PROJECT : 03_case_recompute.sql
-- 극심지역 대표 8곳 + LOCA 시연 사례 1건을 확정 기준으로 재계산
--
-- 왜 필요한가
--   보고서의 총부담 증가액을 역산하면 내재 교통비 증가가 사례마다
--   -746원 ~ 75,639원으로 갈린다. 같은 산식이면 나올 수 없는 편차다.
--   요금 결측을 0으로 채웠을 가능성이 높아, DB 원본으로 다시 계산한다.
--
-- 확정 기준
--   시간가치 10,320원/시간, 월 출근일수 21일, 왕복 2회
--   교통비는 실지출·정기권(기후동행카드 62,000원 캡) 병기
--
-- 읽는 법
--   fare_status 가 '기준지 요금없음' 또는 '후보지 요금없음'이면
--   그 사례는 교통비 계산이 불가능하다. 0으로 채우면 과대 계산된다.
--   경로없음은 fact_commute_route(80% 컷)에 해당 OD 쌍이 없다는 뜻이며,
--   이 경우 사례 자체를 다른 쌍으로 교체해야 한다.
-- =====================================================================
USE multicam;

WITH pairs AS (
    -- 근무동, 기준 거주동, 후보 거주동 (시군구는 동명이인 구분용)
    SELECT '역삼1동' AS w_dong, '강남구' AS w_gu,
           '서초1동' AS a_dong, '서초구' AS a_gu,
           '방화제2동' AS b_dong, '강서구' AS b_gu, '극심1' AS tag
    UNION ALL SELECT '성수2가3동','성동구','행당제1동','성동구','신길제3동','영등포구','극심2'
    UNION ALL SELECT '성수1가2동','성동구','행당제1동','성동구','송천동','강북구','극심3'
    UNION ALL SELECT '여의동','영등포구','신길제1동','영등포구','월계3동','노원구','극심4'
    UNION ALL SELECT '양재2동','서초구','내곡동','서초구','불광제2동','은평구','극심5'
    UNION ALL SELECT '삼성1동','강남구','반포1동','서초구','쌍문제1동','도봉구','극심6'
    UNION ALL SELECT '반포4동','서초구','방배1동','서초구','삼양동','강북구','극심7'
    UNION ALL SELECT '서초3동','서초구','도곡1동','강남구','월계1동','노원구','극심8'
    UNION ALL SELECT '역삼1동','강남구','잠원동','서초구','신길1동','영등포구','LOCA시연'
),
-- 행정동명 표기 차이 흡수: "역삼제1동" <-> "역삼1동"
-- 제 뒤에 숫자가 오는 경우만 제거하므로 제기동·제물포 같은 이름은 안 건드린다
norm AS (
    SELECT dong_code8, sigungu_name,
           REGEXP_REPLACE(dong_name, '제([0-9])', '$1') AS n_name,
           dong_name
    FROM dim_region
),
resolved AS (
    SELECT p.tag, p.w_dong, p.a_dong, p.b_dong,
           w.dong_code8 AS w_code, a.dong_code8 AS a_code, b.dong_code8 AS b_code
    FROM pairs p
    LEFT JOIN norm w ON w.n_name = REGEXP_REPLACE(p.w_dong,'제([0-9])','$1') AND w.sigungu_name = p.w_gu
    LEFT JOIN norm a ON a.n_name = REGEXP_REPLACE(p.a_dong,'제([0-9])','$1') AND a.sigungu_name = p.a_gu
    LEFT JOIN norm b ON b.n_name = REGEXP_REPLACE(p.b_dong,'제([0-9])','$1') AND b.sigungu_name = p.b_gu
),
calc AS (
    SELECT r.tag, r.w_dong, r.a_dong, r.b_dong,
           ha.surface_housing_cost AS a_rent,
           hb.surface_housing_cost AS b_rent,
           ra.oneway_min           AS a_min,
           rb.oneway_min           AS b_min,
           ra.fare                 AS a_fare,
           rb.fare                 AS b_fare,
           -- 요금 결측을 0으로 채우면 교통비 증가가 후보지 전액이 되어 과대 계산된다.
           -- 채우지 않고 NULL 로 두어 드러나게 한다.
           ra.fare * 2 * 21                       AS a_transport_actual,
           rb.fare * 2 * 21                       AS b_transport_actual,
           LEAST(ra.fare * 2 * 21, 62000)         AS a_transport_pass,
           LEAST(rb.fare * 2 * 21, 62000)         AS b_transport_pass,
           ROUND((rb.oneway_min - ra.oneway_min) * 2 * 21 / 60 * 10320) AS time_cost_delta
    FROM resolved r
    LEFT JOIN fact_dong_burden   ha ON ha.dong_code8 = r.a_code
    LEFT JOIN fact_dong_burden   hb ON hb.dong_code8 = r.b_code
    LEFT JOIN fact_commute_route ra ON ra.home_code8 = r.a_code AND ra.work_code8 = r.w_code
    LEFT JOIN fact_commute_route rb ON rb.home_code8 = r.b_code AND rb.work_code8 = r.w_code
)
SELECT
    tag                                              AS 사례,
    CONCAT(a_dong,'→',b_dong)                        AS 비교쌍,
    w_dong                                           AS 근무동,
    ROUND((a_rent - b_rent) / 10000, 1)              AS 주거비절감_만원,
    ROUND(b_min - a_min, 1)                          AS 편도증가_분,
    ROUND(time_cost_delta / 10000, 1)                AS 시간비용증가_만원,
    ROUND((b_transport_actual - a_transport_actual) / 10000, 1) AS 교통비증가_실지출_만원,
    ROUND((b_transport_pass   - a_transport_pass)   / 10000, 1) AS 교통비증가_정기권_만원,
    ROUND((time_cost_delta + b_transport_actual - a_transport_actual
           - (a_rent - b_rent)) / 10000, 1)          AS 총부담증가_실지출_만원,
    ROUND((time_cost_delta + b_transport_pass - a_transport_pass
           - (a_rent - b_rent)) / 10000, 1)          AS 총부담증가_정기권_만원,
    CASE WHEN a_min  IS NULL THEN '기준지 경로없음'
         WHEN b_min  IS NULL THEN '후보지 경로없음'
         WHEN a_fare IS NULL THEN '기준지 요금없음'
         WHEN b_fare IS NULL THEN '후보지 요금없음'
         ELSE 'OK' END                               AS 상태
FROM calc
ORDER BY 사례;


-- 코드 매칭 실패 진단 (0행이어야 정상)
-- 행이 나오면 그 행정동명이 dim_region 표기와 다르다는 뜻이다
WITH pairs AS (
    SELECT '역삼1동' AS d, '강남구' AS g UNION ALL SELECT '서초1동','서초구'
    UNION ALL SELECT '방화제2동','강서구' UNION ALL SELECT '성수2가3동','성동구'
    UNION ALL SELECT '행당제1동','성동구' UNION ALL SELECT '신길제3동','영등포구'
    UNION ALL SELECT '성수1가2동','성동구' UNION ALL SELECT '송천동','강북구'
    UNION ALL SELECT '여의동','영등포구'  UNION ALL SELECT '신길제1동','영등포구'
    UNION ALL SELECT '월계3동','노원구'   UNION ALL SELECT '양재2동','서초구'
    UNION ALL SELECT '내곡동','서초구'    UNION ALL SELECT '불광제2동','은평구'
    UNION ALL SELECT '삼성1동','강남구'   UNION ALL SELECT '반포1동','서초구'
    UNION ALL SELECT '쌍문제1동','도봉구' UNION ALL SELECT '반포4동','서초구'
    UNION ALL SELECT '방배1동','서초구'   UNION ALL SELECT '삼양동','강북구'
    UNION ALL SELECT '서초3동','서초구'   UNION ALL SELECT '도곡1동','강남구'
    UNION ALL SELECT '월계1동','노원구'   UNION ALL SELECT '잠원동','서초구'
    UNION ALL SELECT '신길1동','영등포구'
)
SELECT p.d AS 못찾은_행정동, p.g AS 시군구
FROM pairs p
LEFT JOIN dim_region r
       ON REGEXP_REPLACE(r.dong_name,'제([0-9])','$1') = REGEXP_REPLACE(p.d,'제([0-9])','$1')
      AND r.sigungu_name = p.g
WHERE r.dong_code8 IS NULL;


-- 시연 기준점 표본 확인: 잠원동·서초1동 등 고가 지역의 청년 거래가 충분한가
SELECT r.sigungu_name, r.dong_name,
       COUNT(t.txn_id)                       AS 거래수,
       FORMAT(ROUND(AVG(t.rent_krw)), 0)     AS 평균월세,
       b.flag_small_sample                   AS 표본부족플래그
FROM dim_region r
LEFT JOIN fact_rent_transaction t ON t.dong_code8 = r.dong_code8
LEFT JOIN fact_dong_burden      b ON b.dong_code8 = r.dong_code8
WHERE REGEXP_REPLACE(r.dong_name,'제([0-9])','$1')
      IN ('잠원동','서초1동','신길1동','방화2동','행당1동','내곡동','반포1동','방배1동','도곡1동')
GROUP BY r.sigungu_name, r.dong_name, b.flag_small_sample
ORDER BY 거래수;