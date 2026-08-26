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


def deadline_sort_key(deadline_text) -> str:
    """정렬 전용 키. 소스마다 마감일시 표기 형식이 다릅니다
    (예: 나라장터 "2026-08-20 09:00", D2B "202608200900" 처럼 구분자 유무가 다름).
    main.py에서 여러 소스를 한꺼번에 문자열로 정렬하면 형식이 섞여서 마감이 이른
    순서대로 정확히 정렬되지 않을 수 있어서, 숫자가 아닌 문자(-, :, 공백 등)를 모두
    제거해 자리수를 통일한 순수 숫자 문자열로 변환합니다. 이렇게 하면 형식이 달라도
    항상 같은 기준(연월일시분...)으로 사전식 비교가 가능해집니다."""
    return re.sub(r"\D", "", str(deadline_text or ""))


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


def get_region_scope(region_text: str, org_text: str = "", title_text: str = "",
                      has_region_restriction=None):
    """용인시 소재 업체가 이 공고에 실제로 입찰 참가 가능한 범위를 판단.

    반환값: "용인" | "경기" | "전국" | None(참가불가/판단불가)

    2026-08-24: 예전엔 True/False만 반환했는데, 대시보드에서 "용인만"/"경기도만"/
    "전국만"을 독립적으로 켜고 끌 수 있게 해달라는 요청으로 범위까지 반환하도록
    바꿨습니다. 판단 기준 자체는 그대로입니다:

    "용인": "용인" 명시
    "경기": "경기도"라고만 되어있고, 용인이 아닌 다른 경기도 시·군이 안 붙어있는 경우
            (=경기도 전체 대상 공고)
    "전국": 지역 정보가 비어있음 / "전국" 명시 / 한전·철도공사 등 전국구 발주기관
            (ALWAYS_INCLUDE_ORGS)
    None (참가 불가):
      - "경기도 안양시"처럼 용인이 아닌 다른 경기도 시·군이 명시된 경우
      - 다른 광역시/도(부산, 강원, 충북 등)가 명시된 경우
      - "서울"만 있는 경우도 여기 포함됩니다 - 경기/용인과는 별개 지역이라
        굳이 용인/경기도/전국 셋 중 하나로 억지로 분류하지 않고, 대시보드
        지역 드롭다운에서 "서울"을 직접 선택해 따로 찾아보도록 남겨둡니다.

    2026-08-24: "인천광역시,경기도"처럼 참가가능지역이 여러 개 나열된 공고(=그중
    아무 지역에서나 등록된 업체면 참가 가능한 OR 조건)가, EXCLUDE_REGION_KEYWORDS에
    걸리는 다른 지역이 하나라도 같이 적혀있으면 무조건 참가불가로 처리되고 있었다
    (경쟁 서비스 대박낙찰정보와 대조해서 발견 - 예: "26-M-포상진지 통신공사(3091)"
    같은 D2B 공고가 거기선 정상적으로 뜨는데 여기선 빠짐). 실제로는 나열된 지역 중
    "경기"가 포함되어 있으면 참가 가능한 것이므로, "경기" 매칭을
    EXCLUDE_REGION_KEYWORDS 검사보다 먼저 하도록 순서를 바꿨다 (단, 안양/수원처럼
    경기도 안의 다른 특정 시·군이 지목된 경우는 여전히 그 아래 GYEONGGI_OTHER_CITIES
    검사에서 먼저 걸러진다 - 그건 "OR 조건"이 아니라 그 시·군 하나로 못박힌 경우라서).

    has_region_restriction: 공고에 실제 지역제한(나라장터 API의
      rgnLmtBidLocplcJdgmBssNm/rgnDutyJntcontrctYn 같은 필드)이 걸려있는지
      호출하는 쪽이 알고 있으면 넘겨줍니다.
      - False로 넘어오면: 공식 데이터로 지역제한이 없다고 "확인된" 경우입니다.
        이때는 region_text가 무슨 지역을 담고 있든(경기도든 충청남도든) 그냥
        공사현장 소재지 설명일 뿐 참가자격 제한이 아니므로, 전국 어디 업체든
        참가 가능한 것으로 보고 무조건 "전국"을 반환합니다.
      - None(모름, 기본값)이면 기존처럼 지역 시·군 이름만으로 추정합니다.

    2026-08-26: 위 has_region_restriction=False 처리를 "경기도 시·군이 같이
    적힌 경우"에만 적용하고 있었는데, 실제로는 경기도가 아예 안 나오고 다른
    도(道)만 적힌 경우(예: "충청남도 예산군")도 지역제한이 없다고 확인되면
    참가 가능한 게 맞았다 (대박낙찰정보와 대조해서 발견 - "예산시험장 1종대형
    장내기능시험장 시설 보수공사"/"내포공동구 소방 무선통신보조설비 보강공사"
    둘 다 restrictions가 비어있는데도(=지역제한 없음 확인됨) region이
    "충청남도"라는 이유만으로 계속 참가불가 처리되고 있었음). 그래서
    has_region_restriction is False 체크를 지역명 매칭보다 먼저, 무조건
    "전국"을 반환하도록 맨 위로 옮겼다.
    """
    region_text = region_text or ""
    org_text = org_text or ""
    title_text = title_text or ""
    combined = region_text + " " + org_text + " " + title_text

    if any(o in org_text for o in ALWAYS_INCLUDE_ORGS):
        return "전국"
    if has_region_restriction is False:
        # 실제 지역제한이 없다고 API로 확인된 경우: region_text에 어떤 지역이
        # 적혀있든 공사현장 소재지 설명일 뿐이라, 지역명 매칭 없이 바로 전국 대상.
        return "전국"
    if HOME_CITY in region_text:
        return "용인"
    if "전국" in region_text:
        return "전국"
    if any(city in combined for city in GYEONGGI_OTHER_CITIES):
        # 용인이 아닌 다른 경기도 시·군이 특정되어 있으면 참가 불가
        # (has_region_restriction이 False로 확인된 경우는 위에서 이미 전국으로 처리됨)
        return None
    if HOME_PROVINCE in region_text:
        # "경기도"(또는 "경기도"를 포함해 여러 지역이 나열된 경우)면 경기도 업체는
        # 참가 가능 - 나열된 다른 지역(EXCLUDE_REGION_KEYWORDS)에 걸리는지는
        # 상관없다. 여러 지역이 나열된 공고는 그중 아무 곳에나 등록된 업체면
        # 참가할 수 있는 OR 조건이기 때문.
        return "경기"
    if any(k in combined for k in EXCLUDE_REGION_KEYWORDS):
        # "경기"가 전혀 없이 경기도 밖 다른 광역시/도만 특정되어 있으면 참가 불가
        return None
    if not region_text:
        # 지역 정보 자체가 없음 = 전국 대상으로 간주
        return "전국"
    return None


def is_eligible_region(region_text: str, org_text: str = "", title_text: str = "",
                        has_region_restriction=None) -> bool:
    """(하위 호환용) get_region_scope()가 None이 아니면 참가가능."""
    return get_region_scope(region_text, org_text, title_text, has_region_restriction) is not None
