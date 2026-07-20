# -*- coding: utf-8 -*-
"""バックテスト・回帰検証 (docs/DESIGN.md §6.3 / §6.4)。

golden照合:  python3 -m engine.backtest --db ../data/keiba.db
E2Eリプレイ: python3 -m engine.backtest --db ../data/keiba.db --replay 2026-04-25
引数なし(--replayなし)の場合は golden_v2照合 → golden(v1参照値)照合 →
同梱E2E v2フィクスチャの日付でリプレイ、をすべて実行する。どれかが不一致なら exit 1。

v2の前走由来の値(days_since_last / prev_distance)は、DB内の同一馬の直前レース
(scratched=0 かつ finish_position NOT NULL の出走行)から算出する。
馬体重は当該レースの entries.horse_weight を使う。
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from engine import rules

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_V1_PATH = ROOT / "tests" / "fixtures" / "golden.json"
GOLDEN_V2_PATH = ROOT / "tests" / "fixtures" / "golden_v2.json"
E2E_PATH = ROOT / "tests" / "fixtures" / "e2e_day_20260425_v2.json"

# golden_v2 のうち再計算で照合するキー(bootstrap系は乱数依存のため対象外)
GOLDEN_V2_SKIP_KEYS = ("description", "db_span", "core_bootstrap_ci95", "core_p_roi_gt_100")

RESULT_QUERY = """
SELECT ra.race_id, ra.race_date, v.code AS venue_code, ra.surface, ra.distance,
       e.horse_id, e.horse_number, e.horse_weight, e.odds_win,
       res.finish_position, res.odds_place, s.name AS sire_name
FROM results res
JOIN entries e ON res.entry_id = e.id
JOIN races ra ON e.race_id = ra.id
LEFT JOIN venues v ON ra.venue_id = v.id
JOIN horses h ON e.horse_id = h.id
LEFT JOIN sires s ON h.sire_id = s.id
WHERE e.scratched = 0 AND res.finish_position IS NOT NULL
ORDER BY e.horse_id, ra.race_date
"""


def load_rows(db_path):
    """全結果行を読み、馬ごとの直前レースから前走情報(prev_distance / days_since_last)を付与。"""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    raw = con.execute(RESULT_QUERY).fetchall()
    con.close()

    rows = []
    prev_horse_id, prev_date, prev_distance = None, None, None
    for r in raw:  # horse_id, race_date 昇順
        d = date.fromisoformat(str(r["race_date"]))
        if r["horse_id"] != prev_horse_id:
            prev_horse_id, prev_date, prev_distance = r["horse_id"], None, None
        row = dict(r)
        row["race_date"] = d
        row["prev_distance"] = prev_distance
        row["days_since_last"] = (d - prev_date).days if prev_date else None
        rows.append(row)
        prev_date, prev_distance = d, r["distance"]
    return rows


def judge(row):
    """1行にv2判定を適用し (is_candidate, excluded_reason, tier) を返す。

    build_weekly / update_odds と同じ rules の判定関数を使う(E2E要件)。
    """
    if not rules.is_candidate(
        row["surface"], row["distance"], row["sire_name"], row["venue_code"]
    ):
        return False, [], None
    reasons = rules.exclusion_reasons(
        row["days_since_last"], row["horse_weight"], row["prev_distance"], row["distance"]
    )
    t = rules.tier(row["odds_win"]) if not reasons else None
    return True, reasons, t


def roi_pct(rows, ret):
    """rows: 対象行, ret: 行→払戻(単位: 100円賭けあたり倍率)。100円ベタ買い回収率%。

    float誤差で正確な .x5 が .x50…003 等にズレて丸めが振れるのを防ぐため、
    オッズ由来の値を Decimal で合算し偶数丸め(golden生成時と同じ)で1桁に丸める。
    """
    if not rows:
        return 0.0
    total = sum(Decimal(str(ret(r))) for r in rows)
    pct = total / len(rows) * 100
    return float(pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN))


def win_ret(r):
    return (r["odds_win"] or 0.0) if r["finish_position"] == 1 else 0.0


def place_ret(r):
    if r["finish_position"] <= 3 and r["odds_place"] is not None:
        return r["odds_place"]
    return 0.0


def tier_stats(rows):
    by_year = defaultdict(list)
    for r in rows:
        by_year[str(r["race_date"].year)].append(r)
    return {
        "n": len(rows),
        "win_roi_pct": roi_pct(rows, win_ret),
        "place_roi_pct": roi_pct(rows, place_ret),
        "by_year": {
            y: {"n": len(rs), "win_roi_pct": roi_pct(rs, win_ret)}
            for y, rs in sorted(by_year.items())
        },
    }


def compute_stats_v2(rows):
    core, watch = [], []
    for row in rows:
        is_cand, reasons, t = judge(row)
        if not is_cand or reasons:
            continue
        if t == "core":
            core.append(row)
        elif t == "watch":
            watch.append(row)

    half = defaultdict(list)
    for r in core:
        half[f"{r['race_date'].year}H{1 if r['race_date'].month <= 6 else 2}"].append(r)

    return {
        "rule_v2_core_10_30": tier_stats(core),
        "rule_v2_watch_30_50": tier_stats(watch),
        "rule_v2_full_10_50": tier_stats(core + watch),
        "core_half_year_win_roi": {
            h: roi_pct(rs, win_ret) for h, rs in sorted(half.items())
        },
    }


def compute_stats_v1(rows):
    """golden.json(v1=base) 照合用。セグメントは千直・中京込み(verify_factors F02 準拠)。"""
    seg = [
        r for r in rows
        if rules.is_golden_segment(r["surface"], r["distance"], r["sire_name"])
    ]
    band = [r for r in seg if rules.is_in_band(r["odds_win"])]

    def win_ret_capped(r):
        return min(win_ret(r), rules.BAND_MAX)

    by_year = defaultdict(list)
    for r in band:
        by_year[str(r["race_date"].year)].append(r)

    return {
        "total_result_rows": len(rows),
        "segment_all_odds": {
            "n": len(seg),
            "win_roi_pct": roi_pct(seg, win_ret),
            "place_roi_pct": roi_pct(seg, place_ret),
        },
        "segment_band_10_50": {
            "n": len(band),
            "win_roi_pct": roi_pct(band, win_ret),
            "win_roi_capped50_pct": roi_pct(band, win_ret_capped),
        },
        "by_year_band_10_50": {
            y: {"n": len(rs), "win_roi_pct": roi_pct(rs, win_ret)}
            for y, rs in sorted(by_year.items())
        },
    }


def diff_dict(expected, actual, path=""):
    """golden(expected)に存在するキーだけを再帰比較し、不一致リストを返す。"""
    diffs = []
    for key, exp in expected.items():
        p = f"{path}.{key}" if path else key
        if isinstance(exp, dict):
            diffs += diff_dict(exp, actual.get(key, {}), p)
        else:
            act = actual.get(key)
            if act != exp:
                diffs.append(f"  {p}: expected={exp} actual={act}")
    return diffs


def verify_against(name, golden_path, stats, skip_keys=("description", "db_span")):
    golden = json.loads(golden_path.read_text())
    expected = {k: v for k, v in golden.items() if k not in skip_keys}
    diffs = diff_dict(expected, stats)
    print(f"== {name} 照合 ==")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if diffs:
        print(f"NG: {golden_path.name} と不一致:")
        print("\n".join(diffs))
        return False
    print(f"OK: {golden_path.name} と完全一致")
    return True


def verify_golden(db_path):
    """golden_v2(v2ルール)と golden(v1参照値)の両方を照合する。"""
    rows = load_rows(db_path)
    ok_v2 = verify_against(
        "golden_v2 (v2ルール)", GOLDEN_V2_PATH, compute_stats_v2(rows), GOLDEN_V2_SKIP_KEYS
    )
    ok_v1 = verify_against("golden (v1=base 参照値)", GOLDEN_V1_PATH, compute_stats_v1(rows))
    return ok_v2 and ok_v1


def build_day_candidates(db_path, day):
    """指定日の候補一覧を build_weekly と同じ判定コードパス(judge)で生成する。"""
    rows = [r for r in load_rows(db_path) if r["race_date"].isoformat() == day]
    out = []
    for row in rows:
        is_cand, reasons, t = judge(row)
        if not is_cand:
            continue
        out.append({
            "race_id": row["race_id"],
            "venue_code": row["venue_code"],
            "distance": row["distance"],
            "horse_number": row["horse_number"],
            "sire_name": row["sire_name"],
            "odds_win": row["odds_win"],
            "prev_distance": row["prev_distance"],
            "days_since_last": row["days_since_last"],
            "horse_weight": row["horse_weight"],
            "excluded_reason": reasons,
            "tier": t,
            "finish_position": row["finish_position"],
        })
    return out


def verify_replay(db_path, day):
    fixture = json.loads(E2E_PATH.read_text())
    if day != fixture["date"]:
        print(f"NG: E2Eフィクスチャは {fixture['date']} 用です (指定: {day})")
        return False

    actual = build_day_candidates(db_path, day)
    n_after = sum(1 for c in actual if not c["excluded_reason"])
    n_core = sum(1 for c in actual if c["tier"] == "core")
    n_watch = sum(1 for c in actual if c["tier"] == "watch")
    print(f"== E2Eリプレイ {day} (v2) ==")
    print(f"raw={len(actual)} 除外後={n_after} core={n_core} watch={n_watch} "
          f"(期待: {fixture['n_raw_candidates']}/{fixture['n_after_exclusion']}"
          f"/{fixture['n_core']}/{fixture['n_watch']})")

    def key(c):
        return (c["race_id"], c["horse_number"])

    exp_map = {key(c): c for c in fixture["candidates"]}
    act_map = {key(c): c for c in actual}
    ok = True
    for k in sorted(exp_map.keys() | act_map.keys()):
        exp, act = exp_map.get(k), act_map.get(k)
        if exp is None:
            print(f"NG: 余分な候補 {k}: {act}")
            ok = False
        elif act is None:
            print(f"NG: 候補の欠落 {k}: {exp}")
            ok = False
        else:
            fields = [f for f in exp if exp[f] != act.get(f)]
            if fields:
                print(f"NG: 不一致 {k}: " + ", ".join(
                    f"{f} expected={exp[f]} actual={act.get(f)}" for f in fields))
                ok = False
    counts_ok = (
        len(actual) == fixture["n_raw_candidates"]
        and n_after == fixture["n_after_exclusion"]
        and n_core == fixture["n_core"]
        and n_watch == fixture["n_watch"]
    )
    if ok and counts_ok:
        print(f"OK: E2E一致 (raw{len(actual)}→除外後{n_after}→core{n_core}・watch{n_watch})")
        return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="逆・血統ビーム バックテスト")
    ap.add_argument("--db", required=True, help="keiba.db のパス")
    ap.add_argument("--replay", metavar="YYYY-MM-DD",
                    help="指定日のE2Eリプレイのみ実行(省略時はgolden照合+E2E両方)")
    args = ap.parse_args(argv)

    if not Path(args.db).exists():
        print(f"NG: DBが見つかりません: {args.db}")
        return 1

    if args.replay:
        ok = verify_replay(args.db, args.replay)
    else:
        ok = verify_golden(args.db)
        fixture_date = json.loads(E2E_PATH.read_text())["date"]
        ok = verify_replay(args.db, fixture_date) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
