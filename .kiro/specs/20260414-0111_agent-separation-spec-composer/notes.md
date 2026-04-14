# Notes: SPECエージェントと実装エージェントの分離

Guidelines:
- **Purpose**: Record sufficient information so that:
  - Future sessions can understand the full context
  - Knowledge notes and learning materials can be generated from this log
  - Issues can be traced and verified through the timeline
- **What to capture**:
  - **Facts**: What happened, what was tried, results and errors
  - **Decisions**: Why this approach, what alternatives were considered
  - **Impressions**: Concerns, surprises, discoveries, evaluations
- **When to record**: After each meaningful unit of work (e.g., investigation, decision, problem resolution). Do not defer.
- **Append-only**: Never edit or delete existing content

## Log

### [2026-04-14 01:00] 議論開始 — エージェント分離の動機

Slackでの議論から発展。WEB版のコスト肥大化（検索ツール、大量トークン）が動機。
サブエージェントでのコンテキスト圧縮よりも、役割ごとのエージェント分離がクリーンという結論。

### [2026-04-14 01:01] インターフェース設計 — 3ファイルで完結

SPECエージェント → 実装エージェントの受け渡しは3ファイル（brief.md, outline.md, art-direction.html）のみ。
追加の指示文は不要。ファイルがインターフェースそのもの。
brief.mdに制約・個別要望・素材情報を含めることで、暗黙知の明文化を担保。

### [2026-04-14 01:02] art-direction.html の発見

art-direction.html が既にデザイントークン（CSS変数）+ ビジュアルサンプルの構造を持っていた。
これが並列エージェントへの「共通言語」として機能する。
CSS変数というWeb標準をデザイントークンとして流用している設計が秀逸。

### [2026-04-14 01:03] 進化パスの設計 — C → B

Phase C（直列1実装エージェント）→ Phase B（並列実装エージェント）。
差分はoutline.mdにレイアウト方針を1行追加するだけ。アーキテクチャ変更不要。
並列化のインパクト: 10枚 × 3-5分 → 3-5分（フル並列時）。速度だけでなく品質にも効く。

### [2026-04-14 01:05] レビューフェーズの所在

レビュー（Phase 3）は実装エージェントが担当。理由: 実装コンテキストを持っているから。
SPECエージェントは実装の知識がないのでレビューできない。
ユーザーからの修正要望はSPECエージェントが受け取り、実装指示に変換してcomposerに渡す。

### [2026-04-14 01:06] ステートレス設計の決定

実装エージェントは毎回新規起動でも可。コンテキストはファイルに全てある。
メリット: コンテキストが常にクリーン、並列化と同じモデル、実装が単純。

### [2026-04-14 01:07] MCP tools の分割方針

分割しない。両エージェントにフルセット提供。制約はsystem promptで制御。
わざわざ分ける複雑さを入れる必要がない。

### [2026-04-14 01:08] 技術調査 — Strands / A2A / AgentCore

調査結果:
- **Strands Agents SDK**: Agents as Tools パターンが今回のユースケースにそのままフィット。同一プロセス内で動作。`@tool`デコレータで関数をラップするだけ。
- **A2A**: 異なる組織間のエージェント連携向け。今回はオーバースペック。将来リモート分離時に有用。
- **AgentCore**: マネージドランタイム。本番デプロイ時のインフラ層。開発段階では不要。

結論: Strands Agents SDK の Agents as Tools パターンを採用。

### [2026-04-14 01:15] Layer 4の認識修正

既存アーキテクチャは4層構成で、Layer 4（Agent + Web UI）が既に存在していた。
Layer 4は既にStrands Agent + AgentCore Runtimeで構成されている。
今回のエージェント分離はLayer 4内の変更であり、Layer 1-3は一切変更不要。
steering/principles.mdの3層構造は古い記述で、実際のdocs/architecture.mdは4層。

---
**Created**: 2026-04-14

### [2026-04-14 08:10] レビュー — 並列エージェントのファイル書き込み競合

presentation.json が単一ファイルであることが並列化のボトルネック。
S3 PutObject は last-writer-wins で、並列エージェントが同時に書くと片方の変更が消える。

対策として3案を検討:
- A. presentation.json をスライド単位に分割 → 競合しないがLayer 1への影響大
- B. オーケストレーター方式 → 親がマージ、Layer 1-3変更なし
- C. S3条件付き書き込み + リトライ → 並列数増加でリトライ地獄

### [2026-04-14 08:13] 方針決定 — ファイル分割 + sandbox互換

ユーザーの制約:
- MCP toolsをマルチエージェント特化させない
- 実装エージェントは担当分だけでビルドまで完結する必要がある
- ファイル分割はOK

結論: Storage層でスライド単位分割。sandbox I/Fは互換維持（読み込み時マージ、書き戻し時分割）。

### [2026-04-14 08:15] メタデータの確認

presentation.json のトップレベルメタデータは3つだけ:
- template: テンプレートファイル名
- fonts: {"fullwidth": "...", "halfwidth": "..."}
- defaultTextColor: デフォルトテキスト色

全てPhase 1（art-direction Step 1）で確定。Phase 2では変更不要。

### [2026-04-14 08:17] メタデータ分離の設計

Phase 1でdeck.jsonを作成、Phase 2は読み取り専用。
deck.json = {"template": "...", "fonts": {...}, "defaultTextColor": "..."}
slides/{slug}.json = 各スライドのdict

実装エージェントはdeck.json + 担当slides/*.jsonだけで完結。

### [2026-04-14 08:20] スライド順序の管理 — outline.md slug化

番号プレフィックスは50ファイル先頭挿入で全リネーム必要。indexファイルは単一操作点。
→ outline.md のラベルをslugに変更し、行順序がスライド順序を定義する方式に決定。

```markdown
- [title] Audience knows the topic and speaker
- [current-state] Audience sees the problem
- [feature-a] Audience understands the solution
```

slug = slides/{slug}.json のファイル名。挿入は1行追加のみ。
WebUI の outlineParser.ts は正規表現1本の変更で対応可能（既存実績あり）。

### [2026-04-14 08:30] outline執筆ツールは不要

操作はテキスト編集そのもの。エージェントは既にファイル読み書きできる。
専用ツールは「MCP toolsの使い方をエージェントに任せる」方針と矛盾。
必要なのはgenerate_pptx時のoutline.mdパース + slides/*.jsonマージ処理のみ。

### [2026-04-14 08:35] SPEC方針の転換 — 並列化をMUSTに

1スライド1分以上 × 10枚 = 直列10分以上。WEB版UXとして許容できない。
並列化の効果: 10分 → 1-2分。品質も均一化（コンテキスト膨張による後半品質低下がなくなる）。

Phase Cは「Phase Bへの中間チェックポイント」、ゴールはPhase B（並列化）。
ファイル分割・outline slug化は前提として含める。SPECを書き直す。

### [2026-04-14 08:43] 方針変更 — sandbox互換のマージ/分割を廃止

ユーザー判断: ファイル分割をEngineのルールにしてよい。
sandbox互換のためのマージ/分割レイヤーは不要。全レイヤーで deck.json + slides/{slug}.json を正式フォーマットとする。

変更点:
- Layer 1: _resolve_config がディレクトリ入力に対応（presentation.json後方互換あり）
- Layer 3: sandbox内もそのまま分割構造
- エージェント: `open("slides/{slug}.json")` で直接編集

メリット: 変換レイヤーがなくなりシンプル。並列時に各エージェントが担当slugだけ触るのが自然な操作になる。

### [2026-04-14 08:55] グループ分割 — SPECエージェントのLLM判断に委ねる

機械的なルール（slug prefix等）ではなく、SPECエージェントがoutline全体を見てグループを決定。
parallel_composerの引数でslugsリストとして渡す。
outline.mdにグループ情報は持たせない（outline.mdはユーザーとの合意文書）。

判断基準（system promptに記載）:
- override関係は必ず同一グループ
- ユーザーが揃えたいと言ったものは同一グループ
- それ以外はart-directionで一貫性担保される前提で積極的に分ける

### [2026-04-14 09:00] 並列エージェント間の一貫性 — 事前最小限、事後補正

課題: 同じレイアウトの連続、通したメッセージ、伏線の回収。
これらは前後スライドの文脈が必要で、並列エージェントが独立に動く限り構造的に解決できない。

レイアウト決定はPhase 2で行う（patterns/componentsを読むのがPhase 2）ため、
Phase 1のSPECエージェントはレイアウトの語彙を持たない。

結論: Phase 3レビューで全スライドを通しで見て補正する。
- 隣接レイアウト重複検出
- メッセージ接続チェック
- 伏線回収チェック
- デザイントークン逸脱チェック

設計方針: 事前は最小限（outline + art-direction + グループ分割判断）、事後で補正。

### [2026-04-14 09:15] レビュー設計の確定 — 2層構造

レビュー専用エージェントは立てない。

- スライド単体の品質: 各composerがPhase 2+3ループで担保
- スライド間の一貫性: SPECエージェントがpreview画像 + outline.mdで事後レビュー

SPECエージェントはPhase 1で全スライドのメッセージを設計した本人なので、
ストーリー接続・伏線回収の判断が一番得意。
ビジュアルはpreview画像で「似てる」「逸脱してる」程度の判断。
スライドJSONは読まない（コンテキスト節約）。

修正が必要な場合はcomposer（直列）を再呼び出し。
ユーザーからの修正要望も同じパス。

### [2026-04-14 09:31] オーナーレビュー — SPEC修正3点

オーナーレビューで以下3点を修正:

1. **requirements.md Layer 1整合性**: 「変更なし」→「軽微な変更（_resolve_configのディレクトリ入力対応）」に修正。design.md/tasks.mdとの矛盾を解消。
2. **design.md エラーハンドリング追加**: 並列エージェント失敗時の方針を新セクションとして追加。return_exceptions=True + 失敗グループのみ直列リトライ（最大1回）。部分ビルド対応も定義。
3. **requirements.md briefフロー強化の具体化**: 制約・個別要望セクション（MUST NOT/MUST/PREFER分類）と素材一覧セクション（テーブル形式）のテンプレートを追加。

レビュー精度（画像でレイアウト重複検出）とグループ分割精度はPhase C実測で検証する方針とし、SPECでは詰めない判断。

### [2026-04-14 11:24] Q-SPECヒアリング — 既存実装との整合性分析

影響分析で4つの未定義事項を発見し、Q-SPECで設計を詰めた。

#### 1. sandbox 新規ファイル検出
問題: 現在の paths リスト方式では、sandbox 内で新規作成されたファイルが S3 に保存されない。
決定: prefix ベース走査方式に変更。`_WORKSPACE_PREFIXES` に合致するファイルを全部書き戻す。
判断理由: sandbox ルートが `decks/{deckId}/` 直下なので、フィルタなしだと `__pycache__/` 等も書き戻される。prefix は必要。

#### 2. 既存デッキのマイグレーション
問題: 既存デッキは presentation.json 形式。新形式デプロイ後にどうなるか。
決定: マイグレーション不要。`_assemble_slides` が deck.json の有無で新旧判定し、読み込み時に組み立てるだけ。
発見: 現行の presentation.json は「組み立て済みの完成品」、新形式は「部品」。Engine に渡す dict は同じ。組み立て工程が増えるだけ。

#### 3. OutlineView の title 表示
問題: slug 化で num と title がなくなる。
決定: ノード円に連番（index+1）、slug を太字、message を下に表示。num はデータとして持たず算出。

#### 4. Storage ABC
決定: 抽象メソッド4つ追加（機械的）。outline パースは Storage の責務ではなく _assemble_slides に置く。

#### 追加発見: _prepare_workspace と _assemble_slides の分離
問題: `_prepare_workspace` は I/O とデータ変換が混在。`run_python` の measure 後処理でも呼ばれる。
決定: I/O（_prepare_workspace）とデータ変換（_assemble_slides）を分離。組み立ては `_assemble_slides` に集約。

#### 追加発見: 並列時の measure
問題: 並列中に全体ビルドすると、他の composer のスライドが未完成でエラーになる。
決定: 欠損スライドは黙ってスキップ（警告するとエージェントが勝手に作る恐れ）。存在するもので組み立て、結果を slug ベースで返す。ページ番号はエージェントに見せない。

#### 追加発見: measure_slides の slug 化
問題: 並列時にページ番号が不安定。
決定: `measure_slides` を `list[int]` → `list[str]`（slug）に変更。内部で slug → ページ番号変換。

#### 追加発見: ツール名統一
問題: Phase C の `composer` と Phase B の `parallel_composer` が別ツール。
決定: `compose_slides` に統一。内部が直列か並列かは実装の切り替えのみ。Phase C → B 移行時に system prompt 変更不要。

#### 追加発見: compose_slides の戻り値レポート
決定: generated_slides, outline_check, preview_images, measure_summary, errors を返す。SPECエージェントが事後レビューと修正判断に使う。

### [2026-04-14 14:04] 議論 — グループ分割戦略と並列度制御

#### 事前調整 vs 事後補正
隣接グループ間のレイアウト重複を事前にどこまで防げるか検討。
4案を比較（outline.mdにレイアウトヒント / 隣接コンテキスト渡し / レイアウト制約マップ / 2パス方式）。
根本的な難しさ: レイアウト選択はPhase 2の実装判断であり、Phase 1で調整しようとすると分離の意味が薄れる。

結論: 隣接多様性はグループ分割の基準に入れず、事後レビューで対応。
ただしグループ分割の工夫で事後レビューの負荷を減らす方向に。

#### グループ分割の判断基準を刷新
旧: 「積極的に分ける、目安2-4枚」
新: 2ステップ方式

Step 1 — 核グループの形成:
- override継承は同一グループ（必須）
- 構造的に同じ役割のスライドは同一グループ（強く推奨）
- ユーザーが揃えたいと言ったものは同一グループ

Step 2 — 独立スライドの振り分け:
- 核グループに属さない独立スライドを、各グループの負荷が均等になるように振り分け
- 独立スライドだけのグループは作らない

判断の優先順位: override継承 > 構造的同一性 >> 隣接多様性（事後） > ストーリー連続性（outline.mdで担保済み）

#### 並列度制御の分離
グループ分割（意味的判断）と並列度制御（インフラ制約）を分離。
semaphore（max_concurrency）でインフラ側を制御。SPECエージェントはグループ数を気にせず最適な分割をする。
Phase C: max_concurrency=1、Phase B: 3-5から実測で調整。

#### 既存デッキのlazy migration
旧: 「既存デッキへの書き込みも既存形式のまま」
新: 書き込みは常に新形式（lazy migration）。composerの書き込みパスを1本に統一。
読み込みの後方互換（_assemble_slidesでの新旧判定）はそのまま残す。
判断理由: composerのsystem promptとsandbox内の条件分岐を排除するため。

### [2026-04-14 14:16] 実装開始 — ファイル分割 + outline slug化

Phase Cの最初の2ブロック（16タスク）を実装完了。

#### ファイル分割（commit: 934a8d0）
- Layer 1 `_resolve_config`: ディレクトリ入力対応。`_assemble_slides_from_dir` + `parse_outline_slugs` を追加。presentation.json後方互換維持。
- Storage ABC: 4抽象メソッド追加（get/put_deck_json, get/put_slide_json）
- AwsStorage: S3の `decks/{deckId}/deck.json` と `decks/{deckId}/slides/{slug}.json` の読み書き実装
- generate.py: `_prepare_workspace` と `_assemble_slides` を分離。`_assemble_slides` が deck.json有無で新旧判定。欠損スライドは黙スキップ。
- sandbox.py: `_WORKSPACE_PREFIXES` に `deck.json`, `slides/` 追加。`_save_deck_workspace` を prefix ベース走査に変更（paths リスト方式廃止）。
- init.py: `presentation.json` → `deck.json` に変更。
- server.py: `measure_slides` を `list[int]` → `list[str]`（slug）に変更。lint は `_assemble_slides` の戻り値を使用（presentation.json直接読み廃止）。

#### outline slug化（commit: 0eb7ed5）
- outline ワークフロー: `[N: label]` → `[slug]` kebab-case形式
- art-direction ワークフロー: `presentation.json` → `deck.json` 書き込み
- outlineParser.ts: 正規表現変更、OutlineSlide から num/title 削除し slug 追加
- OutlineView.tsx: ノード円に index+1、slug を太字表示、message を下に

判断: Layer 3の `_parse_outline_slugs` はLayer 1の `parse_outline_slugs` と同一ロジックだが、Layer 1はskill package、Layer 3はmcp-serverで別パッケージのため重複実装。共通化はSPECスコープ外（将来のリファクタリング候補）。

### [2026-04-14 14:23] セルフレビュー — 3件修正（commit: 6eb3e1f）

実装後のセルフレビューで3件の問題を発見・修正。

1. **`_resolve_template` のディレクトリ入力**: `Path(input_path).parent` がディレクトリの親を返してしまう。`is_dir()` チェックを追加し、ディレクトリならそのまま `base_dir` として使用。
2. **`_prepare_workspace` の例外キャッチ範囲**: `except (ValueError, Exception)` → `except ValueError` に限定。S3接続エラー等のインフラ障害を握りつぶすのは危険。`ValueError` は `get_deck_json` が「not found」を示す正常系フォールバック。
3. **outline.md ダウンロード失敗の silent pass**: `except Exception: pass` → warning ログ追加。S3のNoSuchKeyはbotocore.exceptions.ClientErrorのサブクラスだが、Storage抽象化を超えてキャッチするのは設計違反のため、広いキャッチ + ログで対応。

### [2026-04-14 14:38] エージェント分離実装（commit: 73f2eba）

Strands Agents SDK の Agents as Tools パターンを調査し、3つの実装方法を確認:
1. Agent を直接 tools に渡す（SDK が自動変換、input: str のみ）
2. `.as_tool()` でカスタマイズ（名前・説明・コンテキスト保持）
3. `@tool` デコレータで完全制御（前後処理、複数パラメータ、エラーハンドリング）

方法3を採用。理由: Phase B で asyncio.gather に切り替える必要があり、戻り値の加工やエラーハンドリングが必要。

#### 実装内容
- `_SPEC_AGENT_PROMPT_TEMPLATE`: Phase 1 専用。compose_slides を呼んで実装を委譲。build/measure/preview は直接使わない。
- `_COMPOSER_PROMPT_TEMPLATE`: Phase 2+3 専用。ユーザー対話なし。deck.json は読み取り専用。
- `_make_compose_slides()`: クロージャで mcp_servers と model を閉じ込め、`@strands_tool` でラップ。内部で `Agent()` を毎回生成（ステートレス）。`callback_handler=None` で composer の出力を抑制。
- `create_agent`: `SdpmAgent` → `SdpmSpecAgent` にリネーム。tools に compose_slides を追加。
- briefing ワークフロー: Constraints & Requests（MUST NOT/MUST/PREFER）と Materials（テーブル）セクションを追加。

#### 設計判断
- compose_slides の戻り値: Phase C では `str(response)` で十分。構造化レポート（generated_slides, measure_summary 等）は Phase B で各 composer の結果を集約する際に必要になるため、Phase B で実装する。
- MCP tools は両エージェントにフルセット提供。制約は system prompt で制御（ツール分割しない方針）。
- composer の `callback_handler=None`: 親エージェントのストリーミングに composer の出力が混ざるのを防止。
