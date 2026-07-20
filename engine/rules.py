# -*- coding: utf-8 -*-
"""逆・血統ビーム判定ルール v2 (docs/DESIGN.md §2 — 数値・判定式は変更禁止)。

candidate = 芝 AND 非根幹(distance % 400 != 0) AND 千直(芝1000m)除外
            AND 父がJP型 AND 中京(07)以外
除外       = 休養121日以上 OR 馬体重440kg以下 OR 前走比+200m以上の延長
            (前走情報・馬体重が無い項目は判定しない=除外しない)
tier      = core: 10.0 <= オッズ < 30.0(推奨) / watch: 30.0 <= オッズ < 50.0(参考)

golden.json(v1) の集計セグメントは verify_factors.py F02 と同一定義で、
千直・中京を含む。v1照合には is_golden_segment を使う。
candidates/picks 生成(build_weekly / update_odds / E2Eリプレイ)と
golden_v2.json 照合には is_candidate / exclusion_reasons / tier を使うこと。
"""
from engine.siretype import classify

CORE_MIN = 10.0
CORE_MAX = 30.0
WATCH_MIN = 30.0
WATCH_MAX = 50.0
BAND_MIN = 10.0   # full帯(10-50)。v1 golden照合と full集計用
BAND_MAX = 50.0
SENCHOKU_DISTANCE = 1000  # 芝1000m(千直)。検証で効かず(回収率60.2%)明示除外
CHUKYO_VENUE_CODE = "07"  # v2: 検証で効かない会場としてcandidate段階で除外

LAYOFF_DAYS_MIN = 121     # 休養121日以上 → 除外
SMALL_WEIGHT_MAX = 440    # 馬体重440kg以下 → 除外
EXTEND_DELTA_MIN = 200    # 前走比+200m以上の延長 → 除外

# 出典: tests/fixtures/golden_v2.json (core 10-30倍, n=1,878)
PERFORMANCE_LINE = (
    "コア帯の過去実績: 2023年116% / 24年114% / 25年119% / "
    "26年168%(単勝ベタ買い回収率・全年100%超)"
)
WATCH_NOTE = "参考: 30-50倍はデータ希薄のため購入対象外"


def is_nonroot(distance):
    """非根幹距離か(400mの倍数でない)。"""
    return distance % 400 != 0


def is_candidate(surface, distance, sire_name, venue_code=None):
    """v2の候補判定(千直・中京は明示除外)。

    venue_code=None は会場情報なし(単体テスト等)で、中京チェックをスキップする。
    本番コードパス(build_weekly / backtest)は必ず venue_code を渡すこと。
    """
    return (
        surface == "芝"
        and is_nonroot(distance)
        and distance != SENCHOKU_DISTANCE
        and classify(sire_name) == "JP"
        and venue_code != CHUKYO_VENUE_CODE
    )


def is_golden_segment(surface, distance, sire_name):
    """golden.json(v1) 照合用のセグメント判定(verify_factors.py F02 準拠・千直込み)。"""
    return surface == "芝" and is_nonroot(distance) and classify(sire_name) == "JP"


def exclusion_reasons(days_since_last, horse_weight, prev_distance, distance):
    """ネガ3除外の該当理由リスト(該当なしなら空)。

    値が None の項目(初出走・地方転入・馬体重未発表等)は判定しない=除外しない。
    順序は long_layoff → small → extend で固定(E2Eフィクスチャと同順)。
    """
    reasons = []
    if days_since_last is not None and days_since_last >= LAYOFF_DAYS_MIN:
        reasons.append("long_layoff")
    if horse_weight is not None and horse_weight <= SMALL_WEIGHT_MAX:
        reasons.append("small")
    if prev_distance is not None and distance - prev_distance >= EXTEND_DELTA_MIN:
        reasons.append("extend")
    return reasons


def tier(odds_win):
    """帯判定。core=推奨(10-30倍) / watch=参考(30-50倍) / None=帯外。

    除外馬は呼び出し側で tier=None にすること(この関数はオッズのみ見る)。
    オッズ未確定(None)は帯外。
    """
    if odds_win is None:
        return None
    if CORE_MIN <= odds_win < CORE_MAX:
        return "core"
    if WATCH_MIN <= odds_win < WATCH_MAX:
        return "watch"
    return None


def is_in_band(odds_win):
    """full帯 10.0 <= オッズ < 50.0(v1互換・full集計用)。"""
    return odds_win is not None and BAND_MIN <= odds_win < BAND_MAX


def has_chukyo_warning(venue_code):
    """中京(07)判定。v2ではcandidate段階で除外されるため通常は表示に出ない。"""
    return venue_code == CHUKYO_VENUE_CODE


def reason_text(sire_name, venue_name, distance, odds_win):
    """理由表示テンプレート(DESIGN.md §2)。"""
    odds = f"{odds_win:.1f}" if odds_win is not None else "--"
    return (
        f"父{sire_name}(日本型主流)× {venue_name}芝{distance}m(非根幹)"
        f"× 単勝{odds}倍(コア妙味帯10-30倍)"
    )
