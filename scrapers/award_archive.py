"""
통신 공사 낙찰 아카이브(data/award_archive.json) - 경쟁사 분석과 사정율 이력의 장기 표본.

2026-10-19: data/awards.json은 최근 30일(LOOKBACK_DAYS)만 남아서, 경쟁사 현황을 보면 업체마다
1~2건뿐이었다. 통신 관련 공사 낙찰만 따로 모아 365일 동안 보관한다(공개 데이터만).
처음 한 번은 지난 12개월을 한 달씩 나눠 채우고(backfill), 이후에는 매 실행의 새 낙찰만 더한다.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import KEYWORDS
from scrapers.g2b_awards import fetch_g2b_awards
from scrapers._common import get_region_scope

ARCHIVE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "award_archive.json")
KEEP_DAYS = 365
BACKFILL_MONTHS = 12
BACKFILL_PER_RUN = 4   # 한 실행에 최대 4개월씩 채워 호출량을 나눈다


def _is_telecom(a, bids_by_key):
    b = bids_by_key.get(f"{a.get('source')}::{a.get('notice_no')}") or {}
    return any(k in ((a.get("title") or "") + " " + (b.get("industry") or "")) for k in KEYWORDS)


def update_award_archive(new_awards, bids_by_key):
    try:
        with open(ARCHIVE_PATH, encoding="utf-8") as f:
            archive = json.load(f)
    except Exception:
        archive = {"awards": {}, "backfilled_months": []}
    store = archive.setdefault("awards", {})
    done = set(archive.setdefault("backfilled_months", []))
    if not archive.get("chunked_v2"):
        done = set()  # 첫 백필은 월 단위 조회가 7,500건에서 잘렸다 - 5일 단위로 다시 채운다
        archive["chunked_v2"] = True

    def add(a):
        if not (a.get("notice_no") and _is_telecom(a, bids_by_key)):
            return
        rec = {k: a.get(k) for k in (
            "source", "title", "org", "notice_no", "winner", "award_amount", "assessed_rate",
            "open_date", "region_scope", "notice_kind", "url", "participants")}
        if not rec.get("region_scope"):
            # 과거 구간에서 채운 낙찰은 참가가능지역을 모르므로 발주기관·공고명으로 경기/용인만 표시한다.
            guess = get_region_scope("", a.get("org", ""), a.get("title", ""))
            rec["region_scope"] = guess if guess in ("용인", "경기") else "기타"
        key = f"{a.get('source')}::{a['notice_no']}"
        if key in store and store[key].get("region_scope") not in (None, "기타") and rec["region_scope"] == "기타":
            rec["region_scope"] = store[key]["region_scope"]
        store[key] = rec

    for a in new_awards:
        add(a)

    # 지난 12개월 채우기 - 아직 안 채운 달부터, 한 번에 BACKFILL_PER_RUN개월까지
    today = datetime.now().replace(day=1)
    months = []
    for i in range(1, BACKFILL_MONTHS + 1):
        y, m = today.year, today.month - i
        while m <= 0:
            y, m = y - 1, m + 12
        months.append(f"{y}-{m:02d}")
    for ym in [m for m in months if m not in done][:BACKFILL_PER_RUN]:
        y, m = map(int, ym.split("-"))
        start = datetime(y, m, 1)
        end = (datetime(y + (m == 12), (m % 12) + 1, 1) - timedelta(seconds=1))
        # 2026-10-20: 한 달을 한 번에 조회하면 7,500건 상한에 걸려 잘렸다(2026-06~09 모두 정확히 7,500건).
        # 5일씩 나눠 조회한다.
        rows, cur, failed = [], start, False
        while cur <= end:
            chunk_end = min(cur + timedelta(days=5) - timedelta(seconds=1), end)
            try:
                rows += fetch_g2b_awards(cur, chunk_end)
            except Exception as e:
                print(f"[낙찰 아카이브] {ym} {cur:%m-%d} 구간 실패: {e}")
                failed = True
                break
            cur = chunk_end + timedelta(seconds=1)
            time.sleep(1)
        if failed:
            break
        before = len(store)
        for a in rows:
            add(a)
        done.add(ym)
        print(f"[낙찰 아카이브] {ym} 채움: 낙찰 {len(rows)}건 중 통신 {len(store) - before}건 추가")
        time.sleep(1)
    archive["backfilled_months"] = sorted(done)

    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    for k in [k for k, v in store.items() if (v.get("open_date") or "9999") < cutoff]:
        del store[k]
    with open(ARCHIVE_PATH, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)
    print(f"[낙찰 아카이브] 통신 공사 낙찰 누적 {len(store)}건 (채운 달 {len(done)}/{BACKFILL_MONTHS})")
    return list(store.values())
