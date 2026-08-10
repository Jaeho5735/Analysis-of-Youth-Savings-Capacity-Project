-- =====================================================================
-- MULTICAM_PROJECT : 01b_seed_params.sql
-- 파라미터 테이블 초기값. 01_schema.sql 실행 직후에 돌린다.
--
-- 이 세 테이블은 CSV 소스가 없다. 가정을 코드가 아니라 데이터로
-- 분리해두기 위해 만든 것이라 값은 여기서 직접 관리한다.
-- 값을 바꾸고 싶으면 이 파일만 고쳐서 다시 실행하면 된다.
-- =====================================================================
USE multicam;

-- ---------------------------------------------------------------------
-- 시간가치 : 기획안 v2의 3종 비교안
-- 기본값은 최저임금. 나머지 둘은 민감도 분석용이며 값 확정 전까지 주석 유지
-- ---------------------------------------------------------------------
TRUNCATE TABLE dim_time_value;
INSERT INTO dim_time_value
  (time_value_code, label, hourly_wage, is_default, source_note) VALUES
  ('minwage', '최저임금 기준', 10320, 1, '2025년 최저임금. Phase 1 총부담 테이블과 동일 기준');
-- 확정 후 주석 해제
-- , ('youth_avg',   '청년 평균임금 기준', 0, 0, '값 미확정')
-- , ('user_income', '사용자 소득 기준',   0, 0, '서비스단 개인화 - 이번 범위 제외')


-- ---------------------------------------------------------------------
-- 소득 시나리오 : 기획안 v2 5단계 (세후 월소득 220~350만원)
-- ---------------------------------------------------------------------
TRUNCATE TABLE dim_income_scenario;
INSERT INTO dim_income_scenario
  (income_code, label, monthly_net_income) VALUES
  ('S1', '세후 220만원', 2200000),
  ('S2', '세후 250만원', 2500000),
  ('S3', '세후 280만원', 2800000),
  ('S4', '세후 310만원', 3100000),
  ('S5', '세후 350만원', 3500000);


-- ---------------------------------------------------------------------
-- 생활비 가정 : ※ 미확정 항목 ※
-- 생활소비부담지수는 강건 z-score라 금액이 아니다.
-- 지수를 금액으로 환산하는 근거가 아직 없으므로 아래 값은 자리표시용이며,
-- 이 값을 쓰는 Q4 결과는 "가정 기반 시산"으로만 해석해야 한다.
-- ---------------------------------------------------------------------
TRUNCATE TABLE dim_living_cost_assumption;
INSERT INTO dim_living_cost_assumption
  (assumption_code, label, base_amount, index_slope, source_note) VALUES
  ('base', '자리표시용 가정(미확정)', 700000, 50000,
   '근거 미확보. 지수는 z-score이므로 금액 환산 규칙을 팀에서 확정해야 함');


-- 확인
SELECT 'dim_time_value' AS tbl, COUNT(*) AS cnt FROM dim_time_value
UNION ALL SELECT 'dim_income_scenario', COUNT(*) FROM dim_income_scenario
UNION ALL SELECT 'dim_living_cost_assumption', COUNT(*) FROM dim_living_cost_assumption;
