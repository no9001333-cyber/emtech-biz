"""
방위사업청 국방전자조달시스템(D2B) 입찰공고 수집기
공공데이터포털의 "방위사업청_군수품조달정보 입찰공고_GW" OpenAPI 사용
(이 API도 데이터포맷이 XML이므로 XML로 파싱합니다)

사전 준비:
1) https://www.data.go.kr 에서 "방위사업청 군수품조달정보 입찰공고" 검색 → 활용신청
2) 발급받은 서비스키를 환경변수 D2B_SERVICE_KEY 로 설정

참고: 법령상 군 공사(시설) 입찰공고는 나라장터에도 동시 공고되므로,
      g2b.py 수집 결과에 이미 상당수 군부대 공사 건이 포함되어 있을 수 있습니다.

참고(실제 응답 필드명, data.go.kr Swagger 문서로 확인함 — 상세 URL:
      https://www.data.go.kr/data/15158416/openapi.do):
      이전 코드는 pblancNm/bidNtceNm/ntceNm, bidClseDt/clseDt, dmndInsttNm/ntceInsttNm
      같은 필드명을 추정해서 썼는데, 실제로는 전부 존재하지 않는 필드라서
      title은 항상 100% 공백, org는 항상 하드코딩된 "국방부"로만 표기되고 있었습니다.

      이 API는 조회 목적에 따라 오퍼레이션이 두 종류입니다.
        1) getDmstcCmpetBidPblancList (국내 경쟁입찰공고 = 물품/용역 중심)
           실제 필드: pblancSeCode, pblancSe, demandYear, pblancDate, pblancNo,
           pblancOdr, g2bPblancNo, g2bPblancOdr, dcsNo, bidNm, orntCode, ornt,
           prdctnAbltyPresentnClosDt, bidPartcptRegistClosDt, biddocPresentnClosDt,
           opengDt, excutTyCode, excutTy, cntrctMth, bidStle, bsisPrdprcApplcAt,
           bsicExpt, bsisPrdprcOthbcAt, busiDivs
           (금액 필드 자체가 없음 — 물품/용역은 사전에 금액을 공개하지 않는 경우가 많음)
        2) getFcltyCmpetBidPblancList (시설 경쟁입찰공고 = 공사 중심)
           실제 필드: pblancYear, pblancDate, pblancSeCode, pblancSe, pblancNo,
           pblancOdr, g2bPblancNo, g2bPblancOdr, cntrwkNo, cntrwkNm, ornt, orntCode,
           bidPartcptRegistClosDt, biddocPresentnClosDt, opengDt, cntrctMth, bidStle,
           baseAmnt, bsisPrdprcApplcAt, busiDivs
           (cntrwkNm=공사명, baseAmnt=기초금액 — 통신"공사"를 하는 이 회사에는
           이쪽이 더 직접적으로 관련된 오퍼레이션이라 함께 수집합니다)

      두 오퍼레이션 모두 "지역(공사현장 소재지)"을 나타내는 필드가 없습니다.
      D2B는 원래 출처 자체가 군부대 시설로 한정되어 있어 지역 필터를 적용하지
      않던 기존 동작을 유지하고, region은 계속 빈 값으로 둡니다.

      Swagger 문서상의 필드명과 실제 XML 응답 태그명이 미묘하게 다를 수 있어,
      g2b.py/kwater.py와 동일하게 각 오퍼레이션의 첫 응답에서 실제 태그명을
      로그로 출력해 검증할 수 있게 해두었습니다.
"""

import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS, D2B_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry

ENDPOINT = "https://apis.data.go.kr/1690000/BidPblancInfoService"
OPERATION_GOODS = "getDmstcCmpetBidPblancList"   # 국내 경쟁입찰공고 (물품/용역 중심)
OPERATION_FCLTY = "getFcltyCmpetBidPblancList"   # 시설 경쟁입찰공고 (공사 중심)


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _matches_keyword(title: str) -> bool:
    return any(k in (title or "") for k in KEYWORDS)


def _xml_text(elem, *tag_candidates):
    for tag in tag_candidates:
        found = elem.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def _fetch_items(operation: str, begin_dt: str, end_dt: str):
    """지정한 오퍼레이션으로 조회해서 XML item 엘리먼트 리스트를 반환. 실패하면 빈 리스트."""
    params = {
        "serviceKey": _clean_key(D2B_SERVICE_KEY),
        "numOfRows": 1000,
        "pageNo": 1,
        "inqryDiv": 1,
        "inqryBgnDt": begin_dt,
        "inqryEndDt": end_dt,
    }
    try:
        url = f"{ENDPOINT}/{operation}"
        resp = get_with_retry(url, params=params, timeout=30)
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"[D2B:{operation}] 요청 실패: {e}")
        try:
            print(f"[D2B:{operation}] 응답 내용(처음 300자): {resp.text[:300]}")
        except Exception:
            pass
        return []

    items = root.findall(".//item")
    if not items:
        print(f"[D2B:{operation}] item 태그를 찾지 못함. 응답 최상위 태그: {root.tag}")
        return []

    print(f"[D2B:{operation}] 응답 태그명 예시: {[c.tag for c in items[0]]}")
    return items


def _parse_goods_item(item) -> dict:
    """getDmstcCmpetBidPblancList(물품/용역) 항목을 공통 필드로 매핑"""
    title = _xml_text(item, "bidNm")
    deadline = _xml_text(item, "biddocPresentnClosDt")
    return {
        "source": "국방전자조달(D2B)",
        "title": title,
        "industry": _xml_text(item, "busiDivs"),
        "org": _xml_text(item, "ornt") or "국방부",
        "notice_no": _xml_text(item, "pblancNo"),
        "region": "",  # 이 오퍼레이션 응답에는 지역 필드가 없음
        "base_amount": "",  # 물품/용역은 금액 필드 자체가 없음 (사전 비공개)
        "notice_date": _xml_text(item, "pblancDate"),
        "reg_deadline": _xml_text(item, "bidPartcptRegistClosDt"),
        "bid_method": _xml_text(item, "cntrctMth"),
        "restrictions": "",  # 이 API 응답에서 제한사항 관련 필드를 아직 확인하지 못해 비워둠
        "deadline": deadline,
        "url": "https://www.d2b.go.kr",
        "eligible": True,
    }


def _parse_fclty_item(item) -> dict:
    """getFcltyCmpetBidPblancList(시설/공사) 항목을 공통 필드로 매핑"""
    title = _xml_text(item, "cntrwkNm")
    deadline = _xml_text(item, "biddocPresentnClosDt")
    return {
        "source": "국방전자조달(D2B)",
        "title": title,
        "industry": _xml_text(item, "busiDivs"),
        "org": _xml_text(item, "ornt") or "국방부",
        "notice_no": _xml_text(item, "pblancNo"),
        "region": "",  # 이 오퍼레이션 응답에도 지역 필드가 없음
        "base_amount": _xml_text(item, "baseAmnt"),
        "notice_date": _xml_text(item, "pblancDate"),
        "reg_deadline": _xml_text(item, "bidPartcptRegistClosDt"),
        "bid_method": _xml_text(item, "cntrctMth"),
        "restrictions": "",
        "deadline": deadline,
        "url": "https://www.d2b.go.kr",
        "eligible": True,
    }


def fetch_d2b_bids():
    """국방전자조달 입찰공고 목록 반환.
    물품/용역(getDmstcCmpetBidPblancList)과 시설/공사(getFcltyCmpetBidPblancList)
    두 오퍼레이션을 모두 조회해서 합칩니다. (통신공사 업체이므로 시설/공사 쪽이 특히 중요)
    (D2B는 출처 자체가 군부대로 한정되어 있어 지역 필터는 적용하지 않음)"""
    if not D2B_SERVICE_KEY:
        print("[D2B] 서비스키(D2B_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    begin_dt = begin.strftime("%Y%m%d0000")
    end_dt = end.strftime("%Y%m%d2359")

    results = []

    for operation, parser in (
        (OPERATION_GOODS, _parse_goods_item),
        (OPERATION_FCLTY, _parse_fclty_item),
    ):
        items = _fetch_items(operation, begin_dt, end_dt)
        for item in items:
            parsed = parser(item)
            if not is_deadline_in_range(parsed["deadline"]):
                continue
            results.append(parsed)

    print(f"[D2B] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_d2b_bids():
        print(b)
