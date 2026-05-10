[EN](../en/custom-template.md) | [JA](../ja/custom-template.md)

# カスタムテンプレート・スタイル・アセット

spec-driven-presentation-maker は任意の `.pptx` ファイルをテンプレートとして使用できます。
テンプレートのレイアウト、カラー、フォント、プレースホルダーを自動解析するため、手動設定は不要です。

テンプレート以外にも、以下 4 種類のリソースをユーザー単位でカスタマイズできます。

- **テンプレート** (`.pptx`) — スライドマスター
- **スタイル** (`.html`) — エージェントが参照するデザインガイド
- **アセット** (`.svg` / `.png` 等の画像) — アイコン、ロゴ、イラスト
- **設定** (`config.json`) — 出力ディレクトリ、追加アセットソースなど

いずれもユーザーローカルに配置でき、`pip install --upgrade` やリポジトリの再 clone でも消えません。

---

## テンプレート解析の仕組み

`analyze_template` を呼び出すと、エンジンが .pptx ファイルを検査し、以下の情報を抽出します。

- **スライドレイアウト** — 名前、寸法、プレースホルダーの位置とサイズ
- **テーマカラー** — 背景色、アクセントカラー、テキストカラー
- **フォント** — 見出しフォントと本文フォント
- **プレースホルダー** — タイトル、本文、フッターの正確な座標

エージェントはこの情報を使って、テンプレートのデザインシステムに沿った正確な要素配置を行います。

---

## テンプレートの作成

PowerPoint、Google Slides、または Keynote（.pptx にエクスポート）でテンプレートを設計します。

1. **スライドレイアウトを定義** — 最低限、以下を作成:
   - タイトルスライドレイアウト
   - コンテンツスライドレイアウト（タイトルプレースホルダー + 本文エリア）
   - セクション区切りレイアウト（任意）
   - 白紙レイアウト（カスタムデザイン用）

2. **テーマカラーを設定** — スライドマスターのカラーテーマにブランドカラーを定義。エージェントがこれを読み取り、一貫して使用します

3. **フォントを設定** — スライドマスターに見出しフォントと本文フォントを定義。エージェントが自動抽出します

4. **クリーンに保つ** — レイアウトからサンプルコンテンツを削除。エージェントはプレースホルダーの位置を使って作業します

5. **スピーカーノートでレイアウト指示を追加** — 各レイアウトのサンプルスライドのスピーカーノートに使用方法の指示を記述できます。エージェントはテンプレート解析時にこれを読み取り、そのレイアウトでスライドを構築する際に従います。

   例:
   - 「このレイアウトは2カラム比較に使用してください」
   - 「画像は右側にのみ配置してください」
   - 「タイトルは1行に収めてください」

### ヒント

- わかりやすいレイアウト名を付けてください（例: 「Content with Image」「Two Column」）— エージェントがこの名前を読み取ります
- 背景色とテキスト色のコントラスト比 4.5:1 以上を確保してください
- `analyze_template` を実行して出力を確認し、テンプレートをテストしてください

---

## テンプレートの解析

### Layer 1（CLI）

```bash
# 全レイアウトを表示
uv run python3 scripts/pptx_builder.py analyze-template my-template.pptx

# 特定レイアウトの詳細
uv run python3 scripts/pptx_builder.py analyze-template my-template.pptx --layout "Content"
```

### Layer 2（MCP）

エージェントはデザインフェーズで `analyze_template` を自動的に呼び出します。直接依頼することもできます:

> 「テンプレートを解析して、利用可能なレイアウトを見せて」

### Layer 3（リモート）

テンプレートは S3 に保存され、Amazon DynamoDB に登録されます。エージェントは `list_templates` で利用可能なテンプレートを確認し、選択したテンプレート ID で `analyze_template` を呼び出します。

---

## テンプレートの登録

### Layer 2（ローカル MCP）

.pptx ファイルをアクセス可能な場所に配置し、初期化時にパスを指定します。

```json
{
  "tool": "init_presentation",
  "arguments": {
    "name": "My Deck"
  }
}
```

または、エージェントに「my-template.pptx を使って」と伝えるだけです。

`skill/templates/` に配置すれば `list_templates` に自動的に表示されます。

同梱のサンプルテンプレート:

```
skill/templates/
├── sample_template_dark.pptx
└── sample_template_light.pptx
```

#### ユーザーローカルなテンプレート

パッケージ外にカスタムテンプレートを置くこともできます。この方法なら
`pip install --upgrade` やリポジトリの再 clone でも消えません。Kiro CLI /
`pptx_builder.py` は以下の順で検索し、`list_templates` ではマージして表示します。

1. `$SDPM_TEMPLATES_DIR` に列挙されたディレクトリ (プラットフォームのパス区切り文字: Unixは `:`、Windowsは `;` — `PATH` と同じセマンティクス)
2. `<user-config>/templates/` — 下記の **ユーザーローカルディレクトリ構成** を参照
3. `skill/templates/` (パッケージ同梱)

同じファイル名がある場合はユーザーローカル側が優先されます。リポジトリを
変更せずに同梱テンプレートを上書きしたいケースに便利です。

#### ユーザーローカルディレクトリ構成

ユーザーローカルのベースディレクトリはプラットフォームに応じて決まります。

| プラットフォーム | 場所 |
|----------|----------|
| macOS / Linux | `$XDG_CONFIG_HOME/sdpm/` (既定: `~/.config/sdpm/`) |
| Windows | `%APPDATA%/sdpm/` (既定: `C:\Users\<you>\AppData\Roaming\sdpm\`) |

構成:

```
<user-config>/sdpm/
├── templates/          # ユーザーローカルの .pptx テンプレート
├── styles/             # ユーザーローカルのスタイル HTML (下記「カスタムスタイル」参照)
├── assets/             # ユーザーローカルのアセットソース (下記「カスタムアセット」参照)
│   └── my-company/
│       ├── manifest.json
│       └── logo.svg
└── config.json         # ユーザー単位の設定 (output_dir, extra_sources 等)
```

いずれも既定では存在しません。必要なものだけ作成してください
(`mkdir -p ~/.config/sdpm/styles` など)。

### Layer 3（リモート MCP）

テンプレートを S3 にアップロードし、Amazon DynamoDB に登録します。

```bash
uv run python scripts/upload_template.py \
  --file my-template.pptx \
  --name "Corporate 2026" \
  --bucket <ResourceBucketName> \
  --table <TableName> \
  --default
```

| パラメータ | 必須 | 説明 |
|-----------|:---:|------|
| `--file` | ✅ | テンプレート .pptx ファイルのパス |
| `--name` | ✅ | テンプレートの表示名 |
| `--bucket` | ✅ | S3 バケット名（CDK 出力の `ResourceBucketName`） |
| `--table` | ✅ | Amazon DynamoDB テーブル名（CDK 出力の `TableName`） |
| `--default` | | デフォルトテンプレートに設定 |

スクリプトは S3 へのアップロード、テンプレート解析、Amazon DynamoDB へのメタデータ登録を自動で行います。

---

## カスタムスタイル

スタイルは、デッキの視覚的な方向性（配色、タイポグラフィ、コンポーネント、
トーン）を記述した HTML ファイルです。エージェントは `:root` の CSS 変数と
スタイルクラスを読み取り、`slides.json` に反映します。

### ユーザーローカルなスタイル

`create-style` ワークフロー（エージェント駆動）で新しいスタイル HTML を生成する
と、`<user-config>/styles/{name}.html` に書き出されます。macOS/Linux なら
`~/.config/sdpm/styles/`、Windows なら `%APPDATA%/sdpm/styles/` です。

既存のスタイルを手動でコピーしても構いません。

```bash
mkdir -p ~/.config/sdpm/styles
cp skill/references/examples/styles/elegant-dark.html \
   ~/.config/sdpm/styles/my-style.html
```

検索順序（同一ファイル名は先勝ち）:

1. `$SDPM_STYLES_DIR` に列挙されたディレクトリ (プラットフォームのパス区切り文字、`PATH` と同じセマンティクス)
2. `<user-config>/styles/`
3. `skill/references/examples/styles/` (パッケージ同梱のサンプル)

スタイルギャラリー（`list_styles` や CLI の `examples styles` で開くもの）は
全 3 箇所をスキャンし、一覧を統合して表示します。同名のユーザーローカル
スタイルは同梱サンプルをシャドウするため、リポジトリを変更せずに上書き
できます。

---

### 組み込みアセットソース

spec-driven-presentation-maker には 2 つのアイコンセットのダウンロードスクリプトが含まれています。

```bash
# AWS Architecture Icons
uv run python3 scripts/download_aws_icons.py

# Material Symbols（Google）
uv run python3 scripts/download_material_icons.py
```

アイコンは `skill/assets/` にソースごとの `manifest.json` と共に保存されます。

```
skill/assets/
├── config.json          # 任意: ユーザー設定（git管理外、config.example.json を参照）
├── config.example.json  # 設定例（git管理）
├── aws/
│   ├── manifest.json    # {"icons": [{"name": "Lambda", "file": "Lambda.svg", "tags": [...]}]}
│   └── *.svg
└── material/
    ├── manifest.json
    └── *.svg
```

### スライドでのアセット参照

```json
{
  "type": "image",
  "src": "assets:aws/Lambda",
  "x": 100, "y": 200, "width": 64, "height": 64
}
```

参照形式:
- `assets:{source}/{name}` — 特定ソースから（例: `assets:aws/Lambda`）
- `icons:{name}` — 全ソースを横断検索（後方互換）

### カスタムアセットソースの追加

カスタムアセットソース（会社ロゴ等）を追加する方法は 2 通りあります。

#### 方法 A — `<user-config>/assets/` に配置する（自動認識）

ユーザーローカルの assets ディレクトリ配下にソースを配置すると、実行時に
自動でスキャンされます。設定ファイルの変更は不要です。

```
~/.config/sdpm/assets/my-company/     # Windows: %APPDATA%/sdpm/assets/my-company/
├── manifest.json
└── logo.svg
```

`manifest.json` のフォーマットは組み込みソースと同じです。

```json
{
  "source": "my-company",
  "icons": [
    {"name": "my-logo", "file": "logo.svg", "tags": ["brand", "logo"], "type": "service"}
  ]
}
```

`slides.json` からの参照:

```json
{ "type": "image", "src": "assets:my-company/logo", "x": 100, "y": 200, "width": 64, "height": 64 }
```

#### 方法 B — `config.json` で明示登録する

ファイルがディスクの任意の場所にある場合（共有ネットワークドライブ等）、
または既存のディレクトリを移動せずに参照したい場合に使います。

```json
{
  "extra_sources": [
    {
      "source": "mybrand",
      "manifest": "/path/to/my-icons/manifest.json",
      "files_dir": "/path/to/my-icons/"
    }
  ]
}
```

`<user-config>/config.json` に保存します（下記「ユーザー設定」を参照）。

### 優先順序

同じアセット名が複数ソースに存在する場合、先に列挙された方が勝ちます。

1. `config.json` の `extra_sources` — 明示的なオーバーライド
2. `<user-config>/assets/` — 自動認識されるユーザーローカルソース
3. `skill/assets/` — 組み込みソース（aws、material）
4. レガシー `icons/` ディレクトリ（存在する場合のみ）

これにより `extra_sources` がユーザーローカルを、ユーザーローカルが同梱を
それぞれ上書きできます。組み込みと同名のエントリを `extra_sources` に登録
することは、同梱アイコンを差し替える正規の手段です。

---

## ユーザー設定

ユーザー単位の設定は `<user-config>/config.json`（macOS/Linux なら
`~/.config/sdpm/config.json`、Windows なら `%APPDATA%/sdpm/config.json`）に
置きます。ファイルは任意で、欠落しているキーは既定値にフォールバックします。

既定値込みの完全なスキーマ:

```json
{
  "output_dir": "~/Documents/SDPM-Presentations",
  "extra_sources": []
}
```

- `output_dir` — 生成した PPTX の出力先ベースディレクトリ。`~` 展開可能。
  `$SDPM_OUTPUT_DIR` でも実行時に上書きできます
- `extra_sources` — 追加アセットマニフェスト（上記「方法 B」参照）

以前同梱されていた `skill/assets/config.json` は読み込み対象から外れました。
`pip install --upgrade` で消失する問題があったため、ユーザーローカルパスに
一本化しています。

---

### S3 へのアセットアップロード（Layer 3）

```bash
uv run python scripts/upload_assets.py \
  --dir ./my-icons/ \
  --bucket <ResourceBucketName> \
  --category icons
```

---

## 関連ドキュメント

- [はじめに](getting-started.md) — セットアップとデプロイ手順
- [アーキテクチャ](architecture.md) — アセットリゾルバーの仕組み
