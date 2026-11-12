[English](../en/programmatic-access.md) | [日本語](programmatic-access.md)

# プログラムからの利用

Cloud デプロイに対して自分の自動化を動かせます。たとえば AWS What's New の投稿ごとに短い
デッキを作るボットを、cron、AWS Lambda、AWS Step Functions で動かす使い方です。自動化は
**あなた自身として**デッキを作ります。デッキは Web UI のデッキ一覧に、作成したチャットと
一緒に表示されます。

ブラウザでのサインインは 1 回です。サインインで自動化にリフレッシュトークンが渡り、
自動化はその有効期限（既定 90 日）まで無人で動きます。期限が切れたら、もう一度サインイン
します。

フルスタック（`stacks.agent` と `stacks.webUi`）と既定の Cognito ユーザープールが必要です。
外部 OIDC IdP（`auth.oidcDiscoveryUrl`）では使えません。

## 有効にする

プログラム用クライアントは既定で無効です。`infra/config.yaml` で有効にします:

```yaml
auth:
  programmaticClient:
    enabled: true
    refreshTokenValidityDays: 90   # 1〜3650。既定 90
```

すべてのスタックをデプロイします（`SdpmAuth` がクライアントを作り、`SdpmAgent` と
`SdpmWebUi` がそれを受け入れます）。クライアントは Cognito ユーザープール内の OAuth
ネイティブアプリ用クライアント（RFC 8252）です:

| 設定 | 値 |
|---|---|
| クライアントの種類 | パブリック（クライアントシークレットなし） |
| フロー | PKCE 付き認可コードフロー |
| コールバック URL とサインアウト URL | `http://127.0.0.1:8765` のみ |
| スコープ | `openid profile email sdpm-mcp/invoke` |
| リフレッシュトークン | `refreshTokenValidityDays`（既定 90 日）、ローテーションなし |

Agent Runtime のオーソライザー（`allowedClients`）と REST API の JWT オーソライザー
（`jwtAudience`）がこのクライアントの ID を受け入れます。MCP ランタイムは
`sdpm-mcp/invoke` スコープを確認し、このクライアントのトークンはそのスコープを持ちます。
ブロックを無効に戻すとクライアントは削除され、発行済みのリフレッシュトークンはすべて
使えなくなります。

クライアント ID は `SdpmAuth` スタックから取得します:

```bash
aws cloudformation describe-stacks --stack-name SdpmAuth \
  --query "Stacks[0].Outputs[?OutputKey=='ProgrammaticClientId'].OutputValue" --output text
# または: aws ssm get-parameter --name /sdpm/auth/programmatic-client-id --query Parameter.Value --output text
```

クライアント ID は秘密情報ではありません。パブリッククライアントにシークレットはなく、
本人であることはサインインで証明します。

## リファレンスクライアント

[`examples/programmatic-client/sdpm_client.py`](../../examples/programmatic-client/sdpm_client.py)
は、このページの契約だけを使う 1 ファイルのクライアントです。自分のプロジェクトにコピーして、
必要に応じて変更してください。[uv](https://docs.astral.sh/uv/)（または `websockets` と
`boto3` を入れた Python 3.10 以上）が必要です。

デプロイの設定は Web UI サイトの公開ファイル `aws-exports.json` から読み、独自の設定を 3 つ、
オプションか環境変数で受け取ります:

| オプション | 環境変数 | 値 |
|---|---|---|
| `--site` | `SDPM_SITE` | Web UI の URL（`https://xxxx.cloudfront.net`） |
| `--client-id` | `SDPM_CLIENT_ID` | プログラム用クライアントの ID |
| `--store` | `SDPM_TOKEN_STORE` | リフレッシュトークンの保存先: `file:<パス>`（既定 `~/.config/sdpm-programmatic-client/token.json`）または `secretsmanager:<名前または ARN>` |

`login` はこの 3 つの設定（トークンは含まない）を
`~/.config/sdpm-programmatic-client/config.json` に保存するので、以降のコマンドには
オプションが要りません。

どのコマンドも JSON オブジェクトを 1 つ出力します。終了コード: `0` 完了、`1` エラー、
`2` 使い方の誤り、`3` リフレッシュトークンが期限切れ・失効・無効（もう一度サインイン）。

### login

```bash
cd examples/programmatic-client
uv run sdpm_client.py login --site https://xxxx.cloudfront.net --client-id <クライアント ID>
```

ブラウザで Cognito のサインインページを開き、`127.0.0.1:8765` へのリダイレクト 1 回を最大
5 分待ちます。待ち受けはループバックのみで、そのリダイレクトを受けたら止まります。続けて
リフレッシュトークンを、本人だけが読めるファイル（モード 0600）にリポジトリの外で保存します。
`--no-browser` を付けると、ブラウザを開かずに URL を表示します。

Lambda 関数などヘッドレスな実行環境にトークンを渡すときは、AWS Secrets Manager に直接
保存します。この場合ディスクには何も書きません:

```bash
uv run sdpm_client.py login --site https://xxxx.cloudfront.net --client-id <クライアント ID> \
  --store secretsmanager:sdpm/whatsnew-bot
```

シークレットがあれば更新し、なければ作成します。あなたの AWS 認証情報に
`secretsmanager:PutSecretValue`（新規作成には `secretsmanager:CreateSecret` も）が必要です。
シークレットの中身は JSON で、`refresh_token`、`client_id`、`obtained_at`（サインインした
時刻の Unix 時間）です。

### run

```bash
uv run sdpm_client.py run "<トピック> についてチーム向けの 3 枚のデッキを作ってください。質問はせず、妥当な既定で決めて PPTX まで作ってください。"
# {"sessionId": "c6c289e49e9c05b2-0f8c6a4e-...", "accepted": "turn"}
```

`run` は新しいトークンを取得し、新しいセッションを開いて `vibe` モードでプロンプトを送り、
エージェントが受け付けた時点（2〜4 秒）で切断します。エージェントは作業を続けます。表示された
`sessionId` を控えてください。プロンプトに `-` を渡すと標準入力から読みます。

答える人はいないので、エージェントが質問しなくて済むプロンプトにしてください。

### status

```bash
uv run sdpm_client.py status c6c289e49e9c05b2-0f8c6a4e-...
# {"sessionId": "...", "state": "done", "deckId": "...", "name": "...", "slideCount": 4, "hasPptx": true, "pptxUrl": "https://..."}
```

`state` は `pending`（デッキがまだない）、`in_progress`（デッキはあるが PPTX はまだ）、
`done`（PPTX がある）のいずれかです。dev 環境では 3〜5 枚のデッキに 2〜7 分かかりました。
確認は 1 分おき以上の間隔で行ってください。`pptxUrl` は短時間で期限が切れる署名付きの
ダウンロードリンクです。

## 契約

自作のクライアントが前提にしてよいのは次の内容です。それ以外（ほかの `/ws` メッセージ、
イベントのフィールド、ここにない REST のフィールド）は予告なく変わることがあります。

**設定。** `https://<サイト>/aws-exports.json` には `authority`（ユーザープールの発行者。
`<authority>/.well-known/openid-configuration` に認可エンドポイントとトークンエンドポイントが
あります）、`agentRuntimeArn`、`apiBaseUrl`、`awsRegion` があります。プログラム用クライアントの
ID は `SdpmAuth` の出力 `ProgrammaticClientId`（SSM `/sdpm/auth/programmatic-client-id`）です。

**トークン。** PKCE（`S256`）付き認可コードフローで、スコープ
`openid profile email sdpm-mcp/invoke`、リダイレクト URI `http://127.0.0.1:8765` を使って
サインインします。トークンエンドポイントで `refresh_token` グラントを使うと、アクセストークンと
ID トークン（有効期限 60 分）が返ります。`/ws` にはアクセストークン、REST API には ID トークンを
使います。リフレッシュトークンが拒否されると、HTTP 400 で `"error": "invalid_grant"` が返ります。

**セッション ID。** ジョブごとに新しい ID を 1 つ作ります。トークンの `sub` の SHA-256 の
先頭 16 文字（16 進）、ハイフン、ランダムな UUID をつなげたものです
（`c6c289e49e9c05b2-0f8c6a4e-2b1d-4c3e-9a7f-5d6e7f8a9b0c`）。ほかのユーザーのプレフィックスを
持つ ID はエージェントが拒否します。

**ジョブの開始（`/ws`）。**

- URL: `wss://bedrock-agentcore.<リージョン>.amazonaws.com/runtimes/<URL エンコードした agentRuntimeArn>/ws?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id=<セッション ID>`
- サブプロトコル: `base64UrlBearerAuthorization.<アクセストークンの base64url（パディングなし）>`
  と `base64UrlBearerAuthorization`。
- 先に送るのはクライアントです。
  `{"type": "prompt", "id": "<64 文字以内>", "prompt": "<本文>", "mode": "vibe"}` を送ります。
- エージェントは `{"ctl": "accepted", "id": "...", "as": "..."}` または
  `{"ctl": "error", "code": "...", "error": "..."}` を返します。
- 切断してもジョブは止まりません。接続したまま見届ける場合は、`{"type": "ping"}` を 25 秒以内の
  間隔で送り、WebSocket ライブラリのプロトコル ping は無効にします。
  `"ev": {"work": {"state": "idle"}}` のイベントが届いたらジョブは終わっています。イベントは
  `{"batch": [...]}` フレームにまとめて届くことも、`{"chunk": ...}` フレームに分割されて届く
  こともあります。

**デッキを見つけて完了を知る（REST、`Authorization: Bearer <ID トークン>`）。**

- `GET <apiBaseUrl>/decks`: 各項目に `chatSessionId` があります。`chatSessionId` がジョブの
  セッション ID と一致するデッキが、そのジョブのデッキです。
- `GET <apiBaseUrl>/decks/<deckId>`: `slideCount` と `pptxUrl`。
- デッキに PPTX がある（`pptxUrl` が入っている）とき、ジョブは完了しています。オーケストレーターの
  `turnEnd` イベントは完了ではありません。スライドの作成はその後もバックグラウンドで続きます。

## Lambda と Step Functions

Cognito にはデバイスコードフローがないため、最初のサインインには必ずブラウザが要ります。
ヘッドレスな実行環境は、`login --store secretsmanager:<名前>` で Secrets Manager に保存した
リフレッシュトークンを使います。

**Lambda 関数。** `sdpm_client.py` を `websockets` と一緒にパッケージします（`boto3` は Lambda の
Python ランタイムに含まれます）。たとえば
`uv pip install --target package websockets && cp sdpm_client.py package/`。ハンドラー:

```python
import sdpm_client as sdpm


def handler(event, context):
    # SDPM_SITE、SDPM_CLIENT_ID、SDPM_TOKEN_STORE=secretsmanager:sdpm/whatsnew-bot
    settings = sdpm.Settings.resolve()
    if event["action"] == "start":
        return sdpm.start_job(settings, event["prompt"])
    return sdpm.job_status(settings, event["sessionId"])
```

タイムアウトは 2 分にします。実行ロールに必要なのは、そのシークレット 1 つへの
`secretsmanager:GetSecretValue`（カスタマーマネージドキーで暗号化しているならそのキーへの
`kms:Decrypt`）だけです。関数は IAM ではなく、あなたのトークンを使って HTTPS で SDPM を呼びます。
デプロイが WAF で IP アドレスを制限している場合は、関数の送信元アドレスを許可してください。

**ステートマシン。** ジョブを開始し、デッキに PPTX ができるまで 1 分おきに確認し、リフレッシュ
トークンが期限切れならアラートを送ります。拒否されたリフレッシュトークンは
`RefreshTokenExpired` を送出し、Step Functions はそれをエラー名として受け取ります:

```json
{
  "Comment": "One deck from a prompt, created as the signed-in user",
  "TimeoutSeconds": 3600,
  "StartAt": "Start",
  "States": {
    "Start": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": { "FunctionName": "<関数の ARN>", "Payload": { "action": "start", "prompt.$": "$.prompt" } },
      "OutputPath": "$.Payload",
      "Catch": [{ "ErrorEquals": ["RefreshTokenExpired"], "Next": "SignInAgain" }],
      "Next": "Wait"
    },
    "Wait": { "Type": "Wait", "Seconds": 60, "Next": "Status" },
    "Status": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": { "FunctionName": "<関数の ARN>", "Payload": { "action": "status", "sessionId.$": "$.sessionId" } },
      "OutputPath": "$.Payload",
      "Catch": [{ "ErrorEquals": ["RefreshTokenExpired"], "Next": "SignInAgain" }],
      "Next": "Done?"
    },
    "Done?": {
      "Type": "Choice",
      "Choices": [{ "Variable": "$.state", "StringEquals": "done", "Next": "Done" }],
      "Default": "Wait"
    },
    "Done": { "Type": "Succeed" },
    "SignInAgain": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "<アラート用トピックの ARN>",
        "Message": "The SDPM refresh token has expired. Run: sdpm_client.py login --store secretsmanager:sdpm/whatsnew-bot"
      },
      "Next": "Failed"
    },
    "Failed": { "Type": "Fail", "Error": "RefreshTokenExpired" }
  }
}
```

Amazon EventBridge のスケジュールから、項目ごとに 1 回起動します。期限切れの後ではなく前に
知りたい場合は、シークレットの `obtained_at` と `refreshTokenValidityDays` を定期チェックで
比べてください。リフレッシュトークンのローテーションは無効のままです。1 つのトークンが有効期限
いっぱいまで使え、実行環境がシークレットを書き換える必要はありません。

## セキュリティ上の注意

- **リフレッシュトークンは、チャットでできることすべてです。** 持っている人は期限が切れるまで、
  あなたとしてデッキの作成・閲覧・削除やエージェントの利用ができます。パスワードと同じように
  扱ってください。
- **暗号化して保存します。** 自分のマシンでは 0600 のファイル、それ以外では Secrets Manager
  （AWS KMS で暗号化。カスタマーマネージドキーならキーポリシーで復号できる人を絞れます）を
  使います。リポジトリ、共有システムの環境変数、コンテナイメージには入れないでください。
- **最小権限。** シークレットを読めるのは実行環境のロールだけにします（そのシークレット ARN 1 つへの
  `GetSecretValue`）。書き込みは `login` のときにあなたの認証情報で行います。
- **トークンをログに残しません。** リファレンスクライアントはトークンも認可コードも出力しません。
  シークレットの値、トークンエンドポイントの応答、サブプロトコル付きの `/ws` URL をログに
  出さないでください。Step Functions の履歴に残るのはセッション ID とデッキの情報だけで、
  `pptxUrl` は短時間で切れる署名付きリンクです。
- **サインイン。** ループバックの待ち受けは `127.0.0.1` だけにバインドし、リダイレクトを 1 回
  受けたら止まります。PKCE と `state` の値で、リダイレクトを開始したサインインに結び付けます。
- **失効。** `aws cognito-idp admin-user-global-sign-out --user-pool-id <ID> --username <ユーザー>`
  でそのユーザーのリフレッシュトークンがすべて失効します（Web UI のセッションも含む）。
  `auth.programmaticClient` を無効にすると、クライアントと発行済みのトークンがすべて
  なくなります。
- **監査。** アクセストークンの `client_id` にはプログラム用クライアントの ID が入るので、自動化からの
  呼び出しと Web UI からの呼び出しを区別できます。

[Security](../en/security.md)（英語）と
[Architecture — Authentication and Authorization Model](../en/architecture.md#authentication-and-authorization-model)（英語）も
参照してください。
