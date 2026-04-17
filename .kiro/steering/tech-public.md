<!-- PUBLIC: This file is git-tracked and visible in the public repository. -->

# Tech (Public)

## Deployment
- WebUI: `AWS_DEFAULT_REGION=<region> bash scripts/deploy_webui.sh`
- CDK stacks: SdpmWebUi, SdpmAgent, SdpmRuntime, SdpmData, SdpmAuth

## Security Scanning
- ASH (Automated Security Helper) v3
- Local: `ash scan --mode local --fail-on-findings`
- Install: `alias ash="uvx git+https://github.com/awslabs/automated-security-helper.git@v3"`
- CI: GitHub Actions `.github/workflows/` で `--fail-on-findings` 付きで実行
- md5等の非セキュリティ用途ハッシュには `usedforsecurity=False` を付与（bandit B303）
