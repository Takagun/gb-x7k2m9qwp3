# -*- coding: utf-8 -*-
"""netkeiba スクレイパー (docs/DESIGN.md §4)。

礼儀: リクエスト間2〜4秒ランダムディレイ / リトライ3回 / タイムアウト15秒 /
UA明示 / 直列のみ(並列リクエスト禁止)。EUC-JP。
パーサは soup/データを受ける純関数に分離し、フィクスチャで単体テストする。
"""
import json
import logging
import random
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TOP_URL = "https://race.netkeiba.com/top/?kaisai_date={date_str}"
SHUTUBA_URL = "https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
PED_URL = "https://db.netkeiba.com/horse/ped/{horse_id}/"
ODDS_API_URL = "https://race.netkeiba.com/api/api_get_jra_odds.html"
ODDS_SP_URL = "https://odds.sp.netkeiba.com/"

# JRA会場コード (NAR=地方は30以上なので除外)
JRA_VENUE_CODES = {f"{i:02d}" for i in range(1, 11)}
VENUE_NAMES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}

RACE_ID_RE = re.compile(r"\b(20[2-9]\d{9})\b")
POST_TIME_RE = re.compile(r"(\d{1,2}:\d{2})発走")
SURFACE_DIST_RE = re.compile(r"(芝|ダ)(\d{3,4})m")
KAISAI_RE = re.compile(r"(\d+)回\s*(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)\s*(\d+)日目")
HORSE_LINK_RE = re.compile(r"db\.netkeiba\.com/horse/(\d{10})")


class ParseError(Exception):
    """パース失敗。黙って空を返さずワークフローを fail させる (PROMPT #9)。"""


class BaseScraper:
    """レート制限+リトライ付きHTTPクライアント。並列利用禁止。"""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://race.netkeiba.com/",
    }
    MIN_DELAY = 2.0
    MAX_DELAY = 4.0
    MAX_RETRIES = 3
    TIMEOUT = 15
    BACKOFF_BASE = 5.0

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._last_request = 0.0

    def _wait(self):
        delay = random.uniform(self.MIN_DELAY, self.MAX_DELAY)
        elapsed = time.time() - self._last_request
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request = time.time()

    def _fetch(self, url, params=None):
        last_err = None
        for attempt in range(self.MAX_RETRIES):
            try:
                self._wait()
                resp = self.session.get(url, params=params, timeout=self.TIMEOUT)
                if resp.status_code == 429:
                    wait = self.BACKOFF_BASE * (2 ** attempt)
                    logger.warning("429 rate limited, sleeping %.1fs", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last_err = e
                logger.warning("attempt %d failed for %s: %s", attempt + 1, url, e)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.BACKOFF_BASE * (attempt + 1))
        raise ParseError(f"{self.MAX_RETRIES}回のリトライ全て失敗: {url}: {last_err}")

    def get_soup(self, url, params=None, encoding="EUC-JP"):
        resp = self._fetch(url, params=params)
        # サーバ宣言charsetを優先、無宣言/デフォルト値ならEUC-JPヒントを使う
        if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "windows-1252"):
            resp.encoding = encoding or resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")

    def get_json(self, url, params=None):
        resp = self._fetch(url, params=params)
        try:
            return resp.json()
        except json.JSONDecodeError as e:
            raise ParseError(f"JSONパース失敗: {url}: {e}") from e


# ──────────────────────────────────────────────
# パーサ (純関数 — フィクスチャでテスト)
# ──────────────────────────────────────────────

def parse_race_ids(html_text):
    """kaisai_date ページのHTMLから同開催の全レースIDを展開して返す。

    12桁ID (YYYYVVRRDDNN) を収集 → JRA会場のみ → 開催カード (YYYYVVRRDD)
    ごとに R01-12 へ展開 (race_list_scraper._expand_to_full_card 方式)。
    """
    cards = set()
    for m in RACE_ID_RE.finditer(html_text):
        race_id = m.group(1)
        if race_id[4:6] in JRA_VENUE_CODES:
            cards.add(race_id[:10])
    return sorted(f"{card}{nn:02d}" for card in cards for nn in range(1, 13))


def parse_shutuba(soup, race_id):
    """出馬表ページからレース情報と出走馬を抽出する。

    返り値: {race_id, venue_code, venue_name, race_number, post_time,
             surface, distance, race_name, date, horses: [{horse_number, horse_id, horse_name}]}
    """
    text = soup.get_text(" ", strip=False)

    m = SURFACE_DIST_RE.search(text)
    if not m:
        raise ParseError(f"{race_id}: 馬場・距離が抽出できない")
    surface = "芝" if m.group(1) == "芝" else "ダート"
    distance = int(m.group(2))

    post_time = None
    m = POST_TIME_RE.search(text)
    if m:
        h, mi = m.group(1).split(":")
        post_time = f"{int(h):02d}:{mi}"

    race_name = None
    name_elem = soup.find(class_="RaceName")
    if name_elem:
        race_name = name_elem.get_text(strip=True)

    date_str = None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(soup))
    if m:
        date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    venue_code = race_id[4:6]
    horses = _parse_shutuba_horses(soup)
    if not horses:
        raise ParseError(f"{race_id}: 出走馬が1頭も抽出できない")

    return {
        "race_id": race_id,
        "venue_code": venue_code,
        "venue_name": VENUE_NAMES.get(venue_code, venue_code),
        "race_number": int(race_id[10:12]),
        "post_time": post_time,
        "surface": surface,
        "distance": distance,
        "race_name": race_name,
        "date": date_str,
        "horses": horses,
    }


def _parse_shutuba_horses(soup):
    """出馬表テーブルの各行から (馬番, horse_id, 馬名) を取る。

    horse_id は db.netkeiba.com/horse/{id} リンクから。馬番は同じ行の
    Umaban セルまたは数字のみのセルから取得する。
    """
    horses = []
    seen = set()
    for a in soup.find_all("a", href=True):
        m = HORSE_LINK_RE.search(a["href"])
        if not m:
            continue
        horse_id = m.group(1)
        name = a.get_text(strip=True)
        if not name or horse_id in seen:
            continue
        tr = a.find_parent("tr")
        if tr is None:
            continue
        number = _horse_number_from_row(tr)
        if number is None:
            continue
        seen.add(horse_id)
        horses.append({"horse_number": number, "horse_id": horse_id, "horse_name": name})
    horses.sort(key=lambda h: h["horse_number"])
    return horses


def _horse_number_from_row(tr):
    cells = tr.find_all("td")
    # netkeiba出馬表は td[0]=枠番, td[1]=馬番 (クラス名 Umaban/Waku が付くことが多い)
    for td in cells:
        cls = " ".join(td.get("class", []))
        if "Umaban" in cls:
            t = td.get_text(strip=True)
            if t.isdigit():
                return int(t)
    digits = [td.get_text(strip=True) for td in cells[:3] if td.get_text(strip=True).isdigit()]
    if len(digits) >= 2:
        return int(digits[1])  # [枠番, 馬番, ...]
    if len(digits) == 1:
        return int(digits[0])
    return None


def parse_ped_sire(soup, horse_id=""):
    """血統表ページ (table.blood_table) から父名を返す。

    ⚠️ リンク出現順の先頭だけが父。2番目以降は父父・父父父 (rowspan構造) で
    母ではないので、先頭リンク以外を使ってはならない。
    """
    table = soup.find("table", class_="blood_table")
    if table is None:
        raise ParseError(f"ped {horse_id}: blood_table が見つからない")
    rows = table.find_all("tr")
    if not rows:
        raise ParseError(f"ped {horse_id}: blood_table が空")
    first_link = rows[0].find("a", href=True)
    if first_link is None:
        raise ParseError(f"ped {horse_id}: 父リンクが見つからない")
    name = first_link.get_text(strip=True)
    # 例 "キズナ 2010" のような付随テキストを除去 (和名部分のみ)
    name = re.sub(r"\s+", " ", name).split(" ")[0]
    if not name:
        raise ParseError(f"ped {horse_id}: 父名が空")
    return name


def parse_odds_json(data):
    """オッズAPI JSONから {馬番:int → 単勝オッズ:float} を返す。未発売なら {}。"""
    odds_map = {}
    if not isinstance(data, dict):
        return odds_map
    inner = data.get("data")
    if not isinstance(inner, dict):
        return odds_map
    win = inner.get("odds", {}).get("1", {})
    if not isinstance(win, dict):
        return odds_map
    for umaban, vals in win.items():
        try:
            num = int(umaban)
            val = float(vals[0]) if vals and vals[0] else 0.0
            if num > 0 and val > 0:
                odds_map[num] = val
        except (ValueError, IndexError, TypeError):
            continue
    return odds_map


def parse_odds_html(soup):
    """odds.sp.netkeiba.com のHTMLテーブルフォールバック。"""
    odds_map = {}
    table = soup.find("table", class_=re.compile(r"[Oo]dds"))
    if table is None:
        return odds_map
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        try:
            num = int(cells[0].get_text(strip=True))
            val = float(cells[-1].get_text(strip=True))
            if num > 0 and val > 0:
                odds_map[num] = val
        except ValueError:
            continue
    return odds_map


# ──────────────────────────────────────────────
# スクレイパー (ネットワーク層)
# ──────────────────────────────────────────────

class RaceListScraper(BaseScraper):
    def race_ids_for_date(self, date_str):
        """kaisai_date=YYYYMMDD のページからJRAレースIDを展開して返す。"""
        soup = self.get_soup(TOP_URL.format(date_str=date_str))
        return parse_race_ids(str(soup))


class ShutubaScraper(BaseScraper):
    def scrape(self, race_id):
        soup = self.get_soup(SHUTUBA_URL.format(race_id=race_id))
        return parse_shutuba(soup, race_id)


class PedScraper(BaseScraper):
    def sire_name(self, horse_id):
        soup = self.get_soup(PED_URL.format(horse_id=horse_id))
        return parse_ped_sire(soup, horse_id)


class OddsScraper(BaseScraper):
    def win_odds(self, race_id):
        """JSON API → HTMLフォールバックの順で単勝オッズを取る。未発売は {}。"""
        try:
            data = self.get_json(
                ODDS_API_URL, params={"race_id": race_id, "type": "1", "action": "update"})
            odds = parse_odds_json(data)
            if odds:
                return odds
        except ParseError as e:
            logger.warning("odds API failed for %s: %s", race_id, e)
        soup = self.get_soup(ODDS_SP_URL, params={"race_id": race_id, "type": "1"})
        return parse_odds_html(soup)
