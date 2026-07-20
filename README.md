# gyaku-beam

逆・血統ビーム(検証済みFactor 02)単体の週末推奨馬アプリ(個人用)。

- 仕様の正: `docs/DESIGN.md`
- 実装規約: `CLAUDE.md`
- Claude Code への実装指示: `docs/PROMPT.md`

## 判定ルール(変更禁止)

```
候補   = 芝 AND 距離%400≠0(非根幹) AND 千直(芝1000m)除外 AND 父が日本型主流(JP)
推奨   = 候補 AND 単勝10.0〜49.9倍
中京07 = 除外しないが「効き弱」警告バッジ
```

根拠: keiba.db 2023-01〜2026-05 の検証で帯内 n=5,298 / 単勝回収率99.5%
(`tests/fixtures/golden.json`)。

## セットアップ

```sh
# 依存 (requests / beautifulsoup4 / pytest / ruff のみ)
pip3 install requests beautifulsoup4 pytest ruff

make test        # オフラインテスト + lint (CIと同一)
make test-net    # ネットワーク込み (実HTMLフィクスチャ取得、ローカルのみ)
make backtest    # golden.json / E2E 照合 (要 keiba.db: 既定 ../data/keiba.db)
make weekly      # build_weekly をdry-runで実行
make odds        # update_odds をdry-runで実行
make serve       # http://localhost:8000 で site/ をプレビュー
```

初回デプロイ(gh CLI 必要):

```sh
./bootstrap.sh                 # ランダム名でプライベートリポジトリ作成→push→Pages有効化
DISCORD_WEBHOOK_URL=... ./bootstrap.sh   # Discord通知も登録する場合
```

## 運用スケジュール(GitHub Actions・自動)

| ワークフロー | JST | 内容 |
|---|---|---|
| weekly.yml | 木・金 21:00 | 翌土日の出馬表→候補確定→candidates.json |
| odds.yml | 土日 8:00、9:00〜16:00毎時 | 候補レースのオッズ→picks.json、新規帯入りをDiscord通知 |
| pages.yml | site/** 変更時 | GitHub Pages デプロイ |
| ci.yml | push/PR | pytest + ruff |

手動実行: GitHub → Actions → weekly / odds → **Run workflow**。
ローカルなら `python3 -m engine.build_weekly --date 20260725` / `python3 -m engine.update_odds --date 20260725`。

## iPhone ホーム画面に追加

1. Safari で Pages の URL を開く(`bootstrap.sh` 完了時に表示)
2. 共有ボタン → **ホーム画面に追加**
3. 以降は全画面(standalone)で起動。圏外でも最後に取得した推奨が表示される
   (ヘッダの「◯:◯時点」が取得時刻)

## 画面の見方

- 最上部の大きいカード = 次に発走が近い推奨馬。発走30分前から残り時間が赤字
- 塗りつぶしオッズバッジ = 帯内(10〜50倍)。「オッズ発売待ち」= 発売前(前日夜〜当日朝)
- 「候補(帯外)」はタップで展開。終了レースは下部「終了」へ自動移動
- 中京のレースには「中京は効き弱(検証済)」バッジ(検証根拠: docs/factors/02)
- 推奨0頭の日は「今日は該当なし。買わないのも戦略」

## kill-switch 基準(減衰監視)

四半期ごとに既存Keibaアプリ側で `python3 docs/factors/verify_factors.py data/keiba.db` を実行し、
F02セグメント(JP型×非根幹芝×10-50倍)の直近四半期回収率を確認する。

**2四半期連続で単勝回収率80%未満なら本アプリの運用を停止する。**
(停止 = weekly/odds ワークフローを Actions 画面で Disable)

## 注意

- 判定ルール・閾値・同梱フィクスチャ(golden.json / e2e_day_20260425.json /
  siretype.py / sire_cache.json)は検証済み確定値。変更禁止
- スクレイピングは2〜4秒ディレイ・直列のみ。netkeibaに負荷をかけない
- Discord Webhook URL等の秘密情報は GitHub Secrets のみ(コード・JSONに書かない)
- フロント(site/sw.js)のシェルはcache-first。site/ のHTML/CSS/JSを変更したら
  `sw.js` の `VERSION` を上げること(データJSONはnetwork-firstなので不要)
- 過去実績は将来の回収率を保証しない。馬券購入は自己責任
