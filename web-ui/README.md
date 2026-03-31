> 📝 [日本語版 README はこちら](README_ja.md)

# Web UI — Spec-Driven Presentation Maker

Layer 4 Web UI for [Spec-Driven Presentation Maker](../README.md).
A React-based chat interface for creating presentations through conversational AI — design your spec, then let the agent build the slides.

![Chat UI](readme-imgs/fast-chat-screenshot.png)

---

## Tech Stack

- **Next.js 16** with Turbopack (static export)
- **React 19** / TypeScript 5
- **Tailwind CSS v4** / shadcn/ui / Radix UI
- **react-oidc-context** — Cognito OIDC authentication
- **react-markdown** + remark-gfm — Markdown rendering
- **react-dropzone** — File upload
- **sonner** — Toast notifications
- **PWA** — Service Worker + Web App Manifest

---

## Prerequisites

- Node.js 20+
- npm

---

## Quick Start

```bash
cd web-ui
npm install
npm run dev     # Starts dev server with Turbopack
```

Open [http://localhost:3000](http://localhost:3000).

> **Note:** Authentication is required by default. See the [Authentication](#authentication) section to configure or disable it.

---

## Authentication

Authentication uses OIDC via Cognito User Pool. Configuration is loaded from `public/aws-exports.json` at runtime, with optional environment variable overrides.

### Setup

1. Copy the example config:

```bash
cp public/aws-exports.example.json public/aws-exports.json
```

2. Fill in your Cognito values:

```json
{
  "authority": "https://cognito-idp.<REGION>.amazonaws.com/<USER_POOL_ID>",
  "client_id": "<CLIENT_ID>",
  "redirect_uri": "http://localhost:3000",
  "post_logout_redirect_uri": "http://localhost:3000",
  "response_type": "code",
  "scope": "openid profile email",
  "automaticSilentRenew": true,
  "agentRuntimeArn": "arn:aws:bedrock-agentcore:<REGION>:<ACCOUNT_ID>:runtime/<NAME>",
  "apiBaseUrl": "https://<API_GW_ID>.execute-api.<REGION>.amazonaws.com/prod/",
  "awsRegion": "<REGION>"
}
```

### Environment Variable Override

Environment variables (`NEXT_PUBLIC_COGNITO_*`) take priority over `aws-exports.json`:

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_COGNITO_REGION` | AWS region |
| `NEXT_PUBLIC_COGNITO_USER_POOL_ID` | Cognito User Pool ID |
| `NEXT_PUBLIC_COGNITO_CLIENT_ID` | Cognito App Client ID |
| `NEXT_PUBLIC_COGNITO_REDIRECT_URI` | OAuth redirect URI |
| `NEXT_PUBLIC_COGNITO_POST_LOGOUT_REDIRECT_URI` | Post-logout redirect URI |
| `NEXT_PUBLIC_COGNITO_RESPONSE_TYPE` | OAuth response type (default: `code`) |
| `NEXT_PUBLIC_COGNITO_SCOPE` | OAuth scopes (default: `email openid profile`) |
| `NEXT_PUBLIC_COGNITO_AUTOMATIC_SILENT_RENEW` | Auto token renewal (`true`/`false`) |

### Disabling Auth for Local Development

Authentication is enforced through a Next.js [Route Group](https://nextjs.org/docs/app/building-your-application/routing/route-groups). All protected pages live under `src/app/(authenticated)/`, which wraps children with `AuthProvider` in its `layout.tsx`:

```
src/app/
├── layout.tsx                    # RootLayout — no auth
└── (authenticated)/
    ├── layout.tsx                # AuthProvider wrapper
    ├── page.tsx                  # Redirects to /decks
    └── decks/page.tsx            # Main page
```

To bypass auth during local development, remove the `AuthProvider` wrapper in `src/app/(authenticated)/layout.tsx`:

Before:

```tsx
import { AuthProvider } from "@/components/auth/AuthProvider"

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}
```

After:

```tsx
export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
```

> ⚠️ This change is for local development only. Do not deploy to production.

---

## Project Structure

```
web-ui/
├── src/
│   ├── app/
│   │   ├── layout.tsx                  # RootLayout (Geist font, Toaster, PWA)
│   │   ├── globals.css
│   │   └── (authenticated)/
│   │       ├── layout.tsx              # AuthProvider wrapper
│   │       ├── page.tsx                # Root → /decks redirect
│   │       └── decks/page.tsx          # Main deck workspace
│   ├── components/
│   │   ├── ui/                         # shadcn/ui primitives
│   │   ├── auth/                       # AuthProvider, AutoSignin
│   │   ├── chat/                       # ChatPanel, ChatMessage, ToolCard, FileDropZone, etc.
│   │   ├── deck/                       # DeckCard, SlideCarousel, OutlineView, DeckListView, etc.
│   │   └── AppShell.tsx                # Header + layout shell
│   ├── hooks/                          # useAuth, useDeckList, useWorkspace, useSwipe, etc.
│   ├── lib/                            # auth.ts (Cognito config), utils.ts
│   ├── services/                       # deckService, uploadService, agentCoreService, parsers
│   └── types/
├── public/
│   ├── aws-exports.example.json        # Auth config template
│   ├── manifest.json                   # PWA manifest
│   └── sw.js                           # Service Worker
├── package.json
├── next.config.ts                      # Static export, build → build/
├── tsconfig.json
├── components.json                     # shadcn/ui config
└── postcss.config.mjs
```

---

## Key Components

### Chat (`components/chat/`)

Conversational interface for interacting with the agent. Includes message rendering with Markdown support, tool execution cards, file drag-and-drop upload, mention overlays, and slide tag references.

### Deck (`components/deck/`)

Presentation management — deck cards with thumbnails, slide carousel viewer, outline view, spec step navigation, search results grid, and deck CRUD actions.

### Auth (`components/auth/`)

OIDC authentication flow — `AuthProvider` wraps the Cognito OIDC context, `AutoSignin` handles automatic redirect-based sign-in.

---

## Documentation

| Document | Description |
|---|---|
| [Getting Started](../docs/en/getting-started.md) | Full setup guide for all layers |
| [Architecture](../docs/en/architecture.md) | 4-layer design, data flow, auth model |
| [CloudShell Deploy](../docs/en/deploy-cloudshell.md) | One-command deploy from CloudShell |

---

## License

[MIT-0](../LICENSE)
