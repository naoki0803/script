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

## GitHub Actions 連携（iPhone から実行したい場合）

このリポジトリには、iPhone のショートカットや GitHub API から起動できる
`workflow_dispatch` 用 workflow を追加しています。

ファイル:

```text
.github/workflows/notion-okr-duplicate.yml
```

### 1. GitHub に push する

workflow は GitHub 上に存在してはじめて実行できるので、まずこのリポジトリを push します。

### 2. GitHub Secrets を設定する

リポジトリ `Settings > Secrets and variables > Actions` で、最低限これを設定します。

```text
NOTION_TOKEN
NOTION_DATA_SOURCE_ID
```

必要に応じて次も設定できます。

```text
NOTION_PAGE_ID
NOTION_DATABASE_ID
NOTION_CHILD_DATABASE_TITLE
NOTION_DATA_SOURCE_NAME
NOTION_BASE_URL
NOTION_PERIOD_PROPERTY
NOTION_OBJECT_PROPERTY
NOTION_KEY_PROPERTY
NOTION_TIMEOUT_SECONDS
```

通常は `NOTION_TOKEN` と `NOTION_DATA_SOURCE_ID` だけで足ります。  
`NOTION_EXECUTE` や `NOTION_LIMIT` は workflow 起動時の input で渡すので、Secrets に入れなくて大丈夫です。

### 3. GitHub で手動実行する

GitHub の `Actions` タブから `Notion OKR duplicate` を開き、
`Run workflow` を押すと実行できます。

- `execute=false` なら dry-run
- `execute=true` なら本番実行
- `limit` は空欄なら全件

### 4. iPhone のショートカットから起動する

GitHub の fine-grained personal access token を 1 つ用意します。

- 対象リポジトリ: `naoki0803/script`
- 権限: **Actions = Write**

そのうえで iPhone のショートカットで `URL の内容を取得` を使って、
次の API を `POST` します。

```text
https://api.github.com/repos/naoki0803/script/actions/workflows/notion-okr-duplicate.yml/dispatches
```

ヘッダー:

```text
Accept: application/vnd.github+json
Authorization: Bearer <YOUR_GITHUB_TOKEN>
X-GitHub-Api-Version: 2026-03-10
Content-Type: application/json
```

本文の例（本番実行）:

```json
{
  "ref": "main",
  "inputs": {
    "execute": "true",
    "limit": ""
  }
}
```

本文の例（dry-run）:

```json
{
  "ref": "main",
  "inputs": {
    "execute": "false",
    "limit": ""
  }
}
```

ショートカットの最小構成はこれです。

1. `辞書` で JSON 本文を組む
2. `URL` に dispatch API を入れる
3. `URL の内容を取得`
4. `通知を表示` で「起動しました」を出す

これで iPhone から 1 タップで、**今と同じ `run_okr_duplicate.sh` ベースの処理**を GitHub Actions 上で実行できます。

## 補足

- `対象期間` の解析は `YYYY-MM`, `YYYY/MM`, `YYYY年M月`, `YYYYMM`, `YYYY-MM-DD` を想定しています
- relation が多すぎて Notion 側で省略表示される場合、その省略分はコピーされません
- Notion 内部アップロードの files プロパティは API 上そのまま安全に複製しづらいため、外部 URL の files だけコピーします
- `NOTION_BASE_URL` を変えるとモックサーバー相手の疎通確認もできます
- `NOTION_PAGE_ID` を使う場合は、その **ページ自体** も integration に共有されている必要があります。DB だけ共有している場合は `NOTION_DATABASE_ID` か `NOTION_DATA_SOURCE_ID` を使ってください
- iPhone 側には Notion token ではなく **GitHub の起動用 token** だけを置く構成なので、Notion token を端末に持ち歩かずに運用できます

## 404 が出るとき

`Could not find page/database/data source` が出る場合は、ID の間違いより **integration の接続漏れ** のことが多いです。

1. Notion で対象の `OKR` ページ、またはその中の inline database を開く
2. 右上の `•••` を開く
3. `Add connections` を選ぶ
4. `振り返りAutomation` を接続する
5. その後にもう一度 `./run_okr_duplicate.sh` を実行する

親ページに接続すると、その子要素も API から見えるようになります。inline database 側で接続しても構いません。
