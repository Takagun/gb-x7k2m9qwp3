# Claude Code への実装指示(このままコピペ可)

---

`CLAUDE.md` と `docs/DESIGN.md` を読んでから着手してください。gyaku-beam(逆・血統ビーム週末推奨アプリ)を以下のフェーズ順で実装します。各フェーズ完了時に `make test` を通してからコミットしてください。判定ルール・同梱フィクスチャ(golden.json / e2e_day_20260425.json / siretype.py / sire_cache.json)は検証済みの確定値なので変更禁止です。

このアプリの利用者は私1人で、**利用シーンの9割はスマホ(iPhone)・片手操作**です。小さい娘を抱えたまま、レースの合間に数秒だけ見る、という使い方が基本になります。フロントエンドはこの前提を最優先してください(Phase 3に詳細)。

## Phase 1: ルールエンジン + バックテスト(スクレイピングなしで完結)

1. `engine/rules.py`: DESIGN.md §2 の判定式を実装(candidate判定 / 帯判定10.0≦odds<50.0 / 芝1000m千直の明示除外 / 中京(07)warning / 理由テキスト生成)。`engine/siretype.py` の `classify` を使う。
2. `engine/backtest.py`: `--db` で keiba.db(SQLite)の全結果行にルールを適用し、`tests/fixtures/golden.json` と n・回収率の完全一致を検証。`--replay 2026-04-25` で `e2e_day_20260425.json` と候補・帯内判定が一致することを検証。スキーマは races/entries/results/horses/sires/venues(../src/database/models.py 参照、venues のカラム名は code)。scratched=0 と finish_position NOT NULL で絞る。
3. `tests/test_rules.py`: DESIGN.md §6.1 のゴールデンケース(境界値: 9.9/10.0/49.9/50.0、千直、ダート、根幹距離、中京)。
4. **合格基準**: `make backtest` が golden 完全一致(全体 n=14,577 / 80.9%、帯内 n=5,298 / 99.5%、E2E 候補56・帯内20)。一致しないまま Phase 2 に進むこと禁止。

## Phase 2: スクレイパー + バッチ

5. `engine/scraper.py`: BaseScraper(2〜4秒ランダムディレイ / リトライ3回 / EUC-JP / 直列のみ)+ RaceList(kaisai_date→race_id展開)+ Shutuba(レース情報・出走馬)+ Ped(父解決。**血統表はリンク出現順の先頭だけが父で、2番目以降は父父・父父父**という罠に注意)+ OddsAPI。仕様は DESIGN.md §4。`../src/scraper/` の実装を参考・コピー改変してよい。
6. `engine/build_weekly.py` / `engine/update_odds.py`: JSON契約(DESIGN.md §5)どおり site/data/ を生成。`--dry-run` と `--date YYYYMMDD` オプション付き。sire解決は sire_cache → ped の順、新規解決分はキャッシュへ追記。
7. `engine/notify.py`: 環境変数 DISCORD_WEBHOOK_URL があれば新規帯入り馬を通知(同一馬は1回まで)。
8. `tests/test_parsers.py`: 実HTMLを network マーク付きテストで1度取得して tests/fixtures/ に保存し、以後はフィクスチャでパーサをテスト(CIは network 除外)。
9. パース失敗時はワークフローを fail させる(黙って空JSONを出さない)。

## Phase 3: PWAフロントエンド(最重要フェーズ — スマホ片手利用に全振り)

10. `site/` に vanilla JS + 単一CSSで実装。ビルドツール禁止。設計原則は「**3秒で分かる・親指だけで操作できる・電波が悪くても開く**」。

**レイアウト(モバイルファースト、基準幅375px)**
- 画面上部: 更新時刻と「オッズ更新」ボタン(タップでdata再fetch、更新中はスピナー)。
- その下: **次に発走が近い推奨馬を最上部に大きく**(ヒーローカード)。以降、発走時刻順のカードリスト。終わったレース(発走時刻超過)は自動で下部の「終了」セクションへ。
- 日付切替(土/日)は**画面下部の固定タブバー**に置く(親指の届く位置。上部タブは禁止)。タブバーは 土 / 日 / 実績 の3タブ。safe-area-inset-bottom を考慮。
- 帯外候補は「候補(帯外) n頭」の折りたたみ行として推奨リストの下に。展開もワンタップ。

**推奨カード(グランス最適化)**
- 1枚のカードで完結: 1行目「**14:25 新潟9R** 芝1800」+ 発走までの残り時間(30分切りで強調色)。2行目「**7番 サンプルホース**」を最大フォント(20px+)で。3行目にオッズバッジ「単勝 14.2倍」(帯内=アクセント色の塗りバッジ)。4行目に理由チップ(「父キズナ=日本型」「1800m=非根幹」「10-50倍帯」)。中京のみ警告バッジ「中京は効き弱(検証済)」。
- カード全体をタップで詳細展開(年別実績 2023:99.6%→2026:132.0%、netkeibaの出馬表へのリンク)。誤タップに寛容に: 破壊的操作は一切置かない。
- 推奨0頭の日は「今日は該当なし。買わないのも戦略」と大きく表示(空画面にしない)。

**操作性・視認性の必須要件**
- タップターゲットは最小44×44px、隣接要素と8px以上の間隔。
- 本文16px以上、馬名・オッズは太字20px以上。屋外視認のためコントラスト比4.5:1以上。
- `prefers-color-scheme` でライト/ダーク自動切替(夜間の授乳・寝かしつけ中に眩しくないダークを既定同等の品質で)。
- ホバー依存の操作を作らない。横スクロール禁止。アニメーションは150ms以下、`prefers-reduced-motion` 尊重。
- `viewport-fit=cover` + safe-area対応、`user-scalable=yes` のまま(拡大を殺さない)。
- 片手持ちを想定し、重要な操作(タブ・更新)はすべて画面下半分に配置。

**PWA・パフォーマンス**
- manifest.json(standalone、テーマカラー、192/512アイコン — シンプルな「逆」1文字のSVG生成アイコンでよい)+ apple-touch-icon。iPhoneの「ホーム画面に追加」で全画面起動すること。
- sw.js: シェルはcache-first、site/data/*.json はnetwork-first+キャッシュフォールバック。**圏外でも最後に取得したpicksが表示される**こと(スタレ表示時は「◯時◯分時点」を明示)。
- 依存ライブラリゼロ、初回ロード合計100KB以下(アイコン除く)、Lighthouse(mobile)で Performance・Accessibility・PWA 各90以上。
- `<meta name="robots" content="noindex,nofollow">`、フッターに免責(過去実績は将来を保証しない/馬券は自己責任)。

11. 表示確認用サンプルJSON(candidates/picks/meta — meta.jsonにgolden.json由来の年別実績を入れる)を site/data/ に置く。推奨あり/推奨0/オッズ未発売の3状態を確認できるサンプルを用意し、`make serve` + Chrome DevToolsのiPhone SE/14 Proエミュレーションで両状態のスクリーンショットを撮って確認すること。

## Phase 4: CI/CD + デプロイ

12. `.github/workflows/`: ci.yml(pytest -m "not network and not db" + ruff)/ weekly.yml(木金21:00 JST = `0 12 * * 4,5` UTC)/ odds.yml(土日8:00 = `0 23 * * 5,6`、9:00-16:00毎時 = `0 0-7 * * 6,0`)/ pages.yml(site/** 変更時デプロイ)。バッチコミットは `[skip ci]` 付き、両バッチに workflow_dispatch を付ける。
13. `bootstrap.sh`: gh CLI でプライベートリポジトリ作成(推測不能な名前)→ push → Pages有効化(build_type=workflow)→(任意)`gh secret set DISCORD_WEBHOOK_URL`。冪等に。
14. `README.md`: セットアップ、運用スケジュール、手動実行、iPhoneのホーム画面追加手順、kill-switch基準(四半期の verify_factors で2期連続80%未満なら運用停止)。

**最終確認**: CLAUDE.md「完了の定義」5項目+ Phase 3 のLighthouse基準を満たすこと。

---

## 補足コンテキスト(判断に迷ったら)

- 理由表示・実績ラインの数値の出典は `tests/fixtures/golden.json`(2023:99.6 / 2024:96.0 / 2025:94.9 / 2026:132.0、帯内n=5,298)。フロントは meta.json 経由で表示。
- オッズは発売開始まで(概ね前日夜〜当日朝)APIが空。空なら全picks in_band=false のまま表示(「オッズ発売待ち」バッジ)。エラーにしない。
- 出走取消はオッズ欠落で自然に帯外へ落ちるので特別処理不要。
- 迷ったら「機能を足す」より「タップ数を減らす」を選ぶこと。
