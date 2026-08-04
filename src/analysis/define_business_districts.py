"""
주요 업무지구 정의.

분석 3(근무지에 따라 최적 주거지가 어떻게 달라지는가)은 근무지를 고정하고 거주동을
비교하는 구조라, 개별 행정동을 다 돌리는 대신 대표 업무지구를 먼저 정해야 한다.

업무중심성 판정은 세 축을 같이 본다. 하나만 보면 오판이 생긴다.
  규모  - 출근 유입량. 큰 곳을 놓치지 않기 위한 축
  방향  - 유입/유출 비율. 유입이 유출보다 많아야 순수 근무지다
  시간  - 주야간 인구비. 낮에 사람이 늘어나는 곳인지 확인
사업체·종사자 수를 함께 쓰는 것이 정석이나 현재 미확보라, 확보되면 판정 결과를
검증하는 용도로 붙인다.

출근 유입·유출량은 **전체 OD 기준**을 쓴다. 누적 80%로 줄인 OD로 계산하면 잘려나간
소수 흐름만큼 유입량이 과소 집계된다. 12번 노트북이 전체 OD로 산출한 값이
`commute_burden_with_network_metrics.csv`에 들어 있으므로 그것을 우선 사용하고,
없을 때만 보유한 OD 파일에서 직접 계산한다(이 경우 80% 컷 한계를 로그로 알린다).

직접 계산할 때는 내부통근(거주동=근무동)을 뺀다. 같은 동 안에서 출퇴근하는 사람은
유입도 유출도 아니어서 넣으면 양쪽이 동시에 부풀려진다.

업무지구 소속 행정동은 판정 결과를 지리·기능 단위로 묶어 확정하며, 지구 안에서는
유입량 비중을 가중치로 둬서 대표 통근시간·교통비를 가중평균할 때 쓴다.

입력: data/all_age_commute_od_selected_80.csv
      data/행정동_기준코드표.csv
      data/2023~2025_행정동별_청년생활인구_지표.csv
출력: data/업무중심성_행정동별.csv, data/업무지구_정의.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

NETWORK_PATH = DATA_DIR / "commute_burden_with_network_metrics.csv"
_OD_CANDIDATES = ["all_age_commute_od_aggregated.csv", "all_age_commute_od_selected_80.csv"]
OD_PATH = next((DATA_DIR / f for f in _OD_CANDIDATES if (DATA_DIR / f).exists()),
               DATA_DIR / _OD_CANDIDATES[0])
CROSSWALK_PATH = DATA_DIR / "행정동_기준코드표.csv"
POP_PATH = DATA_DIR / "2023~2025_행정동별_청년생활인구_지표.csv"

OUT_SCORE = DATA_DIR / "업무중심성_행정동별.csv"
OUT_DISTRICT = DATA_DIR / "업무지구_정의.csv"

INFLOW_Q = 0.85  # 출근 유입량 상위 15%

# 업무지구 구성. 판정된 행정동을 지리·기능 단위로 묶었다.
DISTRICTS = {
    "강남": ["역삼1동", "역삼2동", "삼성1동", "삼성2동", "논현1동", "논현2동",
             "대치2동", "대치4동", "도곡1동", "서초1동", "서초2동", "서초3동", "서초4동"],
    "도심": ["종로1.2.3.4가동", "종로5.6가동", "사직동", "이화동",
             "명동", "소공동", "회현동", "을지로동", "광희동", "필동"],
    "여의도·영등포": ["여의동", "영등포동", "문래동", "당산제1동"],
    "구로·가산": ["가산동", "구로제2동", "구로제3동"],
    "마곡·강서": ["가양제1동", "발산제1동"],
    "성수": ["성수1가제2동", "성수2가제3동"],
    "상암": ["상암동"],
    "송파·문정": ["문정2동", "잠실6동", "가락본동"],
    "용산": ["한강로동", "남영동"],
}

# 판정은 됐으나 지구에서 제외한 동과 사유. 판단 근거를 남겨둔다.
EXCLUDED = {
    "압구정동": "상업·의료 중심, 업무지구 성격 아님",
    "청담동": "상업·유흥 중심",
    "신사동": "가로수길 상업 중심",
    "한남동": "주거·대사관 지역",
    "서교동": "홍대 상업·유흥 상권",
    "신촌동": "대학가 상권",
    "충현동": "대학가·상업 혼합",
    "양재1동": "R&D·유통 특화, 강남과 통근권이 분리됨",
    "양재2동": "R&D·유통 특화",
    "반포4동": "고속터미널 상업 중심",
    "공항동": "공항 종사 특수 입지",
    "풍납2동": "병원 중심 고용",
    "구의제3동": "행정·상업 혼합, 규모 작음",
    "목1동": "상업 중심",
    "양평제2동": "준공업지역 제조·물류 중심, 여의도·영등포 통근권과 분리",
}


def build_workplace_score() -> pd.DataFrame:
    if not CROSSWALK_PATH.exists():
        sys.exit(f"{CROSSWALK_PATH} 이 없습니다. build_region_master.py를 먼저 실행하세요.")

    if NETWORK_PATH.exists():
        net = pd.read_csv(NETWORK_PATH, encoding="utf-8-sig")
        net["code8"] = net["거주동 코드"].astype(str).str.zfill(8)
        flow = net.set_index("code8")[["출근_유입량", "출근_유출량", "출근_유입유출비"]].copy()
        flow = flow.rename(columns={"출근_유입유출비": "유입유출비"})
        flow["내부통근량"] = net.set_index("code8")["내부통근_출근량"]
        flow["출근_순유입"] = flow["출근_유입량"] - flow["출근_유출량"]
        print(f"유입·유출 출처: {NETWORK_PATH.name} (전체 OD 기준)")
    else:
        if not OD_PATH.exists():
            sys.exit(f"{NETWORK_PATH.name} 도 {OD_PATH.name} 도 없습니다.")
        if "selected_80" in OD_PATH.name:
            print(f"[경고] {OD_PATH.name}은 누적 80% 컷 파일이라 유입량이 과소 집계된다.")
            print("  전체 OD 또는 12번 네트워크 결합본을 쓰는 것이 정확하다.")
        od = pd.read_csv(OD_PATH, encoding="utf-8-sig")
        od["거주code8"] = od["거주동 코드"].astype(str).str.zfill(8)
        od["근무code8"] = od["근무동 코드"].astype(str).str.zfill(8)

        ext = od[od["거주code8"] != od["근무code8"]]
        inflow = ext.groupby("근무code8")["출근_이동량"].sum().rename("출근_유입량")
        outflow = ext.groupby("거주code8")["출근_이동량"].sum().rename("출근_유출량")
        inner = (od[od["거주code8"] == od["근무code8"]]
                 .set_index("거주code8")["출근_이동량"].rename("내부통근량"))

        flow = pd.concat([inflow, outflow, inner], axis=1).fillna(0)
        flow["유입유출비"] = flow["출근_유입량"] / flow["출근_유출량"].replace(0, np.nan)
        flow["출근_순유입"] = flow["출근_유입량"] - flow["출근_유출량"]
        print(f"유입·유출 출처: {OD_PATH.name} (직접 계산)")

    cw = pd.read_csv(CROSSWALK_PATH, encoding="utf-8-sig", dtype=str)
    need = ["행정동코드8", "행정동코드10", "시군구명", "행정동명", "권역"]
    miss = [c for c in need if c not in cw.columns]
    if miss:
        sys.exit(f"기준코드표에 컬럼이 없습니다: {miss}. build_region_master.py를 다시 실행하세요.")
    df = cw[need].merge(
        flow, left_on="행정동코드8", right_index=True, how="left")

    if POP_PATH.exists():
        pop = pd.read_csv(POP_PATH, encoding="utf-8-sig")
        pop["행정동코드8"] = pop["행정동코드"].astype(str).str.zfill(8)
        keep = ["행정동코드8", "주야간_인구비", "주간_순유입_규모", "평일_집중도", "출근_유입_변화율"]
        df = df.merge(pop[[c for c in keep if c in pop.columns]], on="행정동코드8", how="left")
    else:
        print("[경고] 생활인구 지표가 없어 시간대 축 없이 판정합니다")
        df["주야간_인구비"] = np.nan

    for col, rank_col in [("출근_유입량", "r_규모"), ("유입유출비", "r_방향"),
                          ("주야간_인구비", "r_주야간"), ("평일_집중도", "r_평일")]:
        df[rank_col] = df[col].rank(pct=True) if col in df else np.nan
    df["업무중심성점수"] = df[["r_규모", "r_방향", "r_주야간", "r_평일"]].mean(axis=1)

    cutoff = df["출근_유입량"].quantile(INFLOW_Q)
    df["업무중심"] = (df["출근_유입량"] >= cutoff) & (df["유입유출비"] > 1) & (df["주야간_인구비"] > 1)
    share = df.loc[df["업무중심"], "출근_유입량"].sum() / df["출근_유입량"].sum()
    print(f"업무중심 판정 {df['업무중심'].sum()}개 "
          f"(유입량 컷 {cutoff:,.0f}, 서울 출근유입의 {share*100:.1f}% 흡수)")
    return df


def build_districts(df: pd.DataFrame) -> pd.DataFrame:
    name_to_district = {d: k for k, dongs in DISTRICTS.items() for d in dongs}
    df["업무지구"] = df["행정동명"].map(name_to_district)

    listed = {d for dongs in DISTRICTS.values() for d in dongs}
    missing = listed - set(df["행정동명"])
    if missing:
        print(f"[경고] 정의에는 있으나 데이터에 없는 행정동: {sorted(missing)}")

    not_selected = df[df["업무지구"].notna() & ~df["업무중심"]]
    if len(not_selected):
        print(f"[확인] 업무지구에 넣었으나 판정 기준 미달인 동 {len(not_selected)}개: "
              f"{', '.join(not_selected['행정동명'])}")

    d = df[df["업무지구"].notna()].copy()
    d["지구내_가중치"] = d.groupby("업무지구")["출근_유입량"].transform(lambda s: s / s.sum())

    total = df["출근_유입량"].sum()
    summary = (d.groupby("업무지구")
               .agg(행정동수=("행정동명", "count"),
                    출근_유입량=("출근_유입량", "sum"),
                    평균_주야간인구비=("주야간_인구비", "mean"))
               .assign(서울출근유입_비중=lambda x: x["출근_유입량"] / total * 100)
               .sort_values("출근_유입량", ascending=False))
    print("\n[업무지구 요약]")
    print(summary.round(2).to_string())
    print(f"\n{len(summary)}개 지구 합계가 서울 출근 유입의 {summary['서울출근유입_비중'].sum():.1f}%")

    excluded_found = df[df["업무중심"] & df["업무지구"].isna()]
    print(f"\n[지구 미소속] 판정은 됐으나 제외한 {len(excluded_found)}개")
    for _, r in excluded_found.iterrows():
        print(f"  {r['시군구명']} {r['행정동명']}: {EXCLUDED.get(r['행정동명'], '사유 미기재')}")
    return d


def main():
    df = build_workplace_score()
    d = build_districts(df)

    score_cols = ["행정동코드10", "행정동코드8", "시군구명", "행정동명", "권역",
                  "출근_유입량", "출근_유출량", "내부통근량", "유입유출비", "출근_순유입",
                  "주야간_인구비", "평일_집중도", "업무중심성점수", "업무중심", "업무지구"]
    df[score_cols].round(4).to_csv(OUT_SCORE, index=False, encoding="utf-8-sig")

    dist_cols = ["업무지구", "행정동코드10", "행정동코드8", "시군구명", "행정동명",
                 "출근_유입량", "지구내_가중치", "주야간_인구비", "업무중심"]
    (d[dist_cols].sort_values(["업무지구", "지구내_가중치"], ascending=[True, False])
     .round(4).to_csv(OUT_DISTRICT, index=False, encoding="utf-8-sig"))

    print(f"\n저장 완료: {OUT_SCORE}")
    print(f"저장 완료: {OUT_DISTRICT}")


if __name__ == "__main__":
    main()