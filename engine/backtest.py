# -*- coding: utf-8 -*-
"""バックテスト・回帰検証 (docs/DESIGN.md §6.3 / §6.4)。

golden照合:  python3 -m engine.backtest --db ../data/keiba.db
E2Eリプレイ: python3 -m engine.backtest --db ../data/keiba.db --replay 2026-04-25
引数なし(--replayなし)の場合は golden照合 → 同梱E2Eフィクスチャの日付でリプレイ、
の両方を実行する。どちらかが不一致なら exit 1。
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from engine import rules

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "golden.json"
E2E_PATH = ROOT / "tests" / "fixtures" / "e2e_day_20260425.json"

RESULT_QUERY = """
SELECT ra.race_date, ra.surface, ra.distance, e.odds_win,
       res.finish_position, res.odds_place, s.name AS sire_name
FROM results res
JOIN entries e ON res.entry_id = e.id
JOIN races ra ON e.race_id = ra.id
JOIN horses h ON e.horse_id = h.id
LEFT JOIN sires s ON h.sire_id = s.id
WHERE e.scratched = 0 AND res.finish_position IS NOT NULL
"""

REPLAY_QUERY = """
SELECT ra.race_id, v.code AS venue_code, ra.surface, ra.distance,
       e.horse_number, e.odds_win, res.finish_position, s.name AS sire_name
FROM entries e
JOIN races ra ON e.race_id = ra.id
LEFT JOIN venues v ON ra.venue_id = v.id
JOIN horses h ON e.horse_id = h.id
JOIN results res ON res.entry_id = e.id
LEFT JOIN sires s ON h.sire_id = s.id
WHERE e.scratched = 0 AND res.finish_position IS NOT NULL AND ra.race_date = ?
"""


def roi_pct(rows, ret):
    """rows: 対象行, ret: 行→払戻(単位: 100円賭けあたり倍率)。100円ベタ買い回収率%。"""
    if not rows:
        return 0.0
    return round(sum(ret(r) for r in rows) / len(rows) * 100, 1)


def compute_stats(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(RESULT_QUERY).fetchall()
    con.close()

    seg = [
        r for r in rows
        if rules.is_golden_segment(r["surface"], r["distance"], r["sire_name"])
    ]
    band = [r for r in seg if rules.is_in_band(r["odds_win"])]

    def win_ret(r):
        return (r["odds_win"] or 0.0) if r["finish_position"] == 1 else 0.0

    def win_ret_capped(r):
        return min(win_ret(r), rules.BAND_MAX)

    def place_ret(r):
        if r["finish_position"] <= 3 and r["odds_place"] is not None:
            return r["odds_place"]
        return 0.0

    by_year = defaultdict(list)
    for r in band:
        by_year[str(r["race_date"])[:4]].append(r)

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


def verify_golden(db_path):
    golden = json.loads(GOLDEN_PATH.read_text())
    stats = compute_stats(db_path)
    expected = {k: v for k, v in golden.items() if k not in ("description", "db_span")}
    diffs = diff_dict(expected, stats)
    print("== golden照合 ==")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if diffs:
        print("NG: golden.json と不一致:")
        print("\n".join(diffs))
        return False
    print(f"OK: golden.json と完全一致 (n={stats['segment_all_odds']['n']:,} / "
          f"{stats['segment_all_odds']['win_roi_pct']}% , "
          f"band n={stats['segment_band_10_50']['n']:,} / "
          f"{stats['segment_band_10_50']['win_roi_pct']}%)")
    return True


def build_day_candidates(db_path, date):
    """指定日の candidates/picks を build_weekly と同じ判定コードパスで生成する。

    candidate判定は rules.is_candidate、帯判定は rules.is_in_band を使う
    (E2E要件: 本番と同一コードパス)。
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(REPLAY_QUERY, (date,)).fetchall()
    con.close()

    out = []
    for r in rows:
        if not rules.is_candidate(r["surface"], r["distance"], r["sire_name"]):
            continue
        out.append({
            "race_id": r["race_id"],
            "venue_code": r["venue_code"],
            "distance": r["distance"],
            "horse_number": r["horse_number"],
            "sire_name": r["sire_name"],
            "odds_win": r["odds_win"],
            "in_band": rules.is_in_band(r["odds_win"]),
            "finish_position": r["finish_position"],
        })
    return out


def verify_replay(db_path, date):
    fixture = json.loads(E2E_PATH.read_text())
    if date != fixture["date"]:
        print(f"NG: E2Eフィクスチャは {fixture['date']} 用です (指定: {date})")
        return False

    actual = build_day_candidates(db_path, date)
    n_picks = sum(1 for c in actual if c["in_band"])
    print(f"== E2Eリプレイ {date} ==")
    print(f"candidates={len(actual)} picks={n_picks} "
          f"(期待: {fixture['n_candidates']}/{fixture['n_picks']})")

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
    if ok and len(actual) == fixture["n_candidates"] and n_picks == fixture["n_picks"]:
        print(f"OK: E2E一致 (候補{len(actual)}/帯内{n_picks})")
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
