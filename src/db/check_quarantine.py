"""
적재 시 격리된 행이 실제로 얼마나 손실인지 진단한다.

행 수만 보면 판단할 수 없다. OD는 828행이 빠져도 이동량 비중이 0.01%면 무시해도 되고,
1%가 넘으면 그 지역 통근이 통째로 사라진 것이라 대응이 필요하다.
비중이 기준을 넘으면 화면에 경고를 띄우되, 배분 같은 판단은 사람이 한다.

실행: python src/db/check_quarantine.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
Q_DIR = DATA_DIR / "quarantine"

WARN_PCT = 0.5  # 이 비중을 넘으면 대응 검토 필요

# (격리파일, 원본파일, 비중을 잴 컬럼, 이름 컬럼 후보)
CHECKS = [
    ("fact_commute_od_orphan.csv", "all_age_commute_od_aggregated.csv",
     "출근_이동량", ["거주동 이름", "근무동 이름"]),
    ("fact_commute_route_orphan.csv", "commute_routes_analysis_ready.csv",
     "출근_이동량", ["거주동 이름", "근무동 이름"]),
    ("fact_rent_transaction_orphan.csv", "표면주거비_거래단위.csv",
     None, ["행정동명_최종", "시군구명"]),
    ("fact_dong_burden_orphan.csv", "주거통근_통합부담_행정동별.csv",
     None, ["행정동명_최종"]),
    ("fact_dong_type_orphan.csv", None, None, []),
    ("bridge_district_dong_orphan.csv", None, None, []),
]


def load(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, encoding="utf-8-sig", low_memory=False)


def main():
    if not Q_DIR.exists():
        print(f"격리 폴더 없음: {Q_DIR}")
        print("-> 격리된 행이 하나도 없다는 뜻이다. 정상.")
        return

    print(f"격리 폴더: {Q_DIR}\n")
    verdicts = []

    for q_name, src_name, amount_col, name_cols in CHECKS:
        q = load(Q_DIR / q_name)
        if q is None or len(q) == 0:
            continue

        print("=" * 66)
        print(f"{q_name}   격리 {len(q):,}행")

        # 행 수 비중
        if src_name:
            src = load(DATA_DIR / src_name)
            if src is not None:
                row_pct = len(q) / len(src) * 100
                print(f"  행 수 비중 : {row_pct:.4f}%  ({len(q):,} / {len(src):,})")

                # 이동량 등 총량 비중 - 행 수보다 이쪽이 실제 손실에 가깝다
                if amount_col and amount_col in q.columns and amount_col in src.columns:
                    amt_pct = q[amount_col].sum() / src[amount_col].sum() * 100
                    print(f"  {amount_col} 비중 : {amt_pct:.4f}%")
                    verdicts.append((q_name, amt_pct))
                else:
                    verdicts.append((q_name, row_pct))

        # 어느 행정동 때문인지
        for col in name_cols:
            if col in q.columns:
                vc = q[col].value_counts().head(5)
                if len(vc):
                    print(f"  {col} 상위: " +
                          ", ".join(f"{k}({v:,})" for k, v in vc.items()))
        print()

    if not verdicts:
        print("총량 비중을 잴 수 있는 격리 파일이 없다.")
        return

    print("=" * 66)
    print("판정")
    for name, pct in verdicts:
        if pct >= WARN_PCT:
            print(f"  [검토 필요] {name}: {pct:.4f}%  -> {WARN_PCT}% 이상. 팀 논의 필요")
        else:
            print(f"  [수용 가능] {name}: {pct:.4f}%  -> 문서에 한 줄 기록하고 진행")

    print()
    print("참고: 폐지 행정동(용신동 등)은 신설동·용두동으로 1:N 분동이라")
    print("      이동량을 나눌 근거가 없다. 임의 안분보다 제외 후 기록이 안전하다.")


if __name__ == "__main__":
    main()