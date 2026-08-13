"""
한국수자원공사(K-water) 전자조달 입찰공고 수집기
공공데이터포털의 "한국수자원공사_전자조달 입찰공고" OpenAPI 사용 (JSON+XML 모두 지원)

사전 준비:
1) https://www.data.go.kr 에서 "한국수자원공사 전자조달 입찰공고" 검색 → 활용신청 (자동승인)
2) 발급받은 서비스키를 환경변수 KWATER_SERVICE_KEY 로 설정
"""

import sys
import os
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS, REGIONS, ALWAYS_INCLUDE_ORGS, KWATER_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry, is_eligible_region

ENDPOINT = "https://apis.data.go.kr/B500001/ebid/tndr3"
# 공사 입찰공고 정보 조회 오퍼레이션 (용역/내자/물품은 각각 다른 오퍼레이션명 사용 - 필요시 추가)
OPERATION = "getEbidPblancTndrCnstwkList"


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _matches_keyword(title: str) -> bool:
    return any(k in (title or "") for k in KEYWORDS)


def _matches_region(region_text: str, org_text: str = "") -> bool:
    if any(o in (org_text or "") for o in ALWAYS_INCLUDE_ORGS):
        return True
    if not region_text:
        return False
    return any(r in region_text for r in REGIONS)


def fetch_kwater_bids():
    """한국수자원공사 공사 입찰공고 중 통신 키워드 + 대상 지역에 해당하는 공고 리스트 반환"""
    if not KWATER_SERVICE_KEY:
        print("[K-water] 서비스키(KWATER_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    url = f"{ENDPOINT}/{OPERATION}"
    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    params = {
        "serviceKey": _clean_key(KWATER_SERVICE_KEY),
        "pageNo": 1,
        "numOfRows": 1000,
        "type": "json",
        "inqryDiv": 1,
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": end.strftime("%Y%m%d2359"),
    }

    try:
        resp = get_with_retry(url, params=params, timeout=30)
        data = resp.json()
    except Exception as e:
        print(f"[K-water] 요청 실패: {e}")
        try:
            print(f"[K-water] 응답 내용(처음 300자): {resp.text[:300]}")
        except Exception:
            pass
        return []

    body = data.get("response", {}).get("body", {}) if isinstance(data, dict) else {}
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])

    results = []
    for item in items:
        title = item.get("bidNtceNm") or item.get("ntceNm", "")
        region_text = item.get("rgnNm", "")
        deadline = item.get("bidClseDt", "")
        if not is_deadline_in_range(deadline):
            continue

        results.append({
            "source": "한국수자원공사",
            "title": title,
            "industry": "",
            "org": "한국수자원공사",
            "notice_no": item.get("bidNtceNo", ""),
            "region": region_text,
            "base_amount": item.get("presmptPrce", ""),
            "notice_date": item.get("bidNtceDt", ""),
            "reg_deadline": "",
            "bid_method": "",
            "deadline": deadline,
            "url": "https://www.kwater.or.kr",
            "eligible": is_eligible_region(region_text, "한국수자원공사", title),
        })

    print(f"[K-water] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kwater_bids():
        print(b)
