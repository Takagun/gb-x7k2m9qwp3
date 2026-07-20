# -*- coding: utf-8 -*-
"""keiba.db がある環境限定の回帰テスト (CIでは -m "not db" でスキップ)。"""
import os
from pathlib import Path

import pytest

from engine import backtest

DB_PATH = os.environ.get("KEIBA_DB", str(Path(__file__).parents[2] / "data" / "keiba.db"))

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(not Path(DB_PATH).exists(), reason="keiba.db がない"),
]


def test_golden_exact_match():
    assert backtest.verify_golden(DB_PATH)


def test_e2e_replay_20260425():
    assert backtest.verify_replay(DB_PATH, "2026-04-25")
