# -*- coding: utf-8 -*-
"""make_meta の連敗・累積収支計算のユニットテスト (DB不要)。"""
from datetime import date

from engine.make_meta import pnl_by_year, streak_info

BETS = [
    (date(2025, 12, 20), -100),
    (date(2026, 1, 10), -100),
    (date(2026, 1, 11), 1540),   # 勝ち (16.4倍)
    (date(2026, 2, 1), -100),
    (date(2026, 2, 8), -100),
    (date(2026, 2, 9), -100),
]


class TestStreakInfo:
    def test_current_and_longest(self):
        s = streak_info(BETS, date(2026, 2, 9))
        assert s["current"] == 3          # 勝利後の連敗3
        assert s["longest"] == 3
        assert s["last_win_date"] == "2026-01-11"
        assert s["asof"] == "2026-02-09"

    def test_ends_with_win(self):
        bets = BETS[:3]
        s = streak_info(bets, date(2026, 1, 11))
        assert s["current"] == 0
        assert s["longest"] == 2

    def test_no_wins(self):
        bets = [(date(2026, 1, 1), -100), (date(2026, 1, 2), -100)]
        s = streak_info(bets, date(2026, 1, 2))
        assert s["current"] == 2 and s["longest"] == 2
        assert s["last_win_date"] is None


class TestPnlByYear:
    def test_cumulative_per_year(self):
        pnl = pnl_by_year(BETS)
        assert pnl["2025"] == [-100]
        # 2026: -100 → +1440 → +1340 → +1240 → +1140
        assert pnl["2026"] == [-100, 1440, 1340, 1240, 1140]
