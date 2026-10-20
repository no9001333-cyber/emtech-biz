"""
API 진단(수동 실행 전용, .github/workflows/diag.yml). 수집과 무관하게 몇 분 안에 끝난다.
새로 붙인 data.go.kr 오퍼레이션의 실제 응답을 파라미터 조합별로 찍어 맞는 호출 방식을 찾는다.
서비스키는 출력하지 않는다(GitHub도 마스킹함).
"""
import json
import os
import urllib.parse
from datetime import datetime, timedelta

import requests

G2B = urllib.parse.unquote(os.environ.get("G2B_SERVICE_KEY", ""))
AWD = urllib.parse.unquote(os.environ.get("G2B_AWARDS_SERVICE_KEY", "")) or G2B


def show(label, url, params, key):
    try:
        r = requests.get(url, params={**params, "serviceKey": key}, timeout=40)
        txt = r.text
        try:
            j = r.json()
            h = j.get("response", {}).get("header", {})
            b = j.get("response", {}).get("body", {})
            items = b.get("items", [])
            if isinstance(items, dict):
                items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]
            first = items[0] if items else {}
            print(f"[{label}] HTTP {r.status_code} code={h.get('resultCode')} msg={h.get('resultMsg')} total={b.get('totalCount')} n={len(items)}")
            if first:
                print(f"    keys={list(first.keys())}")
                print(f"    first={json.dumps(first, ensure_ascii=False)[:700]}")
        except Exception:
            print(f"[{label}] HTTP {r.status_code} (not json) {txt[:300]!r}")
    except Exception as e:
        print(f"[{label}] 요청 실패 {type(e).__name__}: {e}")


now = datetime.now()
d = lambda days: (now - timedelta(days=days)).strftime("%Y%m%d")

PREP = "https://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoCnstwkPreparPcDetail"
NO = "R26BK01754526"  # 2026-10-12 개찰된 통신공사
for label, p in [
    ("예비가격/공고번호 inqryDiv=4", {"inqryDiv": 4, "bidNtceNo": NO}),
    ("예비가격/공고번호 inqryDiv=2", {"inqryDiv": 2, "bidNtceNo": NO}),
    ("예비가격/공고번호+차수", {"inqryDiv": 4, "bidNtceNo": NO, "bidNtceOrd": "000"}),
    ("예비가격/개찰일 범위", {"inqryDiv": 3, "inqryBgnDt": d(9) + "0000", "inqryEndDt": d(7) + "2359"}),
    ("예비가격/등록일 범위", {"inqryDiv": 1, "inqryBgnDt": d(9) + "0000", "inqryEndDt": d(7) + "2359"}),
]:
    show(label, PREP, {"pageNo": 1, "numOfRows": 20, "type": "json", **p}, AWD)
    show(label + " (입찰공고키)", PREP, {"pageNo": 1, "numOfRows": 20, "type": "json", **p}, G2B) if AWD != G2B else None

PLAN = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwk"
for label, p in [
    ("발주계획/등록일 30일 inqryDiv=1", {"inqryDiv": 1, "inqryBgnDt": d(30) + "0000", "inqryEndDt": d(0) + "2359"}),
    ("발주계획/inqryDiv 없음", {"inqryBgnDt": d(30) + "0000", "inqryEndDt": d(0) + "2359"}),
    ("발주계획/날짜 8자리", {"inqryDiv": 1, "inqryBgnDt": d(30), "inqryEndDt": d(0)}),
    ("발주계획/발주년월", {"inqryDiv": 2, "orderBgnYm": now.strftime("%Y%m"), "orderEndYm": (now + timedelta(days=90)).strftime("%Y%m")}),
    ("발주계획/파라미터 없음", {}),
]:
    show(label, PLAN, {"pageNo": 1, "numOfRows": 10, "type": "json", **p}, G2B)
