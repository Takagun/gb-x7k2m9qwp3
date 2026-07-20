# -*- coding: utf-8 -*-
"""build_weekly / update_odds / form_resolver のロジックユニットテスト (ネットワーク不要)。"""
import json
from datetime import date

from engine.build_weekly import candidate_form_fields, next_weekend
from engine.form_resolver import FormResolver
from engine.update_odds import fetch_day_weights, races_needing_weights, update_picks

CANDIDATES = {
    "races": [
        {
            "race_id": "202604020601", "date": "2026-07-25", "venue_code": "04",
            "venue_name": "新潟", "race_number": 6, "post_time": "12:55",
            "distance": 1800,
            "candidates": [
                {"horse_number": 3, "horse_id": "2023101234", "horse_name": "サンプルホース",
                 "prev_distance": 2000, "days_since_last": 28, "prev_weight": 466,
                 "excluded_reason": [], "form_missing": False},
                {"horse_number": 7, "horse_id": "2023109999", "horse_name": "コガラホース",
                 "prev_distance": 1800, "days_since_last": 30, "prev_weight": 438,
                 "excluded_reason": ["small"], "form_missing": False},
            ],
        },
        {
            "race_id": "202604020701", "date": "2026-07-26", "venue_code": "04",
            "venue_name": "新潟", "race_number": 7, "post_time": "13:25",
            "distance": 1800,
            "candidates": [
                {"horse_number": 5, "horse_id": "2023105678", "horse_name": "アシタノホース",
                 "prev_distance": 1800, "days_since_last": 21, "prev_weight": 480,
                 "excluded_reason": [], "form_missing": False},
            ],
        },
    ]
}


class TestNextWeekend:
    def test_monday(self):
        assert next_weekend(date(2026, 7, 20)) == [date(2026, 7, 25), date(2026, 7, 26)]

    def test_friday(self):
        assert next_weekend(date(2026, 7, 24)) == [date(2026, 7, 25), date(2026, 7, 26)]

    def test_saturday_is_kept(self):
        # 土曜実行はその週末を対象にする
        assert next_weekend(date(2026, 7, 25)) == [date(2026, 7, 25), date(2026, 7, 26)]

    def test_sunday_rolls_to_next(self):
        assert next_weekend(date(2026, 7, 26)) == [date(2026, 8, 1), date(2026, 8, 2)]


class TestCandidateFormFields:
    def test_normal(self):
        form = {"last_date": "2026-06-27", "last_distance": 2000,
                "last_weight": 466, "form_missing": False}
        f = candidate_form_fields(form, "2026-07-25", 1800)
        assert f == {"prev_distance": 2000, "days_since_last": 28, "prev_weight": 466,
                     "excluded_reason": [], "form_missing": False}

    def test_layoff_and_extend(self):
        form = {"last_date": "2026-03-01", "last_distance": 1400,
                "last_weight": 440, "form_missing": False}
        f = candidate_form_fields(form, "2026-07-25", 1800)
        assert f["days_since_last"] == 146
        assert f["excluded_reason"] == ["long_layoff", "small", "extend"]

    def test_missing_form_not_excluded(self):
        # 初出走・取得失敗は除外しない (DESIGN §2)
        form = {"last_date": None, "last_distance": None,
                "last_weight": None, "form_missing": True}
        f = candidate_form_fields(form, "2026-07-25", 1800)
        assert f["excluded_reason"] == [] and f["form_missing"]


class TestUpdatePicks:
    def test_core_entry_sets_entered_at_and_notifies(self):
        odds = {"202604020601": {3: 14.2, 7: 15.0}}
        picks, new = update_picks(CANDIDATES, [], odds, {}, "T1")
        p = next(p for p in picks if p["horse_number"] == 3)
        assert p["tier"] == "core" and p["odds_win"] == 14.2
        assert p["entered_band_at"] == "T1"
        assert len(new) == 1 and new[0]["horse_name"] == "サンプルホース"
        assert new[0]["tier"] == "core"

    def test_watch_tier(self):
        picks, new = update_picks(CANDIDATES, [], {"202604020601": {3: 30.0}}, {}, "T1")
        p = next(p for p in picks if p["horse_number"] == 3)
        assert p["tier"] == "watch"
        assert new[0]["tier"] == "watch"

    def test_excluded_horse_never_gets_tier(self):
        # 7番は前走馬体重438kg (small) — 帯内オッズでも tier=None・通知なし
        odds = {"202604020601": {3: 9.0, 7: 15.0}}
        picks, new = update_picks(CANDIDATES, [], odds, {}, "T1")
        p = next(p for p in picks if p["horse_number"] == 7)
        assert p["tier"] is None and p["excluded_reason"] == ["small"]
        assert new == []

    def test_day_weight_overrides_prev_weight(self):
        # 当日馬体重444kg発表 → smallが外れて core に入る
        odds = {"202604020601": {7: 15.0}}
        weights = {"202604020601": {7: 444}}
        picks, new = update_picks(CANDIDATES, [], odds, weights, "T1")
        p = next(p for p in picks if p["horse_number"] == 7)
        assert p["tier"] == "core" and p["excluded_reason"] == []
        assert p["day_weight"] == 444
        assert len(new) == 1

    def test_day_weight_can_add_exclusion(self):
        # 前走466kg → 当日438kgに減 → small で除外に転じる
        odds = {"202604020601": {3: 14.2}}
        weights = {"202604020601": {3: 438}}
        picks, new = update_picks(CANDIDATES, [], odds, weights, "T1")
        p = next(p for p in picks if p["horse_number"] == 3)
        assert p["tier"] is None and p["excluded_reason"] == ["small"]
        assert new == []

    def test_day_weight_persists_from_prev_picks(self):
        # 前回取得済みの当日馬体重は weights 未取得でも引き継ぐ
        prev = [{"race_id": "202604020601", "horse_number": 7, "odds_win": 15.0,
                 "tier": "core", "day_weight": 444, "entered_band_at": "T0",
                 "excluded_reason": [], "form_missing": False}]
        picks, new = update_picks(CANDIDATES, prev, {"202604020601": {7: 16.0}}, {}, "T1")
        p = next(p for p in picks if p["horse_number"] == 7)
        assert p["day_weight"] == 444 and p["tier"] == "core"
        assert p["entered_band_at"] == "T0" and new == []

    def test_already_in_band_not_renotified(self):
        prev = [{"race_id": "202604020601", "horse_number": 3, "odds_win": 12.0,
                 "tier": "core", "entered_band_at": "T0"}]
        picks, new = update_picks(CANDIDATES, prev, {"202604020601": {3: 14.2}}, {}, "T1")
        p = next(p for p in picks if p["horse_number"] == 3)
        assert p["entered_band_at"] == "T0"
        assert new == []

    def test_out_of_band(self):
        picks, new = update_picks(CANDIDATES, [], {"202604020601": {3: 9.9}}, {}, "T1")
        p = next(p for p in picks if p["horse_number"] == 3)
        assert p["tier"] is None and "entered_band_at" not in p
        assert new == []

    def test_missing_odds_is_out_of_band(self):
        # 出走取消はオッズ欠落で自然に帯外へ落ちる (特別処理不要)
        picks, _ = update_picks(CANDIDATES, [], {"202604020601": {}}, {}, "T1")
        p = next(p for p in picks if p["horse_number"] == 3)
        assert p["odds_win"] is None and p["tier"] is None

    def test_other_day_race_preserved(self):
        # 土曜の更新で日曜レースの前回値を壊さない
        prev = [{"race_id": "202604020701", "horse_number": 5, "odds_win": 20.0,
                 "tier": "core", "entered_band_at": "T0"}]
        picks, new = update_picks(CANDIDATES, prev, {"202604020601": {3: 14.2}}, {}, "T1")
        p = next(p for p in picks if p["race_id"] == "202604020701")
        assert p["odds_win"] == 20.0 and p["tier"] == "core"
        assert p["entered_band_at"] == "T0"
        assert len(new) == 1  # 新規は土曜の1頭のみ


class TestRacesNeedingWeights:
    def test_all_needed_initially(self):
        races = CANDIDATES["races"][:1]
        assert races_needing_weights(races, []) == races

    def test_skipped_when_all_have_day_weight(self):
        races = CANDIDATES["races"][:1]
        prev = [
            {"race_id": "202604020601", "horse_number": 3, "day_weight": 470},
            {"race_id": "202604020601", "horse_number": 7, "day_weight": 444},
        ]
        assert races_needing_weights(races, prev) == []

    def test_partial_weights_still_fetched(self):
        races = CANDIDATES["races"][:1]
        prev = [{"race_id": "202604020601", "horse_number": 3, "day_weight": 470}]
        assert races_needing_weights(races, prev) == races


class FakeShutuba:
    def __init__(self, horses=None, fail=False):
        self.horses = horses or []
        self.fail = fail
        self.calls = []

    def scrape(self, race_id):
        from engine.scraper import ParseError
        self.calls.append(race_id)
        if self.fail:
            raise ParseError("boom")
        return {"horses": self.horses}


class TestFetchDayWeights:
    def test_collects_weights(self):
        fake = FakeShutuba(horses=[
            {"horse_number": 3, "horse_weight": 470},
            {"horse_number": 7, "horse_weight": None},  # 未発表はスキップ
        ])
        w = fetch_day_weights(CANDIDATES["races"][:1], fake)
        assert w == {"202604020601": {3: 470}}

    def test_failure_is_not_fatal(self):
        # 当日馬体重が取れなくても前走値の仮判定で続行する
        w = fetch_day_weights(CANDIDATES["races"][:1], FakeShutuba(fail=True))
        assert w == {}


class FakeFormScraper:
    def __init__(self, form=None, fail=False):
        self.form_data = form or {"last_date": "2026-06-27",
                                  "last_distance": 2000, "last_weight": 466}
        self.fail = fail
        self.calls = []

    def form(self, horse_id):
        self.calls.append(horse_id)
        if self.fail:
            raise RuntimeError("boom")
        return dict(self.form_data)


class TestFormResolver:
    def test_scrape_then_cache(self, tmp_path):
        path = tmp_path / "form_cache.json"
        scraper = FakeFormScraper()
        r = FormResolver(form_scraper=scraper, cache_path=path, weekend_key="2026-07-25")
        f1 = r.resolve("2023101234")
        assert f1["last_distance"] == 2000 and not f1["form_missing"]
        r.resolve("2023101234")
        assert scraper.calls == ["2023101234"]  # 2回目はキャッシュ
        assert r.save()
        # 同一週末なら再ロードしてもキャッシュ有効
        r2 = FormResolver(form_scraper=scraper, cache_path=path, weekend_key="2026-07-25")
        r2.resolve("2023101234")
        assert scraper.calls == ["2023101234"]

    def test_cache_discarded_on_new_weekend(self, tmp_path):
        path = tmp_path / "form_cache.json"
        path.write_text(json.dumps({
            "weekend": "2026-07-18",
            "horses": {"2023101234": {"last_date": "2026-01-01",
                                      "last_distance": 1200, "last_weight": 400}},
        }))
        scraper = FakeFormScraper()
        r = FormResolver(form_scraper=scraper, cache_path=path, weekend_key="2026-07-25")
        f = r.resolve("2023101234")
        assert f["last_distance"] == 2000  # 古い週末のキャッシュは破棄され再取得
        assert scraper.calls == ["2023101234"]

    def test_failure_returns_missing_and_not_cached(self, tmp_path):
        path = tmp_path / "form_cache.json"
        scraper = FakeFormScraper(fail=True)
        r = FormResolver(form_scraper=scraper, cache_path=path, weekend_key="2026-07-25")
        f = r.resolve("2023101234")
        assert f["form_missing"] and f["last_date"] is None
        # 失敗はキャッシュされず次回リトライ
        scraper.fail = False
        f2 = r.resolve("2023101234")
        assert not f2["form_missing"]
        assert scraper.calls == ["2023101234", "2023101234"]

    def test_no_scraper_returns_missing(self, tmp_path):
        r = FormResolver(cache_path=tmp_path / "x.json", weekend_key="2026-07-25")
        assert r.resolve("2023101234")["form_missing"]
