"""
나라장터 공고의 진짜 기초금액/A값을 전용 오퍼레이션으로 다시 채웁니다.

배경: g2b.py가 목록 조회(getBidPblancListInfoCnstwk)에서 받는 예산금액(bdgtAmt)은
기초금액의 "잠정 추정치"일 뿐입니다. 사용자가 실제 나라장터 화면 스크린샷으로
예산금액(1,118,254,000원)과 실제 기초금액공개(1,124,760,000원)가 서로 다른
사례를 제보해서 확인했습니다. 또한 예전 코드가 A값으로 쓰던 "관급자재금액"은
투찰금액 계산(사정율) 공식에 쓰이는 진짜 A값(국민연금보험료·국민건강보험료·
퇴직공제부금비·노인장기요양보험료·산업안전보건관리비·안전관리비·품질관리비 등
법정경비 합계)과 전혀 다른 개념이었습니다 - 사용자가 제보한 "기초금액조회" 팝업
스크린샷의 "A란?" 설명과 대조해서 확인했습니다.

진짜 값은 조달청_나라장터 입찰공고정보서비스의 별도 오퍼레이션인
getBidPblancListInfoCnstwkBsisAmount(공사기초금액조회)에서만 얻을 수 있습니다
(조달청_OpenAPI참고자료_나라장터_입찰공고정보서비스_1.2.docx, 오퍼레이션 번호 6).
이 오퍼레이션은 기초금액(bssamt)뿐 아니라 A값 구성 항목 전부와, 품질관리비/
표준시장단가금액이 A값에 포함되는지 여부(Y/N)까지 함께 내려줍니다.

주의: 기초금액/A값은 보통 개찰일 즈음에야 공개됩니다("기초금액공개일시"가
찍혀있음). 아직 공개 전인 공고는 이 오퍼레이션이 데이터를 안 주므로, 그런
공고는 g2b.py가 채워둔 잠정 추정치(예산금액)를 그대로 두고 건드리지 않습니다 -
없는 값을 억지로 채우는 것보다는 "확인필요"로 남겨두는 게 안전합니다.
"""

import concurrent.futures
import sys
import os

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_SERVICE_KEY

ENDPOINT = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoCnstwkBsisAmount"
REQUEST_TIMEOUT = 20
MAX_WORKERS = 8


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key).strip()


def _to_int_or_none(v):
    try:
        s = str(v).replace(",", "").strip()
        return int(s) if s else None
    except (TypeError, ValueError):
        return None


def _fetch_one(bid_ntce_no: str, bid_ntce_ord: str):
    """공고 하나의 진짜 기초금액/A값을 조회.
    반환: (result_dict_또는_None, 실패사유_문자열_또는_None)
    아직 공개 전이거나 실패하면 result는 None이고, 실패사유에 원인 카테고리를 남긴다
    (enrich_g2b_bids_with_basis_amount가 이걸 모아서 요약 로그를 찍는다 - 개별
    공고마다 로그를 찍으면 너무 많아지므로 카테고리별 집계만 남긴다)."""
    if not bid_ntce_no:
        return None, "no_notice_no"
    params = {
        "serviceKey": _clean_key(G2B_SERVICE_KEY),
        "type": "json",
        "inqryDiv": 2,
        "numOfRows": 10,
        "pageNo": 1,
        "bidNtceNo": bid_ntce_no,
    }
    try:
        resp = requests.get(ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None, f"request_error:{type(e).__name__}"

    header = data.get("response", {}).get("header", {}) if isinstance(data, dict) else {}
    result_code = header.get("resultCode", "")

    body = data.get("response", {}).get("body", {}) if isinstance(data, dict) else {}
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if not items:
        return None, f"no_items(resultCode={result_code})"

    # bidNtceOrd(공고차수)가 일치하는 항목을 우선 찾고, 없으면 첫 항목을 씀
    # (재공고 등으로 차수가 여러 건일 수 있어서).
    item = next((i for i in items if i.get("bidNtceOrd") == bid_ntce_ord), items[0])

    bssamt = _to_int_or_none(item.get("bssamt"))
    if bssamt is None:
        return None, "bssamt_not_disclosed"  # 아직 기초금액 자체가 공개 전

    a_components = [
        _to_int_or_none(item.get("sftyMngcst")) or 0,        # 산업안전보건관리비
        _to_int_or_none(item.get("sftyChckMngcst")) or 0,    # 안전관리비
        _to_int_or_none(item.get("rtrfundNon")) or 0,        # 퇴직공제부금비
        _to_int_or_none(item.get("mrfnHealthInsrprm")) or 0, # 국민건강보험료
        _to_int_or_none(item.get("npnInsrprm")) or 0,        # 국민연금보험료
        _to_int_or_none(item.get("odsnLngtrmrcprInsrprm")) or 0,  # 노인장기요양보험료
    ]
    if item.get("qltyMngcstAObjYn") == "Y":
        a_components.append(_to_int_or_none(item.get("qltyMngcst")) or 0)  # 품질관리비
    if item.get("smkpAmtYn") == "Y":
        a_components.append(_to_int_or_none(item.get("smkpAmt")) or 0)  # 표준시장단가금액
    a_value = sum(a_components)

    return {
        "base_amount": str(bssamt),
        "a_value": str(a_value),
    }, None


def enrich_g2b_bids_with_basis_amount(bids: list) -> None:
    """나라장터 공고 리스트를 받아, 진짜 기초금액/A값이 공개된 건만 실제 값으로
    덮어쓴다(in-place). 조회 실패/미공개 공고는 g2b.py가 채워둔 잠정 추정치를
    그대로 둔다. 이 단계 전체가 실패해도 예외를 밖으로 던지지 않는다.

    대상은 eligible=True인 공고로만 한정합니다 - G2B_SERVICE_KEY는 목록 조회/
    낙찰정보 조회와 공유해서 쓰는 키라 하루 호출량 한도가 있는데, 참가 자체가
    불가능한(지역 등으로 걸러진) 공고까지 정확한 금액을 조회할 실익은 없고,
    수천 건 전체를 조회하면 다른 나라장터 기능까지 한도 초과로 망가질 위험이
    있습니다."""
    if not bids or not G2B_SERVICE_KEY:
        return

    candidates = [b for b in bids if b.get("eligible") is True]
    if not candidates:
        return

    try:
        updated = 0
        fail_reasons = {}  # 카테고리별 실패 건수 집계 (개별 로그는 너무 많아서 요약만)
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            future_to_bid = {
                pool.submit(_fetch_one, b.get("notice_no", ""), b.get("notice_ord", "000")): b
                for b in candidates
            }
            for future in concurrent.futures.as_completed(future_to_bid):
                bid = future_to_bid[future]
                try:
                    result, reason = future.result()
                except Exception as e:
                    result, reason = None, f"future_error:{type(e).__name__}"
                if result:
                    bid["base_amount"] = result["base_amount"]
                    bid["a_value"] = result["a_value"]
                    bid["base_amount_confirmed"] = True
                    updated += 1
                else:
                    fail_reasons[reason] = fail_reasons.get(reason, 0) + 1

        # 실패사유를 종류별로 최대 몇 건인지만 요약 - "대부분 아직 미공개"인지
        # "요청 자체가 죄다 실패"인지 다음 실행 로그에서 바로 구분할 수 있게.
        reason_summary = ", ".join(
            f"{k.split(':')[0].split('(')[0]}:{v}건"
            for k, v in sorted(fail_reasons.items(), key=lambda kv: -kv[1])[:6]
        )
        print(f"[나라장터 기초금액/A값 재확인] 참가가능 {len(candidates)}건 중 {updated}건을 실제 공개된 값으로 갱신함")
        if fail_reasons:
            print(f"[나라장터 기초금액/A값 재확인] 미확인 {len(candidates)-updated}건 사유 요약: {reason_summary}")
    except Exception as e:
        print(f"[나라장터 기초금액/A값 재확인] 예상치 못한 오류로 중단됨(이미 처리된 결과는 유지): {e}")
