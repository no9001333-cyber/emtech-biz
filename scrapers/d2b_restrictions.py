"""
국방전자조달(D2B) 개별 공고의 실제 공고문(웹페이지 상세)을 열어서
"면허제한"과 "제한지역" 정보를 가져옵니다.

배경: 방위사업청 공식 오픈API(getFcltyCmpetBidPblancList)는 공고명/일정/금액
필드만 제공하고, 실제로 어느 회사가 참가할 수 있는지를 결정하는 면허·지역
제한 정보는 필드 자체가 존재하지 않습니다(d2b.py 상단 주석에 실제 필드 목록
정리해둠). 그런데 d2b.go.kr 사이트에서 공고를 직접 열어보면 "공종 및
면허제한", "제한지역" 표에 그 정보가 그대로 나옵니다 - 예를 들어 어떤 공고는
"제주특별자치도"에서만 참가 가능하고, 어떤 공고는 "경기도"에서만 참가
가능한 식으로 공고마다 다릅니다. 이걸 확인하지 않고 그냥 게시만 하면(예전
방식) 실제로는 참가할 수 없는 지역 공고까지 전부 "참가가능"으로 보이는
문제가 있었습니다.

그래서 이 모듈은 Playwright로 실제 웹사이트를 열어:
  1) 공고명으로 검색
  2) 우리가 공식 API로 이미 수집해둔 공고번호(pblancNo)와 일치하는(그리고
     "취소공고"가 아닌) 결과를 찾아 클릭
  3) 상세 페이지의 면허제한/제한지역 표를 읽어옵니다.

주의 (일부러 방어적으로 짬):
  - 공식 API가 아니라 실제 웹페이지를 여는 방식이라 사이트 구조가 바뀌거나
    일시적으로 느려지면 깨질 수 있습니다. 그래서 공고 하나가 실패해도 전체
    수집이 죽지 않도록 개별적으로 try/except로 감쌉니다.
  - 확인에 실패한 공고는 restrictions에 "자동확인 실패 - 공고문 직접 확인
    필요"라고 명시합니다. 2026-08-25까지는 이 경우 eligible=False(참가불가
    확정)로 덮어썼는데, 이 자동확인 자체가 TouchEn nxWeb 미설치로 사실상
    100% 실패하는 상태라(아래 2026-08-18 원인 참고), 결과적으로 D2B 공고
    전체가 실제 자격과 무관하게 매일 "참가불가"로 숨겨지고 있었습니다.
    확인이 안 됐다는 것과 확인 결과 참가불가라는 것은 다른 얘기라, 이제는
    eligible을 건드리지 않고(d2b.py가 기본값 True로 채워둔 것을 그대로 둠)
    "확인필요" 표시만 남깁니다 - 놓치는 것보다 나중에 공고문 직접 확인해서
    거르는 쪽이 안전합니다.
  - Playwright 자체가 설치 안 되어 있거나 브라우저 실행이 안 되면, 이 기능
    전체를 건너뛰고 기존 수집 결과를 그대로 반환합니다 - 이것 때문에 전체
    수집(공고 목록 자체)이 죽으면 안 되기 때문입니다.

중요 - 2026-08-18에 밝혀진 진짜 원인 (타임아웃 문제가 아니었음):
  타임아웃을 45초로 늘려도 47건이 전부 동일하게 실패해서 직접 조사해보니,
  d2b.go.kr은 라온시큐어(RaonSecure)사의 "TouchEn nxWeb"이라는 콘텐츠 보호
  프로그램이 PC에 설치·실행되어 있어야만 정상 동작합니다. 이게 없으면
  페이지가 조용히 `/raonnx/nxWeb/help/help.html`로 리다이렉트되면서 검색 자체가
  안 됩니다(사이트가 느린 게 아니라 이 보안 체크에 막힌 것). Playwright가
  실행하는 브라우저(기본은 Playwright 전용 크로미움)에는 이 프로그램이 당연히
  없어서 100% 실패합니다.

  그래서 아래처럼 바꿨습니다: 이 PC(자체 호스팅 러너)에 실제로 설치된 Edge
  브라우저(TouchEn nxWeb를 정상 설치해둔 프로필)를 Playwright가 그대로
  구동하도록 시도합니다. TouchEn nxWeb 프로그램 자체를 우회/무력화하려는 게
  아니라, 정상적으로 설치된 실제 브라우저를 자동화 도구로 조작하는 것뿐입니다
  (사람이 마우스로 클릭하는 것과 원리상 동일). 이 방식도 실패하면(예: 그 PC에
  Edge가 없거나 TouchEn nxWeb이 설치 안 되어 있으면) 기존 방식(Playwright 전용
  크로미움, headless)으로 자동 대체하되, 이 경우 사이트 보안 체크를 통과하지
  못해 계속 "자동확인 실패"로 표시될 가능성이 높습니다.

  ** 이 방식이 동작하려면 사용자가 먼저 그 PC에서 직접 해야 하는 일 **
  1) 그 PC의 실제 Edge 브라우저로 https://www.d2b.go.kr 접속
  2) TouchEn nxWeb 설치 안내가 뜨면 정상적으로 설치 완료
  3) 설치 후 실제로 공고 검색이 되는지 Edge에서 직접 확인
  이 과정을 거쳐야 D2B_EDGE_PROFILE_DIR 아래에 TouchEn nxWeb이 인식하는
  프로필이 만들어집니다. 이 단계 없이는 아래 코드도 소용없습니다.
"""

import os

# 자체 호스팅 러너 PC에서 TouchEn nxWeb이 정상 설치된 실제 Edge 프로필 경로.
# 환경변수로 지정하지 않으면 기본값(사용자 홈 폴더 아래 고정 경로)을 씁니다.
# 이 폴더는 "일반 Edge 사용자 데이터 폴더"와 똑같은 구조이므로, 사용자가 평소
# 쓰는 프로필을 그대로 가리켜도 되고, 자동화 전용으로 새 폴더를 하나 만들어
# 거기서 한 번 수동으로 TouchEn nxWeb을 설치해둬도 됩니다.
D2B_EDGE_PROFILE_DIR = os.environ.get(
    "D2B_EDGE_PROFILE_DIR",
    os.path.expanduser("~/.d2b_edge_profile"),
)

D2B_LIST_URL = "https://www.d2b.go.kr/mainBidAnnounceList.do"
# 방화벽/백신이 막고 있던 문제를 해결한 뒤 실제로 확인해보니(2026-08-18 실행 로그),
# DNS/네트워크 접속 자체는 정상화됐지만 이번엔 전부 "Timeout 15000ms exceeded -
# waiting for locator(a.fgirdB)"로 실패했습니다. 즉 검색 버튼을 누른 뒤 결과 그리드
# (구형 SBGrid 커스텀 컴포넌트)가 15초 안에 렌더링되지 않는다는 뜻입니다. 실제로
# 사람이 브라우저로 똑같이 검색해봐도 결과가 뜨는 데 상당히 오래 걸리는 걸
# 확인해서(사이트 자체가 오래된 방식이라 느림), 타임아웃을 넉넉하게 늘렸습니다.
ACTION_TIMEOUT_MS = 45000
NAV_TIMEOUT_MS = 45000
UNVERIFIED_NOTE = "지역/면허제한 자동확인 실패-공고문 직접확인 필요"
# 공고 한 건이 최악의 경우(타임아웃 연속) ACTION_TIMEOUT_MS 근처까지 걸릴 수 있어서,
# 사이트 자체가 막혀있는 날(예: 점검, 자동화 차단)에 전체 수집이 너무 오래 걸리지
# 않도록 전체 소요시간 상한을 둡니다. 이 시간을 넘기면 남은 공고는 더 시도하지 않고
# 바로 "자동확인 실패"로 표시합니다. (타임아웃을 45초로 늘렸으므로, 47건 기준
# 최악의 경우 47 * 약 50초 ≈ 40분까지 걸릴 수 있어 상한도 함께 늘렸습니다.)
MAX_TOTAL_SECONDS = 2700


def enrich_d2b_bids_with_restrictions(bids):
    """D2B 공고 리스트(dict)를 받아 각 항목의 region/restrictions/eligible을
    실제 공고문 기준으로 채워서 반환한다. 이 함수 자체가 통째로 실패해도
    원본 bids를 그대로 반환해서 D2B 수집 전체가 죽지 않게 한다."""
    if not bids:
        return bids

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[D2B 공고문 확인] Playwright 미설치로 건너뜀 (전체 {len(bids)}건은 자동확인 실패로 표시): {e}")
        for bid in bids:
            _mark_unverified(bid)
        return bids

    import time

    ok_count = 0
    fail_count = 0
    skipped_count = 0
    try:
        with sync_playwright() as p:
            context, browser, mode = _launch_browser_context(p)
            if context is None:
                print("[D2B 공고문 확인] 브라우저 실행 자체가 실패해서 건너뜀")
                for bid in bids:
                    if "eligible" not in bid or bid.get("restrictions", "") == "":
                        _mark_unverified(bid)
                return bids

            print(f"[D2B 공고문 확인] 브라우저 모드: {mode}")
            start = time.time()
            try:
                page = context.new_page()
                page.set_default_timeout(ACTION_TIMEOUT_MS)
                page.set_default_navigation_timeout(NAV_TIMEOUT_MS)

                for bid in bids:
                    if time.time() - start > MAX_TOTAL_SECONDS:
                        skipped_count += 1
                        _mark_unverified(bid)
                        continue

                    try:
                        result = _lookup_one(page, bid.get("title", ""), bid.get("notice_no", ""))
                    except Exception as e:
                        result = None
                        print(f"[D2B 공고문 확인] 실패: {bid.get('title','')[:30]} ({e})")

                    if result is None:
                        fail_count += 1
                        _mark_unverified(bid)
                    else:
                        licenses, regions = result
                        _apply_restriction_result(bid, licenses, regions)
                        ok_count += 1
            finally:
                context.close()
                if browser is not None:
                    browser.close()
    except Exception as e:
        print(f"[D2B 공고문 확인] 예상치 못한 오류로 중단됨: {e}")
        for bid in bids:
            if "eligible" not in bid or bid.get("restrictions", "") == "":
                _mark_unverified(bid)
        return bids

    print(
        f"[D2B 공고문 확인] {ok_count}건 확인 성공, {fail_count}건 실패, "
        f"{skipped_count}건 시간초과로 건너뜀 (실패/건너뜀 건은 공고문 직접확인 필요로 표시)"
    )
    return bids


def _launch_browser_context(p):
    """가능하면 이 PC에 실제 설치된 Edge(TouchEn nxWeb이 설치된 프로필)를 그대로
    구동하고, 안 되면 Playwright 전용 크로미움(headless)으로 대체한다.
    (context, browser_또는_None, 사용된 모드 설명) 튜플을 반환한다.
    완전히 실패하면 (None, None, None).

    실제 Edge 프로필을 쓰는 경우 headless=False로 띄운다 - TouchEn nxWeb 같은
    콘텐츠 보호 프로그램은 브라우저 확장/프로세스를 정상적으로 인식해야 동작
    하는데, 그러려면 실제로 화면에 렌더링되는 일반 실행 방식이어야 할 가능성이
    높기 때문입니다(이 PC는 실제 사람이 로그인해 쓰는 데스크톱이라 화면 표시가
    가능합니다). launch_persistent_context는 context 자체가 곧 browser 역할을
    해서 별도 browser 객체가 없으므로 두 번째 값은 None을 반환한다."""
    try:
        context = p.chromium.launch_persistent_context(
            D2B_EDGE_PROFILE_DIR,
            channel="msedge",
            headless=False,
        )
        return context, None, f"실제 Edge 브라우저 (프로필: {D2B_EDGE_PROFILE_DIR})"
    except Exception as e:
        print(
            f"[D2B 공고문 확인] 실제 Edge 프로필로 실행 실패, 기본 방식(headless "
            f"크로미움)으로 대체합니다 - 이 경우 TouchEn nxWeb 보안 체크를 통과하지 "
            f"못해 계속 '자동확인 실패'로 표시될 가능성이 높습니다: {e}"
        )

    try:
        browser = p.chromium.launch(headless=True)
        return browser.new_context(), browser, "Playwright 기본 크로미움 (headless, TouchEn nxWeb 없음)"
    except Exception as e:
        print(f"[D2B 공고문 확인] 기본 크로미움 실행도 실패: {e}")
        return None, None, None


def _lookup_one(page, title, pblanc_no):
    """공고명으로 검색해서, 우리가 수집한 공고번호(pblancNo)와 일치하고
    "취소공고"가 아닌 결과를 찾아 열고 (면허목록, 지역목록)을 반환한다.
    못 찾으면 None."""
    if not title or not pblanc_no:
        return None

    page.goto(D2B_LIST_URL, wait_until="domcontentloaded")
    page.fill("#anmt_name", title)
    page.click("#btn_search")
    try:
        page.wait_for_selector("a.fgirdB", timeout=ACTION_TIMEOUT_MS)
    except Exception:
        # 결과 링크가 끝내 안 나타난 경우: "검색결과 0건"인지(정상 - 그냥 못 찾은 것)
        # 아니면 그리드 자체가 안 뜬 것인지(비정상 - 사이트 구조 변경/차단 의심) 구분해서
        # 로그에 남깁니다. 다음 실행 때 원인 파악에 필요한 최소한의 진단 정보입니다.
        try:
            no_data = page.query_selector("text=표시할 데이터가 없습니다")
            diag = "검색결과 0건(정상)" if no_data else f"원인불명 - 현재 URL: {page.url}"
        except Exception:
            diag = "진단 실패"
        print(f"[D2B 공고문 확인] 결과 그리드 미출현: {title[:30]} - {diag}")
        raise
    page.wait_for_timeout(800)  # 커스텀 그리드(SBGrid) 렌더링 여유시간

    rows = page.query_selector_all("table tr")
    for row in rows:
        try:
            row_text = row.inner_text()
        except Exception:
            continue
        if pblanc_no not in row_text or "취소" in row_text:
            continue
        link = row.query_selector("a.fgirdB")
        if not link:
            continue
        link.click()
        try:
            page.wait_for_selector('table[summary="상세테이블"]', timeout=ACTION_TIMEOUT_MS)
        except Exception:
            return None
        page.wait_for_timeout(500)
        return _extract_restriction_info(page)

    return None


def _extract_restriction_info(page):
    """상세 페이지에서 면허제한/제한지역 표를 읽어 (면허명 리스트, 지역명 리스트)로 반환.
    표가 아예 없으면(=제한 없음) 빈 리스트."""
    licenses = []
    regions = []

    try:
        license_table = page.query_selector('table[summary="공종 및 면허제한"]')
        if license_table:
            for row in license_table.query_selector_all("tr"):
                cells = row.query_selector_all("td")
                if not cells:
                    continue
                name = cells[-1].inner_text().strip()
                name = name.split("[")[0].strip()
                if name:
                    licenses.append(name)
    except Exception:
        pass

    try:
        for table in page.query_selector_all('table[summary="목록테이블"]'):
            header_text = table.inner_text()
            if "지역1" not in header_text:
                continue
            for row in table.query_selector_all("tr"):
                for cell in row.query_selector_all("td"):
                    txt = cell.inner_text().strip()
                    txt = txt.split("[")[0].strip()
                    if txt:
                        regions.append(txt)
            break
    except Exception:
        pass

    return licenses, regions


def _apply_restriction_result(bid, licenses, regions):
    from scrapers._common import is_eligible_region

    region_text = ",".join(dict.fromkeys(regions))  # 순서 유지 중복제거 ("지역" 컬럼 표시용)
    has_restriction = bool(regions)

    # 주의: restrictions는 대시보드에서 쉼표(,) 기준으로 배지를 나눠서 표시하므로,
    # 괄호 안에서 여러 면허/지역을 나열할 때는 쉼표 대신 "/"를 써야 배지가 깨지지 않음.
    tags = []
    if licenses:
        tags.append("면허제한(" + "/".join(dict.fromkeys(licenses)) + ")")
    if has_restriction:
        tags.append("지역제한(" + "/".join(dict.fromkeys(regions)) + ")")

    bid["restrictions"] = ", ".join(tags)
    bid["region"] = region_text
    bid["eligible"] = is_eligible_region(
        region_text, bid.get("org", ""), bid.get("title", ""),
        has_region_restriction=has_restriction,
    )


def _mark_unverified(bid):
    existing = (bid.get("restrictions") or "").strip()
    if UNVERIFIED_NOTE not in existing:
        bid["restrictions"] = (existing + ", " if existing else "") + UNVERIFIED_NOTE
    # eligible은 건드리지 않는다 - d2b.py가 채워둔 기본값(True)을 그대로 둬서
    # "확인 실패"가 "참가불가 확정"으로 둔갑해 목록에서 사라지지 않게 한다.
