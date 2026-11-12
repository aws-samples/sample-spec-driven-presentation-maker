// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The MCP and agent runtimes' platform version is declared in the stacks, and
 * their configuration holds no per-deploy value (each new version rebuilds the
 * V2 snapshot). Asset bundling skipped.
 */

import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { DataStack } from "../lib/data-stack";
import { RuntimeStack } from "../lib/runtime-stack";
import { AgentStack } from "../lib/agent-stack";

const MODEL = "global.anthropic.claude-sonnet-4-6";

function synth(): { runtime: Template; agent: Template } {
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
  });
  const agent = new AgentStack(app, "SdpmAgent", {
    env,
    mcpRuntimeArn: runtime.runtimeArn,
    allowedClients: [],
    useAuthStack: true,
    chatModelId: MODEL,
    createModelId: MODEL,
    allowedModelIds: [MODEL],
  });
  return { runtime: Template.fromStack(runtime), agent: Template.fromStack(agent) };
}

function runtimeResources(template: Template) {
  return Object.values(template.findResources("AWS::BedrockAgentCore::Runtime"));
}

const first = synth();
const again = synth();
const stacks = [
  { name: "MCP runtime", first: runtimeResources(first.runtime), again: runtimeResources(again.runtime) },
  { name: "agent runtime", first: runtimeResources(first.agent), again: runtimeResources(again.agent) },
];

for (const { name, first: runtimes, again: rerun } of stacks) {
  test(`the ${name} runs on platform version V2`, () => {
    assert.equal(runtimes.length, 1);
    assert.equal(runtimes[0].Properties.PlatformVersion, "V2");
  });

  test(`the ${name}'s configuration holds no per-deploy value`, () => {
    // Two synths of the same inputs give the same runtime: an unchanged deploy creates no version.
    assert.deepEqual(rerun[0].Properties, runtimes[0].Properties);
    const vars = runtimes[0].Properties.EnvironmentVariables as Record<string, unknown>;
    assert.equal("DEPLOY_TIMESTAMP" in vars, false);
  });
}
