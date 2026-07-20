# -*- coding: utf-8 -*-
"""build_weekly / update_odds のロジックユニットテスト (ネットワーク不要)。"""
from datetime import date

from engine.build_weekly import next_weekend
from engine.update_odds import update_picks

CANDIDATES = {
    "races": [
        {
            "race_id": "202604020601", "date": "2026-07-25", "venue_code": "04",
            "venue_name": "新潟", "race_number": 6, "post_time": "12:55",
            "candidates": [
                {"horse_number": 3, "horse_id": "2023101234", "horse_name": "サンプルホース"},
            ],
        },
        {
            "race_id": "202604020701", "date": "2026-07-26", "venue_code": "04",
            "venue_name": "新潟", "race_number": 7, "post_time": "13:25",
            "candidates": [
                {"horse_number": 5, "horse_id": "2023105678", "horse_name": "アシタノホース"},
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


class TestUpdatePicks:
    def test_new_band_entry_sets_entered_at_and_notifies(self):
        odds = {"202604020601": {3: 14.2}}
        picks, new = update_picks(CANDIDATES, [], odds, "T1")
        p = next(p for p in picks if p["race_id"] == "202604020601")
        assert p["in_band"] and p["odds_win"] == 14.2 and p["entered_band_at"] == "T1"
        assert len(new) == 1 and new[0]["horse_name"] == "サンプルホース"

    def test_already_in_band_not_renotified(self):
        prev = [{"race_id": "202604020601", "horse_number": 3, "odds_win": 12.0,
                 "in_band": True, "entered_band_at": "T0"}]
        picks, new = update_picks(CANDIDATES, prev, {"202604020601": {3: 14.2}}, "T1")
        p = next(p for p in picks if p["race_id"] == "202604020601")
        assert p["entered_band_at"] == "T0"
        assert new == []

    def test_out_of_band(self):
        picks, new = update_picks(CANDIDATES, [], {"202604020601": {3: 9.9}}, "T1")
        p = next(p for p in picks if p["race_id"] == "202604020601")
        assert not p["in_band"] and "entered_band_at" not in p
        assert new == []

    def test_missing_odds_is_out_of_band(self):
        # 出走取消はオッズ欠落で自然に帯外へ落ちる (特別処理不要)
        picks, _ = update_picks(CANDIDATES, [], {"202604020601": {}}, "T1")
        p = next(p for p in picks if p["race_id"] == "202604020601")
        assert p["odds_win"] is None and not p["in_band"]

    def test_other_day_race_preserved(self):
        # 土曜の更新で日曜レースの前回値を壊さない
        prev = [{"race_id": "202604020701", "horse_number": 5, "odds_win": 20.0,
                 "in_band": True, "entered_band_at": "T0"}]
        picks, new = update_picks(CANDIDATES, prev, {"202604020601": {3: 14.2}}, "T1")
        p = next(p for p in picks if p["race_id"] == "202604020701")
        assert p["odds_win"] == 20.0 and p["in_band"] and p["entered_band_at"] == "T0"
        assert len(new) == 1  # 新規は土曜の1頭のみ
