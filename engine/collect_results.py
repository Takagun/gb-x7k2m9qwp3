# -*- coding: utf-8 -*-
"""週末結果の自動収集 — 実運用トラッキング (DESIGN.md §10 の report 相当)。

月曜朝に GitHub Actions (results.yml) から実行し、candidates.json の候補レースの
確定結果 (着順・確定単勝オッズ) を db.netkeiba のレースページから取得して
site/data/history.json に追記する。実績タブの「実運用」セクションが表示に使う。

- 冪等: 取得済み (race_id, 馬番) はスキップ。何度実行しても重複しない
- 施行前 (対象日が今日以降) のレースは対象外
- 個別レースの取得失敗はスキップして次回リトライ。全滅時のみ exit 1

使い方: python3 -m engine.collect_results [--dry-run]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.scraper import DbRaceScraper, ParseError

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "site" / "data" / "candidates.json"
PICKS_PATH = ROOT / "site" / "data" / "picks.json"
HISTORY_PATH = ROOT / "site" / "data" / "history.json"
JST = timezone(timedelta(hours=9))


def load_json(path, default):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text())


def entry_key(e):
    return (e["race_id"], e["horse_number"])


def collect(candidates, picks, history, scraper, today_iso):
    """未収集の施行済み候補レースの結果エントリを返す。(new_entries, n_errors)"""
    picks_map = {(p["race_id"], p["horse_number"]): p for p in picks.get("picks", [])}
    seen = {entry_key(e) for e in history.get("entries", [])}
    new_entries = []
    n_errors = 0
    for race in candidates.get("races", []):
        if race["date"] >= today_iso:
            continue  # 未施行
        todo = [c for c in race["candidates"]
                if (race["race_id"], c["horse_number"]) not in seen]
        if not todo:
            continue
        try:
            info = scraper.scrape(race["race_id"])
        except ParseError as e:
            print(f"  結果取得失敗 {race['race_id']}: {e} (次回リトライ)", file=sys.stderr)
            n_errors += 1
            continue
        finish = {h["horse_number"]: h.get("finish_position") for h in info["horses"]}
        final_odds = info.get("win_odds", {})
        for c in todo:
            num = c["horse_number"]
            p = picks_map.get((race["race_id"], num), {})
            new_entries.append({
                "race_id": race["race_id"],
                "date": race["date"],
                "venue_name": race["venue_name"],
                "race_number": race["race_number"],
                "distance": race["distance"],
                "horse_number": num,
                "horse_name": c["horse_name"],
                "tier": p.get("tier"),
                "excluded_reason": p.get("excluded_reason",
                                         c.get("excluded_reason", [])),
                "odds_app": p.get("odds_win"),      # アプリが最後に表示したオッズ
                "odds_final": final_odds.get(num),  # 確定オッズ (収支計算はこちら)
                "finish_position": finish.get(num),  # None = 取消・除外・中止
            })
    return new_entries, n_errors


def main(argv=None):
    ap = argparse.ArgumentParser(description="週末結果の自動収集")
    ap.add_argument("--dry-run", action="store_true", help="ファイルを書かず表示のみ")
    args = ap.parse_args(argv)

    candidates = load_json(CANDIDATES_PATH, {})
    picks = load_json(PICKS_PATH, {})
    history = load_json(HISTORY_PATH, {"entries": []})
    if not candidates.get("races"):
        print("candidates.json が空 — 即終了")
        return 0

    today_iso = datetime.now(JST).date().isoformat()
    new_entries, n_errors = collect(
        candidates, picks, history, DbRaceScraper(), today_iso)

    n_core = sum(1 for e in new_entries if e["tier"] == "core")
    print(f"新規 {len(new_entries)}頭 (うちcore {n_core}) / 取得失敗 {n_errors}レース")
    if not new_entries:
        if n_errors:
            print("NG: 新規結果を1件も取得できなかった", file=sys.stderr)
            return 1
        print("収集対象なし (すべて取得済みか未施行)")
        return 0

    entries = history.get("entries", []) + new_entries
    entries.sort(key=lambda e: (e["date"], e["race_id"], e["horse_number"]))
    out = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "entries": entries,
    }
    if args.dry_run:
        print(json.dumps(new_entries, ensure_ascii=False, indent=1))
        return 0
    HISTORY_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {HISTORY_PATH} (計 {len(entries)}頭)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
