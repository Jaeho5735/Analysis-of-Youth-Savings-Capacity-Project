# src/db/ — CSV를 MySQL로 옮기는 단계

## 왜 필요했나

`reference → preprocessing → indicators → validation → analysis` 까지 돌면 분석은 끝난다. 결과는 CSV로 남고, 그대로도 읽을 수 있다.

이 폴더는 그다음이다. **분석 결과를 조회 가능한 형태로 옮긴다.** 여기서 파이프라인의 성격이 바뀐다.

- 지금까지: 우리가 가끔 돌리는 **구축 단계**
- 여기부터: 사용자가 항상 두드리는 **운영 단계**

두 단계는 시간대가 다르다. 도서관에 책을 꽂는 일과 손님이 책을 찾는 일이 같은 시각에 일어나면 안 되는 것과 같다. 적재는 데이터가 갱신될 때만 돌고, 서비스는 그 결과를 읽기만 한다.

**사용자가 입력한 소득·나이·예산은 DB에 쓰지 않는다.** 계산에만 쓰고 응답 후 버린다. 보관할 이유가 없고, 보관하면 관리 책임이 생긴다.

## 문제였던 점

적재는 `to_sql` 한 줄이면 될 것 같지만, 실제로 걸린 곳은 전부 다른 데였다.

### ① 스키마를 파이썬이 만들게 두면 안 된다

`to_sql(if_exists="replace")`를 쓰면 타입·기본키·인덱스·주석이 전부 날아가고 **행정동코드가 BIGINT로 바뀐다.** 선행 0이 사라지면 결합키가 조용히 깨진다.

그래서 스키마는 `sql/01_schema.sql`이 소유하고, 이 폴더는 `if_exists="append"`만 쓴다.

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

## 하는 일

```
inspect_csv.py     (1회) data/ 아래 CSV 구조 조사
       ↓
load_to_db.py      (갱신 시) CSV -> MySQL 적재
       ↓
check_quarantine.py (적재 후) 격리된 행의 실제 손실 진단
```

### inspect_csv.py

적재 스크립트의 컬럼 매핑을 실제 헤더에 맞추기 위한 **일회용 조사 도구**다.

컬럼명이 한 글자만 달라도 적재가 실패한다. 에러를 보고 하나씩 고치면 파일 수만큼 왕복하게 되므로, 헤더를 한 번에 다 뽑아 한 번에 맞춘다.

`data/` 아래를 재귀로 훑고 출력을 두 단계로 나눈다. 원본 CSV가 수십 개라 전부 컬럼을 찍으면 읽기 힘들다.

- 1부: 전체 목록 (폴더별 파일명·행수·컬럼수)
- 2부: 적재 대상 후보만 컬럼 전체와 값 예시

앞 5행만 읽으므로 16만 행 파일도 몇 초면 끝난다. 인코딩은 utf-8 → cp949 → euc-kr 순으로 자동 판별한다.

**입력** `data/**/*.csv`
**출력** `csv_headers.txt` (프로젝트 루트)

### load_to_db.py

CSV 8종을 읽어 MySQL 테이블 9개에 넣는다. FK 의존 순서대로 돌고, 삭제는 역순이다.

접속 정보는 `.env`에서 읽는다. 비밀번호를 코드에 넣지 않기 위해서다(`.gitignore` 필수).

병합이 필요한 곳이 두 군데 있다.

- **`fact_dong_burden`** — 통합부담 + 업무중심성(주야간 인구비) + 유형화 결과(청년1인세대비율)를 코드8 기준으로 결합
- **`fact_commute_od`** — 전체 OD(164,860행)와 80% 컷(30,839행)을 한 테이블에 담고 `is_top80` 플래그로 구분. 80% 컷의 `최종_가중치`는 대표 통근시간 산출 근거이자 Tmap 호출 대상이라 재현성을 위해 보관해야 한다. 교체가 아니라 역할 분담이다

파이썬이 계산한 순위와 부담유형을 `rank_housing_src` / `rank_burden_src` / `burden_type_src`로 같이 넣는다. **적재 과정에서 값이 뒤틀리지 않았는지 SQL로 대조하기 위한 것**이다(`sql/02_qc.sql` QC5).

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

**출력** MySQL `multicam` 스키마, `data/quarantine/*_orphan.csv`

`dim_business_district`는 CSV에 없다. `업무지구_정의.csv` 40행을 지구명으로 group by 해서 9행을 만들고, `district_id`가 AUTO_INCREMENT라 DB에서 다시 읽어 bridge에 매핑한다.

### check_quarantine.py

격리된 행이 **실제로 얼마나 손실인지** 진단한다.

행 수만 보면 판단할 수 없다. OD 828행이 빠져도 이동량 비중이 0.01%면 무시해도 되고, 1%를 넘으면 그 지역 통근이 통째로 사라진 것이라 대응이 필요하다. 그래서 행 수가 아니라 **총량 비중**을 잰다.

0.5%를 넘으면 검토 필요로 판정하되, 배분 여부 같은 판단은 사람이 한다. 폐지 행정동은 1:N 분동이라 이동량을 나눌 근거가 없어 임의 안분보다 제외 후 기록이 안전하다.

**입력** `data/quarantine/*_orphan.csv` + 대응 원본 CSV
**출력** 콘솔 진단 (판정 포함)

## 적재 실적

| 테이블 | 적재 | 격리 |
|---|---|---|
| `dim_region` | 427 | — |
| `dim_business_district` | 9 | — |
| `bridge_district_dong` | 40 | — |
| `fact_dong_burden` | 420 | — |
| `fact_dong_type` | 427 | — |
| `fact_dong_type_features` | 427 | — |
| `fact_commute_od` | 164,032 | 828 |
| `fact_commute_route` | 30,636 | 203 |
| `fact_rent_transaction` | 577,745 | 16 |

QC 7종 전항목 통과. 순위 재현 불일치 10개는 표면주거비 INT 반올림 차이로 diff가 전부 ±1이었다.

유형화 결과는 팀원A의 FuzzyCMeans k=6 산출물(`dong_typology_final.csv`)을 쓴다. 427행 전체를 넣고 유형이 없는 7개 동은 `type_name` NULL + `flag_insufficient=1`로 남긴다. 군집 입력 변수는 `fact_dong_type_features`에 스냅샷으로 따로 보관하는데, 집계 기준이 다를 수 있어(표면주거비는 거래단위 pooled 중앙값) 재현성을 위해서다.

## 요약

| 파일 | 역할 | 실행 주기 |
|---|---|---|
| `inspect_csv.py` | CSV 구조 조사 | 컬럼이 바뀔 때만 |
| `load_to_db.py` | CSV → MySQL 적재 | 데이터 갱신 시 |
| `check_quarantine.py` | 격리 행 손실 진단 | 적재 직후 |

스키마와 조회 쿼리는 `sql/`에 있다. 이 폴더는 그 사이를 잇는 다리다.