"""
한국수자원공사(K-water) 공고별 참가 가능 여부(지역제한/수의시담)를 K-water 전자조달시스템
(ebid.kwater.or.kr)에서 직접 확인한다.

배경(2026-09-28): data.go.kr K-water 입찰공고 API에는 지역 필드가 없어서 K-water 공고가
전부 "전국"으로 표시됐다(진행중 90건 전부). 실제로 확인해보니
  - 24건은 "수의계약(시담)" - 특정 업체와 이미 정해진 계약이라 우리는 참가 자체가 불가,
  - 소액전자·제한경쟁은 대부분 지사 소재 시·도로 지역제한이 걸려 있다
    (예: 정읍수도센터 통신공사 = 본점소재지 전북특별자치도, 포항권지사 = 경상북도).
전자조달시스템 공고 상세(POST /bidpblanc/bidpblancsttus/selectBidPblancDtl.do)는
로그인 없이 JSON으로 조회되며, 계약방법(ctrmthdCdNm)과 참가자격 요약
문구(tndrQualfAtpn)를 준다. 지역제한은 구조화 필드가 없어서
  1) 참가자격 요약 문구에서 지역명을 찾고,
  2) 없으면 첨부 공고문(HWP/HWPX/PDF, GET /sc/file/downloadAtchFileOne.do?xmlValue=...)
     본문에서 "지역제한/본점소재지" 문맥의 지역명을 찾는다.
그래도 못 찾으면 "미확인"으로 두고 대시보드 기본 화면(용인/경기/전국)에는 올리지 않는다
- 확인 안 된 공고를 전국으로 보여주는 것이 사용자가 지적한 "다른 지역이 올라오는" 원인이었다.

결과는 data/kwater_regions_cache.json에 저장해 새 공고만 조회한다.
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GYEONGGI_OTHER_CITIES
from scrapers._common import get_region_scope
from scrapers.doc_regions import extract_restricted_regions, document_text, extract_licenses as _licenses

BASE = "https://ebid.kwater.or.kr"
DETAIL_URL = f"{BASE}/bidpblanc/bidpblancsttus/selectBidPblancDtl.do"
DOWNLOAD_URL = f"{BASE}/sc/file/downloadAtchFileOne.do"
WORKERS = 4
TIME_BUDGET_SEC = 15 * 60
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kwater_regions_cache.json")


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    s.get(f"{BASE}/wq/index.do?w2xPath=%2fui%2findex.xml", timeout=30)
    return s


def _pick_notice_file(files):
    """첨부 중 공고문(또는 견적서 제출 안내 공고문)을 고른다."""
    def score(f):
        name = (f.get("docNm") or "") + " " + (f.get("docFileNm") or "")
        if "공고" in name or "안내문" in name:
            return 0
        return 9
    candidates = sorted((f for f in files or [] if score(f) == 0), key=score)
    return candidates[0] if candidates else None


def _lookup(session, notice_no):
    r = session.post(DETAIL_URL, json={
        "dmaSearchData": {"tndrPbanno": notice_no, "imtPblancYn": "N"},
        "ktagTokenField": "BID_savedToken", "BID_savedToken": None,
    }, timeout=60)
    j = r.json()
    if (j.get("message") or {}).get("code") != "success":
        raise RuntimeError(f"상세 조회 실패: {j.get('message')}")
    data = j.get("data") or {}
    t = data.get("tndrPblanc") or {}
    method = t.get("ctrmthdCdNm") or ""
    qual = (t.get("tndrQualfAtpn") or "").strip()
    info = {
        "found": bool(t),
        "method": method,
        "qualification": qual[:300],
        "regions": [],
        "basis": "",
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if "시담" in method:
        info["private"] = True
        return info
    regions = extract_restricted_regions(qual, GYEONGGI_OTHER_CITIES, whole_text_is_qualification=True)
    licenses = _licenses(qual)
    if regions:
        info.update(regions=regions, basis="참가자격 문구")
    notice_text = None
    if not regions or not licenses:
        # 지역이나 면허가 요약 문구에 없으면 공고문 본문을 읽는다. 대박의 "업종"은 공고의 면허
        # (예: 정보통신공사업)인데, K-water 상세 JSON에는 면허 필드가 없다(2026-09-30 확인).
        f = _pick_notice_file(data.get("atchflList"))
        if f:
            x = session.get(DOWNLOAD_URL, params={"xmlValue": json.dumps({"atchflId": f["atchflId"], "fileSeq": f.get("fileSeq", 1)})}, timeout=90)
            notice_text = document_text(x.content, f.get("docFileNm", ""))
            if not regions:
                regions = extract_restricted_regions(notice_text, GYEONGGI_OTHER_CITIES)
                if regions:
                    info.update(regions=regions, basis=f"공고문({f.get('docFileNm', '')})")
                else:
                    info["basis"] = "공고문에서 지역 문구를 못 찾음" if notice_text else "공고문을 읽지 못함"
            if not licenses:
                licenses = _licenses(notice_text)
        elif not regions:
            info["basis"] = "공고문 첨부 없음"
    info["licenses"] = licenses
    return info



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


def apply_kwater_regions(bids):
    """K-water 공고(bids, in-place)에 참가 가능 지역을 반영한다."""
    if not bids:
        return
    cache = _load_cache()
    todo = list(dict.fromkeys(b["notice_no"] for b in bids
                              if b.get("notice_no") and b.get("status") != "마감"
                              and (b["notice_no"] not in cache
                                   or ("licenses" not in cache[b["notice_no"]] and not cache[b["notice_no"]].get("private")))))
    failed = set()
    if todo:
        try:
            session = _session()
        except Exception as e:
            print(f"[수자원 지역] ebid.kwater.or.kr 접속 실패, 이번엔 건너뜀: {e}")
            session = None
        if session:
            started = time.time()
            print(f"[수자원 지역] 새로 조회할 공고 {len(todo)}건 (캐시 {len(cache)}건)")

            def work(no):
                if time.time() - started > TIME_BUDGET_SEC:
                    return no, None
                try:
                    return no, _lookup(session, no)
                except Exception as e:
                    print(f"[수자원 지역] {no} 조회 실패: {e}")
                    return no, "error"

            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                for no, info in ex.map(work, todo):
                    if isinstance(info, dict):
                        cache[no] = info
                    elif info == "error":
                        failed.add(no)
            _save_cache(cache)

    counts = {"수의시담": 0, "지역제한": 0, "참가불가지역": 0, "미확인": 0}
    for b in bids:
        info = cache.get(b.get("notice_no"))
        if not info or not info.get("found"):
            if b.get("status") != "마감":
                counts["미확인"] += 1
                b["region_scope"] = None
                b["eligible"] = False
                b["region_check"] = {
                    "verified": False, "eligible_confirmed": None,
                    "note": "K-water 전자조달시스템에서 참가자격을 아직 확인하지 못함 - 공고문 확인 필요",
                    "snippet": "",
                }
            continue
        if info.get("private"):
            counts["수의시담"] += 1
            b["region_scope"] = None
            b["eligible"] = False
            b["restrictions"] = "수의계약(시담) - 지정 업체와의 계약"
            b["region_check"] = {
                "verified": True, "eligible_confirmed": False,
                "note": "수의계약(시담): 특정 업체와 계약하는 건이라 참가 불가",
                "snippet": info.get("qualification", "")[:150],
            }
            continue
        if info.get("licenses"):
            b["industry"] = ",".join(info["licenses"])
            b["licenses"] = info["licenses"]
        b["notice_kind"] = "공사"
        regions = info.get("regions") or []
        if regions:
            scope = get_region_scope(",".join(regions), "", "", has_region_restriction=True)
            counts["지역제한"] += 1
            if scope is None:
                counts["참가불가지역"] += 1
            b["participation_regions"] = regions
            b["region"] = ",".join(regions)
            b["restrictions"] = f"지역제한({','.join(regions)})"
            b["region_scope"] = scope
            b["eligible"] = scope is not None
            b["region_check"] = {
                "verified": True, "eligible_confirmed": scope if scope is not None else False,
                "note": f"K-water {info.get('basis')}으로 지역제한 확인함",
                "snippet": info.get("qualification", "")[:150],
            }
        else:
            counts["미확인"] += 1
            b["region_scope"] = None
            b["eligible"] = False
            b["region_check"] = {
                "verified": False, "eligible_confirmed": None,
                "note": f"K-water 참가자격에서 지역을 확인하지 못함({info.get('basis')}) - 공고문 확인 필요",
                "snippet": info.get("qualification", "")[:150],
            }
    print(
        f"[수자원 지역] 수의시담(참가불가) {counts['수의시담']}건, 지역제한 {counts['지역제한']}건"
        f"(그중 참가불가 {counts['참가불가지역']}건), 미확인 {counts['미확인']}건, 조회 실패 {len(failed)}건"
    )
