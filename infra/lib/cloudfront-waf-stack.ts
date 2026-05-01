// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * CloudFront WAF Stack — deployed in us-east-1.
 *
 * WAF v2 WebACLs with scope CLOUDFRONT must reside in us-east-1.
 * This stack is only created when IP address restrictions are configured.
 */

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import { CommonWebAcl } from "./construct/common-web-acl";

interface CloudFrontWafStackProps extends cdk.StackProps {
  readonly allowedIpV4AddressRanges?: string[];
  readonly allowedIpV6AddressRanges?: string[];
}

export class CloudFrontWafStack extends cdk.Stack {
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: CloudFrontWafStackProps) {
    super(scope, id, props);

    const webAcl = new CommonWebAcl(this, "CloudFrontWebAcl", {
      scope: "CLOUDFRONT",
      allowedIpV4AddressRanges: props.allowedIpV4AddressRanges,
      allowedIpV6AddressRanges: props.allowedIpV6AddressRanges,
    });

    this.webAclArn = webAcl.webAclArn;

    new cdk.CfnOutput(this, "WebAclArn", { value: webAcl.webAclArn });
  }
}
