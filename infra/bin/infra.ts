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

let oidcDiscoveryUrl: string;
let allowedClients: string[];
let authStack: AuthStack | undefined;

if (externalOidc && externalClients) {
  // Customer-provided IdP — no AuthStack needed
  oidcDiscoveryUrl = externalOidc;
  allowedClients = externalClients;
} else {
  // Default Amazon Cognito (demo/quickstart)
  authStack = new AuthStack(app, "SdpmAuth", { env });
  oidcDiscoveryUrl = authStack.oidcDiscoveryUrl;
  allowedClients = [authStack.clientId];
}

// --- Required stacks ---
const searchSlides = config.features?.searchSlides === true;
const observability = config.features?.observability === true;
const data = new DataStack(app, "SdpmData", { env, searchSlides, observability });

const runtime = new RuntimeStack(app, "SdpmRuntime", {
  env,
  table: data.table,
  pptxBucket: data.pptxBucket,
  resourceBucket: data.resourceBucket,
  oidcDiscoveryUrl,
  allowedClients,
  kbSsmParamName: data.kbSsmParamName || undefined,
  vectorBucketName: data.vectorBucketName || undefined,
  vectorIndexName: data.vectorIndexName || undefined,
});

if (config.stacks?.agent) {
  const agent = new AgentStack(app, "SdpmAgent", {
    env,
    table: data.table,
    pptxBucket: data.pptxBucket,
    mcpRuntimeArn: runtime.runtimeArn,
    oidcDiscoveryUrl,
    allowedClients,
    modelId: config.model?.modelId,
  });

  if (config.stacks?.webUi) {
    if (!authStack) {
      throw new Error("WebUiStack requires AuthStack (default Cognito). Remove auth.oidcDiscoveryUrl from config.yaml to use default Cognito, or deploy Web UI separately.");
    }
    new WebUiStack(app, "SdpmWebUi", {
      env,
      table: data.table,
      pptxBucket: data.pptxBucket,
      resourceBucket: data.resourceBucket,
      agentRuntimeArn: agent.agentRuntimeArn,
      userPool: authStack.userPool,
      userPoolClient: authStack.userPoolClient,
      memoryId: agent.memoryId,
      kbId: searchSlides ? data.kbSsmParamName : undefined,
      vectorBucketName: data.vectorBucketName || undefined,
      vectorIndexName: data.vectorIndexName || undefined,
    });
  }
}
