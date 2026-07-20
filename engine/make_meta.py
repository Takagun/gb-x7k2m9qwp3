# -*- coding: utf-8 -*-
"""site/data/meta.json 生成 (要 keiba.db)。

golden_v2 の静的実績に加えて、core(推奨)ベタ買いの
- 連敗状況 (現在の連敗・最長連敗・最終勝利日)
- 年別の累積収支カーブ (100円/点 単位。フロントで賭け金に換算)
を keiba.db から計算して焼き込む。四半期ごとの verify_factors 実行後などに
`make meta` で更新し、commit/push すると実績タブに反映される。

使い方: python3 -m engine.make_meta --db ../data/keiba.db [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

from engine import backtest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_V2_PATH = ROOT / "tests" / "fixtures" / "golden_v2.json"
OUT_PATH = ROOT / "site" / "data" / "meta.json"
SAMPLE_META_PATHS = [
    ROOT / "site" / "data" / "samples" / "empty" / "meta.json",
    ROOT / "site" / "data" / "samples" / "nosale" / "meta.json",
]


def core_bets(rows):
    """v2判定でcoreになる行を時系列順の (race_date, net_100yen) にして返す。

    net_100yen = 100円ベットの純損益 (勝ち: odds*100-100 / 負け: -100)。
    """
    bets = []
    for row in rows:
        is_cand, reasons, tier = backtest.judge(row)
        if not (is_cand and not reasons and tier == "core"):
            continue
        win = row["finish_position"] == 1
        net = int(round(row["odds_win"] * 100)) - 100 if win else -100
        bets.append((row["race_date"], net))
    bets.sort(key=lambda b: b[0])
    return bets


def streak_info(bets, asof):
    """現在の連敗・最長連敗・最終勝利日。"""
    current = 0
    for _, net in reversed(bets):
        if net > 0:
            break
        current += 1
    longest = run = 0
    last_win = None
    for d, net in bets:
        if net > 0:
            run = 0
            last_win = d
        else:
            run += 1
            longest = max(longest, run)
    return {
        "current": current,
        "longest": longest,
        "last_win_date": last_win.isoformat() if last_win else None,
        "asof": asof.isoformat(),
    }


def pnl_by_year(bets):
    """年ごとの累積収支リスト (100円/点 単位、1ベット1点)。"""
    out = {}
    for d, net in bets:
        series = out.setdefault(str(d.year), [])
        series.append((series[-1] if series else 0) + net)
    return out


def build_meta(db_path):
    golden = json.loads(GOLDEN_V2_PATH.read_text())
    rows = backtest.load_rows(db_path)
    stats = backtest.compute_stats_v2(rows)
    core_stats = stats["rule_v2_core_10_30"]
    g_core = golden["rule_v2_core_10_30"]
    if core_stats["n"] != g_core["n"] or core_stats["win_roi_pct"] != g_core["win_roi_pct"]:
        # DBが更新されたら golden_v2 と乖離する。実績表示はDB実測値を正とする
        print(f"note: DB実測 (n={core_stats['n']}, {core_stats['win_roi_pct']}%) が "
              f"golden_v2 (n={g_core['n']}, {g_core['win_roi_pct']}%) と異なる "
              "(DB更新後は正常)", file=sys.stderr)

    bets = core_bets(rows)
    asof = max(r["race_date"] for r in rows)
    wins = sum(1 for _, net in bets if net > 0)

    return {
        "source": f"engine/make_meta.py (keiba.db 〜{asof.isoformat()})",
        "db_span": [golden["db_span"][0], asof.isoformat()],
        "core": {
            **core_stats,
            "ci95": golden["core_bootstrap_ci95"],
            "p_gt_100": golden["core_p_roi_gt_100"],
            "wins": wins,
            "win_rate_pct": round(wins / len(bets) * 100, 1) if bets else 0.0,
        },
        "watch": {
            "n": stats["rule_v2_watch_30_50"]["n"],
            "win_roi_pct": stats["rule_v2_watch_30_50"]["win_roi_pct"],
            "worst_year_roi_pct": min(
                v["win_roi_pct"]
                for v in stats["rule_v2_watch_30_50"]["by_year"].values()),
        },
        "full": {
            "n": stats["rule_v2_full_10_50"]["n"],
            "win_roi_pct": stats["rule_v2_full_10_50"]["win_roi_pct"],
        },
        "streak": streak_info(bets, asof),
        "pnl_by_year": pnl_by_year(bets),
        "disclaimer": "過去実績は将来の回収率を保証しません。馬券の購入は自己責任で。",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="meta.json 生成")
    ap.add_argument("--db", required=True, help="keiba.db のパス")
    ap.add_argument("--dry-run", action="store_true", help="書き込まず表示のみ")
    args = ap.parse_args(argv)

    if not Path(args.db).exists():
        print(f"NG: DBが見つかりません: {args.db}")
        return 1

    meta = build_meta(args.db)
    s = meta["streak"]
    print(f"core: n={meta['core']['n']} / {meta['core']['win_roi_pct']}% / "
          f"勝率{meta['core']['win_rate_pct']}%")
    print(f"連敗: 現在{s['current']} / 最長{s['longest']} / 最終勝利 {s['last_win_date']} "
          f"(〜{s['asof']})")
    print("年別収支(円/100円ベット): " + ", ".join(
        f"{y}:{v[-1]:+,}" for y, v in sorted(meta["pnl_by_year"].items())))

    if args.dry_run:
        return 0
    text = json.dumps(meta, ensure_ascii=False, indent=1) + "\n"
    OUT_PATH.write_text(text)
    print(f"wrote {OUT_PATH}")
    for p in SAMPLE_META_PATHS:
        if p.parent.exists():
            p.write_text(text)
            print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
