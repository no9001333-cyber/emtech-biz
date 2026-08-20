import json
import os
import hashlib
import calendar
from datetime import datetime

from config import (
    DOCS_DIR, DASHBOARD_HTML_PATH, BIDS_JSON_PATH, STATUS_JSON_PATH, KEYWORDS, REGIONS,
    EXTERNAL_MANUAL_LINKS, DASHBOARD_PASSWORD, AWARDS_JSON_PATH, AWARDS_HTML_PATH,
)


def _add_months(d, delta_months):
    """날짜에 달력 기준으로 정확히 n개월을 더한다(뺄 때는 음수).
    timedelta(days=30)을 쓰면 큰 달(31일)이 껴서 하루씩 밀리는 문제가 있어서
    (예: 2026-08-20 + "30일" = 09-19, 사용자가 기대한 09-20이 아님) 달력 월
    단위로 정확히 계산한다. 말일 근처(예: 1/31 + 1개월)는 해당 월의 마지막
    날로 자동 보정한다(예: 1/31 + 1개월 -> 2/28)."""
    month_index = d.month - 1 + delta_months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>emtech-biz | 이엠테크 입찰 모니터</title>
<style>
  :root {{
    --ink: #14213d;
    --paper: #fbfaf7;
    --line: #e4e1d8;
    --accent: #c8511b;
    --accent-soft: #f5e3d8;
    --muted: #6b6b63;
    --card: #ffffff;
    --good: #2a6f97;
    --good-soft: #e4eef4;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    background: var(--paper);
    color: var(--ink);
  }}
  header {{ padding: 28px 24px 16px; border-bottom: 1px solid var(--line); }}
  header h1 {{ margin: 0 0 6px; font-size: 1.4rem; letter-spacing: -0.02em; }}
  header p {{ margin: 0; color: var(--muted); font-size: 0.88rem; }}
  .meta {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:12px; font-size:0.8rem; color:var(--muted); }}
  .meta b {{ color: var(--ink); }}

  .controls {{
    display:flex; gap:10px; flex-wrap:wrap;
    padding:14px 24px; border-bottom:1px solid var(--line);
    position: sticky; top: 0; background: var(--paper); z-index: 5;
  }}
  .controls input, .controls select {{
    padding:8px 12px; border:1px solid var(--line); border-radius:6px;
    background:var(--card); font-size:0.85rem; color:var(--ink);
  }}
  .controls input {{ flex:1; min-width:160px; }}

  main {{ padding: 8px 24px 60px; }}
  .count {{ font-size:0.82rem; color:var(--muted); margin:14px 0; }}

  table {{ width:100%; border-collapse:collapse; font-size:0.84rem; }}
  thead th {{
    text-align:left; padding:9px 10px; border-bottom:2px solid var(--ink);
    color:var(--muted); font-weight:600; white-space:nowrap;
  }}
  .filter-row th {{ padding:4px 6px 8px; border-bottom:1px solid var(--line); }}
  .col-filter {{
    width:100%; box-sizing:border-box; padding:5px 6px; font-size:0.76rem;
    border:1px solid var(--line); border-radius:5px; background:var(--paper); color:var(--ink);
  }}
  .col-filter[type="number"] {{ width:60px; }}
  tbody tr {{ border-bottom:1px solid var(--line); vertical-align: top; }}
  tbody tr:hover {{ background: var(--accent-soft); }}
  td {{ padding:10px; }}
  td.title a {{ color:var(--ink); text-decoration:none; font-weight:500; }}
  td.title a:hover {{ color:var(--accent); text-decoration:underline; }}
  .region-check {{ display:block; margin-top:2px; font-size:0.72rem; cursor:help; }}
  .region-check.confirmed {{ color:var(--good); }}
  .region-check.ambiguous {{ color:#a67c00; }}
  .region-check.unverified {{ color:var(--muted); }}

  .tag {{ display:inline-block; font-size:0.72rem; padding:2px 8px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }}
  .tag.g2b {{ border-color:#2a6f97; color:#2a6f97; }}
  .tag.lh {{ border-color:#6a994e; color:#6a994e; }}
  .tag.d2b {{ border-color:var(--accent); color:var(--accent); }}

  .memo-input {{
    width: 140px; padding:6px 8px; font-size:0.8rem;
    border:1px solid var(--line); border-radius:5px; background:var(--paper); color:var(--ink);
  }}
  .btn-calc {{
    padding:6px 10px; font-size:0.78rem; font-weight:600;
    border:none; border-radius:6px; background:var(--ink); color:#fff; cursor:pointer; white-space:nowrap;
  }}
  .btn-calc:hover {{ background:#0c1730; }}

  .empty {{ padding:60px 0; text-align:center; color:var(--muted); }}
  .ext-links {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:14px; font-size:0.8rem; }}
  .status-pill {{
    font-size:0.72rem; padding:2px 8px; border-radius:999px; border:1px solid var(--line);
    cursor:default;
  }}
  .status-ok {{ border-color:var(--good); color:var(--good); }}
  .status-bad {{ border-color:var(--accent); color:var(--accent); background:var(--accent-soft); }}
  .ext-label {{ color:var(--muted); }}
  .ext-links a {{
    color:var(--good); text-decoration:none; padding:3px 10px;
    border:1px solid var(--line); border-radius:999px; font-size:0.78rem;
  }}
  .ext-links a:hover {{ background:var(--good-soft); }}
  footer {{ padding:20px 24px 40px; font-size:0.78rem; color:var(--muted); border-top:1px solid var(--line); }}

  /* 달력형 마감일 검색 */
  .cal-section {{ padding:14px 24px; border-bottom:1px solid var(--line); }}
  .cal-header {{ display:flex; align-items:center; gap:10px; margin-bottom:10px; flex-wrap:wrap; }}
  .cal-legend {{ margin-left:auto; font-size:0.76rem; color:var(--muted); display:flex; gap:12px; }}
  .cal-legend span {{ display:inline-flex; align-items:center; gap:4px; }}
  .cal-legend .dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
  .cal-legend .dot.reg {{ background:var(--good); }}
  .cal-legend .dot.ddl {{ background:var(--accent); }}
  .cal-strip {{ display:flex; gap:4px; overflow-x:auto; padding-bottom:6px; }}
  .cal-day {{
    min-width:66px; flex:0 0 auto; text-align:center; padding:8px 4px; border:1px solid var(--line);
    border-radius:8px; cursor:pointer; background:var(--card);
  }}
  .cal-day:hover {{ border-color:var(--accent); }}
  .cal-day.today {{ border-color:var(--good); border-width:2px; }}
  .cal-day.active {{ background:var(--accent-soft); border-color:var(--accent); border-width:2px; }}
  .cal-day.sun .cal-wd {{ color:#c0392b; }}
  .cal-day.sat .cal-wd {{ color:#2a6f97; }}
  .cal-date {{ font-weight:700; font-size:0.82rem; }}
  .cal-wd {{ font-size:0.7rem; color:var(--muted); margin:2px 0 6px; }}
  .cal-counts {{ display:flex; justify-content:center; gap:6px; font-size:0.72rem; min-height:14px; }}
  .cal-counts .cnt-reg {{ color:var(--good); font-weight:600; }}
  .cal-counts .cnt-ddl {{ color:var(--accent); font-weight:600; }}

  /* 모달 (투찰금액 계산기) */
  .modal-overlay {{
    display:none; position:fixed; inset:0; background:rgba(20,33,61,0.5);
    z-index:50; align-items:flex-start; justify-content:center; overflow-y:auto; padding:30px 14px;
  }}
  .modal-overlay.open {{ display:flex; }}
  .modal {{
    background:var(--card); border-radius:10px; max-width:520px; width:100%;
    padding:22px; position:relative;
  }}
  .modal h3 {{ margin:0 0 4px; font-size:1.05rem; }}
  .modal .sub {{ font-size:0.8rem; color:var(--muted); margin-bottom:16px; }}
  .modal-close {{
    position:absolute; top:14px; right:16px; border:none; background:none;
    font-size:1.2rem; cursor:pointer; color:var(--muted);
  }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
  .field {{ display:flex; flex-direction:column; gap:4px; margin-bottom:10px; }}
  .field label {{ font-size:0.76rem; color:var(--muted); }}
  .field input, .field select {{
    padding:8px 9px; border:1px solid var(--line); border-radius:6px; font-size:0.86rem; background:var(--paper); color:var(--ink);
  }}
  .src-badge {{ display:inline-block; font-size:0.66rem; padding:1px 6px; border-radius:10px; margin-left:6px; font-weight:600; }}
  .src-badge.ok {{ background:var(--good-soft); color:var(--good); }}
  .src-badge.warn {{ background:var(--accent-soft); color:var(--accent); }}
  .info-line {{ font-size:0.8rem; color:var(--muted); margin-bottom:12px; padding:8px 10px; background:var(--paper); border:1px solid var(--line); border-radius:6px; }}
  .info-line b {{ color:var(--ink); }}
  .calc-warn-box {{ background:var(--accent-soft); border:1px solid var(--accent); color:var(--accent); border-radius:8px; padding:9px 11px; font-size:0.78rem; margin-bottom:10px; display:none; white-space:pre-line; }}
  .btn-row {{ display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }}
  .btn {{ padding:9px 16px; border-radius:7px; border:none; font-size:0.84rem; font-weight:600; cursor:pointer; }}
  .btn-primary {{ background:var(--accent); color:#fff; }}
  .btn-secondary {{ background:var(--ink); color:#fff; }}
  .btn:disabled {{ background:var(--line); color:var(--muted); cursor:not-allowed; }}

  .mini-table {{ width:100%; border-collapse:collapse; font-size:0.78rem; margin-top:8px; }}
  .mini-table th, .mini-table td {{ padding:5px 6px; text-align:right; border-bottom:1px solid var(--line); }}
  .mini-table th:first-child, .mini-table td:first-child {{ text-align:center; }}
  .mini-table tr.picked {{ background:var(--accent-soft); font-weight:600; }}

  .result-grid {{ display:grid; grid-template-columns:1fr auto; gap:5px 10px; font-size:0.84rem; margin-top:10px; }}
  .result-grid .k {{ color:var(--muted); }}
  .result-grid .v {{ font-weight:600; text-align:right; }}
  .final-box {{ margin-top:12px; padding:14px; border-radius:8px; background:var(--good-soft); border:1px solid var(--good); text-align:center; }}
  .final-box .label {{ font-size:0.78rem; color:var(--good); margin-bottom:3px; }}
  .final-box .amount {{ font-size:1.3rem; font-weight:700; }}

  @media (max-width: 720px) {{
    table, thead, tbody, tr, td {{ display:block; }}
    thead {{ display:none; }}
    tbody tr {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin-bottom:12px; padding:8px 4px; }}
    td {{ padding:6px 12px; }}
    td::before {{ content: attr(data-label); display:block; font-size:0.7rem; color:var(--muted); margin-bottom:2px; }}
    .grid2 {{ grid-template-columns:1fr; }}
  }}
  .lock-screen {{
    position:fixed; inset:0; background:var(--paper); z-index:200;
    display:flex; align-items:center; justify-content:center; flex-direction:column; gap:16px;
  }}
  .lock-box {{
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:32px 28px; width:280px; text-align:center;
  }}
  .lock-box h2 {{ font-size:1.05rem; margin:0 0 16px; }}
  .lock-box input {{
    width:100%; box-sizing:border-box; padding:10px 12px; margin-bottom:10px;
    border:1px solid var(--line); border-radius:6px; font-size:0.9rem; text-align:center;
  }}
  .lock-box button {{
    width:100%; padding:10px; border:none; border-radius:6px;
    background:var(--accent); color:#fff; font-weight:600; cursor:pointer;
  }}
  .lock-error {{ color:var(--accent); font-size:0.8rem; margin-top:8px; display:none; }}
</style>
</head>
<body>

<div class="lock-screen" id="lockScreen">
  <div class="lock-box">
    <h2>비밀번호를 입력하세요</h2>
    <input id="lockInput" type="password" placeholder="비밀번호" autofocus>
    <button onclick="checkPassword()">입장</button>
    <div class="lock-error" id="lockError">비밀번호가 틀렸습니다.</div>
  </div>
</div>

<div id="mainContent" style="display:none;">
<header>
  <h1>emtech-biz — 이엠테크 입찰 모니터</h1>
  <p>나라장터 · LH · 국방전자조달(D2B) · 한국수자원공사 · 한국전력공사 전업종 공고 자동 수집 + 메모 + 투찰금액 계산</p>
  <div class="meta">
    <span>마지막 업데이트: <b>{updated_at}</b></span>
    <span>업종: <b>전체 (직접 필터링)</b></span>
    <span>지역: <b>전체 수집 후 직접 필터링</b></span>
    <span>총 <b>{count}</b>건</span>
  </div>
  <div class="ext-links">
    <span class="ext-label">자동수집 안 되는 곳(직접 확인):</span>
    {external_links_html}
  </div>
  <div class="ext-links">
    <span class="ext-label">낙찰 결과(과거 공고)는 별도 페이지:</span>
    <a href="awards.html">낙찰결과 보기 →</a>
  </div>
  <div class="ext-links">
    <span class="ext-label">수집 상태:</span>
    {status_html}
  </div>
</header>

<div class="cal-section">
  <div class="cal-header">
    <button class="btn-calc" onclick="calShift(-7)">◀ 7일</button>
    <span id="calRangeLabel" style="font-weight:600; font-size:0.84rem;"></span>
    <button class="btn-calc" onclick="calShift(7)">7일 ▶</button>
    <button class="btn-calc" onclick="calToday()">오늘</button>
    <div class="cal-legend">
      <span><span class="dot reg"></span>참가등록마감</span>
      <span><span class="dot ddl"></span>투찰마감</span>
      <span>날짜를 클릭하면 해당 날짜로 필터링됩니다</span>
    </div>
  </div>
  <div class="cal-strip" id="calStrip"></div>
</div>

<div id="bidsView">
<div class="controls">
  <label style="display:flex; align-items:center; gap:6px; font-size:0.85rem; white-space:nowrap; cursor:pointer;">
    <input id="eligibleOnly" type="checkbox" checked style="width:16px; height:16px;">
    용인 참가가능만 보기
  </label>
  <label style="display:flex; align-items:center; gap:6px; font-size:0.85rem; white-space:nowrap; cursor:pointer;">
    <input id="telecomOnly" type="checkbox" checked style="width:16px; height:16px;">
    통신 업종만 보기
  </label>
  <select id="searchField" style="max-width:130px; flex:none;">
    <option value="all">전체검색</option>
    <option value="title">공고명</option>
    <option value="notice_no">공고번호</option>
    <option value="org">발주기관</option>
  </select>
  <input id="search" type="text" placeholder="검색어 입력...">
  <select id="sourceFilter">
    <option value="">전체 출처</option>
    <option value="나라장터">나라장터</option>
    <option value="LH">LH</option>
    <option value="국방전자조달(D2B)">국방전자조달(D2B)</option>
    <option value="한국수자원공사">한국수자원공사</option>
    <option value="한국전력공사">한국전력공사</option>
  </select>
  <select id="regionFilter">
    <option value="">전체 지역</option>
    <option value="용인">용인</option>
    <option value="경기">경기</option>
    <option value="서울">서울</option>
    <option value="인천">인천</option>
    <option value="부산">부산</option>
    <option value="대구">대구</option>
    <option value="광주">광주</option>
    <option value="대전">대전</option>
    <option value="울산">울산</option>
    <option value="세종">세종</option>
    <option value="강원">강원</option>
    <option value="충북">충북</option>
    <option value="충남">충남</option>
    <option value="전북">전북</option>
    <option value="전남">전남</option>
    <option value="경북">경북</option>
    <option value="경남">경남</option>
    <option value="제주">제주</option>
    <option value="전국">전국</option>
    <option value="__EMPTY__">지역 미표기</option>
  </select>
</div>

<div class="controls" style="border-top:none;">
  <select id="dateBasis" style="flex:none;">
    <option value="deadline">투찰마감 기준</option>
    <option value="reg_deadline">참가등록마감 기준</option>
  </select>
  <input id="dateStart" type="date" value="{date_start_default}">
  <span style="align-self:center; color:var(--muted);">~</span>
  <input id="dateEnd" type="date" value="{date_end_default}">
  <button class="btn-calc" onclick="applyDateSearch()">검색</button>
  <button class="btn-calc" onclick="clearDateRange()">전체</button>
</div>

<main>
  <div class="count" id="count"></div>
  <table>
    <thead>
      <tr>
        <th>출처</th><th>상태</th><th>공고명</th><th>발주기관</th><th>업종</th><th>지역</th><th>입찰방식</th><th>제한사항</th>
        <th>금액정보(추정/기초/A값)</th><th>투찰마감</th><th>참가등록마감</th><th>메모</th><th></th>
      </tr>
      <tr class="filter-row">
        <th><select id="colFilterSource" class="col-filter"><option value="">전체</option>
          <option value="나라장터">나라장터</option><option value="LH">LH</option>
          <option value="국방전자조달(D2B)">D2B</option><option value="한국수자원공사">수자원공사</option>
          <option value="한국전력공사">한전</option>
        </select></th>
        <th><select id="colFilterStatus" class="col-filter"><option value="">전체</option>
          <option value="진행중">진행중</option><option value="마감">마감/개찰</option>
        </select></th>
        <th><input id="colFilterTitle" class="col-filter" type="text" placeholder="검색"></th>
        <th><input id="colFilterOrg" class="col-filter" type="text" placeholder="검색"></th>
        <th><input id="colFilterIndustry" class="col-filter" type="text" placeholder="검색"></th>
        <th><input id="colFilterRegion" class="col-filter" type="text" placeholder="검색"></th>
        <th><input id="colFilterBidMethod" class="col-filter" type="text" placeholder="검색"></th>
        <th><input id="colFilterRestrictions" class="col-filter" type="text" placeholder="검색"></th>
        <th>
          <div style="display:flex; gap:2px;">
            <input id="colFilterAmountMin" class="col-filter" type="number" placeholder="최소">
            <input id="colFilterAmountMax" class="col-filter" type="number" placeholder="최대">
          </div>
        </th>
        <th></th>
        <th></th>
        <th><input id="colFilterMemo" class="col-filter" type="text" placeholder="검색"></th>
        <th><button class="btn-calc" onclick="clearColFilters()">초기화</button></th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="empty" id="emptyMsg" style="display:none;">조건에 맞는 공고가 없습니다.</div>
</main>
</div>

<footer>
  이 페이지는 매일 자동 실행되는 스크립트가 생성합니다. 메모는 이 브라우저에만 저장됩니다(다른 기기와 공유되지 않음).
  투찰 전에는 반드시 원본 사이트에서 공고 내용을 다시 확인하세요.
</footer>

<!-- 투찰금액 계산 모달 -->
<div class="modal-overlay" id="calcModal">
  <div class="modal">
    <button class="modal-close" onclick="closeCalc()">✕</button>
    <h3 id="calcTitle">투찰금액 계산</h3>
    <div class="sub" id="calcOrg"></div>

    <div class="info-line" id="calcEstLine">추정금액(공고 API 값): <b id="calcEstDisplay">-</b></div>

    <div class="grid2">
      <div class="field">
        <label>기초금액 (원) <span class="src-badge" id="badgeBase"></span></label>
        <input id="calcBase" type="number">
      </div>
      <div class="field">
        <label>A값 (원) <span class="src-badge" id="badgeAValue"></span></label>
        <input id="calcAValue" type="number" placeholder="법정 정산항목 합계">
      </div>
      <div class="field">
        <label>예가변동폭 (%) <span class="src-badge warn">공고문 직접확인</span></label>
        <select id="calcVariance">
          <option value="2">-2 / +2</option>
          <option value="3">-3 / +3</option>
        </select>
      </div>
      <div class="field">
        <label>낙찰하한율 <span class="src-badge" id="badgeRate"></span></label>
        <select id="calcRateSel">
          <option value="0.89745">10억 미만 (89.745%)</option>
          <option value="0.88745">10억~50억 (88.745%)</option>
          <option value="0.87495">50억~100억 (87.495%)</option>
          <option value="custom">직접입력</option>
        </select>
      </div>
      <div class="field">
        <label>복수예가 생성개수 <span class="src-badge" id="badgeTotalCount"></span></label>
        <input id="calcTotalCount" type="number" min="2" max="50" value="15">
      </div>
      <div class="field">
        <label>추첨개수 <span class="src-badge" id="badgeDrawCount"></span></label>
        <input id="calcDrawCount" type="number" min="1" max="50" value="4">
      </div>
    </div>
    <div class="field" id="calcCustomRateField" style="display:none;">
      <label>낙찰하한율 직접 입력 (%)</label>
      <input id="calcCustomRate" type="number" step="0.001">
    </div>

    <div class="calc-warn-box" id="calcWarnBox"></div>

    <div class="btn-row">
      <button class="btn btn-primary" id="calcGenBtn" onclick="calcGenerate()">🎲 복수예가 15개 생성</button>
      <button class="btn btn-secondary" id="calcDrawBtn" onclick="calcDraw()" disabled>🎯 4개 추첨</button>
    </div>

    <table class="mini-table" id="calcTable" style="display:none;">
      <thead><tr><th>번호</th><th>변동률</th><th>예가</th></tr></thead>
      <tbody id="calcTbody"></tbody>
    </table>

    <div id="calcResultBox" style="display:none;">
      <div class="result-grid">
        <div class="k">4개 평균 (사정예정가격)</div><div class="v" id="c_assessed">-</div>
        <div class="k">A값 제외 대상금액</div><div class="v" id="c_excl">-</div>
        <div class="k">하한율 적용 금액</div><div class="v" id="c_applied">-</div>
        <div class="k">A값 재합산 금액</div><div class="v" id="c_readded">-</div>
      </div>
      <div class="final-box">
        <div class="label">🎯 최종 투찰금액 (원 단위 절사)</div>
        <div class="amount" id="c_final">-</div>
      </div>
    </div>
  </div>
</div>
</div>

<script>
const BIDS = {bids_json};
const TELECOM_KEYWORDS = {keywords_json};
const MEMO_KEY = 'bidmonitor_memos';

/* ---------- 비밀번호 잠금화면 ---------- */
const PASSWORD_HASH = "{password_hash}";
const LOCK_KEY = 'bidmonitor_unlocked';

async function sha256Hex(text) {{
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}}

async function checkPassword() {{
  const input = document.getElementById('lockInput').value;
  const hash = await sha256Hex(input);
  if (hash === PASSWORD_HASH) {{
    localStorage.setItem(LOCK_KEY, PASSWORD_HASH);
    unlock();
  }} else {{
    document.getElementById('lockError').style.display = 'block';
  }}
}}

function unlock() {{
  document.getElementById('lockScreen').style.display = 'none';
  document.getElementById('mainContent').style.display = 'block';
}}

document.getElementById('lockInput')?.addEventListener('keydown', (e) => {{
  if (e.key === 'Enter') checkPassword();
}});

if (!PASSWORD_HASH) {{
  unlock();
}} else if (localStorage.getItem(LOCK_KEY) === PASSWORD_HASH) {{
  unlock();
}}

const tagClass = {{ "나라장터": "g2b", "LH": "lh", "국방전자조달(D2B)": "d2b", "한국수자원공사": "g2b", "한국전력공사": "g2b" }};

function loadMemos() {{
  try {{ return JSON.parse(localStorage.getItem(MEMO_KEY) || '{{}}'); }} catch (e) {{ return {{}}; }}
}}
function saveMemo(key, value) {{
  const memos = loadMemos();
  memos[key] = value;
  localStorage.setItem(MEMO_KEY, JSON.stringify(memos));
}}

function memoKey(b) {{ return (b.source || '') + '::' + (b.notice_no || b.title || ''); }}

function parseDateStr(s) {{
  if (!s) return null;
  const m = String(s).match(/(\\d{{4}})-?(\\d{{2}})-?(\\d{{2}})/);
  if (!m) return null;
  return new Date(`${{m[1]}}-${{m[2]}}-${{m[3]}}`);
}}

function fmtYMD(d) {{
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}}

// 투찰마감/참가등록마감 표시용 날짜·시간 통일 포맷터.
// 소스(나라장터/LH/D2B/수자원공사 등)마다 원본 형식이 제각각이라(예: "202608201000"처럼
// 구분자 없는 숫자, "2026-08-20 12:00:00"처럼 초까지 있는 문자열 등) 화면에 섞여 나오면
// 날짜/시간이 한눈에 구분되지 않는 문제가 있었습니다. 숫자만 뽑아서 항상
// "YYYY-MM-DD HH:MM" 형태로 통일해서 보여줍니다 (시간 정보가 없으면 날짜만 표시).
function fmtDateTime(s) {{
  if (!s) return '-';
  const digits = String(s).replace(/\\D/g, '');
  if (digits.length === 0) return '-';
  if (digits.length >= 12) {{
    const y = digits.slice(0, 4), mo = digits.slice(4, 6), da = digits.slice(6, 8);
    const hh = digits.slice(8, 10), mi = digits.slice(10, 12);
    return `${{y}}-${{mo}}-${{da}} ${{hh}}:${{mi}}`;
  }}
  if (digits.length >= 8) {{
    const y = digits.slice(0, 4), mo = digits.slice(4, 6), da = digits.slice(6, 8);
    return `${{y}}-${{mo}}-${{da}}`;
  }}
  return String(s); // 알 수 없는 형식이면 원본 그대로 표시 (데이터 유실 방지)
}}

function ddayLabel(deadlineText, status) {{
  const d = parseDateStr(deadlineText);
  if (!d) return '';
  const today = new Date(); today.setHours(0,0,0,0);
  const diff = Math.round((d - today) / 86400000);
  if (status === '마감' || diff < 0) return '';
  if (diff === 0) return 'D-day';
  return 'D-' + diff;
}}

// 공고명을 클릭하면(수정키 없는 일반 좌클릭) 같은 창 안의 새 탭이 아니라
// 완전히 분리된 새 브라우저 창으로 열리게 한다 - window.open에 크기(width/height)
// 옵션을 주면 브라우저가 이를 탭이 아닌 별도 창(팝업)으로 취급한다.
// Ctrl/Cmd/Shift/휠클릭(새 탭으로 열기 등 사용자가 의도한 동작)은 그대로 두고
// 브라우저 기본 동작을 살려둔다.
function openBidWindow(e, url) {{
  if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return true;
  e.preventDefault();
  window.open(url, '_blank', 'noopener,noreferrer,width=1100,height=900');
  return false;
}}

// 나라장터 공고서(PDF) 원문으로 재확인한 지역 참가자격 결과를 지역 컬럼에 작게 표시.
// title 속성(브라우저 기본 툴팁)에 실제 공고서 발췌문을 그대로 넣어서,
// 마우스를 올리면 원문 한 줄을 바로 확인할 수 있게 한다.
function regionCheckHtml(regionCheck) {{
  if (!regionCheck) return '';
  const esc = (s) => (s || '').replace(/"/g, '&quot;');
  if (!regionCheck.verified) {{
    return `<span class="region-check unverified" title="${{esc(regionCheck.note)}}">⚠ 공고서 미검증</span>`;
  }}
  if (regionCheck.eligible_confirmed === null || regionCheck.eligible_confirmed === undefined) {{
    return `<span class="region-check ambiguous" title="${{esc(regionCheck.note + ': ' + (regionCheck.snippet || ''))}}">❔ 공고서 확인필요</span>`;
  }}
  return `<span class="region-check confirmed" title="${{esc(regionCheck.note + ': ' + (regionCheck.snippet || ''))}}">✓ 공고서로 확인됨</span>`;
}}

function restrictionsHtml(restrictions) {{
  const text = (restrictions || '').trim();
  if (!text) return '-';
  return text.split(',').map(t => t.trim()).filter(Boolean)
    .map(t => `<span class="tag" style="border-color:var(--accent); color:var(--accent); margin:1px 2px 1px 0;">${{t}}</span>`)
    .join('');
}}

// "검색" 버튼: 사용자가 직접 입력/선택한 시작일~종료일 그대로 적용해서 필터링.
// (예전에는 1개월/3개월/6개월 버튼이 "오늘 - N일 ~ 오늘"처럼 과거 방향으로만 동작해서,
//  마감일이 미래인 공고를 찾을 때는 오히려 안 맞았습니다. 이제는 입력한 날짜를 그대로 검색합니다.)
function applyDateSearch() {{
  render();
  buildCalendar();
}}

// "전체" 버튼: 날짜 범위를 비워서 날짜 필터를 끔.
function clearDateRange() {{
  document.getElementById('dateStart').value = '';
  document.getElementById('dateEnd').value = '';
  render();
  buildCalendar();
}}

function parseAmount(v) {{
  if (!v) return null;
  const n = parseInt(String(v).replace(/[^0-9]/g, ''), 10);
  return isNaN(n) ? null : n;
}}

// 표에 추정금액/기초금액/A값을 한 셀에 요약 표시. 개찰 전이라 아직 기초금액이
// 공개되지 않은 공고는 추정금액(예산금액)을 잠정치로 대신 보여주므로 둘이 같은
// 값일 수 있습니다 - 실제로 기초금액이 공개된 공고는
// scrapers/g2b_basis_amount.py가 진짜 기초금액/A값(국민연금·건강보험·
// 퇴직공제부금·안전관리비 등 법정경비 합계)으로 덮어씁니다. A값은 0원도
// 정상적인 실제 값이라 null(데이터 없음)과 구분해서 표시합니다.
function amountInfoHtml(b) {{
  const est = parseAmount(b.est_amount);
  const base = parseAmount(b.base_amount);
  const a = parseAmount(b.a_value);
  if (est === null && base === null) return '-';
  const lines = [];
  lines.push(`추정: ${{est !== null ? Number(est).toLocaleString('ko-KR') + '원' : '-'}}`);
  lines.push(`기초: ${{base !== null ? Number(base).toLocaleString('ko-KR') + '원' : '-'}} <span style="color:var(--muted); font-size:0.7rem;">(참고용)</span>`);
  lines.push(`A값: ${{a !== null ? Number(a).toLocaleString('ko-KR') + '원' : '<span style="color:var(--muted);">확인필요</span>'}}`);
  return lines.join('<br>');
}}

function fieldMatches(b, q, field) {{
  if (!q) return true;
  if (field === 'title') return (b.title || '').toLowerCase().includes(q);
  if (field === 'notice_no') return (b.notice_no || '').toLowerCase().includes(q);
  if (field === 'org') return (b.org || '').toLowerCase().includes(q);
  return (b.title || '').toLowerCase().includes(q) || (b.org || '').toLowerCase().includes(q) ||
         (b.industry || '').toLowerCase().includes(q) || (b.notice_no || '').toLowerCase().includes(q);
}}

function render() {{
  const eligibleOnly = document.getElementById('eligibleOnly').checked;
  const telecomOnly = document.getElementById('telecomOnly').checked;
  const q = document.getElementById('search').value.trim().toLowerCase();
  const searchField = document.getElementById('searchField').value;
  const src = document.getElementById('sourceFilter').value;
  const region = document.getElementById('regionFilter').value;
  const dateBasis = document.getElementById('dateBasis').value;
  const startVal = document.getElementById('dateStart').value;
  const endVal = document.getElementById('dateEnd').value;
  const startDate = startVal ? new Date(startVal) : null;
  const endDate = endVal ? new Date(endVal) : null;

  const colSrc = document.getElementById('colFilterSource').value;
  const colTitle = document.getElementById('colFilterTitle').value.trim().toLowerCase();
  const colOrg = document.getElementById('colFilterOrg').value.trim().toLowerCase();
  const colIndustry = document.getElementById('colFilterIndustry').value.trim().toLowerCase();
  const colRegion = document.getElementById('colFilterRegion').value.trim().toLowerCase();
  const colBidMethod = document.getElementById('colFilterBidMethod').value.trim().toLowerCase();
  const colRestrictions = document.getElementById('colFilterRestrictions').value.trim().toLowerCase();
  const colAmountMin = parseFloat(document.getElementById('colFilterAmountMin').value);
  const colAmountMax = parseFloat(document.getElementById('colFilterAmountMax').value);
  const colMemo = document.getElementById('colFilterMemo').value.trim().toLowerCase();
  const colStatus = document.getElementById('colFilterStatus').value;

  const memos = loadMemos();
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';

  const filtered = BIDS.filter(b => {{
    const matchEligible = !eligibleOnly || b.eligible !== false;
    const matchTelecom = !telecomOnly || TELECOM_KEYWORDS.some(k =>
      (b.title || '').includes(k) || (b.industry || '').includes(k));
    const matchQ = fieldMatches(b, q, searchField);
    const matchSrc = !src || b.source === src;
    let matchRegion;
    if (!region) {{
      matchRegion = true;
    }} else if (region === '__EMPTY__') {{
      matchRegion = !(b.region || '').trim();
    }} else {{
      matchRegion = (b.region || '').includes(region);
    }}
    let matchDate = true;
    if (startDate || endDate) {{
      const basisText = dateBasis === 'reg_deadline' ? b.reg_deadline : b.deadline;
      const d = parseDateStr(basisText) || parseDateStr(b.notice_date);
      if (!d) {{
        matchDate = false;
      }} else {{
        if (startDate && d < startDate) matchDate = false;
        if (endDate && d > endDate) matchDate = false;
      }}
    }}

    // 컬럼별 필터
    const matchColSrc = !colSrc || b.source === colSrc;
    const matchColTitle = !colTitle || (b.title || '').toLowerCase().includes(colTitle);
    const matchColOrg = !colOrg || (b.org || '').toLowerCase().includes(colOrg);
    const matchColIndustry = !colIndustry || (b.industry || '').toLowerCase().includes(colIndustry);
    const matchColRegion = !colRegion || (b.region || '').toLowerCase().includes(colRegion);
    const matchColBidMethod = !colBidMethod || (b.bid_method || '').toLowerCase().includes(colBidMethod);
    const matchColRestrictions = !colRestrictions || (b.restrictions || '').toLowerCase().includes(colRestrictions);
    const amount = parseAmount(b.base_amount);
    const matchColAmountMin = isNaN(colAmountMin) || (amount !== null && amount >= colAmountMin);
    const matchColAmountMax = isNaN(colAmountMax) || (amount !== null && amount <= colAmountMax);
    const memoVal = (memos[memoKey(b)] || '').toLowerCase();
    const matchColMemo = !colMemo || memoVal.includes(colMemo);
    const matchColStatus = !colStatus || b.status === colStatus;

    return matchEligible && matchTelecom && matchQ && matchSrc && matchRegion && matchDate &&
           matchColSrc && matchColTitle && matchColOrg && matchColIndustry &&
           matchColRegion && matchColBidMethod && matchColRestrictions && matchColAmountMin && matchColAmountMax && matchColMemo && matchColStatus;
  }});

  document.getElementById('count').textContent = filtered.length + '건 표시 중';
  document.getElementById('emptyMsg').style.display = filtered.length ? 'none' : 'block';

  filtered.forEach((b, idx) => {{
    const cls = tagClass[b.source] || '';
    const key = memoKey(b);
    const memoVal = memos[key] || '';
    const statusBadge = b.status === '마감'
      ? `<span class="tag" style="border-color:var(--muted); color:var(--muted);">마감</span>`
      : `<span class="tag" style="border-color:var(--good); color:var(--good);">진행중</span>`;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td data-label="출처"><span class="tag ${{cls}}">${{b.source || ''}}</span></td>
      <td data-label="상태">${{statusBadge}}</td>
      <td data-label="공고명" class="title">${{b.url ? `<a href="${{b.url}}" target="_blank" rel="noopener" onclick="return openBidWindow(event, this.href)">${{b.title || ''}}</a>` : (b.title || '')}}</td>
      <td data-label="발주기관">${{b.org || ''}}</td>
      <td data-label="업종">${{b.industry || '-'}}</td>
      <td data-label="지역">${{b.region || ''}}${{b.eligible === false ? ' <span style="color:var(--accent); font-size:0.72rem;">(참가불가)</span>' : ''}}${{regionCheckHtml(b.region_check)}}</td>
      <td data-label="입찰방식">${{b.bid_method || '-'}}</td>
      <td data-label="제한사항">${{restrictionsHtml(b.restrictions)}}</td>
      <td data-label="금액정보">${{amountInfoHtml(b)}}</td>
      <td data-label="투찰마감">${{fmtDateTime(b.deadline)}}${{ddayLabel(b.deadline, b.status) ? ` <span class="tag" style="border-color:var(--accent); color:var(--accent);">${{ddayLabel(b.deadline, b.status)}}</span>` : ''}}</td>
      <td data-label="참가등록마감">${{fmtDateTime(b.reg_deadline)}}</td>
      <td data-label="메모"><input class="memo-input" type="text" placeholder="메모 입력..." value="${{memoVal.replace(/"/g,'&quot;')}}" data-key="${{key}}"></td>
      <td><button class="btn-calc" data-idx="${{idx}}">투찰금액 계산</button></td>
    `;
    tr.querySelector('.memo-input').addEventListener('change', (e) => {{
      saveMemo(e.target.dataset.key, e.target.value);
    }});
    tr.querySelector('.btn-calc').addEventListener('click', () => openCalc(b));
    tbody.appendChild(tr);
  }});
}}

function clearColFilters() {{
  ['colFilterSource','colFilterStatus','colFilterTitle','colFilterOrg','colFilterIndustry',
   'colFilterRegion','colFilterBidMethod','colFilterRestrictions','colFilterAmountMin','colFilterAmountMax','colFilterMemo'
  ].forEach(id => {{ document.getElementById(id).value = ''; }});
  render();
}}

document.getElementById('eligibleOnly').addEventListener('change', render);
document.getElementById('telecomOnly').addEventListener('change', render);
document.getElementById('search').addEventListener('input', render);
document.getElementById('searchField').addEventListener('change', render);
document.getElementById('sourceFilter').addEventListener('change', render);
document.getElementById('regionFilter').addEventListener('change', render);
document.getElementById('dateBasis').addEventListener('change', () => {{ buildCalendar(); render(); }});
document.getElementById('dateStart').addEventListener('change', () => {{ buildCalendar(); render(); }});
document.getElementById('dateEnd').addEventListener('change', () => {{ buildCalendar(); render(); }});
['colFilterSource','colFilterStatus','colFilterTitle','colFilterOrg','colFilterIndustry',
 'colFilterRegion','colFilterBidMethod','colFilterRestrictions','colFilterAmountMin','colFilterAmountMax','colFilterMemo'
].forEach(id => {{
  const evt = document.getElementById(id).tagName === 'SELECT' ? 'change' : 'input';
  document.getElementById(id).addEventListener(evt, render);
}});
render();

/* ---------- 달력형 마감일 검색 ---------- */
let calAnchor = new Date();
calAnchor.setHours(0, 0, 0, 0);
// 기본 검색범위(오늘~1개월 후)를 한 화면에서 다 볼 수 있도록 31일치를 한 번에
// 보여준다(예전엔 16일씩만 보여서 나머지를 보려면 "7일 ▶"을 여러 번 눌러야 했음).
const CAL_DAYS = 31;

function calShift(days) {{
  calAnchor.setDate(calAnchor.getDate() + days);
  buildCalendar();
}}

function calToday() {{
  calAnchor = new Date();
  calAnchor.setHours(0, 0, 0, 0);
  buildCalendar();
}}

function buildCalendar() {{
  const strip = document.getElementById('calStrip');
  strip.innerHTML = '';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const weekdays = ['일', '월', '화', '수', '목', '금', '토'];

  const regCounts = {{}};
  const ddlCounts = {{}};
  BIDS.forEach(b => {{
    const rd = parseDateStr(b.reg_deadline);
    if (rd) {{ const k = fmtYMD(rd); regCounts[k] = (regCounts[k] || 0) + 1; }}
    const dd = parseDateStr(b.deadline);
    if (dd) {{ const k = fmtYMD(dd); ddlCounts[k] = (ddlCounts[k] || 0) + 1; }}
  }});

  const startVal = document.getElementById('dateStart').value;
  const endVal = document.getElementById('dateEnd').value;

  let labelStart = null, labelEnd = null;
  for (let i = 0; i < CAL_DAYS; i++) {{
    const d = new Date(calAnchor);
    d.setDate(d.getDate() + i);
    const key = fmtYMD(d);
    if (i === 0) labelStart = key;
    if (i === CAL_DAYS - 1) labelEnd = key;
    const wd = d.getDay();
    const isToday = key === fmtYMD(today);
    const isActive = startVal === key && endVal === key;
    const col = document.createElement('div');
    col.className = 'cal-day' + (wd === 0 ? ' sun' : wd === 6 ? ' sat' : '') + (isToday ? ' today' : '') + (isActive ? ' active' : '');
    col.innerHTML = `
      <div class="cal-date">${{d.getMonth() + 1}}/${{d.getDate()}}</div>
      <div class="cal-wd">${{weekdays[wd]}}${{isToday ? ' (오늘)' : ''}}</div>
      <div class="cal-counts">
        <span class="cnt-reg">${{regCounts[key] || ''}}</span>
        <span class="cnt-ddl">${{ddlCounts[key] || ''}}</span>
      </div>
    `;
    col.addEventListener('click', () => {{
      document.getElementById('dateStart').value = key;
      document.getElementById('dateEnd').value = key;
      buildCalendar();
      render();
    }});
    strip.appendChild(col);
  }}
  document.getElementById('calRangeLabel').textContent = labelStart + ' ~ ' + labelEnd;
}}

buildCalendar();

/* ---------- 투찰금액 계산 모달 ----------
   2026-08-18 개선: 추정금액/기초금액/A값/낙찰하한율/복수예가 생성·추첨 개수를
   가능하면 실제 공고 데이터(g2b.py가 수집한 API 값)로 자동 채우고, 각 값 옆에
   "공고 데이터(자동)" 또는 "확인필요(수동입력)" 배지로 출처를 명확히 표시합니다.
   실제 데이터가 없거나 값이 비정상적인 범위(예: 낙찰하한율이 30~100%를 벗어남,
   추첨개수가 생성개수보다 많음)면 자동으로 채우지 않고 수동 입력을 안내하며,
   버튼을 눌러도 검증에 실패하면 결과를 계산/표시하지 않습니다(잘못된 값으로
   그럴듯한 최종 투찰금액을 만들어내지 않기 위함). */
let calcBids = [];
let calcPicked = [];

document.getElementById('calcRateSel').addEventListener('change', (e) => {{
  document.getElementById('calcCustomRateField').style.display = e.target.value === 'custom' ? 'flex' : 'none';
}});

function setBadge(id, ok, okText, warnText) {{
  const el = document.getElementById(id);
  el.textContent = ok ? (okText || '공고 데이터(자동)') : (warnText || '확인필요(수동)');
  el.className = 'src-badge ' + (ok ? 'ok' : 'warn');
}}

// 추정가격 규모에 따른 낙찰하한율 구간 자동 선택 (기존 3단계 드롭다운 기준).
// 100억 이상이거나 금액을 알 수 없으면 구간을 확정할 수 없어 null 반환(수동확인 필요).
function pickRateTierByAmount(amount) {{
  if (amount === null || amount === undefined || amount <= 0) return null;
  if (amount < 1e9) return '0.89745';
  if (amount < 5e9) return '0.88745';
  if (amount < 1e10) return '0.87495';
  return null;
}}

function openCalc(bid) {{
  document.getElementById('calcTitle').textContent = bid.title || '투찰금액 계산';
  document.getElementById('calcOrg').textContent = (bid.org || '') + (bid.region ? ' · ' + bid.region : '');

  const est = parseAmount(bid.est_amount);
  const base = parseAmount(bid.base_amount);
  const aValue = parseAmount(bid.a_value);
  const rateRaw = parseFloat(bid.successful_bid_lower_rate);
  const totalRaw = parseInt(bid.reserve_price_total_count, 10);
  const drawRaw = parseInt(bid.reserve_price_draw_count, 10);

  document.getElementById('calcEstDisplay').textContent = est !== null ? Number(est).toLocaleString('ko-KR') + '원' : '데이터 없음 - 공고문에서 직접 확인 필요';

  // 기초금액: 예산금액(bdgtAmt) 기준 실제 값을 채웁니다. 공고 상세페이지의 "기초금액공개"
  // 값과 일치하는 것을 확인했지만, 발주기관이 별도로 산정한 진짜 기초금액과 다를 가능성이
  // 완전히 배제되지는 않아 warn 배지로 공고문 대조를 안내합니다.
  const baseVal = base !== null ? base : est;
  document.getElementById('calcBase').value = baseVal || '';
  setBadge('badgeBase', false, '', baseVal ? '예산금액 기준(공고 데이터) - 공고문 대조 권장' : '데이터 없음-직접입력');

  // A값(법정 정산항목 합계): 0원도 정상적인 실제 값일 수 있으므로, null(데이터 없음)과
  // 구분해서 처리합니다 - 0을 확인필요로 잘못 표시하지 않도록 주의.
  if (aValue !== null) {{
    document.getElementById('calcAValue').value = aValue;
    setBadge('badgeAValue', true, aValue > 0 ? '공고 데이터(실제값)' : '공고 데이터(실제값·0원)');
  }} else {{
    document.getElementById('calcAValue').value = '';
    setBadge('badgeAValue', false, '', '데이터 없음-직접입력');
  }}

  // 낙찰하한율: 공고에 실제 값이 있고 30~100% 범위면 그대로 사용, 아니면 금액 구간으로
  // 추정하되(그것도 안되면) 수동 입력을 안내.
  const customField = document.getElementById('calcCustomRateField');
  if (!isNaN(rateRaw) && rateRaw > 0.3 && rateRaw <= 1) {{
    document.getElementById('calcRateSel').value = 'custom';
    document.getElementById('calcCustomRate').value = (rateRaw * 100).toFixed(3);
    customField.style.display = 'flex';
    setBadge('badgeRate', true, '공고 데이터(실제값)');
  }} else if (!isNaN(rateRaw) && rateRaw > 30 && rateRaw <= 100) {{
    // 이미 %(예: 89.745) 단위로 온 경우
    document.getElementById('calcRateSel').value = 'custom';
    document.getElementById('calcCustomRate').value = rateRaw.toFixed(3);
    customField.style.display = 'flex';
    setBadge('badgeRate', true, '공고 데이터(실제값)');
  }} else {{
    const tier = pickRateTierByAmount(baseVal);
    if (tier) {{
      document.getElementById('calcRateSel').value = tier;
      customField.style.display = 'none';
      setBadge('badgeRate', false, '', '금액구간 추정값-확인필요');
    }} else {{
      document.getElementById('calcRateSel').value = 'custom';
      document.getElementById('calcCustomRate').value = '';
      customField.style.display = 'flex';
      setBadge('badgeRate', false, '', '데이터 없음-직접입력');
    }}
  }}

  // 복수예가 생성개수 / 추첨개수
  if (!isNaN(totalRaw) && totalRaw >= 2 && totalRaw <= 50 && !isNaN(drawRaw) && drawRaw >= 1 && drawRaw <= totalRaw) {{
    document.getElementById('calcTotalCount').value = totalRaw;
    document.getElementById('calcDrawCount').value = drawRaw;
    setBadge('badgeTotalCount', true, '공고 데이터(실제값)');
    setBadge('badgeDrawCount', true, '공고 데이터(실제값)');
  }} else {{
    document.getElementById('calcTotalCount').value = 15;
    document.getElementById('calcDrawCount').value = 4;
    setBadge('badgeTotalCount', false, '', '기본값(15)-확인필요');
    setBadge('badgeDrawCount', false, '', '기본값(4)-확인필요');
  }}

  document.getElementById('calcGenBtn').textContent = `🎲 복수예가 ${{document.getElementById('calcTotalCount').value}}개 생성`;
  document.getElementById('calcDrawBtn').textContent = `🎯 ${{document.getElementById('calcDrawCount').value}}개 추첨`;

  document.getElementById('calcWarnBox').style.display = 'none';
  document.getElementById('calcTable').style.display = 'none';
  document.getElementById('calcResultBox').style.display = 'none';
  document.getElementById('calcDrawBtn').disabled = true;
  calcBids = []; calcPicked = [];
  document.getElementById('calcModal').classList.add('open');
}}
function closeCalc() {{
  document.getElementById('calcModal').classList.remove('open');
}}

function calcRate() {{
  const sel = document.getElementById('calcRateSel').value;
  if (sel === 'custom') {{
    const v = parseFloat(document.getElementById('calcCustomRate').value);
    return isNaN(v) ? 0 : v / 100;
  }}
  return parseFloat(sel);
}}
function won(n) {{ return Math.round(n).toLocaleString('ko-KR') + '원'; }}

function showCalcWarn(errors) {{
  const box = document.getElementById('calcWarnBox');
  if (!errors.length) {{ box.style.display = 'none'; box.textContent = ''; return false; }}
  box.textContent = '⚠ 계산을 진행할 수 없습니다 - 값을 확인 후 다시 시도해주세요.\\n' + errors.map(e => '· ' + e).join('\\n');
  box.style.display = 'block';
  return true;
}}

function calcGenerate() {{
  const base = parseFloat(document.getElementById('calcBase').value);
  const variance = parseFloat(document.getElementById('calcVariance').value);
  const totalCount = parseInt(document.getElementById('calcTotalCount').value, 10);

  const errors = [];
  if (!base || base <= 0) errors.push('기초금액을 입력해주세요.');
  if (!totalCount || totalCount < 2 || totalCount > 50) errors.push('복수예가 생성개수가 올바르지 않습니다(2~50 사이여야 함).');
  if (showCalcWarn(errors)) return;

  calcBids = [];
  for (let i = 1; i <= totalCount; i++) {{
    const rate = (Math.random() * (variance * 2) - variance);
    const price = Math.round(base * (1 + rate / 100));
    calcBids.push({{ no: i, rate, price }});
  }}
  calcPicked = [];
  renderCalcTable();
  document.getElementById('calcTable').style.display = 'table';
  document.getElementById('calcResultBox').style.display = 'none';
  document.getElementById('calcDrawBtn').disabled = false;
  const drawCount = parseInt(document.getElementById('calcDrawCount').value, 10) || 4;
  document.getElementById('calcDrawBtn').textContent = `🎯 ${{drawCount}}개 추첨`;
}}

function renderCalcTable() {{
  const tbody = document.getElementById('calcTbody');
  tbody.innerHTML = '';
  const pickedNos = calcPicked.map(p => p.no);
  calcBids.forEach(b => {{
    const tr = document.createElement('tr');
    if (pickedNos.includes(b.no)) tr.className = 'picked';
    tr.innerHTML = `<td>${{b.no}}</td><td>${{b.rate >= 0 ? '+' : ''}}${{b.rate.toFixed(3)}}%</td><td>${{won(b.price)}}</td>`;
    tbody.appendChild(tr);
  }});
}}

function calcDraw() {{
  const drawCount = parseInt(document.getElementById('calcDrawCount').value, 10);
  const lowLimitRate = calcRate();

  const errors = [];
  if (!calcBids.length) errors.push('먼저 복수예가를 생성해주세요.');
  if (!drawCount || drawCount < 1 || drawCount > calcBids.length) errors.push(`추첨개수는 1~${{calcBids.length || '?'}} 사이여야 합니다.`);
  if (!lowLimitRate || lowLimitRate <= 0.3 || lowLimitRate > 1) errors.push('낙찰하한율 값이 비정상입니다(30%~100% 범위여야 함). 공고문에서 정확한 낙찰하한율을 확인한 뒤 "직접입력"으로 입력해주세요.');
  if (showCalcWarn(errors)) {{ document.getElementById('calcResultBox').style.display = 'none'; return; }}

  const shuffled = [...calcBids].sort(() => Math.random() - 0.5);
  calcPicked = shuffled.slice(0, drawCount).sort((a, b) => a.no - b.no);
  renderCalcTable();

  const aValue = parseFloat(document.getElementById('calcAValue').value) || 0;
  const avgPrice = calcPicked.reduce((s, b) => s + b.price, 0) / calcPicked.length;
  const exclAmount = avgPrice - aValue;
  const appliedAmount = exclAmount * lowLimitRate;
  const readdedAmount = appliedAmount + aValue;
  const finalAmount = Math.floor(readdedAmount);

  document.getElementById('c_assessed').textContent = won(avgPrice);
  document.getElementById('c_excl').textContent = won(exclAmount);
  document.getElementById('c_applied').textContent = won(appliedAmount);
  document.getElementById('c_readded').textContent = won(readdedAmount);
  document.getElementById('c_final').textContent = won(finalAmount);
  document.getElementById('calcResultBox').style.display = 'block';
}}
</script>

</body>
</html>
"""


AWARDS_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>emtech-biz | 낙찰결과</title>
<style>
  :root {{
    --ink: #14213d; --paper: #fbfaf7; --line: #e4e1d8; --accent: #c8511b;
    --accent-soft: #f5e3d8; --muted: #6b6b63; --card: #ffffff; --good: #2a6f97; --good-soft: #e4eef4;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif; background:var(--paper); color:var(--ink); }}
  header {{ padding: 28px 24px 16px; border-bottom: 1px solid var(--line); }}
  header h1 {{ margin: 0 0 6px; font-size: 1.4rem; letter-spacing: -0.02em; }}
  header p {{ margin: 0; color: var(--muted); font-size: 0.88rem; }}
  .meta {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:12px; font-size:0.8rem; color:var(--muted); }}
  .meta b {{ color: var(--ink); }}
  .ext-links {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:14px; font-size:0.8rem; }}
  .ext-label {{ color:var(--muted); }}
  .ext-links a {{ color:var(--good); text-decoration:none; padding:3px 10px; border:1px solid var(--line); border-radius:999px; font-size:0.78rem; }}
  .ext-links a:hover {{ background:var(--good-soft); }}

  .controls {{ display:flex; gap:10px; flex-wrap:wrap; padding:14px 24px; border-bottom:1px solid var(--line); position: sticky; top: 0; background: var(--paper); z-index: 5; }}
  .controls input, .controls select {{ padding:8px 12px; border:1px solid var(--line); border-radius:6px; background:var(--card); font-size:0.85rem; color:var(--ink); }}
  .controls input[type=text] {{ flex:1; min-width:160px; }}

  main {{ padding: 8px 24px 60px; }}
  .count {{ font-size:0.82rem; color:var(--muted); margin:14px 0; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.84rem; }}
  thead th {{ text-align:left; padding:9px 10px; border-bottom:2px solid var(--ink); color:var(--muted); font-weight:600; white-space:nowrap; }}
  .filter-row th {{ padding:4px 6px 8px; border-bottom:1px solid var(--line); }}
  .col-filter {{ width:100%; box-sizing:border-box; padding:5px 6px; font-size:0.76rem; border:1px solid var(--line); border-radius:5px; background:var(--paper); color:var(--ink); }}
  .col-filter[type="number"] {{ width:60px; }}
  tbody tr {{ border-bottom:1px solid var(--line); vertical-align: top; }}
  tbody tr:hover {{ background: var(--accent-soft); }}
  td {{ padding:10px; }}
  td.title a {{ color:var(--ink); text-decoration:none; font-weight:500; }}
  td.title a:hover {{ color:var(--accent); text-decoration:underline; }}
  .btn-calc {{ padding:6px 10px; font-size:0.78rem; font-weight:600; border:none; border-radius:6px; background:var(--ink); color:#fff; cursor:pointer; white-space:nowrap; }}
  .btn-calc:hover {{ background:#0c1730; }}
  .empty {{ padding:60px 0; text-align:center; color:var(--muted); }}
  footer {{ padding:20px 24px 40px; font-size:0.78rem; color:var(--muted); border-top:1px solid var(--line); }}

  @media (max-width: 720px) {{
    table, thead, tbody, tr, td {{ display:block; }}
    thead {{ display:none; }}
    tbody tr {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin-bottom:12px; padding:8px 4px; }}
    td {{ padding:6px 12px; }}
    td::before {{ content: attr(data-label); display:block; font-size:0.7rem; color:var(--muted); margin-bottom:2px; }}
  }}
  .lock-screen {{ position:fixed; inset:0; background:var(--paper); z-index:200; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:16px; }}
  .lock-box {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:32px 28px; width:280px; text-align:center; }}
  .lock-box h2 {{ font-size:1.05rem; margin:0 0 16px; }}
  .lock-box input {{ width:100%; box-sizing:border-box; padding:10px 12px; margin-bottom:10px; border:1px solid var(--line); border-radius:6px; font-size:0.9rem; text-align:center; }}
  .lock-box button {{ width:100%; padding:10px; border:none; border-radius:6px; background:var(--accent); color:#fff; font-weight:600; cursor:pointer; }}
  .lock-error {{ color:var(--accent); font-size:0.8rem; margin-top:8px; display:none; }}
</style>
</head>
<body>

<div class="lock-screen" id="lockScreen">
  <div class="lock-box">
    <h2>비밀번호를 입력하세요</h2>
    <input id="lockInput" type="password" placeholder="비밀번호" autofocus>
    <button onclick="checkPassword()">입장</button>
    <div class="lock-error" id="lockError">비밀번호가 틀렸습니다.</div>
  </div>
</div>

<div id="mainContent" style="display:none;">
<header>
  <h1>emtech-biz — 낙찰결과</h1>
  <p>나라장터 공사 낙찰(개찰결과) 정보 — 과거 공고 위주 (참가등록/투찰마감이 남은 공고는 입찰공고 목록에서 확인)</p>
  <div class="meta">
    <span>마지막 업데이트: <b>{updated_at}</b></span>
    <span>총 <b>{count}</b>건</span>
  </div>
  <div class="ext-links">
    <span class="ext-label"></span>
    <a href="index.html">← 입찰공고 목록으로</a>
  </div>
</header>

<div class="controls">
  <label style="display:flex; align-items:center; gap:6px; font-size:0.85rem; white-space:nowrap; cursor:pointer;">
    <input id="telecomOnly" type="checkbox" checked style="width:16px; height:16px;">
    통신 업종만 보기
  </label>
  <select id="searchField" style="max-width:130px; flex:none;">
    <option value="all">전체검색</option>
    <option value="title">공고명</option>
    <option value="notice_no">공고번호</option>
    <option value="org">발주기관</option>
    <option value="winner">낙찰자</option>
  </select>
  <input id="search" type="text" placeholder="검색어 입력...">
</div>
<div class="controls" style="border-top:none;">
  <span style="align-self:center; font-size:0.82rem; color:var(--muted);">개찰일 기준</span>
  <input id="dateStart" type="date" value="{date_start_default}">
  <span style="align-self:center; color:var(--muted);">~</span>
  <input id="dateEnd" type="date" value="{date_end_default}">
  <button class="btn-calc" onclick="render()">검색</button>
  <button class="btn-calc" onclick="clearDateRange()">전체</button>
</div>

<main>
  <div class="count" id="count"></div>
  <table>
    <thead>
      <tr>
        <th>공고명</th><th>발주기관</th><th>낙찰자</th><th>낙찰자 전화번호</th><th>낙찰금액</th><th>기초금액</th><th>사정율</th><th>개찰일</th>
      </tr>
      <tr class="filter-row">
        <th><input id="colFilterTitle" class="col-filter" type="text" placeholder="검색"></th>
        <th><input id="colFilterOrg" class="col-filter" type="text" placeholder="검색"></th>
        <th><input id="colFilterWinner" class="col-filter" type="text" placeholder="검색"></th>
        <th></th>
        <th>
          <div style="display:flex; gap:2px;">
            <input id="colFilterAmountMin" class="col-filter" type="number" placeholder="최소">
            <input id="colFilterAmountMax" class="col-filter" type="number" placeholder="최대">
          </div>
        </th>
        <th></th>
        <th></th>
        <th><button class="btn-calc" onclick="clearColFilters()">초기화</button></th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div class="empty" id="emptyMsg" style="display:none;">조건에 맞는 낙찰결과가 없습니다.</div>
</main>

<footer>emtech-biz | 이엠테크 낙찰결과 모니터</footer>
</div>

<script>
const AWARDS = {awards_json};
const TELECOM_KEYWORDS = {keywords_json};
const MEMO_KEY = 'bidmonitor_memos';

/* ---------- 비밀번호 잠금화면 (index.html과 동일한 키를 공유) ---------- */
const PASSWORD_HASH = "{password_hash}";
const LOCK_KEY = 'bidmonitor_unlocked';

async function sha256Hex(text) {{
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}}

async function checkPassword() {{
  const input = document.getElementById('lockInput').value;
  const hash = await sha256Hex(input);
  if (hash === PASSWORD_HASH) {{
    localStorage.setItem(LOCK_KEY, PASSWORD_HASH);
    document.getElementById('lockScreen').style.display = 'none';
    document.getElementById('mainContent').style.display = 'block';
  }} else {{
    document.getElementById('lockError').style.display = 'block';
  }}
}}
document.getElementById('lockInput').addEventListener('keydown', (e) => {{ if (e.key === 'Enter') checkPassword(); }});

if (!PASSWORD_HASH) {{
  document.getElementById('lockScreen').style.display = 'none';
  document.getElementById('mainContent').style.display = 'block';
}} else if (localStorage.getItem(LOCK_KEY) === PASSWORD_HASH) {{
  document.getElementById('lockScreen').style.display = 'none';
  document.getElementById('mainContent').style.display = 'block';
}}

function won(n) {{
  const v = parseAmount(n);
  return v === null ? '-' : Number(v).toLocaleString('ko-KR') + '원';
}}
function parseAmount(v) {{
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
}}
function fmtDateTime(text) {{
  if (!text) return '-';
  return String(text).replace('T', ' ').slice(0, 16);
}}
function clearDateRange() {{
  document.getElementById('dateStart').value = '';
  document.getElementById('dateEnd').value = '';
  render();
}}

function openBidWindow(e, url) {{
  if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return true;
  e.preventDefault();
  window.open(url, '_blank', 'noopener,noreferrer,width=1100,height=900');
  return false;
}}

function clearColFilters() {{
  ['colFilterTitle','colFilterOrg','colFilterWinner','colFilterAmountMin','colFilterAmountMax'].forEach(id => {{
    document.getElementById(id).value = '';
  }});
  render();
}}

function render() {{
  const telecomOnly = document.getElementById('telecomOnly').checked;
  const searchField = document.getElementById('searchField').value;
  const q = document.getElementById('search').value.trim().toLowerCase();
  const startVal = document.getElementById('dateStart').value;
  const endVal = document.getElementById('dateEnd').value;
  const colTitle = document.getElementById('colFilterTitle').value.trim().toLowerCase();
  const colOrg = document.getElementById('colFilterOrg').value.trim().toLowerCase();
  const colWinner = document.getElementById('colFilterWinner').value.trim().toLowerCase();
  const colAmountMin = parseAmount(document.getElementById('colFilterAmountMin').value);
  const colAmountMax = parseAmount(document.getElementById('colFilterAmountMax').value);

  let filtered = AWARDS.filter(a => {{
    if (telecomOnly && !TELECOM_KEYWORDS.some(k => (a.title || '').includes(k))) return false;
    if (q) {{
      const hay = searchField === 'all'
        ? [a.title, a.org, a.notice_no, a.winner].join(' ').toLowerCase()
        : String(a[searchField] || '').toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    if (colTitle && !(a.title || '').toLowerCase().includes(colTitle)) return false;
    if (colOrg && !(a.org || '').toLowerCase().includes(colOrg)) return false;
    if (colWinner && !(a.winner || '').toLowerCase().includes(colWinner)) return false;
    const awardAmt = parseAmount(a.award_amount);
    if (colAmountMin !== null && (awardAmt === null || awardAmt < colAmountMin)) return false;
    if (colAmountMax !== null && (awardAmt === null || awardAmt > colAmountMax)) return false;
    if (startVal || endVal) {{
      const d = (a.open_date || '').slice(0, 10);
      if (!d) return false;
      if (startVal && d < startVal) return false;
      if (endVal && d > endVal) return false;
    }}
    return true;
  }});

  filtered.sort((a, b) => (b.open_date || '').localeCompare(a.open_date || ''));

  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  document.getElementById('count').textContent = filtered.length + '건 표시 중';
  document.getElementById('emptyMsg').style.display = filtered.length ? 'none' : 'block';

  filtered.forEach(a => {{
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td data-label="공고명" class="title">${{a.url ? `<a href="${{a.url}}" target="_blank" rel="noopener" onclick="return openBidWindow(event, this.href)">${{a.title || ''}}</a>` : (a.title || '')}}</td>
      <td data-label="발주기관">${{a.org || ''}}</td>
      <td data-label="낙찰자"><b>${{a.winner || '-'}}</b></td>
      <td data-label="낙찰자 전화번호">${{a.winner_tel || '-'}}</td>
      <td data-label="낙찰금액">${{won(a.award_amount)}}</td>
      <td data-label="기초금액">${{won(a.base_amount)}}</td>
      <td data-label="사정율">${{a.assessed_rate ? a.assessed_rate + '%' : '-'}}</td>
      <td data-label="개찰일">${{fmtDateTime(a.open_date)}}</td>
    `;
    tbody.appendChild(tr);
  }});
}}

document.getElementById('telecomOnly').addEventListener('change', render);
document.getElementById('search').addEventListener('input', render);
document.getElementById('searchField').addEventListener('change', render);
document.getElementById('dateStart').addEventListener('change', render);
document.getElementById('dateEnd').addEventListener('change', render);
['colFilterTitle','colFilterOrg','colFilterWinner','colFilterAmountMin','colFilterAmountMax'].forEach(id => {{
  document.getElementById(id).addEventListener('input', render);
}});
render();
</script>

</body>
</html>
"""


def generate_awards_page(awards=None, status_list=None):
    os.makedirs(DOCS_DIR, exist_ok=True)

    if awards is None:
        if os.path.exists(AWARDS_JSON_PATH):
            with open(AWARDS_JSON_PATH, "r", encoding="utf-8") as f:
                awards = json.load(f)
        else:
            awards = []

    password_hash = (
        hashlib.sha256(DASHBOARD_PASSWORD.encode("utf-8")).hexdigest()
        if DASHBOARD_PASSWORD else ""
    )

    # 기본 검색 범위: 1개월 전 ~ 오늘 (낙찰결과는 이미 끝난 과거 공고 위주라
    # 과거 방향으로 잡음 - 입찰공고 목록 페이지의 미래 방향 기본값과 반대).
    today = datetime.now().date()
    date_start_default = _add_months(today, -1).isoformat()
    date_end_default = today.isoformat()

    html = AWARDS_TEMPLATE.format(
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        count=len(awards),
        awards_json=json.dumps(awards, ensure_ascii=False),
        keywords_json=json.dumps(KEYWORDS, ensure_ascii=False),
        password_hash=password_hash,
        date_start_default=date_start_default,
        date_end_default=date_end_default,
    )

    with open(AWARDS_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"낙찰결과 페이지 생성 완료: {AWARDS_HTML_PATH}")


def generate_dashboard(bids=None, status_list=None):
    os.makedirs(DOCS_DIR, exist_ok=True)

    if bids is None:
        if os.path.exists(BIDS_JSON_PATH):
            with open(BIDS_JSON_PATH, "r", encoding="utf-8") as f:
                bids = json.load(f)
        else:
            bids = []

    if status_list is None:
        if os.path.exists(STATUS_JSON_PATH):
            with open(STATUS_JSON_PATH, "r", encoding="utf-8") as f:
                status_list = json.load(f).get("sources", [])
        else:
            status_list = []

    links_html = " ".join(
        f'<a href="{link["url"]}" target="_blank" rel="noopener">{link["name"]}</a>'
        for link in EXTERNAL_MANUAL_LINKS
    )

    status_html = "".join(
        f'<span class="status-pill {"status-ok" if s["ok"] else "status-bad"}" '
        f'title="{s["note"]}">{s["source"]} {"●" if s["ok"] else "⚠"}</span>'
        for s in status_list
    )

    password_hash = (
        hashlib.sha256(DASHBOARD_PASSWORD.encode("utf-8")).hexdigest()
        if DASHBOARD_PASSWORD else ""
    )

    # 기본 검색 범위: 오늘 ~ 1개월 후 (참가등록/투찰마감처럼 앞으로 다가올 일정
    # 위주로 보는 페이지라 미래 방향으로 잡음). 낙찰결과(과거 방향)는
    # awards.html이 별도로 담당합니다 - 한 페이지에서 미래/과거를 같이
    # 검색하려니 날짜 범위가 서로 안 맞았던 문제를 이렇게 분리했습니다.
    today = datetime.now().date()
    date_start_default = today.isoformat()
    date_end_default = _add_months(today, 1).isoformat()

    html = TEMPLATE.format(
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        keywords=", ".join(KEYWORDS),
        regions=", ".join(REGIONS),
        count=len(bids),
        bids_json=json.dumps(bids, ensure_ascii=False),
        keywords_json=json.dumps(KEYWORDS, ensure_ascii=False),
        external_links_html=links_html,
        status_html=status_html,
        password_hash=password_hash,
        date_start_default=date_start_default,
        date_end_default=date_end_default,
    )

    with open(DASHBOARD_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"대시보드 생성 완료: {DASHBOARD_HTML_PATH}")


if __name__ == "__main__":
    generate_dashboard()
    generate_awards_page()
