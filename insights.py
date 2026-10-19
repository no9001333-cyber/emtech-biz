"""
분석 페이지(docs/insights.html): 투찰가 추천 · 경쟁사 현황 · 발주예정(발주계획).

2026-10-19 사용자 요청("가장 혁신적으로 입찰을 보기 위해 할 수 있는 것" 중 알림을 뺀 나머지):
  1) 투찰가 추천 - 지금 기본 화면에 뜨는 공고(참가가능·공사·통신·진행중)마다, 과거 개찰의
     실제 사정율(예정가격/기초금액, data/rate_history.json)을 같은 발주기관 → 같은 금액대 통신공사
     순으로 찾아 하위25%/중앙/상위25% 구간과 그에 해당하는 투찰금액을 보여준다.
     투찰금액 = (기초금액 × 사정율 − A값) × 낙찰하한율 + A값.
  2) 경쟁사 현황 - 낙찰정보(data/awards.json) 중 용인/경기/전국 통신공사 낙찰 업체별 건수·금액·평균
     낙찰률·평균 사정율.
  3) 발주예정 - 나라장터 발주계획(data/order_plans.json) 중 앞으로 나올 용인/경기/전국 통신공사.

이엠테크 자체 투찰 이력(금액·순위)은 이 페이지에 넣지 않는다 - 저장소와 사이트가 공개라서.
그 분석은 로컬 전용 보고서(tools/my_bid_report.py)로 만든다.
"""

import hashlib
import html
import json
import os
import statistics
from datetime import datetime, timedelta

from config import DOCS_DIR, DATA_DIR, KEYWORDS, DASHBOARD_PASSWORD

INSIGHTS_HTML_PATH = os.path.join(DOCS_DIR, "insights.html")
RATE_HISTORY_PATH = os.path.join(DATA_DIR, "rate_history.json")
ORDER_PLANS_PATH = os.path.join(DATA_DIR, "order_plans.json")
MIN_SAMPLES = 3


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _is_telecom(b):
    return any(k in ((b.get("title") or "") + " " + (b.get("industry") or "")) for k in KEYWORDS)


def _visible(b):
    return (b.get("eligible") and b.get("region_scope") in ("용인", "경기", "전국")
            and b.get("notice_kind") in (None, "공사") and b.get("status") == "진행중" and _is_telecom(b))


def _amount_band(base):
    if base is None:
        return None
    for limit, name in ((1e8, "1억 미만"), (3e8, "1~3억"), (10e8, "3~10억"), (30e8, "10~30억")):
        if base < limit:
            return name
    return "30억 이상"


def _quartiles(values):
    vs = sorted(values)
    if len(vs) < MIN_SAMPLES:
        return None
    q = statistics.quantiles(vs, n=4, method="inclusive")
    return q[0], statistics.median(vs), q[2]


def _bid_amount(base, sajung, lower, a_value):
    if not (base and sajung and lower):
        return None
    a = a_value or 0
    return round((base * sajung / 100 - a) * lower / 100 + a)


def build_recommendations(bids, history):
    samples = [h for h in history.values() if "sajung" in h and 95 <= h["sajung"] <= 105]
    by_org, by_band = {}, {}
    for h in samples:
        by_org.setdefault(h.get("org") or "", []).append(h["sajung"])
        if h.get("telecom"):
            by_band.setdefault(_amount_band(h.get("base")), []).append(h["sajung"])
    recs = []
    for b in bids:
        if not _visible(b):
            continue
        base = _num(b.get("base_amount"))
        lower = _num(b.get("successful_bid_lower_rate"))
        a_value = _num(b.get("a_value"))
        q, basis = None, ""
        org_vals = by_org.get(b.get("org") or "", [])
        if len(org_vals) >= MIN_SAMPLES:
            q, basis = _quartiles(org_vals), f"같은 발주기관 {len(org_vals)}건"
        else:
            band = _amount_band(base)
            band_vals = by_band.get(band, [])
            if len(band_vals) >= MIN_SAMPLES:
                q, basis = _quartiles(band_vals), f"통신공사 {band} {len(band_vals)}건"
        recs.append({
            "title": b.get("title", ""), "org": b.get("org", ""), "source": b.get("source", ""),
            "notice_no": b.get("notice_no", ""), "deadline": str(b.get("deadline") or "")[:16],
            "url": b.get("url", ""), "base": base, "base_confirmed": bool(b.get("base_amount_confirmed")),
            "lower": lower, "a_value": a_value, "basis": basis or "비교할 과거 개찰이 아직 부족",
            "q": [round(x, 3) for x in q] if q else None,
            "amounts": [_bid_amount(base, x, lower, a_value) for x in q] if q else None,
        })
    recs.sort(key=lambda r: r["deadline"] or "9999")
    return recs, len(samples)


def build_competitors(awards, history, days=180):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = {}
    for a in awards:
        if not a.get("winner") or (a.get("open_date") or "") < since:
            continue
        if a.get("region_scope") not in ("용인", "경기", "전국") or not _is_telecom(a):
            continue
        r = rows.setdefault(a["winner"].strip(), {"wins": 0, "amount": 0.0, "rates": [], "sajungs": [], "last": ""})
        r["wins"] += 1
        r["amount"] += _num(a.get("award_amount")) or 0
        rate = _num(a.get("assessed_rate"))
        if rate and 70 < rate < 100:
            r["rates"].append(rate)
        h = history.get(a.get("notice_no") or "")
        if h and "sajung" in h:
            r["sajungs"].append(h["sajung"])
        if (a.get("open_date") or "") > r["last"]:
            r["last"] = a.get("open_date") or ""
            r["last_title"] = a.get("title", "")
    out = []
    for name, r in rows.items():
        out.append({
            "winner": name, "wins": r["wins"], "amount": round(r["amount"]),
            "avg_rate": round(statistics.mean(r["rates"]), 3) if r["rates"] else None,
            "avg_sajung": round(statistics.mean(r["sajungs"]), 3) if r["sajungs"] else None,
            "last": r["last"][:10], "last_title": r.get("last_title", ""),
        })
    out.sort(key=lambda x: (-x["wins"], -x["amount"]))
    return out[:40], days


def build_competition_size(awards, days=180):
    """범위(용인/경기/전국)별 통신공사 참여업체 수 중앙값. 2026-10-19 이엠테크 자체 투찰 147건을
    분석해보니 경기 한정 공고는 약 1,850곳, 용인 한정 공고는 100~130곳이 들어와 같은 조건이면
    낙찰 확률이 15배 가까이 차이 났다 - 공개 낙찰정보(참여업체 수)로 같은 통계를 계속 보여준다."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    by = {}
    for a in awards:
        n = _num(a.get("participants"))
        if not n or (a.get("open_date") or "") < since or not _is_telecom(a):
            continue
        by.setdefault(a.get("region_scope") or "미상", []).append(n)
    return {k: (len(v), statistics.median(v)) for k, v in by.items()}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _won(v):
    return f"{int(v):,}" if v else "-"


def generate_insights_page(bids, awards):
    history = _load(RATE_HISTORY_PATH, {})
    plans = _load(ORDER_PLANS_PATH, [])
    recs, n_samples = build_recommendations(bids, history)
    comps, days = build_competitors(awards, history)
    comp_size = build_competition_size(awards)
    e = html.escape

    rec_rows = []
    for r in recs:
        if r["q"]:
            band = " / ".join(f"{x:.3f}%" for x in r["q"])
            amt = " / ".join(_won(x) for x in r["amounts"]) if r["amounts"] and all(r["amounts"]) else "기초금액·하한율 확인 필요"
        else:
            band, amt = "-", "-"
        base_note = "" if r["base_confirmed"] else ' <span class="muted">(예산액 기준·기초금액 미공개)</span>'
        rec_rows.append(
            f"<tr><td>{e(r['deadline'])}</td><td class='title'><a href='{e(r['url'])}' target='_blank'>{e(r['title'])}</a>"
            f"<div class='muted'>{e(r['org'])} · {e(r['source'])}</div></td>"
            f"<td>{_won(r['base'])}{base_note}</td><td>{r['lower'] or '-'}</td>"
            f"<td><b>{band}</b><div class='muted'>{e(r['basis'])}</div></td><td>{amt}</td></tr>")
    comp_rows = [
        f"<tr><td>{i}</td><td>{e(c['winner'])}</td><td>{c['wins']}</td><td>{_won(c['amount'])}</td>"
        f"<td>{c['avg_rate'] or '-'}</td><td>{c['avg_sajung'] or '-'}</td><td>{e(c['last'])}<div class='muted'>{e(c['last_title'][:40])}</div></td></tr>"
        for i, c in enumerate(comps, 1)]
    plan_rows = [
        f"<tr><td>{e(p.get('order_month') or '미정')}</td><td class='title'>{e(p.get('title') or '')}</td>"
        f"<td>{e(p.get('org') or '')}</td><td>{e(p.get('region') or '')} <span class='muted'>({e(str(p.get('region_scope')))})</span></td>"
        f"<td>{_won(_num(p.get('amount')))}</td><td>{e(p.get('contract_method') or '')}</td></tr>"
        for p in plans]

    size_rows = [f"<tr><td>{e(k)}</td><td>{n}</td><td><b>{m:,.0f}곳</b></td></tr>"
                 for k, (n, m) in sorted(comp_size.items(), key=lambda kv: kv[1][1]) if k in ("용인", "경기", "전국")]
    def table(head, rows, empty):
        if not rows:
            return f"<p class='empty'>{empty}</p>"
        return "<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"

    password_hash = hashlib.sha256(DASHBOARD_PASSWORD.encode("utf-8")).hexdigest() if DASHBOARD_PASSWORD else ""
    page = TEMPLATE
    for k, v in {
        "%UPDATED%": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "%N_SAMPLES%": str(n_samples),
        "%REC_TABLE%": table(["마감", "공고", "기초금액", "낙찰하한율", "추천 사정율 (하위25% / 중앙 / 상위25%)", "투찰금액 (같은 순서)"],
                             rec_rows, "지금 기본 화면에 뜨는 공고가 없습니다."),
        "%COMP_DAYS%": str(days),
        "%COMP_TABLE%": table(["#", "업체", "낙찰 건수", "낙찰금액 합계", "평균 낙찰률(%)", "평균 사정율(%)", "최근 낙찰"],
                              comp_rows, "조건에 맞는 낙찰 기록이 아직 없습니다."),
        "%SIZE_TABLE%": table(["범위", "낙찰 건수", "참여업체 중앙값"], size_rows,
                              "참여업체 수가 쌓이는 중입니다(다음 수집부터 기록)."),
        "%PLAN_TABLE%": table(["발주시기", "사업명", "발주기관", "지역", "금액", "계약방법"], plan_rows,
                              "발주계획 데이터가 아직 없습니다 (공공데이터포털 '조달청_나라장터 발주계획현황서비스' 활용신청 필요)."),
        "%PASSWORD_HASH%": password_hash,
    }.items():
        page = page.replace(k, v)
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(INSIGHTS_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"분석 페이지 생성 완료: {INSIGHTS_HTML_PATH} (추천 {len(recs)}건, 사정율 표본 {n_samples}건, 경쟁사 {len(comps)}곳, 발주예정 {len(plans)}건)")


TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>emtech-biz | 분석</title>
<style>
:root { --ink:#14213d; --paper:#fbfaf7; --line:#e4e1d8; --accent:#c8511b; --muted:#6b6b63; --card:#fff; --good:#2a6f97; }
* { box-sizing:border-box; }
body { margin:0; font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif; background:var(--paper); color:var(--ink); }
header { padding:24px 24px 14px; border-bottom:1px solid var(--line); }
header h1 { margin:0 0 6px; font-size:1.35rem; }
header p, .muted { color:var(--muted); font-size:0.8rem; margin:0; }
nav a { color:var(--good); text-decoration:none; margin-right:14px; font-size:0.85rem; }
section { padding:18px 24px 8px; }
h2 { font-size:1.05rem; margin:8px 0 4px; }
.desc { color:var(--muted); font-size:0.82rem; margin:0 0 10px; line-height:1.5; }
table { width:100%; border-collapse:collapse; font-size:0.83rem; margin-bottom:18px; }
th { text-align:left; padding:8px; border-bottom:2px solid var(--ink); color:var(--muted); font-weight:600; white-space:nowrap; }
td { padding:8px; border-bottom:1px solid var(--line); vertical-align:top; }
td.title a { color:var(--ink); text-decoration:none; font-weight:500; }
td.title a:hover { color:var(--accent); text-decoration:underline; }
.empty { color:var(--muted); padding:16px 0; }
.lock-screen { position:fixed; inset:0; background:var(--paper); z-index:200; display:flex; align-items:center; justify-content:center; }
.lock-box { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:28px; width:280px; text-align:center; }
.lock-box input { width:100%; padding:10px; margin:10px 0; border:1px solid var(--line); border-radius:6px; text-align:center; }
.lock-box button { width:100%; padding:10px; border:none; border-radius:6px; background:var(--accent); color:#fff; font-weight:600; cursor:pointer; }
#lockError { color:var(--accent); font-size:0.8rem; display:none; }
@media (max-width:720px) { table, thead, tbody, tr, td { display:block; } thead { display:none; } tr { border:1px solid var(--line); border-radius:8px; margin-bottom:10px; background:var(--card); } }
</style></head><body>
<div class="lock-screen" id="lockScreen"><div class="lock-box"><b>비밀번호를 입력하세요</b>
<input id="lockInput" type="password" placeholder="비밀번호"><button onclick="checkPassword()">입장</button><div id="lockError">비밀번호가 틀렸습니다.</div></div></div>
<div id="mainContent" style="display:none">
<header><h1>입찰 분석</h1><p>업데이트 %UPDATED% · 사정율 표본 %N_SAMPLES%건</p>
<nav style="margin-top:10px"><a href="index.html">← 입찰공고</a><a href="awards.html">낙찰결과</a><a href="#rec">투찰가 추천</a><a href="#size">경쟁 규모</a><a href="#comp">경쟁사</a><a href="#plan">발주예정</a></nav></header>
<section id="rec"><h2>투찰가 추천</h2>
<p class="desc">지금 기본 화면(참가가능·공사·통신·진행중)의 공고마다 과거 개찰의 실제 사정율(예정가격÷기초금액)을 같은 발주기관 → 같은 금액대 통신공사 순으로 찾아 구간을 보여줍니다.
투찰금액 = (기초금액 × 사정율 − A값) × 낙찰하한율 + A값. 기초금액이 아직 공개되지 않은 공고는 예산액 기준이라 참고용입니다. 표본은 매일 개찰 결과로 쌓입니다.</p>
%REC_TABLE%</section>
<section id="size"><h2>경쟁 규모 - 어디에 투찰해야 확률이 높은가</h2>
<p class="desc">최근 180일 통신공사 낙찰의 참여업체 수 중앙값입니다. 사정율은 공고마다 사실상 무작위(±0.6%p)라 금액을 정교하게 고르는 것보다
경쟁이 적은 공고에 들어가는 것이 낙찰 확률을 훨씬 크게 바꿉니다 - 용인 한정 공고는 경쟁이 경기 전체 공고의 약 1/15입니다.</p>
%SIZE_TABLE%</section>
<section id="comp"><h2>경쟁사 현황 (최근 %COMP_DAYS%일, 용인/경기/전국 통신공사 낙찰)</h2>
<p class="desc">평균 사정율은 그 업체가 낙찰한 공고의 사정율이고, 평균 낙찰률은 예정가격 대비 낙찰금액입니다.</p>
%COMP_TABLE%</section>
<section id="plan"><h2>발주예정 (나라장터 발주계획)</h2>
<p class="desc">기관이 미리 올린 발주계획 중 앞으로 나올 용인/경기/전국(또는 지역 미정) 통신공사입니다. 정식 공고 전에 현장 확인·협력사 섭외를 준비할 수 있습니다.</p>
%PLAN_TABLE%</section>
</div>
<script>
const PASSWORD_HASH = "%PASSWORD_HASH%"; const LOCK_KEY = 'bidmonitor_unlocked';
async function sha256Hex(t){ const b=await crypto.subtle.digest('SHA-256', new TextEncoder().encode(t)); return Array.from(new Uint8Array(b)).map(x=>x.toString(16).padStart(2,'0')).join(''); }
function unlock(){ document.getElementById('lockScreen').style.display='none'; document.getElementById('mainContent').style.display='block'; }
async function checkPassword(){ const h=await sha256Hex(document.getElementById('lockInput').value); if(h===PASSWORD_HASH){ localStorage.setItem(LOCK_KEY,PASSWORD_HASH); unlock(); } else { document.getElementById('lockError').style.display='block'; } }
document.getElementById('lockInput').addEventListener('keydown', e => { if (e.key === 'Enter') checkPassword(); });
if (!PASSWORD_HASH || localStorage.getItem(LOCK_KEY) === PASSWORD_HASH) unlock();
</script></body></html>
"""
