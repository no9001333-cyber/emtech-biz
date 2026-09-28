"""
한국전력공사 공고별 "지역제한"을 한전 전자조달시스템(srm.kepco.net)에서 직접 가져온다.

배경(2026-09-28): 한전 빅데이터 API(kepco.py)에는 지역 필드가 없어서 한전 공고는 전부
"전국"으로 고정돼 있었다(진행중 309건 전부 전국). 그런데 대박낙찰정보 맞춤입찰정보를
보면 한전 공고에도 지역이 붙어 있고(예: 안양 지중화 광통신망 = 경기, 선유S/S 무인보안 =
경기), 경기본부·서울본부처럼 지역본부 발주 공사는 대부분 그 지역 업체로 제한된다.
즉 "전국"으로 두면 서울·대구 업체만 참가 가능한 공고가 우리 화면에 섞여 올라온다.

srm.kepco.net 통합공고 화면은 로그인 없이 볼 수 있는 ExtJS 화면이고, 내부적으로
POST /router(Ext.Direct)로 JSON을 주고받는다. 공고번호로 검색하는 목록 호출
(JoinPublicAnnounceController.getPageList, searchType=AnnounceNo) 응답에 이미
areaCodeName(지역명)과 limitedReasonCode(3006 = 국가계약법 시행령 제21조 제6호
지역제한)가 들어 있고, 상세화면의 "지역제한구분 / 지역명"은
BidDetailController.findRegionCodeData(bidId)가 준다(OR 조건 복수 지역 가능).
대박낙찰정보가 보여주는 값과 건별로 일치하는 것을 확인했다(2026-09-28).

호출은 CSRF 토큰(index.do의 <meta name="_csrf">)이 필요하다. 한 건에 약 3초라서
결과를 data/kepco_regions_cache.json에 저장해 두고 새 공고만 조회한다.
조회에 실패한 공고는 기존 판정("전국")을 지우지 않고 region_check에 "확인 실패"로
남긴다(나중 실행에서 다시 시도).
"""

import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers._common import get_region_scope

BASE = "https://srm.kepco.net"
LIST_ACTION = "smartsuit.ui.etnajs.spt.joinpublicannouncement.sp.JoinPublicAnnounceController"
DETAIL_ACTION = "smartsuit.ui.etnajs.pro.rfx.sp.BidDetailController"
REGION_LIMIT_CODE = "3006"
WORKERS = 4
TIME_BUDGET_SEC = 25 * 60  # 첫 실행처럼 조회할 게 많아도 이 시간을 넘기면 나머지는 다음 실행으로 미룬다
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kepco_regions_cache.json")


class _Client:
    """srm.kepco.net 세션(CSRF 토큰 포함). 세션이 끊기면 한 번 다시 연다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._open()

    def _open(self):
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0"
        html = s.get(f"{BASE}/index.do", timeout=30).text
        m = re.search(r'name="_csrf" content="([^"]+)"', html)
        if not m:
            raise RuntimeError("CSRF 토큰을 찾지 못함")
        s.headers.update({
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": m.group(1),
        })
        self.session = s

    def rpc(self, action, method, data):
        body = json.dumps({"action": action, "method": method, "data": [data], "type": "rpc", "tid": 1})
        for attempt in range(3):
            try:
                r = self.session.post(f"{BASE}/router", data=body, timeout=60)
                out = r.json()
                out = out[0] if isinstance(out, list) else out
                if out.get("type") == "exception" or "result" not in out:
                    raise RuntimeError(out.get("message") or "rpc exception")
                return out["result"]
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
                with self._lock:
                    try:
                        self._open()
                    except Exception:
                        pass


def _lookup(client, notice_no):
    """공고번호 하나의 지역제한 정보를 조회한다. 반환: 캐시에 넣을 dict."""
    today = datetime.now()
    res = client.rpc(LIST_ACTION, "getPageList", {
        "page": 1, "start": 0, "limit": 5,
        "searchType": "AnnounceNo", "searchText": notice_no,
        "fromSearchDate": (today - timedelta(days=364)).strftime("%Y-%m-%dT00:00:00"),
        "toSearchDate": today.strftime("%Y-%m-%dT23:59:59"),
    })
    recs = [r for r in (res.get("records") or []) if r.get("announceNo") == notice_no]
    if not recs:
        return {"found": False}
    rec = recs[0]
    regions = []
    if rec.get("areaCodeName") or rec.get("limitedReasonCode") == REGION_LIMIT_CODE:
        # 목록의 areaCodeName은 대표 지역 하나뿐일 수 있어, 상세의 지역제한 목록(OR 조건)을 다시 읽는다.
        detail = client.rpc(DETAIL_ACTION, "findRegionCodeData", {"bidId": rec.get("id"), "type": "Construction"})
        for d in detail or []:
            name = " ".join(x for x in (d.get("areaCodeName"), d.get("subAreaCodeName")) if x)
            if name and name not in regions:
                regions.append(name)
        if not regions and rec.get("areaCodeName"):
            regions = [rec["areaCodeName"]]
    return {
        "found": True,
        "regions": regions,
        "limited_reason": rec.get("limitedReasonCode"),
        "rfx_type": rec.get("rfxType"),
        "department": rec.get("departmentName"),
        "checked_at": today.strftime("%Y-%m-%d %H:%M"),
    }


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


def _notice_kind(bid, info):
    """한전 공고의 공사/용역/구매 구분. 목록 rfxType이 ProductBid면 자재구매,
    ServiceBid는 공사와 용역이 섞여 있어 공고명으로 가른다."""
    if info.get("rfx_type") == "ProductBid":
        return "구매"
    return "용역" if "용역" in (bid.get("title") or "") else "공사"


def apply_kepco_regions(bids):
    """한전 공고(bids, in-place)에 srm.kepco.net 공식 지역제한을 반영한다."""
    if not bids:
        return
    cache = _load_cache()
    todo = [b.get("notice_no") for b in bids
            if b.get("notice_no") and b.get("status") != "마감" and b["notice_no"] not in cache]
    todo = list(dict.fromkeys(todo))

    failed = set()
    if todo:
        try:
            client = _Client()
        except Exception as e:
            print(f"[한전 지역] srm.kepco.net 접속 실패, 이번엔 건너뜀(기존 판정 유지): {e}")
            client = None
        if client:
            started = time.time()
            print(f"[한전 지역] 새로 조회할 공고 {len(todo)}건 (캐시 {len(cache)}건)")

            def work(no):
                if time.time() - started > TIME_BUDGET_SEC:
                    return no, None
                try:
                    return no, _lookup(client, no)
                except Exception as e:
                    print(f"[한전 지역] {no} 조회 실패: {e}")
                    return no, "error"

            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for no, info in ex.map(work, todo):
                    if isinstance(info, dict):
                        cache[no] = info
                    elif info == "error":
                        failed.add(no)
            skipped = [n for n in todo if n not in cache and n not in failed]
            if skipped:
                print(f"[한전 지역] 시간 제한으로 {len(skipped)}건은 다음 실행에서 조회")
            _save_cache(cache)

    by_region = by_none = by_open = unknown = 0
    for b in bids:
        info = cache.get(b.get("notice_no"))
        if not info or not info.get("found"):
            if b.get("status") != "마감":
                unknown += 1
                b["region_check"] = {
                    "verified": False, "eligible_confirmed": None,
                    "note": "한전 전자조달시스템에서 지역제한을 아직 확인하지 못함 - 공고문 확인 필요",
                    "snippet": "",
                }
            continue
        b["notice_kind"] = _notice_kind(b, info)
        regions = info.get("regions") or []
        b["participation_regions"] = regions
        if regions:
            # org는 넘기지 않는다: get_region_scope는 발주기관명에 "한국전력공사"(ALWAYS_INCLUDE_ORGS)가
            # 있으면 지역과 무관하게 전국을 돌려주는데, 한전 공고는 org가 그 이름으로 채워진 경우가 있다.
            scope = get_region_scope(",".join(regions), "", "", has_region_restriction=True)
            b["region"] = ",".join(regions)
            b["restrictions"] = f"지역제한({','.join(regions)})"
            b["region_scope"] = scope
            b["eligible"] = scope is not None
            b["region_check"] = {
                "verified": True, "eligible_confirmed": scope if scope is not None else False,
                "note": "한전 전자조달시스템 공식 지역제한으로 확인함", "snippet": ",".join(regions),
            }
            by_region += 1
            if scope is None:
                by_none += 1
        else:
            b["region_scope"] = "전국"
            b["eligible"] = True
            b["region_check"] = {
                "verified": True, "eligible_confirmed": "전국",
                "note": "한전 전자조달시스템에 지역제한 없음(공식 데이터)", "snippet": "",
            }
            by_open += 1
    print(
        f"[한전 지역] 지역제한 {by_region}건(그중 참가불가 {by_none}건), 제한 없음 {by_open}건, "
        f"미확인 {unknown}건, 조회 실패 {len(failed)}건"
    )
