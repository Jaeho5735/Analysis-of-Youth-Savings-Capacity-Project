"""C4: _monthly 가 days·cap 을 인자로만 받는지 검사한다.

2026-09-06 배경
--------------
같은 총부담 계산이 세 군데(3페이지 / 4·6페이지 / 5페이지)에 따로 적혀 있었고
각자 다른 days·cap 을 쓰고 있어서 같은 입력에 다른 값이 나왔다.
해소책으로 `_monthly(b, days, cap)` 하나로 합쳤다.

규약의 범위
----------
"어떤 상수도 읽지 마라"가 아니다. 그렇게 만들면 호출부마다 인자가 늘어나고
'빼먹을 수 있는 자리'가 함께 늘어난다. 그게 애초에 사고의 원인이었다.

인자로 받아야 하는 것은 **호출 맥락마다 달라지는 값**뿐이다.
  days -> 사용자 입력(출근일수)
  cap  -> 나이에 따라 변함(정기권 상한)

반대로 프로젝트 전체에서 하나로 확정된 파라미터는 모듈 상수로 두는 편이 안전하다.
다만 그런 상수는 **다른 곳에 같은 값이 또 정의돼 있지 않은지**를 따로 감시해야 한다.
(2026-09-06 전월세전환율 3.48% 건이 정확히 그 유형이었다.)

이 파일은 함수를 호출하지 않고 소스를 AST 로 뜯어보므로 DB 도 데이터도 필요 없다.
"""

import ast
import builtins
import inspect
import textwrap

import pytest

from web import service

BUILTIN_NAMES = set(dir(builtins))

# _monthly 이 읽어도 되는 모듈 상수와 그 이유.
# 여기 없는 상수를 읽기 시작하면 테스트가 실패하면서 검토를 강제한다.
ALLOWED_MODULE_CONSTANTS = {
    "TIME_VALUE_PER_HOUR": (
        "시간가치 시급. 최저임금 기준 단일 확정값이라 호출 맥락에 따라 달라지지 않는다. "
        "다만 DB dim_time_value 에도 같은 값이 있으므로 정합성을 따로 감시한다."
    ),
}

# 프로젝트 확정 파라미터. 값이 바뀌면 DB dim_time_value 와 문서도 함께 바뀌어야 한다.
EXPECTED_TIME_VALUE = 10320


def _func_ast(fn):
    """함수 하나의 소스를 AST 로 파싱해 FunctionDef 노드를 돌려준다."""
    src = textwrap.dedent(inspect.getsource(fn))
    node = ast.parse(src).body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)), (
        f"{fn.__name__} 의 소스를 함수 정의로 파싱하지 못했다"
    )
    return node


def _bound_names(node):
    """함수 안에서 '만들어지는' 이름 전부.

    인자, 대입 변수, for 변수, with ... as, 컴프리헨션 변수, 중첩 함수명, import 명.
    이 목록에 없는 이름을 읽고 있다면 바깥에서 가져오는 것이다.
    """
    names = set()

    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        names.add(arg.arg)
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)

    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            names.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        elif isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names.add(alias.asname or alias.name.split(".")[0])

    return names


def _free_names(node):
    """함수가 바깥에서 읽어오는 이름. 내장 이름은 뺀다."""
    bound = _bound_names(node)
    used = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }
    return used - bound - BUILTIN_NAMES


def test_monthly_reads_only_allowed_constants():
    """_monthly 이 허용목록 밖의 모듈 상수를 읽지 않는지.

    헬퍼 함수 호출은 허용한다. 규약은 '아무것도 안 부른다'가 아니라
    '맥락마다 달라지는 값을 함수 안에서 집어오지 않는다'이다.
    따라서 바깥에서 읽어온 이름 중 호출 가능하지 않은 것(숫자·딕셔너리 등)만 본다.
    """
    node = _func_ast(service._monthly)

    offenders = []
    for name in sorted(_free_names(node)):
        if name in ALLOWED_MODULE_CONSTANTS:
            continue
        value = getattr(service, name, None)
        if value is None:
            # 모듈에 없는 이름이면 다른 스코프에서 온 것이므로 여기서 판단하지 않는다.
            continue
        if not callable(value):
            offenders.append(f"{name} = {value!r}")

    assert not offenders, (
        "_monthly 이 허용목록에 없는 모듈 상수를 읽고 있다.\n"
        "호출 맥락마다 달라지는 값이면 days·cap 처럼 인자로 받을 것.\n"
        "프로젝트 확정 파라미터라면 ALLOWED_MODULE_CONSTANTS 에 이유와 함께 추가할 것.\n"
        "위반 목록:\n  " + "\n  ".join(offenders)
    )


def test_monthly_signature_is_explicit():
    """_monthly 시그니처가 (b, days, cap) 세 인자를 명시적으로 받는지.

    days 나 cap 에 기본값이 생기면 '안 넘기면 조용히 기본값으로 돈다'가 되어
    2026-09-06 사고와 같은 구조가 다시 만들어진다.
    """
    sig = inspect.signature(service._monthly)
    params = list(sig.parameters.values())

    assert [p.name for p in params] == ["b", "days", "cap"], (
        f"_monthly 시그니처가 바뀌었다: {sig}"
    )

    defaulted = [p.name for p in params if p.default is not inspect.Parameter.empty]
    assert not defaulted, (
        f"{defaulted} 에 기본값이 생겼다. 호출부가 인자를 빼먹어도 에러가 안 나므로 "
        "페이지마다 다른 값이 나올 수 있다. 기본값 없이 항상 명시적으로 넘길 것"
    )


def test_time_value_constant_locked():
    """시간가치가 최저임금 기준 확정값 그대로인지.

    이 값을 바꾸려면 DB dim_time_value, 뷰 v_dong_burden 결과,
    방법론 문서, 발표 수치가 전부 함께 움직여야 한다.
    한쪽만 바꾸는 것을 막기 위해 여기에 못을 박는다.
    """
    assert service.TIME_VALUE_PER_HOUR == EXPECTED_TIME_VALUE, (
        f"시간가치가 {EXPECTED_TIME_VALUE} -> {service.TIME_VALUE_PER_HOUR} 로 바뀌었다. "
        "DB dim_time_value 와 문서도 함께 갱신됐는지 확인할 것"
    )


def test_time_value_literal_appears_once(service_source):
    """10320 이라는 숫자가 소스에 상수 정의 딱 한 번만 나오는지.

    같은 값을 여러 곳에 직접 적어두면 한 곳만 고쳤을 때 조용히 어긋난다.
    2026-09-06 전월세전환율 3.48% 건이 이 유형이었다.
    """
    tree = ast.parse(service_source)
    hits = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == EXPECTED_TIME_VALUE
    ]

    assert len(hits) == 1, (
        f"{EXPECTED_TIME_VALUE} 가 소스에 {len(hits)}번 나온다 "
        f"(등장 줄: {[n.lineno for n in hits]}). "
        "TIME_VALUE_PER_HOUR 상수 하나만 두고 나머지는 그 상수를 참조할 것"
    )


@pytest.mark.parametrize(
    "fn_name, param, expected_hazard",
    [
        ("_diagnosis_cards", "work_days", 21),
        ("recommend_dongs", "work_days", 21),
        ("_col_of", "cap", None),
        ("build_page5", "base_code", "11650540"),
        ("build_page5", "work_code", "11680640"),
    ],
)
def test_known_silent_default_is_documented(fn_name, param, expected_hazard):
    """호출부가 인자를 빼먹었을 때 조용히 쓰이는 기본값 목록.

    이 테스트는 '기본값을 없애라'가 아니라 '목록을 알고 있어라'는 뜻이다.
    기본값이 사라지거나 값이 바뀌면 여기가 실패하면서 검토를 강제한다.

    각 항목이 위험한 이유:
      _diagnosis_cards.work_days / recommend_dongs.work_days
          -> 사용자가 출근일수를 바꿔도 그 화면만 21일로 계산된다(어제 5페이지와 같은 증상)
      _col_of.cap
          -> None 일 때 함수 안에서 상수를 대체값으로 읽으면 _monthly 통합이 절반만 된 것
      build_page5.base_code / work_code
          -> 코드 전달이 끊겨도 엉뚱한 동 값이 정상처럼 표시된다(5페이지만 있는 폴백)
    """
    fn = getattr(service, fn_name)
    sig = inspect.signature(fn)

    assert param in sig.parameters, f"{fn_name} 에 {param} 인자가 없어졌다"

    actual = sig.parameters[param].default
    assert actual == expected_hazard, (
        f"{fn_name}({param}=) 기본값이 {expected_hazard!r} -> {actual!r} 로 바뀌었다. "
        "의도한 변경이면 이 테스트의 기대값을 같이 고칠 것"
    )
