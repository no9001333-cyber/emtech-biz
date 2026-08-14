"""
한국수자원공사(K-water) 전자조달 입찰공고 수집기
공공데이터포털의 "한국수자원공사_전자조달 입찰공고" OpenAPI 사용

사전 준비:
1) https://www.data.go.kr 에서 "한국수자원공사 전자조달 입찰공고" 검색 → 활용신청 (자동승인)
2) 발급받은 서비스키를 환경변수 KWATER_SERVICE_KEY 로 설정

참고: data.go.kr의 Swagger 문서(Base URL: apis.data.go.kr/B500001/ebid/tndr3) 기준
      공사 입찰공고 조회 오퍼레이션은 /cntrwkList 이며, 파라미터는
      serviceKey, pageNo, numOfRows, _type(json/xml), searchDt(검색년월, YYYYMM)
      입니다. searchDt는 월 단위로만 조회되므로, LOOKBACK_DAYS 범위에 걸친
      연-월을 모두 순회하며 조회해서 합칩니다.
"""

import sys
import os
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REGIONS, ALWAYS_INCLUDE_ORGS, KWATER_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, is_eligible_region

ENDPOINT = "https://apis.data.go.kr/B500001/ebid/tndr3"
OPERATION = "cntrwkList"


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _matches_region(region_text: str, org_text: str = "") -> bool:
    if any(o in (org_text or "") for o in ALWAYS_INCLUDE_ORGS):
        return True
    if not region_text:
        return False
    return any(r in region_text for r in REGIONS)


def _month_range(begin: datetime, end: datetime):
    """begin~end 사이에 걸친 연-월(YYYYMM) 목록을 순서대로 반환 (searchDt가 월 단위라서 필요)."""
    months = []
    y, m = begin.year, begin.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return months


def _fetch_month(search_dt):
    url = f"{ENDPOINT}/{OPERATION}"
    params = {
        "serviceKey": _clean_key(KWATER_SERVICE_KEY),
        "pageNo": 1,
        "numOfRows": 1000,
        "_type": "json",
        "searchDt": search_dt,
    }
    resp = requests.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    try:
        data = resp.json()
    except Exception:
        return None, f"JSON 파싱 실패 (응답 앞부분: {resp.text[:150]})"

    body = data.get("response", {}).get("body", {}) if isinstance(data, dict) else {}
    result_code = data.get("response", {}).get("header", {}).get("resultCode") if isinstance(data, dict) else None
    if result_code and str(result_code) not in ("00", "0"):
        result_msg = data.get("response", {}).get("header", {}).get("resultMsg", "")
        return None, f"resultCode={result_code} ({result_msg})"

    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    return items, None


def fetch_kwater_bids():
    """한국수자원공사 공사 입찰공고 중 대상 지역에 해당하는 공고 리스트 반환 (업종 무관 전체 수집)"""
    if not KWATER_SERVICE_KEY:
        print("[K-water] 서비스키(KWATER_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)

    all_items = []
    errors = []
    for search_dt in _month_range(begin, end):
        found_items, error = _fetch_month(search_dt)
        if error is not None:
            errors.append(f"{search_dt}: {error}")
            continue
        if found_items:
            all_items.extend(found_items)

    if errors and not all_items:
        print("[K-water] 요청 실패: 조회한 월 전부 실패")
        for e in errors:
            print(f"[K-water]   - {e}")
        return []
    for e in errors:
        print(f"[K-water] 일부 월 조회 실패 - {e}")

    if not all_items:
        print("[K-water] 수집된 항목이 없습니다.")
        return []

    print(f"[K-water] 응답 필드명 예시: {list(all_items[0].keys())[:15]}")

    results = []
    for item in all_items:
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
            "eligible": is_eligible_region(region_text, "한국수자원공사"),
        })

    print(f"[K-water] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kwater_bids():
        print(b)
