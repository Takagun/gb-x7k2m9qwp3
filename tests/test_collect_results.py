# -*- coding: utf-8 -*-
"""collect_results のロジックユニットテスト (ネットワーク不要)。"""
from engine.collect_results import collect
from engine.scraper import ParseError

CANDIDATES = {
    "races": [
        {
            "race_id": "202604020509", "date": "2026-07-18", "venue_name": "新潟",
            "race_number": 9, "distance": 1800,
            "candidates": [
                {"horse_number": 7, "horse_name": "サンプルホース",
                 "excluded_reason": []},
                {"horse_number": 12, "horse_name": "オビソトホース",
                 "excluded_reason": []},
            ],
        },
        {
            "race_id": "202604020609", "date": "2026-07-26", "venue_name": "新潟",
            "race_number": 9, "distance": 1800,
            "candidates": [
                {"horse_number": 1, "horse_name": "ミライホース",
                 "excluded_reason": []},
            ],
        },
    ]
}
PICKS = {
    "picks": [
        {"race_id": "202604020509", "horse_number": 7, "odds_win": 14.2,
         "tier": "core", "excluded_reason": []},
        {"race_id": "202604020509", "horse_number": 12, "odds_win": 88.5,
         "tier": None, "excluded_reason": []},
    ]
}
TODAY = "2026-07-20"


class FakeDbRace:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def scrape(self, race_id):
        self.calls.append(race_id)
        if self.fail:
            raise ParseError("boom")
        return {
            "horses": [
                {"horse_number": 7, "finish_position": 1},
                {"horse_number": 12, "finish_position": None},  # 取消
            ],
            "win_odds": {7: 15.1},
        }


class TestCollect:
    def test_collects_finished_races_only(self):
        scraper = FakeDbRace()
        new, errors = collect(CANDIDATES, PICKS, {"entries": []}, scraper, TODAY)
        # 7/26 (未施行) は対象外
        assert scraper.calls == ["202604020509"]
        assert errors == 0
        assert len(new) == 2
        e7 = next(e for e in new if e["horse_number"] == 7)
        assert e7["tier"] == "core" and e7["odds_app"] == 14.2
        assert e7["odds_final"] == 15.1 and e7["finish_position"] == 1
        e12 = next(e for e in new if e["horse_number"] == 12)
        assert e12["finish_position"] is None and e12["odds_final"] is None

    def test_idempotent(self):
        history = {"entries": [
            {"race_id": "202604020509", "horse_number": 7},
            {"race_id": "202604020509", "horse_number": 12},
        ]}
        scraper = FakeDbRace()
        new, errors = collect(CANDIDATES, PICKS, history, scraper, TODAY)
        assert new == [] and scraper.calls == []  # 再取得もしない

    def test_partial_history_refetches_race(self):
        history = {"entries": [{"race_id": "202604020509", "horse_number": 7}]}
        new, _ = collect(CANDIDATES, PICKS, history, FakeDbRace(), TODAY)
        assert [e["horse_number"] for e in new] == [12]

    def test_failure_is_counted_not_fatal(self):
        new, errors = collect(CANDIDATES, PICKS, {"entries": []},
                              FakeDbRace(fail=True), TODAY)
        assert new == [] and errors == 1
