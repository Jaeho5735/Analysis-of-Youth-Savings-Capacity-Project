"""
행정동 유형화 군집분석 (예비 - 통근권 변수 제외).

기획안 17-2의 군집 입력 변수 7개 중, 루뱅 통근권 분석이 아직 없어 산출되지 않은
2개(동일 통근권 내부 출근 비율, 목적지 집중도)를 제외하고 5개로 먼저 돌린다.
통근권 변수가 나오면 동일 절차로 재실행해 유형이 얼마나 흔들리는지 비교한다.

입력 변수는 파생이 아닌 원천변수만 쓴다. 통근시간 기회비용은 통근시간에 상수를 곱한
값이고, 통합부담은 여러 변수를 합산한 값이라 함께 넣으면 같은 정보를 두 번 세게 된다.
이들은 군집 형성이 아니라 군집 결과 해석에 쓴다.

군집 수는 실루엣 계수와 엘보로 후보를 좁히되, 최종 판단에는 해석 가능성을 함께 본다.
군집 명칭은 사전에 정하지 않고 군집별 변수 평균을 확인한 뒤 사후에 붙인다.

입력: data/주거통근_통합부담_행정동별.csv
출력: data/행정동_유형화_결과.csv, data/행정동_유형화_프로파일.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

BURDEN_PATH = DATA_DIR / "주거통근_통합부담_행정동별.csv"
# 파일명이 소스마다 달라 이름에 "청년1인세대"가 들어간 csv를 찾는다
YOUTH_CANDIDATES = sorted(DATA_DIR.glob("*청년1인세대*.csv"))
YOUTH_PATH = YOUTH_CANDIDATES[0] if YOUTH_CANDIDATES else DATA_DIR / "청년1인세대_행정동별.csv"
OUT_RESULT = DATA_DIR / "행정동_유형화_결과.csv"
OUT_PROFILE = DATA_DIR / "행정동_유형화_프로파일.csv"

# 기획안 17-2의 군집 입력 변수 7개.
# 목적지 집중도는 HHI 대신 정규화 엔트로피를 쓴다. HHI는 내부통근 비중과 상관 0.87로
# 사실상 "자기 동에서 일한다"를 재고, 분포도 중앙 0.020 대 최대 0.208로 치우쳐 있다.
# 정규화 엔트로피는 0.53~0.86으로 고르고 다른 변수와의 최대 상관도 0.66이다.
BASE_FEATURES = ["표면주거비_원", "대표_편도통근시간_분", "월교통비_실지출_원",
                 "생활소비부담지수", "동일통근권_내부출근비율", "목적지_정규화엔트로피"]
YOUTH_FEATURE = "청년1인세대_비율"
CORR_LIMIT = 0.8
K_RANGE = range(3, 10)
K_FIXED = 7                  # 실루엣 최댓값 대신 해석 가능성으로 확정
WINSOR_Q = 0.01              # 교통비 극단치가 단독 군집을 만드는 것을 막는다
MIN_CLUSTER_SIZE = 10        # 이보다 작은 군집이 생기면 과분할로 본다
RANDOM_STATE = 42


def load() -> tuple:
    if not BURDEN_PATH.exists():
        sys.exit(f"{BURDEN_PATH} 이 없습니다. build_total_burden.py를 먼저 실행하세요.")
    df = pd.read_csv(BURDEN_PATH, encoding="utf-8-sig")
    df["행정동코드8"] = df["행정동코드8"].astype(str).str.zfill(8)

    missing = [c for c in BASE_FEATURES if c not in df.columns]
    if missing:
        print(f"[안내] 입력에 없는 변수 {missing} - 제외하고 진행")
        print("  통근권 변수가 없다면 build_total_burden.py가 11번 산출물만 읽은 것이다")
    feats = [c for c in BASE_FEATURES if c in df.columns]
    if YOUTH_PATH.exists():
        print(f"청년 1인세대 파일: {YOUTH_PATH.name}")
        y = pd.read_csv(YOUTH_PATH, encoding="utf-8-sig")
        need = ["행정기관코드", "전체1인세대대비_청년1인세대비율_3개년", "3개년_저표본_여부"]
        miss = [c for c in need if c not in y.columns]
        if miss:
            sys.exit(f"청년 1인세대 파일에 컬럼이 없습니다: {miss}")
        # 전체 1인세대 대비 청년 비율을 쓴다. 세대수 대비는 그 동의 1인세대 자체가
        # 적으면 낮게 나와, 청년 밀집도가 아니라 가구 구성을 재게 된다.
        y["행정동코드8"] = (pd.to_numeric(y["행정기관코드"], errors="coerce")
                        .astype("Int64").astype(str).str.zfill(10).str[:8])
        y = y.rename(columns={"전체1인세대대비_청년1인세대비율_3개년": YOUTH_FEATURE})
        df = df.merge(y[["행정동코드8", YOUTH_FEATURE, "3개년_저표본_여부"]], on="행정동코드8", how="left")
        df["청년세대_저표본"] = df["3개년_저표본_여부"].eq("주의")
        feats.append(YOUTH_FEATURE)
        print(f"청년 1인세대 비율 결합: 미매칭 {df[YOUTH_FEATURE].isna().sum()}행, "
              f"저표본 주의 {df['청년세대_저표본'].sum()}개")
    else:
        print("[안내] 청년 1인세대 파일이 없어 해당 변수 없이 진행")

    # 표본이 부실한 동은 군집 형성에서 빼고, 학습된 군집에 사후 배정한다
    def flag(col):
        if col not in df.columns:
            return pd.Series(False, index=df.index)
        return df[col].astype("boolean").fillna(False).astype(bool)

    weak = (flag("표본부족") | flag("업종부족") | flag("교통비_커버리지부족")
            | flag("청년세대_저표본") | df[feats].isna().any(axis=1))
    print(f"군집 학습 대상 {(~weak).sum()}개 / 사후 배정 {weak.sum()}개(표본·업종·커버리지 부족)")
    return df, feats, weak


def winsorize(s: pd.Series, q: float = WINSOR_Q) -> pd.Series:
    """극단값을 제거하지 않고 분위 경계로 눌러 단독 군집 생성을 막는다."""
    return s.clip(s.quantile(q), s.quantile(1 - q))


def scan_k(X: np.ndarray) -> None:
    """실루엣은 k가 작을수록 유리한 편향이 있어 단독 기준으로 쓰지 않는다.
    최소 군집 크기를 함께 보고 과분할 여부를 판단한다."""
    print("\n[군집 수 진단]")
    for k in K_RANGE:
        km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=20).fit(X)
        sizes = np.bincount(km.labels_)
        flag = "  <- 과분할" if sizes.min() < MIN_CLUSTER_SIZE else ""
        print(f"  k={k}: 실루엣 {silhouette_score(X, km.labels_):.3f}, "
              f"inertia {km.inertia_:7.1f}, 최소군집 {sizes.min():3d}개{flag}")
    print(f"  -> 채택 k={K_FIXED} (기획안 예상 유형 수 및 해석 가능성 기준)")


def profile(df: pd.DataFrame, feats: list, label: str = "군집") -> pd.DataFrame:
    agg = {f: "mean" for f in feats}
    agg["월교통비_원본_원"] = "mean"
    agg["통합부담_정기권_원"] = "mean"
    agg["월세착시_순위차"] = "mean"
    prof = df.groupby(label).agg(agg)
    prof["행정동수"] = df.groupby(label).size()
    return prof


def name_clusters(prof: pd.DataFrame, feats: list) -> dict:
    """군집별 변수 평균의 상대 위치로 사후 명명한다."""
    z = (prof[feats] - prof[feats].mean()) / prof[feats].std(ddof=0)
    names = {}
    for c in prof.index:
        h = z.loc[c, "표면주거비_원"]
        t = z.loc[c, "대표_편도통근시간_분"]
        fare = z.loc[c, "월교통비_실지출_원"]
        idx = z.loc[c, "생활소비부담지수"] if "생활소비부담지수" in feats else 0
        y = z.loc[c, YOUTH_FEATURE] if YOUTH_FEATURE in feats else 0

        inner = z.loc[c, "동일통근권_내부출근비율"] if "동일통근권_내부출근비율" in feats else 0
        div = z.loc[c, "목적지_정규화엔트로피"] if "목적지_정규화엔트로피" in feats else 0

        # 가장 두드러진 축부터 본다. 여러 조건에 걸리면 편차가 큰 쪽이 그 유형의 성격이다.
        if fare > 1.0:
            nm = "교통비 부담형"
        elif h > 1.0:
            nm = "고주거비·근거리형" if t < 0 else "고주거비·장거리형"
        elif y > 1.0:
            nm = "청년 밀집형"
        elif idx > 1.0:
            nm = "생활소비 압박형"
        elif inner < -1.0:
            nm = "통근권 외부의존형"
        elif t > 0.8:
            nm = "저주거비·장거리형" if h < 0 else "통근 부담형"
        elif h < -0.6:
            nm = "상대적 저부담형"
        elif inner > 0.8 and div < 0:
            nm = "통근권 내부완결형"
        else:
            nm = "주거·통근 균형형"

        if nm in names.values():
            # 같은 이름이 겹치면 그 유형 안에서 가장 차이 나는 축으로 구분한다
            axis = max([("주거비", h), ("통근", t), ("청년", y), ("소비", idx)], key=lambda kv: abs(kv[1]))
            nm = f"{nm}({axis[0]}{'↑' if axis[1] > 0 else '↓'})"
            n = 2
            base = nm
            while nm in names.values():
                nm = f"{base}-{n}"; n += 1
        names[c] = nm
    return names


def main():
    df, feats, weak = load()

    # 군집 계산용으로만 극단치를 누른다. 산출 파일에는 원본 값을 남긴다.
    df["월교통비_원본_원"] = df["월교통비_실지출_원"]
    df["월교통비_실지출_원"] = winsorize(df["월교통비_실지출_원"])
    df["교통비_윈저라이징"] = df["월교통비_원본_원"] != df["월교통비_실지출_원"]
    print(f"\n교통비 윈저라이징(상하위 {WINSOR_Q:.0%}): {df['교통비_윈저라이징'].sum()}개 동의 값이 눌림 "
          f"(제외가 아니라 경계값으로 조정, 전부 유형에 포함)")

    train = df[~weak].copy()
    scaler = StandardScaler().fit(train[feats])
    Xtr = scaler.transform(train[feats])

    corr = train[feats].corr().abs()
    high = [(a, b, corr.loc[a, b]) for i, a in enumerate(feats)
            for b in feats[i + 1:] if corr.loc[a, b] > CORR_LIMIT]
    print(f"\n[변수 상관] 최대 {corr.where(~np.eye(len(feats), dtype=bool)).max().max():.3f}")
    if high:
        print(f"[경고] 상관 {CORR_LIMIT} 초과 쌍 - 같은 정보를 두 번 세게 되므로 하나를 빼야 한다")
        for a, b, v in high:
            print(f"  {a} ~ {b}: {v:.3f}")

    scan_k(Xtr)
    k = K_FIXED
    km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=50).fit(Xtr)
    train["군집"] = km.labels_

    # 학습에서 제외한 동은 가장 가까운 중심에 배정하고 플래그로 구분
    df["군집"] = np.nan
    df.loc[~weak, "군집"] = km.labels_
    if weak.sum():
        ok = df[weak][feats].notna().all(axis=1)
        idx = df[weak][ok].index
        if len(idx):
            df.loc[idx, "군집"] = km.predict(scaler.transform(df.loc[idx, feats]))
    df["군집_사후배정"] = weak & df["군집"].notna()
    df["군집"] = df["군집"].astype("Int64")

    prof = profile(train, feats)
    names = name_clusters(prof, feats)
    df["행정동_유형"] = df["군집"].map(names)
    prof.index = [f"{c} {names[c]}" for c in prof.index]

    print(f"\n[군집 프로파일 (k={k}, 학습 {len(train)}개 기준)]")
    print(prof.round(1).to_string())

    print("\n[유형별 대표 행정동]")
    for c, nm in names.items():
        sub = train[train["군집"] == c].nsmallest(4, "통합부담_정기권_원")
        print(f"  {nm} ({(train['군집']==c).sum()}개): {', '.join(sub['행정동명_최종'])}")

    print("\n[유형 x 부담유형 교차]")
    print(pd.crosstab(df["행정동_유형"], df["부담유형"]).to_string())

    keep = (["행정동코드8", "시군구명", "행정동명_최종", "권역", "군집", "행정동_유형", "군집_사후배정",
             "부담유형"] + feats +
            ["월교통비_원본_원", "교통비_윈저라이징", "통합부담_정기권_원", "월세착시_순위차",
             "표본부족", "업종부족", "교통비_커버리지부족", "청년세대_저표본"])
    df[[c for c in keep if c in df.columns]].to_csv(OUT_RESULT, index=False, encoding="utf-8-sig")
    prof.round(2).to_csv(OUT_PROFILE, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_RESULT}")
    print(f"저장 완료: {OUT_PROFILE}")


if __name__ == "__main__":
    main()