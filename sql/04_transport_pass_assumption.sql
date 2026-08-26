-- 04_transport_pass_assumption.sql
-- 정기권 가정 테이블 + fact_dong_burden 재현성 컬럼 추가.
-- seed 데이터는 여기에 INSERT 하지 않는다. data/정기권_가정.csv 가 단일 원천이고
-- load_to_db.py 가 그 파일을 읽어 적재한다. SQL 에도 값을 박으면 두 곳이 어긋난다.

CREATE TABLE IF NOT EXISTS dim_transport_pass_assumption (
  assumption_code  VARCHAR(32)  NOT NULL COMMENT '가정 식별 코드',
  assumption_name  VARCHAR(64)  NOT NULL COMMENT '표시용 이름',
  monthly_cap      INT          NOT NULL COMMENT '월 정기권 상한(원)',
  target_age_min   TINYINT      NULL     COMMENT '적용 최소 연령. NULL=제한없음',
  target_age_max   TINYINT      NULL     COMMENT '적용 최대 연령. NULL=제한없음',
  is_default       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '기본 가정. 정확히 1행만 1',
  valid_from       DATE         NULL     COMMENT '적용 시작일. NULL=상시',
  valid_to         DATE         NULL     COMMENT '적용 종료일. NULL=상시',
  source_note      VARCHAR(255) NULL     COMMENT '근거·주의사항',
  PRIMARY KEY (assumption_code),
  KEY idx_default (is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='정기권 월 상한 가정. 요금이 바뀌거나 시나리오를 늘릴 때 행만 추가한다';


-- fact_dong_burden 에 어떤 가정으로 산출된 값인지 남긴다.
-- 이게 없으면 DB 안의 monthly_transport_pass 가 어느 요금 기준인지 알 수 없다.
-- MySQL 은 ADD COLUMN IF NOT EXISTS 를 지원하지 않아 information_schema 로 막는다.
SET @sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fact_dong_burden'
      AND COLUMN_NAME = 'transport_pass_code') = 0,
  'ALTER TABLE fact_dong_burden
     ADD COLUMN transport_pass_code VARCHAR(32) NULL COMMENT ''산출에 쓴 정기권 가정'',
     ADD COLUMN flag_fare_imputed TINYINT(1) NOT NULL DEFAULT 0
       COMMENT ''교통비 결측을 정기권 상한으로 대체한 동'' ',
  'SELECT ''이미 적용됨 - 건너뜀'' AS msg');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;


-- FK 는 적재 순서를 강제하려는 목적이므로 컬럼 추가 이후에 건다.
SET @sql := IF(
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'fact_dong_burden'
      AND CONSTRAINT_NAME = 'fk_burden_pass') = 0,
  'ALTER TABLE fact_dong_burden
     ADD CONSTRAINT fk_burden_pass FOREIGN KEY (transport_pass_code)
     REFERENCES dim_transport_pass_assumption(assumption_code)',
  'SELECT ''FK 이미 있음 - 건너뜀'' AS msg');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
