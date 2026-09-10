"""
한국토지주택공사(LH) 입찰공고 수집기
공공데이터포털의 "한국토지주택공사 입찰공고정보_GW" OpenAPI 사용

2026-09-10: 기존에 쓰던 API("한국토지주택공사 입찰공고정보", 엔드포인트
openapi.ebid.lh.or.kr/...OpenBidInfoList.dev)가 2026-08-20 즈음 LH 전자조달
Open API 6종 고도화 과정에서 폐기(중지)됐다. 사용자 data.go.kr 마이페이지에서
해당 활용신청이 "중지" 상태로 뜨는 것을 확인함. 그동안 수집이 계속 0건
("SERVICE KEY IS NOT REGISTERED ERROR")이었던 진짜 원인이 이것.

대체 API는 "한국토지주택공사 입찰공고정보_GW"(data.go.kr 데이터번호 15159012,
수정일 2026-09-01, 자동승인)다. 요청 파라미터명(tndrbidRegDtStart/End 등)과
응답 필드명(bidnmKor, zoneRstrct1~4, tndrdocAcptEndDtm 등)은 구 API와 동일하게
유지됐고, 바뀐 건 엔드포인트와 (구 API의 EUC-KR 대신) apis.data.go.kr 표준
UTF-8 응답이라는 점 정도다. 그래서 코드 변경은 ENDPOINT 교체 + 인코딩 처리
정도로 최소화했다.

사전 준비:
1) https://www.data.go.kr → "한국토지주택공사 입찰공고정보_GW" 검색 → 활용신청
   (자동승인, 즉시 발급). ※ 구 "입찰공고정보"(_GW 없는 것)가 아니라 반드시
   "_GW" 붙은 신규 API여야 함.
2) 발급받은 서비스키를 GitHub Secrets의 LH_SERVICE_KEY 로 설정(기존 값 교체)

주의: 이 API는 XML로만 응답합니다. 조회 필수 파라미터는 입찰공고일자
      (tndrbidRegDtStart + tndrbidRegDtEnd, YYYYMMDD 8자리) 또는 공고번호(bidNum)
      중 하나입니다. 여기서는 조회기간 기준으로 시작/끝 날짜를 함께 보냅니다.
"""

import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REGIONS, ALWAYS_INCLUDE_ORGS, EXCLUDE_REGION_KEYWORDS, LH_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import is_deadline_in_range, get_region_scope

# 신규 "_GW" API. B552555 = 한국토지주택공사 기관코드, OpenBidInfoList = 서비스,
# getOpenBidInfo = "입찰정보 조회" 오퍼레이션.
ENDPOINT = "https://apis.data.go.kr/B552555/OpenBidInfoList/getOpenBidInfo"


def _clean_key(key: str) -> str:
    """data.go.kr에서 Encoding/Decoding 어느 버전의 키를 넣어도 동작하도록,
    URL 인코딩되어 있으면 한 번 풀어준다 (requests가 다시 인코딩하므로 이중 인코딩 방지).
    (2026-08-19: 앞뒤 공백/줄바꿈이 섞여 들어와도 인증 실패로 이어질 수 있어 strip 추가.
     "SERVICE KEY IS NOT REGISTERED ERROR"가 코드 문제가 아니라 실제로 등록 안 된
     키/공백 문제일 수도 있어서, 아래 fetch_lh_bids()에 키 마스킹 진단 로그도 추가함.)"""
    import urllib.parse
    return urllib.parse.unquote(key).strip()


def _xml_text(elem, tag):
    found = elem.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ""


def fetch_lh_bids():
    """LH 입찰공고 중 대상 지역에 해당하는 공고 리스트 반환 (업종 무관 전체 수집)"""
    if not LH_SERVICE_KEY:
        print("[LH] 서비스키(LH_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    key = _clean_key(LH_SERVICE_KEY)
    # 키 자체는 절대 로그에 남기지 않고, 길이/앞뒤 몇 글자만 마스킹해서 출력.
    # "SERVICE KEY IS NOT REGISTERED ERROR"가 떴을 때 원인이 (1) 진짜 미승인 키인지
    # (2) 복사 과정에서 공백/줄바꿈이 섞였거나 다른 API 키가 잘못 들어간 건지
    # 구분하는 데 씀 (실행 로그에서 이 값과 data.go.kr 마이페이지의 실제 키 길이를 대조).
    masked = f"{key[:4]}...{key[-4:]} (길이 {len(key)})" if len(key) >= 8 else "(키가 너무 짧음)"
    print(f"[LH] 사용 중인 서비스키(마스킹): {masked}")
    # 공식 문서 기준 파라미터명: tndrbidRegDtStart / tndrbidRegDtEnd (YYYYMMDD, 8자리)
    params = {
        "serviceKey": key,
        "numOfRows": 1000,
        "pageNo": 1,
        "tndrbidRegDtStart": begin.strftime("%Y%m%d"),
        "tndrbidRegDtEnd": end.strftime("%Y%m%d"),
    }

    try:
        resp = requests.get(ENDPOINT, params=params, timeout=30)
        resp.raise_for_status()
        # 신규 apis.data.go.kr API는 UTF-8 응답이지만, 혹시 몰라 UTF-8 우선 +
        # EUC-KR 폴백으로 디코딩한다(구 API는 EUC-KR이었음). XML 선언에 인코딩이
        # 박혀 있으면 ET.fromstring이 바이트를 직접 읽는 게 안전하지만, 인코딩이
        # 응답 헤더에만 있는 경우도 있어 문자열로 먼저 확정한다.
        try:
            raw_text = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = resp.content.decode("euc-kr", errors="replace")
        root = ET.fromstring(raw_text)
    except Exception as e:
        print(f"[LH] 요청 실패: {e}")
        try:
            print(f"[LH] 응답 내용(처음 500자): {resp.text[:500]}")
        except Exception:
            pass
        return []

    items = root.findall(".//item")
    if not items:
        # 에러 메시지가 있으면 같이 출력 (resultCode/resultMsg는 header 안에 있음)
        result_msg = root.find(".//resultMsg")
        result_code = root.find(".//resultCode")
        print(
            f"[LH] item을 찾지 못함. resultCode: "
            f"{result_code.text if result_code is not None else '(없음)'}, "
            f"resultMsg: {result_msg.text if result_msg is not None else '(없음)'}"
        )
        return []

    # 첫 실행 검증용: 신규 _GW API 응답 필드명이 구 API와 정말 같은지 로그로 확인.
    # (다른 scrapers/*.py와 동일한 진단 패턴)
    print(f"[LH] 응답 필드명 예시: {[c.tag for c in items[0]]}")

    results = []
    for item in items:
        title = _xml_text(item, "bidnmKor")
        deadline = _xml_text(item, "tndrdocAcptEndDtm")  # 입찰서접수마감일시 = 투찰마감
        if not is_deadline_in_range(deadline):
            continue

        # 참가지역1~4를 합쳐서 지역 텍스트로 사용
        region_parts = [
            _xml_text(item, f"zoneRstrct{i}") for i in range(1, 5)
        ]
        region_text = ",".join(p for p in region_parts if p)

        bid_num = _xml_text(item, "bidNum")
        # 공고차수. 상세페이지 URL은 2자리(예: "00")를 받는다.
        bid_degree = _xml_text(item, "bidDegree") or "0"
        try:
            bid_degree = f"{int(bid_degree):02d}"
        except ValueError:
            pass
        # LH e-Bid 입찰공고 상세조회(외부, 로그인 불필요). bidNum+bidDegree로
        # 실제 공고문 페이지로 바로 들어간다. 확인해보니 공사/용역/물품 모두
        # 이 BidsrvcsDetailListCmd 하나로 열린다(페이지 제목만 "(용역)"으로 고정).
        detail_url = (
            f"https://ebid.lh.or.kr/ebid.et.tp.cmd.BidsrvcsDetailListCmd.dev"
            f"?bidNum={bid_num}&bidDegree={bid_degree}"
        ) if bid_num else "https://ebid.lh.or.kr"

        results.append({
            "source": "LH",
            "title": title,
            "org": "한국토지주택공사",
            "industry": _xml_text(item, "cstrtnJobGbNm"),  # 업무구분(시설공사 등)
            "notice_no": bid_num,
            "region": region_text,
            "base_amount": _xml_text(item, "fdmtlAmt") or _xml_text(item, "presmtPrc"),
            "notice_date": _xml_text(item, "tndrbidRegDt"),
            "reg_deadline": _xml_text(item, "tndrdocAcptBgninDtm"),  # 입찰서접수개시일시
            "bid_method": _xml_text(item, "tndrCtrctMedCd"),  # 입찰계약방법(제한경쟁 등)
            "restrictions": f"지역제한({region_text})" if region_text else "",  # 참가지역1~4가 있으면 지역제한 공고
            "deadline": deadline,
            "url": detail_url,
            # g2b.py와 마찬가지로 region_scope("용인"/"경기"/"전국"/None)를 직접
            # 세팅해야 대시보드의 지역 체크박스(region_scope 기준 필터)에 걸린다 -
            # 예전 lh.py는 eligible만 세팅하고 region_scope는 안 넣어서 LH 공고가
            # 지역 필터에서 전부 빠지고 있었다(LH 복구 후 발견).
            #
            # LH는 zoneRstrct1~4(참가가능지역)가 명시적/신뢰할 수 있는 필드다:
            #  - 비어 있으면 지역제한 없음 = 전국 대상. 이 경우 굳이 공고명을
            #    파싱하지 않고 바로 "전국"으로 둔다. LH 공고명엔 "울산다운2",
            #    "경산대임", "대구국가산단"처럼 사업지구명이 잔뜩 들어가 있어서
            #    get_region_scope에 공고명까지 넘기면 EXCLUDE_REGION_KEYWORDS(울산 등)에
            #    엉뚱하게 걸려 참가불가로 잘못 처리된다.
            #  - 채워져 있으면 실제 지역제한 공고 → region_text만으로 판정.
            "region_scope": (_scope := (
                "전국" if not region_text
                else get_region_scope(region_text, "한국토지주택공사", "",
                                      has_region_restriction=True)
            )),
            "eligible": _scope is not None,
        })

    print(f"[LH] 총 {len(results)}건 수집")
    return results


if __name__ == "__main__":
    for b in fetch_lh_bids():
        print(b)
