"""
scrapers 공통 유틸리티
- 투찰마감이 설정된 기간(MIN~MAX일) 안에 있는 공고만 통과시키는 함수
"""

import re
from datetime import datetime

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import MIN_DAYS_UNTIL_DEADLINE, MAX_DAYS_UNTIL_DEADLINE, POST_DEADLINE_TRACK_DAYS, HOME_CITY, HOME_PROVINCE, GYEONGGI_OTHER_CITIES, EXCLUDE_REGION_KEYWORDS, ALWAYS_INCLUDE_ORGS

import time
import requests


def get_with_retry(url, params=None, headers=None, timeout=30, retries=2, backoff=3):
    """일시적인 타임아웃/연결 오류에 대비해 몇 번 재시도하는 GET 요청."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(backoff)
    raise last_error


def parse_deadline(deadline_text: str):
    """'2026-08-11 12:00', '20260811 1200' 등 다양한 형식에서 날짜만 뽑아 datetime으로 변환.
    파싱 실패 시 None 반환."""
    if not deadline_text:
        return None
    m = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", str(deadline_text))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def is_deadline_in_range(deadline_text: str) -> bool:
    """투찰마감 기준으로 목록에 남길지 판단.
    - 아직 마감 전이면: 남은 일수가 MIN~MAX일 사이여야 함 (너무 임박/너무 먼 것 제외)
    - 이미 마감이 지났으면: POST_DEADLINE_TRACK_DAYS일 이내까지는 남겨둠 (개찰 결과 확인용)
    마감일을 파싱할 수 없으면 일단 통과시킴 (걸러내지 않음)."""
    d = parse_deadline(deadline_text)
    if d is None:
        return True
    days_left = (d - datetime.now()).days
    if days_left >= 0:
        return MIN_DAYS_UNTIL_DEADLINE <= days_left <= MAX_DAYS_UNTIL_DEADLINE
    else:
        return abs(days_left) <= POST_DEADLINE_TRACK_DAYS


def bid_status(deadline_text: str) -> str:
    """공고의 현재 상태를 '진행중' / '개찰대기' / '마감' 중 하나로 반환.
    (실제 낙찰 결과가 붙었는지는 별도 필드(result)로 표시하며, 이 함수는 시간 기준 상태만 판단)"""
    d = parse_deadline(deadline_text)
    if d is None:
        return "진행중"
    days_left = (d - datetime.now()).days
    if days_left >= 0:
        return "진행중"
    return "마감"


def is_eligible_region(region_text: str, org_text: str = "", title_text: str = "") -> bool:
    """용인시 소재 업체가 이 공고에 실제로 입찰 참가 가능한지 판단.

    참가 가능:
      - 지역 정보가 비어있음 (=지역제한 없음, 전국 대상으로 간주)
      - "전국" 명시
      - "용인" 명시
      - "경기도"라고만 되어있고, 용인이 아닌 다른 경기도 시·군이 안 붙어있는 경우
        (=경기도 전체 대상 공고)
      - 한전/철도공사 등 전국구 발주기관 (ALWAYS_INCLUDE_ORGS)

    참가 불가:
      - "경기도 안양시"처럼 용인이 아닌 다른 경기도 시·군이 명시된 경우
      - 다른 광역시/도(부산, 강원, 충북 등)가 명시된 경우
    """
    region_text = region_text or ""
    org_text = org_text or ""
    title_text = title_text or ""
    combined = region_text + " " + org_text + " " + title_text

    if any(o in org_text for o in ALWAYS_INCLUDE_ORGS):
        return True
    if HOME_CITY in region_text:
        return True
    if "전국" in region_text:
        return True
    if any(city in combined for city in GYEONGGI_OTHER_CITIES):
        # 용인이 아닌 다른 경기도 시·군이 특정되어 있으면 참가 불가
        return False
    if any(k in combined for k in EXCLUDE_REGION_KEYWORDS):
        # 경기도 밖 다른 광역시/도가 특정되어 있으면 참가 불가
        return False
    if HOME_PROVINCE in region_text:
        # "경기도"만 있고 특정 시·군은 없음 = 경기도 전체 대상
        return True
    if not region_text:
        # 지역 정보 자체가 없음 = 전국 대상으로 간주
        return True
    return False
