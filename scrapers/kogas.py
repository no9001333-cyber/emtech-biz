"""
한국가스공사 입찰정보 수집기
공공데이터포털의 "한국가스공사_입찰정보" OpenAPI 사용
(한국가스공사가 직접 등록한 API이며, data.go.kr 기준 개발/운영 모두 자동승인이라
 신청 즉시 서비스키를 받아 바로 쓸 수 있습니다)

사전 준비:
1) https://www.data.go.kr 에서 "한국가스공사 입찰정보" 검색 → 활용신청 (자동승인)
2) 발급받은 서비스키를 환경변수 KOGAS_SERVICE_KEY 로 설정

주의:
- 이 API는 데이터 표준이 XML로 고정되어 있어(JSON 지원 여부가 문서에 명시돼 있지 않음),
  요행을 바라지 않고 xml.etree로 직접 파싱합니다.
- DOCDATE_START(공고일자 시작)가 필수 파라미터라 LOOKBACK_DAYS 기준으로 채워 넣습니다.
- 응답 필드가 입찰번호/입찰명/입찰구분/업무구분/계약방법/마감일시/개찰일시/취소여부
  뿐이라 추정금액·기초금액·지역 정보는 이 API에 아예 없습니다. 대시보드 쪽은 금액이
  비어있으면 자연스럽게 "확인필요"로 표시하니 별도 처리는 필요 없고, 지역도 KEPCO/
  코레일과 동일하게 전국구 발주기관으로 보고 필터 없이 항상 포함시킵니다.
- 개별 공고 상세로 바로 연결되는 딥링크 필드가 없어, url은 한국가스공사 입찰시스템
  대문(bid.kogas.or.kr)으로 고정합니다.
"""

import sys
import os
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KOGAS_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry

ENDPOINT = "https://apis.data.go.kr/B551210/bidInfoList/getBidInfoList"


def _clean_key(key: str) -> str:
    import urllib.parse
    # 앞뒤 공백/줄바꿈이 섞여 들어오면 HTTP 헤더에서 오류가 나므로 반드시 strip
    return urllib.parse.unquote(key).strip()


def _text(el, tag):
    """el(Element) 하위에서 tag를 찾아 텍스트를 반환. 없으면 빈 문자열."""
    found = el.find(f".//{tag}")
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def fetch_kogas_bids():
    """한국가스공사 입찰정보 전체 리스트 반환.
    (전국 단위 발주기관이라 별도 지역 필터는 적용하지 않음)"""
    if not KOGAS_SERVICE_KEY:
        print("[한국가스공사] 서비스키(KOGAS_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)

    params = {
        "serviceKey": _clean_key(KOGAS_SERVICE_KEY),
        "pageNo": 1,
        "numOfRows": 500,
        "DOCDATE_START": begin.strftime("%Y%m%d"),
        "DOCDATE_END": end.strftime("%Y%m%d"),
    }

    try:
        resp = get_with_retry(ENDPOINT, params=params, timeout=30)
    except Exception as e:
        print(f"[한국가스공사] 요청 실패: {e}")
        return []

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        print(f"[한국가스공사] XML 파싱 실패: {e}")
        print(f"[한국가스공사] 응답 내용(처음 300자): {resp.text[:300]}")
        return []

    items = root.findall(".//item")
    if not items:
        result_code = _text(root, "resultCode")
        result_msg = _text(root, "resultMsg")
        print(f"[한국가스공사] 수집된 항목이 없습니다. (resultCode={result_code}, resultMsg={result_msg})")
        print(f"[한국가스공사] 응답 내용(처음 300자): {resp.text[:300]}")
        return []

    print(f"[한국가스공사] 응답 필드명 예시: {[child.tag for child in items[0]]}")

    results = []
    for item in items:
        if _text(item, "CANCEL_YN") == "Y":
            continue  # 취소된 공고는 목록에서 제외

        title = _text(item, "NOTICE_NAME")
        deadline = _text(item, "END_DT")
        if not is_deadline_in_range(deadline):
            continue

        results.append({
            "source": "한국가스공사",
            "title": title,
            "industry": "",
            "org": "한국가스공사",
            "notice_no": _text(item, "NOTICE_CODE"),
            "region": "",  # 이 API는 지역 필드를 제공하지 않음 → 전국 대상으로 간주
            "base_amount": "",  # 이 API는 금액 정보를 제공하지 않음 (대시보드에 "확인필요"로 표시됨)
            "notice_date": _text(item, "NOTICE_DT"),
            "reg_deadline": "",
            "bid_method": _text(item, "CONT_METHOD_NAME"),
            "deadline": deadline,
            "url": "http://bid.kogas.or.kr/",
            "eligible": True,
        })

    print(f"[한국가스공사] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kogas_bids():
        print(b)
