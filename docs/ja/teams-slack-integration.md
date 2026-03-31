[EN](../en/teams-slack-integration.md) | [JA](../ja/teams-slack-integration.md)

# Microsoft Teams・Slack 連携

Spec-Driven Presentation Maker の Layer 4 Agent をそのまま Microsoft Teams や Slack から利用する方法を説明します。

## 概要

Layer 4 の Agent は Amazon Bedrock AgentCore Runtime 上で HTTPS エンドポイントを公開しており、JWT Bearer 認証付きの `POST /invocations` で呼び出せます。Slack Bot や Teams Bot から直接この Agent を呼び出すことで、チャットプラットフォーム上でプレゼンテーション生成が可能になります。

```
Teams / Slack
  ↓ Webhook / Bot Event
API Gateway + Lambda（ボットハンドラ）
  ↓ HTTPS + JWT Bearer（SSE ストリーミング）
AgentCore Runtime（spec-driven-presentation-maker Agent — Layer 4）
  ↓ MCP
AgentCore Runtime（spec-driven-presentation-maker MCP Server — Layer 3）
  ↓
DynamoDB + S3（デッキ・PPTX・プレビュー）
```

Layer 4 Agent はワークフロー制約（Phase 1 → 2 → 3）、MCP ツール接続、セッション管理を全て内蔵しているため、ボットハンドラ側で AI ロジックを実装する必要はありません。ボットハンドラの責務は「メッセージの中継」と「SSE レスポンスの読み取り」だけです。

## 前提条件

- spec-driven-presentation-maker Layer 3 + Layer 4 がデプロイ済み（[はじめに — Layer 4](getting-started.md#layer-4-フルスタックaws)参照）
- JWT トークンを取得できる認証基盤（認証設定の詳細は[はじめに — 認証オプション](getting-started.md#認証オプション)を参照）

---

## Agent Runtime の呼び出し方

Teams/Slack どちらの場合も、ボットハンドラから Agent Runtime を以下の形式で呼び出します。

### エンドポイント

```
POST https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations?qualifier=DEFAULT
```

| ヘッダー | 値 |
|---|---|
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer {JWT_TOKEN}` |

### リクエストボディ

```json
{
  "prompt": "AWS の Well-Architected について5枚のスライドを作成してください",
  "runtimeSessionId": "slack-U12345-1710000000",
  "userId": "user-sub-from-jwt"
}
```

`runtimeSessionId` をユーザー+チャンネル単位で固定すると、会話の継続が可能です。

### レスポンス

SSE（Server-Sent Events）ストリーム。テキストチャンク、ツール実行状況、最終結果が順次返されます。

```
data: {"event":{"contentBlockDelta":{"delta":{"text":"スライドを作成します"}}}}
data: {"toolStart":{"name":"init_presentation","toolUseId":"abc123"}}
data: {"toolResult":{"toolUseId":"abc123","status":"success","content":"{\"deckId\":\"a1b2c3d4\"}"}}
data: {"keepalive":true}
```

ボットハンドラでは SSE を最後まで読み取り、テキストチャンクを結合して最終メッセージを構築します。

### JWT トークンの取得

#### デフォルト Amazon Cognito（client_credentials フロー）

```python
import base64
import json
import urllib.request

creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
req = urllib.request.Request(
    f"https://{COGNITO_DOMAIN}/oauth2/token",
    data=b"grant_type=client_credentials&scope=sdpm/invoke",
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {creds}",
    },
)
with urllib.request.urlopen(req) as resp:
    token = json.loads(resp.read())["access_token"]
```

クライアントシークレットは AWS Secrets Manager に保管し、Lambda 実行中にキャッシュしてください。

---

## Slack 連携

### 方法 1: Slack Bolt + Lambda（推奨）

[Slack Bolt for Python](https://slack.dev/bolt-python/) を使用して Lambda ベースのボットを構築します。

#### 1. Slack App を作成

1. [Slack API](https://api.slack.com/apps) → Create New App
2. OAuth & Permissions で以下のスコープを追加:
   - `app_mentions:read` — メンション検知
   - `chat:write` — メッセージ送信
   - `files:write` — PPTX ファイルアップロード（任意）
3. Event Subscriptions を有効化:
   - `app_mention` イベントを購読
   - Request URL に Amazon API Gateway のエンドポイントを設定
4. ワークスペースにインストールし、Bot Token を取得

#### 2. Lambda ハンドラ

```python
import json
import os
import urllib.request

from slack_bolt import App
from slack_bolt.adapter.aws_lambda import SlackRequestHandler

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    process_before_response=True,
)


def _invoke_agent(prompt: str, session_id: str) -> str:
    """Layer 4 Agent を呼び出し、最終テキストを返す。"""
    # Agent Runtime を呼び出し（SSE ストリーミング）
    token = _get_oauth_token()  # Cognito client_credentials
    escaped_arn = urllib.request.quote(os.environ["AGENT_RUNTIME_ARN"], safe="")
    url = (
        f"https://bedrock-agentcore.{os.environ['AWS_REGION']}.amazonaws.com"
        f"/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"
    )
    body = json.dumps({
        "prompt": prompt,
        "runtimeSessionId": session_id,
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    # SSE ストリームを読み取り、テキストを結合
    text_parts = []
    with urllib.request.urlopen(req, timeout=540) as resp:
        buffer = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line_bytes, buffer = buffer.split(b"\n", 1)
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                    delta = (data.get("event", {})
                             .get("contentBlockDelta", {})
                             .get("delta", {})
                             .get("text"))
                    if delta:
                        text_parts.append(delta)
                except (json.JSONDecodeError, KeyError):
                    pass
    return "".join(text_parts)


@app.event("app_mention")
def handle_mention(event, say):
    """メンションを受け取り、Agent に転送して返信する。"""
    user_message = event["text"]
    thread_ts = event.get("thread_ts", event["ts"])
    user_id = event["user"]
    channel = event["channel"]

    # セッション ID をユーザー+スレッド単位で固定（会話継続）
    session_id = f"slack-{user_id}-{thread_ts}"

    say(text="作成中です...", thread_ts=thread_ts)

    response = _invoke_agent(prompt=user_message, session_id=session_id)
    say(text=response, thread_ts=thread_ts)


def handler(event, context):
    """Lambda エントリポイント。"""
    slack_handler = SlackRequestHandler(app=app)
    return slack_handler.handle(event, context)
```

#### 3. インフラ構成

```
Slack Events API
  ↓ HTTPS POST
API Gateway (REST)
  ↓ Lambda Proxy
Slack Bolt Lambda
  ↓ HTTPS + JWT Bearer (SSE)
AgentCore Runtime (spec-driven-presentation-maker Agent)
```

必要な環境変数:

| 変数 | 説明 |
|---|---|
| `SLACK_BOT_TOKEN` | Slack Bot OAuth Token（`xoxb-...`） |
| `SLACK_SIGNING_SECRET` | Slack App の Signing Secret |
| `AGENT_RUNTIME_ARN` | spec-driven-presentation-maker Agent の Amazon Bedrock AgentCore Runtime ARN |
| `AWS_REGION` | AWS リージョン |
| `COGNITO_DOMAIN` | Amazon Cognito ドメイン（トークン取得用） |
| `M2M_CLIENT_ID` | Amazon Cognito M2M クライアント ID |
| `M2M_CLIENT_SECRET_NAME` | AWS Secrets Manager シークレット名 |

#### 4. PPTX ファイルの共有（任意）

Agent が生成した PPTX を Slack に直接アップロードする場合:

```python
import requests

# generate_pptx の toolResult から deckId を抽出
pptx_url = f"https://{PPTX_BUCKET}.s3.amazonaws.com/pptx/{deck_id}/output.pptx"
# または S3 presigned URL を生成

app.client.files_upload_v2(
    channel=channel,
    file=requests.get(pptx_url).content,
    filename=f"{deck_name}.pptx",
    thread_ts=thread_ts,
)
```

### 方法 2: Slack Workflow Builder（ローコード）

Slack の Workflow Builder + Webhook ステップで、コーディングなしで連携を構築できます。ただし、SSE ストリーミングの読み取りが必要なため、中間に Lambda を置く方法 1 が推奨です。

---

## Microsoft Teams 連携

### 方法 1: Azure Bot Service + Lambda

1. [Azure Portal](https://portal.azure.com/) → Bot Services → 作成
2. メッセージングエンドポイントに Lambda の Amazon API Gateway URL を設定
3. Lambda ハンドラで Teams Bot Framework のメッセージをパースし、Agent Runtime に転送
4. Teams 管理センターでアプリを登録・配布

ボットハンドラの構造は Slack 版と同じです。メッセージのパース部分のみ Bot Framework SDK に置き換えてください。

### 方法 2: Power Virtual Agents（ローコード）

Microsoft Power Virtual Agents の「HTTP リクエスト」アクションで Agent Runtime を呼び出せます。ただし、SSE ストリーミングの処理が制限されるため、中間 Lambda を経由する構成が推奨です。

---

## セッション管理

Layer 4 Agent は Amazon Bedrock AgentCore Memory によるセッション管理を内蔵しています。`runtimeSessionId` を適切に設定することで、チャットプラットフォーム上でも会話の継続が可能です。

| プラットフォーム | セッション ID の推奨形式 | 効果 |
|---|---|---|
| Slack | `slack-{userId}-{threadTs}` | スレッド単位で会話継続 |
| Teams | `teams-{aadObjectId}-{conversationId}` | 会話単位で継続 |

同じセッション ID で呼び出すと、Agent は前回の会話コンテキストを保持した状態で応答します。

---

## セキュリティに関する注意事項

- Slack の Bot Token / Signing Secret は AWS Secrets Manager に保管してください
- Amazon Cognito のクライアントシークレットも AWS Secrets Manager に保管してください
- ボットの OAuth スコープは最小権限にしてください
- M2M（client_credentials）フローで取得したトークンはサービスアカウントとして動作します。ユーザーごとのアクセス制御が必要な場合は、各ユーザーの JWT を個別に取得する仕組みが必要です

---

## 関連ドキュメント

- [はじめに](getting-started.md) — Layer 3/4 のセットアップとデプロイ手順
- [エージェント接続](add-to-gateway.md) — Amazon Bedrock AgentCore Gateway 経由の接続
- [アーキテクチャ](architecture.md) — 認証・認可モデルの詳細
