"""
혼잡도 표시값 재계산.

17번 노트북이 만든 혼잡도 산출물을 읽어 서비스 표시용으로 다시 계산한다.
노트북 자체는 건드리지 않고, 저장된 CSV의 `혼잡도추출후보_JSON` 컬럼(어떤 값을
어디서 주웠는지 기록)을 원천으로 재계산한다. API 재호출은 없다.

노트북 파서와 달라지는 점 두 가지.

1) 0 을 결측으로 뺀다.
   TMAP 문서상 0 은 한산함이 아니라 해당 운행조합이 없다는 뜻일 수 있다. 노트북은
   0 을 유효값으로 평균에 넣는데, 0 이 하나만 섞여도 대표값이 크게 내려가 등급이
   "혼잡"에서 "보통"으로 뒤집히고 그 구간이 혼잡 노출시간에서 통째로 빠진다.
   없는 데이터를 "안 혼잡하다"로 읽는 셈이라 노출시간을 과소 추정한다.

2) 커버리지가 부족하면 값을 만들지 않는다.
   혼잡도는 시연 경로 일부에만 확보돼 있다. 구간 커버리지가 기준 미만이면 숫자를
   내지 않고 사유를 남긴다. 서비스는 이 경우 혼잡도 항목 자체를 숨긴다. 빈 값을
   0 이나 "여유"로 채우면 데이터가 없는 것과 한산한 것이 구분되지 않는다.

방향·급행 구분은 아직 반영하지 않았다. 같은 역이라도 방향·급행·시작역·종착역별로
값이 다른데 노트북 파서가 이를 구분하지 않고 전부 평균한다. --diagnose 로 후보값의
JSON 경로 분포를 출력해 어떤 필드로 갈라야 하는지 먼저 확인할 것.

입력: <PROCESSED>/loca_demo_crowding_station_results_v17.csv
      <PROCESSED>/loca_demo_crowding_route_detail.csv
출력: <PROCESSED>/crowding_station_display.csv
      <PROCESSED>/crowding_route_display.csv

사용:
    python src/analysis/build_crowding_display.py --diagnose   # 경로 분포만 확인
    python src/analysis/build_crowding_display.py              # 재계산
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 17번 노트북은 project_data/processed 를 쓰고 우리 레포는 data/ 를 쓴다.
# 둘 다 뒤져서 먼저 발견되는 쪽을 원천으로 삼는다.
_CANDIDATE_DIRS = [PROJECT_ROOT / "data",
                   PROJECT_ROOT / "project_data" / "processed"]

STATION_FILE = "loca_demo_crowding_station_results_v17.csv"
ROUTE_FILE = "loca_demo_crowding_route_detail.csv"
OUT_STATION = "crowding_station_display.csv"
OUT_ROUTE = "crowding_route_display.csv"

WORK_DAYS_PER_MONTH = 21      # 프로젝트 공통 기준
CONGESTION_CUT = 70           # 혼잡 노출시간 산정 하한(%)
MIN_COVERAGE = 0.80           # 이 미만이면 경로 혼잡도를 표시하지 않음

# 국토부 지하철 혼잡도 기준(34/100/150)에 70 을 보조 컷으로 추가한 것.
# 서울 출근시간대 관측에서 100% 초과가 드물어 100 이하가 사실상 한 덩어리가 되기
# 때문이며, 원래 기준을 버린 것이 아니라 그 안을 한 번 더 나눈 것이다.
LEVELS = [(34, "여유"), (70, "보통"), (100, "혼잡")]


def resolve_dir() -> Path:
    for d in _CANDIDATE_DIRS:
        if (d / STATION_FILE).exists():
            return d
    sys.exit(f"[중단] {STATION_FILE} 을 찾을 수 없습니다. 확인한 위치: "
             + ", ".join(str(d) for d in _CANDIDATE_DIRS))


def congestion_level(pct) -> object:
    if pd.isna(pct):
        return pd.NA
    pct = float(pct)
    for bound, name in LEVELS:
        if pct < bound:
            return name
    return "고혼잡"


def parse_candidates(raw) -> list:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [x for x in items if isinstance(x, dict) and "value" in x]


def diagnose(station: pd.DataFrame) -> None:
    """후보값이 어떤 JSON 경로에서 왔는지 세어본다. 방향 필드를 찾기 위한 단계."""
    paths, zero_paths = Counter(), Counter()
    n_zero = n_total = 0
    for raw in station["혼잡도추출후보_JSON"]:
        for c in parse_candidates(raw):
            p = str(c.get("path", "?"))
            paths[p] += 1
            n_total += 1
            if float(c["value"]) == 0:
                zero_paths[p] += 1
                n_zero += 1

    print(f"후보값 총 {n_total:,}개 / 0 값 {n_zero:,}개 ({n_zero/max(n_total,1)*100:.1f}%)")
    print("\n[값이 나온 JSON 경로 상위 30]")
    print(f"{'건수':>6} {'0건':>5}  경로")
    for p, n in paths.most_common(30):
        print(f"{n:>6} {zero_paths.get(p, 0):>5}  {p}")
    print("\n경로에 방향·급행·시작역 같은 구분이 보이면 그 필드로 필터를 걸어야 합니다.")


def rebuild_station(station: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in station.iterrows():
        cands = parse_candidates(r.get("혼잡도추출후보_JSON"))
        vals = [float(c["value"]) for c in cands]
        # 0 은 운행조합 없음일 수 있어 평균에서 뺀다
        nz = [v for v in vals if v > 0]
        rows.append({
            "노선명_API": r["노선명_API"], "역명_API": r["역명_API"],
            "요일": r["요일"], "시간": str(r["시간"]).zfill(2),
            "혼잡도_pct": float(np.mean(nz)) if nz else np.nan,
            "혼잡도_pct_구버전": r.get("혼잡도_pct"),
            "후보수": len(vals), "영값수": len(vals) - len(nz),
            "혼잡도_유효": bool(nz),
        })
    out = pd.DataFrame(rows)
    out["혼잡등급"] = out["혼잡도_pct"].apply(congestion_level)

    d = (out["혼잡도_pct"] - pd.to_numeric(out["혼잡도_pct_구버전"], errors="coerce")).abs()
    changed = (d > 0.05).sum()
    print(f"역 단위 {len(out)}건 중 대표값이 바뀐 역: {changed}건 "
          f"(최대 {d.max():.1f}%p)" if len(out) else "역 단위 데이터 없음")
    print(f"  0 값이 섞여 있던 역: {(out['영값수'] > 0).sum()}건 / "
          f"유효값이 아예 없는 역: {(~out['혼잡도_유효']).sum()}건")
    return out


def rebuild_route(route: pd.DataFrame, station: pd.DataFrame) -> pd.DataFrame:
    key = ["노선명_API", "역명_API", "요일", "시간"]
    for df in (route, station):
        df["시간"] = df["시간"].astype(str).str.zfill(2)

    drop = [c for c in ["혼잡도_pct", "혼잡등급", "혼잡노출시간_분"] if c in route.columns]
    m = route.drop(columns=drop).merge(
        station[key + ["혼잡도_pct", "혼잡등급"]], on=key, how="left")

    # 하차역은 이후 이동구간이 없으므로 노출시간 0
    is_leg = m["다음역_API"].notna()
    m["혼잡노출시간_분"] = np.where(
        is_leg & (m["혼잡도_pct"] >= CONGESTION_CUT), m["구간시간_분_추정"], 0.0)

    rows = []
    for (label, dong, hour), g in m.groupby(["비교대상", "행정동명", "시간"], dropna=False):
        travel = g[g["다음역_API"].notna()]
        avail = travel[travel["혼잡도_pct"].notna()]
        cov = len(avail) / len(travel) if len(travel) else np.nan
        # 커버리지가 낮으면 숫자를 만들지 않는다. 서비스는 이때 항목을 숨긴다.
        ok = bool(len(travel)) and cov >= MIN_COVERAGE
        expo = float(avail["혼잡노출시간_분"].sum()) if ok else np.nan
        rows.append({
            "비교대상": label, "행정동명": dong, "요일": g["요일"].iloc[0], "시간": hour,
            "표시가능": ok,
            "미표시사유": "" if ok else (
                "지하철 구간 없음" if not len(travel) else
                f"혼잡도 커버리지 {cov*100:.0f}% < {MIN_COVERAGE*100:.0f}%"),
            "최대혼잡도_pct": avail["혼잡도_pct"].max() if ok and len(avail) else np.nan,
            "평균혼잡도_pct": avail["혼잡도_pct"].mean() if ok and len(avail) else np.nan,
            "통계혼잡도": congestion_level(avail["혼잡도_pct"].max()) if ok and len(avail) else pd.NA,
            "편도혼잡노출시간_분": expo,
            "월혼잡노출시간_시간": expo * 2 * WORK_DAYS_PER_MONTH / 60 if ok else np.nan,
            "혼잡도커버리지_pct": cov * 100 if pd.notna(cov) else np.nan,
            "전체역간구간수": len(travel), "혼잡도확보구간수": len(avail),
            "구간시간산정방식": "TMAP 지하철 leg 총시간을 역간 구간수로 균등 배분",
        })
    out = pd.DataFrame(rows)
    if len(out):
        print(f"\n경로 {len(out)}건 중 표시가능 {out['표시가능'].sum()}건 / "
              f"미표시 {(~out['표시가능']).sum()}건")
        show = ["비교대상", "행정동명", "표시가능", "최대혼잡도_pct", "통계혼잡도",
                "편도혼잡노출시간_분", "혼잡도커버리지_pct", "미표시사유"]
        print(out[show].round(1).to_string(index=False))
    return out


def main():
    ap = argparse.ArgumentParser(description="혼잡도 표시값 재계산")
    ap.add_argument("--diagnose", action="store_true",
                    help="후보값의 JSON 경로 분포만 출력(방향 필드 확인용)")
    args = ap.parse_args()

    base = resolve_dir()
    print(f"입력 위치: {base}")
    station_raw = pd.read_csv(base / STATION_FILE, encoding="utf-8-sig")
    print(f"  읽음 {STATION_FILE}: {len(station_raw)}행")

    if "혼잡도추출후보_JSON" not in station_raw.columns:
        sys.exit("[중단] 혼잡도추출후보_JSON 컬럼이 없습니다. 17번 노트북 산출물이 맞는지 확인할 것.")

    if args.diagnose:
        diagnose(station_raw)
        return

    station = rebuild_station(station_raw)
    station.to_csv(base / OUT_STATION, index=False, encoding="utf-8-sig")

    route_path = base / ROUTE_FILE
    if not route_path.exists():
        print(f"\n[경고] {ROUTE_FILE} 없음 - 역 단위만 저장하고 종료")
        print(f"저장: {base / OUT_STATION}")
        return

    route_raw = pd.read_csv(route_path, encoding="utf-8-sig")
    print(f"  읽음 {ROUTE_FILE}: {len(route_raw)}행")
    route = rebuild_route(route_raw, station)
    route.to_csv(base / OUT_ROUTE, index=False, encoding="utf-8-sig")

    print(f"\n저장: {base / OUT_STATION}")
    print(f"저장: {base / OUT_ROUTE}")


if __name__ == "__main__":
    main()