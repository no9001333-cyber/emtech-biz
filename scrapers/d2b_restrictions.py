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
  4) (2026-08-25 추가) "기초예비가격" 탭도 같은 페이지에서 클릭해서 실제
     기초금액/예가변동폭(하한·상한%)/A값 구성요소(국민건강보험료·국민연금
     보험료·요양보험료·산업안전보건관리비·퇴직공제부금·안전관리비·품질관리비)
     를 읽어옵니다. 사용자가 투찰금액 계산 모달에서 D2B 공고는 전부
     "기본값"/"확인필요"만 뜬다고 지적해서 확인해보니, 공식 API(getFcltyCmpetBidPblancList)엔
     이 정보가 아예 없지만 실제 공고문 상세페이지엔 이미 다 공개돼 있었습니다
     (투찰하려면 입찰자가 기초금액을 미리 알아야 하니 당연히 공고 시점에
     정해져 있는 게 맞다고 사용자가 지적한 대로). 다만 D2B의 낙찰하한율은
     G2B처럼 명확한 퍼센트 값으로 안 나오고 별도 규정 문구로만 있어서,
     잘못된 값을 억지로 계산해 채우지 않고 계속 "확인필요"로 남겨둡니다.

주의 (일부러 방어적으로 짬):
  - 공식 API가 아니라 실제 웹페이지를 여는 방식이라 사이트 구조가 바뀌거나
    일시적으로 느려지면 깨질 수 있습니다. 그래서 공고 하나가 실패해도 전체
    수집이 죽지 않도록 개별적으로 try/except로 감쌉니다.
  - 확인에 실패한 공고는 restrictions에 "자동확인 실패 - 공고문 직접 확인
    필요"라고 명시할 뿐, eligible은 건드리지 않습니다(d2b.py가 기본값 True로
    채워둔 것을 그대로 둠). 확인 안 됐다는 것과 확인 결과 참가불가라는 것은
    다른 얘기라, 실패했다고 "참가불가"로 확정해서 목록에서 숨기지 않습니다.
  - Playwright 자체가 설치 안 되어 있거나 브라우저 실행이 안 되면, 이 기능
    전체를 건너뛰고 기존 수집 결과를 그대로 반환합니다 - 이것 때문에 전체
    수집(공고 목록 자체)이 죽으면 안 되기 때문입니다.

중요 - 2026-08-25에 밝혀진 진짜 원인 (TouchEn nxWeb 문제가 아니었음):
  한동안 이 검색이 headless 크로미움에서 계속 멈추거나 실패해서, "d2b.go.kr이
  라온시큐어 TouchEn nxWeb 보안 프로그램을 요구하고, 그게 설치 안 된 브라우저는
  막힌다"고 잘못 진단하고 실제 Edge 프로필을 띄우는 우회 로직까지 만들었었습니다.
  그런데 사용자가 "나는 그냥 홈페이지에서 공고명 넣으면 바로 들어간다"고 알려줘서
  직접 재현해보니: **입찰공고 목록 페이지(mainBidAnnounceList.do)로 곧장
  이동(page.goto)하면 그 페이지 자체가 응답 없이 멈춰버리지만, 홈페이지
  (index.do)를 먼저 열고 거기 내장된 검색창(#anmt_name)에 입력 후 검색
  버튼(#btn_search)을 누르면 아무 보안 프로그램 없이도 정상적으로
  mainBidAnnounceList.do로 결과가 뜹니다.** 즉 원인은 보안 소프트웨어가 아니라
  진입 경로(직접 URL 이동 vs 홈페이지 경유 검색 제출)였습니다. 두 페이지의
  검색창/버튼 id, 결과 링크(a.fgirdB), 상세 테이블(table[summary="상세테이블"])
  구조가 전부 동일해서, 시작 URL만 홈페이지로 바꾸면 나머지 코드는 그대로
  씁니다. Edge/TouchEn nxWeb 우회 로직은 불필요해져서 제거했습니다.
"""

D2B_LIST_URL = "https://www.d2b.go.kr/index.do"
ACTION_TIMEOUT_MS = 45000
NAV_TIMEOUT_MS = 45000
UNVERIFIED_NOTE = "지역/면허제한 자동확인 실패-공고문 직접확인 필요"
# 공고 한 건이 최악의 경우(타임아웃 연속) ACTION_TIMEOUT_MS 근처까지 걸릴 수 있어서,
# 사이트 자체가 막혀있는 날(예: 점검, 자동화 차단)에 전체 수집이 너무 오래 걸리지
# 않도록 전체 소요시간 상한을 둡니다. 이 시간을 넘기면 남은 공고는 더 시도하지 않고
# 바로 "자동확인 실패"로 표시합니다.
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
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                print(f"[D2B 공고문 확인] 브라우저 실행 자체가 실패해서 건너뜀: {e}")
                for bid in bids:
                    if "eligible" not in bid or bid.get("restrictions", "") == "":
                        _mark_unverified(bid)
                return bids

            start = time.time()
            try:
                page = browser.new_context().new_page()
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
                        licenses, regions, basis_info = result
                        _apply_restriction_result(bid, licenses, regions, basis_info)
                        ok_count += 1
            finally:
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


def _lookup_one(page, title, pblanc_no):
    """공고명으로 검색해서, 우리가 수집한 공고번호(pblancNo)와 일치하고
    "취소공고"가 아닌 결과를 찾아 열고 (면허목록, 지역목록, 기초금액정보)를
    반환한다. 못 찾으면 None. 기초금액정보는 탭이 없거나(물품/용역 등) 파싱에
    실패하면 None으로 채워지되, 그것 때문에 면허/지역 확인 자체가 실패로
    처리되지는 않는다(둘은 독립적인 정보라 한쪽이 없어도 다른 쪽은 살림)."""
    if not title or not pblanc_no:
        return None

    # 목록 페이지로 곧장 이동하면 응답 없이 멈춰버려서, 반드시 홈페이지를 먼저
    # 열고 거기 내장된 검색창으로 제출해야 한다 (모듈 docstring의 2026-08-25 원인 참고).
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
        licenses, regions = _extract_restriction_info(page)
        basis_info = _extract_basis_amount_info(page) or {}
        open_date = _extract_open_date(page)
        if open_date:
            basis_info["open_date"] = open_date
        return licenses, regions, (basis_info or None)

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


def _cell_text_to_int(text):
    """'1,144,179 원' 같은 표시 문자열에서 숫자만 뽑아 int로. 빈 값/파싱 실패는 None."""
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _cell_text_to_float(text):
    """'-2.0 %' 같은 표시 문자열에서 부호 있는 소수만 뽑아 float로. 파싱 실패는 None."""
    import re
    if not text:
        return None
    m = re.search(r"-?[0-9]+(\.[0-9]+)?", text)
    return float(m.group()) if m else None


# A값(법정 정산항목 합계)을 구성하는 항목들 - g2b_basis_amount.py가 나라장터에서
# 쓰는 정의(산업안전보건관리비/안전관리비/퇴직공제부금비/국민건강보험료/
# 국민연금보험료/노인장기요양보험료/품질관리비)와 이름만 다를 뿐 동일한 개념이라
# 그대로 맞춰서 합산합니다.
A_VALUE_LABELS = [
    "국민건강보험료", "국민연금보험료", "요양보험료",
    "산업안전보건관리비", "퇴직공제부금", "안전관리비", "품질관리비",
]


def _extract_basis_amount_info(page):
    """상세 페이지의 "기초예비가격" 탭에서 실제 기초금액/예가변동폭/A값 구성요소를
    읽는다. 탭 자체가 없거나(물품/용역 등 기초예비가격 미적용 공고) 파싱에
    실패하면 None을 반환한다 - 없는 값을 억지로 만들어내지 않는다."""
    try:
        tab_link = page.query_selector('a[href="#tab_content03"]')
        if not tab_link:
            return None
        tab_link.click()
        page.wait_for_timeout(300)

        # th(라벨)-td(값) 쌍을 같은 행(tr) 안에서 DOM 순서 그대로 짝지어야 정확합니다 -
        # 페이지 전체의 th 목록과 td 목록을 따로 뽑아 인덱스로 매칭하면, 라벨 없는
        # 빈 td(예: 기초예비가격 한글 표기용 셀)가 하나 끼어있어서 그 뒤로 전부
        # 한 칸씩 밀리는 오탐이 있었습니다(직접 재현해서 확인함).
        pairs = page.evaluate("""
            () => {
                const el = document.getElementById('tab_content03');
                if (!el) return null;
                const out = {};
                for (const tr of el.querySelectorAll('tr')) {
                    const cells = Array.from(tr.children);
                    for (let i = 0; i < cells.length - 1; i++) {
                        if (cells[i].tagName === 'TH' && cells[i].textContent.trim()) {
                            if (cells[i + 1].tagName === 'TD') {
                                out[cells[i].textContent.trim()] = cells[i + 1].textContent.trim();
                            }
                        }
                    }
                }
                return out;
            }
        """)
        if not pairs:
            return None

        base_amount = _cell_text_to_int(pairs.get("기초예비가격"))
        variance_low = _cell_text_to_float(pairs.get("하한(%)"))
        variance_high = _cell_text_to_float(pairs.get("상한(%)"))

        a_value = None
        a_components = [_cell_text_to_int(pairs.get(label)) for label in A_VALUE_LABELS]
        if any(v is not None for v in a_components):
            a_value = sum(v or 0 for v in a_components)

        if base_amount is None and a_value is None and variance_low is None:
            return None  # 탭은 있었지만 값이 전부 비어있음(기초예비가격 미적용 공고 등)

        return {
            "base_amount": base_amount,
            "a_value": a_value,
            "variance_pct": abs(variance_low) if variance_low is not None else (
                variance_high if variance_high is not None else None
            ),
        }
    except Exception:
        return None


def _extract_open_date(page):
    """상세 페이지 기본 탭(입찰진행정보)에서 개찰일시를 읽는다. D2B 공식 API
    (getFcltyCmpetBidPblancList)엔 개찰일시 필드가 없어서, 이미 지역/면허제한
    확인을 위해 열어둔 이 상세페이지에서 같이 읽어온다. 못 찾으면 빈 문자열."""
    try:
        th = page.query_selector('th:has-text("개찰일시")')
        if not th:
            return ""
        # th 바로 다음 형제가 값이 든 td인 구조 (기초예비가격 탭과 동일 패턴).
        value = page.evaluate("""
            (thEl) => {
                let sib = thEl.nextElementSibling;
                while (sib && sib.tagName !== 'TD') sib = sib.nextElementSibling;
                return sib ? sib.textContent.trim() : '';
            }
        """, th)
        return value or ""
    except Exception:
        return ""


def _apply_restriction_result(bid, licenses, regions, basis_info=None):
    from scrapers._common import get_region_scope

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
    scope = get_region_scope(
        region_text, bid.get("org", ""), bid.get("title", ""),
        has_region_restriction=has_restriction,
    )
    bid["region_scope"] = scope
    bid["eligible"] = scope is not None

    if basis_info:
        if basis_info.get("base_amount") is not None:
            bid["base_amount"] = str(basis_info["base_amount"])
            bid["base_amount_confirmed"] = True
        # A값은 0원도 정상적인 실제값이라 None(데이터 없음)과 구분해서 채운다.
        if basis_info.get("a_value") is not None:
            bid["a_value"] = str(basis_info["a_value"])
        if basis_info.get("variance_pct") is not None:
            bid["bid_variance_pct"] = basis_info["variance_pct"]
        if basis_info.get("open_date"):
            bid["open_date"] = basis_info["open_date"]


def _mark_unverified(bid):
    existing = (bid.get("restrictions") or "").strip()
    if UNVERIFIED_NOTE not in existing:
        bid["restrictions"] = (existing + ", " if existing else "") + UNVERIFIED_NOTE
    # eligible은 건드리지 않는다 - d2b.py가 채워둔 기본값(True)을 그대로 둬서
    # "확인 실패"가 "참가불가 확정"으로 둔갑해 목록에서 사라지지 않게 한다.
