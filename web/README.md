# web — LOCA 서비스

청년 1인가구 주거·통근 통합부담 분석 결과를 보여주는 Flask 앱.
강사님이 제작한 HTML 시안을 편입해 MySQL 과 연결했다.

실행 방법은 `docs/WEB_실행방법.md` 참고.

## 구조

```
web/
├─ app.py            Flask 진입점. 라우트 6개
├─ service.py        조회 결과를 화면 JSON 구조에 주입하는 어댑터
├─ templates/        실제 구동되는 Jinja 템플릿
│   ├─ partials/     상단바·하단바·채팅바 공통 조각
│   └─ index.html, page2~6.html
├─ static/
│   ├─ loca_common.css
│   ├─ images/
│   └─ loca_data.json, loca_page2~6_data.json
└─ preview.html, preview-page2~6.html
```

## ⚠️ preview 와 templates 는 다른 파일이다

- `templates/` + `static/*.json` 이 **실제 구동본**
- `preview*.html` 은 그 둘을 합쳐 만든 **미리보기용 정적 파일**

브라우저로 파일을 바로 열어볼 때는 preview 를, 서버로 띄울 때는 templates 를 쓴다.
**화면을 고칠 때는 양쪽 다 반영해야 한다.** 한쪽만 고치면 둘이 달라진다.

## 라우트

| 경로 | 템플릿 | 데이터 |
|---|---|---|
| `/` | index.html | JSON 고정 |
| `/diagnosis` | page2.html | JSON 고정 |
| `/result` | page3.html | JSON 고정 |
| `/explore` | page4.html | JSON 고정 |
| `/explore/result` | page5.html | **DB 조회** |
| `/compare` | page6.html | JSON 고정 |

현재 DB 와 연결된 것은 `/explore/result` 하나다.
`?dong=`, `?area=`, `?q=` 중 아무 파라미터로나 지역명을 받는다
(4페이지 폼은 `area`, 추천 카드 링크는 `dong` 을 쓴다).

```
/explore/result?dong=신길1동     정상 비교
/explore/result?dong=마장동       unreliable 경고
/explore/result?dong=합정동       low_confidence 라벨
/explore/result?dong=오륜동       주거비 없음 + 인근 후보 카드
/explore/result?dong=없는동       검색 실패 안내
```

## 데이터 흐름

```
app.py  →  service.py  →  src/db/query_dong.py  →  MySQL
```

`query_dong.py` 가 status 4종 JSON 을 돌려주고, `service.py` 가 그 값을
기존 JSON 구조의 해당 자리에 덮어쓴다. **템플릿은 수정하지 않는다.**

`service.py` 가 하는 일 세 가지.

1. 기준 동(현재 집)과 비교 동을 모두 DB 에서 조회한다.
   화면의 개인 실측값과 DB 대표값이 섞이지 않도록 양쪽 다 대표값으로 통일한다.
2. 결론 문구를 결과에 따라 정한다. "월세 착시"를 고정해두지 않는다.
   (주거비↓ + 총부담↑ = 월세 착시 / 주거비↓ + 총부담↓ = 실질 절감)
3. `no_data` 인 동은 추천 카드 자리에 인근 후보를 넣는다. 템플릿 수정 불필요.

DB 조회에 실패해도 화면은 뜬다. 시연 중 사고를 막기 위한 예외 처리가 있다.