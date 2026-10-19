"""
나라장터 개찰결과 "예비가격상세"(조달청_나라장터 낙찰정보서비스 getOpengResultListInfoCnstwkPreparPcDetail)로
개찰된 공사의 기초금액·예정가격을 받아 사정율(예정가격/기초금액) 이력을 쌓는다.

2026-10-19: 투찰가 추천을 만들려면 "비슷한 공고에서 사정율이 얼마로 나왔는지"가 필요한데,
우리 데이터의 기초금액은 대부분 예산액으로 대신 채워진 값이었다(기초금액 조회가 전부 실패 -
g2b_basis_amount.py 참고). 개찰이 끝난 공고는 이 오퍼레이션이 기초금액(bssamt)과
예정가격(plnprc), 복수예비가격 15개·추첨 여부를 공고번호 단위로 준다.

호출량을 아끼기 위해 낙찰정보(awards) 중 통신 관련 공사를 우선, 한 번 실행에 MAX_CALLS건까지만
새로 조회하고 결과는 data/rate_history.json에 계속 누적한다(공개 데이터만 담음).
응답 필드명은 첫 응답을 로그로 남기고 후보 이름으로 읽는다.
"""

import json
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_AWARDS_SERVICE_KEY, G2B_SERVICE_KEY, KEYWORDS
from scrapers._common import get_with_retry

ENDPOINT = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoCnstwkPreparPcDetail"
MAX_CALLS = 250
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rate_history.json")


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _pick(item, *names):
    for n in names:
        if item.get(n) not in (None, ""):
            return item.get(n)
    return None


def _load():
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _fetch(notice_no, key, logged):
    params = {"serviceKey": key, "pageNo": 1, "numOfRows": 50, "type": "json",
              "inqryDiv": 4, "bidNtceNo": notice_no}
    data = get_with_retry(ENDPOINT, params=params, timeout=30).json()
    body = data.get("response", {}).get("body", {})
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    if items and not logged[0]:
        print(f"[사정율 이력] 예비가격상세 응답 필드명 예시: {list(items[0].keys())}")
        logged[0] = True
    return items


def update_rate_history(awards, bids_by_key):
    """awards(낙찰정보)로 사정율 이력을 갱신하고 이력 dict를 돌려준다."""
    key_raw = G2B_AWARDS_SERVICE_KEY or G2B_SERVICE_KEY
    history = _load()
    if not key_raw:
        return history
    key = __import__("urllib.parse").parse.unquote(key_raw)

    def is_telecom(a):
        b = bids_by_key.get(f"나라장터::{a.get('notice_no')}") or {}
        return any(k in (a.get("title", "") + " " + (b.get("industry") or "")) for k in KEYWORDS)

    todo = [a for a in awards if a.get("source") == "나라장터" and a.get("notice_no")
            and a["notice_no"] not in history]
    # 통신 관련 → 경기/용인/전국 → 나머지 순으로, 최근 개찰부터
    todo.sort(key=lambda a: a.get("open_date") or "", reverse=True)
    todo.sort(key=lambda a: (not is_telecom(a), a.get("region_scope") not in ("경기", "용인", "전국")))
    todo = todo[:MAX_CALLS]
    logged, added, failed = [False], 0, 0
    for a in todo:
        try:
            items = _fetch(a["notice_no"], key, logged)
        except Exception as e:
            failed += 1
            if failed >= 5 and added == 0:
                print(f"[사정율 이력] 연속 실패로 중단 - 활용신청/호출한도 확인 필요: {type(e).__name__} {getattr(getattr(e, 'response', None), 'status_code', '')}")
                break
            continue
        time.sleep(0.3)
        if not items:
            history[a["notice_no"]] = {"empty": True}
            continue
        first = items[0]
        base = _num(_pick(first, "bssamt", "bsisAmt", "bssAmt"))
        planned = _num(_pick(first, "plnprc", "plnPrc", "prearngPrcePurcsAmt", "presmptPrce"))
        if not (base and planned):
            history[a["notice_no"]] = {"empty": True, "fields": list(first.keys())[:30]}
            continue
        b = bids_by_key.get(f"나라장터::{a['notice_no']}") or {}
        history[a["notice_no"]] = {
            "title": a.get("title", ""), "org": a.get("org", ""), "open_date": a.get("open_date", ""),
            "region_scope": a.get("region_scope"), "telecom": is_telecom(a),
            "base": base, "planned": planned, "sajung": round(planned / base * 100, 4),
            "award_amount": _num(a.get("award_amount")), "award_rate": _num(a.get("assessed_rate")),
            "winner": a.get("winner", ""), "lower_rate": _num(b.get("successful_bid_lower_rate")),
        }
        added += 1
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    real = sum(1 for v in history.values() if "sajung" in v)
    print(f"[사정율 이력] 새로 {added}건 추가(조회 {len(todo)}건, 실패 {failed}건), 누적 {real}건")
    return history
