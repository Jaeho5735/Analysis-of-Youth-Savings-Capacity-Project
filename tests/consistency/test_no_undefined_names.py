"""정적 소스 검사. 코드를 실행하지 않고 파일만 읽어서 문제를 찾는다.

2026-09-07 배경
--------------
1) web/app.py 가 list_work_options 를 import 하지 않은 채 호출하고 있었다.
   NameError 가 나지만 그 줄이 try/except Exception 안이라
   경고 로그만 남기고 전체 동 목록으로 조용히 폴백했다.
   '근무지 자동완성을 갈 수 있는 곳으로 제한한다'는 기능이 한 번도 동작한 적이
   없었는데 화면상으로는 정상으로 보였다.

2) web/app.py 를 편집기로 저장하면서 파일 앞에 BOM 이 붙었다.
   파이썬 import 는 BOM 을 걷어내므로 앱은 정상이지만,
   소스를 읽어 검사하는 도구는 전부 구문 오류로 멈춘다.

이 프로젝트는 DB 조회 실패에 대비해 try/except 로 감싼 곳이 많다.
그 방어가 오타·미import 까지 함께 삼키기 때문에
실행하지 않고 검사하는 단계가 따로 필요하다.
"""

import pytest

pyflakes_api = pytest.importorskip(
    "pyflakes.api", reason="pip install -r requirements-dev.txt 로 pyflakes 설치 필요"
)

# 검사할 소스 폴더. 노트북과 가상환경은 뺀다.
# notebooks/ 는 팀원이 작성한 것이라 이 프로젝트의 수정 대상이 아니다.
TARGET_DIRS = ["web", "src"]

# pyflakes 메시지 중 '반드시 고쳐야 하는 것'.
# 실행 중 예외로 이어지거나 이름이 조용히 가려지는 것만 넣는다.
#
# f-string 누락은 일부러 뺐다. 크래시가 나지 않는데 계속 빨간불이면
# 테스트가 잔소리가 되어 정작 중요한 실패까지 무시하게 된다.
# 대신 아래 참고 출력에 남으므로 눈으로 확인하면 된다.
FATAL_PATTERNS = (
    "undefined name",
    "undefined local",
    "redefinition of unused",
)


class _Collector:
    """pyflakes 결과를 문자열로 모은다."""

    def __init__(self):
        self.warnings = []
        self.errors = []

    def unexpectedError(self, filename, msg):
        self.errors.append(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.errors.append(f"{filename}:{lineno}: 구문 오류 {msg}")

    def flake(self, message):
        self.warnings.append(str(message))


@pytest.fixture(scope="module")
def flakes(project_root):
    collector = _Collector()
    for name in TARGET_DIRS:
        target = project_root / name
        if target.is_dir():
            pyflakes_api.checkRecursive([str(target)], collector)
    return collector


def test_no_syntax_errors(flakes):
    """읽을 수 없는 파일이 없는지. 여기가 깨지면 아래 검사가 무의미하다."""
    assert not flakes.errors, "구문 오류:\n  " + "\n  ".join(flakes.errors)


def test_no_undefined_names(flakes):
    """정의되지 않은 이름을 쓰는 곳이 없는지.

    이게 실패하면 대부분 import 누락이거나 오타다.
    try/except 안에 있으면 실행 중에는 조용히 넘어가므로
    화면이 멀쩡해 보여도 기능이 죽어 있을 수 있다.
    """
    fatal = [
        w for w in flakes.warnings
        if any(p in w.lower() for p in FATAL_PATTERNS)
    ]
    assert not fatal, (
        "정의되지 않은 이름이 있다. import 누락이나 오타를 확인할 것.\n"
        "try/except 안이면 실행 중에 조용히 폴백하므로 화면만 보고는 못 찾는다.\n"
        "  " + "\n  ".join(fatal)
    )


def test_no_bom_in_python_sources(project_root):
    """파이썬 소스 앞에 BOM 이 붙어 있지 않은지.

    파이썬 import 는 BOM 을 걷어내므로 앱은 정상 동작한다.
    그래서 눈치채기 어렵지만, 소스를 문자열로 읽어 다루는 도구
    (ast.parse, 일부 린터, git diff 도구)는 여기서 멈춘다.

    윈도우에서 제거:
      $p="web\\app.py"
      $c=Get-Content $p -Raw -Encoding UTF8
      [IO.File]::WriteAllText((Resolve-Path $p), $c.TrimStart([char]0xFEFF),
                              (New-Object Text.UTF8Encoding $false))
    """
    offenders = []
    for name in TARGET_DIRS:
        target = project_root / name
        if not target.is_dir():
            continue
        for path in target.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            if path.read_bytes()[:3] == b"\xef\xbb\xbf":
                offenders.append(str(path.relative_to(project_root)))

    assert not offenders, (
        "파일 앞에 BOM 이 붙어 있다. 앱은 돌지만 소스를 읽는 도구가 멈춘다.\n"
        "  " + "\n  ".join(offenders)
    )


def test_flakes_summary_visible(flakes):
    """치명적이지 않은 지적은 실패시키지 않고 출력으로만 남긴다.

    미사용 import, f-string 누락, 안 쓰는 지역변수 등이 여기 들어온다.
    전부 실패로 만들면 테스트가 잔소리가 되지만,
    안 보이게 두면 그 안에 섞인 진짜 문제를 놓친다.
    pytest -rP 또는 -s 로 내용을 볼 수 있다.
    """
    minor = [
        w for w in flakes.warnings
        if not any(p in w.lower() for p in FATAL_PATTERNS)
    ]
    if minor:
        print("\n[참고] 치명적이지 않은 pyflakes 지적 "
              f"{len(minor)}건:\n  " + "\n  ".join(minor))
