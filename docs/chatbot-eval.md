# 챗봇 답변 평가

골든셋 20문항 실행 기록. `python scripts/run_chat_eval.py`

- **PASS** 여섯 축을 모두 통과
- **BLOCK** 게이트가 답변을 차단하고 폴백으로 대체. 실패이지만 거짓이 사용자에게 가지 않았다는 뜻이다.
- **FAIL** 답변은 나갔으나 채점 기준에 못 미침

## 2026-09-10 05:11 · ollama · `exaone3.5:2.4b`

- 통과 **0/1** (0%), 게이트 차단 0건, 총 0.8분
- 축별 통과: json 1, numbers 1, refusal 0, citation 1, mention 1, forbid 1

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-03 | 3p | refuse | **FAIL** | 45.4 | refusal |  |

## 2026-09-10 05:28 · ollama · `exaone3.5:2.4b`

- 통과 **8/20** (40%), 게이트 차단 8건, 총 17.3분
- 축별 통과: json 20, numbers 20, refusal 15, citation 15, mention 16, forbid 20

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **PASS** | 38.4 | - | 컨텍스트에 없는 숫자: ['795'] |
| p3-02 | 3p | explain | **BLOCK** | 42.0 | mention | 컨텍스트에 없는 숫자: ['12,400'] |
| p3-03 | 3p | refuse | **PASS** | 15.2 | - |  |
| p3-04 | 3p | explain | **BLOCK** | 45.5 | citation, mention | 컨텍스트에 없는 숫자: ['795', '55', '974'] |
| p3-05 | 3p | explain | **PASS** | 36.5 | - | 컨텍스트에 없는 숫자: ['795'] |
| p4-01 | 4p | explain | **FAIL** | 41.3 | citation |  |
| p4-02 | 4p | refuse | **FAIL** | 45.9 | refusal |  |
| p4-03 | 4p | refuse | **BLOCK** | 48.6 | refusal | 컨텍스트에 없는 숫자: ['974'] |
| p5-01 | 5p | explain | **BLOCK** | 58.6 | citation | 컨텍스트에 없는 숫자: ['974', '503'] |
| p5-02 | 5p | explain | **PASS** | 49.7 | - |  |
| p5-03 | 5p | refuse | **BLOCK** | 57.4 | refusal | 컨텍스트에 없는 숫자: ['795', '55', '124', '974', '503', '69', '196', |
| p5-04 | 5p | explain | **BLOCK** | 66.7 | citation | 컨텍스트에 없는 숫자: ['974', '795', '18', '4', '503', '768', '19'] |
| p6-01 | 6p | compare | **PASS** | 58.5 | - | 컨텍스트에 없는 숫자: ['793', '768', '790'] |
| p6-02 | 6p | compare | **PASS** | 88.8 | - |  |
| p6-03 | 6p | refuse | **FAIL** | 67.2 | refusal |  |
| p6-04 | 6p | policy | **BLOCK** | 68.1 | mention | 컨텍스트에 없는 숫자: ['795', '974', '503', '768', '505', '793'] |
| p6-05 | 6p | explain | **PASS** | 73.1 | - | 컨텍스트에 없는 숫자: ['974', '768', '790', '793'] |
| cm-01 | 3p | explain | **PASS** | 40.6 | - |  |
| cm-02 | 3p | explain | **FAIL** | 36.1 | citation, mention |  |
| cm-03 | 3p | refuse | **BLOCK** | 57.5 | refusal | 컨텍스트에 없는 숫자: ['795', '974', '974'] |

## 2026-09-10 06:03 · ollama · `exaone3.5:2.4b`

- 통과 **4/20** (20%), 게이트 차단 1건, 총 15.2분
- 축별 통과: json 20, numbers 19, refusal 14, citation 12, mention 15, forbid 20

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **FAIL** | 33.1 | citation |  |
| p3-02 | 3p | explain | **FAIL** | 36.8 | mention |  |
| p3-03 | 3p | refuse | **FAIL** | 38.4 | refusal |  |
| p3-04 | 3p | explain | **FAIL** | 42.1 | citation, mention |  |
| p3-05 | 3p | explain | **PASS** | 35.6 | - |  |
| p4-01 | 4p | explain | **PASS** | 34.0 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 46.0 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 46.1 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 44.4 | mention |  |
| p5-02 | 5p | explain | **FAIL** | 48.5 | citation |  |
| p5-03 | 5p | refuse | **FAIL** | 47.0 | refusal |  |
| p5-04 | 5p | explain | **FAIL** | 45.4 | citation |  |
| p6-01 | 6p | compare | **PASS** | 50.8 | - |  |
| p6-02 | 6p | compare | **FAIL** | 58.1 | citation |  |
| p6-03 | 6p | refuse | **BLOCK** | 59.2 | numbers, refusal | 컨텍스트에 없는 숫자: ['2', '3'] |
| p6-04 | 6p | policy | **FAIL** | 69.6 | citation, mention |  |
| p6-05 | 6p | explain | **FAIL** | 62.7 | citation |  |
| cm-01 | 3p | explain | **PASS** | 33.0 | - |  |
| cm-02 | 3p | explain | **FAIL** | 30.2 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 49.0 | refusal |  |

## 2026-09-10 06:15 · ollama · `exaone3.5:2.4b`

- 통과 **7/20** (35%), 게이트 차단 1건, 총 8.8분
- 축별 통과: json 20, numbers 19, refusal 14, citation 15, mention 16, forbid 20

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **FAIL** | 15.3 | citation |  |
| p3-02 | 3p | explain | **FAIL** | 21.4 | mention |  |
| p3-03 | 3p | refuse | **FAIL** | 23.1 | refusal |  |
| p3-04 | 3p | explain | **FAIL** | 19.7 | citation, mention |  |
| p3-05 | 3p | explain | **PASS** | 20.3 | - |  |
| p4-01 | 4p | explain | **PASS** | 16.1 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 28.7 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 25.6 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 31.0 | citation |  |
| p5-02 | 5p | explain | **PASS** | 26.5 | - |  |
| p5-03 | 5p | refuse | **FAIL** | 24.4 | refusal |  |
| p5-04 | 5p | explain | **PASS** | 20.8 | - |  |
| p6-01 | 6p | compare | **PASS** | 23.1 | - |  |
| p6-02 | 6p | compare | **PASS** | 35.9 | - |  |
| p6-03 | 6p | refuse | **FAIL** | 32.8 | refusal |  |
| p6-04 | 6p | policy | **BLOCK** | 49.2 | numbers, mention | 컨텍스트에 없는 숫자: ['2', '3'] |
| p6-05 | 6p | explain | **FAIL** | 40.0 | citation |  |
| cm-01 | 3p | explain | **PASS** | 19.6 | - |  |
| cm-02 | 3p | explain | **FAIL** | 19.6 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 33.0 | refusal |  |

## 2026-09-10 06:27 · ollama · `exaone3.5:2.4b`

- 통과 **7/20** (35%), 게이트 차단 0건, 총 8.0분
- 축별 통과: json 20, numbers 20, refusal 14, citation 16, mention 15, forbid 20

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **PASS** | 17.2 | - |  |
| p3-02 | 3p | explain | **FAIL** | 23.3 | mention |  |
| p3-03 | 3p | refuse | **FAIL** | 21.7 | refusal |  |
| p3-04 | 3p | explain | **FAIL** | 22.7 | citation, mention |  |
| p3-05 | 3p | explain | **PASS** | 23.4 | - |  |
| p4-01 | 4p | explain | **PASS** | 21.0 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 24.2 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 26.2 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 24.8 | mention |  |
| p5-02 | 5p | explain | **PASS** | 22.6 | - |  |
| p5-03 | 5p | refuse | **FAIL** | 25.5 | refusal |  |
| p5-04 | 5p | explain | **PASS** | 20.5 | - |  |
| p6-01 | 6p | compare | **PASS** | 22.5 | - |  |
| p6-02 | 6p | compare | **FAIL** | 33.7 | citation |  |
| p6-03 | 6p | refuse | **FAIL** | 29.5 | refusal |  |
| p6-04 | 6p | policy | **FAIL** | 36.9 | mention |  |
| p6-05 | 6p | explain | **FAIL** | 31.0 | citation |  |
| cm-01 | 3p | explain | **PASS** | 15.7 | - |  |
| cm-02 | 3p | explain | **FAIL** | 12.4 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 26.2 | refusal |  |

## 2026-09-10 06:45 · ollama · `exaone3.5:2.4b`

- 통과 **6/20** (30%), 게이트 차단 1건, 총 15.4분
- 축별 통과: json 20, numbers 19, refusal 15, citation 13, mention 15, forbid 20

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **FAIL** | 34.1 | citation |  |
| p3-02 | 3p | explain | **FAIL** | 36.5 | citation, mention |  |
| p3-03 | 3p | refuse | **FAIL** | 34.2 | citation |  |
| p3-04 | 3p | explain | **FAIL** | 42.7 | mention |  |
| p3-05 | 3p | explain | **PASS** | 47.1 | - |  |
| p4-01 | 4p | explain | **PASS** | 38.0 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 42.3 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 39.7 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 49.2 | citation, mention |  |
| p5-02 | 5p | explain | **PASS** | 47.3 | - |  |
| p5-03 | 5p | refuse | **FAIL** | 47.9 | refusal |  |
| p5-04 | 5p | explain | **PASS** | 47.0 | - |  |
| p6-01 | 6p | compare | **FAIL** | 47.5 | citation |  |
| p6-02 | 6p | compare | **PASS** | 58.9 | - |  |
| p6-03 | 6p | refuse | **BLOCK** | 64.0 | numbers, refusal | 컨텍스트에 없는 숫자: ['26.7'] |
| p6-04 | 6p | policy | **FAIL** | 65.8 | mention |  |
| p6-05 | 6p | explain | **FAIL** | 66.3 | citation |  |
| cm-01 | 3p | explain | **PASS** | 34.2 | - |  |
| cm-02 | 3p | explain | **FAIL** | 30.7 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 51.4 | refusal |  |

## 2026-09-10 06:55 · ollama · `exaone3.5:2.4b`

- 통과 **6/20** (30%), 게이트 차단 1건, 총 8.3분
- 축별 통과: json 20, numbers 19, refusal 15, citation 13, mention 15, forbid 20

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **FAIL** | 14.2 | citation |  |
| p3-02 | 3p | explain | **FAIL** | 21.3 | mention |  |
| p3-03 | 3p | refuse | **PASS** | 18.0 | - |  |
| p3-04 | 3p | explain | **FAIL** | 31.8 | citation, mention |  |
| p3-05 | 3p | explain | **PASS** | 17.8 | - |  |
| p4-01 | 4p | explain | **PASS** | 22.5 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 26.8 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 19.7 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 29.3 | citation, mention |  |
| p5-02 | 5p | explain | **PASS** | 27.1 | - |  |
| p5-03 | 5p | refuse | **FAIL** | 25.9 | refusal |  |
| p5-04 | 5p | explain | **PASS** | 26.3 | - |  |
| p6-01 | 6p | compare | **FAIL** | 19.8 | citation |  |
| p6-02 | 6p | compare | **FAIL** | 40.4 | citation |  |
| p6-03 | 6p | refuse | **BLOCK** | 33.7 | numbers, refusal | 컨텍스트에 없는 숫자: ['46.7'] |
| p6-04 | 6p | policy | **FAIL** | 31.4 | mention |  |
| p6-05 | 6p | explain | **FAIL** | 38.2 | citation |  |
| cm-01 | 3p | explain | **PASS** | 16.5 | - |  |
| cm-02 | 3p | explain | **FAIL** | 11.7 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 27.2 | refusal |  |

## 2026-09-10 07:05 · ollama · `exaone3.5:2.4b`

- 통과 **6/20** (30%), 게이트 차단 1건, 총 8.0분
- 축별 통과: json 20, numbers 19, refusal 15, citation 13, mention 15, forbid 20

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **FAIL** | 11.9 | citation |  |
| p3-02 | 3p | explain | **FAIL** | 19.8 | mention |  |
| p3-03 | 3p | refuse | **PASS** | 17.6 | - |  |
| p3-04 | 3p | explain | **FAIL** | 30.9 | citation, mention |  |
| p3-05 | 3p | explain | **PASS** | 17.2 | - |  |
| p4-01 | 4p | explain | **PASS** | 21.6 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 26.3 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 19.6 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 28.1 | citation, mention |  |
| p5-02 | 5p | explain | **PASS** | 25.6 | - |  |
| p5-03 | 5p | refuse | **FAIL** | 25.3 | refusal |  |
| p5-04 | 5p | explain | **PASS** | 25.4 | - |  |
| p6-01 | 6p | compare | **FAIL** | 19.0 | citation |  |
| p6-02 | 6p | compare | **FAIL** | 39.4 | citation |  |
| p6-03 | 6p | refuse | **BLOCK** | 33.1 | numbers, refusal | 컨텍스트에 없는 숫자: ['46.7'] |
| p6-04 | 6p | policy | **FAIL** | 31.4 | mention |  |
| p6-05 | 6p | explain | **FAIL** | 36.6 | citation |  |
| cm-01 | 3p | explain | **PASS** | 15.4 | - |  |
| cm-02 | 3p | explain | **FAIL** | 11.3 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 26.8 | refusal |  |

## 2026-09-14 18:04 · ollama · `exaone3.5:2.4b`

- 통과 **0/1** (0%), 게이트 차단 0건, 총 1.0분
- 축별 통과: json 1, numbers 1, refusal 1, citation 0, mention 0, forbid 1, doc 1

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| rag-01 | 3p | doc | **FAIL** | 59.2 | citation, mention |  |

## 2026-09-14 18:05 · ollama · `exaone3.5:2.4b`

- 통과 **0/1** (0%), 게이트 차단 0건, 총 1.0분
- 축별 통과: json 1, numbers 1, refusal 1, citation 0, mention 0, forbid 1, doc 1

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| rag-02 | 3p | doc | **FAIL** | 59.0 | citation, mention |  |

## 2026-09-14 18:06 · ollama · `exaone3.5:2.4b`

- 통과 **0/1** (0%), 게이트 차단 0건, 총 1.5분
- 축별 통과: json 1, numbers 1, refusal 1, citation 0, mention 1, forbid 1, doc 1

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| rag-03 | 6p | doc | **FAIL** | 90.1 | citation |  |

## 2026-09-14 18:07 · ollama · `exaone3.5:2.4b`

- 통과 **0/1** (0%), 게이트 차단 0건, 총 0.6분
- 축별 통과: json 1, numbers 1, refusal 1, citation 0, mention 1, forbid 1, doc 1

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| rag-04 | 3p | refuse | **FAIL** | 38.0 | citation |  |

## 2026-09-14 18:30 · ollama · `exaone3.5:2.4b`

- 통과 **2/24** (8%), 게이트 차단 1건, 총 22.1분
- 축별 통과: json 24, numbers 23, refusal 19, citation 9, mention 18, forbid 24, doc 24

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **PASS** | 34.3 | - |  |
| p3-02 | 3p | explain | **FAIL** | 39.6 | mention |  |
| p3-03 | 3p | refuse | **FAIL** | 34.3 | citation |  |
| p3-04 | 3p | explain | **FAIL** | 74.1 | citation, mention |  |
| p3-05 | 3p | explain | **FAIL** | 50.7 | citation |  |
| p4-01 | 4p | explain | **PASS** | 54.9 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 47.2 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 67.4 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 76.8 | citation |  |
| p5-02 | 5p | explain | **FAIL** | 52.6 | citation |  |
| p5-03 | 5p | refuse | **FAIL** | 59.2 | refusal |  |
| p5-04 | 5p | explain | **FAIL** | 77.6 | citation |  |
| p6-01 | 6p | compare | **FAIL** | 57.2 | citation |  |
| p6-02 | 6p | compare | **FAIL** | 61.4 | citation |  |
| p6-03 | 6p | refuse | **FAIL** | 61.5 | refusal |  |
| p6-04 | 6p | policy | **FAIL** | 74.9 | mention |  |
| p6-05 | 6p | explain | **BLOCK** | 81.9 | numbers, citation | 컨텍스트에 없는 숫자: ['2.2', '2.5'] |
| cm-01 | 3p | explain | **FAIL** | 63.4 | citation |  |
| cm-02 | 3p | explain | **FAIL** | 53.6 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 51.6 | refusal |  |
| rag-01 | 3p | doc | **FAIL** | 62.4 | citation, mention |  |
| rag-02 | 3p | doc | **FAIL** | 22.1 | citation, mention |  |
| rag-03 | 6p | doc | **FAIL** | 28.0 | citation |  |
| rag-04 | 3p | refuse | **FAIL** | 40.9 | citation |  |

## 2026-09-14 18:46 · ollama · `exaone3.5:2.4b`

- 통과 **2/24** (8%), 게이트 차단 1건, 총 12.9분
- 축별 통과: json 24, numbers 24, refusal 19, citation 9, mention 18, forbid 24, doc 24

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **PASS** | 16.9 | - |  |
| p3-02 | 3p | explain | **FAIL** | 42.9 | mention |  |
| p3-03 | 3p | refuse | **FAIL** | 18.6 | citation |  |
| p3-04 | 3p | explain | **FAIL** | 28.7 | citation, mention |  |
| p3-05 | 3p | explain | **FAIL** | 19.0 | citation |  |
| p4-01 | 4p | explain | **FAIL** | 26.1 | citation |  |
| p4-02 | 4p | refuse | **FAIL** | 31.9 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 37.2 | refusal |  |
| p5-01 | 5p | explain | **BLOCK** | 36.6 | citation, mention | JSONDecodeError: Expecting ',' delimiter: line 3 column 74 ( |
| p5-02 | 5p | explain | **FAIL** | 26.5 | citation |  |
| p5-03 | 5p | refuse | **FAIL** | 34.0 | refusal |  |
| p5-04 | 5p | explain | **FAIL** | 31.3 | citation |  |
| p6-01 | 6p | compare | **FAIL** | 23.6 | citation |  |
| p6-02 | 6p | compare | **FAIL** | 41.1 | citation |  |
| p6-03 | 6p | refuse | **FAIL** | 66.3 | refusal |  |
| p6-04 | 6p | policy | **FAIL** | 49.4 | mention |  |
| p6-05 | 6p | explain | **FAIL** | 40.3 | citation |  |
| cm-01 | 3p | explain | **PASS** | 27.6 | - |  |
| cm-02 | 3p | explain | **FAIL** | 19.8 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 37.5 | refusal |  |
| rag-01 | 3p | doc | **FAIL** | 31.9 | citation |  |
| rag-02 | 3p | doc | **FAIL** | 20.1 | citation, mention |  |
| rag-03 | 6p | doc | **FAIL** | 27.1 | citation |  |
| rag-04 | 3p | refuse | **FAIL** | 40.0 | citation |  |

## 2026-09-15 00:17 · ollama · `exaone3.5:2.4b`

- 통과 **8/24** (33%), 게이트 차단 1건, 총 22.7분
- 축별 통과: json 24, numbers 23, refusal 19, citation 16, mention 18, forbid 24, doc 24

| 문항 | 화면 | 유형 | 결과 | 초 | 실패 축 | 비고 |
|---|---|---|---|---|---|---|
| p3-01 | 3p | explain | **PASS** | 51.8 | - |  |
| p3-02 | 3p | explain | **FAIL** | 39.3 | mention |  |
| p3-03 | 3p | refuse | **FAIL** | 34.4 | citation |  |
| p3-04 | 3p | explain | **FAIL** | 73.4 | citation, mention |  |
| p3-05 | 3p | explain | **PASS** | 51.3 | - |  |
| p4-01 | 4p | explain | **PASS** | 53.6 | - |  |
| p4-02 | 4p | refuse | **FAIL** | 46.5 | refusal |  |
| p4-03 | 4p | refuse | **FAIL** | 59.8 | refusal |  |
| p5-01 | 5p | explain | **FAIL** | 69.0 | citation |  |
| p5-02 | 5p | explain | **PASS** | 50.9 | - |  |
| p5-03 | 5p | refuse | **FAIL** | 55.4 | refusal |  |
| p5-04 | 5p | explain | **FAIL** | 68.2 | citation |  |
| p6-01 | 6p | compare | **PASS** | 50.8 | - |  |
| p6-02 | 6p | compare | **PASS** | 56.2 | - |  |
| p6-03 | 6p | refuse | **FAIL** | 59.1 | refusal |  |
| p6-04 | 6p | policy | **FAIL** | 66.5 | mention |  |
| p6-05 | 6p | explain | **BLOCK** | 74.3 | numbers, citation | 컨텍스트에 없는 숫자: ['2.2', '2.5'] |
| cm-01 | 3p | explain | **PASS** | 54.8 | - |  |
| cm-02 | 3p | explain | **FAIL** | 51.1 | citation, mention |  |
| cm-03 | 3p | refuse | **FAIL** | 45.6 | refusal |  |
| rag-01 | 3p | doc | **FAIL** | 58.6 | mention |  |
| rag-02 | 3p | doc | **FAIL** | 59.4 | citation, mention |  |
| rag-03 | 6p | doc | **PASS** | 91.2 | - |  |
| rag-04 | 3p | refuse | **FAIL** | 40.3 | citation |  |
