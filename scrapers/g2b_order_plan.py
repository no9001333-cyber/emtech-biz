"""
나라장터 발주계획(조달청_나라장터 발주계획현황서비스, data.go.kr 15129462)에서
앞으로 공고될 통신 공사를 미리 찾는다.

2026-10-19: 공고가 뜬 뒤 마감까지 1주일 남짓이라 현장 확인·협력사 섭외가 늘 급했다.
기관들은 연초·분기마다 발주계획(사업명, 발주시기, 예산, 공사지역)을 나라장터에 올리므로,
이걸 매일 받아 "앞으로 1~3개월 안에 나올 경기/용인/전국 통신공사"를 미리 보여준다.

엔드포인트: apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwk
같은 data.go.kr 계정의 G2B_SERVICE_KEY를 쓰지만 이 데이터셋도 활용신청(자동승인)이 필요하다.
응답 필드명은 문서 화면에 나오지 않아 첫 응답의 필드명을 로그로 남기고 후보 이름으로 읽는다.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_SERVICE_KEY, KEYWORDS
from scrapers._common import get_with_retry, get_region_scope

# 2026-10-20 진단: 기본 오퍼레이션(getOrderPlanSttusListCnstwk)은 "필수값 입력 에러(08)"를 내고,
# 나라장터 검색조건 오퍼레이션(PPSSrch)이 등록일 범위로 정상 조회된다.
ENDPOINT = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwkPPSSrch"
LOOKBACK_DAYS = 365   # 발주계획은 연초에 한꺼번에 올라오는 경우가 많아 1년치 등록분을 본다
CHUNK_DAYS = 30
MAX_PAGES = 20
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "order_plans.json")


def _pick(item, *names):
    for n in names:
        v = item.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _all_text(item):
    return " ".join(str(v) for v in item.values() if isinstance(v, (str, int, float)))


def _order_month(item):
    """발주시기를 'YYYY-MM'으로. 필드명이 확실치 않아 후보를 차례로 본다."""
    year, mnth = _pick(item, "orderYear"), _pick(item, "orderMnth")
    if year and mnth:
        return f"{year}-{int(mnth):02d}" if mnth.isdigit() else year
    raw = _pick(item, "orderYm", "orderPlanYm", "orderBgnYm")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"{digits[:4]}-{digits[4:6]}" if len(digits) >= 6 else ""


def fetch_order_plans():
    if not G2B_SERVICE_KEY:
        return []
    key = __import__("urllib.parse").parse.unquote(G2B_SERVICE_KEY)
    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    rows, logged = [], False
    cur = begin
    while cur < end:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS), end)
        for page in range(1, MAX_PAGES + 1):
            params = {
                "serviceKey": key, "pageNo": page, "numOfRows": 500, "type": "json",
                "inqryDiv": 1, "inqryBgnDt": cur.strftime("%Y%m%d0000"), "inqryEndDt": chunk_end.strftime("%Y%m%d2359"),
            }
            try:
                data = get_with_retry(ENDPOINT, params=params, timeout=30).json()
            except Exception as e:
                print(f"[발주계획] 요청 실패 - 공공데이터포털에서 '조달청_나라장터 발주계획현황서비스' 활용신청이 필요할 수 있음: {e}")
                return []
            header = data.get("response", {}).get("header", {})
            if str(header.get("resultCode", "00")) not in ("00", "0"):
                print(f"[발주계획] resultCode={header.get('resultCode')} {header.get('resultMsg')}")
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
                print(f"[발주계획] 응답 필드명 예시: {list(items[0].keys())}")
                logged = True
            rows.extend(items)
            if page * 500 >= int(body.get("totalCount", 0) or 0):
                break
            time.sleep(0.5)
        cur = chunk_end
        time.sleep(0.5)

    this_month = datetime.now().strftime("%Y-%m")
    plans, seen = [], set()
    for it in rows:
        text = _all_text(it)
        if not any(k in text for k in KEYWORDS):
            continue
        title = _pick(it, "bizNm", "cnstwkNm", "prdctClsfcNoNm", "orderPlanNm", "bidNtceNm")
        region = _pick(it, "cnstwkRgnNm", "cnstrtsiteRgnNm", "rgnNm", "dlvrPlce", "jrsdctnDivNm")
        scope = get_region_scope(region, "", "", has_region_restriction=None) if region else "미정"
        if scope is None:
            continue  # 다른 시·도 현장
        month = _order_month(it)
        if month and month < this_month:
            continue  # 이미 지난 발주시기
        key_ = (title, _pick(it, "orderInsttNm", "dminsttNm", "ntceInsttNm"))
        if key_ in seen:
            continue
        seen.add(key_)
        plans.append({
            "title": title,
            "org": key_[1],
            "region": region,
            "region_scope": scope,
            "order_month": month,
            "amount": _pick(it, "sumOrderAmt", "orderAmt", "bdgtAmt", "asignBdgtAmt", "cnstwkAmt"),
            "contract_method": _pick(it, "cntrctMthdNm", "bidMethdNm"),
            "registered": _pick(it, "rgstDt", "nticeDt"),
            "contact": " ".join(x for x in (_pick(it, "deptNm"), _pick(it, "ofclNm"), _pick(it, "telNo")) if x),
            "work_type": _pick(it, "cnsttyDivNm"),
            "announced": _pick(it, "ntceNticeYn") == "Y",
        })
    plans.sort(key=lambda p: (p["order_month"] or "9999", p["title"]))
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(plans, f, ensure_ascii=False, indent=1)
    print(f"[발주계획] 원본 {len(rows)}건 중 통신·용인/경기/전국·발주예정 {len(plans)}건 저장")
    return plans
