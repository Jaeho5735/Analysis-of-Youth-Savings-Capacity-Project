"""방법론 문서를 검색 단위로 자른다.

왜 헤딩 그대로 자르지 않는가
---------------------------
`디버깅이력_지표산출.md` 는 ### 이 3~5줄짜리 번호 단계로 40개 가까이 있다.
그대로 자르면 조각이 200자짜리가 되어 "무슨 일이 있었는지"만 남고 "왜"가
잘려 나간다. 반대로 ## 단위로 자르면 8KB 짜리가 나와 작은 모델이 못 읽는다.

그래서 ### 로 자르되 작은 조각은 형제끼리 붙이고, 큰 조각만 나눈다.
자를 때는 문단 경계에서만 자르고 표는 절대 쪼개지 않는다. 이 문서들은
표에 결론이 들어 있어서(라운드별 기록, 근무지별 전환점) 표가 반으로
갈리면 조각 양쪽 다 쓸모가 없어진다.

헤딩 경로를 본문 앞에 붙이는 이유
--------------------------------
"### 5. 1차 수정 — 정규화 함수 추가" 만 떼어 놓으면 무엇에 대한 수정인지
알 수 없다. 검색에도 안 걸리고 모델도 맥락을 못 잡는다. 그래서
"디버깅 이력 — 전처리 > 표기 변이 8라운드 > 1차 수정" 을 본문 앞에 싣는다.
"""

import re

MIN_CHARS = 350      # 이보다 작으면 형제 조각과 붙인다
MAX_CHARS = 1400     # 이보다 크면 문단 경계에서 나눈다

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _is_table_line(line):
    return line.lstrip().startswith("|")


def split_markdown(text, doc_id):
    """마크다운 한 편을 조각 목록으로 만든다.

    돌려주는 것: [{"id", "doc", "path", "text", "chars"}, ...]
    """
    # 윈도우 편집기가 붙인 BOM 을 떼지 않으면 첫 줄 "# 제목"이 헤딩으로
    # 인식되지 않아 문서 제목이 통째로 사라진다. 조각만 보면 무슨 문서인지
    # 알 수 없게 되고, 에러는 안 난다. tests/conftest.py 가 utf-8-sig 를
    # 쓰는 것과 같은 이유다.
    text = text.lstrip("\ufeff")
    sections = _split_by_heading(text)
    merged = _merge_small(sections)

    chunks = []
    for sec in merged:
        for body in _split_big(sec["body"]):
            head = " > ".join(sec["path"])
            chunks.append({
                "id": f"{doc_id}#{len(chunks):02d}",
                "doc": doc_id,
                "path": head,
                # 헤딩 경로를 본문 앞에 붙여 조각 하나만 봐도 맥락이 서게 한다.
                "text": f"[{head}]\n{body}".strip(),
                "chars": len(body),
            })
    return chunks


def _split_by_heading(text):
    """헤딩을 만날 때마다 끊고, 그 시점의 헤딩 경로를 기록한다."""
    out, stack, buf, path = [], [], [], []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            out.append({"path": list(path), "body": body,
                        "level": stack[-1] if stack else 1})

    for line in text.replace("\r\n", "\n").split("\n"):
        m = _HEADING_RE.match(line)
        if not m:
            buf.append(line)
            continue
        flush()
        buf = []
        level, title = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1] >= level:
            stack.pop()
            path.pop()
        stack.append(level)
        path.append(title)
    flush()
    return out


def _merge_small(sections):
    """작은 조각을 뒤 형제와 붙인다.

    붙이는 기준은 부모 경로가 같은 것까지다. 다른 ## 아래로 넘어가면
    성격이 다른 내용이 한 조각에 섞인다.
    """
    out = []
    for sec in sections:
        parent = tuple(sec["path"][:-1])
        prev = out[-1] if out else None
        # 앞 조각이 작아서 채워야 하거나, 이번 조각이 작아서 붙을 데가
        # 필요한 경우 둘 다 병합한다. 앞이 큰데 뒤가 작으면 그 작은 조각이
        # 홀로 남는 문제가 있었다.
        joinable = (prev is not None
                    and tuple(prev["path"][:-1]) == parent
                    and (len(prev["body"]) < MIN_CHARS
                         or len(sec["body"]) < MIN_CHARS)
                    and len(prev["body"]) + len(sec["body"]) <= MAX_CHARS)
        if joinable:
            prev["body"] = prev["body"] + "\n\n" + sec["body"]
            # 경로는 공통 조상까지만 남긴다. 두 절을 합쳤으므로
            # 한쪽 소제목만 달아두면 나머지 내용이 그 제목의 것으로 읽힌다.
            prev["path"] = list(parent) or prev["path"][:1]
            continue
        out.append(dict(sec))

    # 몇 글자짜리 잔여 조각은 부모가 달라도 앞 조각에 붙인다.
    # 검색 결과에 올라와 봐야 아무 정보도 주지 못하고 자리만 차지한다.
    tiny = []
    for sec in out:
        if tiny and len(sec["body"]) < 60:
            tiny[-1]["body"] += "\n\n" + sec["body"]
            continue
        tiny.append(sec)
    return tiny


def _split_big(body):
    """큰 조각을 문단 경계에서 나눈다. 표는 쪼개지 않는다."""
    if len(body) <= MAX_CHARS:
        return [body]

    blocks, cur = [], []
    for line in body.split("\n"):
        cur.append(line)
        # 표가 끝나기 전에는 문단 경계로 보지 않는다.
        if line.strip() == "" and not _is_table_line(cur[-2] if len(cur) > 1
                                                    else ""):
            blocks.append("\n".join(cur).strip())
            cur = []
    if cur:
        blocks.append("\n".join(cur).strip())

    out, acc = [], ""
    for b in blocks:
        if not b:
            continue
        if acc and len(acc) + len(b) > MAX_CHARS:
            out.append(acc.strip())
            acc = b
        else:
            acc = f"{acc}\n\n{b}" if acc else b
    if acc.strip():
        out.append(acc.strip())
    return out or [body]
