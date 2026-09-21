"""
한국토지주택공사(LH) 낙찰결과(개찰결과) 수집기
공공데이터포털의 "한국토지주택공사 전자조달-개찰정보(개찰결과정보)_GW" OpenAPI 사용

2026-09-18: 지금까지 LH는 입찰공고(lh.py)만 수집하고 낙찰결과는 나라장터
(g2b_awards.py)만 있었다. 대박입찰과 대조해보니 LH 낙찰결과("누가 얼마에
낙찰됐는지")를 전혀 못 보여주고 있어서, 경쟁사 낙찰가·사정율을 참고할 수
있도록 이 수집기를 새로 만든다.

사전 준비:
1) https://www.data.go.kr 에서 "한국토지주택공사 전자조달-개찰정보(개찰결과정보)_GW"
   검색 → 활용신청 (자동승인, 즉시 발급)
2) Base URL이 lh.py의 입찰공고 API와 똑같이 apis.data.go.kr/B552555 이므로,
   같은 계정에서 활용신청만 추가로 하면 기존 LH_SERVICE_KEY를 그대로 쓸 수
   있다 - 별도 시크릿을 새로 등록할 필요 없음.

참고(data.go.kr Swagger 문서 기준, 데이터 번호 15159014):
  Base URL: apis.data.go.kr/B552555/OpenTenderopenList
  오퍼레이션: getOpenTenderopenList (개찰결과정보)
  필수 파라미터: serviceKey, pageNo, numOfRows, openDtmStart, openDtmEnd
    (개찰일 기준 조회기간, YYYYMMDD 8자리)
  응답 필드(item): bidNum(공고번호), bidDegree(공고차수), bidnmKor(공고명),
    cstrtnJobGbNm(업무구분), tndrVndrNm(투찰업체명), decTndrAmt(낙찰/결정금액),
    designPrc(설계금액), expectPrc(예정가격), fdmtlAmt(기초금액),
    invtgtRate(사정율로 추정), tndrTm(입찰시간), vndrSccfBidStatusNm(업체
    낙찰상태명), openDtm(개찰일시)

주의: 이 API가 공고 1건당 "낙찰자 1행"만 주는지, 아니면 "참여업체마다 1행씩"
주고 vndrSccfBidStatusNm으로 낙찰/유찰을 구분해야 하는지 문서만으로는
확정할 수 없었다(실제 서비스키가 있어야 응답을 볼 수 있음). 그래서 방어적으로
같은 (bidNum, bidDegree) 안에서 vndrSccfBidStatusNm에 "낙찰"이 포함된 행을
우선 채택하고, 그런 행이 하나도 없으면(=이미 낙찰자만 내려주는 구조였던
경우) 첫 번째 행을 그대로 쓰도록 짰다. 첫 실행 로그에 실제 필드값 예시를
남겨서 다음에 이 가정이 맞았는지 확인할 수 있게 해둔다.
"""

import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LH_SERVICE_KEY, LOOKBACK_DAYS
from scrapers._common import get_with_retry

ENDPOINT = "https://apis.data.go.kr/B552555/OpenTenderopenList/getOpenTenderopenList"
WIN_STATUS_HINT = "낙찰"


def _clean_key(key: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(key).strip()


def _xml_text(elem, tag):
    found = elem.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ""


def _fetch_page(key, begin_dt, end_dt, page_no, num_of_rows=500):
    params = {
        "serviceKey": key,
        "numOfRows": num_of_rows,
        "pageNo": page_no,
        "openDtmStart": begin_dt,
        "openDtmEnd": end_dt,
    }
    resp = get_with_retry(ENDPOINT, params=params, timeout=30)
    try:
        raw_text = resp.content.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = resp.content.decode("euc-kr", errors="replace")
    return ET.fromstring(raw_text)


def fetch_lh_awards():
    """LH 낙찰결과(개찰결과) 목록을 최근 LOOKBACK_DAYS일(개찰일 기준)로 가져온다.

    이 API는 공고 1건당 여러 참여업체 행을 줄 가능성이 있어(문서만으로는
    단정 불가, 위 docstring 참고) 나라장터 낙찰정보보다 원본 행 수가 훨씬
    많을 수 있다. g2b.py/g2b_awards.py에서 페이지 상한 때문에 최신 데이터가
    잘려나갔던 사고를 겪은 뒤로는, 첫 페이지 크기만 믿지 않고 totalCount를
    보며 필요한 만큼 이어서 가져오도록 짠다."""
    if not LH_SERVICE_KEY:
        print("[LH 낙찰정보] 서비스키(LH_SERVICE_KEY)가 설정되지 않아 건너뜁니다.")
        return []

    end = datetime.now()
    begin = end - timedelta(days=LOOKBACK_DAYS)
    key = _clean_key(LH_SERVICE_KEY)
    begin_dt = begin.strftime("%Y%m%d")
    end_dt = end.strftime("%Y%m%d")

    NUM_OF_ROWS = 500
    MAX_PAGES = 15  # 안전장치: 최대 15페이지(=최대 7,500행)까지만 수집

    items = []
    page_no = 1
    while page_no <= MAX_PAGES:
        try:
            root = _fetch_page(key, begin_dt, end_dt, page_no, NUM_OF_ROWS)
        except Exception as e:
            print(f"[LH 낙찰정보] 요청 실패(페이지 {page_no}): {e}")
            break

        page_items = root.findall(".//item")
        if not page_items:
            if page_no == 1:
                result_msg = root.find(".//resultMsg")
                result_code = root.find(".//resultCode")
                print(
                    f"[LH 낙찰정보] item을 찾지 못함. resultCode: "
                    f"{result_code.text if result_code is not None else '(없음)'}, "
                    f"resultMsg: {result_msg.text if result_msg is not None else '(없음)'}"
                )
            break

        items.extend(page_items)

        total_count_elem = root.find(".//totalCount")
        total_count = int(total_count_elem.text) if total_count_elem is not None and total_count_elem.text else len(items)
        if page_no * NUM_OF_ROWS >= total_count:
            break
        if page_no == MAX_PAGES:
            print(f"[LH 낙찰정보] 경고: 총 {total_count}행인데 상한({MAX_PAGES*NUM_OF_ROWS}행)에 걸려 일부 누락됨")
            break
        page_no += 1

    if not items:
        return []

    print(f"[LH 낙찰정보] 응답 필드명 예시: {[c.tag for c in items[0]]}")
    status_values = sorted({_xml_text(it, "vndrSccfBidStatusNm") for it in items} - {""})
    print(f"[LH 낙찰정보] vndrSccfBidStatusNm 값 종류: {status_values}")
    job_values = sorted({_xml_text(it, "cstrtnJobGbNm") for it in items} - {""})
    print(f"[LH 낙찰정보] cstrtnJobGbNm(업무구분) 값 종류: {job_values}")

    # (bidNum, bidDegree)별로 묶어서, "낙찰" 상태인 행을 우선 채택한다.
    groups = {}
    for item in items:
        bid_num = _xml_text(item, "bidNum")
        if not bid_num:
            continue
        bid_degree = _xml_text(item, "bidDegree") or "0"
        key_tuple = (bid_num, bid_degree)
        groups.setdefault(key_tuple, []).append(item)

    results = []
    skipped_non_construction = 0
    for (bid_num, bid_degree), rows in groups.items():
        winner_row = next(
            (r for r in rows if WIN_STATUS_HINT in _xml_text(r, "vndrSccfBidStatusNm")),
            rows[0],
        )

        # 2026-09-21: 우리는 공사만 투찰한다(사용자 지시). 업무구분에 "공사"가
        # 없으면(용역/물품 등) 낙찰결과에서도 제외한다. 값이 비어있으면(판단불가)
        # 버리지 않고 둔다.
        job = _xml_text(winner_row, "cstrtnJobGbNm")
        if job and "공사" not in job:
            skipped_non_construction += 1
            continue

        try:
            degree_padded = f"{int(bid_degree):02d}"
        except ValueError:
            degree_padded = bid_degree
        detail_url = (
            f"https://ebid.lh.or.kr/ebid.et.tp.cmd.BidsrvcsDetailListCmd.dev"
            f"?bidNum={bid_num}&bidDegree={degree_padded}"
        )

        results.append({
            "source": "LH",
            "title": _xml_text(winner_row, "bidnmKor"),
            "org": "한국토지주택공사",
            "notice_no": bid_num,
            "winner": _xml_text(winner_row, "tndrVndrNm"),
            # 이 API 응답엔 낙찰업체 연락처 필드가 없음(g2b_awards.py의
            # bidwinnrTelNo에 대응하는 필드 자체가 없음).
            "winner_tel": "",
            "award_amount": _xml_text(winner_row, "decTndrAmt"),
            "base_amount": _xml_text(winner_row, "fdmtlAmt") or _xml_text(winner_row, "designPrc"),
            "assessed_rate": _xml_text(winner_row, "invtgtRate"),
            "open_date": _xml_text(winner_row, "openDtm"),
            "url": detail_url,
            "notice_kind": "공사",
        })

    print(f"[LH 낙찰정보] 총 {len(results)}건 수집 (원본 {len(items)}행 -> 공고별 그룹핑, 공사 아닌 {skipped_non_construction}건 제외)")
    return results


if __name__ == "__main__":
    for a in fetch_lh_awards():
        print(a)
