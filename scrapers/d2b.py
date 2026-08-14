"""
방위사업청 국방전자조달시스템(D2B) 입찰공고 수집기
공공데이터포털의 "방위사업청_군수품조달정보 입찰공고_GW" OpenAPI 사용
(이 API도 데이터포맷이 XML이므로 XML로 파싱합니다)

사전 준비:
1) https://www.data.go.kr 에서 "방위사업청 군수품조달정보 입찰공고" 검색 → 활용신청
2) 발급받은 서비스키를 환경변수 D2B_SERVICE_KEY 로 설정

참고: 법령상 군 공사(시설) 입찰공고는 나라장터에도 동시 공고되므로,
      g2b.py 수집 결과에 이미 상당수 군부대 공사 건이 포함되어 있을 수 있습니다.
"""

import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS, D2B_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry

ENDPOINT = "https://apis.data.go.kr/1690000/BidPblancInfoService"
OPERATION = "getDmstcCmpetBidPblancList"  # 국내 경쟁입찰공고 목록


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _matches_keyword(title: str) -> bool:
    return any(k in (title or "") for k in KEYWORDS)


def _xml_text(elem, *tag_candidates):
    for tag in tag_candidates:
        found = elem.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def fetch_d2b_bids():
    """국방전자조달 입찰공고 중 통신 키워드에 해당하는 공고 리스트 반환
    (D2B는 출처 자체가 군부대로 한정되어 있어 지역 필터는 적용하지 않음)"""
    if not D2B_SERVICE_KEY:
        print("[D2B] 서비스키(D2B_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)

    params = {
        "serviceKey": _clean_key(D2B_SERVICE_KEY),
        "numOfRows": 1000,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": end.strftime("%Y%m%d2359"),
    }

    try:
        url = f"{ENDPOINT}/{OPERATION}"
        resp = get_with_retry(url, params=params, timeout=30)
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"[D2B] 요청 실패: {e}")
        try:
            print(f"[D2B] 응답 내용(처음 300자): {resp.text[:300]}")
        except Exception:
            pass
        return []

    items = root.findall(".//item")
    if not items:
        print(f"[D2B] item 태그를 찾지 못함. 응답 최상위 태그: {root.tag}")
        return []

    results = []
    for item in items:
        title = _xml_text(item, "pblancNm", "bidNtceNm", "ntceNm")
        deadline = _xml_text(item, "bidClseDt", "clseDt")
        if not is_deadline_in_range(deadline):
            continue

        results.append({
            "source": "국방전자조달(D2B)",
            "title": title,
            "industry": "",
            "org": _xml_text(item, "dmndInsttNm", "ntceInsttNm") or "국방부",
            "notice_no": _xml_text(item, "pblancNo", "ntceNo"),
            "region": _xml_text(item, "dlvrPlaceNm", "rgnNm"),
            "base_amount": _xml_text(item, "presmptPrce"),
            "notice_date": _xml_text(item, "pblancDt", "ntceDt"),
            "reg_deadline": "",
            "bid_method": "",
            "restrictions": "",  # 이 API 응답에서 제한사항 관련 필드를 아직 확인하지 못해 비워둠
            "deadline": deadline,
            "url": "https://www.d2b.go.kr",
            "eligible": True,
        })

    print(f"[D2B] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_d2b_bids():
        print(b)
