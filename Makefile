KEIBA_DB ?= ../data/keiba.db
PY ?= python3

.PHONY: test test-net backtest weekly odds serve

test:
	$(PY) -m pytest -m "not network and not db" -q
	$(PY) -m ruff check .

test-net:
	$(PY) -m pytest -q
	$(PY) -m ruff check .

backtest:
	$(PY) -m engine.backtest --db $(KEIBA_DB)

meta:
	$(PY) -m engine.make_meta --db $(KEIBA_DB)

results:
	$(PY) -m engine.collect_results --dry-run

weekly:
	$(PY) -m engine.build_weekly --dry-run

odds:
	$(PY) -m engine.update_odds --dry-run

serve:
	cd site && $(PY) -m http.server 8000
