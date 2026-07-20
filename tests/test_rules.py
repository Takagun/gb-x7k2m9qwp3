# -*- coding: utf-8 -*-
"""ルールエンジン v2 のゴールデンテスト (docs/DESIGN.md §6.1)。"""
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

    def test_chukyo_is_not_candidate(self):
        # v2: 中京(07)はcandidate段階で除外
        assert not rules.is_candidate("芝", 1800, "キズナ", venue_code="07")

    def test_other_venue_is_candidate(self):
        assert rules.is_candidate("芝", 1800, "キズナ", venue_code="04")

    def test_golden_segment_includes_senchoku_and_chukyo(self):
        # golden.json(v1) のセグメント (verify_factors F02) は千直・中京込み
        assert rules.is_golden_segment("芝", 1000, "ロードカナロア")
        assert not rules.is_golden_segment("芝", 2000, "キズナ")
        assert not rules.is_golden_segment("ダート", 1800, "キズナ")


class TestExclusion:
    def test_shorten_is_not_excluded(self):
        # 前走2000m → 今走1800m(短縮) → 除外なし
        assert rules.exclusion_reasons(30, 480, 2000, 1800) == []

    def test_extend_200m_is_excluded(self):
        # 前走1600m → 今走1800m(+200m延長) → 除外
        assert rules.exclusion_reasons(30, 480, 1600, 1800) == ["extend"]

    def test_extend_199m_is_not_excluded(self):
        assert rules.exclusion_reasons(30, 480, 1601, 1800) == []

    def test_layoff_121_days_is_excluded(self):
        assert rules.exclusion_reasons(121, 480, 1800, 1800) == ["long_layoff"]

    def test_layoff_120_days_is_not_excluded(self):
        assert rules.exclusion_reasons(120, 480, 1800, 1800) == []

    def test_weight_440_is_excluded(self):
        assert rules.exclusion_reasons(30, 440, 1800, 1800) == ["small"]

    def test_weight_441_is_not_excluded(self):
        assert rules.exclusion_reasons(30, 441, 1800, 1800) == []

    def test_missing_form_is_not_excluded(self):
        # 前走情報・馬体重が無い馬(初出走・地方転入等)は除外しない
        assert rules.exclusion_reasons(None, None, None, 1800) == []

    def test_multiple_reasons_in_fixed_order(self):
        # 順序は long_layoff → small → extend で固定 (E2Eフィクスチャと同順)
        assert rules.exclusion_reasons(200, 430, 1400, 1800) == [
            "long_layoff", "small", "extend",
        ]


class TestTier:
    def test_9_9_is_out(self):
        assert rules.tier(9.9) is None

    def test_10_0_is_core(self):
        assert rules.tier(10.0) == "core"

    def test_29_9_is_core(self):
        assert rules.tier(29.9) == "core"

    def test_30_0_is_watch(self):
        assert rules.tier(30.0) == "watch"

    def test_49_9_is_watch(self):
        assert rules.tier(49.9) == "watch"

    def test_50_0_is_out(self):
        assert rules.tier(50.0) is None

    def test_none_odds_is_out(self):
        # オッズ発売前 (None) は帯外扱い
        assert rules.tier(None) is None

    def test_full_band_compat(self):
        # full帯(10-50)ヘルパは tier in (core, watch) と同値
        for odds in (9.9, 10.0, 29.9, 30.0, 49.9, 50.0):
            assert rules.is_in_band(odds) == (rules.tier(odds) is not None)
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
            "× 単勝14.2倍(コア妙味帯10-30倍)"
        )

    def test_no_odds(self):
        assert "単勝--倍" in rules.reason_text("キズナ", "新潟", 1800, None)

    def test_performance_line_matches_golden_v2(self):
        assert "2023年116%" in rules.PERFORMANCE_LINE
        assert "26年168%" in rules.PERFORMANCE_LINE
        assert "全年100%超" in rules.PERFORMANCE_LINE

    def test_watch_note(self):
        assert "購入対象外" in rules.WATCH_NOTE
