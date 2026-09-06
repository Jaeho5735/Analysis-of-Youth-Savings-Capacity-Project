"""pytest 공통 설정.

모든 테스트 파일이 자동으로 이 파일을 읽는다. import 할 필요 없다.
"""

import sys
from pathlib import Path

import pytest

# 프로젝트 루트. tests/conftest.py 기준 한 단계 위.
ROOT = Path(__file__).resolve().parents[1]

# pytest.ini 의 pythonpath 가 안 먹는 환경(구버전 등)을 위한 이중 안전장치.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_source(path):
    """파이썬 소스를 문자열로 읽는다.

    반드시 utf-8-sig 로 읽는다. 윈도우 편집기가 저장할 때 파일 앞에
    BOM(U+FEFF)을 붙이는 경우가 있는데, 그러면 ast.parse 가
    'invalid non-printable character U+FEFF' 로 실패한다.
    (파이썬 import 는 BOM 을 알아서 걷어내므로 앱은 멀쩡히 돈다.
     즉 앱은 되는데 소스 검사 테스트만 깨지는 상황이 생긴다.)
    utf-8-sig 는 BOM 이 있으면 떼고 없으면 그냥 읽으므로 양쪽 다 안전하다.
    """
    return Path(path).read_text(encoding="utf-8-sig")


@pytest.fixture(scope="session")
def project_root() -> Path:
    """소스 파일을 직접 열어 검사하는 테스트에서 쓴다."""
    return ROOT


@pytest.fixture(scope="session")
def service_source(project_root: Path) -> str:
    """web/service.py 원문. '산식이 한 곳에만 있는가' 류 검사용."""
    return read_source(project_root / "web" / "service.py")


@pytest.fixture(scope="session")
def app_source(project_root: Path) -> str:
    """web/app.py 원문. 호출부 배선 검사용."""
    return read_source(project_root / "web" / "app.py")


@pytest.fixture
def base_input() -> dict:
    """페이지 간 일치 검증에 공통으로 쓰는 입력 한 벌.

    2026-09-06 산식 불일치를 잡았던 실제 케이스(월곡제1동 -> 소공동, 총부담 117.9만).
    여기 값만 바꾸면 일관성 테스트 전체가 같이 움직인다.
    """
    return {
        "home_dong": "월곡제1동",
        "work_dong": "소공동",
        "age": 29,
        "deposit": 10_000_000,
        "rent": 750_000,
        "work_days": 21,
    }
