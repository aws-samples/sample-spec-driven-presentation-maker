// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The MCP runtime's platform version is declared in the stack, and its
 * configuration holds no per-deploy value (each new version rebuilds the V2
 * snapshot). Asset bundling skipped.
 */

import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { DataStack } from "../lib/data-stack";
import { RuntimeStack } from "../lib/runtime-stack";

function synthRuntime(): Template {
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
  return Template.fromStack(runtime);
}

const runtimes = Object.values(synthRuntime().findResources("AWS::BedrockAgentCore::Runtime"));

test("the MCP runtime runs on platform version V2", () => {
  assert.equal(runtimes.length, 1);
  assert.equal(runtimes[0].Properties.PlatformVersion, "V2");
});

test("the MCP runtime's configuration holds no per-deploy value", () => {
  // Two synths of the same inputs give the same runtime: an unchanged deploy creates no version.
  const again = Object.values(synthRuntime().findResources("AWS::BedrockAgentCore::Runtime"));
  assert.deepEqual(again[0].Properties, runtimes[0].Properties);
  const vars = runtimes[0].Properties.EnvironmentVariables as Record<string, unknown>;
  assert.equal("DEPLOY_TIMESTAMP" in vars, false);
});
