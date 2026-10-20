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

# 2026-10-20: PPSSrch는 발주년월(orderBgnYm/orderEndYm)과 게시일시(inqryBgnDt/inqryEndDt)를 함께 주고
# inqryDiv는 빼야 한다(NomaDamas/k-skill 프록시 구현 참고). 함께 줘서 기간이 먹는지 확인.
SRCH = "https://apis.data.go.kr/1230000/ao/OrderPlanSttusService/getOrderPlanSttusListCnstwkPPSSrch"
ym0, ym1 = now.strftime("%Y%m"), (now + timedelta(days=180)).strftime("%Y%m")
both = {"orderBgnYm": ym0, "orderEndYm": ym1, "inqryBgnDt": d(365) + "0000", "inqryEndDt": d(0) + "2359"}
for label, p in [
    ("발주년월+게시일시", both),
    ("발주년월+게시일시 공종 통신", {**both, "cnsttyDivNm": "통신"}),
    ("발주년월+게시일시 사업명 통신", {**both, "bizNm": "통신"}),
    ("발주년월+게시일시 2페이지", {**both, "pageNo": 2}),
]:
    show("발주계획PPS/" + label, SRCH, {"pageNo": 1, "numOfRows": 500, "type": "json", **p}, G2B)
