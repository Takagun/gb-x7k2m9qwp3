# -*- coding: utf-8 -*-
"""オッズ更新バッチ (docs/DESIGN.md §3 / §5)。

土日 8:00〜16:00 JST 毎時、candidates.json の候補レースのみ単勝オッズを取得し、
帯 (10-50倍) 判定をして site/data/picks.json を更新する。
新規帯入り馬があれば Discord 通知 (同一馬は1回まで)。

使い方:
  python3 -m engine.update_odds --dry-run           # 書き込みせず表示のみ
  python3 -m engine.update_odds --date 20260725     # 対象日を指定 (既定: 今日JST)
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import notify, rules
from engine.scraper import OddsScraper

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "site" / "data" / "candidates.json"
PICKS_PATH = ROOT / "site" / "data" / "picks.json"
JST = timezone(timedelta(hours=9))


def load_json(path, default):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text())


def update_picks(candidates, prev_picks, odds_by_race, now_iso):
    """picks リストを更新して (picks, 新規帯入りリスト) を返す。

    - 対象日のレース: 取得オッズで in_band を再判定
    - 対象日以外のレース: 前回の picks をそのまま維持
    - entered_band_at は初回帯入り時に設定し、以後保持 (通知の重複防止に使う)
    """
    prev_map = {(p["race_id"], p["horse_number"]): p for p in prev_picks}
    picks = []
    new_entries = []
    for race in candidates.get("races", []):
        race_id = race["race_id"]
        for cand in race["candidates"]:
            key = (race_id, cand["horse_number"])
            prev = prev_map.get(key, {})
            if race_id in odds_by_race:
                odds = odds_by_race[race_id].get(cand["horse_number"])
                in_band = rules.is_in_band(odds)
            else:
                odds = prev.get("odds_win")
                in_band = prev.get("in_band", False)
            entered_at = prev.get("entered_band_at")
            if in_band and not entered_at:
                entered_at = now_iso
                new_entries.append({
                    "venue_name": race["venue_name"],
                    "race_number": race["race_number"],
                    "post_time": race["post_time"],
                    "horse_number": cand["horse_number"],
                    "horse_name": cand["horse_name"],
                    "odds_win": odds,
                })
            pick = {"race_id": race_id, "horse_number": cand["horse_number"],
                    "odds_win": odds, "in_band": in_band}
            if entered_at:
                pick["entered_band_at"] = entered_at
            picks.append(pick)
    return picks, new_entries


def main(argv=None):
    ap = argparse.ArgumentParser(description="オッズ更新バッチ")
    ap.add_argument("--dry-run", action="store_true", help="ファイルを書かず内容表示のみ")
    ap.add_argument("--date", help="対象日 YYYYMMDD (既定: 今日JST)")
    args = ap.parse_args(argv)

    now = datetime.now(JST)
    target = (datetime.strptime(args.date, "%Y%m%d").date() if args.date else now.date())

    candidates = load_json(CANDIDATES_PATH, {})
    races_today = [r for r in candidates.get("races", []) if r["date"] == target.isoformat()]
    if not candidates.get("races"):
        print("candidates.json が空 — 即終了")
        return 0
    if not races_today:
        print(f"{target} のレースが candidates にない — 即終了")
        return 0

    scraper = OddsScraper()
    odds_by_race = {}
    for race in races_today:
        odds_by_race[race["race_id"]] = scraper.win_odds(race["race_id"])
        print(f"{race['race_id']} {race['venue_name']}{race['race_number']}R: "
              f"{len(odds_by_race[race['race_id']])}頭分")

    prev = load_json(PICKS_PATH, {})
    now_iso = now.isoformat(timespec="seconds")
    picks, new_entries = update_picks(candidates, prev.get("picks", []), odds_by_race, now_iso)
    out = {
        "updated_at": now_iso,
        "odds_asof": now.strftime("%H:%M"),
        "picks": picks,
    }
    n_in_band = sum(1 for p in picks if p["in_band"])
    print(f"picks: {len(picks)}頭中 帯内{n_in_band}頭 / 新規帯入り{len(new_entries)}頭")

    if args.dry_run:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    PICKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PICKS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {PICKS_PATH}")
    notify.notify_new_picks(new_entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
