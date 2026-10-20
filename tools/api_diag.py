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

# 2026-10-20: 발주계획 PPSSrch는 inqryBgnDt/inqryEndDt를 무시하고 최근 하루치(387건)만 준다.
# 문서상 "발주년월범위"로 검색 - 발주년월 파라미터 이름 후보를 시험한다.
SRCH = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwkPPSSrch"
BASE_OP = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwk"
ym0, ym1 = now.strftime("%Y%m"), (now + timedelta(days=75)).strftime("%Y%m")
cands = [
    ("1 orderBgnYm", {"inqryDiv": 1, "orderBgnYm": ym0, "orderEndYm": ym1}),
    ("2 orderBgnYm", {"inqryDiv": 2, "orderBgnYm": ym0, "orderEndYm": ym1}),
    ("2 inqryBgnDt YYYYMM 00", {"inqryDiv": 2, "inqryBgnDt": ym0 + "010000", "inqryEndDt": ym1 + "282359"}),
    ("2 inqryBgnDt YYYYMMDD", {"inqryDiv": 2, "inqryBgnDt": ym0 + "01", "inqryEndDt": ym1 + "28"}),
    ("orderYear+orderMnth", {"inqryDiv": 1, "orderYear": now.strftime("%Y"), "orderMnth": now.strftime("%m")}),
    ("1 inqryBgnDt 1년 numOfRows 10", {"inqryDiv": 1, "inqryBgnDt": d(365) + "0000", "inqryEndDt": d(300) + "2359"}),
    ("3 inqryBgnDt", {"inqryDiv": 3, "inqryBgnDt": d(60) + "0000", "inqryEndDt": d(30) + "2359"}),
]
for label, p in cands:
    show("발주계획PPS/" + label, SRCH, {"pageNo": 1, "numOfRows": 500, "type": "json", **p}, G2B)
for label, p in cands[:4]:
    show("발주계획기본/" + label, BASE_OP, {"pageNo": 1, "numOfRows": 500, "type": "json", **p}, G2B)
