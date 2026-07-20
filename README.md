# gyaku-beam

逆・血統ビーム(検証済みFactor 02)単体の週末推奨馬アプリ(個人用)。

- 仕様の正: `docs/DESIGN.md`
- 実装規約: `CLAUDE.md`
- Claude Code への実装指示: `docs/PROMPT.md`(そのままコピペ可)

同梱シードデータ(変更禁止):
- `engine/siretype.py` — 検証済み国タイプ分類
- `data/sire_cache.json` — 23,006頭の horse_id→父名キャッシュ(keiba.db由来)
- `tests/fixtures/golden.json` — ルールエンジン回帰テストの正解値
- `tests/fixtures/e2e_day_20260425.json` — E2Eリプレイの正解セット(候補56/帯内20/勝利2)

実装後の運用: GitHub Actions(木金21時 候補確定 / 土日8-16時 オッズ更新)→ GitHub Pages のPWAをスマホのホーム画面に追加。
