#!/usr/bin/env node
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// Security: This stack follows AWS security best practices for sample code.
// For production use, review and enhance IAM policies, encryption, and logging.
/**
 * CDK entry point — reads config.yaml and deploys only enabled stacks.
 *
 * Dependency chain:
 *   DataStack ──────┐
 *   AuthStack ──────┼→ RuntimeStack → AgentStack → WebUiStack
 *
 * Usage:
 *   cdk deploy --all                    # Deploy all enabled stacks
 *   cdk deploy SdpmData            # Deploy specific stack
 */

import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import * as fs from "fs";
import * as yaml from "yaml";
import * as path from "path";
import { DataStack } from "../lib/data-stack";
import { AuthStack } from "../lib/auth-stack";
import { RuntimeStack } from "../lib/runtime-stack";
import { AgentStack } from "../lib/agent-stack";
import { WebUiStack } from "../lib/web-ui-stack";
import { CloudFrontWafStack } from "../lib/cloudfront-waf-stack";
import { MODEL_METADATA } from "../lib/model-metadata";

// Load deployment configuration
const configPath = path.join(__dirname, "../config.yaml");
if (!fs.existsSync(configPath)) {
  console.error("Error: infra/config.yaml not found. Copy config.example.yaml to config.yaml and customize.");
  process.exit(1);
}
const config = yaml.parse(fs.readFileSync(configPath, "utf8"));

const app = new cdk.App();
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION,
};

// --- Auth: use config.yaml values or create default Amazon Cognito ---
const externalOidc = config.auth?.oidcDiscoveryUrl;
const externalClients = config.auth?.allowedClients;

let oidcDiscoveryUrl: string | undefined;
let allowedClients: string[];
let authStack: AuthStack | undefined;

if (externalOidc && externalClients) {
  // Customer-provided IdP — no AuthStack needed
  oidcDiscoveryUrl = externalOidc;
  allowedClients = externalClients;
} else {
  // Default Amazon Cognito (demo/quickstart)
  authStack = new AuthStack(app, "SdpmAuth", {
    env,
    description: "Spec-Driven Presentation Maker - Auth (uksb-ynuz0lkrea)(tag:auth)",
    mcpCallbackUrls: config.auth?.mcpCallbackUrls,
  });
  // In AuthStack mode, downstream stacks read Auth values (oidcDiscoveryUrl,
  // WebClient ID, MCP custom scope, etc.) from SSM Parameter Store published
  // by AuthStack. Keeping these undefined / empty here prevents CDK from
  // emitting auto-generated cross-stack exports that would collide with the
  // retained legacy exports in AuthStack.
  oidcDiscoveryUrl = undefined;
  allowedClients = [];
}

// --- Required stacks ---
// `searchSlides` has been removed — semantic slide search is always enabled.
if (config.features?.searchSlides !== undefined) {
  console.warn(
    "[deprecation] `features.searchSlides` is deprecated and has been removed. " +
    "Semantic slide search is now always enabled. Please remove this option from config.yaml.",
  );
}

// Resolve enableInvocationLogging with backward compatibility for legacy `observability` key.
let enableInvocationLogging = config.features?.enableInvocationLogging === true;
if (config.features?.observability !== undefined) {
  console.warn(
    "[deprecation] `features.observability` is deprecated. " +
    "Use `features.enableInvocationLogging` instead. The legacy key will be removed in a future release.",
  );
  if (config.features?.enableInvocationLogging === undefined) {
    enableInvocationLogging = config.features.observability === true;
  }
}

const data = new DataStack(app, "SdpmData", { env, enableInvocationLogging, description: "Spec-Driven Presentation Maker - Data (uksb-ynuz0lkrea)(tag:data)" });

const runtime = new RuntimeStack(app, "SdpmRuntime", {
  env,
  description: "Spec-Driven Presentation Maker - Runtime (uksb-ynuz0lkrea)(tag:runtime)",
  table: data.table,
  pptxBucket: data.pptxBucket,
  resourceBucket: data.resourceBucket,
  // oidcDiscoveryUrl is used only when useAuthStack=false (external IdP).
  // In AuthStack mode, the value is read from SSM.
  oidcDiscoveryUrl: authStack ? undefined : oidcDiscoveryUrl,
  // allowedClients is used only when useAuthStack=false (external IdP).
  // In AuthStack mode, RuntimeStack reads the MCP custom scope from SSM and
  // uses it as allowedScopes instead. Passing authStack.clientId here would
  // cause CDK to emit an auto-generated cross-stack export which would
  // collide with the legacy exports retained in AuthStack.
  allowedClients: authStack ? [] : allowedClients,
  kbSsmParamName: data.kbSsmParamName || undefined,
  vectorBucketName: data.vectorBucketName || undefined,
  vectorIndexName: data.vectorIndexName || undefined,
  useAuthStack: !!authStack,
  enableDCR: config.auth?.enableDCR !== false,
});
// When AuthStack is present, explicitly declare the dependency so that SSM
// parameters published by AuthStack exist before RuntimeStack reads them.
// This replaces the implicit dependency that CDK used to infer from
// cross-stack construct references.
if (authStack) {
  runtime.addDependency(authStack);
}

// --- Model configuration & validation ---
const defaultChatModelId: string = config.model?.defaults?.chat ?? "global.anthropic.claude-sonnet-4-6";
// Create model falls back to the chat model when `defaults.create` is omitted.
const defaultCreateModelId: string = config.model?.defaults?.create ?? defaultChatModelId;
const allowedModelIds: string[] = config.model?.allowedModelIds ?? [];

if (allowedModelIds.length > 0) {
  if (!allowedModelIds.includes(defaultChatModelId)) {
    throw new Error(
      `Config error: model.defaults.chat "${defaultChatModelId}" is not in model.allowedModelIds. ` +
      `Add it to the list, or remove allowedModelIds.`,
    );
  }
  if (!allowedModelIds.includes(defaultCreateModelId)) {
    throw new Error(
      `Config error: model.defaults.create "${defaultCreateModelId}" is not in model.allowedModelIds. ` +
      `Add it to the list, or remove allowedModelIds.`,
    );
  }
  const seen = new Set<string>();
  for (const id of allowedModelIds) {
    if (seen.has(id)) {
      throw new Error(`Config error: model.allowedModelIds contains duplicate "${id}".`);
    }
    seen.add(id);
    if (!(id in MODEL_METADATA)) {
      throw new Error(
        `Config error: modelId "${id}" is not registered in infra/lib/model-metadata.ts. ` +
        `Add an entry there, or remove "${id}" from model.allowedModelIds. ` +
        `Known IDs: ${Object.keys(MODEL_METADATA).sort().join(", ")}`,
      );
    }
  }
}

const allowedModels = allowedModelIds.map((id) => ({
  modelId: id,
  displayName: MODEL_METADATA[id].displayName,
  description: MODEL_METADATA[id].description,
  composable: MODEL_METADATA[id].composable !== false,
}));

// --- WAF IP restriction (optional) ---
const allowedIpV4AddressRanges: string[] | undefined = config.waf?.allowedIpV4AddressRanges;
const allowedIpV6AddressRanges: string[] | undefined = config.waf?.allowedIpV6AddressRanges;
const wafEnabled = !!(allowedIpV4AddressRanges || allowedIpV6AddressRanges);

// CloudFront WAF must be in us-east-1
const cloudFrontWafStack = wafEnabled
  ? new CloudFrontWafStack(app, "SdpmCloudFrontWaf", {
      env: { account: env.account, region: "us-east-1" },
      crossRegionReferences: true,
      description: "Spec-Driven Presentation Maker - CloudFront WAF (uksb-ynuz0lkrea)(tag:waf)",
      allowedIpV4AddressRanges,
      allowedIpV6AddressRanges,
    })
  : undefined;

if (config.stacks?.agent) {
  const agent = new AgentStack(app, "SdpmAgent", {
    env,
    description: "Spec-Driven Presentation Maker - Agent (uksb-ynuz0lkrea)(tag:agent)",
    table: data.table,
    pptxBucket: data.pptxBucket,
    mcpRuntimeArn: runtime.runtimeArn,
    oidcDiscoveryUrl: authStack ? undefined : oidcDiscoveryUrl,
    allowedClients,
    useAuthStack: !!authStack,
    chatModelId: defaultChatModelId,
    createModelId: defaultCreateModelId,
    allowedModelIds,
  });
  // AgentStack reads the WebClient ID from SSM in AuthStack mode.
  // Ensure AuthStack deploys first.
  if (authStack) {
    agent.addDependency(authStack);
  }

  if (config.stacks?.webUi) {
    if (!authStack) {
      throw new Error("WebUiStack requires AuthStack (default Cognito). Remove auth.oidcDiscoveryUrl from config.yaml to use default Cognito, or deploy Web UI separately.");
    }
    const webUi = new WebUiStack(app, "SdpmWebUi", {
      env,
      crossRegionReferences: wafEnabled,
      description: "Spec-Driven Presentation Maker - Web UI (uksb-ynuz0lkrea)(tag:web-ui)",
      table: data.table,
      pptxBucket: data.pptxBucket,
      resourceBucket: data.resourceBucket,
      agentRuntimeArn: agent.agentRuntimeArn,
      memoryId: agent.memoryId,
      kbId: data.kbSsmParamName,
      vectorBucketName: data.vectorBucketName || undefined,
      vectorIndexName: data.vectorIndexName || undefined,
      webAclId: cloudFrontWafStack?.webAclArn,
      allowedIpV4AddressRanges,
      allowedIpV6AddressRanges,
      defaultChatModelId,
      defaultCreateModelId,
      allowedModels,
    });
    // WebUiStack reads Cognito values from SSM parameters published by
    // AuthStack. Ensure AuthStack deploys first.
    webUi.addDependency(authStack);
  }
}
