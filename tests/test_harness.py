"""카나리아 테스트.

실제 로직을 검증하지 않는다. '테스트 환경이 프로젝트 코드를 볼 수 있는가'만 본다.
여기가 깨지면 아래 테스트를 아무리 잘 써도 전부 무의미하므로 제일 먼저 통과시킨다.
"""

import importlib

import pytest


def test_project_root_found(project_root):
    """루트를 제대로 찾았는지. web/ 과 src/ 가 보여야 한다."""
    assert (project_root / "web").is_dir()
    assert (project_root / "src").is_dir()


@pytest.mark.parametrize(
    "module_name",
    [
        "web.service",
        "web.app",
        "src.db.query_dong",
    ],
)
def test_module_imports(module_name):
    """import 만으로 DB 접속을 시도하는 모듈이 없는지도 같이 걸러진다.

    import 시점에 커넥션을 열면 DB 없는 환경에서 여기서 터진다.
    그런 모듈이 있으면 조회 계층을 함수 안으로 미루는 리팩터링이 먼저다.
    """
    importlib.import_module(module_name)


def test_service_has_single_monthly():
    """_monthly 가 존재하고 호출 가능한지.

    1순위 일관성 테스트가 전부 이 함수 위에 서므로 여기서 먼저 확인한다.
    """
    from web import service

    assert callable(getattr(service, "_monthly", None)), (
        "_monthly 이 없다. 2026-09-06 산식 통합이 되돌려졌는지 확인할 것"
    )
