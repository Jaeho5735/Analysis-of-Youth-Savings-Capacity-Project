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
import re
from urllib.parse import urlencode

try:
    from src.db.query_dong import (get_dong, get_dong_by_name, list_work_options,
                                   nearest_routed_work, recommend_dongs,
                                   get_policies)
except ImportError:  # web/ 에서 직접 실행할 때
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.db.query_dong import (get_dong, get_dong_by_name, list_work_options,
                                   nearest_routed_work, recommend_dongs,
                                   get_policies)

try:
    from web.resolve_place import resolve as resolve_place
except ImportError:
    from src.db.resolve_place import resolve as resolve_place

# 현재 집 기준 동. 시연 시나리오의 잠원동.
BASE_DONG_CODE = "11650540"

# 근무지. 시연 시나리오의 역삼1동(삼정KPMG).
# 이 값이 있어야 통근시간이 "이 동에서 그 직장까지"가 된다.
# 없으면 거주동 전체 평균이 되어 근무지 축이 사라진다.
WORK_DONG_CODE = "11680640"

# ── 계산 상수 ─────────────────────────────────
WORK_DAYS_DEFAULT = 21                # 월 출근일수 기본값
TIME_VALUE_PER_HOUR = 10_320          # 최저임금
# 정기권 월 상한. DB 의 dim_transport_pass_assumption 기본 가정(youth_regular)과
# 같은 값이어야 한다. 화면만 다른 요금을 쓰면 조회 결과와 표시 금액이 어긋난다.
# 정기권 월 상한. 2026-09-01 기후동행카드가 모두의카드로 대체됐다.
# 모두의카드 정액형은 기준선을 넘는 금액을 100% 환급하므로, 계산상으로는
# 기준선이 곧 실질 상한이다. 그래서 산식은 기존 캡 방식 그대로 쓴다.
#   청년(만 19~39세) 55,000원 / 일반 62,000원
# data/정기권_가정.csv 가 원천이고 여기 값은 나이를 못 받았을 때의 기본값이다.
TRANSIT_PASS_CAP = 55_000             # 모두의카드 청년 기준선
TRANSIT_PASS_CAP_GENERAL = 62_000     # 모두의카드 일반 기준선
YOUTH_AGE_MIN, YOUTH_AGE_MAX = 19, 39

def _num_only(s, default=None):
    """'1,000만 원' 같은 입력에서 숫자만 뽑는다."""
    if s is None:
        return default
    d = re.sub(r"[^\d.]", "", str(s))
    if not d:
        return default
    try:
        return float(d)
    except ValueError:
        return default


# 노선 색. 실제 노선색을 쓰면 사용자가 아는 색으로 경로를 읽을 수 있다.

def _pass_for_age(age):
    """만 나이로 정기권 기준을 고른다.

    나이를 안 받았으면 청년 기준을 쓴다. 이 서비스의 분석 대상이 청년 1인가구라
    그게 기본 가정이고, 그 사실은 화면에도 함께 밝힌다.
    """
    n = _num_only(age, None)
    if n is None:
        return {"cap": TRANSIT_PASS_CAP, "is_youth": True, "age": None,
                "name": "모두의카드 청년", "code": "youth_regular",
                "note": "만 19~39세 청년 기준으로 계산했어요."}
    n = int(n)
    if YOUTH_AGE_MIN <= n <= YOUTH_AGE_MAX:
        return {"cap": TRANSIT_PASS_CAP, "is_youth": True, "age": n,
                "name": "모두의카드 청년", "code": "youth_regular",
                "note": f"만 {n}세는 청년 대상이라 대중교통비를 월 "
                        f"{TRANSIT_PASS_CAP:,}원까지만 부담해요(환급률 30%)."}
    return {"cap": TRANSIT_PASS_CAP_GENERAL, "is_youth": False, "age": n,
            "name": "모두의카드 일반", "code": "general",
            "note": f"만 {n}세는 청년 대상(만 19~39세)이 아니라 일반 기준 "
                    f"{TRANSIT_PASS_CAP_GENERAL:,}원이 적용돼요(환급률 20%)."}
# ─────────────────────────────────────────────────────────────
# 보증금 월환산 전월세전환율
#
# 이전에는 0.0348 단일 상수를 썼는데, 근거를 찾을 수 없는 값이었다.
# 파이프라인이 표면주거비를 만들 때 쓴 전환율(한국부동산원 지역별 고시,
# 거래 577,761건에 실제 적용된 값)의 중앙값은 5.9% 이고, 관측 범위는
# 연립다세대 4.1~5.6 / 단독다가구 5.2~7.5 / 오피스텔 5.5~5.8 이라
# 3.48% 는 전체 분포의 아래쪽 바깥이었다.
#
# 그 결과 "내 집"만 주거비가 낮게 잡히고 후보동은 실제 전환율로 계산돼,
# 같은 비교표의 두 열이 다른 산식 위에 놓여 있었다. 보증금이 클수록
# 어긋나서(1억이면 월 12.7만원) 이사 이득이 과소평가되는 방향이었다.
#
# 권역별 값은 거래단위 산출물의 권역별 중앙값이다(괄호는 거래 수).
# 사용자가 주택유형을 입력하지 않으므로 유형별로 나누지 않고 권역만 쓴다.
# 권역을 알 수 없으면 전체 중앙값으로 물러선다.
DEPOSIT_RATE_BY_REGION = {
    "도심권": 0.0610,   # 30,360건
    "동남권": 0.0539,   # 103,894건
    "동북권": 0.0620,   # 161,402건
    "서남권": 0.0590,   # 204,026건
    "서북권": 0.0620,   # 78,079건
}
DEPOSIT_RATE_DEFAULT = 0.0590   # 전체 중앙값 5.9%


def _region_of(dong_result):
    """get_dong() 결과에서 권역을 꺼낸다. 없으면 None.

    query_dong 이 region_group 을 돌려주지 않는 구버전이어도 조용히
    None 이 되고 전체 중앙값으로 계산된다. 화면이 멈추지 않게 한다.
    """
    if not isinstance(dong_result, dict):
        return None
    return (dong_result.get("dong") or {}).get("region_group")


def _deposit_monthly(deposit, dong_result=None):
    """보증금(만원 단위 입력)을 월 환산액으로 바꾼다.

    돌려주는 것: (월환산액_원, 적용전환율, 보증금_원)
    """
    dep = (_num_only(deposit, 0) or 0) * 10_000
    rate = DEPOSIT_RATE_BY_REGION.get(_region_of(dong_result),
                                      DEPOSIT_RATE_DEFAULT)
    return dep * rate / 12, rate, dep

SEOUL_AVG_COMMUTE_MIN = 29.4          # 2페이지 벤치마크와 같은 값

# 시연 경로(잠원동 -> 역삼1동). 이 조합에만 역 목록과 혼잡도가 있다.
# fact_commute_route 에는 이용노선과 환승횟수만 있고 역 이름 시퀀스가 없어서,
# 임의 입력에 대해서는 역 목록을 만들 수 없다. 혼잡도도 17번 노트북이 이 경로에
# 대해서만 수집했다. 없는 것을 지어내지 않고, 없다고 밝힌다.
#   시안 검산(동남권 5.39%): 1,000만 x 0.0539 / 12 = 44,917원
#   -> 월세 75만 + 4.5만 = 79.5만. 옛 3.48% 기준 77.9만에서 1.6만 오른다.



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


def _code_of(place, default):
    """'수유동' 같은 입력을 행정동코드로 바꾼다. 실패하면 기본값을 유지한다."""
    if not place:
        return default
    if str(place).isdigit():
        return str(place)
    try:
        r = resolve_place(place)
    except Exception:
        return default
    return (r.get("dong_code") or default) if r.get("status") == "ok" else default



def _monthly(b, days, cap):
    """경로 한 건에서 월 단위 값을 만든다. 모든 페이지가 이 함수만 쓴다.

    같은 사람의 총부담이 페이지마다 달랐던 원인이 여기 있었다. 같은 계산이
    세 군데에 따로 적혀 있었고, 각자 다른 값을 썼다.
      - 3페이지: 사용자 출근일수 + 나이별 정기권 상한
      - 4·6페이지: 사용자 출근일수 + 정기권 상한 55,000 고정
      - 5페이지: 조회 계층이 이미 계산한 값(21일·55,000 고정)을 그대로 사용
    그래서 22일·40세로 입력하면 세 페이지가 전부 다른 숫자를 보여줬다.

    days 와 cap 을 받는 이유는, 이 두 가지가 사용자 입력에 따라 달라지는
    유일한 값이기 때문이다. 여기서 상수를 읽지 않는다.
    """
    minutes = b.get("commute_min")
    hours = round(minutes * 2 * days / 60, 2) if minutes is not None else None
    time_value = round(hours * TIME_VALUE_PER_HOUR) if hours is not None else None

    one = b.get("oneway_fare")
    fare_actual = one * 2 * days if one is not None else None
    fare = min(fare_actual, cap) if fare_actual is not None else None

    return {"commute_min": minutes, "monthly_commute_hour": hours,
            "time_value": time_value, "fare": fare, "fare_actual": fare_actual,
            "transfer": b.get("transfer"), "work_days": days, "cap": cap}


def _baseline(residence, workplace, deposit=None, rent=None, work_days=None,
              age=None):
    """사용자 입력으로 '현재 기준' 값을 만든다. build_page3 와 같은 산식을 쓴다.

    실패하면 None 을 돌려준다. 4페이지는 이 값이 없으면 시연 기본값을 그대로 둔다.
    """
    if not residence or not workplace:
        return None
    home, work = resolve_place(residence), resolve_place(workplace)
    if home.get("status") != "ok" or work.get("status") != "ok":
        return None

    # 3페이지와 같은 대체 규칙을 쓴다. 거기서는 인근 근무동으로 대체해 값을
    # 냈는데 여기서만 포기하면, 3페이지에 137.8만원이 떠 있는데 4페이지는
    # "계산하지 못했어요"가 되어 같은 입력에 두 화면이 다른 말을 한다.
    work_code_used = work["dong_code"]
    substitute = None
    target = get_dong(home["dong_code"], work_code=work_code_used)
    if target.get("status") in ("no_route", "not_found", None):
        try:
            substitute = nearest_routed_work(home["dong_code"], work["dong_code"])
        except Exception:
            substitute = None
        if substitute:
            work_code_used = substitute["code"]
            target = get_dong(home["dong_code"], work_code=work_code_used)
    if target.get("status") in ("no_route", "not_found", None):
        return None

    b = target.get("burden") or {}
    days = int(_num_only(work_days, 21) or 21)
    dep_monthly, _rate, dep = _deposit_monthly(deposit, target)
    mrent = (_num_only(rent, 0) or 0) * 10_000

    housing = mrent + dep_monthly
    m = _monthly(b, days, _pass_for_age(age)["cap"])
    minutes, hours = m["commute_min"], m["monthly_commute_hour"]
    time_value, fare, fare_actual = m["time_value"], m["fare"], m["fare_actual"]

    return {
        "home_name": home.get("dong_name") or residence,
        "work_name": work.get("dong_name") or workplace,
        "home_label": residence, "work_label": workplace,
        "home_code": home["dong_code"], "work_code": work_code_used,
        "work_code_input": work["dong_code"],
        "substitute": substitute,
        "housing": housing, "commute_min": minutes,
        "fare": fare, "time_value": time_value,
        "total": housing + (fare or 0) + (time_value or 0),
        "work_days": days,
    }


def man1(v):
    """원 단위를 만원 소수 첫째자리 문자열로."""
    return "—" if v is None else f"{v / 10_000:.1f}"


def _candidate_summary(base, cand, gap_rent, gap_total, gap_min):
    """후보 한 곳에 대한 한 단락 요약. 숫자를 나열하지 않고 결론까지 말한다."""
    # 월세와 통근이 같은 방향이면 "낮고", 반대면 "낮지만" 으로 이어야
    # 문장이 읽힌다. 한쪽만 보고 접속사를 정하면 "낮지만 줄어" 처럼 어긋난다.
    rent_better = gap_rent > 0
    commute_worse = gap_min is not None and gap_min > 0
    same_way = (rent_better and not commute_worse) or (not rent_better and commute_worse)
    conj = "고" if same_way else "지만"

    parts = []
    if gap_rent > 0:
        parts.append(f"월세는 현재보다 약 {gap_rent / 10000:.0f}만 원 낮{conj}")
    elif gap_rent < 0:
        parts.append(f"월세는 현재보다 약 {abs(gap_rent) / 10000:.0f}만 원 "
                     f"{'높고' if same_way else '높지만'}")
    else:
        parts.append("월세는 현재와 비슷하{}".format("고" if same_way else "지만"))

    if gap_min is not None and abs(gap_min) >= 0.5:
        parts.append(f"편도 통근시간도 {abs(gap_min):.1f}분 "
                     f"{'늘어' if gap_min > 0 else '줄어'}"
                     if same_way else
                     f"편도 통근시간이 {abs(gap_min):.1f}분 "
                     f"{'늘어' if gap_min > 0 else '줄어'}")
    else:
        parts.append("통근시간은 크게 다르지 않아")

    if gap_total > 0:
        parts.append(f"교통비와 시간가치를 반영한 월 총부담은 약 "
                     f"{gap_total / 10000:.0f}만 원 더 낮아집니다.")
        tail = ("월세뿐 아니라 통근까지 함께 줄어드는 경우입니다." if gap_rent > 0
                else "월세는 오르지만 통근이 더 크게 줄어 총부담이 낮아지는 경우입니다.")
    elif gap_total < 0:
        parts.append(f"교통비와 시간가치를 반영한 월 총부담은 약 "
                     f"{abs(gap_total) / 10000:.0f}만 원 더 높아집니다.")
        tail = ("월세만 보면 저렴하지만 전체 부담은 오히려 커지는 '월세 착시' 사례입니다."
                if gap_rent > 0 else "월세도 총부담도 모두 늘어나는 경우입니다.")
    else:
        parts.append("월 총부담은 현재와 거의 같습니다.")
        tail = "월세 차이가 통근부담으로 그대로 상쇄된 경우입니다."
    return " ".join(parts) + " " + tail


def build_page4(base_json, residence=None, workplace=None, deposit=None,
                rent=None, work_days=None, depart_time=None, carry_qs="",
                area=None, age=None):
    """3페이지에서 넘어온 입력으로 4페이지 '현재 기준' 패널을 채운다.

    입력이 없거나 조회에 실패하면 원본 JSON(시연 기본값)을 그대로 둔다.
    화면이 비어 보이는 것보다는 기본값이 낫고, 대신 사용자 입력이 있을 때만
    실제 값으로 갈아끼운다.
    """
    data = copy.deepcopy(base_json)
    data["carry_qs"] = carry_qs

    # 검색창 값. 사용자가 방금 입력한 후보(area)가 있으면 그대로 남겨
    # 무엇을 조회한 결과인지 보이게 한다.
    # 입력이 없을 때만 시연용 기본값("신길1동")을 비운다. 그게 남아 있으면
    # 사용자가 넣은 적 없는 값이 자기 입력처럼 보인다.
    if area:
        data["hero"]["search"]["value"] = area
    elif residence or workplace:
        data["hero"]["search"]["value"] = ""

    _carry_nav(data, carry_qs)

    bl = _baseline(residence, workplace, deposit, rent, work_days, age=age)
    if bl is None:
        # 조회에 실패해도 사용자가 입력한 직장·거주지는 그대로 보여준다.
        # 시연 기본값(삼정KPMG·잠원동)을 남기면 입력하지 않은 값이
        # 자기 입력처럼 보여서, 화면 전체를 못 믿게 된다.
        if residence or workplace:
            b = data["baseline"]
            b["rows"] = [
                {"icon": "work", "label": "직장",
                 "value": workplace or "—", "unit": "", "strong": False},
                {"icon": "home", "label": "현재 거주지",
                 "value": f"{residence} (현재)" if residence else "—",
                 "unit": "", "strong": False},
            ]
            for m in b["metrics"]:
                m["value"] = "—"
            b["total"]["value"] = "—"
            data["hero"]["description_line1"] = (
                f"내가 생각한 후보를 같은 직장({workplace}) 기준으로"
                if workplace else data["hero"]["description_line1"])
            data["compare"]["description"] = (
                "현재 기준 값을 계산하지 못했어요. "
                "후보 지역만 단독으로 확인해보세요.")
        return data

    work_label = bl["work_label"]
    h = data["hero"]
    h["description_line1"] = f"내가 생각한 후보를 같은 직장({work_label}) 기준으로"
    # 검색창 값은 위에서 이미 정했다(입력이 있으면 그 값, 없으면 빈칸).
    # 여기서 다시 비우면 사용자가 방금 넣은 후보가 화면에서 사라진다.

    b = data["baseline"]
    b["rows"] = [
        {"icon": "work", "label": "직장", "value": work_label, "unit": "", "strong": False},
        {"icon": "home", "label": "현재 거주지",
         "value": f"{bl['home_name']} (현재)", "unit": "", "strong": False},
    ]
    b["metrics"] = [
        {"icon": "rent", "label": "주거비", "value": man1(bl["housing"]), "unit": "만 원"},
        {"icon": "commute", "label": "편도 통근",
         "value": "—" if bl["commute_min"] is None else f"{bl['commute_min']:.1f}", "unit": "분"},
        {"icon": "fare", "label": "월 교통비", "value": man1(bl["fare"]), "unit": "만 원"},
        {"icon": "commute", "label": "통근시간 가치", "value": man1(bl["time_value"]), "unit": "만 원"},
    ]
    b["total"]["value"] = man1(bl["total"])

    # bl 이 확정된 직후에 남긴다. 이 함수는 후보(area) 미입력이면
    # 아래에서 먼저 return 하는데, 그 화면도 "현재 기준" 패널에 총부담을
    # 이미 보여주고 있다. 함수 끝에 두면 그 경로에서 값이 안 남는다.
    # 페이지 간 총부담 일치를 검증할 수 있게 계산값을 그대로 남긴다.
    # 3페이지가 쓰는 것과 같은 자리·같은 키다. 화면에는 쓰이지 않는다.
    # 이게 없으면 테스트가 화면 문자열을 파싱해야 하고, 그러면
    # 계산이 멀쩡해도 템플릿만 바꾸면 테스트가 깨진다.
    data["_calc"] = {
        "housing": bl["housing"], "fare": bl["fare"],
        "time_value": bl["time_value"], "total": bl["total"],
        "work_days": bl["work_days"], "commute_min": bl["commute_min"],
        "transit_pass_cap": _pass_for_age(age)["cap"],
        "home": bl["home_name"], "work": bl["work_name"],
    }

    # 대체 계산했다면 밝힌다. 3페이지와 같은 규칙이므로 문구도 맞춘다.
    sub = bl.get("substitute")
    if sub:
        rel = "같은 " + sub["gu"] if sub.get("same_gu") else "인근"
        b["rows"][0]["value"] = f"{work_label} → {sub['name']} (대체)"
        data["compare"]["basis_note"] = (
            f"{sub['requested_name']}은 출퇴근 경로 자료가 없어 "
            f"{rel}의 {sub['name']} 기준으로 계산했어요.")

    data["compare"]["description"] = (
        f"같은 직장({work_label}) 기준으로 주거비, 통근시간, 교통비, "
        "총부담까지 한눈에 비교해보세요.")

    # 후보를 입력했으면 같은 페이지에서 바로 검증 결과를 보여준다.
    # 다른 페이지로 넘겼다가 돌아오게 하면 흐름이 끊긴다.
    # 추천과 후보 검증은 사용자가 입력한 원래 근무지를 기준으로 한다.
    # 대체(work_code)는 "현재 집 통근시간"을 못 구할 때만 쓰는 임시방편인데,
    # 그걸 추천 기준까지 끌고 가면 화면은 "서울역 출근"이라 해놓고 실제로는
    # 한강로동 기준으로 뽑아 값이 5분씩 짧아진다.
    ref_work = bl.get("work_code_input") or bl["work_code"]

    if area:
        why = []
        cand = _col_of(area, ref_work, work_days=work_days, reason=why)
        if cand:
            gap_rent = bl["housing"] - cand["housing"]
            gap_total = bl["total"] - cand["total"]
            gap_min = ((cand["commute_min"] - bl["commute_min"])
                       if None not in (cand["commute_min"], bl["commute_min"]) else None)
            extra = (cand["fare"] + cand["time_value"]) - (bl["fare"] + bl["time_value"])

            data["compare"]["candidate"] = {
                "name": cand["name"],
                "type": cand["type"],
                "metrics": [
                    {"label": "후보 주거비", "value": f"{cand['housing'] / 10000:.1f}만 원"},
                    {"label": "편도 통근",
                     "value": "—" if cand["commute_min"] is None
                              else f"{cand['commute_min']:.1f}분"},
                    {"label": "추가 통근부담",
                     "value": f"{'+' if extra >= 0 else '−'}{abs(extra) / 10000:.1f}만 원"},
                    {"label": "월 총부담", "value": f"{cand['total'] / 10000:.1f}만 원"},
                ],
                "summary": _candidate_summary(bl, cand, gap_rent, gap_total, gap_min),
                "tone": "warn" if (gap_rent > 0 and gap_total < 0) else
                        ("good" if gap_total > 0 else "info"),
                "detail_href": (f"/explore/result?area={cand['name']}"
                                + (f"&{carry_qs}" if carry_qs else "")),
            }
        else:
            data["compare"]["candidate_error"] = (
                why[0] if why
                else f"'{area}' 은(는) 서울 밖이거나 이 직장으로 가는 경로 자료가 없어요.")

    # 추천은 후보를 입력한 뒤에만 보여준다.
    # 입력 전에 먼저 띄우면 사용자가 넣지도 않은 지역이 결과처럼 보이고,
    # "여기에 표시됩니다" 안내와도 앞뒤가 맞지 않는다.
    if not area:
        data["compare"]["picks"] = []
        data["compare"]["empty"]["title"] = "비교 결과가 여기에 표시됩니다"
        data["compare"]["empty"]["description"] = (
            "위에 지역을 입력하고 '현재 집과 비교하기'를 눌러주세요.")
        return data

    try:
        picks = recommend_dongs(ref_work,
                                exclude=(bl["home_code"],), limit=3)
    except Exception:
        picks = []

    data["compare"]["picks"] = [{
        "rank": str(i),
        "name": a["name"],
        "gu": a.get("gu") or "",
        "type": a.get("dong_type") or "",
        "housing": f"{a['housing'] / 10000:.1f}",
        "commute": f"{a['commute_min']:.1f}",
        "fare": f"{a['fare'] / 10000:.1f}",
        "transfer": ("환승 없음" if a.get("transfer") == 0
                     else f"환승 {int(a['transfer'])}회"
                     if a.get("transfer") is not None else "—"),
        "total": f"{a['total'] / 10000:.1f}",
        "gap": f"{abs(bl['total'] - a['total']) / 10000:.1f}",
        "gap_down": bl["total"] >= a["total"],
        "href": f"/explore/result?area={a['name']}&" + (carry_qs or ""),
    } for i, a in enumerate(picks, start=1)]

    if data["compare"]["picks"]:
        data["compare"]["picks_title"] = (
            f"{work_label} 출근이라면 이 세 곳을 먼저 보세요")
        data["compare"]["picks_note"] = (
            "실제 출근 흐름이 있는 지역 중 총부담이 낮은 순으로 골랐어요. "
            "카드를 누르면 현재 집과 자세히 비교합니다.")
    return data


def build_page5(base_json, area=None, base_code=BASE_DONG_CODE,
                work_code=WORK_DONG_CODE, base_place=None, work_place=None,
                deposit=None, rent=None, work_days=None, age=None):
    """page5 JSON 을 조회 결과로 갱신해 돌려준다. 원본은 건드리지 않는다.

    base_place / work_place 를 넘기면 그 값으로 비교 기준을 잡는다. 이걸 안 넘기면
    시연 페르소나(잠원동 -> 역삼1동)로 고정되어, 사용자가 다른 거주지·근무지를
    입력해도 대안 탐색만 엉뚱한 기준으로 비교하게 된다.
    """
    data = copy.deepcopy(base_json)
    if not area:
        return data

    base_code = _code_of(base_place, base_code)
    work_code = _code_of(work_place, work_code)

    # 후보 지역도 2페이지 입력과 같은 방식으로 해석한다.
    # 행정동명 직매칭만 쓰면 "신도림역"·"삼성동 아이파크" 같은 입력이 전부
    # 실패하는데, 사용자는 자기 집을 행정동으로 부르지 않는다.
    #   1) 숫자면 코드로 본다
    #   2) resolve_place 로 역명·건물명·도로명·지번을 행정동으로 옮긴다
    #   3) 그래도 안 되면 기존 행정동명 직매칭으로 물러선다
    area_label = area
    if str(area).isdigit():
        target = get_dong(area, work_code=work_code)
    else:
        target, resolved = None, None
        try:
            resolved = resolve_place(area)
        except Exception:
            resolved = None
        if resolved and resolved.get("status") == "ok" and resolved.get("dong_code"):
            target = get_dong(resolved["dong_code"], work_code=work_code)
            if target.get("status") in ("not_found", None):
                target = None
            else:
                area_label = resolved.get("dong_name") or area
        if target is None:
            target = get_dong_by_name(area, work_code=work_code)
    base, base_sub = _base_with_fallback(base_code, work_code)

    data["hero"]["search"]["value"] = area
    v = data["verdict"]
    # 아래 문구는 실제로 조회된 행정동 이름을 쓴다
    area = area_label

    # ── 찾지 못한 경우 ──
    if target.get("status") in ("not_found", None):
        v["title_line1"] = f"'{area}' 은(는) 서울 밖이거나 찾을 수 없어요."
        v["title_line2"] = "지하철역·건물명·주소·행정동 모두 입력할 수 있어요."
        v["conclusion"]["tag"] = "안내"
        v["conclusion"]["title"] = "검색 결과 없음"
        v["conclusion"]["text"] = "예) 신길1동, 봉천동, 잠원동"
        _blank(v)
        return data

    # ── 그 근무지로 가는 경로가 없는 경우 ──
    if target["status"] == "no_route":
        nm = target["dong"]["name"]
        v["title_line1"] = f"{nm}에서 이 직장으로 가는"
        v["title_line2"] = "경로 데이터가 없어요."
        v["conclusion"]["tag"] = "안내"
        v["conclusion"]["title"] = "경로 없음"
        v["conclusion"]["text"] = target.get("reason", "")
        _blank(v, to_label=nm)
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
        qs = data.get("carry_qs") or ""
        for i, a in enumerate(target.get("alternatives", []), start=1):
            c = copy.deepcopy(proto)
            c["rank"] = str(i)
            c["name"] = a["name"]
            c["type"] = f"{bjd} 생활권" if bjd else ""
            c["badge"] = f"거래 {a.get('tx_count') or 0:,}건"
            c["href"] = f"/compare?dong={a['name']}" + (f"&{qs}" if qs else "")
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
    # 조회 계층이 돌려준 fare·time_value 는 기본 가정(21일·청년 상한)으로
    # 계산된 값이라 그대로 쓰면 3·4페이지와 어긋난다. 여기서 다시 만든다.
    days5 = int(_num_only(work_days, WORK_DAYS_DEFAULT) or WORK_DAYS_DEFAULT)
    cap5 = _pass_for_age(age)["cap"]
    tb, bb = dict(_burden(target)), dict(_burden(base))
    tb.update(_monthly(tb, days5, cap5))
    bb.update(_monthly(bb, days5, cap5))
    for d in (tb, bb):
        h = d.get("housing_cost")
        d["total"] = (None if None in (h, d.get("fare"), d.get("time_value"))
                      else h + d["fare"] + d["time_value"])
    r_from, r_to = bb.get("housing_cost"), tb.get("housing_cost")

    # 현재 집 주거비는 그 동네 중앙값이 아니라 사용자가 입력한 월세·보증금을 쓴다.
    # 중앙값을 쓰면 3페이지에서 "총부담 129.6만원"을 본 사람이 5페이지에서
    # 같은 집을 "106.2만원"으로 보게 되어, 어느 쪽을 믿어야 할지 알 수 없다.
    own_housing = None
    if rent or deposit:
        own_housing = ((_num_only(rent, 0) or 0) * 10_000
                       + _deposit_monthly(deposit, base)[0])
        r_from = own_housing

    t_from = (r_from or 0) + (bb.get("fare") or 0) + (bb.get("time_value") or 0)
    t_to = tb.get("total")
    # .get(키, 0) 은 키가 "없을 때"만 0 을 준다. 키가 있고 값이 None 이면
    # None 을 그대로 돌려줘 None + 0 에서 터진다.
    # 근무지와 같은 동을 후보로 넣으면(직주일치) 통근 자료가 없어 fare 가 None 이 된다.
    # 바로 위 t_from 처럼 or 0 으로 받는다.
    extra = (((tb.get("fare") or 0) + (tb.get("time_value") or 0))
             - ((bb.get("fare") or 0) + (bb.get("time_value") or 0)))

    v["rent"].update({
        "from_value": man(r_from), "from_label": f"현재 {b_name}",
        "to_value": man(r_to), "to_label": t_name,
        "pill": diff_pill(r_from, r_to),
    })
    if tb.get("transfer") is not None:
        v["commute"]["title"] = f"하지만 통근까지 계산하면... (환승 {int(tb['transfer'])}회)"
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
    elif not heavier_total:
        # 월세는 오르지만 통근이 줄어 총부담이 내려가는 경우.
        # 여기를 "종합 비교"로 뭉뚱그리면 사용자는 결론을 못 읽는다.
        v["title_line1"] = "월세는 더 비싸지만,"
        v["title_line2"] = "통근까지 계산하면 오히려 부담이 줄어요."
        v["conclusion"].update({
            "tag": "결론", "title": "숨은 효율",
            "text": "주거비는 늘지만 통근부담이 더 크게 줄어\n총부담이 낮아집니다.",
        })
    else:
        v["title_line1"] = "월세도 더 비싸고,"
        v["title_line2"] = "통근까지 더하면 부담이 더 커져요."
        v["conclusion"].update({
            "tag": "결론", "title": "종합 부담 증가",
            "text": "주거비와 통근부담이 모두 늘어\n총부담이 커집니다.",
        })

    # 비교 기준이 서로 다르다는 점을 밝힌다. 현재는 내가 내는 실제 금액,
    # 후보는 그 동네 청년 1인가구 중앙값이다.
    basis = ("현재는 입력하신 월세·보증금 기준, "
             "후보는 그 동네 청년 1인가구 중앙값 기준이에요."
             if own_housing is not None else
             "두 값 모두 청년 1인가구 월세 중앙값 기준이에요.")
    if base_sub:
        rel = "같은 " + base_sub["gu"] if base_sub.get("same_gu") else "인근"
        basis += (f" 현재 집 통근은 {base_sub['requested_name']} 경로 자료가 없어 "
                  f"{rel}의 {base_sub['name']} 기준으로 계산했어요.")
    note = status_note(target)
    v["rent"]["note"] = f"{note} {basis}".strip() if note else basis
    if note:
        v["conclusion"]["title"] += " (참고용)"

    # 추천 섹션. 여기를 갱신하지 않으면 위쪽 비교만 실제 값이고 아래는 시연
    # 기본값(삼정KPMG·청림동 등)이 남아, 한 화면에 서로 다른 근무지가 섞인다.
    # 시연용 질문 문구에 남아 있는 지역명을 실제 입력으로 바꾼다.
    _refresh_chips(data, area_name=t_name, work_name=work_place)

    qs = urlencode({k: v for k, v in {
        "residence": base_place or "", "workplace": work_place or "",
        "deposit": deposit or "", "rent": rent or "",
        "work_days": work_days or "",
        "age": age or "",
    }.items() if v})
    data["carry_qs"] = qs
    _carry_nav(data, qs)
    # 추천 후보를 못 찾아도 상세 비교로는 갈 수 있어야 한다.
    if data.get("recommend", {}).get("cta"):
        data["recommend"]["cta"]["href"] = "/compare" + (f"?{qs}" if qs else "")

    _fill_recommend(data, work_code=work_code, work_label=work_place,
                    exclude=(base_code, target["dong"]["code"]),
                    base_total=t_from)
    # 페이지 간 총부담 일치를 검증할 수 있게 계산값을 그대로 남긴다.
    # 3페이지가 쓰는 것과 같은 자리·같은 키다. 화면에는 쓰이지 않는다.
    # 이게 없으면 테스트가 화면 문자열을 파싱해야 하고, 그러면
    # 계산이 멀쩡해도 템플릿만 바꾸면 테스트가 깨진다.
    # 여기서 남기는 값은 후보동이 아니라 "현재 집"(base) 기준이다.
    # 3·4·6페이지의 총부담과 같은 값이어야 한다.
    data["_calc"] = {
        "housing": r_from, "fare": bb.get("fare"),
        "time_value": bb.get("time_value"), "total": t_from,
        "work_days": days5, "commute_min": bb.get("commute_min"),
        "transit_pass_cap": cap5,
        "home": b_name, "work": work_place,
        "candidate": {"name": t_name, "total": t_to},
    }
    return data


def _carry_nav(data, qs):
    """상단 네비게이션 링크에도 입력을 실어 보낸다.

    이게 없으면 '상세 비교' 탭으로 이동하는 순간 파라미터가 사라져
    시연 기본값(잠원동·청림동) 화면이 뜬다. 버튼만 고쳐서는 안 되는 이유다.
    """
    if not qs:
        return
    for item in data.get("nav") or []:
        href = item.get("href") or ""
        if href.startswith("/") and "?" not in href and href != "/":
            item["href"] = f"{href}?{qs}"


def _refresh_chips(data, area_name, work_name):
    """질문 예시에 박힌 시연 지역명(신길1동 등)을 실제 입력으로 바꾼다."""
    if not area_name:
        return
    for key in ("chat", "faq"):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        field = "chips" if "chips" in block else "questions"
        items = block.get(field)
        if not isinstance(items, list):
            continue
        block[field] = [
            f"{area_name}은 왜 이런 결과가 나왔어요?" if "신길" in q
            else q.replace("삼정KPMG", work_name or "이 직장")
            for q in items
        ]


def _fill_recommend(data, work_code, work_label, exclude, base_total):
    rec = data.get("recommend")
    if not rec or not rec.get("cards"):
        return
    proto = copy.deepcopy(rec["cards"][0])

    try:
        picks = recommend_dongs(work_code, exclude=exclude, limit=3)
    except Exception:
        picks = []

    work_name = work_label or "이 직장"
    rec["title_line1"] = f"그렇다면, {work_name} 출근에는"
    rec["title_line2"] = "어디가 더 나을까요?"

    if not picks:
        rec["description"] = (f"{work_name}으로 통근 가능한 지역 중 "
                              "비교할 후보를 찾지 못했어요.")
        rec["cards"] = []
        return

    qs = data.get("carry_qs") or ""
    rec["description"] = (
        f"실제 {work_name} 출근 흐름이 존재하는 지역 중\n"
        "주거비·통근시간·교통비를 함께 비교하고,\n"
        "서로 다른 부담구조 유형의 지역을 추천했어요.")

    colors = ["teal", "blue", "teal"]
    cards = []
    for i, a in enumerate(picks, start=1):
        c = copy.deepcopy(proto)
        gap = (base_total - a["total"]) if base_total is not None else None
        c["rank"] = str(i)
        c["rank_color"] = colors[(i - 1) % len(colors)]
        c["name"] = a["name"]
        c["type"] = a.get("dong_type") or ""
        c["badge"] = "총부담 절감 1위" if i == 1 else f"총부담 {i}위"
        c["badge_color"] = "green" if i == 1 else "blue"
        c["href"] = f"/compare?dong={a['name']}" + (f"&{qs}" if qs else "")
        c["metrics"] = [
            {"icon": "images/p5-icon-rent.png", "label": "대표 주거비",
             "value": f"{a['housing'] / 10000:.1f} 만원"},
            {"icon": "images/p5-icon-time.png", "label": "편도 통근시간",
             "value": f"{a['commute_min']:.1f}분"},
            {"icon": "images/p5-icon-fare.png", "label": "월 교통비",
             "value": f"{a['fare'] / 10000:.1f}만원"},
            {"icon": "images/p5-icon-transfer.png", "label": "환승",
             "value": f"{int(a['transfer'])}회" if a.get("transfer") is not None else "—"},
        ]
        if gap is None:
            c["summary"] = {"label": "월 총부담", "prefix": "약",
                            "value": f"{a['total'] / 10000:.1f}", "unit": "만원"}
        else:
            c["summary"] = {"label": "현재 대비 총부담", "prefix": "약",
                            "value": f"{abs(gap) / 10000:.1f}",
                            "unit": "만원 감소" if gap >= 0 else "만원 증가"}
        c["note"] = {"icon": proto.get("note", {}).get("icon", ""),
                     "text": f"{a['gu']} {a['name']}의 실제 값이에요."}
        cards.append(c)
    rec["cards"] = cards

# ═════════════════════════════════════════════════════════════
# 6페이지 — 상세 비교
# ═════════════════════════════════════════════════════════════

_TONES = ["cand1", "cand2", "cand3"]
_SEG_COLORS = ["#5cbdb0", "#4a7fd6", "#9a86d4"]     # 주거비 / 교통비 / 시간가치
_TRANSIT_ICONS = ["images/p6-train-1.png", "images/p6-train-2.png",
                  "images/p6-train-3.png", "images/p6-train-4.png"]


def _base_with_fallback(base_code, work_code):
    """현재 집의 통근값을 구한다. 경로가 없으면 인근 근무동으로 대체한다.

    대체하지 않으면 통근시간이 비어 시간가치가 0이 되고, 그 상태로 총부담을
    비교하면 "주거비는 27만원 줄었는데 총부담은 차이 없음" 같은 값이 나온다.
    3페이지가 이미 같은 규칙을 쓰므로 여기서도 맞춘다.
    돌려주는 값은 (조회결과, 대체정보) 이며 대체정보는 화면에 밝혀야 한다.
    """
    base = get_dong(base_code, work_code=work_code)
    has_time = bool((base.get("burden") or {}).get("commute_min"))
    if base.get("status") not in ("no_route", "not_found", None) and has_time:
        return base, None

    try:
        sub = nearest_routed_work(base_code, work_code)
    except Exception:
        sub = None
    if not sub:
        return base, None

    alt = get_dong(base_code, work_code=sub["code"])
    if alt.get("status") in ("no_route", "not_found", None):
        return base, None
    return alt, sub



# ═════════════════════════════════════════════════════════════
# 지원 정책 카드 (6페이지 support 섹션)
# ═════════════════════════════════════════════════════════════

# 아이콘은 강사님 시안의 4종을 그대로 돌려쓴다. 새 이미지를 만들지 않는다.
_SUPPORT_ICONS = {
    "housing_subsidy": "images/p6-support-1.png",
    "transport":       "images/p6-support-2.png",
    "deposit_product": "images/p6-support-3.png",
    "loan":            "images/p6-support-4.png",
    "living_subsidy":  "images/p6-support-4.png",
    "info":            "images/p6-support-4.png",
}
_SUPPORT_ICON_DEFAULT = "images/p6-support-1.png"

# 부담요인 태그: 1 높은월세 2 높은보증금 3 높은통근교통비
#               4 낮은현금흐름 5 자산형성 6 보증금반환위험


def _support_rank(base_col, deposit=None, rent=None):
    """이 사람의 부담 구성으로 부담요인 태그에 점수를 매긴다.

    조건 필터(나이·소득·월세)만으로는 개인화가 되지 않는다. 청년 대상
    정책 대부분이 나이와 소득만 보기 때문에, 20~39세 구간에서는 거의
    같은 목록이 나온다. 그래서 "받을 수 있는가"는 조건으로 거르고,
    "먼저 보여줄 것인가"는 여기서 정한다.

    쓰는 재료는 이미 계산된 값뿐이다. 임계값을 새로 만들지 않으려고
    서울 평균 통근시간처럼 이미 화면에 쓰고 있는 기준선만 쓴다.
    """
    score = {1: 3, 2: 2, 3: 2, 4: 1, 5: 0, 6: 0}   # 기본 순서
    if not base_col:
        return score

    total = base_col.get("total") or 0
    housing = base_col.get("housing") or 0
    minutes = base_col.get("commute_min")

    # 주거비가 부담의 대부분이면 월세·보증금 지원을 앞으로
    if total and housing / total >= 0.70:
        score[1] += 4
        score[2] += 2

    # 통근이 서울 평균보다 길면 교통 지원을 앞으로
    if minutes is not None and minutes > SEOUL_AVG_COMMUTE_MIN:
        score[3] += 4

    # 보증금 월환산이 월세보다 크면 보증금 쪽 부담이 실질적으로 더 크다
    # 권역을 넘겨야 화면에 표시되는 월환산액과 같은 전환율을 쓴다.
    # 안 넘기면 항상 전체 중앙값 5.9% 가 적용돼, 화면은 "월세가 더 크다"인데
    # 순위는 "보증금이 더 크다"로 판단하는 상태가 된다.
    dep_monthly = _deposit_monthly(
        deposit,
        {"dong": {"region_group": base_col.get("region_group")}})[0]
    mrent = (_num_only(rent, 0) or 0) * 10_000
    if dep_monthly and mrent and dep_monthly > mrent:
        score[2] += 3
        score[6] += 2

    return score


def _support_items(base_col=None, age=None, deposit=None, rent=None):
    """support.items 를 정책 조회 결과로 만든다.

    실패하면 None 을 돌려주고, 호출한 쪽은 시안 기본값을 그대로 둔다.
    지원 정보가 안 뜨는 것보다 화면이 죽는 게 더 나쁘다.
    """
    rent_won = (_num_only(rent, 0) or 0) * 10_000 or None
    try:
        res = get_policies(age=_num_only(age, None), income=None, rent=rent_won)
    except Exception:
        return None, None
    matched = res.get("matched") or []
    if not matched:
        return None, None

    score = _support_rank(base_col, deposit, rent)

    def key(p):
        # 점수 높은 태그 먼저 -> 상시 신청 먼저(기간제를 앞세우면 이미 마감된
        # 사업이 첫 칸에 온다) -> 이름순으로 고정해 매번 같은 순서가 되게
        period_last = 1 if (p.get("apply_type") or "") == "기간제" else 0
        info_last = 1 if p.get("is_info") else 0
        return (-score.get(p.get("burden_tag"), 0), info_last, period_last,
                p.get("policy_name") or "")

    items = []
    for p in sorted(matched, key=key):
        name = p.get("policy_name") or ""
        # 조회 계층은 확인하지 못한 조건을 unchecked 로 남긴다.
        # 2페이지 폼에 소득 칸이 없어 소득은 늘 미확인이다.
        # 이걸 버리면 월소득 128만원 이하 대상 정책이 월 280만원 버는
        # 사용자에게 아무 표시 없이 뜬다. 화면까지 그대로 전달한다.
        unchecked = p.get("unchecked") or []
        items.append({
            "label": _wrap_support_label(name),
            "icon": _SUPPORT_ICONS.get(p.get("category"), _SUPPORT_ICON_DEFAULT),
            # 시안은 전부 "#" 이라 눌러도 아무 일이 없었다. 공식 페이지로 보낸다.
            "href": p.get("source_url") or "#",
            "note": ("·".join(unchecked) + " 조건 확인 필요") if unchecked else "",
        })
    return items, res.get("as_of")


def _wrap_support_label(name, width=9):
    """카드 라벨을 두 줄로 나눈다. 시안도 '청년전용\\n주거 지원' 형태다.

    한 줄이 길어지지 않게, 두 줄의 길이 차가 가장 작은 지점에서 자른다.
    """
    name = (name or "").strip()
    if len(name) <= width:
        return name
    words = name.split(" ")
    if len(words) < 2:
        return name
    best, best_cost = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        cost = max(len(a), len(b)) * 10 + abs(len(a) - len(b))
        if best_cost is None or cost < best_cost:
            best, best_cost = (a, b), cost
    return best[0] + "\n" + best[1]


def _col_of(place, work_code, deposit=None, rent=None, work_days=None,
            own_housing=False, reason=None, cap=None):
    """비교 표의 한 열을 만든다. 조회 실패하면 None.

    reason 에 리스트를 넘기면 실패 사유를 담아준다. 화면에서 "안 나온다"만
    보이면 원인을 알 수 없어서, 왜 실패했는지 호출한 쪽에 알린다.
    """
    def fail(msg):
        if reason is not None:
            reason.append(msg)
        return None

    code = _code_of(place, None)
    if not code:
        return fail(f"'{place}' 을(를) 지역으로 해석하지 못했어요.")
    if not work_code:
        return fail("근무지를 확인하지 못했어요.")
    try:
        t = get_dong(code, work_code=work_code)
    except Exception as e:
        return fail(f"조회 중 오류가 났어요. ({type(e).__name__})")
    if t.get("status") in ("no_route", "not_found", None):
        return fail(f"'{place}' 에서 이 직장으로 가는 경로 자료가 없어요.")
    b = t.get("burden") or {}
    days = int(_num_only(work_days, WORK_DAYS_DEFAULT) or WORK_DAYS_DEFAULT)

    m = _monthly(b, days, cap if cap is not None else TRANSIT_PASS_CAP)
    minutes = m["commute_min"]
    time_value = m["time_value"] if m["time_value"] is not None else 0
    fare = m["fare"] if m["fare"] is not None else 0

    # 현재 집만 사용자가 입력한 월세·보증금을 쓴다. 후보는 그 동네 중앙값.
    if own_housing and (rent or deposit):
        housing = ((_num_only(rent, 0) or 0) * 10_000
                   + _deposit_monthly(deposit, t)[0])
    else:
        housing = b.get("housing_cost") or 0

    return {
        "name": (t.get("dong") or {}).get("name") or place,
        "type": (t.get("dong_type") or "").strip(),
        "housing": housing, "fare": fare, "time_value": time_value,
        "commute_min": minutes, "transfer": b.get("transfer"),
        # 보증금 월환산 전환율이 권역별이라 여기서 함께 내보낸다.
        # 이게 없으면 _support_rank 가 권역을 몰라 전체 중앙값으로 계산한다.
        "region_group": (t.get("dong") or {}).get("region_group"),
        "total": housing + fare + time_value,
    }


def build_page6(base_json, base_place=None, work_place=None, dong=None,
                deposit=None, rent=None, work_days=None, carry_qs="",
                age=None):
    """상세 비교 표·차트·교통 카드를 실제 조회값으로 채운다.

    화면 구성은 그대로 두고 값만 바꾼다. 열은 현재 집 + 후보 최대 3곳이며,
    ?dong= 으로 넘어온 후보를 맨 앞에 두고 나머지는 추천으로 채운다.
    """
    data = copy.deepcopy(base_json)
    data["carry_qs"] = carry_qs
    _carry_nav(data, carry_qs)
    if not base_place or not work_place:
        return data

    work_code = _code_of(work_place, None)
    cap = _pass_for_age(age)["cap"]
    base = _col_of(base_place, work_code, deposit, rent, work_days, cap=cap,
                   own_housing=True)
    base_sub = None
    if base is None and work_code:
        # 3페이지와 같은 대체 규칙. 여기서만 포기하면 같은 입력에 대해
        # 3페이지는 값을 보여주고 6페이지는 예시 화면이 되어 앞뒤가 안 맞는다.
        try:
            base_sub = nearest_routed_work(_code_of(base_place, None), work_code)
        except Exception:
            base_sub = None
        if base_sub:
            base = _col_of(base_place, base_sub["code"], deposit, rent, work_days,
                           cap=cap,
                           own_housing=True)
    if not base or not work_code:
        # 조용히 시연 기본값을 보여주면 사용자는 자기 입력 기준 표로 오해한다.
        data["hero"]["description"] = (
            f"{base_place}에서 {work_place}까지의 자료를 불러오지 못해\n"
            "예시 화면을 보여드리고 있어요.")
        return data

    cols = [base]
    seen = {base["name"]}
    if dong:
        c = _col_of(dong, work_code, work_days=work_days, cap=cap)
        if c and c["name"] not in seen:
            cols.append(c)
            seen.add(c["name"])

    try:
        picks = recommend_dongs(work_code, exclude=(_code_of(base_place, None),),
                                limit=4)
    except Exception:
        picks = []
    for a in picks:
        if len(cols) >= 4:
            break
        if a["name"] in seen:
            continue
        cols.append({
            "name": a["name"], "type": a.get("dong_type") or "",
            "housing": a["housing"], "fare": a["fare"],
            "time_value": a["time_value"], "commute_min": a["commute_min"],
            "transfer": a.get("transfer"),
            "total": a["total"],
        })
        seen.add(a["name"])

    if base_sub:
        rel = "같은 " + base_sub["gu"] if base_sub.get("same_gu") else "인근"
        data["hero"]["description"] = (
            f"{base_sub['requested_name']} 경로 자료가 없어 "
            f"{rel}의 {base_sub['name']} 기준으로 계산했어요.\n"
            "실제 값과 다를 수 있어요.")

    man = lambda v: "—" if v is None else f"{v / 10000:.1f}만"

    # ── 표
    tbl = data["table"]
    tbl["columns"] = [
        {"name": c["name"],
         "sub": "현재" if i == 0 else None,
         "type": None if i == 0 else (c["type"] or None),
         "tone": "current" if i == 0 else _TONES[(i - 1) % len(_TONES)]}
        for i, c in enumerate(cols)]

    def row(label, icon, fn, highlight=False):
        return {"label": label, "icon": icon,
                "values": [fn(c) for c in cols], "highlight": highlight}

    tbl["rows"] = [
        row("주거비", "images/p6-row-rent.png", lambda c: man(c["housing"])),
        row("편도 통근", "images/p6-row-commute.png",
            lambda c: "—" if c["commute_min"] is None else f"{c['commute_min']:.1f}분"),
        row("월 교통비", "images/p6-row-fare.png", lambda c: man(c["fare"])),
        row("시간 가치", "images/p6-row-time.png", lambda c: man(c["time_value"])),
        row("환승", "images/p6-row-transfer.png",
            lambda c: "—" if c.get("transfer") is None else f"{int(c['transfer'])}회"),
        row("총부담", "images/p6-row-total.png", lambda c: man(c["total"])),
        row("현재 대비", "images/p6-row-delta.png",
            lambda c: "–" if c is cols[0] else
            f"{'−' if base['total'] - c['total'] >= 0 else '+'}"
            f"{abs(base['total'] - c['total']) / 10000:.1f}만",
            highlight=True),
    ]

    # ── 차트. 축 상한은 최대 총부담을 20만원 단위로 올려 잡는다.
    ch = data["chart"]
    top = max(c["total"] for c in cols) / 10000
    ch["axis_max"] = int(((top // 20) + 1) * 20)
    ch["axis_step"] = 20
    ch["bars"] = [{
        "name": c["name"], "sub": "(현재)" if i == 0 else None,
        "segments": [{"value": round(c[k] / 10000, 1), "color": col}
                     for k, col in zip(("housing", "fare", "time_value"), _SEG_COLORS)],
    } for i, c in enumerate(cols)]

    # ── 교통 비교. 혼잡 노출은 시연 경로에만 있어 여기서는 비운다.
    data["transit"]["cards"] = [{
        "name": c["name"], "sub": "(현재)" if i == 0 else None,
        "type": None if i == 0 else (c["type"] or None),
        "tone": "current" if i == 0 else _TONES[(i - 1) % len(_TONES)],
        "icon": _TRANSIT_ICONS[i % len(_TRANSIT_ICONS)],
        "value": "—" if c["commute_min"] is None else f"{c['commute_min']:.1f}",
        "unit": "분",
        "transfer": "환승 없음" if c.get("transfer") == 0
                    else ("—" if c.get("transfer") is None
                          else f"환승 {int(c['transfer'])}회"),
        "note": man(c["fare"]) + " · 월 교통비",
    } for i, c in enumerate(cols)]

    # ── 요약 문장
    cands = cols[1:]
    if cands:
        best_total = min(cands, key=lambda c: c["total"])
        best_rent = min(cands, key=lambda c: c["housing"])
        fast = min((c for c in cands if c["commute_min"] is not None),
                   key=lambda c: c["commute_min"], default=None)
        parts = [f"총부담 절감을 가장 중요하게 보면 {best_total['name']}",
                 f"주거비 자체를 가장 많이 낮추려면 {best_rent['name']}"]
        if fast:
            parts.append(f"출근시간이 가장 짧은 곳은 {fast['name']}")
        longer = [c for c in cands
                  if c["commute_min"] is not None and base["commute_min"] is not None
                  and c["commute_min"] > base["commute_min"]]
        tail = (f" 다만 {len(longer)}곳은 현재 {base['name']}보다 출근시간이 늘어납니다."
                if longer else "")
        data["ai"]["text"] = ",\n".join(parts) + f"이 눈에 띄어요.{tail}"

    # ── 지원 정책. 조회 실패하면 시안 기본값을 그대로 둔다.
    sup_items, sup_as_of = _support_items(base, age=age, deposit=deposit, rent=rent)
    if sup_items:
        sup = data["support"]
        sup["items"] = sup_items
        # 자격 판정이 아니라 탐색 우선순위라는 것을 한 줄로 밝힌다.
        # 카드에는 이름과 아이콘만 들어가서, 요건 안내는 여기 말고 자리가 없다.
        sup["more"]["label"] = (
            f"연령·소득 요건은 각 기관에서 확인하세요 ({sup_as_of} 기준)"
            if sup_as_of else "연령·소득 요건은 각 기관에서 확인하세요")
        sup["more"]["href"] = "#"

    _refresh_chips(data, area_name=cands[0]["name"] if cands else base["name"],
                   work_name=work_place)
    # 페이지 간 총부담 일치를 검증할 수 있게 계산값을 그대로 남긴다.
    # 3페이지가 쓰는 것과 같은 자리·같은 키다. 화면에는 쓰이지 않는다.
    # 이게 없으면 테스트가 화면 문자열을 파싱해야 하고, 그러면
    # 계산이 멀쩡해도 템플릿만 바꾸면 테스트가 깨진다.
    data["_calc"] = {
        "housing": base["housing"], "fare": base["fare"],
        "time_value": base["time_value"], "total": base["total"],
        "work_days": int(_num_only(work_days, WORK_DAYS_DEFAULT)
                         or WORK_DAYS_DEFAULT),
        "commute_min": base["commute_min"],
        "transit_pass_cap": cap,
        "home": base["name"], "work": work_place,
    }
    return data


# ═════════════════════════════════════════════════════════════
# 3페이지 — 현재 부담 진단
# ═════════════════════════════════════════════════════════════

_LINE_COLOR = [
    ("신분당", "#D4003B"), ("공항철도", "#0090D2"), ("경의중앙", "#77C4A3"),
    ("경춘", "#0C8E72"), ("수인분당", "#FABE00"), ("분당", "#FABE00"),
    ("우이신설", "#B7C450"), ("신림", "#6789CA"), ("김포", "#A17E46"),
    ("의정부", "#FDA600"), ("에버라인", "#56AD27"),
    ("1호선", "#0052A4"), ("2호선", "#00A84D"), ("3호선", "#EF7C1C"),
    ("4호선", "#00A5DE"), ("5호선", "#996CAC"), ("6호선", "#CD7C2F"),
    ("7호선", "#747F00"), ("8호선", "#E6186C"), ("9호선", "#BDB092"),
]
# 버스 도색 기준. 간선 파랑, 지선 초록, 광역 빨강, 순환 노랑, 마을 연두.
_BUS_COLOR = [("간선", "#3D5BAB"), ("지선", "#5BB025"), ("광역", "#E60012"),
              ("순환", "#F99D1C"), ("마을", "#53B332")]
_WALK_COLOR = "#b9c6c2"

# 자료가 영문(WALK/BUS/SUBWAY)일 수도, 한글일 수도 있어 양쪽을 모두 받는다.
# 부분일치로 찾으므로 **긴 키가 먼저** 와야 한다.
# "BUS" 가 앞에 있으면 "EXPRESSBUS" 토큰이 "버스"로 잡혀
# 아래 "고속버스" 값이 영원히 안 나온다. _LINE_COLOR 가
# "수인분당"을 "분당"보다 앞에 둔 것과 같은 이유다.
_MODE_KO = {"EXPRESSBUS": "고속버스", "AIRPLANE": "항공", "FERRY": "여객선",
            "SUBWAY": "지하철", "TRAIN": "기차", "WALK": "도보", "BUS": "버스",
            "고속버스": "고속버스", "지하철": "지하철", "전철": "지하철",
            "기차": "기차", "도보": "도보", "버스": "버스"}


def _line_color(label):
    """노선명에서 색을 고른다. 못 찾으면 서비스 기본색."""
    t = (label or "").replace(" ", "")
    for key, color in _LINE_COLOR:
        if key in t:
            return color
    for key, color in _BUS_COLOR:
        if key in t:
            return color
    return "#7aa9a3"


def _short_line(label):
    """'수도권2호선' -> '2호선', '간선:152' -> '간선 152' 로 줄여 라벨을 짧게."""
    t = (label or "").strip()
    if not t:
        return ""
    t = t.replace("수도권", "")
    if ":" in t:
        kind, no = t.split(":", 1)
        return f"{kind.strip()} {no.strip()}"
    return t


def _mode_strip(mode_sequence, route_lines):
    """교통수단 순서를 노선색이 들어간 경로 띠로 만든다.

    승하차역 이름은 fact_commute_route 에 없다. 역 이름을 지어내면 실제와 다른
    역이 화면에 뜨므로 넣지 않는다. 대신 mode_sequence 의 비도보 구간과
    route_lines 를 순서대로 짝지어, 어느 구간이 어느 노선인지 보여준다.
    두 목록의 개수가 어긋나면 남는 쪽은 수단명만 표시한다.
    """
    raw = (mode_sequence or "").strip()
    if not raw:
        raw = (route_lines or "").strip()
    if not raw:
        return []

    parts = [x.strip() for x in re.split(r"[\u2192><\-|,/]+", raw) if x.strip()]
    if not parts:
        return []
    lines = [x.strip() for x in re.split(r"[|,]+", route_lines or "") if x.strip()]

    strip, li, transit_seen = [], 0, 0
    for i, token in enumerate(parts[:9]):
        up = token.upper()
        ko = next((v for k, v in _MODE_KO.items()
                   if k in up or k in token), None)
        is_walk = ko == "도보"

        if is_walk:
            name, color = "도보", _WALK_COLOR
        else:
            label = lines[li] if li < len(lines) else ""
            li += 1
            transit_seen += 1
            name = _short_line(label) or ko or token
            color = _line_color(label or token)

        strip.append({
            "name": name,
            "sub": "" if is_walk else (ko or ""),
            # 두 번째 이후의 교통수단 구간을 환승 지점으로 본다
            "transfer": (not is_walk) and transit_seen >= 2,
            "color": color,
            "line_color": color if i < len(parts[:9]) - 1 else None,
        })
    return strip


_BURDEN_TYPE_COPY = {
    "A": ("실질 저부담 지역", "월세도 낮고, 통근까지 더해도 부담이 낮은 편이에요."),
    "B": ("월세 착시 지역", "월세는 서울 평균보다 낮지만, 통근시간과 교통비를 더하면 "
                        "오히려 부담이 커지는 곳이에요."),
    "C": ("숨은 효율 지역", "월세는 높은 편이지만 직장이 가까워, 통근까지 더한 총부담은 "
                        "오히려 낮은 곳이에요."),
    "D": ("종합 고부담 지역", "월세와 통근부담이 모두 높은 편이에요."),
}


def _burden_type_key(text):
    """'B 월세 착시' 같은 문자열에서 앞 글자만 뽑는다."""
    t = (text or "").strip()
    return t[0] if t and t[0] in "ABCD" else None


def _conclusion(home_name, work_name, minutes, housing, fare, time_value, burden_type):
    """"그래서 결론이 뭐야"에 답하는 한 문단.

    수치를 다시 늘어놓지 않고, 지금 부담이 어디서 오는지와 다음에 무엇을 보면
    되는지를 말한다. 판단 근거는 세 가지 - 통근시간이 서울 평균보다 긴지,
    주거비 비중이 큰지, 그리고 부담유형이다.
    """
    total = (housing or 0) + (fare or 0) + (time_value or 0)
    if not total:
        return None
    share = (housing or 0) / total
    long_commute = minutes is not None and minutes > SEOUL_AVG_COMMUTE_MIN
    key = _burden_type_key(burden_type)
    commute_cost = (fare or 0) + (time_value or 0)

    # 서울 행정동 중앙값 구성비가 주거비 약 70% / 통근부담 약 30% 라서,
    # 주거비 비중만 보면 거의 모든 경우가 "월세가 대부분"으로 쏠린다.
    # 통근부담 비중을 기준으로 갈라야 실제로 구분이 된다.
    commute_share = commute_cost / total
    if long_commute and commute_share >= 0.28:
        tag, tone = "통근이 부담을 키우고 있어요", "warn"
        text = (f"{home_name}에서 {work_name}까지 편도 {minutes:.0f}분은 서울 평균"
                f"({SEOUL_AVG_COMMUTE_MIN:.0f}분)보다 깁니다. 부담의 "
                f"{commute_cost / total * 100:.0f}%가 교통비와 통근시간에서 나와요. "
                "월세를 조금 올리더라도 직장에 가까운 동네가 총부담은 더 낮을 수 있어요.")
        cta = "직장 가까운 동네 추천받기"
    elif long_commute:
        tag, tone = "월세도 통근도 둘 다 부담이에요", "warn"
        text = (f"주거비가 전체의 {share * 100:.0f}%인데, 편도 {minutes:.0f}분으로 통근까지 "
                "깁니다. 둘 중 하나라도 줄일 수 있는 동네를 찾는 편이 좋아요.")
        cta = "부담이 낮은 동네 추천받기"
    elif share >= 0.75:
        tag, tone = "부담의 대부분이 월세예요", "info"
        text = (f"편도 {minutes:.0f}분으로 통근은 짧은 편이지만, 부담의 "
                f"{share * 100:.0f}%가 주거비입니다. 통근이 조금 늘더라도 월세가 낮은 "
                "동네라면 총부담이 줄어들 수 있어요.")
        cta = "월세가 낮은 동네 추천받기"
    else:
        tag, tone = "지금은 균형이 잡혀 있어요", "good"
        text = (f"편도 {minutes:.0f}분으로 통근이 짧고, 주거비 비중도 "
                f"{share * 100:.0f}%로 한쪽에 치우쳐 있지 않아요. "
                "다른 동네와 비교해도 크게 유리해지기는 어려울 수 있어요.")
        cta = "다른 동네 추천받기"

    if key == "B":
        text += f" 참고로 {home_name}은 월세 착시가 나타나는 지역으로 분류돼요."
    elif key == "C":
        text += f" 참고로 {home_name}은 월세는 높아도 총부담은 낮은 숨은 효율 지역이에요."
    return {"tag": tag, "text": text, "tone": tone, "cta": cta}


def _diagnosis_cards(home_name, target, minutes, time_value, fare, housing,
                     work_days=WORK_DAYS_DEFAULT):
    """혼잡도 자료가 없을 때 그 자리에 보여줄 지역 진단.

    가로 4열에 나란히 놓이므로 제목은 한 줄, 설명은 두 줄을 넘기지 않게 쓴다.
    항목마다 색을 달리해서 네 장이 한 덩어리로 보이지 않게 한다.
    """
    t = target or {}
    b = t.get("burden") or {}
    cards = []

    # burden_type / dong_type 은 burden 안이 아니라 응답 최상위에 있다.
    # 예전 코드는 burden 에서 찾아 두 카드가 통째로 빠졌었다.
    key = _burden_type_key(t.get("burden_type") or b.get("burden_type"))
    if key:
        title, desc = _BURDEN_TYPE_COPY[key]
        cards.append({"tag": "부담 유형", "title": title, "text": desc,
                      "tone": "red" if key in ("B", "D") else "teal"})

    dtype = (t.get("dong_type") or b.get("dong_type") or "").strip()
    if dtype:
        cards.append({"tag": "지역 유형", "title": dtype,
                      "text": "주거비·통근시간·교통구조로 나눈 6가지 유형 중 하나예요.",
                      "tone": "teal"})

    if minutes is not None and time_value:
        # 시간과 금액이 같은 출근일수를 써야 한다. 여기만 기본값 21을 쓰면
        # 20일을 입력한 사람에게 "월 17시간 = 16.4만원"처럼 서로 안 맞는 값이 나온다.
        hours = round(minutes * 2 * (work_days or WORK_DAYS_DEFAULT) / 60)
        cards.append({"tag": "통근시간 가치", "title": f"월 {hours}시간",
                      "text": f"길에 쓰는 시간을 최저임금으로 환산하면 "
                              f"{time_value / 10000:.1f}만원이에요.",
                      "tone": "amber"})

    if housing and fare is not None:
        denom = housing + fare + (time_value or 0)
        if denom:
            cards.append({"tag": "부담 구성", "title": f"주거비 {housing / denom * 100:.0f}%",
                          "text": "나머지는 교통비와 통근시간 가치예요.",
                          "tone": "blue"})
    return cards


def _short_lines(route_lines):
    """'지선:0411 | 수도권9호선' -> '지선 0411 · 9호선'. 한 줄에 들어가게 줄인다."""
    parts = [_short_line(x) for x in re.split(r"[|,]+", route_lines or "") if x.strip()]
    return " · ".join([p for p in parts if p])



def build_page3(base_json, residence=None, workplace=None,
                deposit=None, rent=None, work_days=None, depart_time=None,
                age=None):
    """2페이지 입력을 받아 3페이지를 실제 값으로 채운다."""
    data = copy.deepcopy(base_json)
    if not residence or not workplace:
        return data

    v = data["summary"]
    route = data["route"]

    home = resolve_place(residence)
    work = resolve_place(workplace)

    # 실패해도 입력은 다음 페이지로 넘어가야 한다. 여기서 파라미터를 잃으면
    # 4·5페이지가 시연 기본값(잠원동·삼정KPMG)으로 되돌아간다.
    carry_qs = urlencode({
        "residence": residence or "", "workplace": workplace or "",
        "deposit": deposit or "", "rent": rent or "",
        "work_days": work_days or "", "depart_time": depart_time or "",
        "age": age or "",
    })
    data["cta_banner"]["button_href"] = "/explore?" + carry_qs

    def fail(msg1, msg2, detail=""):
        v["lines"] = [{"text": msg1, "accent": False}]
        v["lines2"] = [{"text": msg2, "accent": False}] + (
            [{"text": detail, "accent": False}] if detail else [])
        v["donut"]["center_value"] = "—"
        v["donut"]["segments"] = []
        route["origin"] = residence
        route["destination"] = workplace
        route["facts"] = []
        route["stations"] = []
        data["congestion"]["segments"] = []
        data["congestion"]["note"] = ""
        for k in ("value", "exposure_value"):
            data["congestion"]["peak"][k] = "—"
        return data

    for who, res, raw in (("거주지", home, residence), ("근무지", work, workplace)):
        if res.get("status") != "ok":
            return fail(f"'{raw}' 을(를) 찾지 못했어요.",
                        "서울 지역만 분석할 수 있어요.",
                        "지하철역명, 도로명주소, 지번주소로 다시 입력해보세요.")

    # DB 조회 — 근무지 기준 경로
    target = get_dong(home["dong_code"], work_code=work["dong_code"])

    # 경로는 거주동별 누적 80% 목적지에 대해서만 수집했다. 흐름이 적은 조합은
    # 빠져 있는데, 그렇다고 "자료 없음"으로 끝내면 다섯 중 한 명은 아무것도
    # 못 본다. 인근 근무동으로 대체 계산하고 무엇으로 대체했는지 밝힌다.
    substitute = None
    if target.get("status") in ("no_route", "not_found", None):
        try:
            substitute = nearest_routed_work(home["dong_code"], work["dong_code"])
        except Exception:
            substitute = None
        if substitute:
            target = get_dong(home["dong_code"], work_code=substitute["code"])
            if target.get("status") in ("no_route", "not_found", None):
                substitute, target = None, target

    if target.get("status") in ("no_route", "not_found", None):
        try:
            opts = list_work_options(home["dong_code"], limit=5)
        except Exception:
            opts = []
        hint = ", ".join(o["name"] for o in opts)
        return fail(
            f"{home['dong_name']}에서 {work['dong_name']}까지 가는",
            "출퇴근 경로 자료가 아직 없어요.",
            f"이 지역에서 조회 가능한 근무지: {hint}" if hint
            else "주요 업무지구(역삼1동, 여의동, 소공동 등)로 시도해보세요.")

    b = target.get("burden") or {}
    days = int(_num_only(work_days, 21) or 21)
    dep_monthly, dep_rate, dep = _deposit_monthly(deposit, target)
    mrent = (_num_only(rent, 0) or 0) * 10_000

    housing = mrent + dep_monthly
    minutes = b.get("commute_min")
    hours = round(minutes * 2 * days / 60, 2) if minutes is not None else None
    time_value = round(hours * TIME_VALUE_PER_HOUR) if hours is not None else None
    one_fare = b.get("oneway_fare")
    fare_actual = one_fare * 2 * days if one_fare is not None else None
    # 만 나이로 정기권 기준이 갈린다(청년 55,000 / 일반 62,000)
    pass_info = _pass_for_age(age)
    fare = min(fare_actual, pass_info["cap"]) if fare_actual is not None else None
    total = housing + (fare or 0) + (time_value or 0)

    # 요약 문구 — 구성비와 통근시간을 함께 보고 정한다.
    # 구성비만 보고 "통근시간은 짧은 편"이라고 쓰면, 편도 43분인 경우에도
    # 주거비 비중이 높다는 이유로 짧다고 단정하게 된다. 화면의 43.2분 옆에
    # "짧은 편"이 붙는 사고를 막기 위해 통근시간을 실제로 비교한다.
    share_h = housing / total if total else 0
    long_commute = minutes is not None and minutes > SEOUL_AVG_COMMUTE_MIN

    if share_h >= 0.6 and not long_commute:
        v["lines"] = [{"text": "현재 집은 직장까지의 통근시간은", "accent": False},
                      {"text": "짧은 편이지만,", "accent": False},
                      {"text": "월환산 주거비가 전체 부담의", "accent": True},
                      {"text": "큰 비중을 차지하고 있어요.", "accent": True}]
    elif share_h >= 0.6:
        v["lines"] = [{"text": "통근시간이 서울 평균보다 긴 편인데,", "accent": False},
                      {"text": "그럼에도", "accent": False},
                      {"text": "월환산 주거비가 전체 부담의", "accent": True},
                      {"text": "큰 비중을 차지하고 있어요.", "accent": True}]
    else:
        v["lines"] = [{"text": "주거비보다", "accent": False},
                      {"text": "통근 부담이", "accent": False},
                      {"text": "전체 부담에서 더 큰 비중을", "accent": True},
                      {"text": "차지하고 있어요.", "accent": True}]
    note = status_note(target)
    v["lines2"] = ([{"text": note, "accent": False}] if note else
                   [{"text": "행정동 대표 지점 기준으로 계산했어요.", "accent": False},
                    {"text": "실제 집·직장 위치에 따라 달라질 수 있어요.", "accent": False}])

    # 도넛 — 값 기반(만원). page3 스크립트가 각도·라벨을 계산한다
    seg = v["donut"].get("segments") or []
    colors = [s.get("color") for s in seg] or ["#f7c1a4", "#7b9ede", "#4bb3ad"]
    pos = [(s.get("label_top"), s.get("label_left"), s.get("label_color")) for s in seg] or \
          [("14%", "63%", "#4b5a55"), ("33%", "78%", "#ffffff"), ("58%", "2%", "#ffffff")]
    vals = [round((time_value or 0) / 10_000, 1),
            round((fare or 0) / 10_000, 1),
            round(housing / 10_000, 1)]
    v["donut"]["segments"] = [
        {"value": vals[i], "color": colors[i % len(colors)],
         "label_top": pos[i % len(pos)][0], "label_left": pos[i % len(pos)][1],
         "label_color": pos[i % len(pos)][2]} for i in range(3)]
    v["donut"]["center_value"] = f"{round(total / 10_000, 1)}"

    # 경로 카드
    route["origin"] = home["dong_name"]
    route["destination"] = work["dong_name"]
    facts = [
        {"icon": "time", "label": "편도", "value": f"{minutes}분"},
        {"icon": "distance", "label": "거리", "value": f"{b.get('oneway_km', '—')}km"
            if b.get("oneway_km") is not None else "—"},
        {"icon": "transfer", "label": "환승",
         "value": f"{int(b['transfer'])}회" if b.get("transfer") is not None else "—"},
        {"icon": "fare", "label": "월 예상 교통비", "value": f"약 {round((fare or 0)/10_000, 1)} 만 원"},
        {"icon": "line", "label": "이용노선",
         "value": _short_lines(b.get("route_lines")) or "—"},
    ]
    route["facts"] = [f for f in facts if f["value"] != "—"]

    # 값이 왜 그렇게 나왔는지 밝힌다. "월세 75만원을 넣었는데 왜 주거비가
    # 77.9만원이지"처럼, 설명이 없으면 계산이 틀린 것처럼 보인다.
    notes = []
    if housing:
        notes.append(f"주거비 {housing / 10000:.1f}만원 = 월세 {mrent / 10000:.0f}만원 "
                     f"+ 보증금 {dep / 10000:.0f}만원을 월로 환산한 "
                     f"{(housing - mrent) / 10000:.1f}만원 "
                     f"(전월세전환율 {dep_rate * 100:.2f}% 적용)")
    if fare is not None and fare_actual is not None and fare_actual > fare:
        notes.append(f"교통비 {fare / 10000:.1f}만원 = 실제 이용액은 월 "
                     f"{fare_actual / 10000:.1f}만원이지만, {pass_info['name']}"
                     f"({pass_info['cap']:,}원)을 쓰면 여기까지만 내요")
    elif fare is not None:
        notes.append(f"교통비 {fare / 10000:.1f}만원 = 편도 요금 x 왕복 x 월 {days}일")
    notes.append(pass_info["note"])
    if time_value:
        notes.append(f"통근시간 가치 {time_value / 10000:.1f}만원 = 실제로 내는 돈이 아니라, "
                     "길에 쓰는 시간을 최저임금으로 환산한 값이에요")
    route["value_notes"] = notes

    # 역 목록·혼잡도는 시연 경로에만 있다.
    # 시연 경로면 원본 JSON 값을 그대로 두고, 아니면 비운 뒤 사유를 남긴다.
    # 비어 있는 채로 두면 화면에 빈 상자가 남아 구현이 덜 된 것처럼 보인다.
    is_demo = (home.get("dong_code") == BASE_DONG_CODE
               and work.get("dong_code") == WORK_DONG_CODE)

    if not is_demo:
        route["stations"] = _mode_strip(b.get("mode_sequence"), b.get("route_lines"))
        route["stations_note"] = "역별 상세는 보유하지 않아 이용 수단 순서로 표시했어요."

        c = data["congestion"]
        c["segments"] = []
        c["peak"]["value"] = "—"
        c["peak"]["exposure_value"] = "—"
        c["peak"]["badge"] = "자료 없음"

        # 혼잡도는 시연 경로에만 있어 대부분 비어 있다. 빈 상자를 두느니
        # 이미 가지고 있는 부담유형·지역유형·시간가치를 사용자 언어로 풀어준다.
        home_name = home.get("dong_name") or residence
        c["diagnosis"] = _diagnosis_cards(home_name, target, minutes,
                                          time_value, fare, housing, days)
        if fare_actual is not None:
            saved = max(fare_actual - (fare or 0), 0)
            c["diagnosis"].insert(0, {
                "tag": "교통 지원",
                "title": (f"모두의카드로 월 {saved / 10000:.1f}만원 절감"
                          if saved else pass_info["name"]),
                "text": pass_info["note"],
                "tone": "teal" if pass_info["is_youth"] else "red",
            })
            c["diagnosis"] = c["diagnosis"][:4]
        if c["diagnosis"]:
            c["title"] = f"{home_name}은 어떤 동네일까요?"
            c["note"] = "이 경로는 구간별 혼잡도 자료가 없어 지역 특성을 알려드려요"
            c["empty_text"] = ""
        else:
            c["note"] = "혼잡도는 일부 경로에서만 확인할 수 있어요"
            c["empty_text"] = "이 경로는 구간별 혼잡도 자료가 없어요."

    # 대체 계산했다면 반드시 화면에 밝힌다. 밝히지 않으면 사용자는 자기가 입력한
    # 근무지 기준 값으로 믿게 된다.
    if substitute:
        rel = "같은 " + substitute["gu"] if substitute.get("same_gu") else "인근"
        v["lines2"] = [
            {"text": f"{substitute['requested_name']}은 출퇴근 경로 자료가 없어", "accent": False},
            {"text": f"{rel}의 {substitute['name']} 기준으로 계산했어요.", "accent": False},
            {"text": "실제 값과 다를 수 있어요.", "accent": False},
        ]
        route["destination"] = f"{substitute['name']} (대체)"

    v["verdict"] = _conclusion(
        home.get("dong_name") or residence, work.get("dong_name") or workplace,
        minutes, housing, fare, time_value,
        target.get("burden_type") or (target.get("burden") or {}).get("burden_type"))

    # 정규화된 출근일수로 CTA 를 다시 쓴다(위에서 원본 입력으로 한 번 세팅했다)
    data["cta_banner"]["button_href"] = "/explore?" + carry_qs
    _carry_nav(data, carry_qs)

    data["_calc"] = {
        "housing": housing, "fare": fare, "fare_actual": fare_actual,
        "time_value": time_value, "total": total,
        "work_days": days, "commute_min": minutes,
        "home": home["dong_name"], "work": work["dong_name"],
        "status": target.get("status"),
        "share_housing": round(share_h, 4),
        "long_commute": long_commute,
        "transit_pass_cap": pass_info["cap"],
        "is_youth": pass_info["is_youth"],
        "is_demo_route": is_demo,
        "substitute_work": substitute["name"] if substitute else None,
    }
    return data