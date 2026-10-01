"""
한국전력공사 전자조달시스템(srm.kepco.net) 통합공고에서 공사 입찰공고를 직접 수집한다.

2026-09-30: 예전 kepco.py는 한전 빅데이터 API(공고명에 "통신"이 들어간 것만)를 썼는데,
대박낙찰정보 맞춤입찰정보와 대조해보니
  - "무인보안시스템 교체공사", "ICT설비 이설공사"처럼 공고명엔 통신이 없지만 면허가
    정보통신공사업인 한전 경기본부 공사를 못 받아오거나(수집 자체 누락), 받아와도 업종이
    비어 있어 통신 필터에서 빠졌고,
  - 한국중부발전 등 같은 전자조달시스템을 쓰는 발전사(공동이용사) 공고는 아예 없었다.
대박의 "업종"은 공고의 면허자격(정보통신공사업 등)이고 "지역"은 지역제한(OR 조건)이다.
통합공고 목록(JoinPublicAnnounceController.getPageList, 로그인 불필요)은 최신 공고부터
주므로 LOOKBACK_DAYS 이전 공고가 나올 때까지만 넘기고, 공사 후보는 공고별로
면허자격(findLicenseCodeData)과 지역제한(findRegionCodeData)을 읽어 판정한다.
공고별 조회 결과는 data/kepco_srm_cache.json에 저장해 새 공고만 조회한다.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LOOKBACK_DAYS, OUR_LICENSES
from scrapers._common import is_deadline_in_range, get_region_scope
from scrapers.kepco_regions import _Client, LIST_ACTION, DETAIL_ACTION, REGION_LIMIT_CODE

PAGE_SIZE = 100
MAX_PAGES = 40
WORKERS = 2  # 4개로 병렬 조회했더니 srm.kepco.net이 접속을 끊음(2026-09-30) - 천천히
TIME_BUDGET_SEC = 20 * 60
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kepco_srm_cache.json")


def _local(iso):
    """'2026-10-07T13:00:00.000+09:00' -> '2026-10-07 13:00'"""
    return (iso or "")[:16].replace("T", " ")


def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def _detail(client, rec):
    p = {"bidId": rec["id"], "type": "Construction"}
    licenses = []
    for d in client.rpc(DETAIL_ACTION, "findLicenseCodeData", p) or []:
        name = d.get("licenseQualificationCodeName")
        if name and name not in licenses:
            licenses.append(name)
    regions = []
    if rec.get("areaCodeName") or rec.get("limitedReasonCode") == REGION_LIMIT_CODE:
        for d in client.rpc(DETAIL_ACTION, "findRegionCodeData", p) or []:
            name = " ".join(x for x in (d.get("areaCodeName"), d.get("subAreaCodeName")) if x)
            if name and name not in regions:
                regions.append(name)
        if not regions and rec.get("areaCodeName"):
            regions = [rec["areaCodeName"]]
    logic = None
    if len(licenses) > 1:
        # 면허가 여러 개면 "모두 필요(And)"인지 "그중 하나(Or)"인지 공고 기본정보에 있다.
        logic = (client.rpc(DETAIL_ACTION, "findBidBasicInfo", rec["id"]) or {}).get("licenseAutoEvalType")
    return {"licenses": licenses, "license_logic": logic, "regions": regions,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _kind(title, licenses):
    if any("공사업" in l for l in licenses):
        return "공사"
    if licenses:
        return "용역"  # 감리업·엔지니어링 등 공사업이 아닌 면허만 요구하면 용역
    return "용역" if "용역" in (title or "") else "공사"


def fetch_kepco_srm_bids():
    client = _Client()
    begin = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    recs = []
    for page in range(1, MAX_PAGES + 1):
        # 날짜 조건은 searchDateType이 같이 있어야 적용된다(없으면 전체 이력 28만여 건을 뒤져서
        # 2페이지부터 서버가 응답을 못 함 - 화면의 조회 버튼이 보내는 파라미터 그대로 맞춤).
        res = client.rpc(LIST_ACTION, "getPageList", {
            "searchDateType": "NoticeDateTime", "searchType": "",
            "fromSearchDate": f"{begin}T00:00:00", "toSearchDate": datetime.now().strftime("%Y-%m-%dT00:00:00"),
            "rfxType": "ServiceBid", "page": page, "start": (page - 1) * PAGE_SIZE, "limit": PAGE_SIZE, "totalCount": 0,
        })
        rows = res.get("records") or []
        if not rows:
            break
        recs.extend(rows)
        if min((r.get("announceDate") or "9999")[:10] for r in rows) < begin:
            break
        time.sleep(0.5)
    recs = [r for r in recs if (r.get("announceDate") or "")[:10] >= begin]
    print(f"[한전 전자조달] 최근 {LOOKBACK_DAYS}일 공사·용역 공고 {len(recs)}건 (공동이용 발전사 포함)")

    # 마감 범위 안이고, 공고명상 용역이 아닌 것만 면허/지역을 조회한다.
    cands = [r for r in recs if is_deadline_in_range(_local(r.get("endProposalDate")))
             and "용역" not in (r.get("announceName") or "")]
    cache = _load_cache()
    todo = [r for r in cands if r.get("announceNo") not in cache
            or (len(cache[r["announceNo"]].get("licenses") or []) > 1 and "license_logic" not in cache[r["announceNo"]])]
    if todo:
        started = time.time()
        print(f"[한전 전자조달] 면허·지역제한 새로 조회 {len(todo)}건 (캐시 {len(cache)}건)")

        fails = {"n": 0}

        def work(rec):
            # 연속으로 실패하면 서버가 막은 것이므로 더 두드리지 않고 다음 실행으로 미룬다.
            if time.time() - started > TIME_BUDGET_SEC or fails["n"] >= 5:
                return rec, None
            try:
                info = _detail(client, rec)
                fails["n"] = 0
                time.sleep(0.5)
                return rec, info
            except Exception as e:
                fails["n"] += 1
                print(f"[한전 전자조달] {rec.get('announceNo')} 상세 조회 실패: {type(e).__name__}")
                return rec, None

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for rec, info in ex.map(work, todo):
                if info is not None:
                    cache[rec["announceNo"]] = info
        _save_cache(cache)

    results = []
    unknown = 0
    for r in cands:
        info = cache.get(r["announceNo"])
        title = r.get("announceName") or ""
        company = (r.get("departmentFullPath") or "").split(" ")[0] or "한국전력공사"
        bid = {
            "source": "한국전력공사",
            "title": title,
            "org": f"{company} {r.get('departmentName') or ''}".strip(),
            "notice_no": r.get("announceNo", ""),
            "base_amount": r.get("presumedprice") or "",
            "notice_date": (r.get("announceDate") or "")[:10],
            "reg_deadline": _local(r.get("endRequestDate")),
            "bid_method": r.get("bidType") or "",
            "deadline": _local(r.get("endProposalDate")),
            "url": "https://srm.kepco.net/index.do",
        }
        if info is None:
            unknown += 1
            bid.update({
                "notice_kind": "공사", "industry": "", "region": r.get("areaCodeName") or "",
                "region_scope": None, "eligible": False,
                "region_check": {"verified": False, "eligible_confirmed": None,
                                 "note": "한전 전자조달시스템 면허·지역 조회 전 - 다음 실행에서 확인", "snippet": ""},
            })
            results.append(bid)
            continue
        licenses, regions = info.get("licenses") or [], info.get("regions") or []
        bid["notice_kind"] = _kind(title, licenses)
        bid["industry"] = ",".join(licenses)
        bid["licenses"] = licenses
        bid["participation_regions"] = regions
        missing = [l for l in licenses if l not in OUR_LICENSES]
        if len(licenses) > 1 and info.get("license_logic") == "And" and missing:
            # 2026-10-01: 이엠테크는 정보통신공사업만 보유. 전기공사업+정보통신공사업처럼 모두 요구하는
            # 공고는 단독으로 참가할 수 없다(대박 맞춤입찰정보도 뺌 - 신안성-동용인, 얼굴인식 출입관리).
            bid.update({
                "region": ",".join(regions), "region_scope": None, "eligible": False, "license_blocked": True,
                "region_check": {"verified": True, "eligible_confirmed": False,
                                 "note": f"면허 모두 필요({'+'.join(licenses)}) - 보유하지 않은 면허: {', '.join(missing)}",
                                 "snippet": ""},
            })
            results.append(bid)
            continue
        if regions:
            scope = get_region_scope(",".join(regions), "", "", has_region_restriction=True)
            bid.update({
                "region": ",".join(regions), "restrictions": f"지역제한({','.join(regions)})",
                "region_scope": scope, "eligible": scope is not None,
                "region_check": {"verified": True, "eligible_confirmed": scope if scope is not None else False,
                                 "note": "한전 전자조달시스템 공식 지역제한으로 확인함", "snippet": ",".join(regions)},
            })
        else:
            bid.update({
                "region": "", "region_scope": "전국", "eligible": True,
                "region_check": {"verified": True, "eligible_confirmed": "전국",
                                 "note": "한전 전자조달시스템에 지역제한 없음(공식 데이터)", "snippet": ""},
            })
        results.append(bid)
    tel = sum(1 for b in results if "정보통신" in (b.get("industry") or ""))
    print(f"[한전 전자조달] 수집 {len(results)}건 (정보통신 면허 {tel}건, 면허·지역 미조회 {unknown}건)")
    return results
