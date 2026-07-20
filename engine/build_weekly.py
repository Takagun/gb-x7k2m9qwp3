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
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import rules
from engine.form_resolver import FormResolver
from engine.scraper import (
    HorseFormScraper,
    ParseError,
    PedScraper,
    RaceListScraper,
    ShutubaScraper,
)
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


def candidate_form_fields(form, race_date_iso, distance):
    """前走情報から除外判定用フィールドを組み立てる (馬体重は前走値で仮判定)。

    days_since_last は対象レース日付基準。前走情報が無い項目は None (=除外しない)。
    """
    days = None
    if form["last_date"]:
        days = (date_cls.fromisoformat(race_date_iso)
                - date_cls.fromisoformat(form["last_date"])).days
    return {
        "prev_distance": form["last_distance"],
        "days_since_last": days,
        "prev_weight": form["last_weight"],
        "excluded_reason": rules.exclusion_reasons(
            days, form["last_weight"], form["last_distance"], distance),
        "form_missing": form["form_missing"],
    }


def build(dates, race_list=None, shutuba=None, resolver=None, form_resolver=None):
    """対象日リストの candidates データを構築して dict を返す。"""
    race_list = race_list or RaceListScraper()
    shutuba = shutuba or ShutubaScraper()
    resolver = resolver or SireResolver(ped_scraper=PedScraper())
    if form_resolver is None:
        form_resolver = FormResolver(
            form_scraper=HorseFormScraper(), weekend_key=dates[0].isoformat())

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
            # 日付検証: トップページ由来のシード展開は対象日以外のカードが
            # 混ざるため、出馬表の開催日が対象日と一致するものだけを数える
            if info["date"] and info["date"] != d.isoformat():
                print(f"  skip {race_id}: 開催日不一致 ({info['date']})", file=sys.stderr)
                continue
            n_races += 1
            if info["surface"] != "芝":
                continue
            race_date_iso = info["date"] or d.isoformat()
            candidates = []
            for h in info["horses"]:
                sire = resolver.resolve(h["horse_id"])
                if not rules.is_candidate(
                    info["surface"], info["distance"], sire, info["venue_code"]
                ):
                    continue
                # ふるい通過馬のみ前走情報を取得 (週末あたり数十頭 — DESIGN §4.4)
                form = form_resolver.resolve(h["horse_id"])
                candidates.append({
                    "horse_number": h["horse_number"],
                    "horse_id": h["horse_id"],
                    "horse_name": h["horse_name"],
                    "sire_name": sire,
                    "stype": classify(sire),
                    **candidate_form_fields(form, race_date_iso, info["distance"]),
                })
            if not candidates:
                continue
            races_out.append({
                "race_id": race_id,
                "date": race_date_iso,
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
    form_resolver = FormResolver(
        form_scraper=HorseFormScraper(), weekend_key=dates[0].isoformat())
    try:
        data = build(dates, resolver=resolver, form_resolver=form_resolver)
    except ParseError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    n_cand = sum(len(r["candidates"]) for r in data["races"])
    n_excl = sum(1 for r in data["races"] for c in r["candidates"] if c["excluded_reason"])
    print(f"candidates: {len(data['races'])} races / {n_cand} horses (うち仮除外 {n_excl})")

    if args.dry_run:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT_PATH}")
    resolver.save()
    form_resolver.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
