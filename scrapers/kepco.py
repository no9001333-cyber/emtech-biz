"""
한국전력공사(KEPCO) 빅데이터 오픈API - 전자입찰 계약정보
data.go.kr이 아닌 KEPCO 자체 빅데이터 포털(bigdata.kepco.co.kr)에서 발급받은 API 키를 사용합니다.

사전 준비:
1) https://bigdata.kepco.co.kr 가입 → Open API 신청 → API 인증키(apiKey) 발급
2) 발급받은 키를 환경변수 KEPCO_API_KEY 로 설정

주의: 이 API는 companyId(회사구분)와 noticeBeginDate~noticeEndDate(공고기간, 최대 90일)를
      반드시 지정해야 합니다. companyId=COM01은 한국전력공사입니다.
"""

import sys
import os
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS, KEPCO_API_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range

ENDPOINT = "https://bigdata.kepco.co.kr/openapi/v1/electContract.do"


def _matches_keyword(title: str) -> bool:
    return any(k in (title or "") for k in KEYWORDS)


def fetch_kepco_bids():
    """한국전력공사 전자입찰 계약정보 중 통신 키워드에 해당하는 공고 리스트 반환.
    KEPCO는 발주 특성상 전국 단위 사업이 많아 별도 지역 필터는 적용하지 않습니다."""
    if not KEPCO_API_KEY:
        print("[KEPCO] 서비스키(KEPCO_API_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=min(LOOKBACK_DAYS, 90))  # 이 API는 최대 90일 제한

    params = {
        "companyId": "COM01",  # 한국전력공사
        "noticeBeginDate": begin.strftime("%Y%m%d"),
        "noticeEndDate": end.strftime("%Y%m%d"),
        "apiKey": KEPCO_API_KEY,
        "returnType": "json",
    }

    try:
        resp = requests.get(ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[KEPCO] 요청 실패: {e}")
        try:
            print(f"[KEPCO] 응답 내용(처음 300자): {resp.text[:300]}")
        except Exception:
            pass
        return []

    items = data.get("data", []) if isinstance(data, dict) else []

    results = []
    for item in items:
        title = item.get("name", "")
        deadline = item.get("endDatetime", "")
        if not is_deadline_in_range(deadline):
            continue

        results.append({
            "source": "한국전력공사",
            "title": title,
            "industry": "",
            "org": item.get("placeName", "") or "한국전력공사",
            "notice_no": item.get("no", ""),
            "region": "",  # KEPCO 응답에 지역 필드가 없어 항상 포함 대상으로 처리
            "base_amount": item.get("presumedPrice", ""),
            "notice_date": item.get("noticeDate", ""),
            "reg_deadline": "",
            "bid_method": "",
            "deadline": deadline,
            "url": "https://bigdata.kepco.co.kr",
            "eligible": True,
        })

    print(f"[KEPCO] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kepco_bids():
        print(b)
