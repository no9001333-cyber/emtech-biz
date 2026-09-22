"""
진단 전용(2026-09-22): 대박 나의투찰결과(myresult)에는 낙찰자/낙찰금액이 이미 떠 있는데
우리 나라장터 낙찰정보 수집(g2b_awards.py)에는 없는 공고 10건을, inqryDiv=4(입찰공고번호
기준)로 직접 조회해서 API에 아예 데이터가 없는 건지(아직 낙찰 미확정) 아니면 날짜 조회
구간(inqryDiv=3, 개찰일시) 쪽 버그로 놓치고 있는 건지 가른다. 수집 결과에는 영향 없음.
"""
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_AWARDS_SERVICE_KEY
from scrapers._common import get_with_retry
from scrapers.g2b_awards import ENDPOINT, OPERATION, _clean_key

PROBE_NOS = [
    "R26BK01725425", "R26BK01730364", "R26BK01705740", "R26BK01721734",
    "R26BK01704127", "R26BK01698121", "R26BK01699872", "R26BK01695590",
    "R26BK01695314", "R26BK01690487",
]


def probe_missing_awards():
    if not G2B_AWARDS_SERVICE_KEY:
        return
    for no in PROBE_NOS:
        params = {
            "serviceKey": _clean_key(G2B_AWARDS_SERVICE_KEY), "pageNo": 1, "numOfRows": 5,
            "type": "json", "inqryDiv": 4, "bidNtceNo": no,
        }
        try:
            data = get_with_retry(f"{ENDPOINT}/{OPERATION}", params=params, timeout=30).json()
            body = data.get("response", {}).get("body", {})
            total = body.get("totalCount", 0)
            items = body.get("items", [])
            if isinstance(items, dict):
                items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]
            first = items[0] if items else {}
            print(f"[낙찰정보 진단] {no}: {total}건 낙찰자={first.get('bidwinnrNm')} "
                  f"개찰일={first.get('rlOpengDt')} 낙찰금액={first.get('sucsfbidAmt')}")
        except Exception as e:
            print(f"[낙찰정보 진단] {no}: 실패 {e}")
        time.sleep(0.3)
