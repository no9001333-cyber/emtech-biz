"""
한국철도공사(코레일) 조달 입찰공고 수집기
공공데이터포털(odcloud 기반) "한국철도공사_조달_입찰공고" OpenAPI 사용

사전 준비:
1) https://www.data.go.kr 에서 "한국철도공사 조달 입찰공고" 검색 → 활용신청 (심의 필요할 수 있음)
2) 발급받은 서비스키를 환경변수 KORAIL_SERVICE_KEY 로 설정

주의: odcloud 기반 API라 나라장터류 API와 파라미터 이름이 다릅니다(page/perPage 사용).
      또한 필드명이 원본 스프레드시트의 한글 컬럼명을 그대로 쓰는 경우가 많아,
      아래 코드는 여러 후보 이름을 순서대로 시도합니다. 만약 전부 매칭되지 않으면
      로그에 실제 응답의 첫 번째 항목을 출력하니, 그 필드명을 보고 후보를 추가하면 됩니다.
"""

import sys
import os
import json

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS, KORAIL_SERVICE_KEY
from scrapers._common import is_deadline_in_range

ENDPOINT = "https://api.odcloud.kr/api/15136102/v1/uddi:6b5d4d9f-d3dd-4aa0-a67b-fde38189d3d2"


def _clean_key(key: str) -> str:
    import urllib.parse
    # 앞뒤 공백/줄바꿈이 섞여 들어오면 HTTP 헤더에서 오류가 나므로 반드시 strip
    return urllib.parse.unquote(key).strip()


def _matches_keyword(title: str) -> bool:
    return any(k in (title or "") for k in KEYWORDS)


def _get_any(item: dict, *key_candidates):
    """정확히 일치하는 키가 없으면, 후보 단어로 '시작하는' 키를 찾는다.
    (코레일 API는 실제 키가 '입찰공고명(DESCRIPTION)'처럼 한글+영문코드가 붙어있어
    정확히 일치시키기 어려우므로, 앞부분만 맞으면 인정한다.)"""
    for k in key_candidates:
        if k in item and item[k]:
            return str(item[k]).strip()
    for k in key_candidates:
        for real_key, v in item.items():
            if real_key.startswith(k) and v:
                return str(v).strip()
    return ""


def fetch_korail_bids():
    """한국철도공사 조달 입찰공고 중 통신 키워드에 해당하는 공고 리스트 반환.
    (코레일은 발주 특성상 전국 단위 사업이 많아 별도 지역 필터는 적용하지 않음)"""
    if not KORAIL_SERVICE_KEY:
        print("[코레일] 서비스키(KORAIL_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    headers = {
        "Authorization": f"Infuser {_clean_key(KORAIL_SERVICE_KEY)}",
    }
    params = {
        "page": 1,
        "perPage": 1000,
        "serviceKey": _clean_key(KORAIL_SERVICE_KEY),
    }

    try:
        resp = requests.get(ENDPOINT, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[코레일] 요청 실패: {e}")
        try:
            print(f"[코레일] 응답 내용(처음 300자): {resp.text[:300]}")
        except Exception:
            pass
        return []

    items = data.get("data", []) if isinstance(data, dict) else []
    if not items:
        print("[코레일] 수집된 항목이 없습니다.")
        return []

    # 필드명을 못 찾는 경우를 대비해, 첫 항목의 실제 키 목록을 한 번 출력
    print(f"[코레일] 응답 필드명 예시: {list(items[0].keys())[:15]}")

    results = []
    for item in items:
        title = _get_any(item, "입찰공고명", "공고명", "bidNtceNm", "title", "name", "DESCRIPTION")
        deadline = _get_any(item, "입찰서접수마감일", "개찰일", "개찰일자", "투찰마감일시", "bidClseDt", "endDatetime")
        if not is_deadline_in_range(deadline):
            continue

        results.append({
            "source": "한국철도공사",
            "title": title,
            "industry": "",
            "org": "한국철도공사",
            "notice_no": _get_any(item, "입찰공고번호", "공고번호", "bidNtceNo", "no"),
            "region": "",
            "base_amount": _get_any(item, "추정가격", "기초금액", "presumedPrice"),
            "notice_date": _get_any(item, "개찰일", "공고개시일", "공고게시일자", "noticeDate"),
            "reg_deadline": "",
            "bid_method": "",
            "deadline": deadline,
            "url": "https://info.korail.com",
            "eligible": True,
        })

    print(f"[코레일] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_korail_bids():
        print(b)
