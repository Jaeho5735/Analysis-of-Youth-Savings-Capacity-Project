"""
SQL 파일 실행 유틸.

PowerShell 은 `<` 리다이렉션을 지원하지 않고 mysql 클라이언트가 PATH 에 없는 경우도
있어서, .env 접속 정보로 직접 SQL 파일을 실행한다.

사용:
    python src/db/run_sql.py sql/init/03_transport_pass_assumption.sql
    python src/db/run_sql.py sql/qc/02_qc_transport_pass.sql
"""
from __future__ import annotations
import os, sys, re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def engine():
    for k in ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB"):
        if not os.getenv(k):
            sys.exit(f"[중단] 환경변수 {k} 없음 (.env 확인)")
    url = (f"mysql+pymysql://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}"
           f"@{os.getenv('MYSQL_HOST','localhost')}:{os.getenv('MYSQL_PORT','3306')}"
           f"/{os.getenv('MYSQL_DB')}?charset=utf8mb4")
    return create_engine(url, pool_pre_ping=True)


def split_statements(sql: str) -> list[str]:
    """주석과 빈 줄을 제거하고 세미콜론으로 문장을 나눈다."""
    lines = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(re.sub(r"\s+--\s.*$", "", line))
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def main():
    if len(sys.argv) < 2:
        sys.exit("사용: python src/db/run_sql.py <sql파일>")

    path = Path(sys.argv[1])
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        sys.exit(f"[중단] 파일 없음: {path}")

    stmts = split_statements(path.read_text(encoding="utf-8"))
    print(f"{path.name}: {len(stmts)}개 문장\n")

    eng = engine()
    failed = 0
    with eng.connect() as conn:
        for i, s in enumerate(stmts, 1):
            head = " ".join(s.split())[:70]
            try:
                result = conn.execute(text(s))
                conn.commit()
                if result.returns_rows:
                    rows = result.fetchall()
                    cols = list(result.keys())
                    print(f"[{i}] {head}")
                    for r in rows:
                        print("    " + " | ".join(
                            f"{c}={v}" for c, v in zip(cols, r)))
                else:
                    print(f"[{i}] {head}  -> OK")
            except Exception as e:
                failed += 1
                print(f"[{i}] {head}\n    !! 실패: {str(e).splitlines()[0][:160]}")

    print(f"\n완료: 성공 {len(stmts)-failed} / 실패 {failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()