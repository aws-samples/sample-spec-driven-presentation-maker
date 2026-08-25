# 使用量の計測（ユーザー別トークン数・スライド作成数）

PoC 運営者向けに、ユーザーごとの Bedrock トークン消費量とスライド作成数を計測する
手順です。計測はすべて CloudWatch 上で行います（エンドユーザー向けの表示機能は
ありません）。

## 記録されるイベント

エージェントと MCP ランタイムは構造化 JSON イベント（1 行ずつ）を出力します:

| イベント (`kind`) | タイミング | 主なフィールド | ロググループ |
|---|---|---|---|
| `bedrock_usage` | 各モデル呼び出し後（エージェント・コンポーザー両方） | `user_id`, `session_id`, `deck_id`, `model_id`, `purpose`, `input`, `output`, `cache_read`, `cache_write` | Agent ランタイム (`/aws/bedrock-agentcore/runtimes/sdpm_agent-*`) |
| `slides_composed` | 各 `compose_slides` 呼び出し後 | `user_id`, `deck_id`, `generated`, `total`, `status` | Agent ランタイム |
| `slides_built` | `generate_pptx` 成功時 | `user_id`, `deck_id`, `slide_count` | MCP ランタイム (`/aws/bedrock-agentcore/runtimes/sdpm-*`) |

`user_id` は Cognito ユーザーの `sub` クレームです。

スライド数の意味に注意: `slides_composed` はコンポーザーが書いたスライド数
（リライトも新規カウント）、`slides_built` は PPTX ビルドごとの枚数
（再ビルドも再カウント）です。レポートの目的に合う方を使ってください。

## ユーザー別トークン使用量（Logs Insights）

CloudWatch Logs Insights で **Agent ランタイム**のロググループを選択:

```
filter kind = "bedrock_usage"
| stats sum(input) as inputTokens,
        sum(output) as outputTokens,
        sum(cache_read) as cacheReadTokens,
        sum(cache_write) as cacheWriteTokens,
        count(*) as invocations
  by user_id, model_id
| sort inputTokens desc
```

JSON フィールドが自動検出されない場合は明示的にパースします:

```
filter @message like /"kind": "bedrock_usage"/
| parse @message '"user_id": "*"' as user_id
| parse @message '"input": *,' as input
| parse @message '"output": *,' as output
| stats sum(input), sum(output), count(*) by user_id
```

## ユーザー別スライド作成数

Agent ランタイムのロググループ（コンポーズ枚数）:

```
filter kind = "slides_composed"
| stats sum(generated) as slidesComposed, count(*) as composeRuns by user_id
```

MCP ランタイムのロググループ（PPTX ビルド枚数）:

```
filter kind = "slides_built"
| stats sum(slide_count) as slidesBuilt, count(*) as builds by user_id
```

## スパンベースのクエリ（Transaction Search）

エージェントは ADOT（OpenTelemetry）で計装済みです。CloudWatch Transaction
Search を有効化すると、全スパンが `aws/spans` ロググループに取り込まれ
（`attributes.user.id` と `gen_ai` トークン属性付き）、**CloudWatch GenAI
Observability** ダッシュボード（セッション数・レイテンシ・トークン・トレース）
が使えるようになります。

デプロイ時に有効化します（アカウントレベル設定・リージョンごとに 1 つ。
既に有効な場合はスキップされます）:

```yaml
# infra/config.yaml
features:
  enableTransactionSearch: true
```

または `bash scripts/deploy.sh --enable-transaction-search`。

`aws/spans` へのクエリ:

```
filter ispresent(attributes.gen_ai.usage.input_tokens) and attributes.user.id != ""
| stats sum(attributes.gen_ai.usage.input_tokens) as inputTokens,
        sum(attributes.gen_ai.usage.output_tokens) as outputTokens
  by attributes.user.id
```

補足:

- `aws/spans` へのスパン取り込みは 100% です。デフォルトの 1% はトレース
  サマリーの index 対象の割合であり、計測精度には影響しません。
- 取り込まれたスパンは CloudWatch の料金体系で課金されます（PoC 規模なら軽微）。
- `enableInvocationLogging`（Bedrock モデル呼び出しログ）とは独立した設定です。
  invocation logging はプロンプト本文を記録するためプライバシー特性が異なります。

## コストの概算

トークン集計値に [Amazon Bedrock の料金](https://aws.amazon.com/jp/bedrock/pricing/)
の単価（input / output / cache-read / cache-write で異なる）を掛けて概算できます。
正確な請求額は AWS Cost Explorer / CUR を正としてください。
