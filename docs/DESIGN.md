# gyaku-beam ハーネス設計書

逆・血統ビーム(Factor 02)単体にフォーカスした個人用の週末推奨馬アプリ。
本書は実装者(Claude Code)向けの正式仕様。数値・判定式は `../Keiba/docs/factors/02_主流血統×非根幹距離ファクター.md` の検証結果に基づき、**勝手に変更しないこと**。

---

## 1. 目的とスコープ

- その週のJRAレースから「逆・血統ビーム」該当馬を抽出し、**理由と実績データを添えて** PC/スマホで表示する。
- 個人利用。公開SaaSにしない(ファクターは公開すると減衰する)。
- MLモデルなし。**ルールベース+バッチ+静的PWA** の最小構成。
- 既存Keibaアプリとはコード・DB・デプロイを完全分離(sire_cache 等のシードデータだけ持ち込む)。

## 2. 判定ルール(ルールエンジン仕様 — 変更禁止)

**v2ルール(2026-07-20確定。検証記録: ../Keiba/docs/factors/02b, 02c)**

```
candidate(候補) = 芝レース
              AND distance % 400 != 0        # 非根幹距離
              AND distance != 1000           # 千直は明示除外
              AND stype(父) == "JP"          # 日本型主流血統 (engine/siretype.py)
              AND venue != 中京(07)          # v2: 検証で効かない会場を除外
除外(exclusion) = 前走から121日以上           # 長期休養明け
              OR 馬体重 <= 440kg             # 小柄馬
              OR 距離が前走比 +200m以上       # 延長ローテ
              # 除外馬は「候補(除外)」として理由付きでグレー表示(非表示にはしない)
pick_core(推奨) = candidate AND NOT excluded AND 10.0 <= 単勝オッズ < 30.0
pick_watch(参考) = candidate AND NOT excluded AND 30.0 <= 単勝オッズ < 50.0
                 # watch層は表示のみ(購入対象外)。検証記録: ../Keiba/docs/factors/02c
```

- core層の実績(確定オッズ・ベタ買い): 全期間 n=1,878 / 単勝119.5%、年別 116/114/119/168%(全年100%超)、
  半期別も全7期100%以上、ブートストラップ95%CI 101-139%、P(>100%)=98%。理由表示・実績ラインはこの値を使う。
- watch層(30-50倍)は3年半で19勝とサンプル希薄なため参考表示に降格(pool 104.5%だがB期間の対市場超過勝率0.92)。
- 前走情報(日付・距離)が取れない馬(初出走・地方転入等)は除外しない(候補に残す)。
- 馬体重は出馬表で当日朝に発表される。未発表の間は前走馬体重で仮判定し、
  オッズバッチ実行時に当日値で再判定する。前走値も無い場合は除外しない。

- `engine/siretype.py` は検証済みの確定マッピング。**編集禁止**(種牡馬の追加はTakahiroの判断で行う)。
- 芝1000m(千直)は非根幹に含まれない(1000%400=200 → 含まれてしまうので **明示除外する**。
  検証で千直は効かないことが確認済み: 回収率60.2%)。
- 理由表示テンプレート:
  `父{sire_name}(日本型主流)× {venue_name}芝{distance}m(非根幹)× 単勝{odds}倍(コア妙味帯10-30倍)`
  + 補足行: `コア帯の過去実績: 2023年116% / 24年114% / 25年119% / 26年168%(単勝ベタ買い回収率・全年100%超)`
  watch層(30-50倍)は `参考: 30-50倍はデータ希薄のため購入対象外` を付す。

## 3. 全体アーキテクチャ

```
[GitHub Actions cron]
  weekly.yml  木曜21:00 & 金曜21:00 JST
    └─ engine/build_weekly.py
        1. 週末(翌土日)のrace_id一覧を取得
        2. 各レースの出馬表(馬番/馬名/horse_id/距離/馬場/発走時刻)を取得
        3. 父を解決(下記チェーン) → ルール判定
        4. site/data/candidates.json を生成しcommit/push
  odds.yml    土日 8:00〜16:00 JST 毎時
    └─ engine/update_odds.py
        1. candidates.json の候補レースのみ単勝オッズを取得
        2. tier判定(core 10-30 / watch 30-50)→ site/data/picks.json 更新、commit/push
        3. 新規に帯入りした馬があれば Discord Webhook 通知(任意)
  pages.yml   push時に site/ を GitHub Pages へデプロイ
[閲覧]  PC/スマホのブラウザ → Pages上のPWA(ホーム画面に追加可)
```

- 実行環境は GitHub Actions のみ(Mac常時起動不要)。プライベートリポジトリ。
- Pages URLは実質公開になるため、`<meta name="robots" content="noindex">` + 推測不能なリポジトリ名を使う。
  さらに秘匿したければ Cloudflare Pages + Access に載せ替え可能な構成にしておく(site/は純静的なので移設自由)。

## 4. データソース仕様(netkeiba)

既存Keibaアプリのスクレイパーで実証済みのアクセスパターンを踏襲する(礼儀: リクエスト間 2〜4秒ランダムディレイ、リトライ3回、UA明示)。

### 4.1 race_id 発見
- 形式: `YYYYVVRRDDNN` 12桁(YYYY=年, VV=会場01-10, RR=回, DD=日目, NN=レース番号01-12)。
- 未来日は `https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=YYYYMMDD`(サーバレンダリング
  の日別一覧断片)の `race_id=` リンクから対象日の実在IDを収集 → 会場コード01-10のみ残す。展開不要。
- 保険: 上記が空なら `https://race.netkeiba.com/top/?kaisai_date=YYYYMMDD` のHTML中に埋まる12桁IDを
  正規表現 `\b(20[2-9]\d{9})\b` で収集 → 会場コード01-10のみ残す → シードIDから同開催のR01-12へ展開。
  (Keiba/src/scraper/race_list_scraper.py の `_expand_to_full_card` 方式をそのまま移植してよい)
  ⚠️ トップ本体はJSシェルで対象日と無関係な注目レースIDしか含まないことがある(2026-07-23の週次
  バッチ全滅の原因)。このルートの結果は必ず出馬表側の開催日と照合すること。

### 4.2 出馬表
- `https://race.netkeiba.com/race/shutuba.html?race_id={race_id}`(EUC-JP)。
- レース情報: ページ上部テキスト `"15:45発走 / 芝2000m (右 B)"` `"2回 福島 6日目"` を正規表現で抽出
  (`(\d{1,2}:\d{2})発走`, `(芝|ダ)(\d{3,4})m`)。
- 出走馬: 各行に `https://db.netkeiba.com/horse/{horse_id}` 形式のリンクがあり horse_id と馬名が取れる。
  馬番は同行のセルから。**父名は出馬表ページからは安定して取れない前提**で、4.3のチェーンで解決する。
- 発売前は「人気」列が `**` でオッズ非表示 → 出馬表段階ではオッズを扱わない(candidates固定のみ)。

### 4.3 父(sire)の解決チェーン
1. `data/sire_cache.json`(23,006頭を同梱済み: horse_id → 父名)をルックアップ
2. キャッシュミス(新馬など)は `https://db.netkeiba.com/horse/ped/{horse_id}/`(EUC-JP)の
   `table.blood_table` の **先頭行の最初のリンクが父**。
   ⚠️ **重要な罠**: リンク出現順の2番目以降は「父父・父父父」であり母ではない(rowspan構造)。
   父だけ取るなら先頭リンクで正しい。母父は `rows[len(rows)//2]` の先頭セル側(今回は不要)。
3. 解決した父は sire_cache.json に追記して commit(キャッシュは単調増加、馬の父は不変なので無効化不要)。

### 4.4 前走情報(v2の除外判定用)

- 候補馬(ふるい①〜③通過馬のみ、週末あたり数十頭)について
  `https://db.netkeiba.com/horse/{horse_id}/`(EUC-JP)の戦績テーブルから
  **直近出走の日付・距離・馬体重** を取得する。
- 戦績テーブルは日付降順。先頭行から `日付`, `距離`(例: `芝1800`), `馬体重`(例: `472(+4)`)を抽出。
- 結果は `data/form_cache.json`(horse_id → {last_date, last_distance, last_weight})にキャッシュし、
  **同一週末内のみ有効**(週をまたいだら破棄。sire_cacheと違い前走情報は変わるため)。
- 取得失敗時は除外判定をスキップ(候補に残す)し、picks.json に `form_missing: true` を立てる。

### 4.5 単勝オッズ
- JSON API: `https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=update`
  → `data.odds["1"]` が `{"01": ["7.2", ...], ...}`(馬番ゼロ埋めキー、[0]がオッズ文字列)。
- フォールバック: `https://odds.sp.netkeiba.com/?race_id={race_id}&type=1` のHTMLテーブル。
- (Keiba/src/scraper/odds_scraper.py と同一仕様。移植可)

## 5. JSON契約(site/data/)

```jsonc
// candidates.json — 木・金バッチが生成、週末中は不変
{
  "generated_at": "2026-07-23T21:05:00+09:00",
  "weekend": ["2026-07-25", "2026-07-26"],
  "races": [{
    "race_id": "202604020601", "date": "2026-07-25", "venue_code": "04",
    "venue_name": "新潟", "race_number": 6, "post_time": "12:55",
    "surface": "芝", "distance": 1800, "race_name": "3歳未勝利",
    "chukyo_warning": false,
    "candidates": [{
      "horse_number": 3, "horse_id": "2023101234", "horse_name": "サンプルホース",
      "sire_name": "キズナ", "stype": "JP"
    }]
  }]
}
// picks.json — オッズバッチが毎時更新
{
  "updated_at": "2026-07-25T10:00:00+09:00",
  "odds_asof": "10:00",
  "picks": [{
    "race_id": "202604020601", "horse_number": 3, "odds_win": 14.2,
    "tier": "core",   // "core" | "watch" | null(帯外)
    "entered_band_at": "2026-07-25T09:00:00+09:00", "form_missing": false
  }]
}
// meta.json — 実績表示用の静的データ(golden.jsonのサブセット) + 免責
```

- フロントは candidates.json と picks.json を突き合わせて表示(tier=core が「推奨」、watch が「参考」、null は「候補(帯外)」としてグレー表示)。
- race_id・馬番のみで結合できる設計にする(horse_id はリンク用)。

## 6. 検証ハーネス(実装の合否はこれで判定)

### 6.1 ユニット: ルールエンジン
- `tests/test_rules.py`: 判定式のゴールデンテスト。
  例: (芝,1800,キズナ)→candidate / (芝,2000,キズナ)→非該当 / (ダ,1800,キズナ)→非該当 /
  (芝,1400,ドレフォン)→非該当 / (芝,1000,ロードカナロア)→非該当(千直除外) /
  オッズ9.9→帯外, 10.0→core, 29.9→core, 30.0→watch, 49.9→watch, 50.0→帯外 / 中京→候補外 /
  前走2000m→今走1800m(短縮)→除外なし, 前走1600m→今走1800m(+200m延長)→除外, 休養121日→除外, 馬体重440kg→除外。

### 6.2 パーサ: フィクスチャHTML
- `tests/fixtures/` に出馬表・ped・オッズJSONのサンプルを保存し、パーサ単体テスト。
  フィクスチャは初回実行時に実HTMLを保存して作る(ネットワークテストはCIでは実行しない。
  `@pytest.mark.network` でローカル限定)。

### 6.3 回帰: golden_v2.json(同梱済み・変更禁止)
- `tests/fixtures/golden_v2.json` は keiba.db(2023-01-05〜2026-05-10, 156,273行)で確定させた正解値:
  core(10-30倍) n=1,878 / 単勝119.5%、watch(30-50倍) n=691 / 104.5%、full n=2,569 / 115.4%、各年別値。
  (`golden.json` はv1=baseルールの参照値: セグメント全体 n=14,577 / 80.9%、10-50倍 n=5,298 / 99.5%)
- `engine/backtest.py --db path/to/keiba.db` がルールエンジンをDB全行に適用し、
  golden.json と **n・回収率が完全一致** することを確認する(ルールの実装ズレ検知)。
  ※ keiba.db が手元にある場合のみ実行(CIではskip)。stype判定は sire_name ベースで行う。

### 6.4 E2E: 過去日シミュレーション(同梱済み・変更禁止)
- `tests/fixtures/e2e_day_20260425_v2.json`: 2026-04-25(raw候補56→除外後19→core4・watch1、tier/除外理由付き)の正解セット。
- `engine/backtest.py --replay 2026-04-25 --db ...` が candidates/picks 生成パスを通して
  このJSONと一致する出力を出すこと(build_weekly と同じ判定コードパスを使うのが要件)。

### 6.5 CI
- `.github/workflows/ci.yml`: push/PR で `pytest -m "not network and not db"` + `ruff check`。

## 7. スケジュール(cron、UTC表記)

| ワークフロー | JST | cron (UTC) |
|---|---|---|
| weekly.yml | 木・金 21:00 | `0 12 * * 4,5` |
| odds.yml | 土日 8:00 | `0 23 * * 5,6` |
| odds.yml | 土日 9:00-16:00 毎時 | `0 0-7 * * 6,0` |

- weekly は対象日 = 実行日から見た次の土曜・日曜(+月曜開催があれば月曜も。祝日開催対応として
  `kaisai_date` ページに出た日付をそのまま使う)。
- odds は candidates.json が空なら即終了(コスト節約)。
- 手動トリガー(`workflow_dispatch`)を両方に付ける。

## 8. フロントエンド(site/ — 純静的PWA)

- vanilla JS + 単一CSS。ビルドツールなし(Pagesにそのまま置く)。
- モバイルファースト: 上部に日付タブ(土/日)、推奨馬カードのリスト。
  カード内容: 発走時刻・会場R・レース名 / 馬番・馬名 / オッズ(更新時刻付き) / 理由チップ3つ
  (血統・距離・オッズ帯) / 実績ライン(年別回収率) / 中京警告バッジ。
- 「候補(帯外)」セクションは折りたたみで下部に。オッズ更新は pull-to-refresh 相当の再fetchボタン。
- PWA: manifest.json(standalone, アイコン), sw.js(シェルはcache-first、data/*.json はnetwork-first)。
- `<meta name="robots" content="noindex,nofollow">` 必須。
- 免責表示: 「過去実績は将来の回収率を保証しない/馬券購入は自己責任」を常時フッターに。

## 9. デプロイ・git連携

- プライベートGitHubリポジトリ(推測不能な名前、例: `gb-notes-tk`)。
- `bootstrap.sh`: `gh auth status` 確認 → `gh repo create <name> --private` → push →
  Pages有効化(`gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow`) →
  Discord Webhook を `gh secret set DISCORD_WEBHOOK_URL` で登録(任意)。
- Actions の commit は `github-actions[bot]` 名義で `site/data/*.json` と `data/sire_cache.json` のみ。
  無限ループ防止: pages.yml は `paths: [site/**]`、weekly/odds は `[skip ci]` をコミットメッセージに付ける。

## 10. 運用・減衰監視

- 四半期ごとに既存Keibaアプリ側の `docs/factors/verify_factors.py` を実行し、F02セグメントの
  直近回収率を確認。2四半期連続で単勝80%未満なら本アプリの運用を停止する(kill-switch基準)。
- picks.json の履歴はgitに残るため、`engine/report.py`(任意実装)で「アプリが推奨した馬の実績」を
  月次集計できる(自分の実運用回収率のトラッキング)。

## 11. 実装しないこと(スコープ外)

- 複勝・馬連等の他券種 / MLモデル / 自動投票(IPAT連携はしない) / ユーザー認証 /
  DBサーバ / 他ファクターの追加(まず単一ファクターで実運用データを貯める)
