"""
주거·통근 통합부담 테이블 산출.

행정동별로 표면주거비와 통근부담(교통비 + 시간 기회비용)을 합산해 하나의 기준으로
비교 가능한 부담 지표를 만든다.

교통비는 두 값을 병기한다. 실지출 기준(원산출)과 기후동행카드 정기권 상한을 적용한
기준이다. 서울은 정기권 때문에 실제 지역 간 교통비 격차가 크게 눌리므로, 캡을 씌우지
않으면 통근부담이 과대평가된다.

시간 기회비용은 최저임금 기준(10,320원/시간)을 기본으로 하되, 월 통근시간 컬럼에서
언제든 다른 시간가치로 재계산할 수 있도록 시간과 금액을 함께 남긴다.

생활소비부담지수는 금액 산식에 직접 차감하지 않는다(기획안 12-6). 지역 특성 해석과
군집화 입력으로만 쓴다.

입력: data/표면주거비_행정동_통합.csv
      data/commute_burden_by_home_dong.csv
      data/생활소비부담지수_행정동별.csv
      data/행정동_기준코드표.csv
출력: data/주거통근_통합부담_행정동별.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

SURFACE_PATH = DATA_DIR / "표면주거비_행정동_통합.csv"
COMMUTE_PATH = DATA_DIR / "commute_burden_by_home_dong.csv"
INDEX_PATH = DATA_DIR / "생활소비부담지수_행정동별.csv"
CROSSWALK_PATH = DATA_DIR / "행정동_기준코드표.csv"
OUT_PATH = DATA_DIR / "주거통근_통합부담_행정동별.csv"

TRANSIT_PASS_CAP = 62000      # 기후동행카드 월 정기권
HOURLY_VALUE = 10320          # 시간가치 기준(최저임금)
COVERAGE_MIN = 0.7            # 교통비 산출 포함률 하한


def to_code8(s: pd.Series, width: int = 10) -> pd.Series:
    """코드 자릿수를 8자리로 통일한다. 10자리 KIKmix는 앞 8자리가 통계청 코드와 같다."""
    return pd.to_numeric(s, errors="coerce").astype("Int64").astype(str).str.zfill(width).str[:8]


def load_and_merge() -> pd.DataFrame:
    for p in (SURFACE_PATH, COMMUTE_PATH):
        if not p.exists():
            sys.exit(f"{p} 이 없습니다.")

    surf = pd.read_csv(SURFACE_PATH, encoding="utf-8-sig")
    surf["행정동코드8"] = to_code8(surf["행정동코드_최종"])

    com = pd.read_csv(COMMUTE_PATH, encoding="utf-8-sig")
    com["행정동코드8"] = com["거주동 코드"].astype(str).str.zfill(8)

    df = surf.merge(com.drop(columns=["거주동 이름"]), on="행정동코드8",
                    how="inner", validate="one_to_one")
    print(f"주거 {len(surf)} + 통근 {len(com)} -> 결합 {len(df)}행")
    only_com = set(com["행정동코드8"]) - set(surf["행정동코드8"])
    if only_com:
        print(f"  통근에만 있는 {len(only_com)}개는 비아파트 임차 거래가 없는 동(기준코드표에서 확인됨)")

    if INDEX_PATH.exists():
        idx = pd.read_csv(INDEX_PATH, encoding="utf-8-sig")
        vals = [c for c in ["생활소비부담지수", "생활소비부담지수_전연령",
                            "반영업종수", "업종부족"] if c in idx.columns]
        # 코드가 있으면 코드로 결합한다. 이름 결합은 "창신제1동" vs "창신1동" 같은
        # 표기 차이로 조용히 누락되므로 코드가 없을 때만 쓴다.
        if "행정동_코드" in idx.columns:
            idx["행정동코드8"] = to_code8(idx["행정동_코드"], 8)
            df = df.merge(idx[["행정동코드8"] + vals].drop_duplicates("행정동코드8"),
                          on="행정동코드8", how="left", validate="one_to_one")
            how = "코드"
        else:
            df = df.merge(idx[["시군구명", "행정동_코드_명"] + vals],
                          left_on=["시군구명", "행정동명_최종"],
                          right_on=["시군구명", "행정동_코드_명"], how="left", validate="one_to_one")
            how = "이름(지수 산출물에 행정동_코드 추가 권장)"
        print(f"  생활소비부담지수 결합[{how}]: 미매칭 {df['생활소비부담지수'].isna().sum()}행")
    else:
        print(f"  [경고] {INDEX_PATH.name} 없음 - 지수 없이 진행")
        df["생활소비부담지수"] = pd.NA
        df["업종부족"] = False

    if CROSSWALK_PATH.exists():
        cw = pd.read_csv(CROSSWALK_PATH, encoding="utf-8-sig", dtype=str)
        df = df.merge(cw[["행정동코드8", "권역"]], on="행정동코드8", how="left")
    return df


def build_burden(df: pd.DataFrame) -> pd.DataFrame:
    df["표면주거비_원"] = df["표면주거비_중앙값"] * 10000

    # 교통비: 실지출과 정기권 상한 적용을 병기한다
    df["월교통비_실지출_원"] = df["월_통근교통비_원"]
    df["월교통비_정기권_원"] = df["월_통근교통비_원"].clip(upper=TRANSIT_PASS_CAP)
    df["정기권_유리"] = df["월_통근교통비_원"] > TRANSIT_PASS_CAP

    # 시간 기회비용: 팀원 산출이 최저임금 기준이므로 그대로 쓰되, 다른 기준 재계산 대비
    df["월시간비용_원"] = df["월_통근시간_시간"] * HOURLY_VALUE

    df["통근부담_실지출_원"] = df["월교통비_실지출_원"] + df["월시간비용_원"]
    df["통근부담_정기권_원"] = df["월교통비_정기권_원"] + df["월시간비용_원"]
    df["통합부담_실지출_원"] = df["표면주거비_원"] + df["통근부담_실지출_원"]
    df["통합부담_정기권_원"] = df["표면주거비_원"] + df["통근부담_정기권_원"]

    df["주거비_비중"] = df["표면주거비_원"] / df["통합부담_정기권_원"]
    df["통근비_비중"] = df["통근부담_정기권_원"] / df["통합부담_정기권_원"]

    df["교통비_커버리지부족"] = df["교통비_산출포함률"] < COVERAGE_MIN
    print(f"\n교통비 산출 포함률 {COVERAGE_MIN} 미만: {df['교통비_커버리지부족'].sum()}개 (플래그 처리)")
    return df


def rank_and_type(df: pd.DataFrame) -> pd.DataFrame:
    """월세 착시 분석 - 주거비 순위와 통합부담 순위의 괴리를 본다."""
    df["순위_주거비"] = df["표면주거비_원"].rank(ascending=True, method="min").astype(int)
    df["순위_통합부담"] = df["통합부담_정기권_원"].rank(ascending=True, method="min").astype(int)
    df["월세착시_순위차"] = df["순위_주거비"] - df["순위_통합부담"]

    mh, mt = df["표면주거비_원"].median(), df["통합부담_정기권_원"].median()
    df["부담유형"] = np.select(
        [(df["표면주거비_원"] < mh) & (df["통합부담_정기권_원"] < mt),
         (df["표면주거비_원"] < mh) & (df["통합부담_정기권_원"] >= mt),
         (df["표면주거비_원"] >= mh) & (df["통합부담_정기권_원"] < mt)],
        ["A 실질 저부담", "B 월세 착시", "C 숨은 효율"],
        default="D 종합 고부담")
    print("\n[부담 유형 분포]")
    print(df["부담유형"].value_counts().sort_index().to_string())
    return df


def report(df: pd.DataFrame) -> None:
    print("\n[비용 항목별 격차 - 무엇이 부담을 가르는가]")
    for label, col in [("표면주거비", "표면주거비_원"), ("시간 기회비용", "월시간비용_원"),
                       ("교통비(실지출)", "월교통비_실지출_원"), ("교통비(정기권)", "월교통비_정기권_원")]:
        s = df[col]
        print(f"  {label:14s} 최소 {s.min():>9,.0f} / 중앙 {s.median():>9,.0f} / 최대 {s.max():>9,.0f} / 격차 {s.max()-s.min():>9,.0f}")

    print("\n[구성비] 주거비 {:.1%} / 통근부담 {:.1%} (중앙값 기준)".format(
        df["주거비_비중"].median(), df["통근비_비중"].median()))

    valid = df[~df["교통비_커버리지부족"]]
    cols = ["시군구명", "행정동명_최종", "표면주거비_원", "통합부담_정기권_원", "순위_주거비", "순위_통합부담", "월세착시_순위차"]

    print("\n[B 월세 착시] 월세는 싼데 통근부담까지 더하면 비싼 동 - 순위 하락 상위 8")
    print(valid[valid["부담유형"] == "B 월세 착시"].nsmallest(8, "월세착시_순위차")[cols].round(0).to_string(index=False))

    print("\n[C 숨은 효율] 월세는 비싸도 통근부담이 낮아 총부담이 낮은 동 - 순위 상승 상위 8")
    print(valid[valid["부담유형"] == "C 숨은 효율"].nlargest(8, "월세착시_순위차")[cols].round(0).to_string(index=False))

    from scipy.stats import spearmanr
    rho, p = spearmanr(df["표면주거비_원"], df["통합부담_정기권_원"])
    print(f"\n주거비 순위 vs 통합부담 순위 스피어만: {rho:.3f}")
    big = (df["월세착시_순위차"].abs() >= 50).sum()
    print(f"순위가 50계단 이상 바뀐 행정동: {big}개 ({big/len(df)*100:.1f}%)")


def main():
    df = load_and_merge()
    df = build_burden(df)
    df = rank_and_type(df)
    report(df)

    keep = ["행정동코드8", "행정동코드_최종", "시군구명", "행정동명_최종", "권역",
            "표면주거비_원", "표본수", "표본부족",
            "대표_편도통근시간_분", "월_통근시간_시간", "대표_편도환승횟수",
            "월교통비_실지출_원", "월교통비_정기권_원", "정기권_유리", "월시간비용_원",
            "통근부담_실지출_원", "통근부담_정기권_원",
            "통합부담_실지출_원", "통합부담_정기권_원", "주거비_비중", "통근비_비중",
            "순위_주거비", "순위_통합부담", "월세착시_순위차", "부담유형",
            "생활소비부담지수", "반영업종수", "업종부족",
            "내부통근비중", "교통비_산출포함률", "교통비_커버리지부족",
            "주요_출근목적지_목록"]
    out = df[[c for c in keep if c in df.columns]].sort_values("통합부담_정기권_원")
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_PATH} ({len(out)}행)")


if __name__ == "__main__":
    main()