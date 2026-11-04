// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Both runtimes keep GenAI message content out of their OTel logs, and the log
 * group AgentCore creates for each runtime gets a retention period without the
 * stacks ever deleting it. Asset bundling skipped.
 */

import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import * as logs from "aws-cdk-lib/aws-logs";
import { Template } from "aws-cdk-lib/assertions";
import { DataStack } from "../lib/data-stack";
import { RuntimeStack } from "../lib/runtime-stack";
import { AgentStack } from "../lib/agent-stack";
import { parseLogRetentionDays } from "../lib/construct/runtime-observability";

const MODEL = "global.anthropic.claude-sonnet-4-6";

function synth(logRetention?: logs.RetentionDays) {
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } });
  const env = { account: "111122223333", region: "ap-northeast-1" };
  const data = new DataStack(app, "SdpmData", { env, enableInvocationLogging: false, enableTransactionSearch: false });
  const runtime = new RuntimeStack(app, "SdpmRuntime", {
    env,
    table: data.table,
    pptxBucket: data.pptxBucket,
    resourceBucket: data.resourceBucket,
    allowedClients: [],
    useAuthStack: true,
    logRetention,
  });
  const agent = new AgentStack(app, "SdpmAgent", {
    env,
    mcpRuntimeArn: runtime.runtimeArn,
    allowedClients: [],
    useAuthStack: true,
    chatModelId: MODEL,
    createModelId: MODEL,
    allowedModelIds: [MODEL],
    logRetention,
  });
  return { runtime: Template.fromStack(runtime), agent: Template.fromStack(agent) };
}

const defaults = synth();
const stacks = [
  { name: "MCP runtime", template: defaults.runtime, runtimeLogicalIdPrefix: "SdpmRuntime" },
  { name: "agent runtime", template: defaults.agent, runtimeLogicalIdPrefix: "AgentRuntime" },
];

function only<T>(resources: Record<string, T>): [string, T] {
  const entries = Object.entries(resources);
  assert.equal(entries.length, 1);
  return entries[0];
}

function retentionResource(template: Template) {
  return only(template.findResources("Custom::LogRetention"))[1] as { Properties: Record<string, unknown> };
}

for (const { name, template, runtimeLogicalIdPrefix } of stacks) {
  test(`the ${name} turns off GenAI message content capture`, () => {
    const [, runtime] = only(template.findResources("AWS::BedrockAgentCore::Runtime"));
    const vars = runtime.Properties.EnvironmentVariables as Record<string, unknown>;
    assert.equal(vars.OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT, "false");
  });

  test(`the ${name}'s DEFAULT log group keeps logs for 30 days by default`, () => {
    const [runtimeId] = only(template.findResources("AWS::BedrockAgentCore::Runtime"));
    assert.ok(runtimeId.startsWith(runtimeLogicalIdPrefix));
    const props = retentionResource(template).Properties;
    assert.equal(props.RetentionInDays, 30);
    assert.deepEqual(props.LogGroupName, {
      "Fn::Join": [
        "",
        ["/aws/bedrock-agentcore/runtimes/", { "Fn::GetAtt": [runtimeId, "AgentRuntimeId"] }, "-DEFAULT"],
      ],
    });
  });

  test(`the ${name}'s log group is never deleted by the stack`, () => {
    assert.equal(retentionResource(template).Properties.RemovalPolicy, "retain");
    // No DeleteLogGroup permission for the retention handler.
    for (const policy of Object.values(template.findResources("AWS::IAM::Policy"))) {
      const statements = (policy.Properties.PolicyDocument.Statement ?? []) as { Action: string | string[] }[];
      for (const s of statements) {
        assert.equal([s.Action].flat().includes("logs:DeleteLogGroup"), false);
      }
    }
  });
}

test("observability.logRetentionDays sets the retention of both runtime log groups", () => {
  const custom = synth(logs.RetentionDays.ONE_WEEK);
  assert.equal(retentionResource(custom.runtime).Properties.RetentionInDays, 7);
  assert.equal(retentionResource(custom.agent).Properties.RetentionInDays, 7);
});

test("observability.logRetentionDays accepts CloudWatch values and defaults to 30", () => {
  assert.equal(parseLogRetentionDays(undefined), 30);
  assert.equal(parseLogRetentionDays(null), 30);
  assert.equal(parseLogRetentionDays(14), 14);
  assert.equal(parseLogRetentionDays(3653), 3653);
  for (const bad of [0, 2, 31, 9999, -1, "30", true]) {
    assert.throws(() => parseLogRetentionDays(bad), /observability\.logRetentionDays/);
  }
});
