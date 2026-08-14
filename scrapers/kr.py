"""
국가철도공단(KR) 입찰정보 수집기
공공데이터포털(odcloud 기반) "국가철도공단_입찰정보DB" OpenAPI 사용
(한국철도공사=코레일과는 다른 기관입니다. 국가철도공단은 철도 건설을 담당해
 궤도·역사·통신설비 신설 공사가 많이 나옵니다.)

사전 준비:
1) https://www.data.go.kr 에서 "국가철도공단 입찰정보" 검색 → 활용신청
2) 발급받은 서비스키를 환경변수 KR_SERVICE_KEY 로 설정

주의: odcloud 기반 API라 파라미터가 나라장터류 API와 다릅니다(page/perPage 사용).
      필드명이 원본 스프레드시트의 한글 컬럼명을 그대로 쓰는 경우가 많아,
      korail.py와 동일하게 여러 후보 이름을 순서대로 시도합니다.
"""

import sys
import os

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KR_SERVICE_KEY
from scrapers._common import is_deadline_in_range

# 2026-06-16 갱신된 최신 데이터셋 사용
ENDPOINT = "https://api.odcloud.kr/api/3070357/v1/uddi:f0726dbf-b031-41ff-a8f4-f06c71caf5f9"


def _clean_key(key: str) -> str:
    import urllib.parse
    # 앞뒤 공백/줄바꿈이 섞여 들어오면 HTTP 헤더에서 오류가 나므로 반드시 strip
    return urllib.parse.unquote(key).strip()


def _get_any(item: dict, *key_candidates):
    for k in key_candidates:
        if k in item and item[k]:
            return str(item[k]).strip()
    for k in key_candidates:
        for real_key, v in item.items():
            if real_key.startswith(k) and v:
                return str(v).strip()
    return ""


def fetch_kr_bids():
    """국가철도공단 입찰정보 전체(업종 무관) 리스트 반환.
    (전국 단위 철도 건설 사업이 많아 별도 지역 필터는 적용하지 않음)"""
    if not KR_SERVICE_KEY:
        print("[국가철도공단] 서비스키(KR_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    key = _clean_key(KR_SERVICE_KEY)
    headers = {"Authorization": f"Infuser {key}"}
    params = {
        "page": 1,
        "perPage": 1000,
        "serviceKey": key,
    }

    try:
        resp = requests.get(ENDPOINT, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[국가철도공단] 요청 실패: {e}")
        try:
            print(f"[국가철도공단] 응답 내용(처음 300자): {resp.text[:300]}")
        except Exception:
            pass
        return []

    items = data.get("data", []) if isinstance(data, dict) else []
    if not items:
        print("[국가철도공단] 수집된 항목이 없습니다.")
        return []

    print(f"[국가철도공단] 응답 필드명 예시: {list(items[0].keys())[:15]}")

    results = []
    for item in items:
        title = _get_any(item, "입찰공고명", "공고명", "사업명", "title", "name")
        deadline = _get_any(item, "입찰마감일", "투찰마감일", "마감일자", "입찰서접수마감일", "endDatetime")
        if not is_deadline_in_range(deadline):
            continue

        results.append({
            "source": "국가철도공단",
            "title": title,
            "org": "국가철도공단",
            "industry": "",
            "notice_no": _get_any(item, "공고번호", "입찰공고번호", "no"),
            "region": "",
            "base_amount": _get_any(item, "추정가격", "기초금액", "presumedPrice"),
            "notice_date": _get_any(item, "공고일자", "공고게시일", "noticeDate"),
            "reg_deadline": "",
            "bid_method": "",
            "deadline": deadline,
            "url": "https://ebid.kr.or.kr",
            "eligible": True,
            "status": "진행중",
        })

    print(f"[국가철도공단] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_kr_bids():
        print(b)
