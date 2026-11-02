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
                print(f"    first={json.dumps(first, ensure_ascii=False)[:2500]}")
            if not first:
                print(f"    raw={txt[:600]!r}")
        except Exception:
            print(f"[{label}] HTTP {r.status_code} (not json) {txt[:600]!r}")
    except Exception as e:
        print(f"[{label}] 요청 실패 {type(e).__name__}: {e}")


now = datetime.now()
d = lambda days: (now - timedelta(days=days)).strftime("%Y%m%d")

# 2026-11-02: PlayMCP "나라장터 조달정보"가 쓰는 공공데이터개방표준서비스(15058815)를 우리 키로 직접 쓸 수 있는지 확인.
# 계약정보는 아직 수집하지 않는 데이터(수의계약 포함)다.
STD = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"
base = {"pageNo": 1, "numOfRows": 20, "type": "json"}
show("표준/입찰공고", STD + "/getDataSetOpnStdBidPblancInfo",
     {**base, "bidNtceBgnDt": d(3) + "0000", "bidNtceEndDt": d(0) + "2359"}, G2B)
show("표준/낙찰", STD + "/getDataSetOpnStdScsbidInfo",
     {**base, "bsnsDivCd": "3", "opengBgnDt": d(3) + "0000", "opengEndDt": d(3) + "2359"}, G2B)
show("표준/계약 7일", STD + "/getDataSetOpnStdCntrctInfo",
     {**base, "cntrctCnclsBgnDate": d(7), "cntrctCnclsEndDate": d(1)}, G2B)
show("표준/계약 공사 3일", STD + "/getDataSetOpnStdCntrctInfo",
     {**base, "bsnsDivCd": "3", "cntrctCnclsBgnDate": d(3), "cntrctCnclsEndDate": d(1)}, G2B)
# 비교: 계약정보서비스(별도 데이터셋)
CN = "https://apis.data.go.kr/1230000/ao/CntrctInfoService/getCntrctInfoListCnstwk"
show("계약정보서비스/공사", CN, {**base, "inqryDiv": 1, "inqryBgnDt": d(3) + "0000", "inqryEndDt": d(1) + "2359"}, G2B)
