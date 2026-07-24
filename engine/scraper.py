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
# 対象日のレース一覧断片 (サーバレンダリング)。トップページ本体はJSシェルで
# 対象日と無関係な注目レースIDしか含まないため、未来日はこちらを使う
RACE_LIST_SUB_URL = "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
SHUTUBA_URL = "https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
PED_URL = "https://db.netkeiba.com/horse/ped/{horse_id}/"
# DESIGN §4.4 は /horse/{id}/ だが、実際は戦績テーブル (db_h_race_results) が
# プロフィールページの静的HTMLに含まれないため、戦績専用ページを使う
HORSE_RESULT_URL = "https://db.netkeiba.com/horse/result/{horse_id}/"
ODDS_API_URL = "https://race.netkeiba.com/api/api_get_jra_odds.html"
ODDS_SP_URL = "https://odds.sp.netkeiba.com/"
# 過去日付のレースは race.netkeiba.com がJSレンダリングの空シェルを返すため、
# サーバレンダリングされる db.netkeiba.com のレースページへフォールバックする
DB_RACE_URL = "https://db.netkeiba.com/race/{race_id}/"
DB_RACE_LIST_URL = "https://db.netkeiba.com/race/list/{date_str}/"

# JRA会場コード (NAR=地方は30以上なので除外)
JRA_VENUE_CODES = {f"{i:02d}" for i in range(1, 11)}
VENUE_NAMES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}

RACE_ID_RE = re.compile(r"\b(20[2-9]\d{9})\b")
POST_TIME_RE = re.compile(r"(\d{1,2}:\d{2})発走")
# 障芝/障ダ を先にマッチさせる (「障芝3110m」を芝と誤認しない)
SURFACE_DIST_RE = re.compile(r"(障芝|障ダ|障|芝|ダ)(\d{3,4})m")
# dbページは "芝右1600m" "ダ1800m" "障芝3350m" のように回り・内外が挟まる。
# 障芝を先に照合しないと障害戦が芝扱いになるので順序を変えないこと。
DB_SURFACE_DIST_RE = re.compile(r"(障芝|障ダ|芝|ダ)(?:右|左|直線)?\s*(?:外|内)?\s*(\d{3,4})m")
DB_POST_TIME_RE = re.compile(r"発走\s*[::]\s*(\d{1,2}:\d{2})")
DB_HORSE_LINK_RE = re.compile(r"/horse/(\d{10})")
KAISAI_RE = re.compile(r"(\d+)回\s*(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)\s*(\d+)日目")
HORSE_LINK_RE = re.compile(r"db\.netkeiba\.com/horse/(\d{10})")
WEIGHT_RE = re.compile(r"^(\d{3,4})(?:\(([+-]?\d+)\))?$")  # 例: 472(+4) / 472
FORM_DATE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
FORM_DIST_RE = re.compile(r"^(芝|ダ|障)(\d{3,4})$")  # 戦績テーブルの距離セル 例: 芝1800


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

    ⚠️ トップページはJS描画で、静的HTMLには対象日と無関係な注目レースIDしか
    無いことがある。この関数の結果は必ず出馬表側の開催日と照合すること
    (build_weekly が info["date"] で検証する)。
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
    surface = {"芝": "芝", "ダ": "ダート"}.get(m.group(1), "障害")
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
        horses.append({
            "horse_number": number,
            "horse_id": horse_id,
            "horse_name": name,
            "horse_weight": _horse_weight_from_row(tr),
        })
    horses.sort(key=lambda h: h["horse_number"])
    return horses


def _horse_weight_from_row(tr):
    """出馬表行の当日馬体重 (td.Weight, 例 '472(+4)')。未発表・計不は None。"""
    for td in tr.find_all("td"):
        if "Weight" in " ".join(td.get("class", [])):
            m = WEIGHT_RE.match(td.get_text(strip=True))
            return int(m.group(1)) if m else None
    return None


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


def parse_race_list_sub(html_text):
    """race_list_sub.html (日別レース一覧の断片) から対象日の実在レースIDを返す。

    サーバレンダリングされ、race_id= リンクに対象日の全レースが列挙される。
    一覧に載っているものが施行予定の全レースなので R01-12 への展開はしない。
    """
    ids = set()
    for m in re.finditer(r"race_id=(20[2-9]\d{9})", html_text):
        race_id = m.group(1)
        if race_id[4:6] in JRA_VENUE_CODES:
            ids.add(race_id)
    return sorted(ids)


def parse_db_race_list(html_text):
    """dbの日別レース一覧ページから実在レースIDを返す (過去日付用)。

    /race/{race_id}/ リンクのみ拾う。R01-12への展開はしない —
    一覧に載っているものが施行された全レースなので、そのまま使う。
    """
    ids = set()
    for m in re.finditer(r"/race/(20[2-9]\d{9})/", html_text):
        race_id = m.group(1)
        if race_id[4:6] in JRA_VENUE_CODES:
            ids.add(race_id)
    return sorted(ids)


def parse_db_race(soup, race_id):
    """db.netkeiba.com のレースページから parse_shutuba 互換の情報を抽出する。

    過去に施行済みのレース用フォールバック。結果テーブルに確定単勝オッズも
    載っているため、追加キー win_odds ({馬番:int → 単勝:float}) も返す。
    """
    text = soup.get_text(" ", strip=False)

    m = DB_SURFACE_DIST_RE.search(text)
    if not m:
        raise ParseError(f"{race_id}: 馬場・距離が抽出できない (dbページ)")
    kind = m.group(1)
    if kind == "芝":
        surface = "芝"
    elif kind == "ダ":
        surface = "ダート"
    else:
        surface = "障害"
    distance = int(m.group(2))

    post_time = None
    m = DB_POST_TIME_RE.search(text)
    if m:
        h, mi = m.group(1).split(":")
        post_time = f"{int(h):02d}:{mi}"

    race_name = None
    intro = soup.find(class_="data_intro")
    h1 = intro.find("h1") if intro else None
    if h1 is None:
        h1s = soup.find_all("h1")
        h1 = h1s[-1] if h1s else None
    if h1 is not None:
        race_name = h1.get_text(strip=True)

    date_str = None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(soup))
    if m:
        date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    horses, win_odds = _parse_db_race_table(soup)
    if not horses:
        raise ParseError(f"{race_id}: 出走馬が1頭も抽出できない (dbページ)")

    venue_code = race_id[4:6]
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
        "win_odds": win_odds,
    }


def _parse_db_race_table(soup):
    """dbレースページの結果テーブルから (horses, win_odds) を取る。

    ヘッダ行の「馬番」「馬名」「単勝」の列位置で引く (列構成の揺れに強くする)。
    """
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if header_row is None:
            continue
        headers = [c.get_text(strip=True) for c in header_row.find_all(["th", "td"])]
        if "馬番" not in headers or "馬名" not in headers:
            continue
        i_umaban = headers.index("馬番")
        i_name = headers.index("馬名")
        i_tansho = headers.index("単勝") if "単勝" in headers else None
        i_weight = headers.index("馬体重") if "馬体重" in headers else None
        i_finish = headers.index("着順") if "着順" in headers else None

        horses = []
        win_odds = {}
        seen = set()
        for row in header_row.find_next_siblings("tr"):
            cells = row.find_all("td")
            if len(cells) <= max(i_umaban, i_name):
                continue
            num_text = cells[i_umaban].get_text(strip=True)
            if not num_text.isdigit():
                continue
            number = int(num_text)
            link = cells[i_name].find("a", href=True)
            if link is None:
                continue
            m = DB_HORSE_LINK_RE.search(link["href"])
            if m is None:
                continue
            horse_id = m.group(1)
            name = link.get_text(strip=True)
            if not name or horse_id in seen:
                continue
            seen.add(horse_id)
            weight = None
            if i_weight is not None and len(cells) > i_weight:
                mw = WEIGHT_RE.match(cells[i_weight].get_text(strip=True))
                if mw:
                    weight = int(mw.group(1))
            finish = None
            if i_finish is not None and len(cells) > i_finish:
                ftext = cells[i_finish].get_text(strip=True)
                finish = int(ftext) if ftext.isdigit() else None  # 取/除/中 は None
            horses.append({"horse_number": number, "horse_id": horse_id,
                           "horse_name": name, "horse_weight": weight,
                           "finish_position": finish})
            if i_tansho is not None and len(cells) > i_tansho:
                try:
                    val = float(cells[i_tansho].get_text(strip=True))
                    if val > 0:
                        win_odds[number] = val
                except ValueError:
                    pass  # 取消・除外は "---" 等になる
        if horses:
            horses.sort(key=lambda h: h["horse_number"])
            return horses, win_odds
    return [], {}


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


def parse_horse_form(soup, horse_id=""):
    """馬ページの戦績テーブル先頭行 (=直近出走) から前走情報を返す (DESIGN.md §4.4)。

    返り値: {last_date: "YYYY-MM-DD"|None, last_distance: int|None, last_weight: int|None}
    戦績テーブルは日付降順。未出走 (データ行なし) は全て None (除外判定しない)。
    テーブル自体が見つからない場合はページ構造変化の疑いなので ParseError。
    """
    table = soup.find("table", class_=re.compile(r"db_h_race_results"))
    if table is None:
        # 未出走馬はテーブルごと無いことがある。「出走レースはありません」等の
        # 文言があれば未出走として扱い、無ければ構造変化として fail させる。
        if "出走" in soup.get_text():
            return {"last_date": None, "last_distance": None, "last_weight": None}
        raise ParseError(f"horse {horse_id}: 戦績テーブルが見つからない")

    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue  # ヘッダ行
        last_date = last_distance = last_weight = None
        for text in cells:
            if last_date is None:
                m = FORM_DATE_RE.match(text)
                if m:
                    last_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    continue
            if last_distance is None:
                m = FORM_DIST_RE.match(text)
                if m:
                    last_distance = int(m.group(2))
                    continue
            if last_weight is None and last_date is not None:
                # 馬体重セルは日付より後。斤量 (例 57.0) と混同しないよう整数3-4桁のみ
                m = WEIGHT_RE.match(text)
                if m and 300 <= int(m.group(1)) <= 700:
                    last_weight = int(m.group(1))
        if last_date is None:
            continue  # 日付が無い行はデータ行でない
        return {
            "last_date": last_date,
            "last_distance": last_distance,
            "last_weight": last_weight,
        }
    # データ行ゼロ = 未出走
    return {"last_date": None, "last_distance": None, "last_weight": None}


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
        """date_str=YYYYMMDD のJRAレースIDを返す。

        1. db.netkeiba.com の日別一覧 (施行済み〜当日は実在IDが確定で取れる)
        2. 空なら race_list_sub.html (サーバレンダリングの日別一覧断片)。
           出馬表公開済みの未来日はここで実在IDが確定で取れる。
        3. それも空なら race.netkeiba.com トップのシードIDをR01-12へ展開 (最後の保険)。
           トップはJSシェルで別週・対象日以外のIDが混ざるため、
           呼び出し側 (build_weekly) で出馬表の開催日と照合すること。
        """
        try:
            soup = self.get_soup(DB_RACE_LIST_URL.format(date_str=date_str))
            ids = parse_db_race_list(str(soup))
            if ids:
                return ids
        except ParseError as e:
            logger.warning("db race list failed for %s: %s", date_str, e)
        try:
            soup = self.get_soup(RACE_LIST_SUB_URL.format(date_str=date_str))
            ids = parse_race_list_sub(str(soup))
            if ids:
                return ids
        except ParseError as e:
            logger.warning("race_list_sub failed for %s: %s", date_str, e)
        soup = self.get_soup(TOP_URL.format(date_str=date_str))
        return parse_race_ids(str(soup))


class ShutubaScraper(BaseScraper):
    def scrape(self, race_id):
        try:
            soup = self.get_soup(SHUTUBA_URL.format(race_id=race_id))
            return parse_shutuba(soup, race_id)
        except ParseError:
            # 施行済みレースはshutubaがJS空シェルになる → dbページへフォールバック。
            # 未来の実在しないレース番号はdb側もParseErrorになり従来どおりskipされる。
            soup = self.get_soup(DB_RACE_URL.format(race_id=race_id))
            return parse_db_race(soup, race_id)


class DbRaceScraper(BaseScraper):
    def scrape(self, race_id):
        """施行済みレースの確定結果 (着順・確定単勝オッズ込み) をdbページから取る。"""
        soup = self.get_soup(DB_RACE_URL.format(race_id=race_id))
        return parse_db_race(soup, race_id)


class PedScraper(BaseScraper):
    def sire_name(self, horse_id):
        soup = self.get_soup(PED_URL.format(horse_id=horse_id))
        return parse_ped_sire(soup, horse_id)


class HorseFormScraper(BaseScraper):
    def form(self, horse_id):
        """馬の戦績ページから直近出走の {last_date, last_distance, last_weight} を返す。"""
        soup = self.get_soup(HORSE_RESULT_URL.format(horse_id=horse_id))
        return parse_horse_form(soup, horse_id)


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
        odds = parse_odds_html(soup)
        if odds:
            return odds
        # 施行済みレースはAPI/spとも空になるため、dbページの確定単勝へフォールバック。
        # 発売前レースはdbページが存在せずParseError → 従来どおり {} (未発売扱い)。
        try:
            db_soup = self.get_soup(DB_RACE_URL.format(race_id=race_id))
            return parse_db_race(db_soup, race_id).get("win_odds", {})
        except ParseError:
            return {}
