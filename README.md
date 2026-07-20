# gyaku-beam

逆・血統ビーム(検証済みFactor 02)単体の週末推奨馬アプリ(個人用)。

- 仕様の正: `docs/DESIGN.md`
- 実装規約: `CLAUDE.md`
- Claude Code への実装指示: `docs/PROMPT.md`

## 判定ルール(v2・変更禁止)

```
候補   = 芝 AND 距離%400≠0(非根幹) AND 千直(芝1000m)除外
         AND 父が日本型主流(JP) AND 中京(07)以外
除外   = 休養121日以上 OR 馬体重440kg以下 OR 前走比+200m以上の延長
         (前走情報が無い馬は除外しない。グレー表示で理由バッジ付き)
推奨   = 候補 AND NOT 除外 AND 単勝10.0〜29.9倍 (core)
参考   = 候補 AND NOT 除外 AND 単勝30.0〜49.9倍 (watch・購入対象外)
```

根拠: keiba.db 2023-01〜2026-05 の検証で core n=1,878 / 単勝回収率119.5%
(年別 116/114/119/168%・全年100%超、95%CI 101-139%)。watch n=691 / 104.5%。
(`tests/fixtures/golden_v2.json`)

## セットアップ

```sh
# 依存 (requests / beautifulsoup4 / pytest / ruff のみ)
pip3 install requests beautifulsoup4 pytest ruff

make test        # オフラインテスト + lint (CIと同一)
make test-net    # ネットワーク込み (実HTMLフィクスチャ取得、ローカルのみ)
make backtest    # golden_v2.json / golden.json / E2E v2 照合 (要 keiba.db: 既定 ../data/keiba.db)
make meta        # 実績タブ用 meta.json 再生成 (連敗状況・年別収支カーブ。要 keiba.db)
make results     # 週末結果の収集をdry-runで実行 (実運用トラッキング)
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
| results.yml | 月曜 9:00 | 週末候補レースの確定結果→history.json(実運用の答え合わせ) |
| pages.yml | site/** 変更時 | GitHub Pages デプロイ |
| ci.yml | push/PR | pytest + ruff |

手動実行: GitHub → Actions → weekly / odds → **Run workflow**。
ローカルなら `python3 -m engine.build_weekly --date 20260725` / `python3 -m engine.update_odds --date 20260725`。

## スマホのホーム画面に追加

**Android (Chrome):**
1. Chrome で Pages の URL を開く
2. メニュー(⋮)→ **「アプリをインストール」**(または「ホーム画面に追加」)
3. 以降は全画面(standalone)のアプリとして起動

**iPhone (Safari):** 共有ボタン → **ホーム画面に追加**。

どちらも圏外で開くと最後に取得した推奨が表示される(ヘッダの「◯:◯時点」が取得時刻)。

## 画面の見方

- 最上部の大きいカード = 次に発走が近い推奨馬(core)。発走30分前から残り時間が赤字
- **塗りつぶし**オッズバッジ = 推奨(core 10-30倍)。**枠線+「参考」** = watch(30-50倍・購入対象外)
- 馬名横のバッジ **休/小/延** = ネガ除外(休養121日+/馬体重440kg以下/延長200m+)。
  馬体重は当日朝の発表値で再判定される(それまでは前走値で仮判定)
- 「オッズ発売待ち」= 発売前(前日夜〜当日朝)。「候補(帯外・除外)」はタップで展開。
  終了レースは下部「終了」へ自動移動
- カードをタップすると年別実績・95%CI・除外理由の説明・netkeibaリンクを展開
- 推奨0頭の日は「今日は該当なし。買わないのも戦略」
- **実績タブ**は2部構成:
  - **実運用** = このアプリが実際にcore推奨した馬の答え合わせ(確定オッズ・
    毎週月曜に自動更新)。通算収支・回収率・連敗・累積収支カーブ
  - **検証** = keiba.db バックテストの連敗状況と年別収支カーブ(コアのみ・
    1点500円換算)。四半期ごとの verify_factors 実行後に `make meta` →
    commit/push で更新する

## kill-switch 基準(減衰監視)

四半期ごとに既存Keibaアプリ側で `python3 docs/factors/verify_factors.py data/keiba.db` を実行し、
F02セグメント(JP型×非根幹芝×10-50倍)の直近四半期回収率を確認する。

**2四半期連続で単勝回収率80%未満なら本アプリの運用を停止する。**
(停止 = weekly/odds ワークフローを Actions 画面で Disable)

## 注意

- 判定ルール・閾値・同梱フィクスチャ(golden.json / golden_v2.json /
  e2e_day_20260425.json / e2e_day_20260425_v2.json / siretype.py / sire_cache.json)
  は検証済み確定値。変更禁止
- スクレイピングは2〜4秒ディレイ・直列のみ。netkeibaに負荷をかけない
- Discord Webhook URL等の秘密情報は GitHub Secrets のみ(コード・JSONに書かない)
- フロント(site/sw.js)のシェルはcache-first。site/ のHTML/CSS/JSを変更したら
  `sw.js` の `VERSION` を上げること(データJSONはnetwork-firstなので不要)
- 過去実績は将来の回収率を保証しない。馬券購入は自己責任
