"""
주거·통근 통합부담 테이블 산출.

행정동별로 표면주거비와 통근부담(교통비 + 시간 기회비용)을 합산해 하나의 기준으로
비교 가능한 부담 지표를 만든다.

교통비는 두 값을 병기한다. 실지출 기준(원산출)과 정기권 월 상한을 적용한 기준이다.
서울은 정기권 때문에 실제 지역 간 교통비 격차가 크게 눌리므로, 캡을 씌우지 않으면
통근부담이 과대평가된다.

정기권 상한은 코드에 상수로 박지 않고 data/정기권_가정.csv 에서 읽는다. 요금은
정책에 따라 바뀌고 연령별로도 다른데, 상수로 두면 값이 바뀔 때마다 코드를 고쳐야 하고
"이 산출물이 어떤 요금 기준인지"가 파일에 남지 않는다. CSV 를 원천으로 두면 같은 파일을
load_to_db.py 가 dim_transport_pass_assumption 에 그대로 적재하므로 CSV·DB 가 항상
같은 값을 본다. --assumption 으로 시나리오를 바꿔 재산출할 수 있다.

시간 기회비용은 최저임금 기준(10,320원/시간)을 기본으로 하되, 월 통근시간 컬럼에서
언제든 다른 시간가치로 재계산할 수 있도록 시간과 금액을 함께 남긴다.

생활소비부담지수는 금액 산식에 직접 차감하지 않는다(기획안 12-6). 지역 특성 해석과
군집화 입력으로만 쓴다.

입력: data/표면주거비_행정동_통합.csv
      data/commute_burden_by_home_dong.csv
      data/생활소비부담지수_행정동별.csv
      data/행정동_기준코드표.csv
      data/정기권_가정.csv
출력: data/주거통근_통합부담_행정동별.csv

사용:
    python src/analysis/build_total_burden.py                        # 기본 가정(is_default)
    python src/analysis/build_total_burden.py --assumption general   # 시나리오 지정
    python src/analysis/build_total_burden.py --dry-run              # 저장 없이 변동만 확인
    python src/analysis/build_total_burden.py --list                 # 가정 목록 출력
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

SURFACE_PATH = DATA_DIR / "표면주거비_행정동_통합.csv"
# 12번 노트북이 통근부담에 네트워크 지표를 결합한 최종본을 우선 쓴다.
# 없으면 11번 산출물로 물러서되, 그 경우 통근권 변수는 비게 된다.
_COMMUTE_CANDIDATES = ["commute_burden_with_network_metrics.csv", "commute_burden_by_home_dong.csv"]
COMMUTE_PATH = next((DATA_DIR / f for f in _COMMUTE_CANDIDATES if (DATA_DIR / f).exists()),
                    DATA_DIR / _COMMUTE_CANDIDATES[0])
INDEX_PATH = DATA_DIR / "생활소비부담지수_행정동별.csv"
CROSSWALK_PATH = DATA_DIR / "행정동_기준코드표.csv"
ASSUMPTION_PATH = DATA_DIR / "정기권_가정.csv"
OUT_PATH = DATA_DIR / "주거통근_통합부담_행정동별.csv"

HOURLY_VALUE = 10320          # 시간가치 기준(최저임금)
COVERAGE_MIN = 0.7            # 교통비 산출 포함률 하한


def to_code8(s: pd.Series, width: int = 10) -> pd.Series:
    """코드 자릿수를 8자리로 통일한다. 10자리 KIKmix는 앞 8자리가 통계청 코드와 같다."""
    return pd.to_numeric(s, errors="coerce").astype("Int64").astype(str).str.zfill(width).str[:8]


def read_assumptions() -> pd.DataFrame:
    if not ASSUMPTION_PATH.exists():
        sys.exit(f"[중단] {ASSUMPTION_PATH} 이 없습니다. 정기권 가정 없이는 산출할 수 없습니다.")
    a = pd.read_csv(ASSUMPTION_PATH, encoding="utf-8-sig")
    need = {"assumption_code", "assumption_name", "monthly_cap", "is_default"}
    if not need.issubset(a.columns):
        sys.exit(f"[중단] {ASSUMPTION_PATH.name} 필수 컬럼 누락: {need - set(a.columns)}")
    a["monthly_cap"] = pd.to_numeric(a["monthly_cap"], errors="coerce")
    if a["monthly_cap"].isna().any():
        sys.exit("[중단] monthly_cap 에 숫자가 아닌 값이 있습니다.")
    if a["assumption_code"].duplicated().any():
        sys.exit("[중단] assumption_code 가 중복됩니다.")
    return a


def pick_assumption(code: str | None) -> pd.Series:
    """쓸 정기권 가정 1행을 고른다. code 가 없으면 is_default 행을 쓴다."""
    a = read_assumptions()
    if code:
        row = a[a["assumption_code"] == code]
        if row.empty:
            sys.exit(f"[중단] '{code}' 가정이 없습니다. 사용 가능: {', '.join(a['assumption_code'])}")
    else:
        row = a[a["is_default"].astype(int) == 1]
        # 기본값이 0개면 어떤 요금을 쓸지 알 수 없고, 2개 이상이면 실행할 때마다
        # 다른 값이 뽑힐 수 있다. 조용히 하나를 고르지 말고 멈춘다.
        if len(row) != 1:
            sys.exit(f"[중단] is_default=1 인 행이 {len(row)}개입니다. 정확히 1개여야 합니다.")
    r = row.iloc[0]
    print(f"정기권 가정: [{r['assumption_code']}] {r['assumption_name']} "
          f"월 상한 {int(r['monthly_cap']):,}원")
    return r


def load_and_merge() -> pd.DataFrame:
    for p in (SURFACE_PATH, COMMUTE_PATH):
        if not p.exists():
            sys.exit(f"{p} 이 없습니다.")

    surf = pd.read_csv(SURFACE_PATH, encoding="utf-8-sig")
    surf["행정동코드8"] = to_code8(surf["행정동코드_최종"])

    com = pd.read_csv(COMMUTE_PATH, encoding="utf-8-sig")
    com["행정동코드8"] = com["거주동 코드"].astype(str).str.zfill(8)
    drop = [c for c in ["거주동 이름", "거주동 이름_network"] if c in com.columns]
    print(f"통근부담 입력: {COMMUTE_PATH.name}")
    has_net = "동일통근권_내부출근비율" in com.columns
    print(f"  통근권 네트워크 지표: {'포함' if has_net else '없음 - 군집 변수 2종이 비게 됨'}")

    df = surf.merge(com.drop(columns=drop), on="행정동코드8",
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


def build_burden(df: pd.DataFrame, assumption: pd.Series) -> pd.DataFrame:
    cap = int(assumption["monthly_cap"])
    df["표면주거비_원"] = df["표면주거비_중앙값"] * 10000

    # 교통비 결측은 0이 아니라 정기권 상한으로 채운다.
    # 0으로 채우면 "교통비가 전혀 안 드는 동"이 되어 통합부담 순위 최상위로 잘못
    # 올라간다(상암동 사례). 정기권 상한은 어떤 동에서든 지불 가능한 상한이므로
    # 보수적 대체값으로 쓸 수 있다. 대체 여부는 플래그로 남겨 해석에서 걸러낸다.
    fare = pd.to_numeric(df["월_통근교통비_원"], errors="coerce")
    df["교통비_결측대체"] = fare.isna()
    if df["교통비_결측대체"].any():
        print(f"\n[교통비 결측] {df['교통비_결측대체'].sum()}개 동을 정기권 상한 {cap:,}원으로 대체")
    fare = fare.fillna(cap)

    df["월교통비_실지출_원"] = fare
    df["월교통비_정기권_원"] = fare.clip(upper=cap)
    df["정기권_유리"] = fare > cap
    # 어떤 요금 기준으로 산출된 파일인지 산출물 자체에 남긴다
    df["정기권_가정코드"] = assumption["assumption_code"]
    df["정기권_상한_원"] = cap

    # 시간 기회비용: 팀원 산출이 최저임금 기준이므로 그대로 쓰되, 다른 기준 재계산 대비
    df["월시간비용_원"] = df["월_통근시간_시간"] * HOURLY_VALUE

    df["통근부담_실지출_원"] = df["월교통비_실지출_원"] + df["월시간비용_원"]
    df["통근부담_정기권_원"] = df["월교통비_정기권_원"] + df["월시간비용_원"]
    df["통합부담_실지출_원"] = df["표면주거비_원"] + df["통근부담_실지출_원"]
    df["통합부담_정기권_원"] = df["표면주거비_원"] + df["통근부담_정기권_원"]

    df["주거비_비중"] = df["표면주거비_원"] / df["통합부담_정기권_원"]
    df["통근비_비중"] = df["통근부담_정기권_원"] / df["통합부담_정기권_원"]

    df["교통비_커버리지부족"] = df["교통비_산출포함률"] < COVERAGE_MIN
    print(f"교통비 산출 포함률 {COVERAGE_MIN} 미만: {df['교통비_커버리지부족'].sum()}개 (플래그 처리)")
    print(f"정기권 적용 대상(상한 초과): {df['정기권_유리'].sum()}개 / {len(df)}개")
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


def compare_with_existing(df: pd.DataFrame) -> None:
    """기존 산출물과 대조해 가정 변경이 결론을 얼마나 흔드는지 본다."""
    if not OUT_PATH.exists():
        print(f"\n[비교] 기존 {OUT_PATH.name} 이 없어 대조를 건너뜁니다.")
        return
    old = pd.read_csv(OUT_PATH, encoding="utf-8-sig", dtype={"행정동코드8": str})
    if "부담유형" not in old.columns:
        print("\n[비교] 기존 파일에 부담유형이 없어 대조를 건너뜁니다.")
        return

    old_code = old["정기권_가정코드"].iloc[0] if "정기권_가정코드" in old.columns else "미기록(구 62,000 고정)"
    print(f"\n[비교] 기존 산출물 가정: {old_code}  ->  이번 가정: {df['정기권_가정코드'].iloc[0]}")

    m = df[["행정동코드8", "부담유형", "순위_통합부담"]].merge(
        old[["행정동코드8", "부담유형", "순위_통합부담"]],
        on="행정동코드8", how="inner", suffixes=("_new", "_old"))
    print(f"  대조 가능 {len(m)}행")

    print("\n  부담유형 분포 변화")
    cnt = pd.DataFrame({
        "기존": m["부담유형_old"].value_counts(),
        "변경": m["부담유형_new"].value_counts()}).fillna(0).astype(int).sort_index()
    cnt["증감"] = cnt["변경"] - cnt["기존"]
    print(cnt.to_string())

    moved = m[m["부담유형_old"] != m["부담유형_new"]]
    print(f"\n  유형이 바뀐 행정동: {len(moved)}개 ({len(moved)/len(m)*100:.1f}%)")
    if len(moved):
        print(moved.groupby(["부담유형_old", "부담유형_new"]).size()
              .rename("건수").to_string())

    d = (m["순위_통합부담_new"] - m["순위_통합부담_old"]).abs()
    print(f"\n  통합부담 순위 이동: 중앙 {d.median():.0f}계단 / 최대 {d.max():.0f}계단 / "
          f"10계단 이상 {(d >= 10).sum()}개")


def main():
    ap = argparse.ArgumentParser(description="주거·통근 통합부담 산출")
    ap.add_argument("--assumption", help="정기권 가정 코드(미지정 시 is_default 행)")
    ap.add_argument("--dry-run", action="store_true", help="CSV 저장 없이 결과와 변동만 출력")
    ap.add_argument("--list", action="store_true", help="사용 가능한 정기권 가정 목록 출력")
    args = ap.parse_args()

    if args.list:
        print(read_assumptions().to_string(index=False))
        return

    assumption = pick_assumption(args.assumption)
    df = load_and_merge()
    df = build_burden(df, assumption)
    df = rank_and_type(df)
    report(df)
    compare_with_existing(df)

    keep = ["행정동코드8", "행정동코드_최종", "시군구명", "행정동명_최종", "권역",
            "표면주거비_원", "표본수", "표본부족",
            "대표_편도통근시간_분", "월_통근시간_시간", "대표_편도환승횟수",
            "월교통비_실지출_원", "월교통비_정기권_원", "정기권_유리", "월시간비용_원",
            "정기권_가정코드", "정기권_상한_원", "교통비_결측대체",
            "통근부담_실지출_원", "통근부담_정기권_원",
            "통합부담_실지출_원", "통합부담_정기권_원", "주거비_비중", "통근비_비중",
            "순위_주거비", "순위_통합부담", "월세착시_순위차", "부담유형",
            "생활소비부담지수", "반영업종수", "업종부족",
            "내부통근비중", "교통비_산출포함률", "교통비_커버리지부족",
            "주요_출근목적지_목록",
            # 12번 네트워크 지표 - 군집 입력 및 해석용
            "통근권_코드", "동일통근권_내부출근비율", "외부통근권_이동비율",
            "목적지_HHI", "목적지_정규화엔트로피", "유효_목적지수", "최대_목적지비중",
            "출근_유입량", "출근_유출량", "출근_유입유출비", "통근권_대표업무중심지_이름"]
    out = df[[c for c in keep if c in df.columns]].sort_values("통합부담_정기권_원")

    if args.dry_run:
        print(f"\n[dry-run] 저장하지 않았습니다. 적용하려면 --dry-run 없이 다시 실행하세요. ({len(out)}행)")
        return

    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT_PATH} ({len(out)}행)")


if __name__ == "__main__":
    main()
