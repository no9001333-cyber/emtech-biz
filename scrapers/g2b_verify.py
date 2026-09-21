"""
나라장터 공고의 "지역제한(참가자격)"을 공고서 원문(PDF)으로 직접 재확인합니다.

배경: g2b.go.kr 상세페이지의 지역제한 필드가 실제로 "공고서참조"로만 나오는
경우가 흔합니다(예: 공고번호 R26BK01648447 - 지역제한: 공고서참조). 즉
공식 API의 구조화된 필드(rgnLmtBidLocplcJdgmBssNm 등)만으로는 실제 참가자격
지역을 알 수 없고, 공고문 원문을 읽어야만 확실합니다. 실제로 위 예시를 열어
읽어보면 "건설산업기본법령에 의한 전문건설업 등록을 필한 그 주된 영업소의
소재지가 서울특별시, 경기도에 본사를 둔 업체"라고 되어 있어 - region 필드에
찍힌 "경기도 안양시"(공사현장 주소일 뿐)와 달리 실제로는 경기도 전역(용인
포함) 업체가 참가 가능한 공고였습니다.

다행히 2026-02-02부터 시행된 「국가종합전자조달시스템 이용약관」 제9조에 따라
모든 입찰공고서는 원본(대부분 HWP, 기계가 읽기 어려움)과 함께 AI가 인식
가능한 변환본(PDF)이 의무적으로 함께 등록됩니다. g2b.py가 이미 API로 받아둔
attachments(첨부파일 URL) 중 PDF만 골라 텍스트를 그대로 추출하면 되므로,
Playwright 같은 브라우저 자동화 없이 requests + pypdf만으로 충분합니다.

검증 대상 범위: 전체 공고(하루 수천 건)를 전부 열어보면 너무 오래 걸리고
실익도 적어서, 아래 두 그룹으로만 한정합니다.
  1) 이미 1차 필터(is_eligible_region)를 통과해 eligible=True로 표시된 공고
     → 혹시 있을 오탐(실제로는 특정 시·군에만 열려있는데 우리가 참가가능으로
        잘못 표시한 경우)을 잡아냅니다.
  2) region에 "경기"는 있지만 용인이 아닌 다른 시·군이 적혀서 eligible=False로
     제외된 공고 → 혹시 있을 누락(실제로는 경기도 전역 대상인데 공사현장
        주소만 보고 우리가 잘못 제외한 경우, 위 예시가 정확히 이 케이스)을
        되살립니다.
  그 외(타 시/도가 명시된 공고 등)는 오판 가능성이 낮아 파일까지 열어볼
  실익이 적어서 대상에서 뺍니다.

시간이 걸려도 정확도를 우선한다는 방침에 따라 만든 기능이지만, 자체호스팅
러너(사용자 PC)가 이 단계에만 무한정 붙잡히지 않도록 전체 소요시간 상한
(MAX_TOTAL_SECONDS)은 둡니다. Playwright 없이 순수 HTTP 요청이라 몇 건씩
동시에 받아도 서버 부담이 크지 않아 약간의 동시성(MAX_WORKERS)만 씁니다.

안전 원칙(d2b_restrictions.py와 동일): 자동판단에 실패하거나 애매하면 기존
값을 함부로 뒤집지 않고, "확인 필요" 메모와 함께 실제 원문 발췌(snippet)를
남겨서 사람이 2줄만 읽고도 직접 판단할 수 있게 합니다.

2026-09-16: 대시보드에 "❔ 공고서 확인필요" 배지가 너무 많이 뜬다는 지적으로
확인해보니, ambiguous 4,154건 중 4,064건(98%)이 애초에 참가자격 조항에
REGION_CUE_WORDS(소재지/본사/관내/지역제한 등) 자체가 전혀 없는 공고였다
(면허·실적 요건만 있고 지역 얘기가 아예 없음). 무작위 샘플을 실제 PDF로
재확인해도 대부분(15건 중 14건, 그리고 원래 참가불가였던 경기 그룹에서도
15건 중 13건) 정말로 지역 제한 문구가 없었다. 즉 "지역단서 단어가 하나도
없다"는 것은 "애매해서 판단 불가"가 아니라 "이 공고는 지역 제한을 두지
않았다"는 뜻이므로, _classify_region()이 이제 이 경우를 "전국"(확정)으로
반환한다. 지역단서 단어는 있는데 근처에서 지역명을 못 찾은, 진짜 애매한
경우(2%, 90건)만 계속 "확인필요"로 남는다.
"""

import io
import re
import time
import concurrent.futures

import requests

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HOME_CITY, HOME_PROVINCE, GYEONGGI_OTHER_CITIES, EXCLUDE_REGION_KEYWORDS

PDF_MAGIC = b"%PDF"
DOWNLOAD_TIMEOUT = 20
MAX_TOTAL_SECONDS = 2400  # 40분 상한
MAX_WORKERS = 5

# 2026-09-17: "입찰참가자의 자격에 관한 사항"처럼 "참가"와 "자격" 사이에 조사
# ("의", "자의" 등)가 끼어드는 실제 공고문 표기를 못 잡아서, 정작 진짜 자격
# 조항은 못 찾고 완전히 다른 절(예: "8. 현장설명회 ① 참가자격: 현장설명 참석
# 대상자")에 우연히 들어있는 "참가자격"에 걸려 엉뚱한 곳을 창(window)으로
# 잡는 사고가 있었다(사례: 사회복지법인한우리 공고 - "본점 소재지가
# 대구광역시 또는 경상북도" 제한이 실제 자격 조항에 있는데, 헤더 매칭이
# 무관한 현장설명회 절의 "참가자격"에 걸려 그 제한 문구를 통째로 놓침).
# 정규식으로 "참가"~"자격" 사이 0~4자를 허용해 이런 변형 표기도 잡는다.
PARTICIPATION_HEADER_PATTERN = re.compile(r"참가.{0,4}?자격")
REGION_CUE_WORDS = [
    "소재지", "본사", "본점", "주된 영업소", "주된영업소", "관내", "관내업체",
    "지역제한", "지역 제한", "지역업체", "본점소재지", "관할구역", "관할 구역",
]

UNVERIFIED_NOTE = "PDF 첨부파일 없음/다운로드 실패 - 원본(HWP) 직접 확인 필요"
AMBIGUOUS_NOTE = "공고서는 확인했으나 참가자격 지역조건을 자동판단하지 못함 - 아래 발췌문 직접 확인 필요"
CONFIRMED_NOTE = "공고서(PDF) 원문으로 참가자격 지역조건을 직접 확인함"


def _find_eligibility_window(text: str, window: int = 500) -> str:
    """본문에서 '참가자격' 계열 헤더가 나오는 위치들을 찾아, 그 뒤 window자씩
    이어붙여 반환한다. 헤더를 하나도 못 찾으면 빈 문자열(=이 파일에서 참가자격
    조건을 못 찾음 - 다른 첨부파일이거나 자동판단 불가로 처리됨).

    "참가"와 "자격" 사이에 조사가 끼는 표기("입찰참가자의 자격")까지 잡도록
    정규식(PARTICIPATION_HEADER_PATTERN)을 쓴다."""
    chunks = []
    for m in PARTICIPATION_HEADER_PATTERN.finditer(text):
        start = m.end()
        chunks.append(text[start:start + window])
    return "\n...\n".join(chunks)


def _snippet_around(text: str, keyword: str, radius: int = 80) -> str:
    idx = text.find(keyword)
    if idx == -1:
        return text[:160].strip()
    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword) + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


LOCAL_RADIUS = 100  # 지역단서(REGION_CUE_WORDS) 바로 근처만 진짜 제한조건으로 인정


def _classify_region(window_text: str, full_text: str = ""):
    """참가자격 텍스트 조각에서 지역 제한 여부를 판단.
    반환: (result, matched_snippet)
    result: "용인"|"경기"|"전국"(참가가능, 해당 범위) / False(참가불가 확정) /
             None(이 조각만으로는 판단 근거를 못 찾음 - 기존 값 유지 + 발췌문만 남김)

    2026-08-24: "서울"은 더 이상 이 함수가 자동으로 참가가능 처리하지 않습니다.
    대시보드가 용인/경기도/전국 세 범위를 독립적으로 켜고 끄는 체크박스로
    바뀌면서, 그 셋 중 어디에도 안 들어가는 서울 같은 지역은 억지로 끼워
    넣지 않고 지역 드롭다운에서 직접 찾아보도록 남겨두기로 했습니다(예전엔
    "서울"만 나와도 무조건 True였는데, 정작 1차 판정(is_eligible_region)은
    애초에 서울을 참가가능으로 보지 않아서 PDF 재확인 후보로도 안 뽑히는
    모순이 있었습니다).

    2026-08-20 재작성 - 실제 운영 데이터로 확인된 심각한 오탐 사례 때문에
    전면 재작성했습니다. 예전 버전은 500자짜리 넓은 창(window) 안에 지역단서
    (소재지/본사 등)와 지역명이 "어딘가에" 같이 있기만 하면 제한조건으로
    판단했는데, 실제로는 그 지역명이 발주기관 이름("경기도이천교육지원청",
    "경기도부천교육지원청")이나 청렴신고 우편주소("부산광역시 남구
    문현금융로")에서 나온 것이지 실제 참가자격 제한과 무관한 경우가 많았습니다
    (샘플 8건 중 5건이 이런 오탐 - "이천"/"부천"/"남양주"/"평택"/"부산"이
    전부 발주기관명·주소에서 나온 것이었고 진짜 지역제한 문구가 아니었음).
    그 결과 실제로는 참가 가능한 통신 공고 상당수가 "참가불가"로 잘못
    표시되는 문제가 있었습니다.

    그래서 이제 "지역단서 단어 바로 옆(LOCAL_RADIUS 이내)"에 있는 지역명만
    진짜 제한조건으로 인정합니다 - 문서 전체에서 지역단서가 나오는 모든
    위치를 훑으면서, 그 주변에서만 지역명을 찾습니다. 판단 순서(용인이 아닌
    다른 특정 시·군을 경기도보다 먼저 검사)는 동일하게 유지합니다 - "경기도
    안양시에 본사를 둔 업체"처럼 특정 시·군까지 콕 집은 경우를 "경기도"라는
    글자만 보고 참가가능으로 잘못 판단하지 않기 위함입니다.

    2026-08-24 순서 버그 수정: EXCLUDE_REGION_KEYWORDS(다른 시·도) 체크가
    HOME_PROVINCE 체크보다 먼저였던 탓에, "경기도, 충청남도, 경상북도, 대구
    광역시... 관할구역 안에 소재한 업체" 처럼 여러 지역을 OR로 나열하면서
    경기도도 그 목록에 포함된 경우(실제로는 참가 가능)가 다른 지역 이름이
    먼저 걸려서 무조건 참가불가로 잘못 판정되고 있었습니다(코레일
    "경부고속선 광명역 등 14개소 구내 광케이블 개량공사" 건에서 발견).
    EXCLUDE_REGION_KEYWORDS는 "이 공고는 완전히 다른 지역 전용"이라는
    뜻이어야 하는데, 같은 local 창 안에 우리 지역(경기/서울)도 같이 나열돼
    있으면 그 전제가 깨지므로, HOME_PROVINCE/서울 체크를 먼저 하도록
    순서를 바꿨습니다. GYEONGGI_OTHER_CITIES(경기도 내 다른 특정 시·군)
    체크는 여전히 그보다 먼저 유지합니다 - "경기도 안양시"처럼 시·군까지
    콕 집은 경우는 "경기도"라는 글자만으로 참가가능 처리하면 안 되기
    때문입니다.
    """
    if not window_text:
        return None, ""

    result, snippet, found_cue = _scan_for_region(window_text)
    if result is not None:
        return result, snippet

    if not found_cue:
        # 2026-09-16: 실제 운영 데이터 확인 결과, "확인필요"(ambiguous)로 빠지는
        # 4,154건 중 98%(4,064건)가 참가자격 조항에 지역단서(REGION_CUE_WORDS)
        # 단어 자체가 아예 없었다(면허·실적 요건만 있고 지역 얘기가 없는 경우).
        # 무작위 15건을 실제 PDF로 재확인해도 14건이 진짜로 지역 제한 문구가
        # 없었다(1건만 지역단서가 있었는데 앞의 500자 윈도우 밖이라 못 봤을 뿐).
        # 즉 "지역단서 단어가 하나도 없음"은 대부분 "이 공고는 지역 제한을 두지
        # 않았다"는 뜻이지 "애매해서 판단 불가"가 아니다. 지역단서가 있는데도
        # 근처에서 지역명을 못 찾은 경우(진짜 애매한 경우)만 아래에서 계속
        # None(확인필요)으로 남긴다.
        #
        # 2026-09-17 안전장치 추가: 위 "98%는 진짜 전국"이라는 결론은 window가
        # 실제 자격 조항을 제대로 잡았다는 전제 하에서만 맞다. 그런데 헤더
        # 매칭이 엉뚱한 절(예: "8. 현장설명회 ① 참가자격: 현장설명 참석 대상자")에
        # 걸려서 정작 진짜 자격 조항("7. 입찰참가자의 자격")을 통째로 놓치는
        # 사례가 실제로 있었다(사회복지법인한우리 공고 - "본점 소재지가
        # 대구광역시 또는 경상북도" 지역제한이 있는데도 전국으로 잘못 확정됨).
        # region 필드가 경기/용인과 무관한 타 지역인데 "전국 확정"된 419건을
        # 표본검사하니 15건 중 7건이 이 케이스였다. window만 보고 "단서 없음"
        # 이라고 성급히 "전국"을 확정하면 안 되고, 첨부파일 전체 본문에도
        # 지역단서가 정말 하나도 없는지 한 번 더 확인해야 한다 - window 밖에
        # 단서가 있다면 자격 조항 자체를 놓쳤을 가능성이 크므로 안전하게
        # "확인필요"로 남긴다(참가불가한 공고를 참가가능으로 잘못 보여주는
        # 것이 확인필요 배지 하나 더 뜨는 것보다 훨씬 위험함).
        #
        # 다만 단순히 "cue 단어가 본문 어딘가에 있다"만 보면 오탐이 난다
        # (예: "본사 안전담당자의 현장 안전보건점검" 같은 안전관리 조항에
        # "본사"가 나오는데 이건 지역 제한과 무관함). 그래서 window와 똑같은
        # _scan_for_region()을 full_text 전체에 다시 돌려서, cue 옆에 실제
        # 지역명까지 붙어있는 "진짜" 매치가 있을 때만 확인필요로 보류한다.
        if full_text:
            full_result, full_snippet, _ = _scan_for_region(full_text)
            if full_result is not None:
                return None, (
                    "(참가자격 조항 근처에는 지역단서가 없었으나, 공고문 다른 곳에 "
                    f"지역 제한으로 보이는 문구가 있어 자동판단을 보류함: {full_snippet})"
                )
        return "전국", "(참가자격 조항에 지역 제한 관련 문구 없음 - 전국 참가가능으로 판단)"

    return None, window_text[:200].strip()


def _scan_for_region(text: str):
    """text 안에서 REGION_CUE_WORDS가 나오는 모든 위치를 훑으며, 그 바로
    옆(LOCAL_RADIUS 이내)에서 실제 지역명을 찾는다.
    반환: (result, snippet, found_cue) - result는 _classify_region과 동일한
    의미(정의된 지역/False/None), found_cue는 cue 단어를 하나라도 찾았는지."""
    found_cue = False
    for cue in REGION_CUE_WORDS:
        search_from = 0
        while True:
            pos = text.find(cue, search_from)
            if pos == -1:
                break
            found_cue = True
            search_from = pos + len(cue)
            local_start = max(0, pos - LOCAL_RADIUS)
            local_end = min(len(text), pos + len(cue) + LOCAL_RADIUS)
            local = text[local_start:local_end]

            if HOME_CITY in local:
                return "용인", _snippet_around(text, HOME_CITY), found_cue
            if "전국" in local:
                return "전국", _snippet_around(text, "전국"), found_cue

            other_city_hit = next((c for c in GYEONGGI_OTHER_CITIES if c in local), None)
            if other_city_hit:
                return False, _snippet_around(text, other_city_hit), found_cue

            if HOME_PROVINCE in local:
                return "경기", _snippet_around(text, HOME_PROVINCE), found_cue

            other_region_hit = next((k for k in EXCLUDE_REGION_KEYWORDS if k in local), None)
            if other_region_hit:
                return False, _snippet_around(text, other_region_hit), found_cue

    return None, "", found_cue


def _extract_pdf_text(url: str) -> str:
    """첨부파일 URL 하나를 받아, PDF일 때만 텍스트를 추출해 반환한다.
    HWP 등 다른 형식이거나 다운로드/파싱에 실패하면 빈 문자열."""
    if not url:
        return ""
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return ""
    if not resp.content.startswith(PDF_MAGIC):
        return ""  # HWP 원본 등 AI가 못 읽는 파일 - 이 첨부는 건너뜀
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(resp.content))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def _verify_one(bid: dict) -> dict:
    """공고 하나를 검증해서 결과만 담은 dict를 반환한다(bid 자체는 건드리지
    않음 - 스레드 풀에서 호출되므로, 실제 bid 갱신은 메인 스레드에서 한 번에
    처리해 스레드 안전성 문제를 피한다)."""
    attachments = bid.get("attachments") or []
    if not attachments:
        return {"source": "no-attachment"}

    for att in attachments:
        text = _extract_pdf_text(att.get("url", ""))
        if not text:
            continue
        window = _find_eligibility_window(text)
        scope, snippet = _classify_region(window, full_text=text)
        if not window:
            continue  # 이 PDF엔 참가자격 조항이 없음 - 다른 첨부파일도 시도
        return {"source": "pdf", "scope": scope, "snippet": snippet}

    return {"source": "pdf-unavailable"}


def _downgrade_provisional(bid: dict, reason: str) -> bool:
    """공사현장이 타 지역이라 API 필드만으로 잠정 "전국" 처리됐던 공고(scope_provisional)를,
    공고서에서 지역제한 없음을 확인하지 못했을 때 제외 처리한다.
    (대박낙찰정보 맞춤입찰정보 건별 대조 결과 - 새만금(전북)/충북/충남 현장 공고가
    우리만 전국으로 표시하던 문제. 참가불가를 참가가능으로 보여주는 쪽이 훨씬 위험함)"""
    if not bid.get("scope_provisional"):
        return False
    bid["eligible"] = False
    bid["region_scope"] = None
    bid["scope_provisional"] = False
    prev = bid.get("region_check") or {}
    bid["region_check"] = {
        **prev,
        "downgraded": True,
        "note": f"공사현장이 타 지역이고 공고서에서 지역제한 없음을 확인하지 못해 제외 ({reason})",
    }
    return True


def verify_g2b_region_eligibility(bids: list) -> None:
    """나라장터 공고 리스트를 받아, 대상 공고에 한해 region_check 필드를 채우고
    필요하면 eligible 값을 실제 공고서 확인 결과로 덮어쓴다 (in-place 수정).
    실패해도 예외를 밖으로 던지지 않고 조용히 원래 값을 유지한다 - 이 검증
    단계 하나가 실패했다고 전체 수집이 죽으면 안 되기 때문."""
    try:
        candidates = [
            b for b in bids
            if b.get("eligible") is True
            or ("경기" in (b.get("region") or "") and HOME_CITY not in (b.get("region") or ""))
        ]
    except Exception as e:
        print(f"[나라장터 공고문 검증] 대상 선정 실패로 건너뜀: {e}")
        return

    if not candidates:
        return

    print(f"[나라장터 공고문 검증] 대상 {len(candidates)}건 - 첨부파일 PDF에서 실제 참가자격 지역조건 재확인 중...")

    start = time.time()
    verified = 0
    changed = 0
    no_pdf = 0
    downgraded = 0

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            future_to_bid = {}
            for b in candidates:
                if time.time() - start > MAX_TOTAL_SECONDS:
                    print(f"[나라장터 공고문 검증] 시간 상한({MAX_TOTAL_SECONDS}초) 도달 - 나머지는 이번엔 건너뜀")
                    break
                future_to_bid[pool.submit(_verify_one, b)] = b

            for future in concurrent.futures.as_completed(future_to_bid):
                bid = future_to_bid[future]
                try:
                    result = future.result()
                except Exception:
                    result = {"source": "error"}

                source = result.get("source")
                if source == "no-attachment":
                    if _downgrade_provisional(bid, "첨부파일 없음"):
                        downgraded += 1
                    continue
                if source in ("pdf-unavailable", "error"):
                    no_pdf += 1
                    bid["region_check"] = {"verified": False, "note": UNVERIFIED_NOTE}
                    if _downgrade_provisional(bid, "PDF 확인 실패"):
                        downgraded += 1
                    continue

                verified += 1
                snippet = result.get("snippet", "")
                confirmed = result.get("scope")  # "용인"|"경기"|"전국" / False / None
                if confirmed is None:
                    bid["region_check"] = {
                        "verified": True, "eligible_confirmed": None,
                        "note": AMBIGUOUS_NOTE, "snippet": snippet,
                    }
                    if _downgrade_provisional(bid, "자동판단 보류"):
                        downgraded += 1
                    continue
                bid["scope_provisional"] = False  # 공고서로 확정됨(전국 확정이든 제한 확정이든)

                new_eligible = confirmed is not False
                new_scope = confirmed if new_eligible else None
                before = bid.get("eligible")
                bid["eligible"] = new_eligible
                bid["region_scope"] = new_scope
                if before != new_eligible:
                    changed += 1
                bid["region_check"] = {
                    "verified": True, "eligible_confirmed": confirmed,
                    "note": CONFIRMED_NOTE, "snippet": snippet,
                }
    except Exception as e:
        print(f"[나라장터 공고문 검증] 예상치 못한 오류로 중단됨(이미 처리된 결과는 유지): {e}")

    for b in candidates:
        if _downgrade_provisional(b, "검증 시간 상한/오류로 확인 못 함"):
            downgraded += 1

    elapsed = int(time.time() - start)
    print(f"[나라장터 공고문 검증] 타 지역 현장 잠정 전국 판정 중 공고서로 확인 못 해 제외: {downgraded}건")
    print(
        f"[나라장터 공고문 검증] {verified}건 PDF로 확인 완료, {no_pdf}건 미확인(PDF 없음/실패), "
        f"{changed}건 판정이 바뀜 ({elapsed}초 소요)"
    )
