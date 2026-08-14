"""
공통 설정 파일
- 검색 키워드 / 대상 지역 / API 키를 여기서 관리합니다.
- API 키는 절대 코드에 직접 적지 말고, 환경변수(GitHub Actions Secrets)로 주입합니다.
"""

import os

# ── 검색 키워드 (공고명에 아래 단어 중 하나라도 포함되면 "통신공사" 관련으로 판단) ──
KEYWORDS = ["통신", "정보통신", "네트워크", "광통신", "무선통신"]

# ── 대상 지역 (공고의 지역/참가가능지역 정보에 아래 단어가 포함되면 통과) ──
# "전국"으로 공고된 건은 지역 필터와 무관하게 항상 포함됩니다.
REGIONS = ["용인", "경기", "전국"]

# ── 발주기관에 아래 단어가 포함되면, 지역 정보와 무관하게 항상 포함 ──
# (한전/철도공단처럼 전국구 발주기관은 지역 필드가 비어있어도 실제로는 전국 대상인 경우가 많음)
# 주의: "조달청"은 넣지 않음 — 지방조달청이 대행하는 공고는 실제 사업장이 특정 지역에
# 한정된 경우가 대부분이라, 여기 넣으면 지역 필터가 사실상 무력화됨.
ALWAYS_INCLUDE_ORGS = [
    "한국전력공사", "한국철도공사", "국가철도공단",
]

# ── 발주기관명/공고명에 아래 지역명이 포함되면 무조건 제외 (대상 외 지역 사업) ──
# 나라장터 API의 "참가가능지역" 필드가 비어있어도(=참가는 전국 어디서나 가능해도)
# 실제 사업 현장이 이 지역들이면 실익이 없으므로, 발주기관명에서 지역을 유추해 걸러냄.
EXCLUDE_REGION_KEYWORDS = [
    "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "강원", "충북", "충남", "충청북도", "충청남도",
    "전북", "전남", "전라북도", "전라남도",
    "경북", "경남", "경상북도", "경상남도",
    "제주",
]

# ── 우리 회사 소재지: 용인시(경기도) ──
# 지역제한 공고에 참가 가능한지 판단할 때 기준이 되는 값.
HOME_CITY = "용인"
HOME_PROVINCE = "경기"

# ── 경기도 소속이지만 용인이 아닌 다른 시·군 (지역제한이 이 시·군으로 걸리면 참가 불가) ──
# "경기도 OO시"처럼 특정 시·군이 명시된 공고는, 그 시·군이 용인이 아니면 참가할 수 없음.
GYEONGGI_OTHER_CITIES = [
    "수원", "성남", "안양", "안산", "고양", "과천", "구리", "군포", "김포",
    "남양주", "동두천", "부천", "시흥", "안성", "양주", "오산", "의왕",
    "의정부", "이천", "파주", "평택", "포천", "하남", "화성",
    "가평", "양평", "여주", "연천",
]

# ── 투찰마감까지 남은 일수 범위 (이 범위 밖의 공고는 목록에서 제외) ──
# 너무 임박하면 준비할 시간이 없고, 너무 멀면 아직 실익이 없어서 기본값을 7~30일로 둠.
# 마감이 지난 뒤에도 개찰 결과(낙찰자/낙찰금액)를 확인할 수 있도록,
# 마감 후 POST_DEADLINE_TRACK_DAYS일까지는 목록에 계속 남겨둠.
MIN_DAYS_UNTIL_DEADLINE = 7
MAX_DAYS_UNTIL_DEADLINE = 30
POST_DEADLINE_TRACK_DAYS = 21

# ── 자동 연동이 안 되는(자체 조달시스템만 운영하는) 발주기관 바로가기 링크 ──
# 공개 API가 없어 자동 수집은 못 하지만, 최소한 클릭 한 번으로 확인할 수 있게 대시보드에 노출.
EXTERNAL_MANUAL_LINKS = [
    {"name": "한국철도공사(코레일) 자체 시스템", "url": "https://ebid.korail.com/"},
    {"name": "한국가스공사", "url": "http://bid.kogas.or.kr/"},
    {"name": "한국석유공사", "url": "https://ebid.knoc.co.kr/"},
]

# ── data.go.kr(공공데이터포털)에서 발급받은 서비스키 ──
# 나라장터: "조달청_나라장터 입찰공고정보서비스" 활용신청 후 발급
# LH:      "한국토지주택공사 입찰공고정보" 활용신청 후 발급
# 군부대(D2B): "방위사업청_군수품조달정보 입찰공고" 활용신청 후 발급
#            (참고: 군 공사 입찰공고는 법령상 나라장터에도 동시 공고되므로,
#             G2B 수집만으로도 상당수 군 공사 건이 함께 잡힙니다.)
G2B_SERVICE_KEY = os.environ.get("G2B_SERVICE_KEY", "")
LH_SERVICE_KEY = os.environ.get("LH_SERVICE_KEY", "")
D2B_SERVICE_KEY = os.environ.get("D2B_SERVICE_KEY", "")
KWATER_SERVICE_KEY = os.environ.get("KWATER_SERVICE_KEY", "")
KEPCO_API_KEY = os.environ.get("KEPCO_API_KEY", "")
KORAIL_SERVICE_KEY = os.environ.get("KORAIL_SERVICE_KEY", "")
KR_SERVICE_KEY = os.environ.get("KR_SERVICE_KEY", "")

# ── 대시보드 접근 비밀번호 (선택) ──
# 설정하면 대시보드를 열 때 비밀번호 입력 화면이 먼저 뜹니다.
# GitHub Secrets에 DASHBOARD_PASSWORD를 등록하면 자동으로 적용됩니다.
# 주의: 정적 웹페이지라 완벽한 보안은 아니고, 검색엔진 노출 방지 + 아무나 못 들어오게
#       막는 정도의 기본 보호입니다. 비워두면 비밀번호 없이 그대로 공개됩니다.
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
G2B_AWARDS_SERVICE_KEY = os.environ.get("G2B_AWARDS_SERVICE_KEY", "")

# ── 조회 기간 (기본: 최근 N일 이내 공고) ──
# 매일 자동 수집이지만, 혹시 놓친 공고가 없도록 넉넉하게 30일치를 매번 다시 확인합니다.
# (data/bids.json에 계속 누적되므로 30일보다 오래된 공고도 한 번 수집되면 계속 남아있습니다)
LOOKBACK_DAYS = 30

# ── 산출물 경로 ──
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BIDS_JSON_PATH = os.path.join(DATA_DIR, "bids.json")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
AWARDS_JSON_PATH = os.path.join(DATA_DIR, "awards.json")
STATUS_JSON_PATH = os.path.join(DATA_DIR, "status.json")
DASHBOARD_HTML_PATH = os.path.join(DOCS_DIR, "index.html")
