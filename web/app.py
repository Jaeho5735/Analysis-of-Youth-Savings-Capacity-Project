import os
import json
from pathlib import Path

from urllib.parse import urlencode

from flask import Flask, jsonify, render_template, request

from service import (build_page3, build_page4, build_page5, build_page6,
                     resolve_place)

try:
    from src.db.query_dong import list_dongs, list_home_options
except ImportError:  # web/ 에서 직접 실행할 때
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
    from src.db.query_dong import list_dongs, list_home_options

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
    # 4페이지 폼은 name="area", 추천 카드 링크는 ?dong= 을 쓴다. 둘 다 받는다.
    area = next((request.args.get(k, "").strip()
                 for k in ("area", "dong", "q")
                 if request.args.get(k, "").strip()), "")
    f = read_form(request.args)
    data = load_data("page5")
    data["carry"] = f
    data["carry_qs"] = urlencode({k: v for k, v in f.items() if v})
    if area:
        try:
            data = build_page5(data, area=area,
                               base_place=f.get("residence"),
                               work_place=f.get("workplace"),
                               deposit=f.get("deposit"), rent=f.get("rent"),
                               work_days=f.get("work_days"))
        except Exception as e:
            # DB 가 죽어도 화면은 떠야 한다. 시연 중 사고 방지.
            app.logger.exception("build_page5 failed: %s", e)
            v = data["verdict"]
            v["title_line1"] = "지금은 조회할 수 없어요."
            v["title_line2"] = "잠시 후 다시 시도해주세요."
            v["conclusion"]["tag"] = "안내"
            v["conclusion"]["title"] = "일시적 오류"
            v["conclusion"]["text"] = "데이터베이스에 연결하지 못했습니다."
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
            work_days=f.get("work_days"),
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