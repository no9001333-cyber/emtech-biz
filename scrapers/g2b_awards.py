"""
나라장터(조달청) 낙찰정보(개찰결과) 수집기
공공데이터포털의 "조달청_나라장터 낙찰정보서비스" OpenAPI 사용

사전 준비:
1) https://www.data.go.kr 에서 "나라장터 낙찰정보서비스" 검색 → 활용신청 (자동승인)
   (※ 입찰공고정보서비스와는 별개의 서비스라 별도로 신청해야 합니다)
2) 발급받은 서비스키를 환경변수 G2B_AWARDS_SERVICE_KEY 로 설정
   (나라장터 입찰공고정보서비스와 같은 계정이면 같은 인증키를 써도 되는 경우가 많습니다.
   안 되면 이 서비스도 별도로 활용신청 후 발급받은 키를 넣어주세요)

참고: data.go.kr의 "조달청_나라장터 낙찰정보서비스" Swagger 문서 기준 Base URL은
      apis.data.go.kr/1230000/as/ScsbidInfoService 입니다 (경로가 /ad/ 가 아니라 /as/ 입니다).
      오퍼레이션명(getScsbidListSttusCnstwk)과 파라미터는 문서와 일치합니다.
"""

import sys
import os
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_AWARDS_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry

ENDPOINT = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
# 공사(工事) 낙찰(개찰결과) 목록 조회 오퍼레이션
OPERATION = "getScsbidListSttusCnstwk"


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def fetch_g2b_awards():
    """나라장터 공사 낙찰(개찰결과) 정보를 최근 LOOKBACK_DAYS일 이내 기준으로 가져온다."""
    if not G2B_AWARDS_SERVICE_KEY:
        print("[낙찰정보] 서비스키(G2B_AWARDS_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)

    url = f"{ENDPOINT}/{OPERATION}"
    params = {
        "serviceKey": _clean_key(G2B_AWARDS_SERVICE_KEY),
        "pageNo": 1,
        "numOfRows": 500,
        "inqryDiv": 1,
        "inqryBgnDt": begin.strftime("%Y%m%d0000"),
        "inqryEndDt": end.strftime("%Y%m%d2359"),
        "type": "json",
    }

    try:
        resp = get_with_retry(url, params=params, timeout=30)
        data = resp.json()
    except Exception as e:
        print(f"[낙찰정보] 요청 실패: {e}")
        try:
            print(f"[낙찰정보] 응답 내용(처음 300자): {resp.text[:300]}")
        except Exception:
            pass
        return []

    body = data.get("response", {}).get("body", {}) if isinstance(data, dict) else {}
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])

    results = []
    for item in items:
        # 낙찰(예정)금액이 있는 것만 유의미한 결과로 취급
        award_amount = item.get("sucsfbidAmt") or item.get("scsbidAmt", "")

        results.append({
            "source": "나라장터",
            "title": item.get("bidNtceNm", ""),
            "org": item.get("ntceInsttNm", ""),
            "notice_no": item.get("bidNtceNo", ""),
            "winner": item.get("prcbdrNm") or item.get("opengCorpNm", ""),
            "award_amount": award_amount,
            "base_amount": item.get("presmptPrce", ""),
            "assessed_rate": item.get("sucsfbidRate") or item.get("bidprcRate", ""),
            "open_date": item.get("opengDt", ""),
            "url": item.get("bidNtceDtlUrl", ""),
        })

    print(f"[낙찰정보] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for a in fetch_g2b_awards():
        print(a)
