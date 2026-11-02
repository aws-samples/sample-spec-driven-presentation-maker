// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Resource-based policies that allow only the data-plane operations the app
 * uses on an AgentCore Runtime: InvokeAgentRuntime and StopRuntimeSession.
 *
 * AgentCore evaluates the resource-based policies of both the runtime and the
 * endpoint being invoked, so one policy is attached to the runtime, one to its
 * DEFAULT endpoint (the qualifier every caller uses) and one to each named
 * endpoint passed in. Once a runtime or endpoint has a policy, actions the
 * policy does not allow are denied; InvokeAgentRuntimeCommand is also denied
 * explicitly.
 *
 * The runtimes use a JWT (OAuth) authorizer, for which AgentCore requires the
 * wildcard principal: the token is validated before the policy is evaluated,
 * so "*" here does not widen who can call the runtime.
 * https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html
 */

import * as cdk from "aws-cdk-lib";
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import { Construct } from "constructs";

/** Operations the Web UI, the agent and external MCP clients call on the runtimes. */
export const ALLOWED_RUNTIME_ACTIONS = [
  "bedrock-agentcore:InvokeAgentRuntime",
  "bedrock-agentcore:StopRuntimeSession",
];

/** Operations denied explicitly, so they stay blocked even if an Allow is widened later. */
export const DENIED_RUNTIME_ACTIONS = ["bedrock-agentcore:InvokeAgentRuntimeCommand"];

export interface RuntimeResourcePolicyProps {
  /** ARN of the runtime (`CfnRuntime.attrAgentRuntimeArn`). */
  readonly runtimeArn: string;
  /**
   * Named endpoints of the runtime (`CfnRuntimeEndpoint.attrAgentRuntimeEndpointArn`).
   * The DEFAULT endpoint is always covered and must not be listed here.
   */
  readonly endpointArns?: Record<string, string>;
}

export class RuntimeResourcePolicy extends Construct {
  constructor(scope: Construct, id: string, props: RuntimeResourcePolicyProps) {
    super(scope, id);

    const targets: Record<string, string> = {
      Runtime: props.runtimeArn,
      // DEFAULT is created with the runtime and has no CloudFormation resource of its own.
      DefaultEndpoint: cdk.Fn.join("", [props.runtimeArn, "/runtime-endpoint/DEFAULT"]),
      ...props.endpointArns,
    };

    for (const [targetId, resourceArn] of Object.entries(targets)) {
      new bedrockagentcore.CfnResourcePolicy(this, targetId, {
        resourceArn,
        policy: cdk.Stack.of(this).toJsonString({
          Version: "2012-10-17",
          Statement: [
            {
              Sid: "AllowInvokeAndStop",
              Effect: "Allow",
              Principal: "*",
              Action: ALLOWED_RUNTIME_ACTIONS,
              Resource: resourceArn,
            },
            {
              Sid: "DenyCommand",
              Effect: "Deny",
              Principal: "*",
              Action: DENIED_RUNTIME_ACTIONS,
              Resource: resourceArn,
            },
          ],
        }),
      });
    }
  }
}
