# src/utils/ — 공용 모듈

## dong_names.py

행정동명 표기를 정규화하는 함수 모음. `resolve_precise_jibun.py`(전처리)와 `calc_consumption_burden_index.py`(지표 산출) 양쪽에서 같은 로직이 필요해서 여기로 뽑아냈다. 처음엔 두 파일에 각각 복제해서 썼는데, 정규식을 하나 고칠 때마다 두 곳을 똑같이 고쳐야 하는 게 유지보수 비용이 컸다.

### 왜 정규화가 필요한가

카카오/juso API나 서로 다른 정부 데이터 소스가 같은 행정동을 다른 표기로 내려준다.

- "가양1동" vs "가양제1동" — "제"가 붙는지 여부가 동마다 제각각이라 일괄 규칙으로는 못 잡는다
- "면목3.8동" vs "면목제3.8동" — 번호에 점(.)이 낀 합성동도 마찬가지
- "금호2.3가동" vs "금호2?3가동" — 원본 파일 인코딩 손상으로 마침표가 물음표로 깨지는 경우도 있었다

## 함수

### `load_official_ref(path)`
`dong_matcher.py`가 만든 공식 행정동 참조표(`행정동_공식명_목록.csv`)를 읽는다. 컬럼: `시군구명`, `행정동명`, `행정동코드`.

### `fix_encoding_artifacts(value)`
숫자 사이의 물음표(`?`)를 마침표(`.`)로 되돌린다. `(?<=\d)\?(?=\d)` 형태의 lookahead/lookbehind를 써서, "1?2?3?4"처럼 물음표가 연달아 있어도 숫자를 소모하지 않고 전부 독립적으로 처리한다 (단순 치환은 겹치는 패턴에서 절반만 고쳐지는 버그가 있었다).

### `normalize_dong_name(value, official_set)`
메인 함수. 순서대로 시도한다.
1. 시/도·구 접두어가 붙어있으면 마지막 단어(동 이름)만 남긴다
2. 인코딩 손상을 되돌린다
3. 이미 공식 목록에 있는 이름이면 그대로 반환
4. "제"를 끼워 넣어봐서 공식 목록에 있으면 그걸로 반환
5. "제"를 빼봐서 공식 목록에 있으면 그걸로 반환
6. 그래도 없으면 원래 형태 그대로 반환 (수동 확인 필요)

`official_set`은 반드시 **서울로 한정한 목록**이어야 한다. 전국 목록을 쓰면, 서울엔 없는 이름이 우연히 다른 지역에 존재할 경우 3번 단계에서 조기에 "이미 맞는 이름"으로 잘못 반환해버리는 문제가 실제로 있었다.

## 사용 예시

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from utils.dong_names import load_official_ref, normalize_dong_name

official_ref = load_official_ref(DATA_DIR / "행정동_공식명_목록.csv")
official_set = set(official_ref["행정동명"])

df["행정동명"] = df["행정동명"].apply(lambda v: normalize_dong_name(v, official_set))
```

## 주의

- `__init__.py`가 이 폴더에 있어야 `from utils.dong_names import ...`가 동작한다. 내용은 비어있어도 된다.
- 여기서 처리하는 건 표기 문제(같은 동을 가리키는 다른 글자)뿐이다. 서로 다른 동네가 이름만 같은 동명이인 문제(신사동 등)는 이 모듈이 아니라 `행정동코드_최종`(구+동 조합으로 재조회한 코드)으로 구분한다 — 자세한 내용은 `src/indicators/README.md` 참고.