"""C1 앞단: app.py 가 네 페이지에 같은 인자를 빠짐없이 넘기는지 검사한다.

2026-09-06 배경
--------------
5페이지가 work_days 를 받고도 쓰지 않아 3페이지와 다른 값을 냈다.
같은 사고의 다른 형태는 '아예 안 넘기는 것'이다.
안 넘기면 기본값(None 또는 21)이 조용히 쓰이고 에러도 안 난다.

이 파일은 app.py 소스를 AST 로 읽어 호출부만 본다.
Flask 를 띄우지도, DB 를 켜지도 않으므로 빠르고 어디서나 돈다.
소스는 conftest 의 app_source 픽스처가 utf-8-sig 로 읽어준다(BOM 대응).

실제 계산이 일치하는지(C1 본체)는 픽스처 캡처 후 별도 파일에서 다룬다.
여기서는 '넘기기는 하는가'만 본다. 넘기지도 않으면 계산 비교가 무의미하다.
"""

import ast

import pytest

PAGE_BUILDERS = ["build_page3", "build_page4", "build_page5", "build_page6"]

# 총부담 산식에 직접 들어가는 입력.
# 네 페이지 모두가 반드시 받아야 하며, 하나라도 빠지면 그 페이지만 다른 값이 나온다.
REQUIRED_ARGS = {"deposit", "rent", "work_days", "age"}

# 페이지마다 다르게 넘겨도 되는 인자와 그 이유.
# '다름'을 알고 두는 것과 모르고 두는 것은 다르다.
KNOWN_DIFFERENCES = {
    "depart_time": "3·4페이지만 받는다. 5·6페이지는 안 받으므로 출발시각이 통근시간에 "
                   "영향을 준다면 페이지 간 값이 갈릴 수 있다. 확인 필요",
    "area": "4·5페이지의 탐색 대상 지역. 3·6페이지에는 개념이 없다",
    "dong": "6페이지의 비교 대상 후보. 다른 페이지에는 개념이 없다",
    "carry_qs": "다음 페이지로 입력을 넘기기 위한 쿼리스트링. 계산에 안 쓰인다",
}


@pytest.fixture(scope="module")
def builder_calls(app_source):
    """app.py 안의 build_pageN 호출을 찾아 넘긴 키워드 인자 이름을 모은다.

    반환: {"build_page3": {"residence", "deposit", ...}, ...}
    """
    tree = ast.parse(app_source)
    found = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in PAGE_BUILDERS):
            continue
        names = {kw.arg for kw in node.keywords if kw.arg is not None}
        # 같은 빌더를 여러 번 부르면 합집합으로 본다.
        found.setdefault(func.id, set()).update(names)

    return found


def test_all_builders_are_called(builder_calls):
    """네 페이지 빌더가 모두 app.py 에서 호출되는지.

    호출부가 사라졌다면 그 화면은 시연용 고정 JSON 만 보여주고 있다는 뜻이다.
    """
    missing = [name for name in PAGE_BUILDERS if name not in builder_calls]
    assert not missing, (
        f"{missing} 호출부가 app.py 에 없다. "
        "해당 페이지가 사용자 입력을 무시하고 고정 JSON 만 보여주는 상태일 수 있다"
    )


@pytest.mark.parametrize("builder", PAGE_BUILDERS)
def test_builder_receives_all_calc_args(builder, builder_calls):
    """총부담 산식에 들어가는 인자를 네 페이지가 모두 받는지.

    하나라도 빠지면 그 페이지만 기본값으로 계산해 다른 값을 낸다.
    2026-09-06 사고와 같은 결과가 나오지만 원인은 더 찾기 어렵다.
    """
    if builder not in builder_calls:
        pytest.skip(f"{builder} 호출부 없음. test_all_builders_are_called 참고")

    passed = builder_calls[builder]
    missing = sorted(REQUIRED_ARGS - passed)

    assert not missing, (
        f"app.py 가 {builder} 에 {missing} 를 안 넘긴다.\n"
        f"실제로 넘기는 인자: {sorted(passed)}\n"
        "안 넘기면 기본값이 조용히 쓰여 이 페이지만 다른 총부담이 나온다"
    )


def test_page5_location_args_documented(builder_calls):
    """build_page5 에 base_code / work_code 를 넘기는지 확인해 둔다.

    현재 app.py 는 area·base_place·work_place 만 넘기고 코드는 안 넘긴다.
    따라서 시그니처의 기본값 base_code='11650540', work_code='11680640' 이 항상 쓰인다.
    place 문자열이 동으로 해석되지 않으면 엉뚱한 동 값이 정상처럼 표시될 수 있다.

    이 테스트는 '고쳐라'가 아니라 '이 상태를 알고 있어라'는 뜻이다.
    코드를 넘기도록 바뀌면 여기가 실패하면서 재검토를 강제한다.
    """
    passed = builder_calls.get("build_page5", set())
    code_args = {"base_code", "work_code"} & passed

    assert not code_args, (
        f"build_page5 에 {sorted(code_args)} 를 넘기기 시작했다. "
        "하드코딩 기본값 폴백이 더 이상 안 쓰이는지 확인하고 이 테스트를 갱신할 것"
    )


@pytest.mark.parametrize("arg", sorted(KNOWN_DIFFERENCES))
def test_known_argument_difference(arg, builder_calls):
    """페이지마다 다르게 넘기는 인자의 현재 상태를 기록해 둔다.

    실패시키는 테스트가 아니라 문서 역할이다.
    어느 페이지가 무엇을 받는지 코드에 남겨두면
    나중에 값이 갈렸을 때 원인 후보를 여기서 바로 찾을 수 있다.
    내용은 pytest -rP 로 볼 수 있다.
    """
    receivers = sorted(b for b in PAGE_BUILDERS if arg in builder_calls.get(b, set()))
    print(f"\n[{arg}] 받는 페이지: {receivers or '없음'}"
          f"\n  사유: {KNOWN_DIFFERENCES[arg]}")
