# -*- coding: utf-8 -*-
"""パーサテスト (docs/DESIGN.md §6.2)。

- 合成HTMLでの純ユニットテスト (CIで常時実行)
- network マーク付きテストで実HTMLを一度 tests/fixtures/ に保存
- 保存済み実フィクスチャがあればそれでもパーサを検証 (フィクスチャ無ければskip)
"""
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from engine.scraper import (
    ParseError,
    parse_odds_json,
    parse_ped_sire,
    parse_race_ids,
    parse_shutuba,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHUTUBA_FIXTURE = FIXTURES / "shutuba_202608030103.html"
PED_FIXTURE = FIXTURES / "ped_sample.html"
ODDS_FIXTURE = FIXTURES / "odds_sample.json"
TOP_FIXTURE = FIXTURES / "kaisai_top_sample.html"


def soup_of(html):
    return BeautifulSoup(html, "html.parser")


# ──────────────────────────────────────────────
# 合成HTMLユニットテスト (CI常時実行)
# ──────────────────────────────────────────────

class TestParseRaceIds:
    def test_expands_card_to_12_races(self):
        html = "<a href='shutuba.html?race_id=202608030104'>x</a>"
        ids = parse_race_ids(html)
        assert len(ids) == 12
        assert ids[0] == "202608030101"
        assert ids[-1] == "202608030112"

    def test_excludes_nar_venues(self):
        # 会場コード44 (NAR) は除外、01-10のみ
        html = "202644030104 202608030104"
        ids = parse_race_ids(html)
        assert all(rid[4:6] == "08" for rid in ids)

    def test_empty_page(self):
        assert parse_race_ids("<html></html>") == []


SHUTUBA_HTML = """
<html><body>
<div class="RaceName">3歳未勝利</div>
<div class="RaceData01">15:45発走 / 芝1800m (右 B) / 天候:晴</div>
<div class="RaceData02"><span>2回</span><span>福島</span><span>6日目</span></div>
<p>2026年4月25日</p>
<table class="Shutuba_Table">
<tr><th>枠</th><th>馬番</th><th>馬名</th></tr>
<tr><td class="Waku">1</td><td class="Umaban">1</td>
    <td><a href="https://db.netkeiba.com/horse/2023100001">アルファホース</a></td></tr>
<tr><td class="Waku">2</td><td class="Umaban">2</td>
    <td><a href="https://db.netkeiba.com/horse/2023100002">ベータホース</a></td></tr>
</table>
</body></html>
"""


class TestParseShutuba:
    def test_basic(self):
        info = parse_shutuba(soup_of(SHUTUBA_HTML), "202603020601")
        assert info["surface"] == "芝"
        assert info["distance"] == 1800
        assert info["post_time"] == "15:45"
        assert info["race_name"] == "3歳未勝利"
        assert info["venue_code"] == "03"
        assert info["venue_name"] == "福島"
        assert info["race_number"] == 1
        assert info["date"] == "2026-04-25"
        assert info["horses"] == [
            {"horse_number": 1, "horse_id": "2023100001", "horse_name": "アルファホース"},
            {"horse_number": 2, "horse_id": "2023100002", "horse_name": "ベータホース"},
        ]

    def test_dirt(self):
        html = SHUTUBA_HTML.replace("芝1800m", "ダ1200m")
        info = parse_shutuba(soup_of(html), "202603020601")
        assert info["surface"] == "ダート"
        assert info["distance"] == 1200

    def test_no_distance_raises(self):
        with pytest.raises(ParseError):
            parse_shutuba(soup_of("<html><body>empty</body></html>"), "202603020601")

    def test_no_horses_raises(self):
        html = "<div class='RaceData01'>15:45発走 / 芝1800m</div>"
        with pytest.raises(ParseError):
            parse_shutuba(soup_of(html), "202603020601")


# rowspan構造の血統表: リンク出現順は 父 → 父父 → 父父父 (2番目は母ではない!)
PED_HTML = """
<table class="blood_table">
<tr><td rowspan="8"><a href="/horse/000a010f79/">キズナ</a></td>
    <td rowspan="4"><a href="/horse/000a010842/">ディープインパクト</a></td>
    <td rowspan="2"><a href="/horse/000a000082/">サンデーサイレンス</a></td></tr>
<tr><td></td></tr>
<tr><td rowspan="2"><a href="/horse/000a008b12/">キャットクイル</a></td></tr>
<tr><td></td></tr>
<tr><td rowspan="4"><a href="/horse/000a011836/">母馬サンプル</a></td></tr>
</table>
"""


class TestParsePedSire:
    def test_first_link_is_sire_not_second(self):
        # 先頭リンクのみが父。2番目 (ディープインパクト=父父) を返したらバグ
        assert parse_ped_sire(soup_of(PED_HTML)) == "キズナ"

    def test_strips_trailing_text(self):
        html = PED_HTML.replace(">キズナ<", ">キズナ 2010<")
        assert parse_ped_sire(soup_of(html)) == "キズナ"

    def test_missing_table_raises(self):
        with pytest.raises(ParseError):
            parse_ped_sire(soup_of("<html></html>"), "x")


class TestParseOddsJson:
    def test_basic(self):
        data = {"data": {"odds": {"1": {"01": ["7.2", "", "3"], "02": ["14.5", "", "6"]}}}}
        assert parse_odds_json(data) == {1: 7.2, 2: 14.5}

    def test_unreleased_returns_empty(self):
        assert parse_odds_json({"data": {"odds": {"1": {}}}}) == {}
        assert parse_odds_json({}) == {}
        assert parse_odds_json(None) == {}

    def test_invalid_values_skipped(self):
        data = {"data": {"odds": {"1": {"01": ["**", "", ""], "02": ["10.0", "", ""]}}}}
        assert parse_odds_json(data) == {2: 10.0}


# ──────────────────────────────────────────────
# 実HTMLフィクスチャの取得 (networkマーク・ローカル1回のみ)
# ──────────────────────────────────────────────

@pytest.mark.network
class TestFetchFixtures:
    """実HTMLを一度取得して tests/fixtures/ に保存する (CIでは実行しない)。"""

    def test_fetch_shutuba(self):
        if SHUTUBA_FIXTURE.exists():
            pytest.skip("取得済み")
        from engine.scraper import ShutubaScraper
        s = ShutubaScraper()
        soup = s.get_soup(
            "https://race.netkeiba.com/race/shutuba.html?race_id=202608030103")
        SHUTUBA_FIXTURE.write_text(str(soup))

    def test_fetch_ped(self):
        if PED_FIXTURE.exists():
            pytest.skip("取得済み")
        from engine.scraper import PedScraper
        s = PedScraper()
        soup = s.get_soup("https://db.netkeiba.com/horse/ped/2020103575/")
        PED_FIXTURE.write_text(str(soup))

    def test_fetch_odds(self):
        if ODDS_FIXTURE.exists():
            pytest.skip("取得済み")
        from engine.scraper import OddsScraper
        s = OddsScraper()
        data = s.get_json(
            "https://race.netkeiba.com/api/api_get_jra_odds.html",
            params={"race_id": "202608030103", "type": "1", "action": "update"})
        ODDS_FIXTURE.write_text(json.dumps(data, ensure_ascii=False))

    def test_fetch_kaisai_top(self):
        if TOP_FIXTURE.exists():
            pytest.skip("取得済み")
        from engine.scraper import RaceListScraper
        s = RaceListScraper()
        soup = s.get_soup("https://race.netkeiba.com/top/?kaisai_date=20260425")
        TOP_FIXTURE.write_text(str(soup))


# ──────────────────────────────────────────────
# 実フィクスチャでのパーサ検証 (フィクスチャがあれば実行)
# ──────────────────────────────────────────────

@pytest.mark.skipif(not SHUTUBA_FIXTURE.exists(), reason="実フィクスチャ未取得")
def test_real_shutuba_fixture():
    info = parse_shutuba(soup_of(SHUTUBA_FIXTURE.read_text()), "202608030103")
    assert info["surface"] == "芝"
    assert info["distance"] == 1800
    assert info["venue_code"] == "08"
    assert info["venue_name"] == "京都"
    # E2Eフィクスチャで13番の父はロジャーバローズ → 13番が存在すること
    numbers = {h["horse_number"] for h in info["horses"]}
    assert 13 in numbers


@pytest.mark.skipif(not PED_FIXTURE.exists(), reason="実フィクスチャ未取得")
def test_real_ped_fixture():
    # horse_id 2020103575 の父は sire_cache 上キタサンブラック
    assert parse_ped_sire(soup_of(PED_FIXTURE.read_text())) == "キタサンブラック"


@pytest.mark.skipif(not ODDS_FIXTURE.exists(), reason="実フィクスチャ未取得")
def test_real_odds_fixture():
    data = json.loads(ODDS_FIXTURE.read_text())
    odds = parse_odds_json(data)
    assert isinstance(odds, dict)  # 過去レースは空 {} の場合もある


@pytest.mark.skipif(not TOP_FIXTURE.exists(), reason="実フィクスチャ未取得")
def test_real_kaisai_top_fixture():
    ids = parse_race_ids(TOP_FIXTURE.read_text())
    assert len(ids) >= 12
    assert all(len(rid) == 12 and rid[4:6] in
               {f"{i:02d}" for i in range(1, 11)} for rid in ids)


DB_RACE_HTML = """
<html><body>
<div class="data_intro">
<h1>3歳以上1勝クラス</h1>
<p><span>芝右1600m / 天候 : 晴 / 芝 : 良 / 発走 : 15:35</span></p>
<p class="smalltxt">2026年7月18日 2回新潟2日目 3歳以上1勝クラス</p>
</div>
<table class="race_table_01">
<tr><th>着順</th><th>枠番</th><th>馬番</th><th>馬名</th><th>性齢</th><th>斤量</th>
<th>騎手</th><th>タイム</th><th>着差</th><th>単勝</th><th>人気</th></tr>
<tr><td>1</td><td>3</td><td>5</td><td><a href="/horse/2023100001/">アルファテスト</a></td>
<td>牡3</td><td>56</td><td>某騎手</td><td>1:33.5</td><td></td><td>12.3</td><td>5</td></tr>
<tr><td>2</td><td>1</td><td>2</td><td><a href="/horse/2023100002/">ベータテスト</a></td>
<td>牝3</td><td>54</td><td>某騎手</td><td>1:33.7</td><td>1.1/4</td><td>3.4</td><td>1</td></tr>
<tr><td>中</td><td>5</td><td>9</td><td><a href="/horse/2023100003/">ガンマテスト</a></td>
<td>牡3</td><td>56</td><td>某騎手</td><td></td><td></td><td>---</td><td></td></tr>
</table>
</body></html>
"""

DB_RACE_JUMP_HTML = """
<html><body>
<div class="data_intro">
<h1>障害3歳以上未勝利</h1>
<p><span>障芝3350m / 天候 : 晴 / 芝 : 良 / 発走 : 09:50</span></p>
</div>
<table>
<tr><th>着順</th><th>枠番</th><th>馬番</th><th>馬名</th><th>単勝</th></tr>
<tr><td>1</td><td>1</td><td>1</td><td><a href="/horse/2022100009/">ジャンプテスト</a></td>
<td>2.0</td></tr>
</table>
</body></html>
"""


class TestParseDbRace:
    def test_basic(self):
        from engine.scraper import parse_db_race
        info = parse_db_race(soup_of(DB_RACE_HTML), "202604020211")
        assert info["surface"] == "芝"
        assert info["distance"] == 1600
        assert info["post_time"] == "15:35"
        assert info["race_name"] == "3歳以上1勝クラス"
        assert info["date"] == "2026-07-18"
        assert info["venue_code"] == "04"
        assert info["venue_name"] == "新潟"
        assert info["race_number"] == 11
        # 馬番順ソート・馬番列(枠番と取り違えない)・horse_id抽出
        assert [h["horse_number"] for h in info["horses"]] == [2, 5, 9]
        by_num = {h["horse_number"]: h for h in info["horses"]}
        assert by_num[5]["horse_id"] == "2023100001"
        assert by_num[5]["horse_name"] == "アルファテスト"
        # 確定単勝オッズ。"---" (取消) はスキップされる
        assert info["win_odds"] == {5: 12.3, 2: 3.4}

    def test_jump_race_is_not_turf(self):
        # 障芝を芝と誤認すると障害戦が候補になり得るので回帰テストで固定
        from engine.scraper import parse_db_race
        info = parse_db_race(soup_of(DB_RACE_JUMP_HTML), "202604020201")
        assert info["surface"] == "障害"

    def test_empty_shell_raises(self):
        from engine.scraper import ParseError, parse_db_race
        with pytest.raises(ParseError):
            parse_db_race(soup_of("<html><body>データがありません</body></html>"), "202604020201")


class TestParseDbRaceList:
    def test_extracts_ids_from_race_links(self):
        from engine.scraper import parse_db_race_list
        html = """
        <a href="/race/202603030101/">福島1R</a>
        <a href="/race/202603030102/">福島2R</a>
        <a href="/race/202644030101/">NAR</a>
        <a href="/horse/2023100001/">馬ページは無視</a>
        """
        assert parse_db_race_list(html) == ["202603030101", "202603030102"]

    def test_empty_for_future_date_shell(self):
        from engine.scraper import parse_db_race_list
        assert parse_db_race_list("<html><body>該当なし</body></html>") == []
