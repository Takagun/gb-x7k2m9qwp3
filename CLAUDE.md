# gyaku-beam — Claude Code 向けプロジェクト規約

個人用・逆血統ビーム週末推奨アプリ。正式仕様は `docs/DESIGN.md`。実装手順は `docs/PROMPT.md`。

## 絶対に守ること

- **判定ルール・閾値(芝/非根幹/JP型/10-50倍/千直除外)を変更しない。** これらは3年半の実データ検証で確定した値(根拠: ../Keiba/docs/factors/02)。「改善」を提案したくなっても実装せず、TODOコメントに留める。
- **編集禁止ファイル**: `engine/siretype.py`(検証済み血統マッピング)、`data/sire_cache.json`、`tests/fixtures/golden.json`、`tests/fixtures/e2e_day_20260425.json`。テストをこれらに合わせる方向のみ可。フィクスチャをテストに合わせる変更は禁止。
- スクレイピングは必ず2〜4秒のランダムディレイ+リトライ3回+タイムアウト15秒。並列リクエスト禁止。netkeibaはEUC-JP。
- 依存は最小限: `requests`, `beautifulsoup4`, `pytest`, `ruff` のみ。pandasはengine本体には入れない(backtest.pyのみ可)。フロントはビルドツールなしのvanilla JS。
- 秘密情報(Discord Webhook URL等)はコード・JSONに書かない。GitHub Secrets / 環境変数のみ。

## コマンド規約(Makefile を用意すること)

```
make test        # pytest -m "not network and not db" + ruff check
make test-net    # ネットワーク込みテスト(ローカルのみ)
make backtest    # engine/backtest.py --db $(KEIBA_DB) → golden.json/E2E照合
make weekly      # ローカルで build_weekly.py を実行(dry-run既定)
make odds        # ローカルで update_odds.py を実行
make serve       # python -m http.server で site/ をプレビュー
```

`KEIBA_DB` の既定値は `../data/keiba.db`(このリポジトリはKeiba/gyaku-beam/に置かれている前提)。

## 完了の定義

1. `make test` が全パス(CIと同一)
2. `make backtest` が golden.json と n=14,577 / 80.9% / n=5,298 / 99.5% を完全一致で再現し、E2Eリプレイ(2026-04-25: 候補56/帯内20)も一致
3. `make serve` でスマホ幅・PC幅の両方で表示が破綻しない(picks空状態のプレースホルダ含む)
4. `bootstrap.sh` 実行で GitHub リポジトリ作成→push→Pages有効化まで通る
5. README.md に運用手順(cron時刻、手動実行、kill-switch基準)が書かれている

## ディレクトリ構成(維持すること)

```
engine/   Python(判定・スクレイプ・バッチ・バックテスト)
site/     静的PWA(Pagesデプロイ対象)。site/data/ はActionsが更新
data/     sire_cache.json ほかシードデータ
tests/    pytest(fixtures/はゴールデン・変更禁止)
docs/     DESIGN.md(仕様の正)・PROMPT.md(実装手順)
.github/workflows/  ci / weekly / odds / pages
```
