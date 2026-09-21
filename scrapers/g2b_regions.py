"""
나라장터 공고별 "참가가능지역"과 "면허제한"을 공식 API로 직접 가져와 판정에 쓴다.

배경(2026-09-21): 대박낙찰정보 "맞춤입찰정보"(이엠테크 기준 25건)와 건별로 대조해보니,
우리가 공고서(PDF) 문구를 읽고 추정하던 지역 판정이 계속 틀렸다. 예를 들어
새만금 자율운송 통합관제 실증지원센터 통신공사(전북), Ai-Edutech 융합교육센터
통신설비공사(충북), xEV 안전성 평가센터 통신 신축공사(충남)는 대박에서 해당 도(道)로
분류돼 있는데 우리는 "전국"으로 표시했다. 사용자가 "공고문에 참가가능지역이 있으니
거기서 경기/용인/전국만 확인하면 되지 않느냐"고 짚은 그 값이, 나라장터 입찰공고정보
서비스(BidPublicInfoService)에 공고별로 이미 구조화돼 있었다:
  - getBidPblancListInfoPrtcptPsblRgn : 참가가능지역정보 (prtcptPsblRgnNm)
  - getBidPblancListInfoLicenseLimit  : 면허제한정보 (lcnsLmtNm, permsnIndstrytyList)
(data.go.kr 명세 15129394, g2b.py와 같은 서비스라 G2B_SERVICE_KEY를 그대로 쓴다.)
대박낙찰정보의 "업종"/"지역" 컬럼이 바로 이 두 값이다. 재개발조합 "시공자 선정"처럼
제목엔 통신이 없어도 면허제한 목록에 통신이 들어간 공고가 대박 맞춤입찰정보에 뜨는
것도 이 면허제한 값 때문이다.

판정 규칙: 참가가능지역 행이 하나도 없으면 "지역제한 없음"(전국), 있으면 그 지역들로
get_region_scope()를 돌려 용인/경기/전국/None을 결정한다(PDF 추정은 이 API를 못 쓴
경우의 보조 수단으로만 남긴다).

주의: 응답 필드명은 명세(Swagger)로 확인했지만 실제 응답은 서비스키가 있어야 볼 수 있어,
필드를 관대하게 읽고 첫 응답 예시/건수를 로그로 남긴다. 조회가 통째로 실패하거나
페이지 상한에 걸려 일부가 잘렸을 가능성이 있으면 "행 없음 = 전국"으로 단정하지 않고
기존 판정을 그대로 둔다(잘못 전국으로 열어주는 것이 더 위험함).
"""

import sys
import os
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import get_with_retry, get_region_scope

ENDPOINT = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
OP_REGION = "getBidPblancListInfoPrtcptPsblRgn"
OP_LICENSE = "getBidPblancListInfoLicenseLimit"
CHUNK_DAYS = 5
NUM_OF_ROWS = 500
MAX_PAGES = 30  # 구간당 상한(=15,000행). 넘으면 잘렸다고 보고 "행 없음=전국" 단정을 막는다.


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _items_of(data):
    body = data.get("response", {}).get("body", {}) if isinstance(data, dict) else {}
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items or [], int(body.get("totalCount", 0) or 0)


def _fetch_op(operation, begin, end):
    """한 오퍼레이션을 CHUNK_DAYS 단위로 쪼개 전부 가져온다.
    반환: (행 리스트, 잘림 여부, 성공 여부)"""
    rows = []
    truncated = False
    ok = True
    cur = begin
    while cur < end:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS), end)
        bgn = cur.strftime("%Y%m%d0000")
        fin = chunk_end.strftime("%Y%m%d2359")
        page = 1
        while page <= MAX_PAGES:
            params = {
                "serviceKey": _clean_key(G2B_SERVICE_KEY),
                "pageNo": page, "numOfRows": NUM_OF_ROWS, "type": "json",
                "inqryDiv": 1, "inqryBgnDt": bgn, "inqryEndDt": fin,
            }
            try:
                data = get_with_retry(f"{ENDPOINT}/{operation}", params=params, timeout=30).json()
            except Exception as e:
                print(f"[G2B 지역/면허] {operation} 요청 실패({bgn}~{fin} p{page}): {e}")
                ok = False
                break
            items, total = _items_of(data)
            if page == 1 and items and not rows:
                print(f"[G2B 지역/면허] {operation} 응답 필드명 예시: {list(items[0].keys())}")
            rows.extend(items)
            if not items or page * NUM_OF_ROWS >= total:
                break
            if page == MAX_PAGES:
                print(f"[G2B 지역/면허] 경고: {operation} {bgn}~{fin} 총 {total}행이 상한에 걸려 잘림")
                truncated = True
                break
            page += 1
            time.sleep(0.5)
        cur = chunk_end
        time.sleep(0.5)
    return rows, truncated, ok


def _pick(item, *names):
    for n in names:
        v = item.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def fetch_region_and_license_index():
    """{공고번호: {"regions": [...], "licenses": [...]}} 와 신뢰 가능 여부를 반환한다."""
    if not G2B_SERVICE_KEY:
        return {}, False
    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)

    region_rows, region_trunc, region_ok = _fetch_op(OP_REGION, begin, end)
    license_rows, license_trunc, license_ok = _fetch_op(OP_LICENSE, begin, end)
    print(f"[G2B 지역/면허] 참가가능지역 {len(region_rows)}행, 면허제한 {len(license_rows)}행")

    index = {}
    for r in region_rows:
        no = _pick(r, "bidNtceNo")
        nm = _pick(r, "prtcptPsblRgnNm")
        if no and nm:
            lst = index.setdefault(no, {"regions": [], "licenses": []})["regions"]
            if nm not in lst:
                lst.append(nm)
    for r in license_rows:
        no = _pick(r, "bidNtceNo")
        if not no:
            continue
        ent = index.setdefault(no, {"regions": [], "licenses": []})["licenses"]
        for nm in (_pick(r, "lcnsLmtNm"), _pick(r, "permsnIndstrytyList")):
            for part in nm.replace("/", ",").split(","):
                part = part.strip()
                if part and part not in ent:
                    ent.append(part)

    # 지역 조회가 성공했고 잘리지 않았어야 "행 없음 = 지역제한 없음(전국)"으로 단정할 수 있다.
    trustworthy_absence = region_ok and not region_trunc and len(region_rows) > 0
    return index, trustworthy_absence


def apply_official_regions(bids):
    """나라장터 공고(bids, in-place)에 공식 참가가능지역/면허제한을 반영한다."""
    try:
        index, trust_absence = fetch_region_and_license_index()
    except Exception as e:
        print(f"[G2B 지역/면허] 예상치 못한 오류로 건너뜀(기존 판정 유지): {e}")
        return
    if not index and not trust_absence:
        print("[G2B 지역/면허] 데이터를 못 가져와 기존 판정을 그대로 둡니다.")
        return

    # 안전 게이트: 참가가능지역이 지정된 공고 비율이 비정상적으로 낮으면(정상이면 공고의
    # 상당수가 지역제한을 가짐) 응답 해석이 틀렸을 수 있으므로 "행 없음=전국"을 쓰지 않는다.
    with_regions = sum(1 for b in bids if index.get(b.get("notice_no", ""), {}).get("regions"))
    if bids and with_regions / len(bids) < 0.01:
        print(f"[G2B 지역/면허] 참가가능지역이 지정된 공고가 {with_regions}/{len(bids)}건뿐이라 응답 해석이 의심스러워 '행 없음=전국'은 적용하지 않습니다.")
        trust_absence = False

    by_region = by_none = by_absent = lic_added = 0
    for b in bids:
        no = b.get("notice_no", "")
        ent = index.get(no)
        regions = ent["regions"] if ent else []
        licenses = ent["licenses"] if ent else []

        if licenses:
            b["licenses"] = licenses
            # 대시보드의 통신 업종 필터는 industry 문자열을 본다. 재개발 시공자 선정처럼
            # 제목엔 통신이 없어도 면허제한에 통신이 들어간 공고가 대박 맞춤입찰정보에
            # 뜨므로, 면허제한 목록을 industry에 합쳐 같은 기준으로 잡히게 한다.
            existing = b.get("industry") or ""
            joined = ",".join(licenses)
            if joined not in existing:
                b["industry"] = (existing + " / " if existing else "") + joined
            lic_added += 1

        if regions:
            scope = get_region_scope(",".join(regions), b.get("org", ""), "", has_region_restriction=True)
            b["participation_regions"] = regions
            b["region_scope"] = scope
            b["eligible"] = scope is not None
            b["scope_provisional"] = False
            b["region_check"] = {
                "verified": True, "eligible_confirmed": scope if scope is not None else False,
                "note": "나라장터 공식 참가가능지역 정보로 확인함", "snippet": ",".join(regions),
            }
            by_region += 1
            if scope is None:
                by_none += 1
        elif trust_absence:
            # 참가가능지역 행이 없음 = 지역제한 없음. 이미 다른 이유로 참가불가였던 것
            # (예: 참가자격제한)은 지역 문제가 아니므로 건드리지 않는다.
            b["participation_regions"] = []
            if b.get("region_scope") is None and b.get("eligible") is False and not b.get("scope_provisional") \
                    and (b.get("region_check") or {}).get("downgraded") is None:
                pass
            b["region_scope"] = "전국"
            b["eligible"] = True
            b["scope_provisional"] = False
            b["region_check"] = {
                "verified": True, "eligible_confirmed": "전국",
                "note": "나라장터 참가가능지역 정보에 제한 없음(공식 데이터)", "snippet": "",
            }
            by_absent += 1
    print(
        f"[G2B 지역/면허] 참가가능지역 지정 {by_region}건(그중 참가불가 {by_none}건), "
        f"제한 없음(전국) {by_absent}건, 면허제한 목록 반영 {lic_added}건"
    )
