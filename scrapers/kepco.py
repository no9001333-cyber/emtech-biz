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


def _clean_key(key: str) -> str:
    """다른 scrapers/*.py와 마찬가지로 앞뒤 공백/줄바꿈이 섞여 들어와도
    인증 실패로 이어지지 않게 strip(). 2026-08-20: KEPCO_API_KEY를 처음
    등록했을 때 이 정리 로직이 빠져있던 걸 발견 - 직접 테스트해보니
    apiKey가 조금이라도 다르면 무조건 401 InvalidApiKeyException을
    반환하는 API라, 복사 과정의 사소한 공백 하나도 치명적일 수 있다."""
    return key.strip()


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

    key = _clean_key(KEPCO_API_KEY)
    # 키 자체는 절대 로그에 남기지 않고, 길이/앞뒤 몇 글자만 마스킹해서 출력.
    # 401 InvalidApiKeyException이 뜰 때 원인이 진짜 미승인 키인지, 복사
    # 과정에서 공백/오탈자가 섞였는지 구분하는 데 씀.
    masked = f"{key[:4]}...{key[-4:]} (길이 {len(key)})" if len(key) >= 8 else "(키가 너무 짧음)"
    print(f"[KEPCO] 사용 중인 API키(마스킹): {masked}")

    params = {
        "companyId": "COM01",  # 한국전력공사
        "noticeBeginDate": begin.strftime("%Y%m%d"),
        "noticeEndDate": end.strftime("%Y%m%d"),
        "apiKey": key,
        "returnType": "json",
    }

    try:
        resp = requests.get(ENDPOINT, params=params, timeout=30)
        # 2026-08-24: 실제 키로도 계속 "Expecting value"(빈 응답 본문)로 실패하는데
        # status_code/헤더를 안 남겨서 200인지 204인지 다른 상태인지조차 몰랐다.
        # raise_for_status() 이전에 무조건 남겨서 다음 실행 로그로 원인을 좁힌다.
        print(
            f"[KEPCO] 응답 상태: {resp.status_code}, "
            f"Content-Length={resp.headers.get('Content-Length')}, "
            f"Content-Type={resp.headers.get('Content-Type')}, "
            f"최종 URL={resp.url}"
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[KEPCO] 요청 실패: {e}")
        try:
            print(f"[KEPCO] 응답 내용(처음 300자): {resp.text[:300]!r}")
        except Exception:
            pass
        return []

    items = data.get("data", []) if isinstance(data, dict) else []
    if not items:
        # 정상 응답인데(200 OK) 항목이 0건일 때, data.get("data")가 진짜
        # 빈 리스트인지 아니면 응답 구조 자체가 기대와 다른지(필드명이
        # 바뀌었다든가) 구분할 수 있게 원본 응답을 그대로 남긴다.
        print(f"[KEPCO] 수집된 항목이 없습니다. 응답 원본(처음 500자): {str(data)[:500]}")

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
            "region_scope": "전국",
        })

    print(f"[KEPCO] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kepco_bids():
        print(b)
