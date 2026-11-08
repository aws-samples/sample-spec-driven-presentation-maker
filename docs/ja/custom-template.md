[English](../en/custom-template.md) | [日本語](custom-template.md)

# カスタムテンプレート・スタイル・アセット

spec-driven-presentation-maker は、どの `.pptx` ファイルでもテンプレートとして使えます。
テンプレートのレイアウト、配色、フォント、プレースホルダーを自動で解析するので、手作業の設定は不要です。

テンプレートのほかに、次のリソースをユーザーごとにカスタマイズできます。

- **テンプレート**（`.pptx`）: スライドマスター
- **スタイル**（`.html`）: エージェントが使うデザインガイド
- **アセット**（`.svg`、`.png` などの画像）: アイコン、ロゴ、イラスト
- **設定**（`config.json`）: 出力先ディレクトリ、追加のアセットソースなど

4 つとも、ユーザーごとのローカルな場所に置けます。`pip install --upgrade` やリポジトリの再 clone の
後もカスタマイズが残ります。

---

## テンプレート解析のしくみ

`analyze_template` を呼ぶと、エンジンは .pptx ファイルを調べて次の情報を取り出します。

- **スライドレイアウト**: 名前、寸法、プレースホルダーの位置とサイズ
- **テーマの配色**: 背景、アクセント、文字の色
- **フォント**: 見出しと本文のフォント
- **プレースホルダー**: タイトル、本文、フッターとその正確な座標

エージェントはこの情報を使い、テンプレートのデザインに沿って要素を正確に配置します。

### HTML デッキ

HTML デッキ（`deck.json` の `outputFormat: "html"`）も同じ `.pptx` テンプレートを使います。エンジンは
テンプレートを次の 3 つに変換します。`theme.css`（キャンバスのサイズ、テーマの配色、フォント、
プレースホルダーの位置と文字のスタイル）、`template.json`（レイアウト、プレースホルダー、スライド番号と
フッターの配置）、そしてマスターとレイアウトが描く装飾（ロゴ、帯、背景画像）をレイアウトごとに 1 枚の
SVG にしたもの。結果はテンプレートの内容のハッシュをキーに `sdpm/.cache/template-html/` にキャッシュ
されるので、`.pptx` を編集すると変換がやり直されます。装飾の描画には LibreOffice と poppler が必要です。
無くても構造は変換され、足りないツールをビルドが 1 度だけ伝えます。プレースホルダー以外に何も描かない
テンプレート（同梱の `blank-light` / `blank-dark` など）では、どちらも不要です。

---

## テンプレートを作る

PowerPoint、Google スライド、Keynote でテンプレートをデザインします（.pptx で書き出し）。

1. **スライドレイアウトを定義する**: 少なくとも次を用意します。
   - タイトルスライドのレイアウト
   - コンテンツスライドのレイアウト（タイトルのプレースホルダー + 本文の領域）
   - セクション区切りのレイアウト（任意）
   - 白紙のレイアウト（自由なデザイン用）

2. **テーマの配色を設定する**: スライドマスターのカラーテーマにブランドの色を定義します。エージェントは
   これを読み取り、一貫して使います。

3. **フォントを設定する**: スライドマスターで見出しと本文のフォントを定義します。エージェントが自動で
   取り出します。

4. **余計なものを残さない**: レイアウトからサンプルの内容を消します。エージェントが使うのはプレース
   ホルダーの位置で、サンプルの文字ではありません。

5. **スピーカーノートにレイアウトの使い方を書く**: 各レイアウトのサンプルスライドのスピーカーノートに、
   使い方を書きます。エージェントはテンプレートの解析時にこれを読み、そのレイアウトでスライドを作るときに
   従います。

   例:
   - 「2 列の比較にはこのレイアウトを使う」
   - 「画像は右側にだけ置く」
   - 「タイトルは 1 行に収める」

### ヒント

- レイアウトには内容が分かる名前を付けます（「Content with Image」「Two Column」など）。エージェントは
  この名前を読みます
- 背景と文字のコントラスト比は 4.5:1 以上にします
- `analyze_template` を実行して出力を確認し、テンプレートを試します

### スライドのサイズ（縦横比）

どのスライドサイズでも使えます。16:9、4:3、16:10 などの比率に対応しています。
エンジンはテンプレートの実際の寸法から描画キャンバスを決めます。

座標系は **幅 1920 px、高さは縦横比に合わせる** 形です。

| テンプレートのスライドサイズ | スライド JSON のキャンバス |
|---|---|
| 16:9（13.33 × 7.5 in） | 1920 × 1080 px |
| 4:3（10 × 7.5 in） | 1920 × 1440 px |
| 16:10 | 1920 × 1200 px |

`analyze_template` はキャンバスのサイズを `slide_size` として返し、エージェントはそれを `deck.json` に
`slideSize` として記録します。これでスライドの作成時にキャンバス全体を使えます。

16:9 以外のテンプレートでの既知の制限:

- **アーキテクチャ図のボックス**: #285 で修正済みです。ボックスの自動の高さは `slideSize.ptPerPx`
  （`analyze_template` が返し `deck.json` に保存される pt から px への換算率）で調整されます。細かく
  調整したいときは、明示的な `box.height` も引き続き使えます。
- **スタイルのデモ**: 同梱のスタイルギャラリーの HTML は 16:9 の固定キャンバスです。作られるスライドには
  影響しません（使われるのはデザイントークンだけです）。
- **デッキ一覧のサムネイル**: Web UI のデッキ一覧は、カードの高さをそろえるためにサムネイルを固定の比率で
  切り抜きます。スライドのプレビュー（作業画面、カルーセル）は実際の縦横比で表示されます。

---

## テンプレートを解析する

### Layer 1（CLI）

```bash
# List all layouts
uv run python3 scripts/pptx_builder.py analyze_template my-template.pptx

# Show specific layout details
uv run python3 scripts/pptx_builder.py analyze_template my-template.pptx --layout "Content"
```

### Layer 2（MCP）

エージェントは設計の段階で `analyze_template` を自動で呼びます。直接頼むこともできます。

> 「テンプレートを解析して、使えるレイアウトを見せて」

### Layer 3（リモート）

テンプレートは S3 に保存されます（メタデータは DynamoDB にキャッシュされます）。エージェントは
`list_templates` で使えるテンプレートを確認し、選んだテンプレートの ID で `analyze_template` を呼びます。

---

## テンプレートを登録する

### Layer 2（ローカル MCP）

.pptx ファイルを参照できる場所に置き、デッキの作成時にパスを指定します。

```json
{
  "tool": "init_deck_workspace",
  "arguments": {
    "name": "My Deck"
  }
}
```

または、エージェントに「このプレゼンには my-template.pptx を使って」と伝えるだけでも構いません。

`sdpm/templates/` に置いたテンプレートは、自動で `list_templates` に表示されます。

同梱のテンプレート:

```
sdpm/templates/
├── blank-dark.pptx
└── blank-light.pptx
```

#### ユーザーローカルのテンプレート

カスタムテンプレートはパッケージの外にも置けます。そうすると `pip install --upgrade` やリポジトリの
再 clone の後も残ります。Kiro CLI / `pptx_builder.py` は次の場所を順に探し、結果をまとめて
`list_templates` に出します。

1. `$SDPM_TEMPLATES_DIR` に並べたディレクトリ（区切り文字はプラットフォームに従い、Unix は `:`、Windows は `;`。`PATH` と同じ扱い）
2. `<user-config>/templates/`（下の **ユーザーローカルのディレクトリ構成** を参照）
3. `sdpm/templates/`（パッケージに同梱）

同じファイル名なら、ユーザーローカルのテンプレートが同梱のものより優先されます。リポジトリを編集せずに
サンプルのテンプレートを差し替えられます。

#### ユーザーローカルのディレクトリ構成

ユーザーローカルの基準ディレクトリはプラットフォームによって異なります。

| プラットフォーム | 場所 |
|----------|----------|
| macOS / Linux | `$XDG_CONFIG_HOME/sdpm/`（既定: `~/.config/sdpm/`） |
| Windows | `%APPDATA%/sdpm/`（既定: `C:\Users\<you>\AppData\Roaming\sdpm\`） |

構成:

```
<user-config>/sdpm/
├── templates/          # User-local .pptx templates
├── styles/             # User-local style HTMLs (see "Custom Styles" below)
├── assets/             # User-local asset sources (see "Custom Assets" below)
│   └── my-company/
│       ├── manifest.json
│       └── logo.svg
└── config.json         # Per-user config overrides (output_dir, extra_sources, …)
```

これらのパスは既定では存在しません。必要なものだけを作ってください（`mkdir -p ~/.config/sdpm/styles` など）。

### Layer 3（リモート MCP）

テンプレートを S3 にアップロードし、DynamoDB に登録します。

```bash
uv run python scripts/upload_template.py \
  --file my-template.pptx \
  --name "Corporate 2026" \
  --bucket <ResourceBucketName> \
  --table <TableName>
```

| パラメータ | 必須 | 説明 |
|-----------|:--------:|-------------|
| `--file` | ✅ | .pptx テンプレートファイルのパス |
| `--name` | ✅ | テンプレートの表示名 |
| `--bucket` | ✅ | S3 バケット名（CDK の出力 `ResourceBucketName`） |
| `--table` | ✅ | Amazon DynamoDB のテーブル名（CDK の出力 `TableName`） |

スクリプトが S3 へのアップロード、テンプレートの解析、Amazon DynamoDB へのメタデータ登録をまとめて行います。

クラウドの Web UI では、各ユーザーが **テンプレート** 画面から組み込みテンプレートと自分のテンプレートに
自分だけのメモを付けられます。エージェントはテンプレートを提案・選択するとき、このメモ（使う場面、好み、
既定で使ってほしいという希望など）を考慮します。

---

## カスタムスタイル

スタイルは 1 つの HTML ファイルで、ルールブック、参考資料、ギャラリーのサンプルを兼ねます。`:root` の
トークン（配色、`--fs-*` のフォントサイズ、寸法）は `apply_style` とビルド時のチェックが機械的に読み取ります。
スライドの部分は、そのスタイルで作った、そのスタイルについての短いデッキです。ルール、タイトルと章の形、
繰り返し使うパターン（比較、手順、表、グラフ…）ごとに 1 枚のスライドがあり、それぞれに使っている領域と
部品がコメントで書かれています。ギャラリーに表示されるものが、そのスタイルのデッキの見た目そのものです。
コンポーザーはファイル全体を `specs/art-direction.html` として読み、オーケストレーターはアウトラインを
書く前にその Message & Outline の部分を読みます。そのため、スタイルは見た目だけでなくデッキの構成も
決めます。骨組みとトークンの約束事は `style` ワークフロー（`start_style()` が返すもの）で定義されています。

### 同梱スタイル

同梱スタイルは 2 種類です。**定番** は見た目を考えたくないときのためのもので、どんな題材、聞き手、
明るい・暗いにも合います。**コンセプト** は見た目で選ぶもので、各スタイルが 1 つの視覚的なアイデアに
絞り、それをどこまで押し出してよいかを決めています。目的ごとの構成（授業やワークショップのデッキを
どう組むか）はスタイルではなくアウトラインが担うので、どのコンセプトスタイルでもどんな種類のデッキを
作れます。

**定番: 迷ったらこの中から**

| スタイル | 向いている用途 | 見た目 |
|---|---|---|
| `report` | 1 人で読む文書。数字、表、結論が先 | 白地、セリフ体の結論、深緑のアクセント 1 色、表と小さな図の並び、グレースケールでも読める |
| `briefing` | 会場で話し、後で読み返されるデッキ | 暗い地、ティールのアクセント 1 色、名詞句のタイトルとトピックセンテンス、カードの代わりに見出し帯と罫線 |
| `aws-dark` / `aws-light` | AWS のサービス、アーキテクチャ、コストについてのデッキ。登壇やデモ（dark）、文書や印刷（light） | Squid Ink か白の地、識別のための公式サービスカテゴリー色、公式アイコン、強調は Smile Orange 1 か所 |

**コンセプト: 見た目で選ぶ**

| スタイル | アイデア | 見た目 |
|---|---|---|
| `neo-brutalist` | 磨き上げより率直な階層。「遠慮しない」 | クリーム色の地、6px の黒枠、12px ずらした硬い影、原色のベタ塗り、大文字のラベル、角は四角 |
| `typographic` | 文字そのものが画像。1 枚に 1 つの拍 | 白地、左端からはみ出す 384px の大きな文字、黒と薄いグレーの重ね、赤い語か数字は多くて 1 つ、図形も罫線も一切なし |
| `signal` | 警告表示の語彙。1 つのものだけを目立たせる | ほぼ黒の地、1 枚に 1 つの安全黄色のパネル、直立した極太の見出し、大きな数字、等幅のメタ情報、ハザードの縞 1 本 |
| `racing` | 勢い。どのスライドも次へつなぐ | ほぼ黒の地、斜体の詰まった見出し、上端に青・紫・赤の帯、細い白のスピード線、赤い要素 1 つ |
| `bento` | 1 タイル 1 事実。モジュール式の製品紹介のリズム | 柔らかいグレーの地、24px のグリッドに角丸 20px の白いタイル、1 枚に暗いタイルちょうど 1 つと青いアクセントのタイル多くて 1 つ、かすかな影 |
| `newspaper` | 新聞の紙面。読むためのデッキ | 古びた紙、ほぼ黒のセリフ体の見出し、3px の題字下の罫と 1px の細罫、2〜3 段の両端そろえ、ドロップキャップ、赤い数字か罫 1 つ |
| `swiss-poster` | 赤い幾何学図形 1 つが紙面を支える | 白地、はみ出さないポスターサイズの黒い文字、赤い円・棒・帯・四角をちょうど 1 つ（はみ出してよい）、グリッド線 1〜2 本、縦書きのラベル |
| `duotone` | 硬い境目 1 本と 2 つの面。片方に主張、もう片方に根拠 | ほぼ黒と鮮やかなオレンジ、50/50 か 33/67 の分割（縦か横）。オレンジの上はほぼ黒の文字、ほぼ黒の上は白とオレンジの文字、グレーはメタ情報だけ。白い棒 1 本を含む棒グラフ |
| `agent-spectrum` | 見られるためのデッキ（画面録画、アニメーションのプレビュー、README の静止画）。色は図の部品を見分けるためだけに使う | フラットなほぼ黒の地、明るい文字、5 つのビルダー色（青、ティール、紫、琥珀、ピンク）を常にこの順で使う、全スライドに 5 色の帯、等幅のラベルとタグ、破線の領域枠。グラデーション、発光、影はなし |
| `prism-dark` | グラデーションは指し示すもの。タイトルが語る 1 点だけに使い、ほかはすべてフラット | ほぼ黒の地、紫からピンクへのグラデーション 1 種類を、要の数字のグラデーション文字、選んだカードの 4px の枠 + 塗りのピル 1 つ、またはグラデーションの棒 1 本に使う。左端に下りる 40px のグラデーションの帯だけが常にある。グラデーションのパネル、ぼかし、発光はなし |
| `prism-light` | `prism-dark` と同じルールを、明るい部屋と印刷向けに | 白地、ほぼ黒の文字、1px の枠のフラットな白いカード、同じ紫からピンクへのグラデーションを同じ指し示す役割で使う |
| `aws-console` | デッキが AWS マネジメントコンソールの画面。画面の部品すべてがデッキの情報を運ぶ | 2 本の暗い見出し帯（aws のロゴ、デッキのタイトルとスライド番号を表示する検索ボックス、未対応のアクション数を示す通知バッジ、リージョンとアカウントの位置に日付と発表者。章ごとの番号付きチップが並ぶお気に入りの行で、現在の章が点灯）の下に白いツールバー。Info リンク付きのページタイトルと、枠線ボタンとオレンジのボタンの組。ドラッグハンドル、Info、ケバブメニュー、リサイズハンドル付きの 2px の枠の白いコンテナ。青いリンクと青い指標、固定の状態色 3 つ、56px の詰まった行、文章なし |

### ユーザーローカルのスタイル

新しいスタイルの HTML は `style` ワークフロー（エージェントが進める）で作ります。
ワークフローは `<user-config>/styles/{name}.html`、つまり macOS / Linux なら `~/.config/sdpm/styles/`、
Windows なら `%APPDATA%/sdpm/styles/` に書き出します。

既存のスタイルを手でコピーすることもできます。

```bash
mkdir -p ~/.config/sdpm/styles
cp sdpm/references/examples/styles/report.html \
   ~/.config/sdpm/styles/my-style.html
```

探す順序（同じファイル名なら先に見つかったものを使う）:

1. `$SDPM_STYLES_DIR` に並べたディレクトリ（区切り文字はプラットフォームに従う。`PATH` と同じ）
2. `<user-config>/styles/`
3. `sdpm/references/examples/styles/`（パッケージに同梱のサンプル）

スタイルギャラリー（`list_styles` か CLI の `examples styles` コマンドで開く）は 3 か所すべてを読み、
1 つの一覧に表示します。同じ名前なら、ユーザーローカルのスタイルが同梱のものより優先されるので、
リポジトリに触れずにサンプルを差し替えられます。

---

### 組み込みのアセットソース

spec-driven-presentation-maker には、2 つのアイコンセットのダウンロードスクリプトが付いています。

```bash
# AWS Architecture Icons
uv run python3 scripts/download_aws_icons.py

# Material Symbols (Google)
uv run python3 scripts/download_material_icons.py
```

アイコンは `sdpm/assets/` に、ソースごとの `manifest.json` と一緒に保存されます。

```
sdpm/assets/
├── config.json          # Optional: user settings (gitignored, see config.example.json)
├── config.example.json  # Example config (git-managed)
├── aws/
│   ├── manifest.json    # {"icons": [{"name": "Lambda", "file": "Lambda.svg", "tags": [...]}]}
│   └── *.svg
└── material/
    ├── manifest.json
    └── *.svg
```

### スライドからアセットを参照する

```json
{
  "type": "image",
  "src": "assets:aws/Lambda",
  "x": 100, "y": 200, "width": 64, "height": 64
}
```

参照の書き方:
- `assets:{source}/{name}`: 特定のソースから（例: `assets:aws/Lambda`）
- `icons:{name}`: すべてのソースから探す（後方互換）

### カスタムのアセットソースを追加する

カスタムのアセットソース（自社のロゴなど）を追加する方法は 2 つあります。

#### 方法 A: `<user-config>/assets/` に置く（自動で検出）

ソースのディレクトリをユーザーローカルのアセットの場所に置きます。実行時に自動で読み込まれ、設定の
変更は要りません。

```
~/.config/sdpm/assets/my-company/     # (Windows: %APPDATA%/sdpm/assets/my-company/)
├── manifest.json
└── logo.svg
```

`manifest.json` は組み込みのものと同じ形式です。

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

#### 方法 B: `config.json` で明示的に登録する

ファイルがディスク上の任意の場所（共有のネットワークドライブなど）にある場合や、既存のディレクトリを
動かさずに指したい場合に使います。

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

`<user-config>/config.json` として保存します（下の **ユーザー設定** を参照）。

### 優先順位

同じ名前のアセットが複数のソースにある場合は、先のソースが優先されます。

1. `config.json` の `extra_sources`: 明示的な上書き
2. `<user-config>/assets/`: 自動で検出されるユーザーローカルのソース
3. `sdpm/assets/`: 組み込みのソース（aws、material）
4. 旧来の `icons/` ディレクトリ（ある場合のみ）

`extra_sources` はユーザーローカルのソースより、ユーザーローカルのソースは同梱のものより優先されます。
組み込みの名前を `extra_sources` に登録すれば、同梱のアイコンを意図的に自分のものに差し替えられます。

---

## ユーザー設定

ユーザーごとの設定は `<user-config>/config.json`（macOS / Linux なら `~/.config/sdpm/config.json`、
Windows なら `%APPDATA%/sdpm/config.json`）に置きます。このファイルは任意で、無いキーは既定値になります。

既定値を含む全体の形:

```json
{
  "output_dir": "~/Documents/SDPM-Presentations",
  "extra_sources": []
}
```

- `output_dir`: デッキの保存先。CLI と MCP サーバーがデッキと生成した PPTX ファイルをここに書き出し、
  ローカルの Web UI はここにあるデッキを一覧に出します。`~` を展開し、空ならデフォルトを使います。
  `$SDPM_DECK_ROOT`、次に `$SDPM_OUTPUT_DIR` を設定すると、そちらが優先されます。
- `extra_sources`: 追加のアセットのマニフェスト（上の **方法 B** を参照）。

以前同梱していた `sdpm/assets/config.json` は、もう読み込まれません。`pip install --upgrade` で
失われていたため、上のユーザーローカルの場所に置き換えました。

---

### アセットを S3 にアップロードする（Layer 3）

```bash
uv run python scripts/upload_assets.py \
  --dir ./my-icons/ \
  --bucket <ResourceBucketName> \
  --category icons
```

---

## 関連ドキュメント

- [はじめに](getting-started.md): SDPM のインストールと使い方
- [Developer guide](../en/developer-guide.md)（英語）: CDK でのデプロイとテンプレートのアップロード
- [Architecture](../en/architecture.md)（英語）: アセットの解決のしくみ
