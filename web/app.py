import json
from pathlib import Path

from flask import Flask, render_template, request

from service import build_page5

app = Flask(__name__)
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
    return render_template("page2.html", data=load_data("page2"))


@app.route("/result")
def result():
    return render_template("page3.html", data=load_data("page3"))


@app.route("/explore")
def explore():
    return render_template("page4.html", data=load_data("page4"))


@app.route("/explore/result")
def explore_result():
    # 사용자가 입력한 지역이 있으면 DB 에서 조회해 값을 갈아끼운다.
    # 입력이 없으면 기존 시연용 JSON 을 그대로 쓴다.
    # 4페이지 폼은 name="area", 추천 카드 링크는 ?dong= 을 쓴다. 둘 다 받는다.
    area = next((request.args.get(k, "").strip()
                 for k in ("area", "dong", "q")
                 if request.args.get(k, "").strip()), "")
    data = load_data("page5")
    if area:
        try:
            data = build_page5(data, area=area)
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


@app.route("/compare")
def compare():
    return render_template("page6.html", data=load_data("page6"))


if __name__ == "__main__":
    app.run(debug=True)