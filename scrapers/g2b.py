"""
나라장터(조달청) 입찰공고 수집기 - 공사(工事) + 용역(用役)
공공데이터포털의 "조달청_나라장터 입찰공고정보서비스" OpenAPI 사용

2026-09-10: 원래 공사(getBidPblancListInfoCnstwk)만 조회했는데, 대박낙찰정보와
대조해보니 재개발조합 "시공자 선정", "통신보안 솔루션 업체 선정", 통신 구축
용역처럼 용역입찰로 게시되는 통신 관련 공고가 통째로 빠지고 있었다. 그래서
용역(getBidPblancListInfoServc)도 같이 조회하도록 확장했다. 두 오퍼레이션의
응답 필드는 공통 필드(bidNtceNo/bidNtceNm/ntceInsttNm/bidClseDt/bdgtAmt/
presmptPrce/rgnLmtBidLocplcJdgmBssNm 등)가 거의 같고, 공사 전용 필드
(mainCnsttyNm=주공종명, cnstrtsiteRgnNm=공사현장지역)는 용역엔 없어서 그냥
빈 값으로 들어온다(코드가 .get()으로 관대하게 처리). 공고 dict에
notice_kind("공사"/"용역")를 넣어 구분한다.

2026-09-11: 용역 추가 직후 실제 운영 실행 로그를 보니 공사(9,340건)/용역(12,170건)
둘 다 30일치 총건수가 페이지 상한(15페이지×500=7,500건)을 넘어 "일부 누락됨" 경고가
떴다. 응답이 공고게시일시 오름차순이라 상한에 걸리면 뒤쪽(=가장 최근) 공고가 잘려서,
실제로 수집 데이터의 notice_date 최댓값이 실행 시점보다 3~4일이나 뒤처져 있었다
(가장 놓치면 안 되는 최신 공고가 매번 빠지고 있었던 셈). 그래서 30일 조회기간을
CHUNK_DAYS(5일) 단위로 쪼개 오퍼레이션별로 여러 번 나눠 조회하도록 바꿨다 - 구간당
건수가 상한보다 훨씬 작아져서 안전하다.

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

참고(입찰 제한사항): 공고문에 명시된 참가자격 제한을 아래 필드로 판단해 배지로 표기합니다.
        - indstrytyLmtYn(업종제한여부), bidPrtcptLmtYn(참가자격제한여부),
          rgnLmtBidLocplcJdgmBssNm(지역제한 소재지 판단기준), rgnDutyJntcontrctYn(지역의무공동도급여부),
          bidMethdNm/cntrctCnclsMthdNm에 "제한"/"지명"이 포함된 경우(제한경쟁·지명경쟁 입찰)
"""

import sys
import os
import time
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS, REGIONS, ALWAYS_INCLUDE_ORGS, EXCLUDE_REGION_KEYWORDS, G2B_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry, get_region_scope

ENDPOINT = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
# (종류, 오퍼레이션) 목록. 순서대로 조회해서 합친다.
OPERATIONS = [
    ("공사", "getBidPblancListInfoCnstwk"),
    ("용역", "getBidPblancListInfoServc"),
]


def _clean_key(key: str) -> str:
    """data.go.kr에서 Encoding/Decoding 어느 버전의 키를 넣어도 동작하도록,
    URL 인코딩되어 있으면 한 번 풀어준다 (requests가 다시 인코딩하므로 이중 인코딩 방지)."""
    import urllib.parse
    return urllib.parse.unquote(key)


def _fetch_page(operation: str, begin_dt: str, end_dt: str, page_no: int, num_of_rows: int = 500):
    url = f"{ENDPOINT}/{operation}"
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


def _build_restrictions(item: dict) -> str:
    """공고 항목에서 입찰 참가 제한 관련 정보를 뽑아 사람이 읽을 수 있는 배지 텍스트 목록으로 만든다.

    업종제한(indstrytyLmtYn)은 실제 데이터로 확인해보니 국내 공사입찰 대부분(약 90%)에
    법적으로 항상 걸려있어 변별력이 없어서 배지에서 제외했습니다. 입찰방식명에 "제한/지명"이
    포함된 경우도 지역제한·지역의무공동도급과 의미가 겹쳐서 함께 제외했습니다. 아래 세 가지만
    남깁니다: 지역제한, 지역의무공동도급, 참가자격제한.
    """
    tags = []
    rgn_lmt_bss = item.get("rgnLmtBidLocplcJdgmBssNm", "")
    if rgn_lmt_bss:
        tags.append(f"지역제한({rgn_lmt_bss})")
    if item.get("rgnDutyJntcontrctYn") == "Y":
        tags.append("지역의무공동도급")
    if item.get("bidPrtcptLmtYn") == "Y":
        tags.append("참가자격제한")
    # 순서를 유지하며 중복 제거
    seen = set()
    deduped = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return ", ".join(deduped)


def _collect_attachments(item: dict) -> list:
    """공고 상세정보 API가 필드별로 흩어서 주는 첨부파일 URL들을 모아
    대시보드에서 바로 다운로드 링크로 보여줄 수 있는 목록으로 만든다.
    (조달청_OpenAPI참고자료_나라장터_입찰공고정보서비스_1.2.docx 기준 필드명:
     stdNtceDocUrl=표준공고서, ntceSpecDocUrl1~10=공고규격서, sptDscrptDocUrl1~5=현장설명서)"""
    attachments = []
    std_url = item.get("stdNtceDocUrl", "")
    if std_url:
        attachments.append({"name": "표준공고서", "url": std_url})
    for i in range(1, 11):
        u = item.get(f"ntceSpecDocUrl{i}", "")
        if u:
            attachments.append({"name": f"규격서{i}", "url": u})
    for i in range(1, 6):
        u = item.get(f"sptDscrptDocUrl{i}", "")
        if u:
            attachments.append({"name": f"현장설명서{i}", "url": u})
    return attachments


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


def _parse_item(item: dict, notice_kind: str):
    """목록 조회 응답 item 하나를 대시보드용 dict로 변환. 대상 기간(마감일)
    밖이면 None. 공사/용역 공통 로직."""
    title = item.get("bidNtceNm", "")
    org_text = item.get("ntceInsttNm", "")
    region_text = (
        item.get("cnstrtsiteRgnNm", "")       # 공사현장 지역(공사 전용)
        or item.get("jntcontrctDutyRgnNm1", "")  # 지역의무공동도급 지역
        or item.get("incntvRgnNm1", "")          # 인센티브 지역
    )
    deadline = item.get("bidClseDt", "")
    if not is_deadline_in_range(deadline):
        return None

    # 실제 지역제한이 있는지 (없다고 "확인된" 경우에만 False로 넘겨서,
    # region_text의 시·군 이름만 보고 잘못 참가불가 처리하는 걸 막음)
    has_region_restriction = bool(item.get("rgnLmtBidLocplcJdgmBssNm")) or (
        item.get("rgnDutyJntcontrctYn") == "Y"
    )

    # 투찰금액 계산기용 실제 공고 데이터 (2026-08-18 추가, 2026-08-19 필드 매핑 수정,
    # 2026-08-20 base_amount/a_value 계산 방식 재수정):
    #   - est_amount(추정금액)=bdgtAmt(예산금액) 우선, 없으면 presmptPrce(추정가격,
    #     VAT 불포함)로 대체. 이 목록 조회 API 시점에는 아직 정식 기초금액이
    #     공개 전인 경우가 많아 이 값은 어디까지나 "잠정 추정치"입니다.
    #   - base_amount(기초금액)/a_value(A값): 이 목록 조회 오퍼레이션에는 진짜
    #     기초금액/A값이 없습니다(예산금액은 기초금액의 근사치일 뿐 실제로 다를 수
    #     있음). 진짜 값은 전용 오퍼레이션(공사기초금액조회)에서만 얻을 수 있어,
    #     일단 est_amount로 잠정 채워두고 g2b_basis_amount.py가 덮어씁니다.
    #   - successful_bid_lower_rate/reserve_price_total_count/draw_count: 공고에
    #     박힌 실제 값. 비거나 비정상 범위일 수 있어 대시보드 JS에서 재검증함.
    budget_amount = item.get("bdgtAmt", "")
    presmpt_price = item.get("presmptPrce", "")
    amount_for_base_est = budget_amount or presmpt_price

    _scope = get_region_scope(
        region_text, org_text, title,
        has_region_restriction=has_region_restriction,
    )
    return {
        "source": "나라장터",
        "notice_kind": notice_kind,  # "공사" | "용역"
        "title": title,
        "org": org_text,
        "industry": item.get("mainCnsttyNm", ""),  # 용역엔 없음(빈값)
        "notice_no": item.get("bidNtceNo", ""),
        "notice_ord": item.get("bidNtceOrd", "000"),
        "region": region_text,
        "base_amount": amount_for_base_est,
        "est_amount": amount_for_base_est,
        "est_price_excl_vat": presmpt_price,
        "a_value": "",
        "successful_bid_lower_rate": item.get("sucsfbidLwltRate", ""),
        "reserve_price_total_count": item.get("totPrdprcNum", ""),
        "reserve_price_draw_count": item.get("drwtPrdprcNum", ""),
        "notice_date": item.get("bidNtceDt", ""),
        # 실제 필드명은 bidQlfctRgstDt (bidQlfctRegDt는 오타).
        "reg_deadline": item.get("bidQlfctRgstDt", ""),
        "bid_method": item.get("bidMethdNm", "") or item.get("cntrctCnclsMthdNm", ""),
        "restrictions": _build_restrictions(item),
        "deadline": deadline,
        # 개찰일시 - 투찰마감 아래에 함께 표시.
        "open_date": item.get("opengDt", ""),
        "url": item.get("bidNtceDtlUrl", ""),
        "attachments": _collect_attachments(item),
        "region_scope": _scope,
        "eligible": _scope is not None,
    }


def _fetch_operation(kind: str, operation: str, begin_dt: str, end_dt: str):
    """한 오퍼레이션(공사 또는 용역)을 페이지네이션하며 전부 가져와 파싱한다."""
    out = []
    page_no = 1
    MAX_PAGES = 15  # 안전장치: 최대 15페이지(=최대 7,500건). IP 차단 위험 회피.
    while page_no <= MAX_PAGES:
        try:
            data = _fetch_page(operation, begin_dt, end_dt, page_no)
        except Exception as e:
            print(f"[G2B/{kind}] 요청 실패: {e}")
            break

        body = data.get("response", {}).get("body", {})
        items = body.get("items", [])
        if isinstance(items, dict):
            items = items.get("item", [])
        if not items:
            break

        if page_no == 1:
            print(f"[G2B/{kind}] 응답 필드명 예시: {list(items[0].keys())}")

        for item in items:
            parsed = _parse_item(item, kind)
            if parsed is not None:
                out.append(parsed)

        total_count = int(body.get("totalCount", 0))
        if page_no * 500 >= total_count:
            break
        if page_no == MAX_PAGES:
            print(f"[G2B/{kind}] 경고: 총 {total_count}건인데 상한(7,500건)에 걸려 일부 누락됨")
            break
        page_no += 1
        time.sleep(1)  # data.go.kr에 너무 몰아치지 않게 요청 사이 1초 휴식

    print(f"[G2B/{kind}] {len(out)}건 수집(대상 기간 필터 후)")
    return out


CHUNK_DAYS = 5  # 조회기간을 잘게 쪼개는 단위. 30일 전체를 한 번에 조회하면
# 공사/용역 모두 건수가 페이지 상한(15페이지=7,500건)을 넘겨서 최신 공고가
# 잘려나가는 문제가 있었다(응답이 공고게시일시 오름차순이라 상한에 걸리면
# 가장 최근 3~4일치가 통째로 누락됨 - 2026-09-11 대박입찰 대조 중 발견).
# 5일 단위로 쪼개면 구간당 건수가 상한보다 훨씬 작아져 안전하다.


def _date_chunks(begin: datetime, end: datetime, chunk_days: int):
    cur = begin
    while cur < end:
        chunk_end = min(cur + timedelta(days=chunk_days), end)
        yield cur, chunk_end
        cur = chunk_end


def fetch_g2b_bids():
    """나라장터 공사+용역 입찰공고 전체(업종 무관) 중 대상 기간에 해당하는 공고 리스트 반환.
    (지역/통신 필터링은 대시보드에서 처리)"""
    if not G2B_SERVICE_KEY:
        print("[G2B] 서비스키(G2B_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)

    results = []
    seen = set()  # 공사/용역 중복 + 조회기간 쪼갠 구간 경계 중복 제거
    for kind, operation in OPERATIONS:
        for chunk_begin, chunk_end in _date_chunks(begin, end, CHUNK_DAYS):
            begin_dt = chunk_begin.strftime("%Y%m%d0000")
            end_dt = chunk_end.strftime("%Y%m%d2359")
            for bid in _fetch_operation(kind, operation, begin_dt, end_dt):
                key = f"{bid.get('notice_no')}::{bid.get('notice_ord')}"
                if key in seen:
                    continue
                seen.add(key)
                results.append(bid)
            time.sleep(1)  # 구간 사이에도 한 템포 쉬어 API에 몰아치지 않게 함

    print(f"[G2B] 총 {len(results)}건 수집 (공사+용역 합계)")
    return results


if __name__ == "__main__":
    for b in fetch_g2b_bids():
        print(b)
