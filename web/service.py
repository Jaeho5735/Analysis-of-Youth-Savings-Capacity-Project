"""
LOCA 서비스 어댑터

query_dong() 의 조회 결과를 loca_page5_data.json 구조에 덮어쓴다.
템플릿은 손대지 않는다. 기존 JSON 의 키를 그대로 쓰고 값만 바꾼다.

    from service import build_page5

    data = build_page5(load_data("page5"), area="봉천동")

동작
    - 기준 동(현재 집)과 비교 동을 모두 DB 에서 조회한다.
      화면의 개인 실측값(17.2분)과 DB 대표값(28.82분)이 섞이지 않도록
      양쪽 다 대표값으로 통일한다.
    - status 에 따라 문구와 카드 내용이 바뀐다.
        ok / low_confidence / unreliable  -> 비교 결과 표시 (+ 라벨)
        no_data                           -> 사유 안내 + 인근 후보를 카드로
        not_found                         -> 안내만
"""

import copy

try:
    from src.db.query_dong import get_dong, get_dong_by_name
except ImportError:  # web/ 에서 직접 실행할 때
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.db.query_dong import get_dong, get_dong_by_name

# 현재 집 기준 동. 시연 시나리오의 잠원동.
BASE_DONG_CODE = "11650540"


# ─────────────────────────────────────────────────────────────
# 표시 헬퍼
# ─────────────────────────────────────────────────────────────

def man(won):
    """원 -> 만원 문자열. 785000 -> '78.5'"""
    if won is None:
        return "—"
    return f"{round(won / 10000, 1):.1f}"


def diff_pill(base, target, unit="만원"):
    """줄었으면 절약, 늘었으면 더 부담."""
    if base is None or target is None:
        return "—"
    d = round((base - target) / 10000, 1)
    if abs(d) < 0.05:
        return "차이 없음"
    return f"월 {abs(d):.1f}{unit} 절약" if d > 0 else f"월 {abs(d):.1f}{unit} 더 부담"


def minute_pill(base, target):
    if base is None or target is None:
        return "—"
    d = round(target - base, 1)
    sign = "+" if d >= 0 else ""
    return f"{sign}{d}분"


def _burden(res):
    return (res or {}).get("burden") or {}


def status_note(res):
    """신뢰도 라벨. 값이 있는 동에만 붙는다."""
    st = res.get("status")
    if st == "unreliable":
        return "이 지역은 인접 동의 값이 섞였을 가능성이 높아요. 참고용으로만 봐주세요."
    if st == "low_confidence":
        reasons = res.get("reasons") or []
        tail = f" ({reasons[0]})" if reasons else ""
        return f"표본이 적어 참고용으로 보시는 것을 권해요.{tail}"
    return None


# ─────────────────────────────────────────────────────────────
# 본체
# ─────────────────────────────────────────────────────────────

def _blank(v, to_label=None):
    """비교 결과가 없을 때 이전 시연 숫자가 남지 않도록 비운다."""
    for blk in ("rent", "total"):
        v[blk]["from_value"] = "—"
        v[blk]["to_value"] = "—"
        v[blk]["pill"] = "—"
        if to_label:
            v[blk]["to_label"] = to_label
    v["commute"]["time"]["from_value"] = "—"
    v["commute"]["time"]["to_value"] = "—"
    v["commute"]["time"]["pill"] = "—"
    v["commute"]["extra"]["to_value"] = "—"


def build_page5(base_json, area=None, base_code=BASE_DONG_CODE):
    """page5 JSON 을 조회 결과로 갱신해 돌려준다. 원본은 건드리지 않는다."""
    data = copy.deepcopy(base_json)
    if not area:
        return data

    target = get_dong(area) if str(area).isdigit() else get_dong_by_name(area)
    base = get_dong(base_code)

    data["hero"]["search"]["value"] = area
    v = data["verdict"]

    # ── 찾지 못한 경우 ──
    if target.get("status") in ("not_found", None):
        v["title_line1"] = f"'{area}' 을(를) 찾지 못했어요."
        v["title_line2"] = "행정동 이름으로 다시 입력해보시겠어요?"
        v["conclusion"]["tag"] = "안내"
        v["conclusion"]["title"] = "검색 결과 없음"
        v["conclusion"]["text"] = "예) 신길1동, 봉천동, 잠원동"
        _blank(v)
        return data

    # ── 여러 행정동에 걸치는 경우 ──
    if target["status"] == "ambiguous":
        names = ", ".join(c["name"] for c in target.get("candidates", [])[:6])
        v["title_line1"] = f"'{area}' 은(는) 여러 행정동에 걸쳐 있어요."
        v["title_line2"] = "어느 동을 보시겠어요?"
        v["conclusion"]["tag"] = "선택"
        v["conclusion"]["title"] = "행정동 선택"
        v["conclusion"]["text"] = names
        _blank(v)
        return data

    t_name = target["dong"]["name"]
    b_name = base["dong"]["name"]

    # ── 주거비가 산출되지 않은 동 ──
    if target["status"] == "no_data":
        v["title_line1"] = f"{t_name}은 주거비를 산출하지 못했어요."
        v["title_line2"] = "대신 인근 행정동을 보여드릴게요."
        v["conclusion"]["tag"] = "안내"
        v["conclusion"]["title"] = "산출 대상 아님"
        v["conclusion"]["text"] = target.get("reason", "")
        _blank(v, to_label=t_name)

        # 인근 후보를 추천 카드 자리에 넣는다. 템플릿 수정 불필요.
        rec = data["recommend"]
        bjd = target.get("shared_bjd")
        rec["title_line1"] = f"{t_name} 대신"
        rec["title_line2"] = f"같은 {bjd} 내 인근 행정동은 어떨까요?" if bjd else "인근 행정동은 어떨까요?"
        rec["description"] = (
            "아래 값은 각 행정동의 실제 데이터입니다.\n"
            f"{t_name}의 추정값이 아닙니다."
        )
        proto = rec["cards"][0]
        cards = []
        for i, a in enumerate(target.get("alternatives", []), start=1):
            c = copy.deepcopy(proto)
            c["rank"] = str(i)
            c["name"] = a["name"]
            c["type"] = f"{bjd} 생활권" if bjd else ""
            c["badge"] = f"거래 {a.get('tx_count') or 0:,}건"
            c["href"] = f"/compare?dong={a['name']}"
            c["metrics"] = [
                {"icon": "images/p5-icon-rent.png", "label": "월 총부담",
                 "value": f"{man(a.get('total'))} 만원"},
                {"icon": "images/p5-icon-time.png", "label": "편도 통근시간",
                 "value": f"{a.get('commute_min') or '—'}분"},
            ]
            c["summary"] = {"label": "표면주거비 산출 거래", "prefix": "",
                            "value": f"{a.get('tx_count') or 0:,}", "unit": "건"}
            c["note"] = {"icon": proto["note"]["icon"],
                         "text": f"{a['name']}의 실제 값이에요."}
            cards.append(c)
        rec["cards"] = cards
        return data

    # ── 정상 비교 ──
    tb, bb = _burden(target), _burden(base)
    r_from, r_to = bb.get("housing_cost"), tb.get("housing_cost")
    t_from, t_to = bb.get("total"), tb.get("total")
    extra = (tb.get("fare", 0) + tb.get("time_value", 0)) - (bb.get("fare", 0) + bb.get("time_value", 0))

    v["rent"].update({
        "from_value": man(r_from), "from_label": f"현재 {b_name}",
        "to_value": man(r_to), "to_label": t_name,
        "pill": diff_pill(r_from, r_to),
    })
    v["commute"]["time"].update({
        "from_value": str(bb.get("commute_min") or "—"),
        "to_value": str(tb.get("commute_min") or "—"),
        "pill": minute_pill(bb.get("commute_min"), tb.get("commute_min")),
    })
    v["commute"]["extra"].update({
        "from_value": "—",
        "to_value": f"{'+' if extra >= 0 else ''}{round(extra / 10000, 1):.1f}",
    })
    v["total"].update({
        "from_value": man(t_from), "from_label": f"현재 {b_name}",
        "to_value": man(t_to), "to_label": t_name,
        "pill": diff_pill(t_from, t_to),
    })

    # 결론은 결과를 보고 정한다. "월세 착시"를 무조건 띄우지 않는다.
    cheaper_rent = r_to < r_from
    heavier_total = t_to > t_from
    if cheaper_rent and heavier_total:
        v["title_line1"] = "월세는 저렴하지만,"
        v["title_line2"] = "통근까지 계산하면 오히려 더 부담이에요."
        v["conclusion"].update({
            "tag": "결론", "title": "월세 착시",
            "text": f"주거비 절감이 통근부담 증가로\n상쇄되어 오히려 더 부담됩니다.",
        })
    elif cheaper_rent:
        v["title_line1"] = "월세도 저렴하고,"
        v["title_line2"] = "통근까지 계산해도 부담이 줄어요."
        v["conclusion"].update({
            "tag": "결론", "title": "실질 절감",
            "text": "주거비 절감분이 통근부담 증가보다 커\n총부담이 줄어듭니다.",
        })
    else:
        v["title_line1"] = "월세가 더 비싸지만,"
        v["title_line2"] = "통근까지 계산하면 달라질 수 있어요."
        v["conclusion"].update({
            "tag": "결론", "title": "종합 비교",
            "text": "주거비와 통근부담을 함께 본 결과입니다.",
        })

    note = status_note(target)
    if note:
        v["rent"]["note"] = note
        v["conclusion"]["title"] += " (참고용)"

    return data