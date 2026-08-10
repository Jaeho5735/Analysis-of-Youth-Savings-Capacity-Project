"""
data/ 아래 CSV 를 재귀로 훑어 구조와 헤더를 한 번에 보고한다.

하위 폴더 구조를 모르는 상태에서 쓰는 조사용 스크립트라 경로를 고정하지 않는다.
출력이 길어지지 않게 두 단계로 나눈다.
  1) 전체 CSV 목록 - 폴더별로 파일명·행수·컬럼수만
  2) 적재 대상 후보 - 컬럼 전체와 값 예시까지

파일을 통째로 읽지 않고 앞 5행만 보므로 큰 파일도 빠르다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUT_FILE = PROJECT_ROOT / "csv_headers.txt"

# 이 단어가 파일명에 있으면 컬럼 전체를 찍는다. 필요하면 추가하면 된다.
TARGET_KEYWORDS = [
    "기준코드표", "폐지코드", "업무지구", "업무중심성",
    "통합부담", "유형화", "군집",
    "od", "commute", "tmap", "network",
    "청년1인가구", "표면주거비",
]


def read_head(path: Path):
    """인코딩을 자동 판별해 앞 5행만 읽는다."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, nrows=5, encoding=enc), enc
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return e, None
    return None, None


def count_rows(path: Path) -> str:
    try:
        with path.open("rb") as f:
            return f"{sum(1 for _ in f) - 1:,}"
    except Exception:
        return "?"


def is_target(name: str) -> bool:
    low = name.lower()
    return any(k.lower() in low for k in TARGET_KEYWORDS)


def main():
    if not DATA_DIR.exists():
        sys.exit(
            f"[중단] data 폴더가 없다: {DATA_DIR}\n"
            f"        스크립트 위치가 src/db/ 가 맞는지 확인할 것."
        )

    files = sorted(DATA_DIR.rglob("*.csv"))
    files = [f for f in files if not f.name.startswith("~$")]
    if not files:
        sys.exit(f"[중단] {DATA_DIR} 아래에 CSV 가 없다.")

    lines = [f"# 루트: {DATA_DIR}", f"# CSV {len(files)}개", ""]

    # 1) 전체 목록 - 폴더별
    lines.append("#" * 70)
    lines.append("# 1. 전체 CSV 목록")
    lines.append("#" * 70)
    current_dir = None
    targets = []
    for path in files:
        rel_dir = path.parent.relative_to(DATA_DIR)
        if rel_dir != current_dir:
            current_dir = rel_dir
            lines.append("")
            lines.append(f"[ data/{rel_dir} ]" if str(rel_dir) != "." else "[ data/ ]")
        df, enc = read_head(path)
        ncol = len(df.columns) if isinstance(df, pd.DataFrame) else "?"
        mark = " <<< 대상" if is_target(path.name) else ""
        lines.append(f"  {path.name}  |  {count_rows(path)}행  |  {ncol}컬럼{mark}")
        if is_target(path.name):
            targets.append((path, df, enc))

    # 2) 적재 대상 후보만 헤더 상세
    lines.append("")
    lines.append("#" * 70)
    lines.append(f"# 2. 적재 대상 후보 상세 ({len(targets)}개)")
    lines.append("#" * 70)

    for path, df, enc in targets:
        lines.append("")
        lines.append("=" * 70)
        lines.append(f"{path.relative_to(DATA_DIR)}   ({count_rows(path)}행, {enc})")
        if not isinstance(df, pd.DataFrame):
            lines.append(f"  !! 읽기 실패: {df}")
            continue
        for i, col in enumerate(df.columns, 1):
            s = df[col].dropna()
            preview = str(s.iloc[0])[:30] if len(s) else "(비어있음)"
            lines.append(f"  {i:>3}. {col}  |  예: {preview}")

    text = "\n".join(lines)
    print(text)
    OUT_FILE.write_text(text, encoding="utf-8")
    print(f"\n>>> 저장 완료: {OUT_FILE}")


if __name__ == "__main__":
    main()