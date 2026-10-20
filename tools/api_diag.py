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
            if items:
                rg = sorted(str(x.get("rgstDt") or x.get("nticeDt") or "")[:10] for x in items)
                om = sorted({f"{x.get('orderYear')}-{x.get('orderMnth')}" for x in items})
                print(f"    rgstDt {rg[0]} ~ {rg[-1]}, 발주시기 {om[:12]}")
            if first:
                print(f"    keys={list(first.keys())}")
                print(f"    first={json.dumps(first, ensure_ascii=False)[:700]}")
            if not first:
                print(f"    raw={txt[:600]!r}")
        except Exception:
            print(f"[{label}] HTTP {r.status_code} (not json) {txt[:600]!r}")
    except Exception as e:
        print(f"[{label}] 요청 실패 {type(e).__name__}: {e}")


now = datetime.now()
d = lambda days: (now - timedelta(days=days)).strftime("%Y%m%d")

# 2026-10-20: 발주계획 PPSSrch가 1년치를 요청해도 전날 등록분만 오는지(저장 3건이 모두 10-19 등록) 확인
SRCH = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwkPPSSrch"
for label, p in [
    ("등록일 1일", {"inqryDiv": 1, "inqryBgnDt": d(1) + "0000", "inqryEndDt": d(0) + "2359"}),
    ("등록일 7일", {"inqryDiv": 1, "inqryBgnDt": d(7) + "0000", "inqryEndDt": d(0) + "2359"}),
    ("등록일 30일", {"inqryDiv": 1, "inqryBgnDt": d(30) + "0000", "inqryEndDt": d(0) + "2359"}),
    ("등록일 60~30일 전", {"inqryDiv": 1, "inqryBgnDt": d(60) + "0000", "inqryEndDt": d(30) + "2359"}),
    ("등록일 2026-01", {"inqryDiv": 1, "inqryBgnDt": "202601010000", "inqryEndDt": "202601312359"}),
    ("inqryDiv=2 발주년월", {"inqryDiv": 2, "inqryBgnDt": now.strftime("%Y%m"), "inqryEndDt": (now + timedelta(days=90)).strftime("%Y%m")}),
    ("inqryDiv=2 일자", {"inqryDiv": 2, "inqryBgnDt": d(0) + "0000", "inqryEndDt": (now + timedelta(days=90)).strftime("%Y%m%d") + "2359"}),
    ("통신 공사지역 경기", {"inqryDiv": 1, "inqryBgnDt": d(90) + "0000", "inqryEndDt": d(0) + "2359", "cnstwkRgnNm": "경기"}),
    ("사업명 통신", {"inqryDiv": 1, "inqryBgnDt": d(90) + "0000", "inqryEndDt": d(0) + "2359", "bizNm": "통신"}),
]:
    show("발주계획/" + label, SRCH, {"pageNo": 1, "numOfRows": 500, "type": "json", **p}, G2B)
