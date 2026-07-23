"""
행정동명 표기 정규화 공용 유틸.

여러 스크립트(resolve_precise_jibun.py, calc_consumption_burden_index.py)에서
API/외부 데이터의 행정동명 표기('제' 유무, 마침표<->물음표 인코딩 손상 등)를
KIKmix 공식 표기로 되돌리는 데 동일한 로직이 필요해서 여기 하나로 모았다.
전에는 두 파일에 같은 코드를 복제해서, 정규식을 고칠 때마다 두 곳을 다 고쳐야
하는 유지보수 비용이 있었다.

사용법:
  from utils.dong_names import normalize_dong_name, load_official_ref, fix_encoding_artifacts
"""

import re
from pathlib import Path

import pandas as pd


def load_official_ref(path: Path) -> pd.DataFrame:
    """dong_matcher.py가 만든 공식 행정동 참조표를 읽는다.
    컬럼: 시군구명, 행정동명, 행정동코드"""
    return pd.read_csv(path, encoding="utf-8-sig", dtype={"행정동코드": str})


def fix_encoding_artifacts(value: str) -> str:
    """원본 파일의 인코딩 손상으로 마침표(.)가 물음표(?)로 깨진 경우를 되돌린다.
    (?<=\\d)\\?(?=\\d) 형태의 lookahead/lookbehind를 써서, "1?2?3?4"처럼 물음표가
    연달아 있어도 숫자를 소모하지 않고 전부 독립적으로 치환한다."""
    if not value or not isinstance(value, str):
        return value
    return re.sub(r"(?<=\d)\?(?=\d)", ".", value)


def normalize_dong_name(value: str, official_set: set) -> str:
    """행정동명 표기를 공식 목록 기준으로 되돌린다.
    1) 시/도·구가 붙어있으면 마지막 단어(동 이름)만 남긴다
    2) 인코딩 손상(?->.)을 되돌린다
    3) 공식 목록과 대조해 '제' 유무를 자동으로 보정한다
       (동마다 '제'가 붙는지 여부가 다 달라서, 일괄 규칙이 아니라 목록과 직접 대조한다)
    """
    if not value or not isinstance(value, str):
        return value

    value = fix_encoding_artifacts(value)
    candidate = value.strip().split()[-1]

    if candidate in official_set:
        return candidate

    # '제'가 없는데 공식 명칭엔 있는 경우: '가양1동'->'가양제1동', '성수1가1동'->'성수1가제1동',
    # '금호2.3가동'->'금호제2.3가동' (숫자/점/가 조합까지 처리)
    inserted = re.sub(r"^(.+?)([\d.]+가?동)$", r"\1제\2", candidate)
    if inserted in official_set:
        return inserted

    # '제'가 있는데 공식 명칭엔 없는 경우: '가양제1동'->'가양1동'
    stripped = re.sub(r"제([\d.]+가?동)$", r"\1", candidate)
    if stripped in official_set:
        return stripped

    return candidate  # 공식 목록에서도 못 찾으면 원래 형태 그대로 (수동 확인 필요)