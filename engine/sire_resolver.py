# -*- coding: utf-8 -*-
"""父(sire)解決チェーン (docs/DESIGN.md §4.3)。

1. data/sire_cache.json (horse_id → 父名) をルックアップ
2. ミスなら血統表ページをスクレイプ
3. 解決分はキャッシュへ追記 (馬の父は不変なので無効化不要・単調増加)
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "sire_cache.json"


class SireResolver:
    def __init__(self, ped_scraper=None, cache_path=CACHE_PATH):
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text())
        self.ped_scraper = ped_scraper
        self.new_entries = {}

    def resolve(self, horse_id):
        """父名を返す。解決できない場合は None (candidate判定でOTHER扱いになる)。"""
        cached = self.cache.get(horse_id)
        if cached:
            return cached
        if self.ped_scraper is None:
            return None
        try:
            name = self.ped_scraper.sire_name(horse_id)
        except Exception as e:
            logger.warning("sire解決失敗 horse_id=%s: %s", horse_id, e)
            return None
        self.cache[horse_id] = name
        self.new_entries[horse_id] = name
        return name

    def save(self):
        """新規解決分があればキャッシュファイルへ追記保存する。"""
        if not self.new_entries:
            return False
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=0) + "\n")
        logger.info("sire_cache に %d 件追記 (計 %d 件)", len(self.new_entries), len(self.cache))
        return True
