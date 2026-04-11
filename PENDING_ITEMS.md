# CloudFront Preview Delivery — 保留事項

## PR
- https://github.com/aws-samples/sample-spec-driven-presentation-maker/pull/42

## 解消済み
- ~~PR #40との統合~~ → rebase完了、マージ済み
- ~~PPTX/JSONダウンロードのS3 presigned URL~~ → CF署名付きURLに移行
- ~~head_objectコールの最適化~~ → list_objects_v2 一括取得に変更（feat/text-bbox-measurement）

## 残保留事項

### 1. openssl依存
署名にLambda環境のopensslコマンドを使用。Lambda Python 3.13ランタイムには
opensslが含まれているが、カスタムランタイムでは注意が必要。

### 2. アップロード画像のpresigned URL
`uploads/tmp/`配下の画像プレビューはS3 presigned URLのまま。
アップロードは一時的なデータなのでCF化の優先度は低い。
