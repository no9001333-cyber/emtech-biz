"""
누리장터 민간입찰공고(조달청_누리장터 민간입찰공고서비스, data.go.kr 15129456)에서 공사 공고를 수집한다.

2026-09-30: 대박낙찰정보 맞춤입찰정보에 뜨는 재개발·재건축 조합 공고(이문3구역 주차관제/CCTV,
소사3구역 지중화(통신), 각종 "시공자 선정 입찰공고")는 R26BK로 시작하는 나라장터 번호인데도
나라장터 입찰공고정보서비스(공사·용역·물품·외자·기타) 어디에도 없었다. 정비사업 조합·아파트
관리사무소 같은 민간 발주처 공고는 별도 서비스인 "누리장터 민간입찰공고서비스"로 나온다.
구조는 나라장터 입찰공고정보서비스와 같다(공사 목록/면허제한/참가가능지역 오퍼레이션).

같은 data.go.kr 계정의 G2B_SERVICE_KEY를 쓰지만 데이터셋별 활용신청(자동승인)이 따로 필요하다.
신청 전에는 403이 나므로 로그만 남기고 빈 목록을 돌려준다.
"""

import os
import sys
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import get_with_retry
from scrapers.g2b import _clean_key, _parse_item, _date_chunks, CHUNK_DAYS
from scrapers.g2b_regions import apply_official_regions

ENDPOINT = "https://apis.data.go.kr/1230000/ao/PrvtBidNtceService"
OP_LIST = "getPrvtBidPblancListInfoCnstwk"
OP_REGION = "getPrvtBidPblancListInfoPrtcptPsblRgn"
OP_LICENSE = "getPrvtBidPblancListInfoLicenseLimit"
MAX_PAGES = 15


def _flatten_text(value):
    """cnstwkDtlList처럼 dict/list로 오는 값에서 문자열만 모아 한 줄로."""
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v not in (None, ""):
            out.append(str(v))
    walk(value)
    return ",".join(dict.fromkeys(out))


def fetch_g2b_private_bids():
    if not G2B_SERVICE_KEY:
        return []
    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    latest = {}
    logged = False
    sample_logs = []
    for chunk_begin, chunk_end in _date_chunks(begin, end, CHUNK_DAYS):
        for page in range(1, MAX_PAGES + 1):
            params = {
                "serviceKey": _clean_key(G2B_SERVICE_KEY), "pageNo": page, "numOfRows": 500,
                "inqryDiv": 1, "inqryBgnDt": chunk_begin.strftime("%Y%m%d0000"),
                "inqryEndDt": chunk_end.strftime("%Y%m%d2359"), "type": "json",
            }
            try:
                data = get_with_retry(f"{ENDPOINT}/{OP_LIST}", params=params, timeout=30).json()
            except Exception as e:
                print(f"[누리장터 민간] 요청 실패 - 공공데이터포털에서 '조달청_누리장터 민간입찰공고서비스' 활용신청이 필요할 수 있음: {e}")
                return []
            body = data.get("response", {}).get("body", {})
            items = body.get("items", [])
            if isinstance(items, dict):
                items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]
            if not items:
                break
            if not logged:
                print(f"[누리장터 민간] 응답 필드명 예시: {list(items[0].keys())}")
                logged = True
            for item in items:
                # 민간 서비스는 필드명이 조금 다르다(첫 실행 로그로 확인, 2026-09-30):
                # 공고명 ntceNm, 공고종류 ntceDivNm, 참고금액 refAmt, 배정예산 asignBdgtAmt.
                item = {
                    **item,
                    "bidNtceNm": item.get("bidNtceNm") or item.get("ntceNm", ""),
                    "ntceKindNm": item.get("ntceKindNm") or item.get("ntceDivNm", ""),
                    "bdgtAmt": item.get("bdgtAmt") or item.get("asignBdgtAmt", ""),
                    "presmptPrce": item.get("presmptPrce") or item.get("refAmt", ""),
                }
                bid = _parse_item(item, "공사")
                if bid is None:
                    continue
                bid["private_notice"] = True
                # 면허제한 오퍼레이션에 행이 없는 민간 공고가 많아(2026-09-30 첫 실행: 153건 중 46건만),
                # 입찰자격명(bidQlfctNm)과 공사 상세목록(cnstwkDtlList)의 업종 문구를 업종으로 쓴다.
                extra = _flatten_text(item.get("cnstwkDtlList"))
                qual = item.get("bidQlfctNm") or ""
                bid["industry"] = " / ".join(x for x in (bid.get("industry"), qual, extra) if x)
                bid["private_region_div"] = item.get("rgnLmtDivNm") or ""
                if len(sample_logs) < 5:
                    sample_logs.append(f"{bid['notice_no']} 자격={qual[:60]!r} 공사상세={extra[:80]!r} 지역제한구분={item.get('rgnLmtDivNm')!r}")
                no = bid.get("notice_no")
                cur = latest.get(no)
                if cur is None or str(bid.get("notice_ord") or "") > str(cur.get("notice_ord") or ""):
                    latest[no] = bid
            if page * 500 >= int(body.get("totalCount", 0) or 0):
                break
            time.sleep(0.5)
        time.sleep(0.5)
    for line in sample_logs:
        print(f"[누리장터 민간] 예시 {line}")
    results = list(latest.values())
    for bid in results:
        if "취소" in (bid.get("notice_type") or ""):
            bid["cancelled"] = True
            bid["eligible"] = False
            bid["region_scope"] = None
    # 참가가능지역·면허제한도 민간 서비스의 오퍼레이션으로 공식 값 반영
    if results:
        apply_official_regions(results, ENDPOINT, OP_REGION, OP_LICENSE)
    print(f"[누리장터 민간] 공사 {len(results)}건 수집")
    return results
