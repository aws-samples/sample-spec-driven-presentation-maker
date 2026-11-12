// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";

/**
 * The AgentCore service principal for a runtime execution role's trust policy,
 * limited to AgentCore resources of this account and Region
 * (confused-deputy prevention, AgentCore Runtime security best practices).
 */
export function agentCoreServicePrincipal(stack: cdk.Stack): iam.ServicePrincipal {
  return new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com", {
    conditions: {
      StringEquals: { "aws:SourceAccount": stack.account },
      ArnLike: { "aws:SourceArn": `arn:aws:bedrock-agentcore:${stack.region}:${stack.account}:*` },
    },
  });
}
