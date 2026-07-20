# -*- coding: utf-8 -*-
"""オッズ更新バッチ (docs/DESIGN.md §3 / §5)。

土日 8:00〜16:00 JST 毎時、candidates.json の候補レースのみ単勝オッズを取得し、
tier判定 (core 10-30 / watch 30-50) をして site/data/picks.json を更新する。
馬体重は当日朝に出馬表で発表されるため、当日値が取れたら前走値の仮判定を
上書きして除外を再判定する (DESIGN §2)。新規帯入り馬は Discord 通知 (同一馬1回まで)。

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
from engine.scraper import OddsScraper, ParseError, ShutubaScraper

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "site" / "data" / "candidates.json"
PICKS_PATH = ROOT / "site" / "data" / "picks.json"
JST = timezone(timedelta(hours=9))


def load_json(path, default):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text())


def update_picks(candidates, prev_picks, odds_by_race, weights_by_race, now_iso):
    """picks リストを更新して (picks, 新規帯入りリスト) を返す。

    - 対象日のレース: 取得オッズ + 当日馬体重 (取れた場合) で tier/除外を再判定
    - 対象日以外のレース: 前回の picks をそのまま維持
    - 馬体重は 当日値 > 前回picksの当日値 > 前走値 (candidates.json) の優先で判定
    - entered_band_at は初回帯入り (tier != null) 時に設定し、以後保持 (通知の重複防止)
    """
    prev_map = {(p["race_id"], p["horse_number"]): p for p in prev_picks}
    picks = []
    new_entries = []
    for race in candidates.get("races", []):
        race_id = race["race_id"]
        for cand in race["candidates"]:
            key = (race_id, cand["horse_number"])
            prev = prev_map.get(key, {})
            day_weight = prev.get("day_weight")
            if race_id in weights_by_race:
                day_weight = weights_by_race[race_id].get(cand["horse_number"], day_weight)
            if race_id in odds_by_race:
                odds = odds_by_race[race_id].get(cand["horse_number"])
            else:
                # 対象日以外 (前回picksを維持)
                odds = prev.get("odds_win")
            weight = day_weight if day_weight is not None else cand.get("prev_weight")
            reasons = rules.exclusion_reasons(
                cand.get("days_since_last"), weight,
                cand.get("prev_distance"), race["distance"])
            tier = rules.tier(odds) if not reasons else None
            entered_at = prev.get("entered_band_at")
            if tier and not entered_at:
                entered_at = now_iso
                new_entries.append({
                    "venue_name": race["venue_name"],
                    "race_number": race["race_number"],
                    "post_time": race["post_time"],
                    "horse_number": cand["horse_number"],
                    "horse_name": cand["horse_name"],
                    "odds_win": odds,
                    "tier": tier,
                })
            pick = {"race_id": race_id, "horse_number": cand["horse_number"],
                    "odds_win": odds, "tier": tier,
                    "excluded_reason": reasons,
                    "form_missing": cand.get("form_missing", False)}
            if day_weight is not None:
                pick["day_weight"] = day_weight
            if entered_at:
                pick["entered_band_at"] = entered_at
            picks.append(pick)
    return picks, new_entries


def races_needing_weights(races_today, prev_picks):
    """当日馬体重が未取得の候補がいるレースのみ出馬表を再取得する (発表後は不変)。"""
    prev_map = {(p["race_id"], p["horse_number"]): p for p in prev_picks}
    out = []
    for race in races_today:
        cands = race["candidates"]
        if any(prev_map.get((race["race_id"], c["horse_number"]), {}).get("day_weight")
               is None for c in cands):
            out.append(race)
    return out


def fetch_day_weights(races, shutuba_scraper):
    """出馬表から当日馬体重を取る。失敗しても前走値の仮判定で続行 (fatalにしない)。"""
    weights_by_race = {}
    for race in races:
        try:
            info = shutuba_scraper.scrape(race["race_id"])
        except ParseError as e:
            print(f"  当日馬体重の取得失敗 {race['race_id']}: {e}", file=sys.stderr)
            continue
        weights_by_race[race["race_id"]] = {
            h["horse_number"]: h["horse_weight"]
            for h in info["horses"] if h["horse_weight"] is not None
        }
    return weights_by_race


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

    prev = load_json(PICKS_PATH, {})
    prev_picks = prev.get("picks", [])

    # 当日馬体重 (未取得レースのみ出馬表を再取得)
    weights_by_race = fetch_day_weights(
        races_needing_weights(races_today, prev_picks), ShutubaScraper())

    scraper = OddsScraper()
    odds_by_race = {}
    for race in races_today:
        odds_by_race[race["race_id"]] = scraper.win_odds(race["race_id"])
        print(f"{race['race_id']} {race['venue_name']}{race['race_number']}R: "
              f"{len(odds_by_race[race['race_id']])}頭分")

    now_iso = now.isoformat(timespec="seconds")
    picks, new_entries = update_picks(
        candidates, prev_picks, odds_by_race, weights_by_race, now_iso)
    out = {
        "updated_at": now_iso,
        "odds_asof": now.strftime("%H:%M"),
        "picks": picks,
    }
    n_core = sum(1 for p in picks if p["tier"] == "core")
    n_watch = sum(1 for p in picks if p["tier"] == "watch")
    print(f"picks: {len(picks)}頭中 core{n_core}頭 watch{n_watch}頭 / "
          f"新規帯入り{len(new_entries)}頭")

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
