# src/db/ — CSV를 MySQL로 옮기고, 다시 꺼내는 단계

## 왜 필요했나

`reference → preprocessing → indicators → validation → analysis` 까지 돌면 분석은 끝난다. 결과는 CSV로 남고, 그대로도 읽을 수 있다.

이 폴더는 그다음이다. **분석 결과를 조회 가능한 형태로 옮기고, 서비스가 쓸 수 있게 꺼내준다.** 여기서 파이프라인의 성격이 바뀐다.

- 지금까지: 우리가 가끔 돌리는 **구축 단계**
- 여기부터: 사용자가 항상 두드리는 **운영 단계**

두 단계는 시간대가 다르다. 도서관에 책을 꽂는 일과 손님이 책을 찾는 일이 같은 시각에 일어나면 안 되는 것과 같다. 적재는 데이터가 갱신될 때만 돌고, 서비스는 그 결과를 읽기만 한다.

**사용자가 입력한 소득·나이·예산은 DB에 쓰지 않는다.** 계산에만 쓰고 응답 후 버린다. 보관할 이유가 없고, 보관하면 관리 책임이 생긴다.

## 문제였던 점

적재는 `to_sql` 한 줄이면 될 것 같지만, 실제로 걸린 곳은 전부 다른 데였다.

### ① 스키마를 파이썬이 만들게 두면 안 된다

`to_sql(if_exists="replace")`를 쓰면 타입·기본키·인덱스·주석이 전부 날아가고 **행정동코드가 BIGINT로 바뀐다.** 선행 0이 사라지면 결합키가 조용히 깨진다.

그래서 스키마는 `sql/init/01_schema.sql`이 소유하고, 이 폴더는 `if_exists="append"`만 쓴다.

### ② 코드 컬럼은 무조건 문자열로 읽는다

`행정동코드_최종`이 `1111065000.0` 같은 실수로 저장돼 있다. 그냥 `astype(str)`을 하면 `.0`이 붙는다. 실수 → 정수 → 10자리 문자열 → 앞 8자리 순으로 변환해야 한다.

### ③ 천단위 콤마가 메모리를 터뜨렸다

`표면주거비_거래단위.csv`의 `보증금(만원)`에 `"1,000"` 형태가 섞여 있어 컬럼이 문자열로 읽혔다. 여기에 `* 10000`을 하면 파이썬은 곱셈이 아니라 **문자열 반복**으로 해석한다. 57만 행에서 `MemoryError`가 났다.

숫자로 쓸 컬럼은 콤마를 제거하고 `to_numeric`으로 변환한 뒤, 변환 실패가 하나라도 있으면 중단한다. 조용히 NaN으로 넘어가면 나중에 잘못된 집계가 나온다.

### ④ 기준표에 없는 코드를 조용히 버리지 않는다

OD에는 폐지된 용신동이 남아 있다. 신설동·용두동으로 1:N 분동돼 이동량을 나눌 근거가 없다. 그냥 drop 하면 왜 없어졌는지 아무도 모른다.

**`data/quarantine/`에 CSV로 떨어뜨리고 건수를 로그에 남긴다.** 프로젝트 전체 원칙(제외 대신 플래그)의 적재판이다.

### ⑤ 멱등성

실행할 때마다 `TRUNCATE` 후 재적재한다. 중간에 실패해도 상태가 꼬이지 않고, 몇 번을 돌려도 결과가 같다.

### ⑥ 컬럼명을 추측하면 조용히 틀린다

조회 계층을 만들면서 세 번 겪었다. 부분문자열로 컬럼을 찾으면 **먼저 나오는 쪽이 이긴다.**

| 찾으려던 것 | 실제로 잡힌 것 | 결과 |
|---|---|---|
| `행정동코드_최종` (420개) | `행정동코드` (보정 전 215개) | 집계 대상이 절반 |
| `교통비_산출포함률` (실수) | `교통비_커버리지부족` (불리언) | 전부 NaN |
| `교통비_산출포함률` | `월교통비_실지출_원` | 컬럼 못 찾고 건너뜀 |

두 번째가 특히 나빴다. 불리언을 숫자로 읽어 전부 NaN이 되고 결과가 **"교통비 커버리지 미달 0개"**로 나왔다. 실제로는 9개다. 에러로 죽었으면 차라리 나았을 텐데 **"안전하다"는 거짓 신호**를 냈다.

그래서 `query_dong.py`는 컬럼을 자동 감지하지 않는다. 파일 상단 `COLS`에 실제 이름을 적어두고, `--inspect`로 확인한 뒤에 쓴다.

## 하는 일

```
inspect_csv.py      (1회)    data/ 아래 CSV 구조 조사
       ↓
run_sql.py          (갱신 시) 스키마·QC SQL 파일 실행
       ↓
load_to_db.py       (갱신 시) CSV -> MySQL 적재
       ↓
check_quarantine.py (적재 후) 격리된 행의 실제 손실 진단
       ↓
query_dong.py       (운영)    MySQL -> 서비스 응답
```

앞의 네 개는 구축 단계, 마지막 하나는 운영 단계다.

### inspect_csv.py

적재 스크립트의 컬럼 매핑을 실제 헤더에 맞추기 위한 **일회용 조사 도구**다.

컬럼명이 한 글자만 달라도 적재가 실패한다. 에러를 보고 하나씩 고치면 파일 수만큼 왕복하게 되므로, 헤더를 한 번에 다 뽑아 한 번에 맞춘다.

`data/` 아래를 재귀로 훑고 출력을 두 단계로 나눈다. 원본 CSV가 수십 개라 전부 컬럼을 찍으면 읽기 힘들다.

- 1부: 전체 목록 (폴더별 파일명·행수·컬럼수)
- 2부: 적재 대상 후보만 컬럼 전체와 값 예시

앞 5행만 읽으므로 16만 행 파일도 몇 초면 끝난다. 인코딩은 utf-8 → cp949 → euc-kr 순으로 자동 판별한다.

**입력** `data/**/*.csv`
**출력** 콘솔. 필요하면 `> csv_headers.txt` 로 리다이렉트해 쓴다.
결과물은 일회성 조사 로그라 저장소에 두지 않는다.

### run_sql.py

`.env` 접속 정보로 SQL 파일을 실행한다.

MySQL CLI 를 쓰면 되지 않느냐 싶지만 두 가지가 걸렸다. **PowerShell 은 `<`
리다이렉션을 지원하지 않고**, `.env` 값은 셸 환경변수가 아니라 파일에만 있어서
`mysql -u $env:MYSQL_USER` 가 빈 값으로 들어간다. `mysql` 이 PATH 에 없는
환경도 있었다.

주석과 빈 줄을 걷어내고 세미콜론으로 문장을 나눠 하나씩 실행한다. **한
커넥션을 유지**하므로 `PREPARE` / `EXECUTE` 같은 세션 의존 구문도 동작한다.
문장별로 성공·실패를 찍고, 결과가 있는 쿼리는 값까지 출력해 QC 판정을 바로
볼 수 있다.

```
python src/db/run_sql.py sql/init/03_transport_pass_assumption.sql
python src/db/run_sql.py sql/qc/02_qc_transport_pass.sql
```

**입력** SQL 파일, `.env`
**출력** 문장별 실행 결과 (실패 시 종료코드 1)

### load_to_db.py

CSV를 읽어 MySQL 테이블 12개에 넣는다. FK 의존 순서대로 돌고, 삭제는 역순이다.

접속 정보는 `.env`에서 읽는다. 비밀번호를 코드에 넣지 않기 위해서다(`.gitignore` 필수).

병합이 필요한 곳이 두 군데 있다.

- **`fact_dong_burden`** — 통합부담 + 업무중심성(주야간 인구비) + 유형화 결과(청년1인세대비율)를 코드8 기준으로 결합
- **`fact_commute_od`** — 전체 OD(164,860행)와 80% 컷(30,839행)을 한 테이블에 담고 `is_top80` 플래그로 구분. 80% 컷의 `최종_가중치`는 대표 통근시간 산출 근거이자 Tmap 호출 대상이라 재현성을 위해 보관해야 한다. 교체가 아니라 역할 분담이다

파이썬이 계산한 순위와 부담유형을 `rank_housing_src` / `rank_burden_src` / `burden_type_src`로 같이 넣는다. **적재 과정에서 값이 뒤틀리지 않았는지 SQL로 대조하기 위한 것**이다(`sql/qc/01_qc.sql` QC5).

**입력** 아래 8개 파일

| CSV | 테이블 |
|---|---|
| `행정동_기준코드표.csv` | `dim_region` |
| `업무지구_정의.csv` | `dim_business_district` + `bridge_district_dong` |
| `주거통근_통합부담_행정동별.csv` + `업무중심성_행정동별.csv` + `dong_typology_final.csv` | `fact_dong_burden` |
| `dong_typology_final.csv` | `fact_dong_type` + `fact_dong_type_features` |
| `all_age_commute_od_aggregated.csv` + `all_age_commute_od_selected_80.csv` | `fact_commute_od` |
| `commute_routes_analysis_ready.csv` | `fact_commute_route` |
| `표면주거비_거래단위.csv` | `fact_rent_transaction` |
| `정기권_가정.csv` | `dim_transport_pass_assumption` |

정책 조건표(`dim_policy`, 12행)도 `LOAD_ORDER`에 포함된다.

**출력** MySQL `multicam` 스키마, `data/quarantine/*_orphan.csv`

**정기권 가정은 CSV 가 원천이다.** `data/정기권_가정.csv` 를 읽어
`dim_transport_pass_assumption` 에 넣는데, 같은 파일을
`src/analysis/build_total_burden.py` 도 읽는다. DB 에만 값을 두면 CSV 산출물과
DB 가 서로 다른 요금 기준을 보게 되므로 원천을 한 곳으로 묶었다.

적재 시점에 두 가지를 막는다. `is_default=1` 이 정확히 1행이 아니면 중단하고,
통합부담 CSV 의 `정기권_가정코드` 가 DB 기본 가정과 다르면 경고와 함께 재산출
명령어를 안내한다. 화면에는 A 요금 기준 금액이 뜨는데 조회 계층은 B 요금으로
계산하는 어긋남을 조용히 넘기지 않기 위해서다.

`dim_business_district`는 CSV에 없다. `업무지구_정의.csv` 40행을 지구명으로 group by 해서 9행을 만들고, `district_id`가 AUTO_INCREMENT라 DB에서 다시 읽어 bridge에 매핑한다.

서비스용 테이블 두 개(`dim_dong_reliability`, `dim_fallback_candidate`)는 이 스크립트가 넣지 않는다. CSV가 아니라 `sql/load/` 의 SQL 파일이 DDL과 데이터를 함께 갖고 있다.

**다만 이 스크립트보다 먼저 돌릴 수 없다.** 두 테이블의 FK가 `dim_region(dong_code8)` 을 참조하는데 `dim_region` 은 여기서 채우기 때문이다. `sql/init/` 과 `sql/load/` 가 폴더로 갈려 있는 이유이며, 자세한 것은 `sql/README.md` 를 참고한다.

### check_quarantine.py

격리된 행이 **실제로 얼마나 손실인지** 진단한다.

행 수만 보면 판단할 수 없다. OD 828행이 빠져도 이동량 비중이 0.01%면 무시해도 되고, 1%를 넘으면 그 지역 통근이 통째로 사라진 것이라 대응이 필요하다. 그래서 행 수가 아니라 **총량 비중**을 잰다.

0.5%를 넘으면 검토 필요로 판정하되, 배분 여부 같은 판단은 사람이 한다. 폐지 행정동은 1:N 분동이라 이동량을 나눌 근거가 없어 임의 안분보다 제외 후 기록이 안전하다.

**입력** `data/quarantine/*_orphan.csv` + 대응 원본 CSV
**출력** 콘솔 진단 (판정 포함)

---

## query_dong.py — 조회 계층

### 왜 필요했나

웹이 SQL을 직접 쓰게 두면 두 가지가 무너진다.

첫째, **상태 판단이 화면마다 흩어진다.** "이 동은 주거비가 없다", "이 동은 배정을 못 믿는다" 같은 판단을 페이지마다 다시 짜면 기준이 어긋난다.

둘째, **계산 규칙이 복제된다.** 총부담과 시간비용은 컬럼에 없고 조회 시점에 계산한다. 이 산식이 여러 곳에 흩어지면 시간가치를 바꿀 때 한 군데를 빠뜨린다.

그래서 조회를 함수 하나로 모았다. 웹은 이 함수만 호출하면 되고 SQL을 몰라도 된다.

### 하는 일

행정동 하나를 조회해 `docs/LOCA_응답계약.md`의 status 4종 JSON을 돌려준다.

```python
from src.db.query_dong import get_dong, get_dong_by_name

get_dong("11710566", work_code="11680640")   # 코드로, 근무지 기준
get_dong_by_name("마장동")                     # 이름으로. 여러 개면 ambiguous
```

**`work_code` 를 받는 것이 중요하다.** 근무지를 주면 `fact_commute_route`
(거주동 × 근무동)에서 실제 경로값을 가져온다. 주지 않으면 거주동 평균값으로
물러서는데, 그건 "이 동에서 강남까지 몇 분"이 아니라 "이 동 사람들이 평균
몇 분 걸린다"라 근무지 비교에는 쓸 수 없다.

| status | 조건 | 응답에 담기는 것 |
|---|---|---|
| `ok` | 정상 | 부담 지표 + 유형 + 거래 수 |
| `low_confidence` | 신뢰도 낮음 | 위 + `notice` + `reasons` |
| `unreliable` | 배정 신뢰 불가 | 위 + `warning` |
| `no_data` | 주거비 미산출 | 사유 + 인근 후보 목록 |
| `ambiguous` | 이름이 여러 행정동에 걸침 | 후보 행정동 목록 |

`unreliable`과 `low_confidence`는 **값이 있다.** 숨기지 않고 라벨만 붙인다. 값이 없는 것은 `no_data`뿐이다.

### 서비스가 쓰는 조회 함수

`get_dong` 하나로는 화면을 못 만든다. 자동완성·추천·대체 처리가 전부 별도
질의라, 웹이 SQL 을 쓰지 않도록 여기에 모았다.

| 함수 | 하는 일 | 왜 필요했나 |
|---|---|---|
| `list_dongs(q)` | 행정동 부분일치 검색 | 입력 자동완성 |
| `list_work_options(home_code, q)` | 그 거주지에서 **갈 수 있는** 근무지 | 없는 조합 선택을 입력 단계에서 차단 |
| `list_home_options(work_code, q)` | 그 근무지로 **갈 수 있는** 거주지 | 후보 지역 자동완성 |
| `nearest_routed_work(home, work)` | 경로 없을 때 인근 대체 근무동 | 화면이 비는 것을 막는다 |
| `recommend_dongs(work_code)` | 총부담 낮은 거주동 추천 | 근무지 기준 개인화의 핵심 |

**범위를 좁히는 두 함수가 이 구조의 요점이다.** 경로는 거주동별 누적 80%
목적지까지만 있어서(거주동당 평균 72곳, 427개 중 약 17%) 전체를 열어두면
사용자가 없는 조합을 고르고 결과 화면에서야 실패를 알게 된다. 실패를 잘
안내하는 것보다 애초에 고를 수 없게 하는 편이 낫다.

`recommend_dongs` 는 총부담 순으로 정렬한 뒤 **행정동 유형별로 한 곳씩만**
남긴다. 같은 유형이 세 개 나오면 선택지가 사실상 하나이기 때문이다. 표본이
부실한 동(`no_data`·`unreliable`)은 후보에서 뺀다. 참고용 딱지가 붙은 값을
"여기가 더 낫습니다"로 내세울 수는 없다.

### 계산 규칙

`fact_dong_burden`에 총부담·시간비용 컬럼이 없다. 시간가치 가정을 컬럼에 박지 않기로 한 결과다(`sql/README.md` 설계원칙 ①).

```
시간비용 = monthly_commute_hour × TIME_VALUE_PER_HOUR(10,320원)
총부담   = surface_housing_cost + 교통비 + 시간비용
```

교통비는 `FARE_MODE` 상수로 고른다. `"pass"`(정기권 캡) 또는 `"actual"`(실지출). 응답에는 선택된 값과 양쪽 원본을 모두 담아, 화면에서 "실지출 기준으로는 얼마"를 병기할 수 있게 했다.

`TRANSIT_PASS_CAP` 은 55,000원이다. 2026-09-01 기후동행카드가 **모두의카드**로
대체됐고, 정액형은 기준선을 넘는 금액을 100% 환급하므로 계산상 기준선이 곧
실질 상한이다. 청년(만 19~39세) 55,000 / 일반 62,000이며, 이 값은
`dim_transport_pass_assumption` 의 기본 가정과 같아야 한다. 여기만 옛 값이면
조회 결과가 화면·CSV 와 어긋난다.

`fact_dong_type`은 `(dong_code8, k_value)` 복합키라 `K_VALUE = 6`으로 조인한다. 이 조건을 빼면 `dong_type`이 NULL로 나온다.

MySQL `DECIMAL`은 파이썬에서 `Decimal` 객체로 온다. Flask의 `jsonify`가 직렬화하지 못하므로 응답 직전에 int/float으로 바꾼다.

### 접속 정보

`.env`에서 읽는다. **비밀번호를 코드에 적지 않는다.** 키 이름이 프로젝트마다 다를 수 있어 후보를 순서대로 훑는다(`MYSQL_PASSWORD` / `DB_PASSWORD` / `DB_PW` 등).

```
python src/db/query_dong.py --env       # 접속 설정 확인 (비밀번호 값은 안 찍음)
python src/db/query_dong.py --inspect   # 테이블 스키마 확인
python src/db/query_dong.py 마장동        # 조회 시험
```

`--env`가 `password (설정됨)`을 찍으면 준비된 것이다.

### 해결된 문제 — 근무지 무관 통근시간

한동안 `fact_dong_burden.oneway_commute_min` 을 그대로 썼다. 거주동 거주자의
모든 목적지를 가중평균한 값이라 **"이 동에서 강남까지 몇 분"이 아니었다.**
시간비용과 총부담이 이 값에 의존해 근무지 기준 비교가 성립하지 않았다.

지금은 `get_dong(code, work_code=...)` 가 `fact_commute_route` 에서 그 조합의
실제 경로값을 가져온다. 근무지를 주지 않았을 때만 평균값으로 물러선다.

### 남은 제약

**경로가 없는 조합이 있다.** 거주동별 누적 80% 목적지만 Tmap 호출했기 때문에
흐름이 적은 조합은 빠져 있다. `nearest_routed_work` 로 인근 근무동을 대신 쓰되,
**대체했다는 사실을 응답에 담아 화면에서 밝히도록** 했다.

**승하차역 시퀀스가 없다.** `fact_commute_route` 에 노선명·환승횟수는 있어도
역 목록이 없어, 화면은 수단·노선 순서까지만 보여준다.

**입력** MySQL `multicam` 스키마, `.env`
**출력** status 4종 JSON

---

## 적재 실적

스키마에 정의된 테이블은 **17개 + 뷰 2개**이고, 채우는 주체가 셋으로 나뉜다.
한 곳만 세면 숫자가 맞지 않는다.

**① `load_to_db.py` — CSV 적재 (12개)**

| 테이블 | 적재 | 격리 |
|---|---|---|
| `dim_region` | 427 | — |
| `map_region_legacy` | 11 | — |
| `dim_business_district` | 9 | — |
| `bridge_district_dong` | 40 | — |
| `fact_dong_burden` | 420 | — |
| `fact_dong_type` | 427 | — |
| `fact_dong_type_features` | 427 | — |
| `fact_commute_od` | 164,032 | 828 |
| `fact_commute_route` | 30,636 | 203 |
| `fact_rent_transaction` | 577,745 | 16 |
| `dim_transport_pass_assumption` | 5 | — |
| `dim_policy` | 12 | — |

**② `sql/init/02_seed_params.sql` — SQL 시드 (3개)**

CSV 원천이 없는 가정값이다. 값을 바꾸려면 그 파일을 고쳐 다시 실행한다.

| 테이블 | 적재 |
|---|---|
| `dim_time_value` | 1 |
| `dim_income_scenario` | 5 |
| `dim_living_cost_assumption` | 1 (시드 파일은 3행) |

**③ `sql/load/` — SQL 파일 자체 INSERT (2개)**

| 테이블 | 적재 |
|---|---|
| `dim_dong_reliability` | 427 |
| `dim_fallback_candidate` | 16 |

스키마의 17개 테이블이 모두 채워진다.

**폐지 행정동 매핑은 CSV 9행이 DB 11행이 된다.** `현행코드8` 이 분동 케이스에서
세미콜론으로 여러 코드를 담기 때문이다.

```
11230536 용신동  ->  11230515;11230533   (신설동 + 용두동)
```

PK 가 `(legacy_code8, current_code8)` 복합키라 코드마다 한 행으로 펼쳐야 한다.
그대로 넣으면 `CHAR(8)` 컬럼에 17글자가 들어간다. 1:N 분동 2건(용신동·상일동)이
각각 2행이 되어 9 + 2 = 11행이다.

`legacy_code8` 은 기준표 대조에서 제외한다. **폐지된 코드가 현행 기준표에 없는
것은 정상**이기 때문이다. 격리 검사는 `current_code8` 만 한다.

QC 7종 전항목 통과. 정기권 QC(`sql/qc/02_qc_transport_pass.sql`) 7종도 통과했고,
420개 동 **전부가 정기권 상한 초과**로 나왔다. 실지출이 모든 동에서 55,000원을
넘는다는 뜻이라, 교통비는 지역 간 차이를 만들지 못한다. 순위 재현 불일치 10개는 표면주거비 INT 반올림 차이로 diff가 전부 ±1이었다.

유형화 결과는 팀원A의 FuzzyCMeans k=6 산출물(`dong_typology_final.csv`)을 쓴다. 427행 전체를 넣고 유형이 없는 7개 동은 `type_name` NULL + `flag_insufficient=1`로 남긴다. 군집 입력 변수는 `fact_dong_type_features`에 스냅샷으로 따로 보관하는데, 집계 기준이 다를 수 있어(표면주거비는 거래단위 pooled 중앙값) 재현성을 위해서다.

## 요약

| 파일 | 역할 | 실행 주기 |
|---|---|---|
| `inspect_csv.py` | CSV 구조 조사 | 컬럼이 바뀔 때만 |
| `run_sql.py` | SQL 파일 실행 | 스키마·QC 실행 시 |
| `load_to_db.py` | CSV → MySQL 적재 | 데이터 갱신 시 |
| `check_quarantine.py` | 격리 행 손실 진단 | 적재 직후 |
| `query_dong.py` | MySQL → 서비스 응답 | 요청마다 |

스키마와 조회 쿼리는 `sql/`에 있다. 이 폴더는 그 사이를 잇는 다리이고, `query_dong.py`부터는 서비스 쪽으로 건너간다. 웹에서 어떻게 쓰이는지는 `web/README.md` 참고.