"""방법론 문서 검색.

왜 임베딩이 아니라 BM25 부터인가
-------------------------------
문서가 네 편, 조각이 40여 개다. 이 규모에서 임베딩은 얻는 것보다 드는 것이
많다 — 모델을 하나 더 받아야 하고, CPU 에서 색인을 다시 만들어야 하며,
왜 그 조각이 나왔는지 설명할 수 없다.

BM25 는 점수의 근거가 "어떤 단어가 몇 번 맞았는가"라 디버깅이 된다.
챗봇 답변이 이상할 때 검색이 문제인지 모델이 문제인지 갈라내야 하는데,
설명되지 않는 검색기를 쓰면 그 구분이 불가능해진다.

임베딩은 이 위에 얹어 같은 골든셋으로 비교하는 것이 순서다.
먼저 재는 도구를 세운다.

한국어 토큰화
------------
형태소 분석기를 쓰지 않는다. 의존성이 늘고, 이 문서들은 "전월세전환율",
"가운뎃점", "동명이인" 같은 복합 명사가 많아 분석기가 오히려 쪼갠다.
대신 글자 2-gram 을 쓴다. "전월세전환율"은 "전월/월세/세전/전환/환율"로
갈려서, 사용자가 "전환율"만 쳐도 "환율"과 "전환"이 맞는다.
"""

import json
import math
import re
from pathlib import Path

K1 = 1.5     # 단어 빈도 포화. 같은 단어가 여러 번 나와도 점수가 무한히 안 커진다
B = 0.75     # 문서 길이 보정

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_HANGUL_RE = re.compile(r"[가-힣]+")

# 질문의 기능어를 지운다.
#
# "혼잡도는 어떻게 계산했나요?" 를 그대로 넣었더니 혼잡도를 다루지 않는
# 문서가 1위로 나왔다. 맞은 조각이 "어떻", "떻게" 뿐이었다. 이런 말은
# 문서에 드물게 나타나서 IDF 가 높게 잡히는데, 정작 의미는 없다.
# 드물지만 무의미한 단어가 점수를 지배하는 상태였다.
#
# 지우고 나면 관련 문서가 없는 질문은 점수가 0 근처로 떨어져서,
# "문서에 근거가 없다"를 판정할 수 있게 된다.
_QUESTION_WORDS = (
    "어떻게", "어떤", "어디", "언제", "누가", "무엇", "무슨", "왜",
    "인가요", "있나요", "하나요", "했나요", "되나요", "인지", "는지",
    "알려줘", "설명해줘", "말해줘", "궁금해", "하는", "해야",
    "그래서", "이거", "저거", "그거", "좀",
)
_STRIP_RE = re.compile("|".join(sorted(_QUESTION_WORDS, key=len,
                                       reverse=True)))


def tokenize(text, is_query=False):
    """영문·숫자는 단어로, 한글은 글자 2-gram 으로 자른다.

    is_query 면 질문의 기능어를 먼저 지운다. 문서 쪽에는 적용하지 않는다.
    문서 본문의 "어떻게"는 설명의 일부라 지울 이유가 없다.
    """
    text = (text or "").lower()
    if is_query:
        text = _STRIP_RE.sub(" ", text)
    toks = _WORD_RE.findall(text)
    for run in _HANGUL_RE.findall(text):
        if len(run) == 1:
            toks.append(run)
        else:
            toks += [run[i:i + 2] for i in range(len(run) - 1)]
    return toks


class DocSearch:
    """조각 목록을 받아 BM25 로 검색한다."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.tokens = [tokenize(c["text"]) for c in self.chunks]
        self.lens = [len(t) for t in self.tokens]
        self.avg_len = (sum(self.lens) / len(self.lens)) if self.lens else 1.0

        self.tf = []
        df = {}
        for toks in self.tokens:
            counts = {}
            for t in toks:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1

        n = max(len(self.chunks), 1)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5))
                    for t, d in df.items()}

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["chunks"])

    def search(self, query, k=4, min_score=3.0, min_hits=2):
        """질문에 맞는 조각을 점수순으로 돌려준다.

        점수와 맞은 단어를 함께 준다. 답변이 이상할 때 "검색이 엉뚱한 걸
        가져왔는지"를 눈으로 확인할 수 있어야 한다.

        min_score 아래는 버린다. 빈 목록이 나오면 그 질문은 문서에 근거가
        없다는 뜻이고, 챗봇은 지어내지 말고 모른다고 답해야 한다.
        점수가 낮아도 뭔가는 돌려주는 검색기는 환각의 재료를 만든다.

        min_hits 는 서로 다른 질문 조각이 몇 개나 맞아야 하는지다.
        "오늘 점심 뭐 먹지?"가 "오늘" 하나로 문서에 걸린 적이 있다.
        한 조각만 우연히 맞는 것은 관련성이 아니다.
        """
        q = tokenize(query, is_query=True)
        if not q:
            return []

        scored = []
        for i, counts in enumerate(self.tf):
            score, hits = 0.0, {}
            for t in q:
                f = counts.get(t)
                if not f:
                    continue
                norm = 1 - B + B * (self.lens[i] / self.avg_len)
                s = self.idf.get(t, 0.0) * (f * (K1 + 1)) / (f + K1 * norm)
                score += s
                hits[t] = hits.get(t, 0) + f
            need = min(min_hits, len(set(q)))
            if score > min_score and len(hits) >= need:
                scored.append((score, i, hits))

        scored.sort(key=lambda x: -x[0])
        out = []
        for score, i, hits in scored[:k]:
            c = dict(self.chunks[i])
            c["score"] = round(score, 3)
            c["hits"] = sorted(hits, key=lambda t: -hits[t])[:8]
            out.append(c)
        return out
