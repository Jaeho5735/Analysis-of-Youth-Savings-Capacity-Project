-- =============================================================
-- dim_fallback_candidate
--   표면주거비가 산출되지 않은 행정동을 사용자가 요청했을 때
--   제시할 인근 행정동 후보.
--
--   값을 대체하지 않는다. 후보를 보여주고 사용자가 고른다.
--   화면에 뜨는 동 이름은 항상 그 데이터의 주인이어야 한다.
--
--   선정 절차
--     1) 법정동 공유 기반 자동 추출 (extract_adjacent_by_bjd.py) -> 24행
--     2) 행정동 경계도로 지리적 인접 육안 검증          -> 16행
--   근거는 docs/결측동_인근후보_확정근거.md 참고
-- =============================================================

USE multicam;

DROP TABLE IF EXISTS dim_fallback_candidate;

CREATE TABLE dim_fallback_candidate (
    missing_dong_code   CHAR(8)      NOT NULL COMMENT '표면주거비 결측 행정동',
    candidate_dong_code CHAR(8)      NOT NULL COMMENT '제시할 인근 행정동',
    display_order       TINYINT      NOT NULL COMMENT '화면 노출 순서(인접도 기준, 조정 가능)',
    shared_bjd_name     VARCHAR(30)  NOT NULL COMMENT '공유하는 법정동명 - 안내 문구에 사용',
    verified_by         VARCHAR(30)  NOT NULL COMMENT '육안 검증자',
    verified_on         DATE         NOT NULL,
    note                VARCHAR(200) NULL,
    PRIMARY KEY (missing_dong_code, candidate_dong_code),
    CONSTRAINT fk_fbc_missing   FOREIGN KEY (missing_dong_code)   REFERENCES dim_region (dong_code8),
    CONSTRAINT fk_fbc_candidate FOREIGN KEY (candidate_dong_code) REFERENCES dim_region (dong_code8)
) COMMENT = '결측 행정동 요청 시 제시할 인근 후보 (값 대체 아님)';


INSERT INTO dim_fallback_candidate
    (missing_dong_code, candidate_dong_code, display_order, shared_bjd_name, verified_by, verified_on, note)
VALUES
-- 하계2동 (노원구) : 법정동 하계동을 공유하는 행정동이 하계1동 하나뿐
('11350612', '11350611', 1, '하계동', '신재호', '2026-08-19', NULL),

-- 상계8동 (노원구) : 서쪽은 강북구라 자치구 경계 밖. 상계9동은 함께 결측이라 제외
('11350700', '11350720', 1, '상계동', '신재호', '2026-08-19', '남쪽 인접'),
('11350700', '11350630', 2, '상계동', '신재호', '2026-08-19', '북쪽 인접'),

-- 상계9동 (노원구) : 상계8동은 함께 결측이라 제외
('11350710', '11350630', 1, '상계동', '신재호', '2026-08-19', '북쪽 인접'),
('11350710', '11350670', 2, '상계동', '신재호', '2026-08-19', '남동쪽 인접'),
('11350710', '11350720', 3, '상계동', '신재호', '2026-08-19', '남쪽 인접'),
('11350710', '11350665', 4, '상계동', '신재호', '2026-08-19', '동쪽 인접'),

-- 반포본동 (서초구) : 반포2동은 함께 결측이라 제외
('11650550', '11650560', 1, '반포동', '신재호', '2026-08-19', NULL),
('11650550', '11650581', 2, '반포동', '신재호', '2026-08-19', NULL),

-- 반포2동 (서초구) : 반포본동은 함께 결측이라 제외
('11650570', '11650560', 1, '반포동', '신재호', '2026-08-19', NULL),
('11650570', '11650581', 2, '반포동', '신재호', '2026-08-19', NULL),

-- 오륜동 (송파구) : 법정동 방이동을 공유
('11710566', '11710562', 1, '방이동', '신재호', '2026-08-19', NULL),
('11710566', '11710561', 2, '방이동', '신재호', '2026-08-19', NULL),

-- 잠실7동 (송파구)
('11710720', '11710680', 1, '잠실동', '신재호', '2026-08-19', NULL),
('11710720', '11710650', 2, '잠실동', '신재호', '2026-08-19', NULL),
('11710720', '11710670', 3, '잠실동', '신재호', '2026-08-19', NULL);


-- =============================================================
-- QC
-- =============================================================

-- QC1  16행이 들어갔는가
SELECT COUNT(*) AS 총행수, COUNT(DISTINCT missing_dong_code) AS 결측동수
FROM dim_fallback_candidate;
-- 기대: 16 / 7

-- QC2  후보가 결측 동인 경우가 없는가 (결측끼리 서로 대체 불가)
SELECT c.missing_dong_code, c.candidate_dong_code
FROM dim_fallback_candidate c
LEFT JOIN fact_dong_burden b ON b.dong_code8 = c.candidate_dong_code
WHERE b.dong_code IS NULL;
-- 기대: 0행

-- QC3  후보가 결측 동과 다른 자치구인 경우가 없는가
SELECT missing_dong_code, candidate_dong_code
FROM dim_fallback_candidate
WHERE LEFT(missing_dong_code, 5) <> LEFT(candidate_dong_code, 5);
-- 기대: 0행

-- QC4  결측 7개 동이 모두 후보를 가지는가
SELECT r.dong_code8, r.dong_name
FROM dim_region r
LEFT JOIN fact_dong_burden  b ON b.dong_code8 = r.dong_code8
LEFT JOIN dim_fallback_candidate c ON c.missing_dong_code = r.dong_code8
WHERE b.dong_code IS NULL AND c.missing_dong_code IS NULL;
-- 기대: 0행


-- =============================================================
-- 서비스 조회 : 결측 동 요청 시 안내 + 후보
-- =============================================================

SELECT
    mr.dong_name                         AS 요청동,
    c.shared_bjd_name                    AS 공유법정동,
    cr.dong_name                         AS 후보동,
    c.display_order                      AS 노출순서,
    b.surface_housing_cost                       AS 표면주거비,
    (b.surface_housing_cost + b.monthly_transport_pass + ROUND(b.monthly_commute_hour * 10320))                       AS 통합부담
FROM dim_fallback_candidate c
JOIN dim_region      mr ON mr.dong_code8 = c.missing_dong_code
JOIN dim_region      cr ON cr.dong_code8 = c.candidate_dong_code
JOIN fact_dong_burden b ON b.dong_code  = c.candidate_dong_code
WHERE c.missing_dong_code = :requested_dong_code
ORDER BY c.display_order;