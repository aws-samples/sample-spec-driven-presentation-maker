<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Tech (Public)

## Deployment
- WebUI: `AWS_DEFAULT_REGION=<region> bash scripts/deploy_webui.sh`
- CDK stacks: SdpmWebUi, SdpmAgent, SdpmRuntime, SdpmData, SdpmAuth
- Which stack to redeploy for a change:
  - `sdpm/references/**` (bundled styles, workflows, guides, templates) → **SdpmData**
    (BucketDeployment uploads `references/` to the resource bucket; the API Lambda serves
    the Web UI style gallery from there and caches it per cold start) **and SdpmRuntime**
    (the MCP image bundles `sdpm/references/` for `list_styles` / `apply_style`).
    Deploying only SdpmRuntime leaves the Web UI gallery on the old style set.
  - `sdpm/sdpm/**`, `servers/remote/**` → SdpmRuntime
  - `agent/**` → SdpmAgent
  - `web-ui/**` → `scripts/deploy_webui.sh` (no CDK)
  - `api/**`, `infra/**` → SdpmWebUi (or the stack that owns the resource)
  - Single stack: `deploy.sh --stack "<Stack> --exclusively"`

## npm Dependency Management (web-ui / infra)

### Lockfile rule — CodeBuild is npm 10
`package-lock.json` must stay npm-10 compatible (deploy CodeBuild runs npm 10;
npm 11 writes locks that fail `npm ci` there — see PR #250 / #254).

After any dependency change:

```bash
npx -y npm@10.8.2 install --package-lock-only
npx -y npm@10.8.2 ci --dry-run   # must exit 0
git add package-lock.json        # commit IMMEDIATELY — run nothing in between
```

Any local `npm install` / `npm test` run after the resync silently rewrites
the lock back to npm-11 format (this exact mistake shipped once in #254).

### Major bumps
- Dependabot delivers majors as a separate grouped PR (`web-ui-majors` /
  `infra-majors`) — never mixed into the weekly minor/patch group
- CI is the first-pass verification; merge if green, close with upstream-blocker
  evidence if red
- Before bumping, check the dependency is actually used (react-dropzone was
  removed, not bumped — zero usages)
- Known-blocked majors are pinned in `.github/dependabot.yml` `ignore:` with
  re-evaluation triggers in the comment

## Onboarding surfaces — where things live

| Concern | File |
|---|---|
| Installer (source → generated `dist/`) | `scripts/install/install.{sh,ps1}`, `lib/tui.*`, `build.sh` |
| `sdpm` launcher | `scripts/install/launcher.{sh,ps1}` |
| Client detection / config / registration | `servers/local/client_config.py` (+ `tests/test_client_config.py`) |
| MCP handshake smoke used by CI | `scripts/install/mcp_smoke.py` |
| Installer CI (3 OS, real install, handshake) | `.github/workflows/installer.yml` |
| Claude Desktop bundle | `scripts/mcpb/`, `scripts/build_mcpb.sh`, `release.yml` |
| Preview dependency reporting | `sdpm/sdpm/engine/preview/environment.py` |
| Icon catalog auto-install | `sdpm/sdpm/knowledge/assets/download.py` (`ensure_assets_installed_async`) |
| User-facing contract | `docs/en/getting-started.md`, `docs/en/migration-onboarding.md` |

State the installer leaves in `~/.sdpm`: `checkout/`, `.profile` (full \| mcp), `.uv-path`,
`.agent-name`. Local smoke: see `scripts/install/README.md` (isolated `SDPM_HOME`, local
git mirror as `SDPM_REPO_URL`).

## Security Scanning
- ASH (Automated Security Helper) v3
- Local: `ash scan --mode local --fail-on-findings`
- Install: `alias ash="uvx git+https://github.com/awslabs/automated-security-helper.git@v3"`
- CI: GitHub Actions `.github/workflows/` で `--fail-on-findings` 付きで実行
- md5等の非セキュリティ用途ハッシュには `usedforsecurity=False` を付与（bandit B303）
