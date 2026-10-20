"""
국방전자조달(d2b.go.kr) 공사 공고의 면허·지역제한·기초예비가격을 브라우저 없이 가져온다.

2026-10-20: 예전엔 Playwright로 홈페이지 통합검색에 공고명을 넣어 상세를 열었는데,
  - 공고 하나에 약 50초가 걸려 45분 상한 안에 200여 건 중 50~60건만 확인됐고,
  - 시설 공개수의(소액 수의견적) 공고는 그 검색에 안 잡혀 매번 29건이 실패했다.
공사 입찰공고 화면(/peb/bid/announceList.do)이 내부적으로 쓰는 요청을 그대로 쓰면 된다:
  1) POST /peb/bid/getAnnounceList.json  (search_numb=공고번호) → 판단번호·부서·차수·구분(lv2Divs)
  2) 상세 POST - 경쟁입찰(lv2Divs=1): /peb/bid/announceView.do
                 공개수의(lv2Divs=2): /peb/openNego/openNegoPlanView.do
  3) 상세 HTML의 "공종 및 면허제한"(그룹별 면허, 같은 그룹은 모두 보유, 그룹 간은 하나 이상)과
     "제한지역", "기초예비가격"·A값 항목을 읽는다.
"""

import html as _html
import re
from datetime import datetime, timedelta

import requests

BASE = "https://www.d2b.go.kr"
_LIST = f"{BASE}/peb/bid/getAnnounceList.json"
_VIEW_COMP = f"{BASE}/peb/bid/announceView.do"
_VIEW_NEGO = f"{BASE}/peb/openNego/openNegoPlanView.do"


class D2BClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Mozilla/5.0"
        self.s.get(f"{BASE}/index.do", timeout=30)

    def find(self, notice_no):
        """공고번호(예: LPK0193, LPK0193-1)로 목록 행을 찾는다. 최신 차수·취소 아닌 것 우선."""
        base_no = notice_no.split("-")[0]
        today = datetime.now()
        data = {
            "date_divs": "1", "date_from": (today - timedelta(days=150)).strftime("%Y%m%d"),
            "date_to": (today + timedelta(days=150)).strftime("%Y%m%d"),
            "search_divs": "", "anmt_divs": "", "dprt_name": "", "dprt_code": "", "edix_gtag": "",
            "anmt_name": "", "numb_divs": "1", "lice_code": "", "lice_name": "", "search_numb": base_no,
            "area_name": "", "currentPageNo": "1",
        }
        r = self.s.post(_LIST, data=data, timeout=40,
                        headers={"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/peb/bid/announceList.do?key=41"})
        rows = [x for x in (r.json().get("list") or []) if x.get("anmtNumb") == base_no]
        if not rows:
            return None
        rows.sort(key=lambda x: (x.get("anmtCncl") != "Y", int(x.get("rqstDegr") or 0)), reverse=True)
        return rows[0]

    def detail_text(self, row):
        if row.get("lv2Divs") == "2":
            url, data = _VIEW_NEGO, {
                "csrt_numb": row["dcsnNumb"], "negn_pldt": row.get("anmtDate", ""), "dprt_code": row["dprtCode"],
                "ordr_year": row["rqstYear"], "negn_degr": row["rqstDegr"], "anmt_numb": row["anmtNumb"],
                "pageDivs": "E", "list_url": "/peb/bid/announceList.do", "searchData": "{}",
            }
        else:
            url, data = _VIEW_COMP, {
                "dprt_code": row["dprtCode"], "anmt_divs": row.get("anmtDivs") or "", "anmt_numb": row["anmtNumb"],
                "rqst_degr": row["rqstDegr"], "dcsn_numb": row["dcsnNumb"], "rqst_year": row["rqstYear"],
                "bsic_stat": row.get("bsicStat") or "", "dmst_itnb": row.get("dmstItnb") or "",
                "anmt_date": row.get("anmtDate", ""), "csrt_numb": row["dcsnNumb"], "lv2Divs": row.get("lv2Divs", "1"),
                "cont_mthd": row.get("contMthd") or "", "pageDivs": "E1", "lv1_divs": row.get("lv1Divs") or "PEB",
                "searchData": "{}",
            }
        h = self.s.post(url, data=data, timeout=40).text
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
        text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
        return re.sub(r"\s+", " ", text)


def _num(s):
    try:
        return int(float(s.replace(",", "")))
    except (TypeError, ValueError, AttributeError):
        return None


def parse_detail(text):
    """상세 텍스트에서 (면허 그룹 리스트, 제한지역 리스트, 기초금액 정보)를 뽑는다."""
    groups = {}
    sec = re.search(r"그룹 면허 명칭\[코드\](.*?)(?:제한지역|첨부서류|문의처)", text)
    if sec:
        for g, name, _code in re.findall(r"(\d+)\s+([^\[\]]+?)\[(\d{4})\]", sec.group(1)):
            groups.setdefault(g, []).append(name.strip())
    regions = []
    sec = re.search(r"제한지역 지역1 지역2 지역3 지역4 지역5(.*?)(?:첨부서류|문의처|기초예비가격|목록)", text)
    if sec:
        for name in re.findall(r"([가-힣][가-힣\s]*?)\s*\[\d+\]", sec.group(1)):
            name = name.strip()
            if name and name not in regions:
                regions.append(name)
    basis = {}
    m = re.search(r"기초예비가격\s*(?:기초예비가격\s*)?([\d,]+(?:\.\d+)?)\s*원", text)
    if m:
        basis["base_amount"] = _num(m.group(1))
    a = 0
    found_a = False
    for label in ("국민건강보험료", "국민연금보험료", "요양보험료", "산업안전보건관리비", "퇴직공제부금", "안전관리비", "품질관리비"):
        mm = re.search(label + r"\s*([\d,]+)\s*원", text)
        if mm:
            a += _num(mm.group(1)) or 0
            found_a = True
    if found_a:
        basis["a_value"] = a
    m = re.search(r"하한\(%\)\s*(-?[\d.]+)\s*%?\s*상한\(%\)\s*(-?[\d.]+)", text)
    if m:
        basis["variance_pct"] = f"{m.group(1)}~{m.group(2)}"
    return list(groups.values()), regions, basis
