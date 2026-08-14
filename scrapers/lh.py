"""
한국토지주택공사(LH) 입찰공고 수집기
공공데이터포털의 "한국토지주택공사 입찰공고정보" OpenAPI 사용
(LH가 배포한 "Open API 활용가이드_20210407.docx" 문서 기준으로 정확한 파라미터/필드명 반영)

사전 준비:
1) https://www.data.go.kr 에서 "한국토지주택공사 입찰공고정보" 검색 → 활용신청 (자동승인)
2) 발급받은 서비스키를 환경변수 LH_SERVICE_KEY 로 설정

주의: 이 API는 XML로만 응답하고, EUC-KR 인코딩입니다.
      필수 조건: 입찰공고일자(시작+끝) 또는 공고번호 중 하나는 반드시 있어야 합니다.
      (여기서는 조회기간을 기준으로 시작/끝 날짜를 함께 보냅니다)
"""

import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REGIONS, ALWAYS_INCLUDE_ORGS, EXCLUDE_REGION_KEYWORDS, LH_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, is_eligible_region

ENDPOINT = "http://openapi.ebid.lh.or.kr/ebid.com.openapi.service.OpenBidInfoList.dev"


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _xml_text(elem, tag):
    found = elem.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ""


def fetch_lh_bids():
    """LH 입찰공고 중 대상 지역에 해당하는 공고 리스트 반환 (업종 무관 전체 수집)"""
    if not LH_SERVICE_KEY:
        print("[LH] 서비스키(LH_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    # 공식 문서 기준 파라미터명: tndrbidRegDtStart / tndrbidRegDtEnd (YYYYMMDD, 8자리)
    params = {
        "serviceKey": _clean_key(LH_SERVICE_KEY),
        "numOfRows": 1000,
        "pageNo": 1,
        "tndrbidRegDtStart": begin.strftime("%Y%m%d"),
        "tndrbidRegDtEnd": end.strftime("%Y%m%d"),
    }

    try:
        resp = requests.get(ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        # 이 API는 EUC-KR로 응답하는데, 파이썬 기본 XML 파서는 바이트에서 곧바로
        # 다중바이트 인코딩(EUC-KR)을 못 읽으므로, 먼저 문자열로 디코딩한 뒤 파싱한다.
        raw_text = resp.content.decode("euc-kr", errors="replace")
        root = ET.fromstring(raw_text)
    except Exception as e:
        print(f"[LH] 요청 실패: {e}")
        try:
            print(f"[LH] 응답 내용(처음 500자): {resp.text[:500]}")
        except Exception:
            pass
        return []

    items = root.findall(".//item")
    if not items:
        # 에러 메시지가 있으면 같이 출력 (resultCode/resultMsg는 header 안에 있음)
        result_msg = root.find(".//resultMsg")
        print(f"[LH] item을 찾지 못함. resultMsg: {result_msg.text if result_msg is not None else '(없음)'}")
        return []

    results = []
    for item in items:
        title = _xml_text(item, "bidnmKor")
        deadline = _xml_text(item, "tndrdocAcptEndDtm")  # 입찰서접수마감일시 = 투찰마감
        if not is_deadline_in_range(deadline):
            continue

        # 참가지역1~4를 합쳐서 지역 텍스트로 사용
        region_parts = [
            _xml_text(item, f"zoneRstrct{i}") for i in range(1, 5)
        ]
        region_text = ",".join(p for p in region_parts if p)

        results.append({
            "source": "LH",
            "title": title,
            "org": "한국토지주택공사",
            "industry": _xml_text(item, "cstrtnJobGbNm"),  # 업무구분(시설공사 등)
            "notice_no": _xml_text(item, "bidNum"),
            "region": region_text,
            "base_amount": _xml_text(item, "fdmtlAmt") or _xml_text(item, "presmtPrc"),
            "notice_date": _xml_text(item, "tndrbidRegDt"),
            "reg_deadline": _xml_text(item, "tndrdocAcptBgninDtm"),  # 입찰서접수개시일시
            "bid_method": _xml_text(item, "tndrCtrctMedCd"),  # 입찰계약방법(제한경쟁 등)
            "restrictions": f"지역제한({region_text})" if region_text else "",  # 참가지역1~4가 있으면 지역제한 공고
            "deadline": deadline,
            "url": "https://ebid.lh.or.kr",
            "eligible": is_eligible_region(region_text, "한국토지주택공사", title),
        })

    print(f"[LH] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_lh_bids():
        print(b)
