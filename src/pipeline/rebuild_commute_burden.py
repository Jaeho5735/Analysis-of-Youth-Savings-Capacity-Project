"""
거주동별 대표 통근부담 갱신 (경로 파생 컬럼만)

재조회로 commute_routes_analysis_ready.csv 가 바뀌었으므로
그 위에서 계산되는 거주동 대표값을 다시 내야 한다.

노트북은 건드리지 않는다.
11번 노트북(11_build_commute_burden_metrics_no_confidence.ipynb)의
산식을 그대로 옮겨와 계산하고, 기존 집계 파일에서
**경로에서 파생되는 컬럼만** 덮어쓴다.

    갱신함   대표_편도통근시간_분 · 대표_편도통근거리_km · 대표_편도교통비_원
             API_경로포함률 · 교통비_산출포함률
             대표_편도도보시간_분 · 대표_편도환승횟수 (+ 각 산출포함률)
             월_통근시간_분/시간 · 월_통근교통비_원 · 월_통근시간_기회비용_원

    유지함   루뱅 통근권 · 목적지 엔트로피 · 내부출근비중 · 유입유출 등
             전체 OD 기반이라 재조회와 무관하다 (12번 노트북 산출물)

산식 출처 (11번 노트북)
    대표시간   sum(분석용_편도시간_분 x 최종_가중치)
    대표요금   요금이 있는 OD 안에서 가중치를 재조정한 뒤 가중합
    포함률     이동량 기준 (경로/요금 있는 OD 이동량 / 전체 선택 OD 이동량)
    월환산     편도 x 2 x 21일, 기회비용 = 월 통근시간(시간) x 10,320원

사용법
    python rebuild_commute_burden.py --dry-run
    python rebuild_commute_burden.py
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# 11번 노트북과 동일
MONTHLY_WORKDAYS = 21.0
HOURLY_TIME_VALUE_WON = 10_320.0

IN_ROUTES = "data/commute_routes_analysis_ready.csv"
IN_METRICS = "data/commute_burden_with_network_metrics.csv"
OUT_METRICS = "data/commute_burden_with_network_metrics.csv"

KEY = ["거주동 코드", "거주동 이름"]


def log(m=""):
    print(m, flush=True)


def section(t):
    log()
    log("=" * 68)
    log(t)
    log("=" * 68)


def read_csv_any(path, **kw):
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"{path} 읽기 실패")


def weighted_with_available(od, value_col, result_col, coverage_col):
    """11번 노트북 weighted_metric_with_available_rows 와 동일."""
    t = od[KEY + ["출근_이동량", "최종_가중치", value_col]].copy()
    t[value_col] = pd.to_numeric(t[value_col], errors="coerce")
    t["_ok"] = t[value_col].notna()

    wsum = t.loc[t["_ok"]].groupby(KEY, observed=True)["최종_가중치"].transform("sum")
    t["_w"] = np.nan
    t.loc[t["_ok"], "_w"] = t.loc[t["_ok"], "최종_가중치"] / wsum
    t["_wv"] = t[value_col] * t["_w"]
    t["_cov"] = np.where(t["_ok"], t["출근_이동량"], 0)

    r = t.groupby(KEY, as_index=False, observed=True).agg(
        **{result_col: ("_wv", "sum"),
           "_c": ("_cov", "sum"), "_t": ("출근_이동량", "sum"), "_any": ("_ok", "any")})
    r.loc[~r["_any"], result_col] = np.nan
    r[coverage_col] = r["_c"] / r["_t"]
    return r.drop(columns=["_c", "_t", "_any"])


def build(od):
    """11번 노트북 산식으로 거주동별 대표값을 만든다."""
    for c in ["분석용_편도시간_분", "분석용_편도거리_km", "분석용_편도요금_원",
              "최종_가중치", "출근_이동량"]:
        od[c] = pd.to_numeric(od[c], errors="coerce")

    # 5. 대표 편도 통근시간·거리
    od["_wt"] = od["분석용_편도시간_분"] * od["최종_가중치"]
    od["_wd"] = od["분석용_편도거리_km"] * od["최종_가중치"]
    out = od.groupby(KEY, as_index=False, observed=True).agg(
        대표_편도통근시간_분=("_wt", "sum"),
        대표_편도통근거리_km=("_wd", "sum"))

    # 6. 대표 편도 교통비 — 요금 존재 OD 안에서 가중치 재조정
    od["_fee_ok"] = od["분석용_편도요금_원"].notna()
    fsum = od.loc[od["_fee_ok"]].groupby(KEY, observed=True)["최종_가중치"].transform("sum")
    od["_fw"] = np.nan
    od.loc[od["_fee_ok"], "_fw"] = od.loc[od["_fee_ok"], "최종_가중치"] / fsum
    od["_wf"] = od["분석용_편도요금_원"] * od["_fw"]

    fee = od.groupby(KEY, as_index=False, observed=True).agg(
        대표_편도교통비_원=("_wf", "sum"))
    has_fee = od.groupby(KEY, observed=True)["_fee_ok"].any().rename("_has").reset_index()
    fee = fee.merge(has_fee, on=KEY, how="left")
    fee.loc[~fee["_has"], "대표_편도교통비_원"] = np.nan
    out = out.merge(fee.drop(columns="_has"), on=KEY, how="left")

    # 7. 포함률 — 이동량 기준
    od["_route_ok"] = od["분석용_편도시간_분"].notna() & od["분석용_편도거리_km"].notna()
    od["_rv"] = np.where(od["_route_ok"], od["출근_이동량"], 0)
    od["_fv"] = np.where(od["_fee_ok"], od["출근_이동량"], 0)
    cov = od.groupby(KEY, as_index=False, observed=True).agg(
        _sel=("출근_이동량", "sum"), _r=("_rv", "sum"), _f=("_fv", "sum"))
    cov["API_경로포함률"] = cov["_r"] / cov["_sel"]
    cov["교통비_산출포함률"] = cov["_f"] / cov["_sel"]
    out = out.merge(cov[KEY + ["API_경로포함률", "교통비_산출포함률"]], on=KEY, how="left")

    # 10. 도보·환승 보조지표
    if "총도보시간_분" in od.columns:
        out = out.merge(weighted_with_available(
            od, "총도보시간_분", "대표_편도도보시간_분", "도보시간_산출포함률"),
            on=KEY, how="left")
    if "환승횟수" in od.columns:
        out = out.merge(weighted_with_available(
            od, "환승횟수", "대표_편도환승횟수", "환승_산출포함률"),
            on=KEY, how="left")

    # 11~12. 월 환산과 기회비용
    out["월_통근시간_분"] = out["대표_편도통근시간_분"] * 2 * MONTHLY_WORKDAYS
    out["월_통근시간_시간"] = out["월_통근시간_분"] / 60
    out["월_통근교통비_원"] = out["대표_편도교통비_원"] * 2 * MONTHLY_WORKDAYS
    out["월_통근시간_기회비용_원"] = out["월_통근시간_시간"] * HOURLY_TIME_VALUE_WON
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", default=IN_ROUTES)
    ap.add_argument("--metrics", default=IN_METRICS)
    ap.add_argument("--out", default=OUT_METRICS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    section("[1단계] 입력 확인")
    for lb, p in [("경로", args.routes), ("집계", args.metrics)]:
        ok = Path(p).exists()
        log(f"  {lb:6s} {p}  {'OK' if ok else '(없음)'}")
        if not ok:
            log("\n  경로를 --routes / --metrics 로 지정해라.")
            return

    od = read_csv_any(args.routes)
    met = read_csv_any(args.metrics)
    od.columns = [c.strip() for c in od.columns]
    met.columns = [c.strip() for c in met.columns]
    log(f"\n  경로 {len(od):,}행 / 집계 {len(met):,}행 {len(met.columns)}컬럼")

    miss = [c for c in KEY + ["최종_가중치", "출근_이동량"] if c not in od.columns]
    if miss:
        log(f"  [중단] 경로 파일에 없는 컬럼: {miss}")
        return
    if not all(k in met.columns for k in KEY):
        log(f"  [중단] 집계 파일에 결합키가 없다. 컬럼: {list(met.columns)[:12]}")
        return

    section("[2단계] 대표값 재계산 (11번 노트북 산식)")
    new = build(od)
    log(f"  거주동 {len(new):,}개 산출")

    section("[3단계] 갱신 대상 컬럼")
    upd = [c for c in new.columns if c not in KEY and c in met.columns]
    skip = [c for c in new.columns if c not in KEY and c not in met.columns]
    log(f"  갱신 {len(upd)}개")
    for c in upd:
        log(f"    {c}")
    if skip:
        log(f"\n  집계 파일에 없어 건너뜀 {len(skip)}개: {skip}")
    keep = [c for c in met.columns if c not in upd and c not in KEY]
    log(f"\n  그대로 유지 {len(keep)}개 (네트워크 지표 등)")

    section("[4단계] 변화 확인")
    m = met[KEY + upd].merge(new[KEY + upd], on=KEY, how="left", suffixes=("_구", "_신"))
    for c in upd:
        a, b = pd.to_numeric(m[f"{c}_구"], errors="coerce"), pd.to_numeric(m[f"{c}_신"], errors="coerce")
        both = a.notna() & b.notna()
        if not both.any():
            continue
        d = (b - a)[both]
        log(f"  {c:<26} 평균 {d.mean():+9.2f}  중앙 {d.median():+9.2f}  "
            f"변화 {int((d.abs() > 1e-9).sum()):>4}/{int(both.sum())}")

    if args.dry_run:
        section("dry-run 종료")
        log("  파일을 쓰지 않았다. 변화가 타당하면 --dry-run 없이 실행해라.")
        return

    merged = met.drop(columns=upd).merge(new[KEY + upd], on=KEY, how="left")
    merged = merged.reindex(columns=list(met.columns))

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    bak = Path(args.metrics).with_name(
        Path(args.metrics).stem + f"_{stamp}.bak.csv")
    shutil.copy(args.metrics, bak)
    merged.to_csv(args.out, index=False, encoding="utf-8-sig")

    section("완료")
    log(f"  백업: {bak}")
    log(f"  저장: {args.out}  ({len(merged):,}행 {len(merged.columns)}컬럼)")
    log()
    log("  다음: python src/analysis/build_total_burden.py")


if __name__ == "__main__":
    main()