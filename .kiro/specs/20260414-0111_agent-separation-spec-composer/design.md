# Design: エージェント分離と並列スライド生成

## 対象レイヤー

```
Layer 4: Agent + Web UI（エージェント分離 + outline slug対応）
  ├─ SPECエージェント（Phase 1）
  └─ 実装エージェント（Phase 2+3）× N並列
  ↓ uses
Layer 3: Remote MCP Server（Storage層のファイル分割対応、旧フォーマット削除済み）
  ↓ uses
Layer 1: Skill Engine（_resolve_config のディレクトリ入力対応 + measure slug対応）
```

## ファイル分割

### S3レイアウト

```
decks/{deckId}/
  deck.json                        ← メタデータ（Phase 1で確定、Phase 2は読み取り専用）
  slides/{slug}.json               ← スライド1枚分（slugはoutline.mdと1:1対応）
  specs/brief.md
  specs/outline.md                 ← slug + メッセージ + 順序定義
  specs/art-direction.html
  includes/                        ← コードブロックJSON
  images/                          ← アップロード画像
```

### outline.md フォーマット

```markdown
- [slug] Message describing what this slide changes in the audience
  - what_to_say: ...
  - evidence: ...
  - what_to_show: ...
  - notes: ...
```

パース: `/^-\s*\[([a-z0-9-]+)\]\s*(.*)/` でslugとメッセージを抽出。行順 = スライド順。

### generate_pptx ビルド処理

```python
def _build_presentation_dict(deck_id, storage):
    deck = storage.get_deck_json(deck_id)          # deck.json
    slugs = parse_outline_slugs(deck_id, storage)   # outline.md → slug順序リスト
    slides = []
    for slug in slugs:
        slide = storage.get_slide_json(deck_id, slug)  # slides/{slug}.json
        slide.setdefault("id", slug)
        slides.append(slide)
    return {**deck, "slides": slides}                # Engine互換dict
```

### sandbox

sandbox内もそのまま分割構造:
```
deck.json
slides/title.json
slides/current-state.json
slides/feature-a.json
specs/...
includes/...
```

エージェントは `open("slides/feature-a.json")` で直接編集。
並列時は各エージェントが自分の担当slugだけ触る。

## エージェントアーキテクチャ

### Phase C: 直列

```
Web UI ←→ API ←→ AgentCore Runtime
                    └─ SPECエージェント（Phase 1）
                         │
                         │ @tool compose_slides(slide_groups)
                         ↓
                    実装エージェント（Phase 2 + 3）
                         │ uses
                         ↓
                    Layer 3: MCP Server tools
```

### Phase B: 並列

```
Web UI ←→ API ←→ AgentCore Runtime
                    └─ SPECエージェント（Phase 1）
                         │
                         │ @tool compose_slides(slide_groups)
                         ↓
                    ┌─ 実装エージェント 1（slides: title, problem, solution）
                    ├─ 実装エージェント 2（slides: demo-1, demo-2, demo-3）
                    └─ 実装エージェント 3（slides: architecture, next-steps, closing）
                         │ uses
                         ↓
                    Layer 3: MCP Server tools
```

Phase C と Phase B でツール名は同一（`compose_slides`）。内部が直列か並列かは実装の切り替えのみ。

## コンポーネント

### SPECエージェント

```python
spec_agent = Agent(
    system_prompt=SPEC_AGENT_PROMPT,
    tools=[*mcp_tools, compose_slides],
)
```

system prompt制約:
- Phase 1（briefing → outline → art-direction）のみ実行
- Phase 2のツール（build, measure等）は直接使わない
- 実装が必要な場合は compose_slides を呼び出す

### 実装エージェント — compose_slides

```python
@tool
def compose_slides(slide_groups: list[dict]) -> dict:
    """スライドを生成する。

    slide_groups: [{"slugs": ["title", "problem"], "instruction": "..."}]

    Phase C: 直列で1グループずつ処理
    Phase B: asyncio.gather で並列処理（内部切り替え）
    """
    results = []
    for group in slide_groups:
        agent = Agent(system_prompt=COMPOSER_PROMPT, tools=mcp_tools)
        results.append(agent(group["instruction"]))
    
    # 全composer完了後に全体ビルド + レポート組み立て
    return _build_compose_report(deck_id, results)
```

各エージェントは自分の担当slugのslides/{slug}.jsonだけを書く。
deck.jsonは全員が読むだけなので競合しない。

## グループ分割

SPECエージェントがoutline全体を見てグループを決定し、compose_slidesの引数で渡す。

### 分割アルゴリズム

2ステップで決定する:

**Step 1: 核グループの形成**
デザインを揃えたいスライド群を核（core group）としてまとめる。
- override継承（同一slug prefix）のスライドは必ず同一グループ（必須）
- 構造的に同じ役割のスライド（intro同士、demo同士等）は同一グループ（強く推奨）
- ユーザーが明示的に揃えたいと言ったスライド群は同一グループ

**Step 2: 独立スライドの振り分け**
核グループに属さない独立スライド（title, closing等）を、各グループの負荷が均等になるように振り分ける。
独立スライドだけのグループは作らない。

### 判断基準の補足
- 隣接スライドのレイアウト多様性はグループ分割では考慮しない（事後レビューで対応）
- グループ数やグループサイズの制約は課さない（並列度はsemaphoreで制御）
- 1枚だけの核グループは作らない（揃える対象がないため、独立スライドとして扱う）

### 例

```
outline:
  [title] [agenda] [intro-a] [intro-b] [intro-c] [detail-a] [detail-b] [demo] [next-steps] [closing]

Step 1 — 核グループ:
  核A: [intro-a, intro-b, intro-c]   ← 同じ役割、揃えたい
  核B: [detail-a, detail-b]          ← 同じ役割、揃えたい
  独立: [title, agenda, demo, next-steps, closing]

Step 2 — 独立スライドを振り分けて負荷均等化:
  グループ1: [intro-a, intro-b, intro-c, title]        ← 核A + 独立1枚
  グループ2: [detail-a, detail-b, agenda, demo, next-steps, closing] ← 核B + 独立4枚
```

核Aが3枚で重いので、独立スライドを核Bに多く振り分けて均等化。

```python
compose_slides(slide_groups=[
    {"slugs": ["intro-a", "intro-b", "intro-c", "title"]},
    {"slugs": ["detail-a", "detail-b", "agenda", "demo", "next-steps", "closing"]},
])
```

## 並列度制御

グループ分割（意味的判断）と並列度制御（インフラ制約）を分離する。

```python
sem = asyncio.Semaphore(max_concurrency)

async def run_with_limit(group):
    async with sem:
        return await run_composer(group)

results = await asyncio.gather(*[run_with_limit(g) for g in slide_groups])
```

- `max_concurrency` は環境変数またはconfig値で設定
- Phase C: max_concurrency=1（直列）
- Phase B: 3-5程度から開始し、実測で調整
- SPECエージェントはグループ数を気にせず意味的に最適な分割をする

## 並列生成後のレビュー（Phase 3強化）

レビューは2層構造:

### スライド単体の品質 → 各composerが担保
各composerはPhase 2+3のループ（build → measure → preview → adjust）を実行し、
担当スライドの品質を完結させてから返す。

### スライド間の一貫性 → SPECエージェントが事後レビュー
全composerの完了後、SPECエージェント自身がレビューする。
レビュー専用エージェントは立てない。

入力:
- get_preview の画像（全スライド）
- outline.md（メッセージの流れ）

スライドJSONは読まない（コンテキスト節約）。

チェック観点:
- 隣接スライドのレイアウト重複
- スライド間のメッセージ接続
- 伏線の回収
- デザイントークンの一貫性

修正が必要な場合、composer（直列）を再呼び出しして該当スライドだけ修正。
ユーザーからの修正要望も同じパス（SPECエージェント → composer）を通る。

### WebUI outlineParser変更

```typescript
// 現在
const SLIDE_RE = /^-\s*\[(\d+):\s*([^\]]+)\]\s*(.*)/

// 変更後
const SLIDE_RE = /^-\s*\[([a-z0-9-]+)\]\s*(.*)/
```

OutlineSlide:
- `num` → 削除（配列 index+1 で算出）
- `title` → `slug` にリネーム
- 表示: ノード円に連番（index+1）、slug を太字、message を下に

### API Lambda compose キー変更

```python
# 現在: ページ番号ベース
compose_key = _latest_compose_key(f"decks/{deck_id}/compose/slide_{i + 1}_", compose_keys)

# 変更後: slug ベース
compose_key = _latest_compose_key(f"decks/{deck_id}/compose/{slug}_", compose_keys)
```

## compose_slides 戻り値

SPECエージェントが次のアクションを判断するための報告を返す:

```python
{
  "generated_slides": ["title", "current-state", "feature-a"],
  "outline_check": {
    "expected": ["title", "current-state", "feature-a", "demo-1"],
    "missing": [],          # outline にあるが生成されなかった
    "extra": [],            # outline にないが生成された
  },
  "preview_images": [
    "decks/{deckId}/previews/epoch/slide-001.webp",
    ...
  ],
  "measure_summary": {
    "title": "OK",
    "current-state": "overflow detected",
  },
  "errors": []              # composer レベルのエラー
}
```

SPECエージェントはこの戻り値で:
- `outline_check` で漏れ確認
- `preview_images` で事後レビュー（画像で一貫性チェック）
- `measure_summary` で品質問題のあるスライドを特定 → 修正指示
- `errors` でリトライ判断

## _prepare_workspace と _assemble_slides の分離

現在の `_prepare_workspace` は I/O とデータ変換が混在。責務を分離する:

```python
_prepare_workspace(deck_id, user_id, storage)
  → S3からtmpdirにダウンロード（新旧どちらの形式でもそのまま）
  → テンプレート/アセット解決
  → return tmpdir, build_kwargs

_assemble_slides(tmpdir)
  → outline.md + slides/*.json から組み立て（deck.json前提）
  → 欠損スライドは黙ってスキップ（警告しない）
  → return slides
```

- `generate_pptx`: `_prepare_workspace` → `_assemble_slides` → ビルド
- `run_python` の measure: `_prepare_workspace` → `_assemble_slides` → 計測
- lint も `_assemble_slides` の戻り値を使う（`tmpdir / "presentation.json"` 直接読みを廃止）

## measure_slides の slug 化

`measure_slides` を `list[int]`（ページ番号）→ `list[str]`（slug）に変更:

- エージェントは slug で指定: `measure_slides=["current-state", "feature-a"]`
- 内部で `_assemble_slides` の結果から slug → ページ番号に変換して Engine に渡す
- 結果は slug ベースで返す（ページ番号はエージェントに見せない）
- 並列時、他の composer のスライドが未完成でもページ番号がずれるだけで問題なし

## sandbox の save 方式変更

paths リスト方式 → prefix ベース走査方式に変更:

```python
_WORKSPACE_PREFIXES = ("deck.json", "slides/", "specs/", "includes/")
```

- save 時に sandbox 内を走査し、`_WORKSPACE_PREFIXES` に合致するファイルを全部書き戻す
- upload 時の paths 記録は不要になる
- 新規作成された `slides/{slug}.json` や `specs/art-direction.html` も自動的にカバー
- `__pycache__/` 等のゴミファイルは prefix フィルタで除外

## 既存デッキの扱い

新フォーマット（deck.json + slides/*.json）のみサポート:

- `_assemble_slides` は deck.json 前提。presentation.json フォールバックなし
- `_prepare_workspace` は deck.json を必須としてダウンロード
- `api/index.py` は outline.md + slides/*.json のみ読み取り
- 新規デッキは常に新形式で作成
- 旧形式（presentation.json）のデッキは `convert_pptx` ツールで再変換が必要

## Storage ABC 追加メソッド

`storage/__init__.py` に抽象メソッドを追加:

```python
@abstractmethod
def get_deck_json(self, deck_id: str) -> dict: ...

@abstractmethod
def put_deck_json(self, deck_id: str, data: dict) -> None: ...

@abstractmethod
def get_slide_json(self, deck_id: str, slug: str) -> dict: ...

@abstractmethod
def put_slide_json(self, deck_id: str, slug: str, data: dict) -> None: ...
```

outline パースは Storage の責務ではなく `_assemble_slides` に置く。

## compose JSON 並列安全設計

### 問題

現状の compose 生成は `run_python(save=True)` のたびに全スライド分の compose JSON を再生成・旧 compose を全削除する。
並列 composer がほぼ同時に `run_python(save=True)` を完了すると:
- 各 composer の `_prepare_workspace` 時点の slides スナップショットが異なる
- compose upload の順序と prepare の順序が一致しない（ビルド時間の差）
- 後に upload した composer の compose が勝つが、そのスナップショットが最新とは限らない
- 他の composer が書いた compose を旧ファイルとして削除する

### 設計原則

**最新の slides/ スナップショットを使ってビルドした composer の compose が勝つべき。**

### 変更

| 項目 | 現状 | 変更後 |
|---|---|---|
| compose キー | `compose/slide_{N}_{epoch}.json` | `compose/{slug}_{epoch}.json` |
| 生成範囲 | 全スライド | `measure_slides` で指定された slug だけ |
| 旧 compose 削除 | `compose/` 以下を全削除 | 担当 slug のキーだけ削除 |
| epoch | compose upload 時刻 | `_prepare_workspace` 開始時点 |
| changed 判定 | sourceHash + スロット番号フォールバック | 同一 slug の前回 compose と component-level diff |
| defs | epoch 付き全削除+再生成 | prepare epoch で後勝ち（最新スナップショットの defs が勝つ） |

### 削除されるコード

sourceHash、prev_by_hash、prev_by_slot、prev_slot_map — slug ベースで前回 compose を直接引けるため不要。

### なぜ安全か

- 各 composer は自分の担当 slug の compose だけ書く → 書き込み対象が重ならない
- defs は後勝ちだが、全 composer が同じテンプレート・同じ outline から PPTX をビルドするため、
  同じスライドには同じ clipPath id が振られる → defs の後勝ちで描画が壊れない
- changed フラグは同一 slug の前回 compose と diff するだけ → 他の composer の影響を受けない
- 最終 `generate_pptx` で全スライド揃った状態の compose が生成され、正規化される

### compose 生成フロー（変更後）

```python
# run_python(save=True) 内
_epoch = int(time.time())  # prepare 開始時に記録
tmpdir, slides, build_kwargs = _prepare_workspace(...)
pptx_path = _build_pptx(...)

# compose: measure_slides の slug だけ生成
compose_prefix = f"decks/{deck_id}/compose/"
svg_path = _export_svg(tmpdir, pptx_path)

# defs: prepare epoch で後勝ち
defs_data = extract_optimized_defs(svg_path)
storage.upload_file(key=f"{compose_prefix}defs_{_epoch}.json", ...)

# 担当 slug だけ
for slug in measure_slugs:
    page_num = slug_to_page[slug]
    comp_data = split_slide_components(svg_path, page_num)

    # 前回 compose を同一 slug から取得して diff
    prev_key = _latest_key(f"{compose_prefix}{slug}_", old_keys)
    prev_comps = load_prev(prev_key) if prev_key else None
    mark_changed(comp_data, prev_comps)

    storage.upload_file(key=f"{compose_prefix}{slug}_{_epoch}.json", ...)

    # 旧 compose は担当 slug のキーだけ削除
    delete_old(f"{compose_prefix}{slug}_", old_keys)

# defs の旧キーも削除（自分の epoch より古いもの）
delete_old_defs(compose_prefix, old_keys, _epoch)
```

## エラーハンドリング（並列エージェント）

### 個別エージェント失敗時

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
```

- `return_exceptions=True` で個別失敗を例外オブジェクトとして収集
- 成功したスライドはそのまま保持（slides/{slug}.json は書き込み済み）
- 失敗したグループのみ直列composerでリトライ（最大1回）
- リトライも失敗した場合、SPECエージェントがユーザーに報告し判断を委ねる

### 部分ビルド

一部スライドが欠損した状態でもgenerate_pptxは実行可能とする:
- outline.mdに存在するがslides/{slug}.jsonがないスライドはスキップ + 警告ログ
- ユーザーが部分的な成果物を確認できるようにする

## Implementation Strategy

### Reusable
- 既存のMCP tools（インターフェース変更なし）
- 既存のワークフローファイル（Phase 1, Phase 2, Phase 3）
- art-direction.html のデザイントークン構造
- outlineParser.ts のパース構造（正規表現変更のみ）

### New
- Layer 1: _resolve_config のディレクトリ入力対応（deck.json + slides/*.json読み込み、presentation.json後方互換）
- Storage ABC: 抽象メソッド4つ追加（get/put_deck_json, get/put_slide_json）
- Storage層: deck.json / slides/{slug}.json の読み書きメソッド
- Storage層: outline.mdパース → slug順序リスト取得
- generate.py: _assemble_slides（I/Oとデータ変換の分離）
- generate.py: _build_presentation_dict（ビルド時組み立て）
- sandbox.py: prefix ベース走査による save 方式
- sandbox.py: deck.json + slides/ 構造の直接読み書き
- SPECエージェントの system prompt
- 実装エージェント（compose_slides）の `@tool` 定義 + system prompt + 戻り値レポート
- briefing ワークフローへの制約・素材セクション追加
- outlineワークフローのslug形式変更

### 変更が必要な既存ファイル
- `skill/sdpm/api.py` — _resolve_config のディレクトリ入力対応（deck.json + slides/*.json、presentation.json後方互換）
- `mcp-server/storage/__init__.py` — Storage ABC に抽象メソッド4つ追加
- `mcp-server/storage/aws.py` — deck.json / slides/*.json メソッド追加
- `mcp-server/tools/generate.py` — _prepare_workspace と _assemble_slides の分離、分割構造対応
- `mcp-server/tools/sandbox.py` — _WORKSPACE_PREFIXES 更新、prefix ベース走査 save
- `mcp-server/tools/init.py` — deck.json + slides/ 初期化
- `mcp-server/server.py` — run_python の measure_slides を list[str]（slug）に変更、lint の presentation.json 直接読みを廃止
- `web-ui/src/components/deck/outlineParser.ts` — slug形式対応
- `web-ui/src/components/deck/OutlineView.tsx` — slug + 連番表示
- `skill/references/workflows/create-new-1-outline.md` — slug形式に変更
- `skill/references/workflows/create-new-1-art-direction.md` — deck.json書き込み手順
- `agent/basic_agent.py` — エージェント分離、compose_slides ツール定義

---
**Created**: 2026-04-14
