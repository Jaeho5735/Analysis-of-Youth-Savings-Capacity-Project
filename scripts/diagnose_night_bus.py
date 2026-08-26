"""
심야버스 경로 분포 진단

Tmap 경로 결과에 심야버스(N61, N51 등)가 1,233건 섞여 있다.
출근 경로일 수 없다. 원인이 둘 중 무엇인지 가른다.

    A. 호출 시각    3만 건을 밤새 돌려 새벽 구간이 심야 경로를 받음
                   -> 파일 앞쪽 특정 구간에 몰려 있을 것
    B. 경로 선택    추천경로 여러 개 중 잘못 고름
                   -> 전 구간에 고르게 흩어져 있을 것

A면 해당 구간만 재조회하면 되고, B면 선택 로직을 고쳐야 한다.

사용법
    python 진단_심야버스.py
"""

import glob
import re
import sys

import pandas as pd

CANDIDATES = [
    "data/**/*commute_routes_analysis_ready*.csv",
    "data/**/*commute_route*.csv",
]
NIGHT = re.compile(r"N\d{2}")


def find_file():
    for pat in CANDIDATES:
        hits = [f for f in glob.glob(pat, recursive=True) if "orphan" not in f]
        if hits:
            return hits[0]
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else find_file()
    if not path:
        print("경로 CSV를 찾지 못했다. 파일 경로를 인자로 넘겨라.")
        return
    print(f"대상: {path}\n")

    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    line_col = "이용노선" if "이용노선" in df.columns else None
    home_col = "거주동 이름" if "거주동 이름" in df.columns else None
    if not line_col:
        print(f"'이용노선' 컬럼이 없다. 전체 컬럼: {list(df.columns)}")
        return

    df = df.reset_index(drop=True)
    df["night"] = df[line_col].astype(str).str.contains(NIGHT, na=False)
    n = int(df["night"].sum())
    print(f"심야버스 포함 {n:,} / 전체 {len(df):,}  ({n / len(df) * 100:.1f}%)\n")
    if n == 0:
        return

    # 1) 행 구간별 분포
    print("=" * 56)
    print("행 구간별 심야버스 비율")
    print("=" * 56)
    df["blk"] = (df.index // 1000) * 1000
    g = df.groupby("blk")["night"].agg(["sum", "count"])
    g["pct"] = (g["sum"] / g["count"] * 100).round(1)
    g = g[g["sum"] > 0]
    for blk, row in g.iterrows():
        bar = "#" * int(row["pct"] / 2)
        print(f"  {blk:>6,}~  {int(row['sum']):>4}건  {row['pct']:>5.1f}%  {bar}")

    # 2) 위치 요약
    idx = df.index[df["night"]]
    print()
    print("=" * 56)
    print("심야버스 행 위치")
    print("=" * 56)
    print(f"  최소 {idx.min():,} / 중앙 {int(idx.to_series().median()):,} / 최대 {idx.max():,}")
    for cut in (5000, 10000, 15000):
        print(f"  상위 {cut:,}행 이내 비율: {(idx < cut).mean() * 100:.1f}%")

    # 3) 판정
    print()
    print("=" * 56)
    print("판정")
    print("=" * 56)
    share = (idx < len(df) * 0.25).mean()
    blocks = len(g)
    total_blocks = df["blk"].nunique()
    print(f"  심야버스가 나타난 구간 {blocks} / 전체 {total_blocks}")
    print(f"  앞 25% 구간에 몰린 비율 {share * 100:.1f}%")
    print()
    if share > 0.7:
        print("  >>> A 가능성 높음 - 호출 시각 문제")
        print("      파일 앞쪽에 집중돼 있다. 해당 구간만 재조회하면 된다.")
    elif blocks > total_blocks * 0.6:
        print("  >>> B 가능성 높음 - 경로 선택 로직")
        print("      전 구간에 흩어져 있다. 재조회보다 선택 기준을 봐야 한다.")
    else:
        print("  >>> 판정 애매. 위 구간별 표를 직접 보고 판단해라.")

    # 4) 영향 범위
    if home_col:
        print()
        print("=" * 56)
        print("영향받은 거주동")
        print("=" * 56)
        vc = df.loc[df["night"], home_col].value_counts()
        print(f"  거주동 {vc.nunique() if hasattr(vc, 'nunique') else len(vc)}개")
        print()
        for name, cnt in vc.head(12).items():
            print(f"    {str(name):16} {cnt:>4}건")

    # 5) 지하철 미사용과 겹치는지
    sub_col = "지하철_이용구간수" if "지하철_이용구간수" in df.columns else None
    if sub_col:
        print()
        print("=" * 56)
        print("지하철 미사용 경로와의 관계")
        print("=" * 56)
        nosub = pd.to_numeric(df[sub_col], errors="coerce").fillna(0) == 0
        print(f"  지하철 미사용 {int(nosub.sum()):,}건 ({nosub.mean() * 100:.1f}%)")
        print(f"  그중 심야버스 포함 {int((nosub & df['night']).sum()):,}건")
        print()
        print("  행 구간별 지하철 미사용 비율")
        df["nosub"] = nosub
        g2 = df.groupby("blk")["nosub"].mean().mul(100).round(1)
        for blk, pct in g2.items():
            bar = "#" * int(pct / 4)
            print(f"    {blk:>6,}~  {pct:>5.1f}%  {bar}")
        print()
        print("  앞 구간만 높으면 호출 시각 문제, 전 구간 고르면 다른 원인이다.")


if __name__ == "__main__":
    main()