# -*- coding: utf-8 -*-
"""Discord Webhook 通知 (任意機能)。

環境変数 DISCORD_WEBHOOK_URL が設定されていれば、新規に帯入りした馬を通知する。
同一馬 (race_id + horse_number) への通知は1回まで — 呼び出し側が
entered_band_at の初回設定時のみ呼ぶことで保証する。
Webhook URL はコード・JSONに書かない (GitHub Secrets / 環境変数のみ)。
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)


TIER_LABELS = {"core": "推奨", "watch": "参考"}


def notify_new_picks(new_picks):
    """new_picks: [{venue_name, race_number, post_time, horse_number, horse_name,
    odds_win, tier}]"""
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url or not new_picks:
        return False
    lines = ["🏇 逆・血統ビーム 新規帯入り"]
    # core(推奨) を先に、watch(参考) を後に
    ordered = sorted(new_picks, key=lambda p: 0 if p.get("tier") == "core" else 1)
    for p in ordered:
        label = TIER_LABELS.get(p.get("tier"), "?")
        lines.append(
            f"[{label}] {p.get('post_time', '--:--')} "
            f"{p.get('venue_name', '?')}{p.get('race_number', '?')}R "
            f"{p.get('horse_number', '?')}番 {p.get('horse_name', '?')} "
            f"単勝{p.get('odds_win', '?')}倍"
        )
    try:
        resp = requests.post(url, json={"content": "\n".join(lines)}, timeout=15)
        resp.raise_for_status()
        logger.info("Discord通知 %d件", len(new_picks))
        return True
    except requests.RequestException as e:
        # 通知失敗でバッチは落とさない (picks.json 更新が主目的)
        logger.warning("Discord通知失敗: %s", e)
        return False
