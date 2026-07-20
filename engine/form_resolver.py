# -*- coding: utf-8 -*-
"""前走情報の解決チェーン (docs/DESIGN.md §4.4)。

1. data/form_cache.json (horse_id → {last_date, last_distance, last_weight}) をルックアップ
2. ミスなら馬ページをスクレイプ
3. キャッシュは **同一週末内のみ有効** (週をまたいだら破棄。前走情報は変わるため)
4. 取得失敗は除外判定スキップ (candidateに残す) + form_missing。失敗はキャッシュしない
   (次回実行でリトライさせる)。
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "form_cache.json"

MISSING = {"last_date": None, "last_distance": None, "last_weight": None, "form_missing": True}


class FormResolver:
    def __init__(self, form_scraper=None, cache_path=CACHE_PATH, weekend_key=None):
        """weekend_key: 対象週末の識別子 (土曜のISO日付)。不一致のキャッシュは破棄する。"""
        self.cache_path = Path(cache_path)
        self.weekend_key = weekend_key
        self.form_scraper = form_scraper
        self.dirty = False
        data = {}
        if self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text())
            except json.JSONDecodeError:
                logger.warning("form_cache が壊れているため破棄する")
        if data.get("weekend") != weekend_key:
            data = {"weekend": weekend_key, "horses": {}}
        self.horses = data.get("horses", {})

    def resolve(self, horse_id):
        """{last_date, last_distance, last_weight, form_missing} を返す。"""
        cached = self.horses.get(horse_id)
        if cached is not None:
            return {**cached, "form_missing": False}
        if self.form_scraper is None:
            return dict(MISSING)
        try:
            form = self.form_scraper.form(horse_id)
        except Exception as e:
            logger.warning("前走情報の取得失敗 horse_id=%s: %s", horse_id, e)
            return dict(MISSING)
        self.horses[horse_id] = form
        self.dirty = True
        return {**form, "form_missing": False}

    def save(self):
        """新規解決分があればキャッシュファイルへ保存する。"""
        if not self.dirty:
            return False
        self.cache_path.write_text(json.dumps(
            {"weekend": self.weekend_key, "horses": self.horses},
            ensure_ascii=False, indent=0) + "\n")
        logger.info("form_cache 保存 (%d 頭, weekend=%s)", len(self.horses), self.weekend_key)
        return True
