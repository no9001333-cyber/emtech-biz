"""
한국수자원공사(K-water) 전자조달 입찰공고 수집기
공공데이터포털의 "한국수자원공사_전자조달 입찰공고" OpenAPI 사용

사전 준비:
1) https://www.data.go.kr 에서 "한국수자원공사 전자조달 입찰공고" 검색 → 활용신청 (자동승인)
2) 발급받은 서비스키를 환경변수 KWATER_SERVICE_KEY 로 설정

주의: 정확한 오퍼레이션(세부기능) 이름을 Swagger 문서로 확인하지 못해서,
      아래 후보 이름들을 순서대로 시도합니다. 성공한 이름이 로그에 찍히니,
      확인되면 CANDIDATE_OPERATIONS 맨 앞으로 그 이름만 남겨도 됩니다.
"""

import sys
import os
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REGIONS, ALWAYS_INCLUDE_ORGS, KWATER_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, is_eligible_region

ENDPOINT = "https://apis.data.go.kr/B500001/ebid/tndr3"

# 공사 입찰공고 조회로 추정되는 후보 오퍼레이션명들 (순서대로 시도)
CANDIDATE_OPERATIONS = [
    "getEbidPblancTndrCnstwkList",
    "getBidPblancListInfoCnstwk",
    "getPblancListCnstwk",
    "getCnstwkPblancList",
    "getTndrCnstwkList",
    "getEbidPblancListCnstwk",
]


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _matches_region(region_text: str, org_text: str = "") -> bool:
    if any(o in (org_text or "") for o in ALWAYS_INCLUDE_ORGS):
        return True
    if not region_text:
        return False
    return any(r in region_text for r in REGIONS)


def _try_fetch(operation, params):
    url = f"{ENDPOINT}/{operation}"
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
    params = {
        "serviceKey": _clean_key(KWATER_SERVICE_KEY),
        "pageNo": 1,
        "numOfRows": 1000,
        "type": "json",
        "inqryDiv": 1,
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": end.strftime("%Y%m%d2359"),
    }

    items = None
    used_operation = None
    errors = []
    for operation in CANDIDATE_OPERATIONS:
        try:
            found_items, error = _try_fetch(operation, params)
        except Exception as e:
            found_items, error = None, str(e)

        if error is None:
            items = found_items
            used_operation = operation
            break
        errors.append(f"{operation}: {error}")

    if used_operation is None:
        print("[K-water] 요청 실패: 시도한 오퍼레이션 전부 실패")
        for e in errors:
            print(f"[K-water]   - {e}")
        return []

    print(f"[K-water] 성공한 오퍼레이션명: {used_operation} (config에 고정하려면 이 이름을 맨 앞으로)")

    if not items:
        print("[K-water] 수집된 항목이 없습니다.")
        return []

    print(f"[K-water] 응답 필드명 예시: {list(items[0].keys())[:15]}")

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
            "eligible": is_eligible_region(region_text, "한국수자원공사"),
        })

    print(f"[K-water] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kwater_bids():
        print(b)
