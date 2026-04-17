# Notion OKR duplicator

最新の `対象期間` を持つレコード群を Notion API で複製するローカル実行スクリプトです。  
**デフォルトは dry-run** で、`--execute` もしくは `NOTION_EXECUTE=true` を付けたときだけ実際に複製します。

## できること

- `page ID` / `database ID` / `data source ID` のどれからでも起動
- ページ配下の child database を自動検出
- 最新の `対象期間` を判定
- その `対象期間` を持つ行を複製
- ただし `対象期間`・`Objects`・`Keys` が重複する場合は、**作成日時が最新の 1 件だけ**を複製
- 複製して作る行の `実施結果` は **空欄** にする
- 同じ `対象期間`・`Objects`・`Keys` の組み合わせで、**本日作成された空欄のコピー**（`作成日時=振り返り日` ベース）がすでにある場合はスキップ
- `対象期間` は元データのまま維持
- Shortcuts / Raycast から呼びやすい shell wrapper 付き

## セットアップ

1. Notion integration を作成する
2. 対象 DB をその integration に共有する
3. `.env.local.example` を `.env.local` にコピーする
4. `NOTION_TOKEN` と、`NOTION_PAGE_ID` / `NOTION_DATABASE_ID` / `NOTION_DATA_SOURCE_ID` のいずれかを設定する

```bash
cd /Users/shiratorinaoki/scripts/notion-okr-duplicator
chmod +x run_okr_duplicate.sh okr_duplicate.py
./run_okr_duplicate.sh
```

このフォルダには `.env.local` を作成済みなので、通常は `NOTION_TOKEN` を追記するだけで使えます。  
既定値は **database ID 優先** にしてあり、親ページが integration に共有されていなくても動かしやすくしています。
`.env.local` は Git 管理対象外です。
`.env.local.example` には実トークンではなくプレースホルダーだけを入れています。

## 実行

### まずは dry-run

```bash
./run_okr_duplicate.sh
```

### 実際に複製する

```bash
./run_okr_duplicate.sh --execute
```

または `.env.local` に以下を設定します。

```bash
NOTION_EXECUTE=true
```

### 件数を絞って確認する

```bash
./run_okr_duplicate.sh --limit 3
```

## Shortcuts 連携

macOS ショートカットで `シェルスクリプトを実行` を追加して、次を指定します。

```bash
/Users/shiratorinaoki/scripts/notion-okr-duplicator/run_okr_duplicate.sh --execute
```

これで Dock / メニューバー / キーボードショートカットから 1 クリック実行できます。

## Finder から 1 クリック実行

Finder で次をダブルクリックしても実行できます。

```bash
/Users/shiratorinaoki/scripts/notion-okr-duplicator/run_okr_duplicate.command
```

## Raycast 連携

このフォルダの `raycast_duplicate_latest_okr.sh` を Raycast Script Command として登録できます。  
もしくは Quicklink から次を呼べます。

```bash
/Users/shiratorinaoki/scripts/notion-okr-duplicator/run_okr_duplicate.sh --execute
```

## 補足

- `対象期間` の解析は `YYYY-MM`, `YYYY/MM`, `YYYY年M月`, `YYYYMM`, `YYYY-MM-DD` を想定しています
- relation が多すぎて Notion 側で省略表示される場合、その省略分はコピーされません
- Notion 内部アップロードの files プロパティは API 上そのまま安全に複製しづらいため、外部 URL の files だけコピーします
- `NOTION_BASE_URL` を変えるとモックサーバー相手の疎通確認もできます
- `NOTION_PAGE_ID` を使う場合は、その **ページ自体** も integration に共有されている必要があります。DB だけ共有している場合は `NOTION_DATABASE_ID` か `NOTION_DATA_SOURCE_ID` を使ってください

## 404 が出るとき

`Could not find page/database/data source` が出る場合は、ID の間違いより **integration の接続漏れ** のことが多いです。

1. Notion で対象の `OKR` ページ、またはその中の inline database を開く
2. 右上の `•••` を開く
3. `Add connections` を選ぶ
4. `振り返りAutomation` を接続する
5. その後にもう一度 `./run_okr_duplicate.sh` を実行する

親ページに接続すると、その子要素も API から見えるようになります。inline database 側で接続しても構いません。
