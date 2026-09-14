import os
import json
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 경로에 넣는다.
# `python web/app.py` 로 실행하면 sys.path 에 web/ 만 들어가서
# service.py 가 'service' 와 'web.service' 두 모듈로 이중 로드된다.
# 항상 web.service 한 경로로만 읽히게 고정한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from urllib.parse import urlencode

from flask import Flask, jsonify, render_template, request

from web.chat_context import attach_docs, build_chat_context
from web.chat_llm import ask
from web.service import (_blank, build_page3, build_page4, build_page5,
                         build_page6, resolve_place)

try:
    from src.db.query_dong import list_dongs, list_home_options, list_work_options
except ImportError:  # web/ 에서 직접 실행할 때
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
    from src.db.query_dong import list_dongs, list_home_options, list_work_options

# web.chat_llm 등 모듈 로거를 보이게 한다.
# Flask 는 app.logger 에만 핸들러를 붙이고 루트 로거는 기본이 WARNING 이라,
# 모듈에서 찍은 log.info 가 조용히 사라진다. 실제로 컨텍스트 크기 로그가
# 안 보여서 "파일이 안 올라갔다"고 며칠 헤맸다.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)

# 2페이지 폼의 input name 은 loca_page2_data.json 의 field.id 에서 나온다.
# 그 id 가 바뀌면 라우트가 값을 못 읽고 조용히 시연용 고정값을 보여주게 되므로
# (실제로 이 사고가 있었다) 이름을 하나로 고정하지 않고 별칭으로 찾는다.
# 정확히 일치하는 이름을 먼저 보고, 없으면 키 안에 조각이 들어있는지로 찾는다.
FIELD_ALIASES = {
    "residence":  ["residence", "home", "house", "live", "origin", "from", "start",
                   "거주지", "거주", "사는곳", "현재집"],
    "workplace":  ["workplace", "work", "office", "company", "destination", "to", "dest",
                   "근무지", "직장", "회사"],
    "deposit":    ["deposit", "bojeung", "보증금", "보증"],
    "rent":       ["rent", "monthly_rent", "wolse", "월세", "임대료"],
    "work_days":  ["work_days", "workdays", "days", "commute_days",
                   "출근일수", "출근일", "근무일"],
    "age":        ["age", "만나이", "나이", "연령"],
    "depart_time": ["depart_time", "departure", "depart", "leave_time", "time",
                    "출발시간", "출발", "시간"],
}
# work 가 work_days 를, time 이 depart_time 을 먼저 집어가지 않도록
# 조각 검색은 긴 이름부터 확정한다.
_MATCH_ORDER = ["work_days", "depart_time", "residence", "workplace",
                "deposit", "rent", "age"]


def read_form(args):
    """폼 필드 이름이 무엇이든 표준 키로 정규화해 돌려준다."""
    got, used = {}, set()
    lowered = {k: k.lower() for k in args.keys()}

    for canon in _MATCH_ORDER:
        aliases = FIELD_ALIASES[canon]
        # 1순위: 이름이 정확히 같은 것
        hit = next((k for k, lo in lowered.items()
                    if k not in used and lo in aliases), None)
        # 2순위: 이름 안에 별칭 조각이 들어 있는 것
        if hit is None:
            hit = next((k for k, lo in lowered.items()
                        if k not in used and any(a in lo for a in aliases)), None)
        if hit is not None:
            used.add(hit)
            got[canon] = (args.get(hit) or "").strip()

    return got
BASE = Path(__file__).parent
DATA_FILES = {
    "page1": BASE / "static" / "loca_data.json",
    "page2": BASE / "static" / "loca_page2_data.json",
    "page3": BASE / "static" / "loca_page3_data.json",
    "page4": BASE / "static" / "loca_page4_data.json",
    "page5": BASE / "static" / "loca_page5_data.json",
    "page6": BASE / "static" / "loca_page6_data.json",
}


def load_data(key):
    with open(DATA_FILES[key], encoding="utf-8") as f:
        return json.load(f)


@app.route("/")
def index():
    return render_template("index.html", data=load_data("page1"))


@app.route("/diagnosis")
def diagnosis():
    # 다시 들어왔을 때 직전 입력을 채워준다. 처음 방문이면 빈 폼이 뜬다.
    data = load_data("page2")
    data["carry"] = read_form(request.args)
    return render_template("page2.html", data=data)


@app.route("/result")
def result():
    # 2페이지 폼이 넘긴 입력을 실제 계산에 쓴다.
    # 입력이 없으면 기존 시연용 JSON 을 그대로 보여준다.
    f = read_form(request.args)
    residence = f.get("residence") or ""
    workplace = f.get("workplace") or ""
    app.logger.info("result args=%s -> %s", dict(request.args), f)
    data = load_data("page3")
    if residence and workplace:
        try:
            data = build_page3(
                data,
                residence=residence,
                workplace=workplace,
                deposit=f.get("deposit"),
                rent=f.get("rent"),
                work_days=f.get("work_days"),
                depart_time=f.get("depart_time"),
                age=f.get("age"),
            )
        except Exception as e:
            app.logger.exception("build_page3 failed: %s", e)
            v = data["summary"]
            v["lines"] = [{"text": "지금은 분석할 수 없어요.", "accent": False}]
            v["lines2"] = [{"text": "잠시 후 다시 시도해주세요.", "accent": False}]
    elif request.args:
        # 폼에서 넘어왔는데 거주지·근무지를 못 찾은 경우.
        # 이때 시연용 고정값을 그대로 보여주면 "입력이 반영된 결과"로 오해된다.
        app.logger.warning("입력을 인식하지 못함. 받은 키: %s", list(request.args.keys()))
        v = data["summary"]
        v["lines"] = [{"text": "입력한 거주지와 근무지를", "accent": False},
                      {"text": "인식하지 못했어요.", "accent": False}]
        v["lines2"] = [{"text": "다시 입력해주세요.", "accent": False}]
    return render_template("page3.html", data=data)


@app.route("/explore")
def explore():
    # 3페이지에서 넘어온 입력을 4페이지가 그대로 들고 있어야
    # "현재 기준" 패널과 비교 요청이 시연 페르소나로 되돌아가지 않는다.
    f = read_form(request.args)
    data = load_data("page4")
    app.logger.info("explore args=%s -> %s area=%r", dict(request.args), f,
                    request.args.get("area"))
    try:
        data = build_page4(
            data, residence=f.get("residence"), workplace=f.get("workplace"),
            deposit=f.get("deposit"), rent=f.get("rent"),
            work_days=f.get("work_days"), depart_time=f.get("depart_time"),
            age=f.get("age"),
            area=(request.args.get("area") or "").strip() or None,
            carry_qs=urlencode({k: v for k, v in f.items() if v}))
    except Exception as e:
        # 조회가 실패해도 화면은 떠야 하지만, 조용히 기본값을 보여주면
        # 사용자는 자기 입력이 무시된 이유를 알 수 없다. 화면에 사유를 남긴다.
        app.logger.exception("build_page4 failed: %s", e)
        data.setdefault("compare", {})["candidate_error"] = (
            f"결과를 불러오지 못했어요. ({type(e).__name__})")
    data["carry"] = f
    return render_template("page4.html", data=data)


@app.route("/explore/result")
def explore_result():
    # 사용자가 입력한 지역이 있으면 DB 에서 조회해 값을 갈아끼운다.
    # 입력이 없으면 기존 시연용 JSON 을 그대로 쓴다.
    # 5페이지 폼은 name="dong", 4페이지 추천 카드 링크는 ?area= 을 쓴다.
    #
    # q 는 여기서 읽지 않는다. 하단 채팅바가 질문 칩을 name="q" 로 제출하는데,
    # 그걸 지역명으로 받으면 "'이 지역은 왜 월세 착시예요?' 는 서울 밖이거나
    # 찾을 수 없어요" 같은 화면이 뜬다. 질문은 지역이 아니다.
    area = next((request.args.get(k, "").strip()
                 for k in ("area", "dong")
                 if request.args.get(k, "").strip()), "")
    f = read_form(request.args)
    # 이 라우트에만 로그가 없었다. 3·4·6 페이지에는 있는데 여기만 빠져서,
    # 화면이 조용히 시연값으로 되돌아가도 서버에 아무 흔적이 남지 않았다.
    app.logger.info("explore_result args=%s -> %s area=%r",
                    dict(request.args), f, area)
    data = load_data("page5")
    data["carry"] = f
    data["carry_qs"] = urlencode({k: v for k, v in f.items() if v})
    if area:
        try:
            data = build_page5(data, area=area,
                               base_place=f.get("residence"),
                               work_place=f.get("workplace"),
                               deposit=f.get("deposit"), rent=f.get("rent"),
                               work_days=f.get("work_days"),
                               age=f.get("age"))
        except Exception as e:
            # DB 가 죽어도 화면은 떠야 한다. 시연 중 사고 방지.
            app.logger.exception("build_page5 failed: %s", e)
            v = data["verdict"]
            v["title_line1"] = "지금은 조회할 수 없어요."
            v["title_line2"] = "잠시 후 다시 시도해주세요."
            v["conclusion"]["tag"] = "안내"
            v["conclusion"]["title"] = "일시적 오류"
            v["conclusion"]["text"] = "데이터베이스에 연결하지 못했습니다."
    elif request.args:
        # 후보 지역 없이 이 페이지로 들어온 경우.
        # 여기서 시연용 JSON 을 그대로 보여주면 화면 전체가 시연 페르소나
        # (잠원동 -> 삼정KPMG, 신길1동, 청림동/난향동/신대방1동)로 돌아간다.
        # 검색창 기본값도 "신길1동"이라 사용자 눈에는 "입력은 반영됐는데
        # 근무지만 틀린 결과"로 보인다. 3페이지 /result 가 같은 이유로
        # 이미 막고 있던 것을 여기서만 빠뜨리고 있었다.
        app.logger.warning("후보 지역을 인식하지 못함. 받은 키: %s",
                           list(request.args.keys()))
        if request.args.get("q"):
            # 하단 채팅바에서 제출된 것. 챗봇을 붙이기 전까지 여기로 떨어진다.
            app.logger.warning("채팅바 제출. q=%r", request.args.get("q"))

        # 시연 숫자를 남기지 않는다. 하나라도 남으면 조회된 값으로 읽힌다.
        v = data["verdict"]
        v["title_line1"] = "비교할 후보 지역을 입력해주세요."
        v["title_line2"] = "지하철역·건물명·주소·행정동 모두 입력할 수 있어요."
        v["conclusion"]["tag"] = "안내"
        v["conclusion"]["title"] = "입력 필요"
        v["conclusion"]["text"] = "예) 신길1동, 봉천동, 잠원동"
        _blank(v)
        # 검색창에 남은 시연 지역명이 사용자 입력처럼 보이지 않게 비운다.
        data["hero"]["search"]["value"] = ""

        # 추천 섹션도 비운다. 여기 남아 있던 "그렇다면, 삼정KPMG 출근에는"
        # 이 실제로 버그로 신고된 문구다.
        rec = data.get("recommend")
        if rec:
            w = f.get("workplace")
            rec["title_line1"] = (f"{w} 출근 기준으로" if w
                                  else "후보를 입력하시면")
            rec["title_line2"] = "후보 지역을 비교해드릴게요."
            rec["description"] = ("위 칸에 후보 지역을 입력하고 "
                                  "'현재 집과 비교하기'를 눌러주세요.")
            rec["cards"] = []
    return render_template("page5.html", data=data)


@app.route("/api/suggest")
def api_suggest():
    """거주지·근무지 입력 자동완성. 행정동명을 부분일치로 돌려준다.

    DB 가 죽어도 입력 자체는 되어야 하므로 실패 시 빈 목록을 준다.
    화면이 멈추는 것보다 자동완성만 안 되는 편이 낫다.
    """
    q = (request.args.get("q") or "").strip()
    kind = (request.args.get("kind") or "").strip()
    home = (request.args.get("home") or "").strip()

    # 근무지 칸은 "그 거주지에서 갈 수 있는 곳"만 제안한다.
    # 경로는 거주동별 누적 80% 목적지만 수집했기 때문에(거주동당 평균 72곳,
    # 427개 중 약 17%) 전체를 열어두면 사용자가 없는 조합을 고르게 된다.
    work = (request.args.get("work") or "").strip()

    rows, scoped = None, False
    if kind == "work" and home:
        try:
            r = resolve_place(home)
            if r.get("status") == "ok" and r.get("dong_code"):
                rows = list_work_options(r["dong_code"], limit=30, q=q or None)
                scoped = True
        except Exception as e:
            app.logger.warning("work suggest scope failed: %s", e)
    elif kind == "home" and work:
        # 대안 탐색의 후보 거주지. 그 직장으로 갈 수 있는 동만 제안한다.
        try:
            r = resolve_place(work)
            if r.get("status") == "ok" and r.get("dong_code"):
                rows = list_home_options(r["dong_code"], limit=30, q=q or None)
                scoped = True
        except Exception as e:
            app.logger.warning("home suggest scope failed: %s", e)

    if rows is None:
        try:
            rows = list_dongs(q or None, limit=30)
        except Exception as e:
            app.logger.exception("list_dongs failed: %s", e)
            return jsonify({"items": [], "error": True})

    return jsonify({"scoped": scoped,
                    "items": [{"label": f"{r['gu']} {r['name']}",
                               "value": r["name"],
                               "code": r["code"]} for r in rows]})


# 챗봇이 어느 화면에서 물어보는지. 경로로 정한다.
# 브라우저가 보낸 page 번호를 그대로 믿으면 5페이지 값으로 3페이지를
# 설명하는 답이 나올 수 있다.
PAGE_BY_PATH = {"/result": 3, "/explore": 4, "/explore/result": 5,
                "/compare": 6}

# 방법론 문서 검색기. 한 번만 읽어 재사용한다.
# 인덱스가 없어도 앱은 떠야 한다. 문서 설명만 못 할 뿐 계산 설명은 된다.
_DOC_SEARCH = "unset"


def doc_searcher():
    global _DOC_SEARCH
    if _DOC_SEARCH == "unset":
        try:
            from web.doc_search import DocSearch
            path = BASE.parent / "data" / "doc_index.json"
            _DOC_SEARCH = DocSearch.load(path)
            app.logger.info("문서 인덱스 로드: 조각 %d개",
                            len(_DOC_SEARCH.chunks))
        except Exception as e:
            app.logger.warning("문서 인덱스 없음(%s). "
                               "python scripts/build_doc_index.py 로 만들 수 "
                               "있습니다.", e)
            _DOC_SEARCH = None
    return _DOC_SEARCH


def _rebuild(page, args):
    """챗봇에 넘길 화면을 서버에서 다시 만든다.

    브라우저에 계산값을 내려보내고 그걸 돌려받는 방식을 쓰지 않는 이유가
    두 가지다. 첫째, 화면에 <script> 로 값을 심으면 DOM 구조가 바뀐다.
    둘째, 사용자가 개발자도구로 숫자를 바꿔 보낼 수 있다. 그러면 챗봇이
    "환각 없이" 거짓말을 하게 된다. 조회를 한 번 더 하는 값을 치른다.
    """
    f = read_form(args)
    area = next((args.get(k, "").strip() for k in ("area", "dong")
                 if args.get(k, "").strip()), "")
    qs = urlencode({k: v for k, v in f.items() if v})

    if page == 3:
        return f, build_page3(
            load_data("page3"), residence=f.get("residence"),
            workplace=f.get("workplace"), deposit=f.get("deposit"),
            rent=f.get("rent"), work_days=f.get("work_days"),
            depart_time=f.get("depart_time"), age=f.get("age"))
    if page == 4:
        return f, build_page4(
            load_data("page4"), residence=f.get("residence"),
            workplace=f.get("workplace"), deposit=f.get("deposit"),
            rent=f.get("rent"), work_days=f.get("work_days"),
            depart_time=f.get("depart_time"), age=f.get("age"),
            area=area or None, carry_qs=qs)
    if page == 5:
        return f, build_page5(
            load_data("page5"), area=area, base_place=f.get("residence"),
            work_place=f.get("workplace"), deposit=f.get("deposit"),
            rent=f.get("rent"), work_days=f.get("work_days"), age=f.get("age"))
    return f, build_page6(
        load_data("page6"), base_place=f.get("residence"),
        work_place=f.get("workplace"), dong=area or None,
        deposit=f.get("deposit"), rent=f.get("rent"),
        work_days=f.get("work_days"), age=f.get("age"), carry_qs=qs)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """질문 칩 하나에 답한다.

    실패해도 200 으로 문장을 돌려준다. 챗봇이 안 되는 것과 화면이 깨지는
    것은 다른 문제이고, 여기서 500 을 던지면 앞단이 빈 말풍선을 띄운다.
    """
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    args = {k: str(v) for k, v in (body.get("params") or {}).items()}
    page = PAGE_BY_PATH.get(body.get("path") or "")

    app.logger.info("api_chat page=%s q=%r", page, question)

    if not question:
        return jsonify({"answer": "무엇이 궁금하신지 알려주세요.",
                        "source": "guard"})
    if page is None:
        return jsonify({"answer": "이 화면에서는 아직 답해드릴 수 없어요.",
                        "source": "guard"})

    try:
        f, data = _rebuild(page, args)
    except Exception as e:
        app.logger.exception("api_chat rebuild 실패: %s", e)
        return jsonify({"answer": "지금은 화면 값을 다시 읽지 못했어요. "
                                  "잠시 후 다시 시도해주세요.",
                        "source": "error"})

    calc = data.get("_calc")
    if not calc:
        # 입력이 없어 시연 화면이거나 조회가 실패한 경우.
        # 이때 답을 만들면 시연 페르소나를 사용자 값처럼 설명하게 된다.
        app.logger.warning("api_chat: _calc 없음. page=%s args=%s", page, args)
        return jsonify({"answer": "아직 계산된 결과가 없어요. "
                                  "거주지와 근무지를 입력하시면 "
                                  "그 값을 기준으로 설명해 드릴게요.",
                        "source": "guard"})

    try:
        ctx = build_chat_context(page, calc, f)
    except Exception as e:
        app.logger.exception("api_chat 컨텍스트 실패: %s", e)
        return jsonify({"answer": "이 화면의 값을 설명할 준비가 안 됐어요.",
                        "source": "error"})

    attach_docs(ctx, question, doc_searcher())
    app.logger.info("문서 근거 %d건: %s", len(ctx["docs"]),
                    ", ".join(d["id"] for d in ctx["docs"]) or "-")

    out = ask(ctx, question)
    if out["source"] == "fallback":
        app.logger.warning("게이트 차단 후 폴백: %s", out["blocked_reason"])
    return jsonify({"answer": out["answer"], "source": out["source"],
                    "refused": out["refused"]})


@app.route("/compare")
def compare():
    # 5페이지 카드에서 ?dong= 으로 후보를 지정해 들어온다.
    # 입력이 없으면 시연용 JSON 을 그대로 보여준다.
    f = read_form(request.args)
    dong = (request.args.get("dong") or request.args.get("area") or "").strip()
    app.logger.info("compare args=%s -> %s dong=%s", dict(request.args), f, dong)
    data = load_data("page6")
    try:
        data = build_page6(
            data, base_place=f.get("residence"), work_place=f.get("workplace"),
            dong=dong or None, deposit=f.get("deposit"), rent=f.get("rent"),
            work_days=f.get("work_days"), age=f.get("age"),
            carry_qs=urlencode({k: v for k, v in f.items() if v}))
    except Exception as e:
        # 조회가 실패해도 화면은 떠야 하지만, 예시 화면이라는 건 밝힌다.
        app.logger.exception("build_page6 failed: %s", e)
        data["hero"]["description"] = ("자료를 불러오지 못해\n"
                                       "예시 화면을 보여드리고 있어요.")
    data["carry"] = f
    return render_template("page6.html", data=data)


if __name__ == "__main__":
    # 기본값은 로컬 실행과 동일하다. 컨테이너에서는 compose 가
    # FLASK_HOST=0.0.0.0 을 넣어 밖에서 접속할 수 있게 한다.
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=True,
    )