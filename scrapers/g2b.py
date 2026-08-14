"""
나라장터(조달청) 공사 입찰공고 수집기
공공데이터포털의 "조달청_나라장터 입찰공고정보서비스" OpenAPI 사용

사전 준비:
1) https://www.data.go.kr 가입 → "나라장터 입찰공고정보서비스" 검색 → 활용신청 (즉시 자동승인)
2) 발급받은 서비스키를 환경변수 G2B_SERVICE_KEY 로 설정

주의: 공공데이터포털 API는 오퍼레이션/파라미터명이 가끔 개편됩니다.
      아래 ENDPOINT/OPERATION이 동작하지 않으면 data.go.kr에서 해당 서비스의
      "Swagger 문서"를 열어 최신 오퍼레이션명을 확인해 OPERATION 값만 바꿔주면 됩니다.

참고(업종/지역 필드): 실제 응답 필드명을 로그로 확인한 결과, 코드에서 원래 쓰던
      indstrytyNm / bizClsfcNoNm / prtcptPsblRgnNm 필드는 이 API 응답에 존재하지
      않아 항상 빈 값이 저장되고 있었습니다. 대신 아래 필드를 사용합니다.
        - 업종: mainCnsttyNm (주공종명, 예: "정보통신공사업")
        - 지역: cnstrtsiteRgnNm (공사현장 지역명) → 없으면 jntcontrctDutyRgnNm1
                (지역의무공동도급 지역명) → 그래도 없으면 incntvRgnNm1(인센티브 지역명)
"""

import sys
import os
import time
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS, REGIONS, ALWAYS_INCLUDE_ORGS, EXCLUDE_REGION_KEYWORDS, G2B_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry, is_eligible_region

ENDPOINT = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
# 공사(工事) 입찰공고 목록 조회 오퍼레이션
OPERATION = "getBidPblancListInfoCnstwk"


def _clean_key(key: str) -> str:
    """data.go.kr에서 Encoding/Decoding 어느 버전의 키를 넣어도 동작하도록,
    URL 인코딩되어 있으면 한 번 풀어준다 (requests가 다시 인코딩하므로 이중 인코딩 방지)."""
    import urllib.parse
    return urllib.parse.unquote(key)


def _fetch_page(begin_dt: str, end_dt: str, page_no: int, num_of_rows: int = 500):
    url = f"{ENDPOINT}/{OPERATION}"
    params = {
        "serviceKey": _clean_key(G2B_SERVICE_KEY),
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "inqryDiv": 1,  # 1: 공고게시일시 기준 조회
        "inqryBgnDt": begin_dt,
        "inqryEndDt": end_dt,
        "type": "json",
    }
    resp = get_with_retry(url, params=params, timeout=30)
    return resp.json()


def _matches_keyword(title: str) -> bool:
    return any(k in (title or "") for k in KEYWORDS)


def _matches_region(region_text: str, org_text: str = "", title_text: str = "") -> bool:
    # 한전/철도공단 등 전국구 발주기관은 무조건 통과
    if any(o in (org_text or "") for o in ALWAYS_INCLUDE_ORGS):
        return True
    # 지역 필드에 대상 지역(용인/경기/전국)이 명시되어 있으면 통과
    if region_text and any(r in region_text for r in REGIONS):
        return True
    # 발주기관명/공고명에 다른 지역명이 명시되어 있으면 제외
    combined = (org_text or "") + (title_text or "") + (region_text or "")
    if any(k in combined for k in EXCLUDE_REGION_KEYWORDS):
        return False
    # 지역 정보가 비어있고 다른 지역 힌트도 없으면, 전국구 기관으로 보고 통과
    if not region_text:
        return True
    return False


def fetch_g2b_bids():
    """나라장터 공사 입찰공고 전체(업종 무관) 중 대상 지역/기간에 해당하는 공고 리스트 반환"""
    if not G2B_SERVICE_KEY:
        print("[G2B] 서비스키(G2B_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    begin_dt = begin.strftime("%Y%m%d0000")
    end_dt = end.strftime("%Y%m%d2359")

    results = []
    page_no = 1
    MAX_PAGES = 15  # 안전장치: 최대 15페이지(=최대 7,500건)까지만 수집 (너무 많이 요청하면 IP 차단 위험)
    while page_no <= MAX_PAGES:
        try:
            data = _fetch_page(begin_dt, end_dt, page_no)
        except Exception as e:
            print(f"[G2B] 요청 실패: {e}")
            break

        body = data.get("response", {}).get("body", {})
        items = body.get("items", [])
        if isinstance(items, dict):
            items = items.get("item", [])
        if not items:
            break

        if page_no == 1 and items:
            print(f"[G2B] 응답 필드명 예시: {list(items[0].keys())}")

        for item in items:
            title = item.get("bidNtceNm", "")
            org_text = item.get("ntceInsttNm", "")
            region_text = (
                item.get("cnstrtsiteRgnNm", "")
                or item.get("jntcontrctDutyRgnNm1", "")
                or item.get("incntvRgnNm1", "")
            )
            deadline = item.get("bidClseDt", "")
            if not is_deadline_in_range(deadline):
                continue

            results.append({
                "source": "나라장터",
                "title": title,
                "org": org_text,
                "industry": item.get("mainCnsttyNm", ""),
                "notice_no": item.get("bidNtceNo", ""),
                "region": region_text,
                "base_amount": item.get("presmptPrce", ""),
                "notice_date": item.get("bidNtceDt", ""),
                "reg_deadline": item.get("bidQlfctRegDt", "") or item.get("prtcptRegYn", ""),
                "bid_method": item.get("bidMethdNm", "") or item.get("cntrctCnclsMthdNm", ""),
                "deadline": deadline,
                "url": item.get("bidNtceDtlUrl", ""),
                "eligible": is_eligible_region(region_text, org_text, title),
            })

        total_count = int(body.get("totalCount", 0))
        if page_no * 500 >= total_count:
            break
        page_no += 1
        time.sleep(1)  # 요청 사이 1초씩 쉬어서 너무 빠르게 몰아치지 않게 함

    print(f"[G2B] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_g2b_bids():
        print(b)
