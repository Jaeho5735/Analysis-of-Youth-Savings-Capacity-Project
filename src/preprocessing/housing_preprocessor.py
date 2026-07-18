"""
전월세 실거래가 CSV 9개 파일 행결합 스크립트
- 대상: 단독다가구/연립다세대/오피스텔(전월세) x 2023/2024/2025
- data 폴더 안의 csv를 모두 찾아 안내문구 헤더를 건너뛰고 하나로 합친다.

주의: 이 스크립트의 출력 파일(전월세_실거래가_통합.csv)도 data 폴더 안에 저장되므로,
      입력 파일을 찾는 glob 패턴이 출력 파일까지 다시 읽어버리지 않도록
      "원본 파일명은 반드시 단독다가구/연립다세대/오피스텔로 시작한다"는 조건으로
      명시적으로 필터링한다. (재실행 시 자기 자신의 결과물을 또 입력으로 읽어버리는
      '자기잠식' 버그 방지)
"""

import glob
import os
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_PATH = DATA_DIR / "전월세_실거래가_통합.csv"

# 국토부 원본 파일은 항상 이 셋 중 하나로 시작한다.
# (파이프라인 자체 산출물인 "전월세_실거래가_통합.csv", "..._행정동.csv" 등은
#  이 접두어로 시작하지 않으므로 자동으로 걸러진다)
VALID_PREFIXES = ("단독다가구", "연립다세대", "오피스텔")


def find_header_row(path: str, encoding: str, max_scan: int = 30) -> int:
    """첫 번째 컬럼이 'NO'인 행을 찾아 그 행 번호(0-indexed)를 반환한다.
    이 행이 실제 데이터의 헤더 행이다."""
    with open(path, encoding=encoding, errors="ignore") as f:
        for i, line in enumerate(f):
            if i > max_scan:
                break
            first_cell = line.split(",")[0].strip().strip('"')
            if first_cell == "NO":
                return i
    raise ValueError(f"헤더 행('NO')을 찾지 못했습니다: {path}")


def read_molit_csv(path: str) -> pd.DataFrame:
    """인코딩을 자동으로 판별하고, 안내문구를 건너뛴 뒤 데이터프레임으로 읽는다."""
    last_error = None
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            header_row = find_header_row(path, enc)
            df = pd.read_csv(path, skiprows=header_row, encoding=enc, low_memory=False)
            df.columns = df.columns.str.strip()
            df["출처파일"] = os.path.basename(path)
            return df
        except (UnicodeDecodeError, ValueError) as e:
            last_error = e
            continue
    raise RuntimeError(f"파일을 읽지 못했습니다: {path}\n마지막 에러: {last_error}")


def main():
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"data 폴더를 찾을 수 없습니다: {DATA_DIR}")

    all_csv = glob.glob(str(DATA_DIR / "*.csv"))
    csv_files = [
        f for f in sorted(all_csv)
        if "~$" not in os.path.basename(f)
        and os.path.basename(f).startswith(VALID_PREFIXES)
    ]
    skipped = sorted(set(all_csv) - set(csv_files))
    if skipped:
        print("아래 파일은 원본 실거래가 파일이 아닌 것으로 판단하여 건너뜁니다"
              "(잠금파일 또는 이 파이프라인의 이전 산출물):")
        for f in skipped:
            print("  -", os.path.basename(f))

    print(f"\n찾은 원본 csv 파일 수: {len(csv_files)}")
    for f in csv_files:
        print(" -", os.path.basename(f))

    if not csv_files:
        print(f"csv 파일을 찾지 못했습니다. {DATA_DIR} 경로를 확인하세요.")
        return

    dfs = []
    for f in csv_files:
        df = read_molit_csv(f)
        print(f"  {os.path.basename(f)}: {len(df)}행, {len(df.columns)}열")
        dfs.append(df)

    merged = pd.concat(dfs, ignore_index=True, sort=False)

    print(f"\n병합 전 각 파일 행 수 합계: {sum(len(d) for d in dfs)}")
    print(f"병합 후 총 행 수: {len(merged)}")
    print(f"병합 후 컬럼 목록: {list(merged.columns)}")

    merged.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()