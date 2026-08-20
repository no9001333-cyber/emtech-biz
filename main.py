"""
메인 실행 스크립트
- 나라장터 / LH / 국방전자조달(D2B) / 한국수자원공사 / 한국전력공사 / 한국가스공사
  입찰공고 수집기와, 나라장터 낙찰정보(개찰결과) 수집기를 모두 돌립니다.
  (코레일/국가철도공단은 API 데이터가 실시간이 아닌 정적 과거 아카이브로 확인되어
   자동수집 대상에서 제외하고, 대시보드 상단 바로가기 링크로만 제공합니다.
   한국가스공사는 2026-08-19에 data.go.kr에서 실시간 오픈API를 새로 확인해서
   추가했습니다 - 다만 이 API는 추정금액/기초금액/지역 필드를 제공하지 않아
   해당 항목은 대시보드에 "확인필요"로 표시됩니다.)
- 매번 "오늘 새로 수집한 결과"로 완전히 새로 저장합니다 (예전 데이터와 병합하지 않음).
  (참고: 공고별 메모는 브라우저에 별도로 저장되므로 이 초기화와 무관하게 유지됩니다)
- 투찰마감이 지난 나라장터 공고는, 같은 공고번호로 낙찰정보가 있으면
  그 결과(낙찰자/낙찰금액/사정율)를 공고 데이터에 그대로 붙여서 저장합니다.
- 소스별 수집 건수를 data/status.json에 기록합니다. 키가 등록된 소스인데 0건이 나오면
  "문제 있음"으로 표시하고, 나중에 daily.yml의 상태 점검 단계가 이걸 보고 실행 실패로
  표시해 GitHub이 자동으로 이메일 알림을 보내게 만듭니다.
- 마지막으로 대시보드(docs/index.html)를 다시 생성합니다.
"""

import json
import os
import time
from datetime import datetime

from config import (
    DATA_DIR, BIDS_JSON_PATH, AWARDS_JSON_PATH, STATUS_JSON_PATH,
    G2B_SERVICE_KEY, LH_SERVICE_KEY, D2B_SERVICE_KEY, KWATER_SERVICE_KEY,
    KEPCO_API_KEY, KOGAS_SERVICE_KEY, G2B_AWARDS_SERVICE_KEY,
)
from scrapers.g2b import fetch_g2b_bids
from scrapers.g2b_verify import verify_g2b_region_eligibility
from scrapers.g2b_basis_amount import enrich_g2b_bids_with_basis_amount
from scrapers.lh import fetch_lh_bids
from scrapers.d2b import fetch_d2b_bids
from scrapers.kwater import fetch_kwater_bids
from scrapers.kepco import fetch_kepco_bids
from scrapers.kogas import fetch_kogas_bids
from scrapers.g2b_awards import fetch_g2b_awards
from scrapers._common import bid_status, deadline_sort_key
from generate_dashboard import generate_dashboard, generate_awards_page


def _dedupe_key(bid):
    return f"{bid.get('source')}::{bid.get('notice_no') or bid.get('title')}"


def _run_source(name, key_configured, fetch_fn, status_list):
    """수집기 하나를 실행하고, 결과와 상태를 함께 기록한다."""
    try:
        results = fetch_fn()
        error = None
    except Exception as e:
        results = []
        error = str(e)

    if not key_configured:
        ok = True  # 키를 아예 등록 안 한 건 의도된 것이니 문제로 보지 않음
        note = "키 미등록 (건너뜀)"
    elif error:
        ok = False
        note = f"실행 중 오류: {error}"
    elif len(results) == 0:
        ok = False
        note = "키는 있는데 0건 수집됨 (API 응답 확인 필요)"
    else:
        ok = True
        note = f"{len(results)}건 수집"

    status_list.append({"source": name, "ok": ok, "count": len(results), "note": note})
    time.sleep(2)  # 다음 소스 요청 전 잠깐 쉬어서 data.go.kr 쪽에 너무 몰아치지 않게 함
    return results


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    status_list = []

    # 1) 입찰공고 수집 (소스별로 상태 기록)
    new_bids = []
    g2b_bids = _run_source("나라장터", bool(G2B_SERVICE_KEY), fetch_g2b_bids, status_list)
    # 2026-08-19: g2b.go.kr 상세페이지의 지역제한 필드가 "공고서참조"로만 나오는
    # 경우가 흔해서, API 구조화 필드만으로는 실제 참가가능 지역을 알 수 없는
    # 공고가 있다. 공고서(PDF) 원문을 직접 읽어 참가자격 지역조건을 재확인한다
    # (자세한 배경은 scrapers/g2b_verify.py 상단 주석 참고). 시간이 걸려도
    # 정확도를 우선하기로 했지만, 이 단계 자체가 실패해도 전체 수집이 죽지
    # 않도록 g2b_verify 내부에서 예외를 전부 흡수한다.
    verify_g2b_region_eligibility(g2b_bids)
    # 2026-08-20: g2b.py가 목록 조회 API로 잠정 채워둔 기초금액/A값을, 전용
    # 오퍼레이션(공사기초금액조회)에서 실제 공개된 값으로 재확인해 덮어쓴다
    # (자세한 배경은 scrapers/g2b_basis_amount.py 상단 주석 참고).
    enrich_g2b_bids_with_basis_amount(g2b_bids)
    new_bids += g2b_bids
    new_bids += _run_source("LH", bool(LH_SERVICE_KEY), fetch_lh_bids, status_list)
    new_bids += _run_source("국방전자조달(D2B)", bool(D2B_SERVICE_KEY), fetch_d2b_bids, status_list)
    new_bids += _run_source("한국수자원공사", bool(KWATER_SERVICE_KEY), fetch_kwater_bids, status_list)
    new_bids += _run_source("한국전력공사", bool(KEPCO_API_KEY), fetch_kepco_bids, status_list)
    new_bids += _run_source("한국가스공사", bool(KOGAS_SERVICE_KEY), fetch_kogas_bids, status_list)

    deduped = {}
    for bid in new_bids:
        bid["collected_at"] = now_str
        bid["status"] = bid_status(bid.get("deadline", ""))
        deduped[_dedupe_key(bid)] = bid
    kept = list(deduped.values())

    # 2) 낙찰정보(개찰결과) 수집 - 나라장터만 지원
    new_awards = _run_source("나라장터 낙찰정보", bool(G2B_AWARDS_SERVICE_KEY), fetch_g2b_awards, status_list)
    awards_by_notice = {}
    for award in new_awards:
        award["collected_at"] = now_str
        key = f"나라장터::{award.get('notice_no') or award.get('title')}"
        awards_by_notice[key] = award

    with open(AWARDS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(list(awards_by_notice.values()), f, ensure_ascii=False, indent=2)
    print(f"총 {len(awards_by_notice)}건 낙찰정보 저장 ({AWARDS_JSON_PATH})")

    # 3) 마감이 지난 나라장터 공고에, 같은 공고번호의 낙찰정보가 있으면 결과를 붙여줌
    matched = 0
    for bid in kept:
        if bid.get("status") != "마감":
            continue
        key = _dedupe_key(bid)
        award = awards_by_notice.get(key)
        if award:
            bid["result"] = {
                "winner": award.get("winner", ""),
                "award_amount": award.get("award_amount", ""),
                "assessed_rate": award.get("assessed_rate", ""),
                "open_date": award.get("open_date", ""),
            }
            matched += 1
    print(f"낙찰결과 매칭: {matched}건")

    # deadline 값의 실제 타입/표기 형식이 수집기(소스)마다 다를 수 있어(문자열 vs 숫자,
    # "2026-08-20 09:00"처럼 구분자가 있는 경우 vs "202608200900"처럼 숫자만 있는 경우),
    # deadline_sort_key()로 숫자만 남긴 문자열로 통일해서 정렬한다. 이렇게 해야
    # (1) 타입이 섞여서 "'<' not supported between instances of 'int' and 'str'" 에러가
    # 나는 것도 막고, (2) 여러 소스가 섞인 목록에서도 마감이 이른 순으로 정확히
    # 정렬된다 (raw 문자열을 그대로 비교하면 구분자 유무 때문에 소스 간 순서가 틀어짐).
    kept.sort(key=lambda b: (b.get("status") == "마감", deadline_sort_key(b.get("deadline", ""))))

    with open(BIDS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    print(f"총 {len(kept)}건 저장 ({BIDS_JSON_PATH})")

    # 4) 상태 기록 저장 (daily.yml의 "상태 점검" 단계가 이 파일을 읽어서 문제 있으면 알림)
    status_payload = {"checked_at": now_str, "sources": status_list}
    with open(STATUS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(status_payload, f, ensure_ascii=False, indent=2)
    problems = [s for s in status_list if not s["ok"]]
    if problems:
        print(f"[상태 점검] 문제 있는 소스 {len(problems)}개: " + ", ".join(p["source"] for p in problems))
    else:
        print("[상태 점검] 모든 소스 정상")

    generate_dashboard(kept, status_list)
    generate_awards_page(list(awards_by_notice.values()), status_list)


if __name__ == "__main__":
    main()
