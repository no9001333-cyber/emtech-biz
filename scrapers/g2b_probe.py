"""
진단 전용(2026-09-21): 대박 맞춤입찰정보에는 있는데 우리 수집에는 없는 나라장터 공고가
나라장터 공식 API의 어느 오퍼레이션에 들어 있는지 공고번호로 직접 조회해 로그로 남긴다.
수집 결과에는 영향을 주지 않는다(예외는 모두 삼킨다).
"""
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_SERVICE_KEY
from scrapers._common import get_with_retry
from scrapers.g2b import ENDPOINT, _clean_key

PROBE_NOS = [
    "R26BK01736105",  # GH 창업특화주택 인테리어공사(통신)
    "R26BK01738267",  # (가칭)능동1초 신축 통신공사
    "R26BK01686309",  # 다산 복합커뮤니티센터
    "R26BK01704458",  # 금정역세권1구역 시공자 선정(2차)
    "R26BK01715692",  # 강북3재정비촉진구역 시공자 선정
    "R26BK01732177",  # 경주 스마트생태공장 (업종 필드 확인용)
]
PROBE_OPS = [
    "getBidPblancListInfoCnstwk", "getBidPblancListInfoServc",
    "getBidPblancListInfoEtc", "getBidPblancListInfoThng",
    "getBidPblancListInfoFrgcpt",
]


def probe_missing_notices():
    if not G2B_SERVICE_KEY:
        return
    for no in PROBE_NOS:
        for op in PROBE_OPS:
            params = {
                "serviceKey": _clean_key(G2B_SERVICE_KEY), "pageNo": 1, "numOfRows": 5,
                "type": "json", "inqryDiv": 2, "bidNtceNo": no,
            }
            try:
                data = get_with_retry(f"{ENDPOINT}/{op}", params=params, timeout=30).json()
                body = data.get("response", {}).get("body", {})
                total = body.get("totalCount", 0)
                items = body.get("items", [])
                if isinstance(items, dict):
                    items = items.get("item", [])
                if isinstance(items, dict):
                    items = [items]
                first = items[0] if items else {}
                print(f"[G2B 진단] {no} {op}: {total}건 title={first.get('bidNtceNm')} "
                      f"게시일={first.get('bidNtceDt')} indstryty={first.get('indstrytyNm') or first.get('mainCnsttyNm')}"
                      f" 필드={list(first.keys())[:0]}")
            except Exception as e:
                print(f"[G2B 진단] {no} {op}: 실패 {e}")
            time.sleep(0.3)
