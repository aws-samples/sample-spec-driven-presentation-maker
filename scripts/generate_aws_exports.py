#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Generate aws-exports.json from CDK outputs.

Usage:
    cdk deploy --all --outputs-file cdk-outputs.json
    python scripts/generate_aws_exports.py [--outputs cdk-outputs.json] [--out web-ui/public/aws-exports.json]
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    """Parse CDK outputs and generate aws-exports.json for web-ui."""
    parser = argparse.ArgumentParser(description="Generate aws-exports.json from CDK outputs")
    parser.add_argument("--outputs", default="infra/cdk-outputs.json", help="CDK outputs JSON file")
    parser.add_argument("--out", default="web-ui/public/aws-exports.json", help="Output path")
    args = parser.parse_args()

    outputs_path = Path(args.outputs)
    if not outputs_path.exists():
        raise FileNotFoundError(
            f"{outputs_path} not found. Run: cd infra && cdk deploy --all --outputs-file cdk-outputs.json"
        )

    with open(outputs_path) as f:
        cdk_outputs = json.load(f)

    # Extract values from stack outputs
    webui = cdk_outputs.get("SdpmWebUi", {})
    agent = cdk_outputs.get("SdpmAgent", {})

    region = webui.get("AwsRegion", "us-east-1")
    user_pool_id = webui.get("UserPoolId", "")
    client_id = webui.get("UserPoolClientId", "")
    api_url = webui.get("ApiUrl", "")
    agent_arn = agent.get("AgentRuntimeArn", "")

    authority = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}" if user_pool_id else ""

    aws_exports = {
        "authority": authority,
        "client_id": client_id,
        "redirect_uri": "",
        "post_logout_redirect_uri": "",
        "response_type": "code",
        "scope": "openid profile email",
        "automaticSilentRenew": True,
        "agentRuntimeArn": agent_arn,
        "apiBaseUrl": api_url,
        "awsRegion": region,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(aws_exports, f, indent=2)
        f.write("\n")

    print(f"Generated {out_path}")
    print(f"  authority: {authority}")
    print(f"  client_id: {client_id}")
    print(f"  apiBaseUrl: {api_url}")
    print(f"  agentRuntimeArn: {agent_arn}")

    if not aws_exports["redirect_uri"]:
        print("\n⚠️  redirect_uri is empty. After deploying to Amplify, set it to your app URL:")
        print(f"   Edit {out_path} and update redirect_uri / post_logout_redirect_uri")
        print("   Also add the URL to Cognito User Pool callback URLs in the console")


if __name__ == "__main__":
    main()
