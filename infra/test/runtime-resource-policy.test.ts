// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Both AgentCore runtimes and every endpoint callers use carry a resource-based
 * policy that allows only InvokeAgentRuntime + StopRuntimeSession (and, on the agent
 * runtime, InvokeAgentRuntimeWithWebSocketStream for the Web UI's /ws) and denies
 * InvokeAgentRuntimeCommand.
 */

import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as s3 from "aws-cdk-lib/aws-s3";
import { AgentStack } from "../lib/agent-stack";
import { RuntimeStack } from "../lib/runtime-stack";

const RESOURCE_POLICY = "AWS::BedrockAgentCore::ResourcePolicy";

function synth(): { runtime: Template; agent: Template } {
  const app = new cdk.App();
  const env = { account: "123456789012", region: "ap-northeast-1" };
  const deps = new cdk.Stack(app, "Deps", { env });
  const table = new dynamodb.TableV2(deps, "Table", {
    partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
  });
  const pptxBucket = new s3.Bucket(deps, "Pptx");
  const resourceBucket = new s3.Bucket(deps, "Resources");

  const runtime = new RuntimeStack(app, "Runtime", {
    env,
    table,
    pptxBucket,
    resourceBucket,
    allowedClients: [],
    useAuthStack: true,
  });
  const agent = new AgentStack(app, "Agent", {
    env,
    mcpRuntimeArn: runtime.runtimeArn,
    allowedClients: [],
    useAuthStack: true,
    allowedModelIds: [],
  });
  return { runtime: Template.fromStack(runtime), agent: Template.fromStack(agent) };
}

/** Render a CloudFormation string value, replacing intrinsics with readable placeholders. */
function render(value: unknown): string {
  if (typeof value === "string") return value;
  const v = value as Record<string, any>;
  if (v["Fn::Join"]) return (v["Fn::Join"][1] as unknown[]).map(render).join(v["Fn::Join"][0]);
  if (v["Fn::GetAtt"]) return `<${v["Fn::GetAtt"].join(".")}>`;
  if (v.Ref) return `<${v.Ref}>`;
  throw new Error(`unexpected intrinsic: ${JSON.stringify(value)}`);
}

function logicalIdOf(template: Template, type: string): string {
  const ids = Object.keys(template.findResources(type));
  assert.equal(ids.length, 1, `expected one ${type}`);
  return ids[0];
}

const INVOKE_AND_STOP = ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:StopRuntimeSession"];

function assertAllowedOnly(template: Template, endpointLogicalId: string, allowed: string[]) {
  const runtimeId = logicalIdOf(template, "AWS::BedrockAgentCore::Runtime");
  const runtimeArn = `<${runtimeId}.AgentRuntimeArn>`;
  const expectedArns = [
    runtimeArn,
    `${runtimeArn}/runtime-endpoint/DEFAULT`,
    `<${endpointLogicalId}.AgentRuntimeEndpointArn>`,
  ];

  const policies = Object.values(template.findResources(RESOURCE_POLICY)).map((r) => ({
    arn: render(r.Properties.ResourceArn),
    doc: JSON.parse(render(r.Properties.Policy)),
  }));
  assert.deepEqual(policies.map((p) => p.arn).sort(), [...expectedArns].sort());

  for (const { arn, doc } of policies) {
    assert.deepEqual(doc, {
      Version: "2012-10-17",
      Statement: [
        {
          Sid: "AllowInvokeAndStop",
          Effect: "Allow",
          Principal: "*",
          Action: allowed,
          Resource: arn,
        },
        {
          Sid: "DenyCommand",
          Effect: "Deny",
          Principal: "*",
          Action: ["bedrock-agentcore:InvokeAgentRuntimeCommand"],
          Resource: arn,
        },
      ],
    });
  }
}

const { runtime, agent } = synth();

test("MCP runtime, its DEFAULT endpoint and sdpm_endpoint allow only invoke and stop", () => {
  assertAllowedOnly(runtime, logicalIdOf(runtime, "AWS::BedrockAgentCore::RuntimeEndpoint"), INVOKE_AND_STOP);
});

test("agent runtime, its DEFAULT endpoint and sdpm_agent_endpoint allow invoke, the WebSocket and stop", () => {
  assertAllowedOnly(agent, logicalIdOf(agent, "AWS::BedrockAgentCore::RuntimeEndpoint"), [
    ...INVOKE_AND_STOP,
    "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream",
  ]);
});

test("McpHttpApi proxy targets the DEFAULT endpoint, which carries a policy", () => {
  const fns = Object.values(runtime.findResources("AWS::Lambda::Function")).filter(
    (r) => r.Properties.Environment?.Variables?.RUNTIME_URL,
  );
  assert.equal(fns.length, 1);
  assert.match(render(fns[0].Properties.Environment.Variables.RUNTIME_URL), /\/invocations\?qualifier=DEFAULT$/);
});
