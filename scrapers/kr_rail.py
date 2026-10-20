"""
국가철도공단 KR전자조달시스템(ebid.kr.or.kr) 공사 입찰공고 수집기.

2026-10-20: 대박 맞춤입찰정보 대조에서 "서해선 전동열차 운정역 연장운행 통신설비 개량 기타공사"
(2026-01-000231-00, 통신·전국,서울,경기)가 우리 화면에 없었다. 국가철도공단은 나라장터가 아닌
자체 전자조달시스템에 공사를 공고하고, 공공데이터포털에도 공고 목록 API가 없다.
로그인 없이 열리는 화면을 그대로 쓴다:
  1) POST /bid/anc/bidAncList.do (schGgGubun=01 공사, pageIndex) → 목록(공고번호, 공고명, 설계금액, 게시일, 상태)
  2) POST /bid/anc/bidAncDetail.do → 입찰서 접수마감·개찰일시·자격등록 마감·낙찰하한율·첨부파일
  3) GET /common/FileDown.do → 입찰공고문(HWPX/HWP/PDF)에서 면허·지역제한·지역의무공동도급 지역을 읽는다.
공고 하나에 요청 2~3번이라 캐시(data/kr_rail_cache.json)에 공고문 판정을 남긴다.
"""

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GYEONGGI_OTHER_CITIES, LOOKBACK_DAYS
from scrapers._common import get_region_scope, is_deadline_in_range, apply_license_rule
from scrapers.doc_regions import document_text, extract_restricted_regions, extract_licenses, _PROVINCES

BASE = "https://ebid.kr.or.kr"
LIST_URL = f"{BASE}/bid/anc/bidAncList.do?menuNo=14000"
DETAIL_URL = f"{BASE}/bid/anc/bidAncDetail.do"
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "kr_rail_cache.json")
MAX_PAGES = 10
_DETAIL_KEYS = "gyErBeonho crSangtae ggDrIrja ggNyeondo ggIrBeonho ygGeumaeg ggChasu cjbcDrMyeong irBeonho ggGubun".split()


def _text(h):
    h = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def _file_url(file_id, name):
    # 사이트의 download()는 encodeURI(encodeURIComponent(x))로 넘긴다 - 한 번 인코딩한 값과 같다.
    return (f"{BASE}/common/FileDown.do?atchFileId={quote(file_id, safe='')}"
            f"&orignlFileNm={quote(name, safe='')}&atchDirId=TENDER_DIR_UPLOAD")


def _list(session):
    """(상세 인자 목록, 공고명, 상태) 목록. 게시일이 LOOKBACK_DAYS보다 오래되면 멈춘다."""
    since = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    out = []
    for page in range(1, MAX_PAGES + 1):
        h = session.post(LIST_URL, data={"pageIndex": str(page), "schGgGubun": "01"}, timeout=40).text
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, flags=re.S)
        got = old = 0
        for row in rows:
            m = re.search(r"detail\(([^)]*)\)", row)
            if not m:
                continue
            args = [a.strip().strip("'") for a in m.group(1).split(",")]
            if len(args) != len(_DETAIL_KEYS):
                continue
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
            got += 1
            if args[2][:10] < since:
                old += 1
                continue
            out.append({"args": args, "cells": cells})
        if not got or old == got:
            break
        time.sleep(0.5)
    return out


def _field(text, label):
    m = re.search(re.escape(label) + r"\s*([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})", text)
    return m.group(1) if m else ""


def _joint_duty_regions(text):
    m = re.search(r"지역의무\s*공동(?:계약|도급)\s*\(([^)]{2,60})\)", text)
    if not m:
        return []
    regions = []
    for pat, name in _PROVINCES + [(r"경기", "경기도")]:
        if re.search(pat, m.group(1)) and name not in regions:
            regions.append(name)
    return regions


def _notice_doc(session, detail_html):
    """첨부 중 입찰공고문 (주소, 이름)."""
    files = re.findall(r"download\('([^']+)',\s*'([^']+)',\s*'TENDER_DIR_UPLOAD'\)", detail_html)
    for fid, name in files:
        if "공고" in name:
            return _file_url(fid, name), name
    return (_file_url(*files[0]), files[0][1]) if files else (None, None)


def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_kr_rail_bids():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"
    cache = _load_cache()
    rows = _list(session)
    results, read_docs, failed = [], 0, 0
    for r in rows:
        args, cells = r["args"], r["cells"]
        notice_no = next((c for c in cells if re.fullmatch(r"\d{4}-\d{2}-\d{6}-\d{2}", c)), "")
        title = next((c for c in cells if len(c) > 8 and not re.fullmatch(r"[\d,\-: .]+", c) and c != notice_no), "")
        state = cells[-1] if cells else ""
        if not notice_no or "무효" in state or "취소" in state:
            continue
        info = cache.get(notice_no)
        if info is None:
            try:
                dh = session.post(DETAIL_URL, data=dict(zip(_DETAIL_KEYS, args)), timeout=40).text
                dt = _text(dh)
                url, name = _notice_doc(session, dh)
                doc = ""
                if url:
                    doc = document_text(session.get(url, timeout=90).content, name) or ""
                    read_docs += 1
                info = {
                    "deadline": _field(dt, "입찰서 접수마감일시"),
                    "open_date": _field(dt, "개찰일시"),
                    "reg_deadline": _field(dt, "입찰참가자 자격등록 마감일시"),
                    "lower_rate": (re.search(r"낙찰하한율\(%\)\s*([\d.]+)", dt) or [None, ""])[1],
                    "url": url or "",
                    "licenses": extract_licenses(doc) if doc else [],
                    "regions": extract_restricted_regions(doc, GYEONGGI_OTHER_CITIES) if doc else [],
                    "joint_duty_regions": _joint_duty_regions(doc) if doc else [],
                    "doc_read": bool(doc),
                    "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                if info["deadline"]:
                    cache[notice_no] = info
                time.sleep(0.5)
            except Exception as e:
                failed += 1
                print(f"[국가철도공단] {notice_no} 상세 실패: {e}")
                continue
        if not is_deadline_in_range(info.get("deadline", "")):
            continue
        bid = {
            "source": "국가철도공단",
            "title": title,
            "org": "국가철도공단",
            "notice_no": notice_no,
            "notice_kind": "공사",
            "base_amount": args[5],
            "notice_date": args[2][:10],
            "reg_deadline": info.get("reg_deadline", ""),
            "deadline": info.get("deadline", ""),
            "open_date": info.get("open_date", ""),
            "successful_bid_lower_rate": info.get("lower_rate", ""),
            "url": info.get("url") or "https://ebid.kr.or.kr/bid/anc/bidAncList.do?menuNo=14000",
            "industry": ",".join(info.get("licenses") or []),
            "licenses": info.get("licenses") or [],
            "joint_duty_regions": info.get("joint_duty_regions") or [],
            "restrictions": "지역의무공동도급" if info.get("joint_duty_regions") else "",
        }
        regions = info.get("regions") or []
        if not info.get("doc_read"):
            bid.update({"region_scope": None, "eligible": False, "region_check": {
                "verified": False, "eligible_confirmed": None,
                "note": "국가철도공단 입찰공고문을 읽지 못함 - 공고문 확인 필요", "snippet": ""}})
        elif regions:
            scope = get_region_scope(",".join(regions), "", "", has_region_restriction=True)
            bid.update({"participation_regions": regions, "region": ",".join(regions),
                        "restrictions": ",".join(x for x in (bid["restrictions"], f"지역제한({','.join(regions)})") if x),
                        "region_scope": scope, "eligible": scope is not None,
                        "region_check": {"verified": True, "eligible_confirmed": scope if scope is not None else False,
                                         "note": "국가철도공단 입찰공고문으로 지역제한 확인함", "snippet": ",".join(regions)}})
        else:
            bid.update({"participation_regions": [], "region_scope": "전국", "eligible": True,
                        "region_check": {"verified": True, "eligible_confirmed": "전국",
                                         "note": "국가철도공단 입찰공고문에 지역제한 없음", "snippet": ""}})
        apply_license_rule(bid, bid["licenses"], "국가철도공단")
        results.append(bid)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    tel = sum(1 for b in results if "정보통신" in b["industry"])
    print(f"[국가철도공단] 목록 {len(rows)}건 → 마감 범위 내 공사 {len(results)}건 (정보통신 면허 {tel}건, "
          f"공고문 새로 읽음 {read_docs}건, 실패 {failed}건)")
    return results


if __name__ == "__main__":
    for b in fetch_kr_rail_bids():
        print(b["notice_no"], b["deadline"], b["region_scope"], b["industry"], b["joint_duty_regions"], b["title"][:40])
