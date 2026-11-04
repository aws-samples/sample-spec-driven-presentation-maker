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
                             ├── MCP: spec-driven-presentation-maker (AgentCore Runtime + JWT)
                             ├── MCP: AWS Knowledge (Public, no auth)
                             ├── MCP: AWS Pricing (Local stdio)
                             ├── Built-in: upload_tools
                             └── Built-in: web_tools
```

---

## セッションランタイム

`basic_agent.py` は 2 つの入口を、1 つのセッションランタイム（`session_runtime.py`）の上で受ける。

- **`/ws`**（`ws_entry.py`）— Web UI の WebSocket。クライアントのメッセージは `prompt`、`steer`、
  `cancel`、`resume(from_seq)`、`prepare`、`ping`。サーバーは制御フレーム（`accepted`、`cancelAck`、
  `resumeAck`、`prepareAck`、`ready`、`pong`、`keepalive`、`error`）と、セッションのイベント
  `{"seq", "ev"}` を返す。`ev` は HTTP のストリームと同じ形に、`work`（busy / idle）、`turn`、
  `turnEnd`、`steer`、`taskStart`、`taskEnd`、`composerNote` を足したもの。フレームは 24,000 バイト以下（`{"batch": [...]}`、大きいイベントは
  `{"chunk", ...}`）で、20 ミリ秒に 1 つまで送る。最初に送るのはクライアント。セッションは最初の
  メッセージで、プラットフォームが転送する `Authorization` ヘッダから受け付け、以後のメッセージごとに
  持ち主を確かめる。
- **`/invocations`** — Local と外部のクライアント向けの HTTP ストリーミング。自分が始めたターンでは、
  今までと同じイベントと振る舞いになる。

セッションは MCP クライアント、Agent、Memory のセッションマネージャをターンをまたいで持つ
（`session_handle.py`。JWT はターンごとに `token_holder.py` で差し替える）。ターンが動いているか、
続きのターンが待っている間は「仕事中」で、その期間は `/ping` で HealthyBusy を返す。仕事中に送った
メッセージは steer になる（`steer_inbox.py`）。動いているターンの次の user メッセージに足してから
Memory に保存するか、終わろうとしているターンを続けるか、終わった後に届いたものは新しいターンにする。
イベントはセッションのリング（`event_ring.py`）で番号を振るので、つなぎ直したクライアントは
取りこぼした分を求められる。

ターンを止めるのは、停止ボタン（`cancel`。まだ届けていない steer を先に捨てる）、仕事中の期間の
60 分の番犬、SIGTERM の 3 つだけ。切断では止めない。

`compose_slides` はオーケストレーターの Strands バックグラウンドタスクとして動く（`background.py`）。
呼び出しはディスパッチの通知（`taskStart`）を返してすぐ戻り、コンポーザーが作業している間もターンは
続くか終わる。レポートが届くまでセッションは仕事中のまま。進捗は `toolStream` で届き続け、終わった
タスクは `taskEnd` として出る。ターンが動いていなければ入力なしのターン（`turn {why: "wake"}`）を
始め、Strands がモデル呼び出しの前にレポートをオーケストレーターに渡す。渡し方は user のテキスト
`<compose_result task status>` で、管理ツールの合成の呼び出しは履歴に入る前に書き換える。その間に送った steer は
すぐにターンになる。停止は仕事中の期間の停止イベント（コンポーザーも見る）を立ててからタスクを
キャンセルし、ターンが動いていなければタスクが書くデッキをフェンスする。コンポーザーの作業中、
オーケストレーターは `message_composer` でコンポーザーに伝え、コンポーザーは `report_to_orchestrator`
で答える（`compose_messaging.py`）。答えはセッションが `composerNote` として出し、`<composer_note>`
のテキストとして steer と同じように届ける（ターンが動いていなければ `turn {why: "report"}`）。

---

## MCP サーバーパターン

`factory.py` がセッションごとに 3 つの接続パターンを使用している。

### Pattern 1: AgentCore Runtime + JWT Bearer

AgentCore Runtime 上の MCP サーバーに JWT を転送して接続する。あわせて呼び出し元のセッション ID を、トークンの利用者の持ち主プレフィックス付きで `Mcp-Session-Id` として転送し、同一セッションのリクエストが同じ microVM に routing されるようにする。

```python
def _mcp_agentcore_runtime(jwt_token: str, session_id: str = "") -> MCPClient:
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    runtime_arn = os.environ["MCP_RUNTIME_ARN"]
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"

    headers = {"Authorization": f"Bearer {jwt_token}"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers=headers,
            timeout=120,
            terminate_on_close=False,
        ),
    )
```

> `Mcp-Session-Id` を省略してはいけない。AgentCore はヘッダーのないリクエストごとに
> 新しいセッション ID を発行するため、毎回新しい microVM に載り新セッション起動の
> コストを払う。本プロジェクトの MCP ランタイムを `ap-northeast-1` で実測した値は、
> 一貫した ID ありで 0.18〜0.20 秒、ID なしでウォーム容量がない場合 17.6〜19.7 秒。

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

---

## ディレクトリ構成

```
agent/
├── basic_agent.py          # メインエージェント（エントリポイント）
├── tools/
│   └── web_tools.py        # web_fetch
├── pyproject.toml          # 依存（ルートの uv.lock で固定）
├── Dockerfile
└── __init__.py
```

---

## Docker

### ビルド

```bash
docker build -t sdpm-agent .
```

### 実行

```bash
docker run -p 8080:8080 sdpm-agent
```

- ポート: `8080`
- ヘルスチェック: `http://localhost:8080/ping`
- エントリポイント: `opentelemetry-instrument python -m basic_agent`

---

## ドキュメント

| ドキュメント | 説明 |
|---|---|
| [開発者ガイド](../docs/en/developer-guide.md) | checkout での開発と CDK デプロイ |
| [アーキテクチャ](../docs/en/architecture.md) | 4 層設計、データフロー、認証モデル |
| [エージェント接続](../docs/en/add-to-gateway.md) | AgentCore と MCP クライアントの設定 |
