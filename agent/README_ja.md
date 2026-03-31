> 📝 [English README](README.md)

# Agent — Spec-Driven Presentation Maker

Layer 4 の Agent コンポーネント。[Strands Agent](https://github.com/strands-agents/sdk-python) を使用し、Amazon Bedrock AgentCore Runtime 上にデプロイされる。MCP サーバー経由でツールにアクセスし、プレゼンテーション生成を実行する。

認証方式は JWT Bearer（呼び出し元の JWT をそのまま MCP サーバーへ転送）。

---

## アーキテクチャ概要

Agent は以下の 2 種類のツールを組み合わせて動作する。

- **MCP サーバー** — 外部ツール（プレゼン生成、AWS ドキュメント、料金情報）
- **ビルトインツール** — Agent コンテナ内のローカル関数（ファイル読み取り、Web 取得）

```
User → AgentCore Runtime → Agent
                             ├── MCP: pptx-maker (AgentCore Runtime + JWT)
                             ├── MCP: AWS Knowledge (Public, no auth)
                             ├── MCP: AWS Pricing (Local stdio)
                             ├── Built-in: upload_tools
                             └── Built-in: web_tools
```

---

## MCP サーバーパターン

`basic_agent.py` の `create_agent()` で 3 つの接続パターンを使用している。

### Pattern 1: AgentCore Runtime + JWT Bearer

AgentCore Runtime 上の MCP サーバーに JWT を転送して接続する。

```python
def _mcp_agentcore_runtime(jwt_token: str) -> MCPClient:
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=120,
            terminate_on_close=False,
        ),
    )
```

### Pattern 2: Public Remote MCP（認証なし）

公開 MCP サーバーに直接接続する。

```python
def _mcp_aws_knowledge() -> MCPClient:
    return MCPClient(
        lambda: streamablehttp_client(url="https://knowledge-mcp.global.api.aws"),
    )
```

### Pattern 3: Local stdio MCP

コンテナ内でローカルプロセスとして実行する。

```python
def _mcp_aws_pricing() -> MCPClient:
    from mcp.client.stdio import StdioServerParameters, stdio_client

    return MCPClient(
        lambda: stdio_client(StdioServerParameters(
            command="awslabs.aws-pricing-mcp-server",
            env={**os.environ, "AWS_REGION": "us-east-1", "FASTMCP_LOG_LEVEL": "ERROR"},
        )),
    )
```

---

## ビルトインツール

### upload_tools（`tools/upload_tools.py`）

| 関数 | 説明 |
|---|---|
| `read_uploaded_file(upload_id)` | アップロードファイルの内容を読み取る |
| `list_uploads(session_id)` | セッション内のアップロード一覧を取得する |

### web_tools（`tools/web_tools.py`）

| 関数 | 説明 |
|---|---|
| `web_fetch(url)` | 指定 URL の内容を Markdown として取得する |

---

## 環境変数

| 変数 | 説明 |
|---|---|
| `MCP_RUNTIME_ARN` | L3 MCP Server の Runtime ARN |
| `MEMORY_ID` | Amazon Bedrock AgentCore Memory ID |
| `MODEL_ID` | Bedrock モデル ID（デフォルト: `global.anthropic.claude-sonnet-4-6`） |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | AWS リージョン（デフォルト: `us-east-1`） |
| `DECKS_TABLE` | DynamoDB テーブル名（upload_tools 用） |
| `PPTX_BUCKET` | S3 バケット名（upload_tools 用） |

---

## ディレクトリ構成

```
agent/
├── basic_agent.py          # メインエージェント（エントリポイント）
├── tools/
│   ├── upload_tools.py     # read_uploaded_file, list_uploads
│   └── web_tools.py        # web_fetch
├── requirements.txt
├── Dockerfile
└── __init__.py
```

---

## Docker

### ビルド

```bash
docker build -t pptx-maker-agent .
```

### 実行

```bash
docker run -p 8080:8080 pptx-maker-agent
```

- ポート: `8080`
- ヘルスチェック: `http://localhost:8080/ping`
- エントリポイント: `opentelemetry-instrument python -m basic_agent`

---

## ドキュメント

| ドキュメント | 説明 |
|---|---|
| [はじめに](../docs/ja/getting-started.md) | Layer 1〜4 のセットアップ手順 |
| [アーキテクチャ](../docs/ja/architecture.md) | 4 層設計、データフロー、認証モデル |
| [エージェント接続](../docs/ja/add-to-gateway.md) | AgentCore と MCP クライアントの設定 |
