"""
행정동 유형화 품질 진단.

실루엣 계수가 0.2 내외로 낮다. 이 데이터에서는 당연한 결과다. 서울 행정동의 주거비와
통근시간은 강남에서 외곽으로 갈수록 연속적으로 변하지, "여기부터 싼 동네"라는 선이
그어져 있지 않다. 뚜렷한 경계가 없는 데이터에서 실루엣은 원래 낮게 나온다.

문제는 "원래 낮다"만으로는 군집이 의미 있다는 증명이 안 된다는 것이다. 그래서 실루엣
대신 네 가지로 타당성을 확인한다.

  1. 외적 타당성  군집에 쓰지 않은 변수에서도 군집 간 차이가 나는가
                  알고리즘이 임의로 그은 선이라면 다른 변수에서는 차이가 없어야 한다
  2. 안정성        표본을 바꿔도 같은 동들이 같은 군집에 모이는가
                  실무에서는 실루엣보다 이 지표를 더 신뢰하는 경우가 많다
  3. 기준선 대비   같은 분포의 무작위 데이터보다 뚜렷한가
                  절대값이 낮아도 기준선을 넘으면 구조가 있다는 신호다
  4. 알고리즘 비교 K-Means 말고 다른 방법으로도 비슷하게 갈리는가
  5. k별 비교      채택한 k가 다른 후보보다 견고한가

입력: data/행정동_유형화_결과.csv, data/주거통근_통합부담_행정동별.csv
출력: data/군집품질_진단.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, chi2_contingency
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

CLUSTER_PATH = DATA_DIR / "행정동_유형화_결과.csv"
BURDEN_PATH = DATA_DIR / "주거통근_통합부담_행정동별.csv"
OUT_PATH = DATA_DIR / "군집품질_진단.csv"

# 군집 형성에 쓴 변수. 외적 타당성 검정에서는 이들을 제외한다.
CLUSTER_FEATURES = ["표면주거비_원", "대표_편도통근시간_분", "월교통비_실지출_원",
                    "생활소비부담지수", "청년1인세대_비율"]
# 군집에 쓰지 않은 검정용 변수
EXTERNAL_NUMERIC = ["통합부담_정기권_원", "월세착시_순위차", "월시간비용_원",
                    "주거비_비중", "내부통근비중", "표본수"]
EXTERNAL_CATEGORY = ["부담유형", "권역"]

N_BOOTSTRAP = 50
N_RANDOM = 20
RANDOM_STATE = 42


def load() -> tuple:
    if not CLUSTER_PATH.exists():
        sys.exit(f"{CLUSTER_PATH} 이 없습니다. cluster_dong_types.py를 먼저 실행하세요.")
    df = pd.read_csv(CLUSTER_PATH, encoding="utf-8-sig")

    if BURDEN_PATH.exists():
        burden = pd.read_csv(BURDEN_PATH, encoding="utf-8-sig")
        add = [c for c in EXTERNAL_NUMERIC if c in burden.columns and c not in df.columns]
        keys = ["시군구명", "행정동명_최종"]
        if add:
            df = df.merge(burden[keys + add].drop_duplicates(keys), on=keys, how="left")

    feats = [c for c in CLUSTER_FEATURES if c in df.columns]
    # 사후 배정된 동은 군집 형성에 참여하지 않았으므로 품질 진단에서도 뺀다
    train = df[~df.get("군집_사후배정", False).fillna(False)].dropna(subset=feats + ["군집"])
    print(f"진단 대상 {len(train)}개 (전체 {len(df)}개 중 학습 참여분)")
    print(f"군집 입력 변수 {len(feats)}개: {feats}")
    return df, train, feats


def external_validity(train: pd.DataFrame) -> pd.DataFrame:
    """군집에 쓰지 않은 변수에서도 군집 간 차이가 나는지 본다."""
    print("\n" + "=" * 62)
    print("1. 외적 타당성 — 군집 형성에 쓰지 않은 변수에서의 차이")
    print("=" * 62)

    rows = []
    for col in EXTERNAL_NUMERIC:
        if col not in train.columns or train[col].isna().all():
            continue
        groups = [g[col].dropna().values for _, g in train.groupby("군집") if len(g[col].dropna()) > 1]
        if len(groups) < 2:
            continue
        h, p = kruskal(*groups)
        # epsilon-squared: Kruskal-Wallis의 효과크기 (0.01 작음 / 0.06 중간 / 0.14 큼)
        n = sum(len(g) for g in groups)
        eps2 = (h - len(groups) + 1) / (n - len(groups))
        rows.append({"변수": col, "검정": "Kruskal-Wallis", "통계량": h, "p": p,
                     "효과크기": eps2, "해석": "큼" if eps2 > 0.14 else "중간" if eps2 > 0.06 else "작음"})

    for col in EXTERNAL_CATEGORY:
        if col not in train.columns:
            continue
        ct = pd.crosstab(train["군집"], train[col])
        if ct.shape[0] < 2 or ct.shape[1] < 2:
            continue
        chi2, p, _, _ = chi2_contingency(ct)
        # Cramer's V (0.1 작음 / 0.3 중간 / 0.5 큼)
        v = np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1)))
        rows.append({"변수": col, "검정": "카이제곱", "통계량": chi2, "p": p,
                     "효과크기": v, "해석": "큼" if v > 0.5 else "중간" if v > 0.3 else "작음"})

    res = pd.DataFrame(rows)
    print(res.assign(p=lambda x: x["p"].map(lambda v: f"{v:.2e}"))
          .round({"통계량": 1, "효과크기": 3}).to_string(index=False))

    sig = (res["p"] < 0.05).sum()
    print(f"\n  {sig}/{len(res)}개 변수에서 유의한 차이 (p<0.05)")
    print("  군집이 임의로 그은 선이라면 이 변수들에서는 차이가 없어야 한다.")
    return res


def stability(X: np.ndarray, k: int) -> float:
    """표본을 바꿔도 같은 동들이 같은 군집에 모이는지 본다.

    부트스트랩으로 재추출해 군집을 다시 만들고, 원래 결과와 얼마나 일치하는지
    조정 랜드 지수(ARI)로 잰다. 1이면 완전 일치, 0이면 무작위 수준이다.
    """
    print("\n" + "=" * 62)
    print("2. 안정성 — 표본을 바꿔도 같은 유형이 유지되는가")
    print("=" * 62)

    base = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=50).fit_predict(X)
    rng = np.random.default_rng(RANDOM_STATE)
    scores = []
    for i in range(N_BOOTSTRAP):
        idx = rng.choice(len(X), size=len(X), replace=True)
        uniq = np.unique(idx)
        lab = KMeans(n_clusters=k, random_state=i, n_init=10).fit(X[idx]).predict(X[uniq])
        scores.append(adjusted_rand_score(base[uniq], lab))

    m, s = float(np.mean(scores)), float(np.std(scores))
    grade = "높음" if m >= 0.7 else "보통" if m >= 0.5 else "낮음"
    print(f"  부트스트랩 {N_BOOTSTRAP}회 ARI: 평균 {m:.3f} (표준편차 {s:.3f}) -> 안정성 {grade}")
    print("  ARI 0.7 이상이면 표본이 달라져도 유형 구성이 유지된다고 본다.")
    return m


def random_baseline(X: np.ndarray, k: int) -> tuple:
    """같은 분포의 무작위 데이터와 실루엣을 비교한다.

    변수별 분포는 유지하되 행 순서를 섞으면 변수 간 관계만 끊긴 데이터가 된다.
    여기서 나오는 실루엣이 '구조가 없을 때의 기준선'이다.
    """
    print("\n" + "=" * 62)
    print("3. 기준선 대비 — 무작위 데이터보다 뚜렷한가")
    print("=" * 62)

    actual = silhouette_score(X, KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=50).fit_predict(X))
    rng = np.random.default_rng(RANDOM_STATE)
    nulls = []
    for i in range(N_RANDOM):
        Xr = np.column_stack([rng.permutation(X[:, j]) for j in range(X.shape[1])])
        nulls.append(silhouette_score(Xr, KMeans(n_clusters=k, random_state=i, n_init=10).fit_predict(Xr)))

    m, s = float(np.mean(nulls)), float(np.std(nulls))
    z = (actual - m) / s if s else np.nan
    print(f"  실제 실루엣 {actual:.3f} vs 무작위 기준선 {m:.3f} (표준편차 {s:.3f})")
    print(f"  기준선 대비 {z:+.1f} 표준편차")
    if z > 3:
        print("  절대값은 낮지만 무작위보다 뚜렷하다 - 데이터에 구조가 있다는 신호")
    else:
        print("  기준선과 차이가 크지 않다 - 군집 구조가 약할 수 있어 해석에 주의")
    return actual, m, z


def algorithm_comparison(X: np.ndarray, k: int) -> pd.DataFrame:
    """K-Means만 써보고 결론 내린 것이 아님을 보인다."""
    print("\n" + "=" * 62)
    print("4. 알고리즘 비교 — 다른 방법으로도 비슷하게 갈리는가")
    print("=" * 62)

    km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=50).fit_predict(X)
    models = {
        "K-Means (채택)": km,
        "가우시안 혼합": GaussianMixture(n_components=k, random_state=RANDOM_STATE, n_init=5).fit_predict(X),
        "계층적(Ward)": AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X),
    }
    rows = []
    for name, lab in models.items():
        rows.append({"알고리즘": name, "실루엣": silhouette_score(X, lab),
                     "K-Means와_ARI": adjusted_rand_score(km, lab),
                     "최소군집": int(np.bincount(lab).min())})
    res = pd.DataFrame(rows)
    print(res.round(3).to_string(index=False))
    print("  ARI가 높으면 알고리즘을 바꿔도 같은 구조를 찾는다는 뜻이다.")
    return res


def scan_k_quality(X: np.ndarray, k_used: int) -> pd.DataFrame:
    """k별로 안정성과 기준선 대비를 함께 본다.

    실루엣만 보면 k가 작을수록 유리하고, 최소 군집 크기만 보면 과분할을 못 잡는다.
    안정성(ARI)과 기준선 대비 z를 같이 봐야 어느 k가 실제로 견고한지 드러난다.
    """
    print("\n" + "=" * 62)
    print("5. k별 품질 비교 — 채택한 k가 견고한 선택인가")
    print("=" * 62)
    rng = np.random.default_rng(RANDOM_STATE)
    rows = []
    for k in range(3, 9):
        base = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=50).fit_predict(X)
        sil = silhouette_score(X, base)
        nulls = []
        for i in range(15):
            Xr = np.column_stack([rng.permutation(X[:, j]) for j in range(X.shape[1])])
            nulls.append(silhouette_score(Xr, KMeans(n_clusters=k, random_state=i, n_init=10).fit_predict(Xr)))
        m, sd = float(np.mean(nulls)), float(np.std(nulls))
        aris = []
        for i in range(30):
            idx = rng.choice(len(X), len(X), replace=True)
            u = np.unique(idx)
            lab = KMeans(n_clusters=k, random_state=i, n_init=10).fit(X[idx]).predict(X[u])
            aris.append(adjusted_rand_score(base[u], lab))
        hier = adjusted_rand_score(base, AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X))
        rows.append({"k": k, "실루엣": sil, "무작위": m, "기준선대비_z": (sil - m) / sd if sd else np.nan,
                     "안정성_ARI": float(np.mean(aris)), "계층적_ARI": hier,
                     "최소군집": int(np.bincount(base).min()), "채택": "<-" if k == k_used else ""})
    res = pd.DataFrame(rows)
    print(res.round(3).to_string(index=False))
    best = res.loc[res["안정성_ARI"].idxmax(), "k"]
    if best != k_used:
        print(f"\n  안정성이 가장 높은 것은 k={best}다. 채택한 k={k_used}와 다르면")
        print("  해석 가능성을 위해 안정성을 얼마나 포기했는지 문서에 남겨야 한다.")
    return res


def main():
    df, train, feats = load()
    k = int(train["군집"].nunique())
    X = StandardScaler().fit_transform(train[feats])

    ext = external_validity(train)
    ari = stability(X, k)
    sil, null_sil, z = random_baseline(X, k)
    algo = algorithm_comparison(X, k)
    kscan = scan_k_quality(X, k)

    print("\n" + "=" * 62)
    print("종합")
    print("=" * 62)
    sig = int((ext["p"] < 0.05).sum())
    print(f"  실루엣 {sil:.3f} (무작위 기준선 {null_sil:.3f}, {z:+.1f} 표준편차)")
    print(f"  군집 미사용 변수 {sig}/{len(ext)}개에서 유의한 차이")
    print(f"  부트스트랩 안정성 ARI {ari:.3f}")
    print(f"  알고리즘 간 일치도 ARI {algo['K-Means와_ARI'].iloc[1:].mean():.3f}")
    print("\n  실루엣이 낮은 것은 주거비·통근시간이 연속적으로 변하는 데이터의 특성이다.")
    print("  경계가 흐릿하더라도 위 지표들이 뒷받침하면 유형화 자체는 타당하다고 본다.")

    summary = pd.concat([
        ext.assign(구분="외적 타당성"),
        pd.DataFrame([{"구분": "안정성", "변수": "부트스트랩 ARI", "통계량": ari},
                      {"구분": "기준선", "변수": "실루엣", "통계량": sil},
                      {"구분": "기준선", "변수": "무작위 실루엣", "통계량": null_sil},
                      {"구분": "기준선", "변수": "기준선 대비 표준편차", "통계량": z}]),
        algo.rename(columns={"알고리즘": "변수", "실루엣": "통계량"}).assign(구분="알고리즘 비교"),
        kscan.assign(구분="k별 비교", 변수=lambda x: "k=" + x["k"].astype(str)),
    ], ignore_index=True)
    summary.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_PATH}")


if __name__ == "__main__":
    main()