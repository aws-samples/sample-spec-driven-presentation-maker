// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Execution roles of the agent runtime, the MCP runtime and the API Lambda grant
 * what their code uses. Synthesizes the stacks the way bin/infra.ts wires them
 * (AuthStack mode), with asset bundling skipped.
 */

import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { DataStack } from "../lib/data-stack";
import { RuntimeStack } from "../lib/runtime-stack";
import { AgentStack } from "../lib/agent-stack";
import { WebUiStack } from "../lib/web-ui-stack";

const ACCOUNT = "111122223333";
const REGION = "ap-northeast-1";
const MODEL = "global.anthropic.claude-sonnet-4-6";

function synth() {
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } });
  const env = { account: ACCOUNT, region: REGION };
  const data = new DataStack(app, "SdpmData", { env, enableInvocationLogging: false, enableTransactionSearch: false });
  const runtime = new RuntimeStack(app, "SdpmRuntime", {
    env,
    table: data.table,
    pptxBucket: data.pptxBucket,
    resourceBucket: data.resourceBucket,
    allowedClients: [],
    kbSsmParamName: data.kbSsmParamName || undefined,
    vectorBucketName: data.vectorBucketName || undefined,
    vectorIndexName: data.vectorIndexName || undefined,
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
  const webUi = new WebUiStack(app, "SdpmWebUi", {
    env,
    table: data.table,
    pptxBucket: data.pptxBucket,
    resourceBucket: data.resourceBucket,
    agentRuntimeArn: agent.agentRuntimeArn,
    memoryId: agent.memoryId,
    kbId: data.kbSsmParamName,
    vectorBucketName: data.vectorBucketName || undefined,
    vectorIndexName: data.vectorIndexName || undefined,
    defaultChatModelId: MODEL,
    defaultCreateModelId: MODEL,
    allowedModels: [],
  });
  return {
    runtime: Template.fromStack(runtime),
    agent: Template.fromStack(agent),
    webUi: Template.fromStack(webUi),
  };
}

const templates = synth();

type Statement = {
  Effect: string;
  Action: string | string[];
  Resource: unknown;
  Condition?: Record<string, Record<string, string>>;
  Sid?: string;
};

const asList = <T>(v: T | T[]): T[] => (Array.isArray(v) ? v : [v]);

/** Logical id of the only role whose logical id starts with `prefix`. */
function roleId(template: Template, prefix: string): string {
  const ids = Object.keys(template.findResources("AWS::IAM::Role")).filter((id) => id.startsWith(prefix));
  assert.equal(ids.length, 1, `expected one role starting with ${prefix}, got ${ids}`);
  return ids[0];
}

/** Every statement of the inline policies attached to the role. */
function statements(template: Template, role: string): Statement[] {
  const policies = Object.values(template.findResources("AWS::IAM::Policy"));
  return policies
    .filter((p) => asList(p.Properties.Roles).some((r: unknown) => JSON.stringify(r) === JSON.stringify({ Ref: role })))
    .flatMap((p) => p.Properties.PolicyDocument.Statement as Statement[]);
}

const allows = (s: Statement[]) => s.filter((x) => x.Effect === "Allow");
const actionsOf = (s: Statement[]) => s.flatMap((x) => asList(x.Action));

function assertTrustLimitedToAccount(template: Template, role: string) {
  const doc = template.findResources("AWS::IAM::Role")[role].Properties.AssumeRolePolicyDocument;
  assert.deepEqual(doc.Statement, [
    {
      Action: "sts:AssumeRole",
      Effect: "Allow",
      Principal: { Service: "bedrock-agentcore.amazonaws.com" },
      Condition: {
        StringEquals: { "aws:SourceAccount": ACCOUNT },
        ArnLike: { "aws:SourceArn": `arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:*` },
      },
    },
  ]);
}

// --- Agent runtime ---

const agentRole = roleId(templates.agent, "AgentRole");
const agentStatements = statements(templates.agent, agentRole);

test("agent role has no deck storage, AWS MCP or wildcard AgentCore access", () => {
  const actions = actionsOf(allows(agentStatements));
  for (const action of actions) {
    assert.doesNotMatch(action, /^(dynamodb|s3|aws-mcp|kms):/, action);
    assert.notEqual(action, "bedrock-agentcore:*");
  }
});

test("agent role uses Memory events on its own Memory only", () => {
  const agentcore = allows(agentStatements).filter((s) => actionsOf([s]).some((a) => a.startsWith("bedrock-agentcore:")));
  assert.deepEqual(agentcore, [
    {
      Effect: "Allow",
      Action: [
        "bedrock-agentcore:CreateEvent",
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:GetEvent",
        "bedrock-agentcore:DeleteEvent",
      ],
      Resource: { "Fn::GetAtt": ["AgentMemory", "MemoryArn"] },
    },
  ]);
});

test("agent role denies user-id delegation and calls through AWS-managed MCP servers", () => {
  const denies = agentStatements.filter((s) => s.Effect === "Deny");
  assert.deepEqual(
    denies.find((s) => s.Sid === "DenyUserIdDelegation")?.Action,
    ["bedrock-agentcore:InvokeAgentRuntimeForUser", "bedrock-agentcore:GetWorkloadAccessTokenForUserId"],
  );
  const viaMcp = denies.find((s) => s.Sid === "DenyViaAwsManagedMcp");
  assert.equal(viaMcp?.Action, "*");
  assert.equal(viaMcp?.Resource, "*");
  assert.deepEqual(viaMcp?.Condition, { Bool: { "aws:ViaAWSMCPService": "true" } });
});

test("agent role pulls images from the asset repository only", () => {
  for (const s of allows(agentStatements)) {
    const ecr = actionsOf([s]).filter((a) => a.startsWith("ecr:"));
    if (ecr.length === 0) continue;
    if (ecr.includes("ecr:GetAuthorizationToken")) {
      assert.deepEqual(ecr, ["ecr:GetAuthorizationToken"]);
      continue;
    }
    assert.notEqual(s.Resource, "*");
    assert.match(JSON.stringify(s.Resource), /:repository\//);
  }
});

test("agent trust policy is limited to AgentCore in this account", () => {
  assertTrustLimitedToAccount(templates.agent, agentRole);
});

test("agent runtime gets no deck storage names", () => {
  const runtimes = Object.values(templates.agent.findResources("AWS::BedrockAgentCore::Runtime"));
  assert.equal(runtimes.length, 1);
  const env = runtimes[0].Properties.EnvironmentVariables;
  assert.ok(env.MEMORY_ID);
  assert.equal(env.DECKS_TABLE, undefined);
  assert.equal(env.PPTX_BUCKET, undefined);
});

// --- MCP runtime ---

const mcpRole = roleId(templates.runtime, "RuntimeRole");
const mcpStatements = statements(templates.runtime, mcpRole);

test("MCP role has no AWS Marketplace permissions", () => {
  for (const action of actionsOf(mcpStatements)) assert.doesNotMatch(action, /^aws-marketplace:/);
});

test("MCP role grants ECR image pull on a repository, not on *", () => {
  for (const s of allows(mcpStatements)) {
    const ecr = actionsOf([s]).filter((a) => a.startsWith("ecr:") && a !== "ecr:GetAuthorizationToken");
    if (ecr.length > 0) assert.notEqual(s.Resource, "*");
  }
});

test("MCP trust policy is limited to AgentCore in this account", () => {
  assertTrustLimitedToAccount(templates.runtime, mcpRole);
});

// --- API Lambda ---

test("API Lambda lists events of the agent's Memory only", () => {
  const role = roleId(templates.webUi, "ApiLambdaServiceRole");
  const listEvents = statements(templates.webUi, role).filter((s) => actionsOf([s]).includes("bedrock-agentcore:ListEvents"));
  assert.equal(listEvents.length, 1);
  assert.equal(listEvents[0].Action, "bedrock-agentcore:ListEvents");
  const resource = JSON.stringify(listEvents[0].Resource);
  assert.match(resource, new RegExp(`arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:memory/`));
  assert.match(resource, /AgentMemory/);
});
