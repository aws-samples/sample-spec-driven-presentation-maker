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

### [2026-04-14 16:42] デプロイ検証 — outline 表示問題

症状: WebUI で outline が表示されない。
原因: deploy.sh で SdpmRuntime + SdpmAgent のみデプロイし、WebUI のビルド+デプロイを忘れていた。
outlineParser.ts の正規表現変更（slug 形式対応）が反映されていなかった。
対処: `npm run build` → `deploy_webui.sh` で解決。
教訓: WebUI の変更がある場合は必ず build + deploy_webui.sh を実行すること。deploy.sh は WebUI をビルドしない。

### [2026-04-14 17:20] デプロイ検証 — compose_slides 実行

#### 発見1: API Lambda が新形式未対応
api/index.py の get_deck が presentation.json しか読んでいなかった。
deck.json + slides/*.json 形式に対応する修正を追加（commit: 487f4e8）。
deck.json の存在で新旧判定、outline.md からスラグ順序取得、slides/*.json を個別読み込み。
presentation.json へのフォールバックも維持。

#### 発見2: WebUI デプロイ手順の漏れ
deploy.sh は CodeBuild 経由で CDK デプロイするが、deploy_webui.sh は別途手動実行が必要。
さらに deploy_webui.sh はビルド済み前提で、npm run build を先に実行する必要がある。
outlineParser.ts の変更が反映されていなかったのはこれが原因。

#### 発見3: compose_slides が異常に遅い
deck d325ed14 で compose_slides を実行。10分以上で1枚（company-face.json）しか生成されず。
composer が何をしているか見えない（callback_handler=None、AgentCore Runtime のログなし）。
原因の推測:
- composer が毎回ワークフロー全部を読んでいる
- measure → preview → polish ループを何周もしている
- system prompt が不十分で無駄なツール呼び出しが多い

#### 発見4: SdpmAuth スタックが壊れている
UPDATE_ROLLBACK_COMPLETE 状態。UserPool の export が SdpmWebUi に使われていて削除できない。
今回の変更とは無関係。buildspec を一時的に個別スタック指定に変更して回避。

#### 方針決定: compose_slides 進捗表示を優先実装
callback_handler でツール呼び出しを拾い、tool_stream_event として WebUI に流す。
一石二鳥: ユーザーへの進捗表示 + デバッグ情報の可視化。
汎用パイプラインとして実装し、compose_slides 固有の結合を作らない。

実装箇所:
1. compose_slides: async generator + callback_handler → yield
2. agent_stream: tool_stream_event を透過的に流す
3. strandsParser.js: 新イベントタイプのパース
4. ToolCard.tsx: 進捗テキスト表示

### [2026-04-14 22:40] コードレビュー — 2件修正（commit: c33e744）

全13コミットの変更内容をレビューし、2件の問題を発見・修正。

#### 1. outline parser の3重複
`parse_outline_slugs` が3箇所に存在していた:
- `skill/sdpm/api.py` — Engine（正規の場所）
- `mcp-server/tools/generate.py` — `_parse_outline_slugs()` コピー
- `api/index.py` — インライン実装

principles.md の「Engine is the source of truth」に違反。
- generate.py: 削除し `from sdpm.api import parse_outline_slugs` に変更。mcp-server は sdpm を import 可能。
- api/index.py: Lambda で sdpm を import できない制約があるため、インライン実装は残しつつ正規の場所をコメントで明記。

notes [2026-04-14 14:16] で「共通化はSPECスコープ外」と判断していたが、generate.py は sdpm を既に多数 import しており、共通化のコストはゼロだった。判断ミス。

#### 2. compose_slides 進捗が表示されない
原因: `ChatMessage.tsx` の `isActive` 条件に `Object.keys(block.tool.input || {}).length === 0` があった。
これは「input がまだストリーミング中（空）のツール」を active 表示するためのロジックだったが、compose_slides は `slide_groups` という input を持つため、input 確定後は常に `isActive=false` → streamMessages が表示されなかった。

修正: input 空チェックを削除。`isStreaming && !block.tool.status && i === blocks.length - 1` のみに変更。
影響: 全ツールで input 確定後も active 表示されるようになるが、status が設定されれば非 active になるため、実質的な副作用なし。

#### 副次修正
- compose_slides 内の未使用 `from typing import AsyncIterator` を削除。

### [2026-04-14 22:50] composer コンテキスト事前注入 — 設計と実装

#### 問題の本質
composer が毎回「初めてこのプロジェクトに参加する人」として動いていた。
system prompt に mcp_instructions（Phase 1 のワークフローに誘導する内容）が入っており、
composer は Phase 1 の briefing ワークフローから読み始め、さらに compose ワークフロー、
slide-json-spec、grid ガイド、components、patterns を順に MCP ツールで読んでいた。
これが全て LLM ターン（Bedrock API 往復）になり、スライド生成前に大量の時間を消費。

#### 解決策: prefetch + system prompt 注入
compose_slides 内で、composer Agent 生成前に MCPClient.call_tool_sync() で
全リファレンスを Python から直接取得し、system prompt に埋め込む。

prefetch 対象:
1. 共通リファレンス（毎回同じ、call_tool_sync で取得）:
   - read_workflows(["create-new-2-compose"]) — compose ワークフロー
   - read_workflows(["slide-json-spec"]) — JSON スキーマ仕様
   - read_guides(["grid"]) — グリッドガイド
   - read_examples(["components/all"]) — 全コンポーネント
   - read_examples(["patterns"]) — パターンカタログ

2. デッキ固有（deck_id で取得、run_python 経由）:
   - specs/brief.md
   - specs/outline.md
   - specs/art-direction.html
   - deck.json

#### 設計判断
- mcp_instructions を composer から完全除去。「read_workflows 等は呼ぶな」と明記。
- specs は run_python(deck_id=...) で取得。composer もどうせ sandbox を使うので追加コストなし。
- compose_slides に deck_id を明示的な引数として追加（instruction テキストに含めるのは不確実）。
- _build_system_prompt を **kwargs 対応に拡張（prefetched_context プレースホルダー）。
- measure_slides は独立ツールではなく run_python のオプション。system prompt を修正。

### [2026-04-14 23:01] セルフレビュー — 4件修正

prefetch 実装のセルフレビューで4件の問題を発見・修正。

#### 1. prefetch 失敗時のエラーハンドリング（🔴）
共通リファレンスの `call_tool_sync` が失敗した場合、例外がそのまま上がりスタックトレースが不明瞭だった。
`result.get("status") == "error"` をチェックし、`RuntimeError` で明確なメッセージを出すように修正。

#### 2. specs パースの脆弱性（🔴）
`run_python` の戻り値パースで `except (_json.JSONDecodeError, TypeError): pass` — 失敗を黙って無視していた。
specs が取得できなければ composer は何も知らない状態で動くことになる。
空結果・JSONDecodeError を明示的に `RuntimeError` にした。

#### 3. SPEC エージェント prompt に deck_id 指示がない（🟡）
compose_slides に `deck_id` が required になったが、SPEC エージェントの prompt は
「call compose_slides」としか言っていなかった。
`compose_slides(deck_id=..., slide_groups=[...])` と明示。

#### 4. import 位置（🟢）
`import json as _json` がループ内にあったのを関数先頭に移動。

### [2026-04-15 07:00] 検証 — compose_slides 進捗ストリーミングの根本原因特定

ローカルの Strands SDK で4パターンを検証し、根本原因を特定。

#### 検証結果

| パターン | ToolStreamEvent 伝播 | リアルタイム |
|---------|---------------------|------------|
| simple yield (no nesting) | ✅ 全部 | ✅ |
| yield inside `async for stream_async()` | ❌ 中間が消える | - |
| collect from stream_async → yield after | ✅ 全部 | ❌ バッチ |
| `invoke_async` + callback + `asyncio.Queue` | ✅ 全部 | ✅ |

#### 根本原因
`stream_async` の `async for` ループ内で `yield` すると、外側の async generator consumer と内側の `stream_async` が同じ event loop 上で競合し、中間の yield が消失する。
具体的には、`yield {'tool': name}` を `async for event in inner.stream_async()` の中で実行すると、`starting` と最後の `done` だけが伝播し、中間イベントが全て消える。
一方、ループ外での yield（before/after）は正常に伝播する。
simple async generator（`stream_async` でない）の `async for` 内 yield は正常動作するため、`stream_async` 固有の問題。

#### 解決策
`invoke_async` + `callback_handler` + `asyncio.Queue` パターン。
- callback_handler のクロージャでグループ番号を閉じ込め、Queue に `put_nowait`
- drain ループで `await asyncio.wait_for(queue.get(), timeout=0.1)` → yield
- 並列（`asyncio.gather`）でも各エージェントの callback が group 付きで Queue に入るため判別可能

#### 並列検証
3エージェント並列で10イベントがリアルタイム伝播。イベント到着順がインターリーブされ、並列動作を確認。
`asyncio.Queue` は thread-safe かつ async-safe なので、並列 callback から `put_nowait` しても安全。

#### 判断
- `stream_async` のネスト使用を廃止
- `invoke_async` + callback + Queue パターンを compose_slides の標準実装とする
- Phase C（直列）も Phase B（並列 gather）も同一パターンで対応可能
- 前回コミット（64105fc: asyncio.to_thread 方式）は revert し、このパターンで置き換える

### [2026-04-15 08:20] 修正完了 — compose_slides 進捗表示

#### 問題の全体像（3層）
進捗が表示されなかった原因は3層に分かれていた。

**Layer 1: バックエンド（agent/basic_agent.py）**
`stream_async` の `async for` ループ内で `yield` すると中間イベントが消失する問題。
→ `invoke_async` + `callback_handler` + `asyncio.Queue` パターンで解決（commit: 5f3ca7e）。

**Layer 2: ChatPanel.tsx — blocks 未再構築**
toolStream ハンドラが `toolUses` の `streamMessages` を更新しても、`blocks` を再構築していなかった。
ChatMessage は `message.blocks` 経由で ToolCard に props を渡すため、blocks が古いままだと streamMessages が伝播しない。
→ toolStream ハンドラ内で `rebuildBlocks` を呼ぶように修正（commit: a71d617）。

**Layer 3: ChatMessage.tsx — isActive 条件**
`isActive` が `i === blocks.length - 1`（最後のブロックのみ）だった。
compose_slides はテキストブロックの途中に挿入されるため、最後のブロックではなく常に false。
→ `streamMessages` が存在する場合も active にする条件を追加（commit: a71d617）。

#### デバッグ手法
1. strandsParser.js に全 SSE イベントの console.log を追加 → `toolStream` が SSE に来ていることを確認
2. ChatPanel.tsx の toolStream ハンドラに console.log → `findIndex: 0` で toolUses にマッチしていることを確認
3. blocks が再構築されていないことを特定 → rebuildBlocks 追加で解決

#### 副次的な修正
- buildspec.yml: SdpmAuth / SdpmWebUi が UPDATE_ROLLBACK_COMPLETE のため、`--all` を個別スタック指定に変更（commit: 3bcef4e）。TODO コメント付き。
- SdpmWebUi の孤立リソース（PreviewOAC, PreviewCachePolicy）は未修復。別 SPEC で対応予定。

#### tasks.md 更新
- [x] compose_slides の stream_async ネスト問題修正（invoke_async + callback + Queue パターンへ移行）

### [2026-04-15 09:09] リッチ進捗表示 — 実装と未解決問題

#### 実装内容
compose_slides の ToolCard 内にサブツールのアクティビティフィードを実装。

**バックエンド（agent/basic_agent.py）**:
- callback_handler を拡張: tool start（name + input + toolUseId）、toolUpdate（input パース完了時に再送）、toolResult（完了ステータス）の3種イベント
- `_try_parse_input()` ヘルパー追加: callback の input は最初不完全な JSON → パース可能になった時点で toolUpdate として再送
- ローカルテストでは全イベント（tool/toolUpdate/toolResult + input/toolUseId）が正しく出力されることを確認

**WebUI（ToolCard.tsx）**:
- `streamMessages` を `string[]` → `Record<string, unknown>[]` に変更
- サブツールリスト表示: アイコン（TOOL_META）+ ラベル + detail（getDetail）+ スピナー/チェック
- グループヘッダー: `Group 1/3 · ai-what`
- 完了カウント: `3 of 7 steps complete`
- `stripPrefix()` で MCP プレフィックス除去 → TOOL_META マッチ

**WebUI（ChatPanel.tsx）**:
- toolStream ハンドラを3分岐に拡張: `d.toolResult`（完了）、`d.toolUpdate`（input更新）、`d.tool`（新規）、`d.status`（グループ）

#### 未解決: toolUseId と input が SSE で消失
ブラウザの DevTools ログで `toolUseId` と `input` キーが `toolStream.data` に含まれていない。

**確認済み事実**:
1. ローカル Python テスト: callback → Queue → yield で `toolUseId` と `input` は正しく dict に入る ✅
2. Strands SDK テスト: `tool_stream_event.data` は yield した dict をそのまま通す ✅
3. JSON シリアライズ: `json.dumps` で `None` → `null`、キーは消えない ✅
4. strandsParser.js: `json.toolStream.data` をそのまま `toolCallback` に渡す ✅
5. ブラウザログ: `{"group":1,"slugs":"ai-what","tool":"run_python"}` — `toolUseId` と `input` がない ❌

**仮説**:
- AgentCore Runtime の `_safe_serialize_to_json_string` → `convert_complex_objects` が特定キーを除去？
- compose_slides の `_on_event` callback 内で `_try_parse_input` が呼ばれていない（コードパスの問題）？
- `85e10cc` コミットに `_try_parse_input` のコードが含まれているが、callback 内の分岐が正しく動いていない？

**次のアクション**:
- `85e10cc` のコミット内容を精査し、callback の `_on_event` が `toolUseId` と `input` を Queue に入れるコードパスが正しいか確認
- 必要なら CloudWatch ログで実際の yield 内容を確認

#### コミット
- `221ae07` — rich sub-tool progress in compose_slides ToolCard（WebUI 3ファイル）
- `85e10cc` — separate model config（バックエンド、あなたのコミット。_try_parse_input 含む）

### [2026-04-15 09:41] measure の slug 対応 — Engine まで一貫化

#### 問題
`format_measure_report` が `Slide {page_num}:` でページ番号を出力していた。
Layer 3 の `run_python` は slug → ページ番号変換を持っていたが、結果の逆変換がなかった。
さらに Engine の `measure()` API 自体が `list[int]` しか受け付けず、slug の概念がなかった。

#### 検討
Layer 3 で文字列置換する案もあったが、Engine がディレクトリ入力（deck.json + slides/*.json）に
対応した時点で measure も slug ベースにするのが自然。Layer 3 だけの対処は不整合を放置することになり、
Layer 2 が将来 slug 対応する際にまた同じ変換を書くことになる。
requirements.md の「Layer 1: 軽微な変更」というスコープ記述が実態に追いついていなかった。

#### 修正内容（commit: 61c8006）
- `skill/sdpm/preview/measure.py`: `format_measure_report` に `page_to_slug` オプション追加。slug があれば `Slide title:` のように出力
- `skill/sdpm/api.py`: `measure()` が `list[str]`（slug）を受け付けるように拡張。内部で slug → ページ番号変換 + 逆引きマッピング構築
- `mcp-server/server.py`: `_run_measure` に `page_to_slug` を渡す。既存の slug → ページ番号変換ロジックはそのまま活用

Layer 2 は `list[int]` のまま呼んでも `page_to_slug=None` で従来通り動くので後方互換維持。

### [2026-04-15 09:42] 並列化実装 — 4タスク完了

#### 1. compose_slides 並列化（commit: c857d82）
直列 `for` ループを `asyncio.Semaphore` + `asyncio.gather` に切り替え。
- 全グループ共有の `asyncio.Queue` で進捗を集約（notes [2026-04-15 07:00] で検証済みのパターン）
- `return_exceptions=True` で個別失敗を収集、失敗グループのみ直列リトライ（最大1回）
- `COMPOSER_MAX_CONCURRENCY` 環境変数（デフォルト 3）

注意点: `_prefetch_deck_specs` が `call_tool_sync`（同期呼び出し）を使っており、並列時に event loop をブロックする可能性がある。Strands SDK の MCPClient 内部実装次第。実測で確認が必要。

#### 2. グループ分割判断基準（commit: 011a50d）
SPEC エージェントの system prompt に 2 ステップのグループ分割基準を追加。
design.md のアルゴリズムをそのまま prompt 化。

#### 3. 全体ビルド + レポート組み立て（commit: 011a50d）
compose_slides の最後に generate_pptx + outline_check を実行。
- generate_pptx: `call_tool_sync` で PPTX ビルド
- outline_check: outline.md のスラグリストと generated_slides を比較し、missing/extra を報告
- preview_images はレポートに含めない（SPEC エージェントが事後レビューで get_preview を自分で呼ぶ）

#### 4. 事後レビューワークフロー（commit: 9a8b8f3）
SPEC エージェントの system prompt に事後レビュー手順を追加。
- outline_check の missing 確認
- get_preview で全スライド画像取得
- レイアウト重複、メッセージ接続、伏線回収、デザイン一貫性をチェック
- 問題があれば compose_slides を再呼び出し（該当 slug のみ）
