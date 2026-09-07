"""P2: 정책 추천 순위 점수가 부담 구성에 맞게 매겨지는지 검사한다.

배경
----
조건 필터(나이·소득·월세)만으로는 개인화가 안 된다.
청년 대상 정책 대부분이 나이와 소득만 보기 때문에
20~39세 구간에서는 거의 같은 목록이 나온다.
"받을 수 있는가"는 조건으로 거르고, "먼저 보여줄 것인가"는 여기서 정한다.

태그
    1 높은 월세 부담   2 높은 보증금 부담   3 높은 통근 교통비
    4 낮은 현금흐름 잔여액   5 자산형성 여력   6 보증금 반환 위험

DB 가 필요 없다. pytest -m "not db" 로도 돈다.
"""

import pytest

from web.service import SEOUL_AVG_COMMUTE_MIN, _support_rank

BASE_SCORE = {1: 3, 2: 2, 3: 2, 4: 1, 5: 0, 6: 0}


def col(total=1_000_000, housing=500_000, commute_min=20, region="서남권"):
    """_col_of 결과 중 _support_rank 가 실제로 보는 부분만 만든다."""
    return {"total": total, "housing": housing,
            "commute_min": commute_min, "region_group": region}


def test_no_column_returns_base_score():
    """비교 기준이 없으면 기본 순서 그대로. 화면이 비지 않게 한다."""
    assert _support_rank(None) == BASE_SCORE


def test_nothing_special_keeps_base_score():
    """주거비 비중도 통근도 평범하면 기본 순서."""
    assert _support_rank(col(), deposit="0", rent="50") == BASE_SCORE


# ── 주거비 비중 ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "housing, total, boosted",
    [
        (700_000, 1_000_000, True),    # 정확히 70%
        (699_999, 1_000_000, False),   # 70% 직전
        (900_000, 1_000_000, True),
    ],
)
def test_housing_share_threshold(housing, total, boosted):
    """주거비가 부담의 70% 이상이면 월세·보증금 지원을 앞으로."""
    s = _support_rank(col(total=total, housing=housing), deposit="0", rent="50")
    assert (s[1] > BASE_SCORE[1]) is boosted
    assert (s[2] > BASE_SCORE[2]) is boosted


# ── 통근시간 ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "minutes, boosted",
    [
        (SEOUL_AVG_COMMUTE_MIN + 0.1, True),
        (SEOUL_AVG_COMMUTE_MIN, False),     # 평균과 같으면 '길다'가 아니다
        (SEOUL_AVG_COMMUTE_MIN - 0.1, False),
        (None, False),                       # 통근 자료 없음
        (60, True),
    ],
)
def test_commute_threshold(minutes, boosted):
    """서울 평균보다 길면 교통 지원을 앞으로.

    임계값을 새로 만들지 않고 이미 화면에 쓰는 기준선을 그대로 쓴다.
    """
    s = _support_rank(col(commute_min=minutes), deposit="0", rent="50")
    assert (s[3] > BASE_SCORE[3]) is boosted


# ── 보증금 대 월세 ──────────────────────────────────────────

def test_deposit_heavier_than_rent():
    """보증금 월환산이 월세보다 크면 보증금 쪽을 앞으로."""
    s = _support_rank(col(), deposit="10000", rent="30")   # 1억 vs 월세 30만
    assert s[2] > BASE_SCORE[2]
    assert s[6] > BASE_SCORE[6]


def test_rent_heavier_than_deposit():
    """월세가 더 크면 보증금 가산이 없어야 한다."""
    s = _support_rank(col(), deposit="1000", rent="80")     # 1천만 vs 월세 80만
    assert s[6] == BASE_SCORE[6]


def test_region_rate_changes_the_verdict():
    """권역별 전환율이 순위 판단에까지 반영되는지.

    2026-09-07 에 _support_rank 만 _deposit_monthly 에 권역을 안 넘겨
    화면은 권역별 전환율, 순위는 전체 중앙값(5.9%)으로 판단하고 있었다.

    보증금 1억 · 월세 47만이 그 차이가 드러나는 구간이다.
        동남권 5.39% -> 월환산 449,167원  (월세보다 작다 -> 가산 없음)
        전체   5.90% -> 월환산 491,667원  (월세보다 크다 -> 가산)
    권역이 반영되지 않으면 이 테스트가 실패한다.
    """
    same = _support_rank(col(region="동남권"), deposit="10000", rent="47")
    assert same[6] == BASE_SCORE[6], (
        "동남권(5.39%) 기준이면 보증금 월환산이 월세보다 작아 가산이 없어야 한다. "
        "가산이 붙었다면 전체 중앙값 5.9% 로 계산하고 있다"
    )

    high = _support_rank(col(region="동북권"), deposit="10000", rent="47")
    assert high[6] > BASE_SCORE[6], (
        "동북권(6.20%) 기준이면 보증금 월환산이 월세보다 커 가산이 붙어야 한다"
    )


# ── 결합 ────────────────────────────────────────────────────

def test_all_conditions_stack():
    """조건이 겹치면 점수도 겹쳐 오른다."""
    s = _support_rank(
        col(total=1_000_000, housing=800_000, commute_min=45),
        deposit="10000", rent="30")
    assert s[1] > BASE_SCORE[1]
    assert s[2] > BASE_SCORE[2] + 2      # 주거비 비중 + 보증금 둘 다
    assert s[3] > BASE_SCORE[3]
    assert s[6] > BASE_SCORE[6]


def test_score_covers_all_tags():
    """여섯 태그가 모두 점수를 받는지.

    태그가 빠지면 _support_items 의 정렬에서 score.get(tag, 0) 이 0 이 되어
    그 태그 정책만 조용히 뒤로 밀린다.
    """
    s = _support_rank(col())
    assert set(s) == {1, 2, 3, 4, 5, 6}


@pytest.mark.parametrize("total", [0, None])
def test_zero_total_does_not_divide(total):
    """총부담이 0 이면 나눗셈을 하지 않아야 한다."""
    s = _support_rank(col(total=total), deposit="1000", rent="50")
    assert s[1] == BASE_SCORE[1]
