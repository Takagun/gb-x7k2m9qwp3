# -*- coding: utf-8 -*-
"""ルールエンジンのゴールデンテスト (docs/DESIGN.md §6.1)。"""
from engine import rules


class TestCandidate:
    def test_shiba_1800_kizuna_is_candidate(self):
        assert rules.is_candidate("芝", 1800, "キズナ")

    def test_shiba_2000_kizuna_is_not_candidate(self):
        # 2000 % 400 == 0 → 根幹距離
        assert not rules.is_candidate("芝", 2000, "キズナ")

    def test_dirt_1800_kizuna_is_not_candidate(self):
        assert not rules.is_candidate("ダート", 1800, "キズナ")
        assert not rules.is_candidate("ダ", 1800, "キズナ")

    def test_shiba_1400_drefong_is_not_candidate(self):
        # ドレフォンはUS型
        assert not rules.is_candidate("芝", 1400, "ドレフォン")

    def test_shiba_1000_lordkanaloa_is_not_candidate(self):
        # 千直は明示除外 (1000 % 400 != 0 だが対象外)
        assert not rules.is_candidate("芝", 1000, "ロードカナロア")

    def test_shiba_odd_distance_is_candidate(self):
        # 3170mのような変則距離も非根幹 (E2Eフィクスチャに実在)
        assert rules.is_candidate("芝", 3170, "ワールドエース")

    def test_unknown_sire_is_not_candidate(self):
        assert not rules.is_candidate("芝", 1800, "無名種牡馬")
        assert not rules.is_candidate("芝", 1800, None)

    def test_eu_sire_is_not_candidate(self):
        assert not rules.is_candidate("芝", 1800, "ハービンジャー")

    def test_golden_segment_includes_senchoku(self):
        # golden.json のセグメント (verify_factors F02) は千直込み
        assert rules.is_golden_segment("芝", 1000, "ロードカナロア")
        assert not rules.is_golden_segment("芝", 2000, "キズナ")
        assert not rules.is_golden_segment("ダート", 1800, "キズナ")


class TestBand:
    def test_9_9_is_out(self):
        assert not rules.is_in_band(9.9)

    def test_10_0_is_in(self):
        assert rules.is_in_band(10.0)

    def test_49_9_is_in(self):
        assert rules.is_in_band(49.9)

    def test_50_0_is_out(self):
        assert not rules.is_in_band(50.0)

    def test_none_odds_is_out(self):
        # オッズ発売前 (None) は帯外扱い
        assert not rules.is_in_band(None)


class TestChukyoWarning:
    def test_chukyo_has_warning(self):
        assert rules.has_chukyo_warning("07")

    def test_other_venues_have_no_warning(self):
        for code in ["01", "02", "03", "04", "05", "06", "08", "09", "10"]:
            assert not rules.has_chukyo_warning(code)


class TestReasonText:
    def test_template(self):
        text = rules.reason_text("キズナ", "新潟", 1800, 14.2)
        assert text == (
            "父キズナ(日本型主流)× 新潟芝1800m(非根幹)"
            "× 単勝14.2倍(検証妙味帯10-50倍)"
        )

    def test_no_odds(self):
        assert "単勝--倍" in rules.reason_text("キズナ", "新潟", 1800, None)

    def test_performance_line_matches_golden(self):
        assert "2023年99.6%" in rules.PERFORMANCE_LINE
        assert "26年132.0%" in rules.PERFORMANCE_LINE
