<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Tech (Public)

## Deployment
- WebUI: `AWS_DEFAULT_REGION=<region> bash scripts/deploy_webui.sh`
- CDK stacks: SdpmWebUi, SdpmAgent, SdpmRuntime, SdpmPngWorker, SdpmData, SdpmAuth

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

## Security Scanning
- ASH (Automated Security Helper) v3
- Local: `ash scan --mode local --fail-on-findings`
- Install: `alias ash="uvx git+https://github.com/awslabs/automated-security-helper.git@v3"`
- CI: GitHub Actions `.github/workflows/` で `--fail-on-findings` 付きで実行
- md5等の非セキュリティ用途ハッシュには `usedforsecurity=False` を付与（bandit B303）
