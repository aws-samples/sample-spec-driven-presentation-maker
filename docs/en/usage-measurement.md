# Measuring Usage (Per-User Tokens & Slide Counts)

For PoC operators who want to measure how much each user consumes — Bedrock
tokens and slides created. All measurement is done in CloudWatch; there is no
end-user-facing UI for this.

## What gets logged

The agent and MCP runtime emit structured JSON events (one line each):

| Event (`kind`) | Emitted when | Key fields | Log group |
|---|---|---|---|
| `bedrock_usage` | After every model invocation (agent and composers) | `user_id`, `session_id`, `deck_id`, `model_id`, `purpose`, `input`, `output`, `cache_read`, `cache_write` | Agent runtime (`/aws/bedrock-agentcore/runtimes/sdpm_agent-*`) |
| `slides_composed` | After each `compose_slides` call | `user_id`, `deck_id`, `generated`, `total`, `status` | Agent runtime |
| `slides_built` | After each successful `generate_pptx` | `user_id`, `deck_id`, `slide_count` | MCP runtime (`/aws/bedrock-agentcore/runtimes/sdpm-*`) |

`user_id` is the Cognito user's `sub` claim.

Note on slide counts: `slides_composed` counts slides written by composers
(rewrites count as new activity); `slides_built` counts slides in each PPTX
build (rebuilds count again). Pick the semantics that fit your report.

## Per-user token usage (Logs Insights)

Select the **agent runtime** log group in CloudWatch Logs Insights.
The runtime wraps log lines with a logger prefix, so JSON fields are not
auto-discovered — parse them explicitly (verified working):

```
filter @message like /"kind": "bedrock_usage"/
| parse @message '"user_id": "*"' as user_id
| parse @message '"model_id": "*"' as model_id
| parse @message '"input": *,' as input_tokens
| parse @message '"output": *,' as output_tokens
| parse @message '"cache_read": *,' as cache_read_tokens
| parse @message '"cache_write": *' as cache_write_tokens
| stats sum(input_tokens) as inputTokens,
        sum(output_tokens) as outputTokens,
        sum(cache_read_tokens) as cacheReadTokens,
        sum(cache_write_tokens) as cacheWriteTokens,
        count(*) as invocations
  by user_id, model_id
| sort inputTokens desc
```

## Per-user slide counts

Agent runtime log group (slides composed):

```
filter @message like /"kind": "slides_composed"/
| parse @message '"user_id": "*"' as user_id
| parse @message '"generated": *,' as generated
| stats sum(generated) as slidesComposed, count(*) as composeRuns by user_id
```

MCP runtime log group (PPTX builds):

```
filter @message like /"kind": "slides_built"/
| parse @message '"user_id": "*"' as user_id
| parse @message '"slide_count": *' as slide_count
| stats sum(slide_count) as slidesBuilt, count(*) as builds by user_id
```

## Span-based queries (Transaction Search)

The agent is instrumented with ADOT (OpenTelemetry). If you enable CloudWatch
Transaction Search, every span lands in the `aws/spans` log group with
`attributes.user.id` and `gen_ai` token attributes, and the
**CloudWatch GenAI Observability** dashboard (sessions, latency, token usage,
traces) becomes available.

Enable it at deploy time (account-level setting, one per region — skipped if
already enabled):

```yaml
# infra/config.yaml
features:
  enableTransactionSearch: true
```

or `bash scripts/deploy.sh --enable-transaction-search`.

Then query `aws/spans`. Filter on model-invocation spans
(`gen_ai.operation.name = "chat"`) — token usage also appears on the parent
`invoke_agent` span, so without this filter every token is counted twice:

```
filter attributes.gen_ai.operation.name = "chat" and attributes.user.id != ""
| stats sum(attributes.gen_ai.usage.input_tokens) as inputTokens,
        sum(attributes.gen_ai.usage.output_tokens) as outputTokens
  by attributes.user.id
```

Notes:

- Span ingestion into `aws/spans` is 100%; the default 1% only affects
  trace-summary indexing, not measurement accuracy.
- Ingested spans are billed per CloudWatch pricing — fine at PoC scale.
- This is independent from `enableInvocationLogging` (Bedrock model invocation
  logging), which records prompt text and has different privacy implications.

## Estimating cost

Multiply the token sums by the model's unit prices from
[Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
(input / output / cache-read / cache-write are priced differently).
For authoritative spend, use AWS Cost Explorer / CUR.
