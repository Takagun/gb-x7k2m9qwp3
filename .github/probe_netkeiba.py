# -*- coding: utf-8 -*-
"""netkeibaページ構造の一時診断 (weekly.yml の probe 入力から実行)。

2026-07-23 の週次バッチ全滅の原因切り分け用:
- 未来日付のレースID発見 (race_list_sub.html が使えるか)
- dbレースページのパース可否 (7/20 は成功、7/23 は失敗)
礼儀は engine/scraper.py と同じ: 2〜4秒ディレイ・直列・タイムアウト15秒。
"""
import random
import re
import sys
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://race.netkeiba.com/",
}
DB_SURFACE_DIST_RE = re.compile(r"(障芝|障ダ|芝|ダ)(?:右|左|直線)?\s*(?:外|内)?\s*(\d{3,4})m")
SURFACE_DIST_RE = re.compile(r"(障芝|障ダ|障|芝|ダ)(\d{3,4})m")
RACE_ID_RE = re.compile(r"race_id=(\d{12})|/race/(\d{12})/?")

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url):
    time.sleep(random.uniform(2.0, 4.0))
    try:
        return session.get(url, timeout=15)
    except requests.RequestException as e:
        print(f"== {url}\n  FETCH ERROR: {e}")
        return None


def visible_text(html):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def probe(url, extra_res=()):
    r = fetch(url)
    if r is None:
        return None
    print(f"== {url}")
    print(f"  status={r.status_code} bytes={len(r.content)} "
          f"hdr_encoding={r.encoding} content_type={r.headers.get('content-type')}")
    best = None
    for enc in ("EUC-JP", "UTF-8"):
        text = r.content.decode(enc, errors="ignore")
        ids = sorted({a or b for a, b in RACE_ID_RE.findall(text)})
        m_title = re.search(r"<title>(.*?)</title>", text, re.S)
        title = re.sub(r"\s+", " ", m_title.group(1)).strip()[:80] if m_title else None
        hits = {res.pattern[:20]: bool(res.search(text)) for res in extra_res}
        print(f"  [{enc}] race_ids n={len(ids)} sample={ids[:6]}")
        print(f"  [{enc}] title={title!r} regex_hits={hits}")
        if best is None or (title and re.search(r"[ぁ-んァ-ン一-龥]", title)):
            best = (enc, text, ids)
    enc, text, ids = best
    print(f"  [{enc}] visible_text[:350]={visible_text(text)[:350]!r}")
    return ids


print("--- 1. 未来日付のレースID発見ルート ---")
ids_sat = probe("https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=20260725") or []
ids_sun = probe("https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=20260726") or []
probe("https://race.netkeiba.com/top/?kaisai_date=20260725")

print("--- 2. dbページ (7/20成功 vs 7/23失敗の切り分け) ---")
probe("https://db.netkeiba.com/race/list/20260718/")
probe("https://db.netkeiba.com/race/202603020701/", extra_res=(DB_SURFACE_DIST_RE,))
probe("https://db.netkeiba.com/race/202604020207/", extra_res=(DB_SURFACE_DIST_RE,))

print("--- 3. 未来レースの出馬表 ---")
for rid in (ids_sat[:1] + ids_sun[:1]) or []:
    probe(f"https://race.netkeiba.com/race/shutuba.html?race_id={rid}",
          extra_res=(SURFACE_DIST_RE, re.compile(r"db\.netkeiba\.com/horse/\d{10}")))
if not ids_sat and not ids_sun:
    print("race_list_sub からIDが取れなかったため出馬表プローブはスキップ")

sys.exit(0)
