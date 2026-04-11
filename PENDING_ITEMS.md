# CloudFront Preview Delivery — 保留事項

## PR
- https://github.com/aws-samples/sample-spec-driven-presentation-maker/pull/42

## 解消済み
- ~~PR #40との統合~~ → rebase完了、マージ済み
- ~~PPTX/JSONダウンロードのS3 presigned URL~~ → CF署名付きURLに移行

## 残保留事項

### 1. head_objectコールの最適化
署名付きURLでもhead_objectは残る（webp/png存在確認用）。
将来的にはDynamoDBにプレビューS3キーを記録し、head_objectを省略可能。

### 2. openssl依存
署名にLambda環境のopensslコマンドを使用。Lambda Python 3.13ランタイムには
opensslが含まれているが、カスタムランタイムでは注意が必要。

### 3. アップロード画像のpresigned URL
`uploads/tmp/`配下の画像プレビューはS3 presigned URLのまま。
アップロードは一時的なデータなのでCF化の優先度は低い。
