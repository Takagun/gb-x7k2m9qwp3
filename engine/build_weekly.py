# -*- coding: utf-8 -*-
"""週末候補の確定バッチ (docs/DESIGN.md §3 / §5)。

木・金 21:00 JST に GitHub Actions から実行し、翌土日の全レースの出馬表から
逆・血統ビーム候補を抽出して site/data/candidates.json を生成する。

使い方:
  python3 -m engine.build_weekly --dry-run          # 生成内容を表示のみ
  python3 -m engine.build_weekly --date 20260725    # 対象日を指定 (複数可: カンマ区切り)
  python3 -m engine.build_weekly                    # site/data/candidates.json へ書き込み
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import rules
from engine.scraper import ParseError, PedScraper, RaceListScraper, ShutubaScraper
from engine.sire_resolver import SireResolver
from engine.siretype import classify

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "site" / "data" / "candidates.json"
JST = timezone(timedelta(hours=9))


def next_weekend(today):
    """実行日から見た次の土曜・日曜 (DESIGN §7)。"""
    days_to_sat = (5 - today.weekday()) % 7
    if days_to_sat == 0 and today.weekday() != 5:
        days_to_sat = 7
    sat = today + timedelta(days=days_to_sat)
    return [sat, sat + timedelta(days=1)]


def build(dates, race_list=None, shutuba=None, resolver=None):
    """対象日リストの candidates データを構築して dict を返す。"""
    race_list = race_list or RaceListScraper()
    shutuba = shutuba or ShutubaScraper()
    resolver = resolver or SireResolver(ped_scraper=PedScraper())

    races_out = []
    n_races = 0
    for d in dates:
        date_str = d.strftime("%Y%m%d")
        race_ids = race_list.race_ids_for_date(date_str)
        print(f"{d}: {len(race_ids)} races")
        for race_id in race_ids:
            try:
                info = shutuba.scrape(race_id)
            except ParseError as e:
                # 存在しないレース番号 (12R未満の開催) は404でここに来る。
                # 馬が1頭も取れないのはページ構造変化の可能性もあるが、
                # 開催が短い日もあるため race単位ではスキップし最後に総数検証する。
                print(f"  skip {race_id}: {e}", file=sys.stderr)
                continue
            n_races += 1
            if info["surface"] != "芝":
                continue
            candidates = []
            for h in info["horses"]:
                sire = resolver.resolve(h["horse_id"])
                if not rules.is_candidate(info["surface"], info["distance"], sire):
                    continue
                candidates.append({
                    "horse_number": h["horse_number"],
                    "horse_id": h["horse_id"],
                    "horse_name": h["horse_name"],
                    "sire_name": sire,
                    "stype": classify(sire),
                })
            if not candidates:
                continue
            races_out.append({
                "race_id": race_id,
                "date": info["date"] or d.isoformat(),
                "venue_code": info["venue_code"],
                "venue_name": info["venue_name"],
                "race_number": info["race_number"],
                "post_time": info["post_time"],
                "surface": info["surface"],
                "distance": info["distance"],
                "race_name": info["race_name"],
                "chukyo_warning": rules.has_chukyo_warning(info["venue_code"]),
                "candidates": candidates,
            })

    if n_races == 0:
        raise ParseError("出馬表を1件もパースできなかった (サイト構造変化の疑い)")

    races_out.sort(key=lambda r: (r["date"], r["post_time"] or "99:99", r["race_id"]))
    return {
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "weekend": [d.isoformat() for d in dates],
        "races": races_out,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="週末候補の確定バッチ")
    ap.add_argument("--dry-run", action="store_true", help="ファイルを書かず内容表示のみ")
    ap.add_argument("--date", help="対象日 YYYYMMDD (カンマ区切りで複数指定可)")
    args = ap.parse_args(argv)

    if args.date:
        dates = [datetime.strptime(s, "%Y%m%d").date() for s in args.date.split(",")]
    else:
        dates = next_weekend(datetime.now(JST).date())

    resolver = SireResolver(ped_scraper=PedScraper())
    try:
        data = build(dates, resolver=resolver)
    except ParseError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    n_cand = sum(len(r["candidates"]) for r in data["races"])
    print(f"candidates: {len(data['races'])} races / {n_cand} horses")

    if args.dry_run:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT_PATH}")
    resolver.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
