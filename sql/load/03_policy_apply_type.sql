-- =====================================================================
-- dim_policy 신청 형태·기준일 컬럼 추가 및 데이터 갱신
--
-- 왜 필요한가
--   정책은 바뀐다. 실시간 API 를 붙이지 않기로 한 대신, 언제 기준의
--   정보인지를 화면에 밝히고 원문으로 보낸다. 여기까지가 우리가 지킬
--   수 있는 선이다.
--
--   특히 기간제 사업은 접수가 끝나도 조건만 보면 통과한다. 실제로
--   '청년 부동산 중개보수 및 이사비 지원'은 2026 하반기 접수가
--   8/31 에 마감됐는데 매칭 목록에 그대로 떠 있었다. 조건 매칭과
--   신청 가능 여부는 다른 것이라, 컬럼으로 분리한다.
--
-- 실행: 이 파일은 데이터가 적재된 뒤에 돌린다(sql/load/ 와 같은 단계).
-- 멱등: 컬럼 추가는 information_schema 로 가드, 갱신은 UPDATE 라
--       여러 번 돌려도 결과가 같다.
-- =====================================================================

-- ── 0) 문자셋 고정 ───────────────────────────────────────────────
--     Windows 콘솔에서 mysql 클라이언트가 EUC-KR 로 접속하면 이 파일의
--     한글 리터럴('상시' 등)이 euckr_korean_ci 로 들어와 테이블의
--     utf8mb4_0900_ai_ci 와 충돌한다(Error 1267). 클라이언트 옵션에
--     의존하지 않도록 파일 안에서 고정한다.
SET NAMES utf8mb4;


-- ── 1) 컬럼 추가 ─────────────────────────────────────────────────
--     이미 있어도, ENUM 값이 깨진 채로 만들어졌으면 다시 만든다.
--     (EUC-KR 접속으로 한 번 돌리면 ENUM 목록에 깨진 한글이 박혀서
--      이후 '상시' 를 넣어도 Error 1265 로 잘린다. 그 상태를 스스로 고친다.)
SET @has = (SELECT COUNT(*) FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'dim_policy'
               AND COLUMN_NAME = 'apply_type');
SET @ok  = (SELECT COUNT(*) FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'dim_policy'
               AND COLUMN_NAME = 'apply_type'
               AND COLUMN_TYPE LIKE '%상시%');

-- 깨진 컬럼이면 먼저 떨어낸다.
SET @sql = IF(@has = 1 AND @ok = 0,
    'ALTER TABLE dim_policy
       DROP COLUMN apply_type,
       DROP COLUMN apply_period_note,
       DROP COLUMN as_of',
    "SELECT '정리 불필요' AS msg");
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 없으면(또는 방금 떨어냈으면) 새로 만든다.
SET @sql = IF(@has = 0 OR @ok = 0,
    "ALTER TABLE dim_policy
       ADD COLUMN apply_type ENUM('상시','기간제','수시') NULL
           COMMENT '신청 형태. 기간제는 공고 기간에만 신청 가능',
       ADD COLUMN apply_period_note VARCHAR(100) NULL
           COMMENT '모집 시기 안내 문구',
       ADD COLUMN as_of DATE NULL
           COMMENT '이 행의 내용을 확인한 날짜'",
    "SELECT '이미 적용됨' AS msg");
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;


-- ── 2) 기본값: 전부 2026-08-05 기준으로 수령한 자료 ───────────────
UPDATE dim_policy
   SET as_of = COALESCE(as_of, '2026-08-05'),
       apply_type = COALESCE(apply_type, '상시');


-- ── 3) 기간제 사업 표시 ──────────────────────────────────────────
--     연 2회 모집이라 조건이 맞아도 지금 신청할 수 없는 시기가 있다.
UPDATE dim_policy
   SET apply_type = '기간제',
       apply_period_note = '연 2회 모집(상·하반기). 모집 시기 확인 필요'
 WHERE policy_name = '청년 부동산 중개보수 및 이사비 지원';

--     공고 단위로 모집한다. 상시가 아니다.
UPDATE dim_policy
   SET apply_type = '기간제',
       apply_period_note = '공고별 모집. 입주자 모집 공고 확인 필요'
 WHERE policy_name = '행복주택 공급';

--     서울시 청년월세지원도 모집 공고 단위다.
UPDATE dim_policy
   SET apply_type = '기간제',
       apply_period_note = '모집 공고 시기 확인 필요'
 WHERE policy_name = '서울시 청년 월세 지원';

--     희망두배 청년통장은 연 1회 모집.
UPDATE dim_policy
   SET apply_type = '기간제',
       apply_period_note = '연 1회 모집. 모집 시기 확인 필요'
 WHERE policy_name = '희망두배 청년통장';


-- ── 4) K-패스 → 모두의카드 개편 반영 ─────────────────────────────
--     2026-01 모두의카드로 확대 개편됐고, 2026-09-01 서울시 특화
--     '기후동행패스'가 출시되면서 청년 기준이 만 39세로 확대됐다.
--     기존 행은 개편 전 상태(age_max 없음, 금액 없음)라 갱신한다.
--
--     이 프로젝트가 쓰는 정기권 가정(청년 월 55,000원)과 청년 정의
--     (20~39세)가 여기서 맞아떨어진다. 서울 특화 청년은 만 39세까지
--     30% 환급 또는 월 55,000원 정액 중 유리한 쪽이 적용된다.
UPDATE dim_policy
   SET policy_name = '모두의카드(기후동행패스)',
       provider = '국토교통부·서울특별시',
       age_max = 39,
       benefit_amount = 55000,
       benefit_unit = 'month',
       apply_type = '상시',
       apply_period_note = NULL,
       as_of = '2026-09-06'
 WHERE policy_name = 'K-패스';


-- ── 5) 확인 ──────────────────────────────────────────────────────
SELECT burden_tag AS 태그, policy_name AS 정책명,
       apply_type AS 신청형태,
       COALESCE(apply_period_note, '-') AS 모집안내,
       as_of AS 기준일
  FROM dim_policy
 ORDER BY burden_tag, policy_name;

SELECT apply_type AS 신청형태, COUNT(*) AS 건수
  FROM dim_policy GROUP BY apply_type;