"""
나라장터(조달청) 낙찰정보(개찰결과) 수집기
공공데이터포털의 "조달청_나라장터 낙찰정보서비스" OpenAPI 사용

사전 준비:
1) https://www.data.go.kr 에서 "나라장터 낙찰정보서비스" 검색 → 활용신청 (자동승인)
   (※ 입찰공고정보서비스와는 별개의 서비스라 별도로 신청해야 합니다)
2) 발급받은 서비스키를 환경변수 G2B_AWARDS_SERVICE_KEY 로 설정
   (나라장터 입찰공고정보서비스와 같은 계정이면 같은 인증키를 써도 되는 경우가 많습니다.
   안 되면 이 서비스도 별도로 활용신청 후 발급받은 키를 넣어주세요)

참고: data.go.kr의 "조달청_나라장터 낙찰정보서비스" Swagger 문서 기준 Base URL은
      apis.data.go.kr/1230000/as/ScsbidInfoService 입니다 (경로가 /ad/ 가 아니라 /as/ 입니다).
      오퍼레이션명(getScsbidListSttusCnstwk)과 파라미터는 문서와 일치합니다.
"""

import sys
import os
import time
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import G2B_AWARDS_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_with_retry

ENDPOINT = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
# 공사(工事) 낙찰(개찰결과) 목록 조회 오퍼레이션
OPERATION = "getScsbidListSttusCnstwk"


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key)


def _fetch_page(begin_dt: str, end_dt: str, page_no: int, num_of_rows: int = 500):
    url = f"{ENDPOINT}/{OPERATION}"
    params = {
        "serviceKey": _clean_key(G2B_AWARDS_SERVICE_KEY),
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        # 2026-08-20: inqryDiv=1(등록일시) 기준으로 조회하고 있었는데, 이 API의
        # 조회구분은 1=등록일시, 2=공고일시, 3=개찰일시, 4=입찰공고번호다(공식
        # 참고자료로 확인함). "등록일시"는 이 낙찰 레코드가 시스템에 입력된
        # 시점일 뿐 실제 개찰일(rlOpengDt, 화면의 open_date)과 무관하게 흩어져
        # 있어서, 실제로는 올해 1월부터 지금까지 뒤섞인 결과가 7,500건 상한에
        # 걸려 최근 개찰 결과 상당수가 누락되고 있었다. 우리가 원하는 건 "최근
        # LOOKBACK_DAYS일 안에 개찰된 것"이므로 3(개찰일시) 기준으로 바꾼다.
        "inqryDiv": 3,
        "inqryBgnDt": begin_dt,
        "inqryEndDt": end_dt,
        "type": "json",
    }
    resp = get_with_retry(url, params=params, timeout=30)
    return resp.json()


def fetch_g2b_awards():
    """나라장터 공사 낙찰(개찰결과) 정보를 최근 LOOKBACK_DAYS일 이내 기준으로 가져온다.

    예전 코드는 1페이지(최대 500건)만 조회하고 끝냈는데, 실제로 매번 정확히
    500건이 잡혀서(=딱 페이지 한도만큼) 그 뒤에 더 있는데 잘려나가고 있었던
    것으로 보입니다. g2b.py의 입찰공고 수집과 동일하게 totalCount를 보고
    필요한 만큼 다음 페이지를 계속 가져오도록 고쳤습니다. 이렇게 해야 마감된
    공고에 낙찰결과(낙찰자/낙찰금액)가 실제보다 적게 붙는 문제를 막을 수 있습니다.
    """
    if not G2B_AWARDS_SERVICE_KEY:
        print("[낙찰정보] 서비스키(G2B_AWARDS_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    begin_dt = begin.strftime("%Y%m%d0000")
    end_dt = end.strftime("%Y%m%d2359")

    results = []
    page_no = 1
    MAX_PAGES = 15  # 안전장치: 최대 15페이지(=최대 7,500건)까지만 수집

    while page_no <= MAX_PAGES:
        try:
            data = _fetch_page(begin_dt, end_dt, page_no)
        except Exception as e:
            print(f"[낙찰정보] 요청 실패: {e}")
            break

        body = data.get("response", {}).get("body", {}) if isinstance(data, dict) else {}
        items = body.get("items", [])
        if isinstance(items, dict):
            items = items.get("item", [])
        if not items:
            break

        if page_no == 1:
            print(f"[낙찰정보] 응답 필드명 예시: {list(items[0].keys())}")

        for item in items:
            # 낙찰(예정)금액이 있는 것만 유의미한 결과로 취급
            award_amount = item.get("sucsfbidAmt") or item.get("scsbidAmt", "")

            results.append({
                "source": "나라장터",
                "title": item.get("bidNtceNm", ""),
                # ntceInsttNm(발주기관명)은 이 API 응답엔 없어서, 대신 있는
                # dminsttNm(수요기관명)으로 대체
                "org": item.get("ntceInsttNm") or item.get("dminsttNm", ""),
                "notice_no": item.get("bidNtceNo", ""),
                # 예전엔 prcbdrNm/opengCorpNm으로 추정해서 항상 빈 값이었음.
                # 위 필드명 로그로 확인한 실제 필드는 bidwinnrNm(낙찰자명).
                "winner": item.get("bidwinnrNm", ""),
                # 협상 완료 후 최종낙찰업체 연락처. 공식 API 문서에 따르면 휴대폰번호는
                # "*"로 마스킹되어 내려온다(공공데이터포털 정책) - 그런 경우는 버그가 아님.
                "winner_tel": item.get("bidwinnrTelNo", ""),
                "award_amount": award_amount,
                "base_amount": item.get("presmptPrce", ""),
                "assessed_rate": item.get("sucsfbidRate") or item.get("bidprcRate", ""),
                # 예전엔 opengDt로 추정했는데 이 응답엔 그 필드가 아예 없었음.
                # 실제 필드는 rlOpengDt(실제개찰일시), 없으면 fnlSucsfDate(최종낙찰일자)
                "open_date": item.get("rlOpengDt") or item.get("fnlSucsfDate", ""),
                "url": item.get("bidNtceDtlUrl", ""),
            })

        total_count = int(body.get("totalCount", 0))
        if page_no * 500 >= total_count:
            break
        if page_no == MAX_PAGES:
            # 안전장치(MAX_PAGES) 때문에 실제로 더 있는 데이터를 못 가져오고
            # 잘라내는 상황 - 조용히 넘어가면 다음에 또 못 알아차리니 경고를 남긴다.
            print(f"[낙찰정보] 경고: 실제 총 {total_count}건인데 상한({MAX_PAGES*500}건)에 걸려 나머지를 못 가져옴 - LOOKBACK_DAYS를 줄이거나 MAX_PAGES를 늘려야 할 수 있음")
            break
        page_no += 1
        time.sleep(1)  # 요청 사이 1초씩 쉬어서 너무 빠르게 몰아치지 않게 함

    print(f"[낙찰정보] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for a in fetch_g2b_awards():
        print(a)
