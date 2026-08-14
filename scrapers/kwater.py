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

참고(실제 응답 필드명): 최초 작성 시 문서만 보고 bidNtceNm/rgnNm/bidClseDt/
      bidNtceNo/presmptPrce/bidNtceDt 같은 필드명을 추정해 사용했는데, 실제
      운영 로그로 확인한 응답 필드는 다음과 같이 전혀 다릅니다:
        cntrctDeptNm(계약부서명), cntrctDivNm(계약구분명: 공사/용역/물품 등),
        ctrmthdCdNm(계약방법명), tndrPartcptEntrpsCo(참가업체수),
        tndrPbanno(입찰공고번호), tndrPblancDe(공고일자),
        tndrPblancEnddt(입찰마감일시), tndrPblancNm(입찰공고명),
        tndrPlnprc(예정가격), tndrPrqudoCo(예정가격수), tndrStat(입찰상태)
      → 아래 매핑을 이 실제 필드명 기준으로 수정했습니다. 단, 이 API에는
      "공사현장이 어느 지역인지"를 직접 알려주는 필드가 없어서, 지역(region)은
      계약부서명(지역본부명, 예: "한강권역본부")으로 대체 표기합니다 — 실제
      현장 소재지와 정확히 일치하지 않을 수 있는 추정값입니다.
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

    def _s(v):
        """이 API는 날짜/번호 같은 필드를 문자열이 아닌 숫자(int)로 내려줄 때가 있어서,
        저장 전에 항상 문자열로 통일한다 (안 그러면 나중에 다른 소스의 문자열 값과
        섞여 정렬할 때 'int'와 'str'을 비교할 수 없다는 TypeError가 난다)."""
        return "" if v is None else str(v)

    results = []
    for item in all_items:
        title = _s(item.get("tndrPblancNm", ""))
        # 이 API에는 공사현장 지역을 직접 나타내는 필드가 없어, 계약부서(지역본부)명으로 대체
        region_text = _s(item.get("cntrctDeptNm", ""))
        deadline = _s(item.get("tndrPblancEnddt", ""))
        if not is_deadline_in_range(deadline):
            continue

        results.append({
            "source": "한국수자원공사",
            "title": title,
            "industry": _s(item.get("cntrctDivNm", "")),  # 계약구분명 (공사/용역/물품 등)
            "org": "한국수자원공사",
            "notice_no": _s(item.get("tndrPbanno", "")),
            "region": region_text,
            "base_amount": item.get("tndrPlnprc", ""),
            "notice_date": _s(item.get("tndrPblancDe", "")),
            "reg_deadline": "",
            "bid_method": _s(item.get("ctrmthdCdNm", "")),
            "restrictions": "",  # 이 API 응답에서 제한사항 관련 필드를 아직 확인하지 못해 비워둠
            "deadline": deadline,
            "url": "https://www.kwater.or.kr",
            "eligible": is_eligible_region(region_text, "한국수자원공사"),
        })

    print(f"[K-water] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kwater_bids():
        print(b)
