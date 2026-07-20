# -*- coding: utf-8 -*-
"""逆・血統ビーム判定ルール (docs/DESIGN.md §2 — 数値・判定式は変更禁止)。

candidate = 芝 AND 非根幹(distance % 400 != 0) AND 千直(芝1000m)除外 AND 父がJP型
pick      = candidate AND 10.0 <= 単勝オッズ < 50.0
中京(07)  = 除外しないが「効きが弱い」警告バッジ

golden.json の集計セグメントは verify_factors.py F02 と同一定義で、
千直を含む(アプリの candidate 判定とは千直の扱いだけが異なる)。
backtest の golden 照合には is_golden_segment を、
candidates/picks 生成(build_weekly / update_odds / E2Eリプレイ)には
is_candidate / is_in_band を使うこと。
"""
from engine.siretype import classify

BAND_MIN = 10.0
BAND_MAX = 50.0
SENCHOKU_DISTANCE = 1000  # 芝1000m(千直)。検証で効かず(回収率60.2%)明示除外
CHUKYO_VENUE_CODE = "07"

PERFORMANCE_LINE = (
    "このセグメントの過去実績: 2023年99.6% / 24年96.0% / 25年94.9% / "
    "26年132.0%(単勝ベタ買い回収率)"
)


def is_nonroot(distance):
    """非根幹距離か(400mの倍数でない)。"""
    return distance % 400 != 0


def is_candidate(surface, distance, sire_name):
    """アプリの候補判定(千直は明示除外)。"""
    return (
        surface == "芝"
        and is_nonroot(distance)
        and distance != SENCHOKU_DISTANCE
        and classify(sire_name) == "JP"
    )


def is_golden_segment(surface, distance, sire_name):
    """golden.json 照合用のセグメント判定(verify_factors.py F02 準拠・千直込み)。"""
    return surface == "芝" and is_nonroot(distance) and classify(sire_name) == "JP"


def is_in_band(odds_win):
    """検証妙味帯 10.0 <= オッズ < 50.0。オッズ未確定(None)は帯外。"""
    return odds_win is not None and BAND_MIN <= odds_win < BAND_MAX


def has_chukyo_warning(venue_code):
    """中京(07)は検証で効きが弱い会場 — 除外はせず警告のみ。"""
    return venue_code == CHUKYO_VENUE_CODE


def reason_text(sire_name, venue_name, distance, odds_win):
    """理由表示テンプレート(DESIGN.md §2)。"""
    odds = f"{odds_win:.1f}" if odds_win is not None else "--"
    return (
        f"父{sire_name}(日本型主流)× {venue_name}芝{distance}m(非根幹)"
        f"× 単勝{odds}倍(検証妙味帯10-50倍)"
    )
