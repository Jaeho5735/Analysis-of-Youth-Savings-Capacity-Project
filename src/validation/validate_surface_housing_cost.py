"""
표면주거비 외적 타당성 검증.

산출한 표면주거비가 실제 지역별 주거비 수준을 반영하는지 독립 외부 통계와 대조한다.

대조 자료는 실거래 신고가 아닌 표본조사 통계를 쓴다. 같은 원천을 두 번 집계하면
검증이 아니라 순환 논증이 된다. 한국부동산원 전국주택가격동향조사는 조사원이 표본
주택을 직접 조사하므로 국토부 실거래 신고와 생성 과정이 독립적이다.

단독주택 월세 통계는 제외한다. 주택 한 채 전체 임대가(권역 112~264만원)라 건물 내
호실 단위인 본 데이터(40~70만원대)와 측정 대상이 다르다. 실제로 권역 서열도 도심권이
최하위로 나와 원룸 시장과 상이하다. 정의가 다른 통계를 대조 기준으로 삼으면 검증이
오염된다.

절대값은 정의가 달라 비교할 수 없다(본 지표는 보증금 환산 포함, 외부는 순수 월세).
따라서 순위 일치도로 검증한다. 외부 통계가 자치구 단위로 공표되지 않아 권역(n=5)
대조에 그치므로, 검정력은 행정동 수준 그룹 차이 검정으로 보완한다.

입력: data/표면주거비_행정동_통합.csv
      data/행정동_기준코드표.csv
      data/*평균월세가격*연립*.csv, data/*오피스텔*월세가격*.csv (R-ONE 다운로드)
출력: data/표면주거비검증_권역별.csv, data/표면주거비검증_이상지역.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, kendalltau, mannwhitneyu

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

SURFACE_PATH = DATA_DIR / "표면주거비_행정동_통합.csv"
MASTER_PATH = DATA_DIR / "행정동_기준코드표.csv"
YEONRIP_GLOB = "*평균월세가격*연립*.csv"
OFFICETEL_GLOB = "*오피스텔*월세가격*.csv"

OUT_REGION = DATA_DIR / "표면주거비검증_권역별.csv"
OUT_ANOMALY = DATA_DIR / "표면주거비검증_이상지역.csv"

REGIONS = ["도심권", "동북권", "서북권", "서남권", "동남권"]
OFFICETEL_SIZE = "40㎡이하"      # 청년 1인가구 주거 규모와 맞는 구간
ANOMALY_Z = 2.5                  # 권역 대비 이탈도 판정 기준


def read_reb(path: Path, skiprows: int = 3) -> pd.DataFrame:
    """R-ONE 다운로드 파일은 상단 안내행이 있고 인코딩이 cp949다."""
    try:
        return pd.read_csv(path, encoding="cp949", header=None, skiprows=skiprows, thousands=",")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8-sig", header=None, skiprows=skiprows, thousands=",")


def numeric_block(df: pd.DataFrame, start_col: int = 4) -> pd.DataFrame:
    """월별 값 컬럼을 숫자로 정리한다. 따옴표·콤마가 섞여 들어온다."""
    return df.iloc[:, start_col:].apply(
        lambda c: pd.to_numeric(c.astype(str).str.replace('"', "").str.replace(",", ""), errors="coerce"))


def load_yeonrip() -> pd.DataFrame:
    hits = sorted(DATA_DIR.glob(YEONRIP_GLOB))
    if not hits:
        sys.exit(f"'{YEONRIP_GLOB}' 파일이 없습니다. R-ONE에서 연립다세대 평균월세가격을 받아주세요.")
    df = read_reb(hits[0])
    vals = numeric_block(df)
    out = pd.DataFrame({"권역": df[3].astype(str).str.strip(),
                        "연립다세대_만원": vals.mean(axis=1) / 10,
                        "_첫달": vals.iloc[:, 0], "_막달": vals.iloc[:, -1]})
    out = out[out["권역"].isin(REGIONS)]

    # 기간 선택이 결과를 좌우하는지 확인한다
    rho, _ = spearmanr(out["_첫달"], out["_막달"])
    print(f"외부 통계 기간 안정성(첫달 vs 막달 권역 순위상관): {rho:.3f}")
    return out[["권역", "연립다세대_만원"]]


def load_officetel() -> pd.DataFrame:
    hits = sorted(DATA_DIR.glob(OFFICETEL_GLOB))
    if not hits:
        print(f"[안내] '{OFFICETEL_GLOB}' 파일이 없어 오피스텔 대조는 건너뜁니다")
        return pd.DataFrame(columns=["권역", "오피스텔40_만원"])

    parts = []
    for h in hits:
        df = read_reb(h)
        vals = numeric_block(df)
        # 평균/중위가 번갈아 오므로 홀수 인덱스(중위)만 취한다
        parts.append(pd.DataFrame({"권역": df[2].astype(str).str.strip(),
                                   "규모": df[3].astype(str).str.strip(),
                                   "중위월세": vals.iloc[:, 1::2].mean(axis=1)}))
    op = pd.concat(parts).groupby(["권역", "규모"])["중위월세"].mean().reset_index()
    op = op[(op["규모"] == OFFICETEL_SIZE) & (op["권역"].isin(REGIONS))]
    print(f"오피스텔 대조 파일 {len(hits)}개 사용")
    return op.assign(오피스텔40_만원=lambda x: x["중위월세"] / 10)[["권역", "오피스텔40_만원"]]


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """표본수를 가중치로 쓴다. 거래가 적은 동이 권역 대표값을 흔들지 않게 한다."""
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    cw = np.cumsum(w)
    return float(v[np.searchsorted(cw, cw[-1] / 2)])


def load_surface() -> pd.DataFrame:
    if not SURFACE_PATH.exists():
        sys.exit(f"{SURFACE_PATH} 이 없습니다.")
    df = pd.read_csv(SURFACE_PATH, encoding="utf-8-sig")

    if MASTER_PATH.exists():
        df["행정동코드8"] = (pd.to_numeric(df["행정동코드_최종"], errors="coerce")
                         .astype("Int64").astype(str).str.zfill(10).str[:8])
        m = pd.read_csv(MASTER_PATH, encoding="utf-8-sig", dtype=str)
        df = df.merge(m[["행정동코드8", "권역"]], on="행정동코드8", how="left")
        miss = df["권역"].isna().sum()
        if miss:
            print(f"[경고] 권역 매핑 실패 {miss}행")
    else:
        sys.exit(f"{MASTER_PATH} 이 없습니다. build_region_master.py를 먼저 실행하세요.")

    print(f"표면주거비 {len(df)}행, 표본부족 {df['표본부족'].sum()}개")
    return df


def compare_regions(surf: pd.DataFrame, ext: pd.DataFrame) -> pd.DataFrame:
    ok = surf[~surf["표본부족"]]
    ours = (ok.groupby("권역")
            .apply(lambda g: weighted_median(g["표면주거비_중앙값"].values, g["표본수"].values),
                   include_groups=False)
            .rename("표면주거비_만원").reset_index())
    cmp = ours.merge(ext, on="권역")

    for c in [c for c in cmp.columns if c != "권역"]:
        cmp[f"순위_{c}"] = cmp[c].rank(ascending=False).astype(int)
    cmp = cmp.sort_values("순위_표면주거비_만원")

    print("\n[권역별 비교]")
    print(cmp.round(1).to_string(index=False))

    print("\n[순위 일치도]")
    for c in [c for c in ext.columns if c != "권역"]:
        rho, p1 = spearmanr(cmp["표면주거비_만원"], cmp[c])
        tau, p2 = kendalltau(cmp["표면주거비_만원"], cmp[c])
        print(f"  vs {c}: 스피어만 {rho:.3f}(p={p1:.3f}) / 켄달 {tau:.3f}(p={p2:.3f})")
    print(f"  * n={len(cmp)}이라 상관계수 자체의 통계적 해석은 제한적 - 아래 그룹 검정으로 보완")
    return cmp


def group_test(surf: pd.DataFrame, cmp: pd.DataFrame, ref_col: str) -> None:
    """외부 통계가 비싸다고 판정한 권역의 행정동이 실제로도 높게 나오는지 본다."""
    ok = surf[~surf["표본부족"]].dropna(subset=["권역"])
    hi_regions = cmp.nlargest(2, ref_col)["권역"].tolist()
    hi = ok[ok["권역"].isin(hi_regions)]["표면주거비_중앙값"]
    lo = ok[~ok["권역"].isin(hi_regions)]["표면주거비_중앙값"]

    u, p = mannwhitneyu(hi, lo, alternative="greater")
    rbc = abs(1 - 2 * u / (len(hi) * len(lo)))
    print(f"\n[그룹 차이 검정] 외부 기준 고주거비 권역({'+'.join(hi_regions)})")
    print(f"  고 {len(hi)}개(중앙 {hi.median():.1f}만원) vs 저 {len(lo)}개({lo.median():.1f}만원)")
    print(f"  Mann-Whitney p={p:.2e}, rank-biserial={rbc:.3f}")
    print(f"  무작위로 두 동을 뽑으면 {(1 + rbc) / 2 * 100:.0f}% 확률로 고주거비 권역 쪽이 높음")


def find_anomalies(surf: pd.DataFrame, cmp: pd.DataFrame, ref_col: str) -> pd.DataFrame:
    """권역 외부값 대비 이탈도가 큰 동을 뽑아 원인 귀속이 가능한지 본다."""
    df = surf.merge(cmp[["권역", ref_col]], on="권역", how="left").copy()
    ratio = np.log(df["표면주거비_중앙값"] / df[ref_col])
    mad = np.median(np.abs(ratio - np.median(ratio))) * 1.4826
    df["이탈도_z"] = (ratio - np.median(ratio)) / mad

    anom = df[(df["이탈도_z"].abs() > ANOMALY_Z) | df["표본부족"]].copy()
    anom["진단"] = np.where(
        anom["표본부족"], "표본부족(n<30) - 유효순위 제외 대상",
        np.where(anom["이탈도_z"] > 0, "권역 대비 고가 - 국지적 프리미엄 하위시장 검토",
                 "권역 대비 저가 - 주택유형 구성 검토"))

    cols = ["권역", "시군구명", "행정동명_최종", "표면주거비_중앙값", ref_col,
            "이탈도_z", "표본수", "주택유형_구성", "진단"]
    anom = anom.sort_values("이탈도_z", ascending=False)[[c for c in cols if c in anom.columns]]
    print(f"\n[이상 지역] 이탈도 |z|>{ANOMALY_Z} 또는 표본부족: {len(anom)}개")
    print(anom.drop(columns=[c for c in ["주택유형_구성"] if c in anom.columns]).round(2).to_string(index=False))
    return anom


def main():
    surf = load_surface()
    ext = load_yeonrip()
    op = load_officetel()
    if len(op):
        ext = ext.merge(op, on="권역", how="left")

    cmp = compare_regions(surf, ext)
    ref = "연립다세대_만원"
    group_test(surf, cmp, ref)
    anom = find_anomalies(surf, cmp, ref)

    cmp.round(3).to_csv(OUT_REGION, index=False, encoding="utf-8-sig")
    anom.round(3).to_csv(OUT_ANOMALY, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_REGION}")
    print(f"저장 완료: {OUT_ANOMALY}")


if __name__ == "__main__":
    main()