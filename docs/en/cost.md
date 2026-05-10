[EN](../en/cost.md) | [JA](../ja/cost.md)

# Cost Estimates

Estimated AWS costs when deploying SDPM.

> Estimates based on publicly listed pricing as of April 2026. AWS pricing may change; always check the latest at [Amazon Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/), [AgentCore Pricing](https://aws.amazon.com/bedrock/agentcore/pricing/), [Amazon S3 Pricing](https://aws.amazon.com/s3/pricing/), and [DynamoDB Pricing](https://aws.amazon.com/dynamodb/pricing/).

## Overall estimate

Estimates for Layer 4 full stack (us-east-1). Assumes a team of ~10 users generating ~20 decks per month.

### Fixed costs (always running)

| Resource | Est. monthly |
|---|---|
| CloudFront | ~$1 |
| Cognito User Pool | $0 |
| API Gateway REST + Lambda (API) | ~$1 |
| S3 (3 buckets) | ~$1 |
| DynamoDB On-Demand | ~$1 |
| ECR (2 images) | ~$1 |
| CloudWatch Logs | ~$1 |

### Variable costs (usage-dependent)

| Resource | Est. for 20 decks/month |
|---|---|
| AgentCore Runtime (MCP Server + Agent) | ~$5-10 |
| Bedrock Claude Sonnet 4.6 (Agent LLM) | ~$80-130 |
| AgentCore Code Interpreter | ~$1-3 |
| AgentCore Memory | ~$1 |
| Slide search (Bedrock KB + Titan Embed V2 + S3 Vectors) | ~$0.01-0.05 |

### Total

**~$95–145/month** (varies with usage)

## How to stop the fixed charges

Fixed costs continue to accrue even when SDPM is not in use. If you no longer need the deployment, follow the [Uninstall Guide](uninstall.md) to clean up the resources.

## Related documents

- [Getting Started](getting-started.md) — Deployment architecture and options
- [Recommended Deploy Guide](deploy-cloudshell.md) — Deployment steps (CloudShell or local shell)
- [Uninstall Guide](uninstall.md) — Resource cleanup
