[EN](../en/custom-template.md) | [JA](../ja/custom-template.md)

# カスタムテンプレートとアセット

spec-driven-presentation-maker は任意の `.pptx` ファイルをテンプレートとして使用できます。
テンプレートのレイアウト、カラー、フォント、プレースホルダーを自動解析するため、手動設定は不要です。

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

## アセットのカスタマイズ

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

アイコンと `manifest.json` を含むディレクトリを作成します。

```json
{
  "icons": [
    {"name": "my-logo", "file": "logo.svg", "tags": ["brand", "logo"]},
    {"name": "product-icon", "file": "product.svg", "tags": ["product"]}
  ]
}
```

`skill/assets/config.json` に登録（`config.example.json` をコピーして作成）:

```json
{
  "output_dir": "~/Documents/SDPM-Presentations",
  "extra_sources": [
    {
      "name": "mybrand",
      "manifest": "/path/to/my-icons/manifest.json",
      "files_dir": "/path/to/my-icons/"
    }
  ],
  "preview": {
    "backend": ""
  }
}
```

`assets:mybrand/my-logo` で参照できるようになります。

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
