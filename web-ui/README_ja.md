# Web UI — Spec-Driven Presentation Maker

> 📝 [English README](README.md)

Spec-Driven Presentation Maker の Layer 4 Web UI コンポーネント。
チャットベースの対話でプレゼンテーションの設計・生成・プレビューを行う React アプリケーション。

![チャット画面](readme-imgs/fast-chat-screenshot.png)

---

## 技術スタック

| カテゴリ | 技術 |
|---|---|
| フレームワーク | Next.js 16 (Turbopack) / React 19 / TypeScript 5 |
| スタイリング | Tailwind CSS v4 / shadcn/ui / Radix UI |
| 認証 | react-oidc-context (Cognito User Pool) |
| その他 | react-markdown, react-dropzone, Lucide React, sonner |
| ビルド | Static export (`output: "export"`, `distDir: "build"`) |

---

## 前提条件

- Node.js 20+
- npm

---

## クイックスタート

```bash
cd web-ui
npm install
npm run dev
```

[http://localhost:3000](http://localhost:3000) をブラウザで開く。

---

## 認証

### 認証設定

認証は `public/aws-exports.json` から読み込まれる。`public/aws-exports.example.json` をコピーして設定する。

```bash
cp public/aws-exports.example.json public/aws-exports.json
```

環境変数で個別に上書きも可能（優先度: 環境変数 > aws-exports.json）:

```bash
export NEXT_PUBLIC_COGNITO_REGION=ap-northeast-1
export NEXT_PUBLIC_COGNITO_USER_POOL_ID=ap-northeast-1_XXXXXXX
export NEXT_PUBLIC_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
export NEXT_PUBLIC_COGNITO_REDIRECT_URI=http://localhost:3000
```

### 認証の構造

認証は Next.js の Route Group `(authenticated)` で制御されている。

```
src/app/
├── layout.tsx                  # RootLayout（認証なし）
└── (authenticated)/
    ├── layout.tsx              # AuthProvider でラップ
    ├── page.tsx                # / → /decks にリダイレクト
    └── decks/page.tsx          # メインページ
```

- `RootLayout` (`src/app/layout.tsx`) には AuthProvider は含まれない
- `AuthProvider` は `src/app/(authenticated)/layout.tsx` にのみ配置
- `(authenticated)` 配下の全ページが自動的に認証必須になる

### ローカル開発での認証無効化

認証なしで UI を開発する場合は、`src/app/(authenticated)/layout.tsx` の AuthProvider ラッパーを外す。

変更前:

```tsx
import { AuthProvider } from "@/components/auth/AuthProvider"

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}
```

変更後:

```tsx
export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
```

> ⚠️ この変更はローカル開発専用。本番環境にデプロイしないこと。

---

## プロジェクト構成

```
web-ui/
├── src/
│   ├── app/
│   │   ├── layout.tsx              # RootLayout（認証なし）
│   │   ├── globals.css
│   │   └── (authenticated)/
│   │       ├── layout.tsx          # AuthProvider ラッパー
│   │       ├── page.tsx            # / → /decks リダイレクト
│   │       └── decks/page.tsx      # メインページ
│   ├── components/
│   │   ├── ui/                     # shadcn/ui コンポーネント
│   │   ├── auth/                   # AuthProvider, AutoSignin
│   │   ├── chat/                   # ChatPanel, ChatMessage, ToolCard 等
│   │   ├── deck/                   # DeckCard, SlideCarousel, OutlineView 等
│   │   └── AppShell.tsx            # ヘッダー付きレイアウトシェル
│   ├── hooks/                      # useAuth, useDeckList, useWorkspace 等
│   ├── lib/                        # auth.ts（Cognito設定）, utils.ts
│   ├── services/                   # deckService, uploadService, agentCoreService
│   └── types/
├── public/
│   ├── aws-exports.example.json    # 認証設定テンプレート
│   ├── manifest.json               # PWA マニフェスト
│   └── sw.js                       # Service Worker
├── package.json
├── next.config.ts
├── tsconfig.json
├── components.json                 # shadcn/ui 設定
└── postcss.config.mjs
```

---

## 主要コンポーネント

### chat

チャットインターフェース。ユーザーとエージェントの対話、ファイルアップロード、ツール実行状況の表示を担当。

- `ChatPanel` — メインのチャット UI
- `ChatMessage` — メッセージの描画（Markdown 対応）
- `ToolCard` / `ToolIndicator` — エージェントのツール実行表示
- `FileDropZone` / `AttachmentPreview` — ファイルアップロード

### deck

プレゼンテーションの管理・プレビュー。デッキ一覧、スライドカルーセル、アウトライン表示を提供。

- `DeckCard` / `DeckListView` — デッキ一覧と検索
- `SlideCarousel` — スライドのプレビュー表示
- `OutlineView` / `SpecStepNav` — アウトラインとスペック進行状況
- `WorkspaceView` — ワークスペース管理

### auth

Cognito OIDC 認証フロー。

- `AuthProvider` — OIDC 設定の非同期読み込みとプロバイダーラップ
- `AutoSignin` — 自動サインインとリダイレクト処理

---

## ドキュメント

| ドキュメント | 説明 |
|---|---|
| [セットアップガイド](../docs/ja/getting-started.md) | Layer 1〜4 の構築手順 |
| [アーキテクチャ](../docs/ja/architecture.md) | 4層設計、データフロー、認証モデル |
| [CloudShell デプロイ](../docs/ja/deploy-cloudshell.md) | CloudShell からのワンコマンドデプロイ |

---

## ライセンス

[MIT-0](../LICENSE)
