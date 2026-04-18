// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Reusable WAF WebACL construct for IP-based access restriction.
 * Based on the pattern from generative-ai-use-cases-jp.
 *
 * Usage:
 *   scope: 'CLOUDFRONT' — must be deployed in us-east-1
 *   scope: 'REGIONAL'   — deployed in the same region as the resource
 */

import { Lazy, Names } from "aws-cdk-lib";
import { CfnIPSet, CfnWebACL, CfnWebACLProps } from "aws-cdk-lib/aws-wafv2";
import { Construct } from "constructs";

export interface CommonWebAclProps {
  readonly scope: "REGIONAL" | "CLOUDFRONT";
  readonly allowedIpV4AddressRanges?: string[];
  readonly allowedIpV6AddressRanges?: string[];
}

export class CommonWebAcl extends Construct {
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: CommonWebAclProps) {
    super(scope, id);

    const suffix = Lazy.string({ produce: () => Names.uniqueId(this) });
    const rules: CfnWebACLProps["rules"] = [];

    const ruleProps = (name: string) => ({
      name,
      action: { allow: {} },
      visibilityConfig: {
        sampledRequestsEnabled: true,
        cloudWatchMetricsEnabled: true,
        metricName: name,
      },
    });

    if (props.allowedIpV4AddressRanges && props.allowedIpV4AddressRanges.length > 0) {
      const ipSet = new CfnIPSet(this, "IPv4Set", {
        ipAddressVersion: "IPV4",
        scope: props.scope,
        addresses: props.allowedIpV4AddressRanges,
      });
      rules.push({
        priority: 1,
        ...ruleProps("IpV4SetRule"),
        statement: { ipSetReferenceStatement: { arn: ipSet.attrArn } },
      });
    }

    if (props.allowedIpV6AddressRanges && props.allowedIpV6AddressRanges.length > 0) {
      const ipSet = new CfnIPSet(this, "IPv6Set", {
        ipAddressVersion: "IPV6",
        scope: props.scope,
        addresses: props.allowedIpV6AddressRanges,
      });
      rules.push({
        priority: 2,
        ...ruleProps("IpV6SetRule"),
        statement: { ipSetReferenceStatement: { arn: ipSet.attrArn } },
      });
    }

    const webAcl = new CfnWebACL(this, "WebAcl", {
      defaultAction: { block: {} },
      name: `WebAcl-${suffix}`,
      scope: props.scope,
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        sampledRequestsEnabled: true,
        metricName: `WebAcl-${suffix}`,
      },
      rules,
    });
    this.webAclArn = webAcl.attrArn;
  }
}
