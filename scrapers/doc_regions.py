"""
공고문(HWP/HWPX/PDF) 본문 추출과, 참가자격 문구에서 "지역제한 지역"을 뽑는 공용 함수.

2026-09-28: 한국수자원공사처럼 API/상세 JSON에 지역제한이 구조화돼 있지 않고
참가자격 문구("지역제한(경기도)", "본점 소재지가 전북특별자치도에 있는 업체")나
공고문 파일에만 적혀 있는 발주처를 위해 만들었다. HWP5 파일은 OLE 컨테이너 안의
BodyText/SectionN 스트림(대개 zlib 압축)에 문단 텍스트 레코드(tag 67)가 UTF-16으로
들어 있어서 olefile만으로 읽을 수 있다.

주의: 지역명이 하나도 없는 문구를 get_region_scope()에 넘기면 "지역 정보 없음 = 전국"
으로 판정되므로, 반드시 extract_restricted_regions()로 지역명이 실제로 있는지 먼저
확인하고, 없으면 "미확인"으로 다룬다.
"""

import io
import re
import struct
import zipfile
import zlib

# (정규식, 표준 지역명). 순서 중요: 긴 이름/특수 이름을 먼저 본다.
_PROVINCES = [
    (r"서울", "서울특별시"),
    (r"인천", "인천광역시"),
    (r"부산", "부산광역시"),
    (r"대구", "대구광역시"),
    (r"전남광주|광주광역시|광주시(?!\S)", "광주광역시"),
    (r"대전", "대전광역시"),
    (r"울산", "울산광역시"),
    (r"세종", "세종특별자치시"),
    (r"강원", "강원특별자치도"),
    (r"충청북도|충북", "충청북도"),
    (r"충청남도|충남", "충청남도"),
    (r"전라북도|전북", "전북특별자치도"),
    (r"전라남도|전남", "전라남도"),
    (r"경상북도|경북", "경상북도"),
    (r"경상남도|경남", "경상남도"),
    (r"제주", "제주특별자치도"),
]

# 참가자격 중 "지역"을 말하는 문맥 표지. 공고문 전체를 훑으면 공사 위치(현장 주소)
# 같은 무관한 지역명까지 걸리므로, 이 표지 뒤쪽 일정 길이만 본다.
_CONTEXT_CUES = re.compile(r"지역제한|지역\s*제한|본점\s*소재지|본점소재지|소재지가|주된\s*영업소|참가\s*가능\s*지역|참가가능지역")
_WINDOW = 160


def extract_restricted_regions(text, gyeonggi_other_cities=(), whole_text_is_qualification=False):
    """문구에서 지역제한 지역 목록을 뽑는다. 못 찾으면 [].

    whole_text_is_qualification=True면(예: K-water 상세의 참가자격 요약 문구처럼 텍스트
    전체가 참가자격 설명인 경우) 문맥 표지 없이 전체를 본다. 공고문 본문처럼 긴 글은
    False로 두고 표지 주변만 본다."""
    text = text or ""
    if whole_text_is_qualification:
        windows = [text]
    else:
        windows = [text[m.start(): m.end() + _WINDOW] for m in _CONTEXT_CUES.finditer(text)]
    found = []

    def add(name):
        if name not in found:
            found.append(name)

    for w in windows:
        # 경기도는 시·군까지 같이 본다(용인이면 용인, 다른 시·군이면 그 시·군으로 못박힌 제한).
        for m in re.finditer(r"용인", w):
            add("경기도 용인시")
        for m in re.finditer(r"경기(?:도)?", w):
            tail = w[m.end(): m.end() + 12]
            city = next((c for c in gyeonggi_other_cities if c in tail), None)
            add(f"경기도 {city}" if city else "경기도")
        for pat, name in _PROVINCES:
            if re.search(pat, w):
                add(name)
        # "경기도 용인시"가 잡혔으면 같은 문맥의 단순 "경기도"는 중복이라 뺀다.
    if "경기도 용인시" in found and "경기도" in found:
        found.remove("경기도")
    return found


def _hwp5_text(data):
    import olefile  # requirements.txt에 추가됨
    ole = olefile.OleFileIO(io.BytesIO(data))
    header = ole.openstream("FileHeader").read()
    compressed = bool(header[36] & 1)
    parts = []
    i = 0
    while ole.exists(f"BodyText/Section{i}"):
        raw = ole.openstream(f"BodyText/Section{i}").read()
        if compressed:
            raw = zlib.decompress(raw, -15)
        p = 0
        while p + 4 <= len(raw):
            h = struct.unpack_from("<I", raw, p)[0]
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            p += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", raw, p)[0]
                p += 4
            if tag == 67:  # HWPTAG_PARA_TEXT
                parts.append(re.sub(r"[\x00-\x1f]", " ", raw[p:p + size].decode("utf-16le", errors="ignore")))
            p += size
        i += 1
    return "\n".join(parts)


def _hwpx_text(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    parts = []
    for name in sorted(n for n in z.namelist() if n.startswith("Contents/section") and n.endswith(".xml")):
        xml = z.read(name).decode("utf-8", errors="ignore")
        parts.append(re.sub(r"<[^>]+>", " ", xml))
    return "\n".join(parts)


def _pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:15])


def document_text(data, filename=""):
    """HWP/HWPX/PDF 바이트에서 본문 텍스트를 뽑는다. 실패하면 ""."""
    try:
        if data[:4] == b"\xd0\xcf\x11\xe0":
            return _hwp5_text(data)
        if data[:2] == b"PK":
            return _hwpx_text(data)
        if data[:4] == b"%PDF":
            return _pdf_text(data)
    except Exception as e:
        print(f"[공고문 읽기] {filename} 본문 추출 실패: {e}")
    return ""
