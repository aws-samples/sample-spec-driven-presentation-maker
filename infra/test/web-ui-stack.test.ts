// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * WebUiStack's UpdateCognitoCallbackUrls custom resource sets the callback and
 * logout URLs only. AuthStack owns every other WebClient field, including the
 * sdpm-mcp/invoke scope; the handler (infra/lambdas/cognito-callback-urls,
 * tests/test_cognito_callback_urls.py) passes those fields through.
 * Asset bundling skipped.
 */

import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { DataStack } from "../lib/data-stack";
import { WebUiStack } from "../lib/web-ui-stack";

function synthWebUi(): Template {
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } });
  const env = { account: "111122223333", region: "ap-northeast-1" };
  const data = new DataStack(app, "SdpmData", { env, enableInvocationLogging: false, enableTransactionSearch: false });
  const webUi = new WebUiStack(app, "SdpmWebUi", {
    env,
    table: data.table,
    pptxBucket: data.pptxBucket,
    resourceBucket: data.resourceBucket,
    agentRuntimeArn: "arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:runtime/sdpm_agent-test",
    defaultChatModelId: "model-chat",
    defaultCreateModelId: "model-create",
    allowedModels: [],
  });
  return Template.fromStack(webUi);
}

const t = synthWebUi();

test("the callback URL custom resource carries the WebClient's URLs and nothing else", () => {
  const resources = Object.values(t.findResources("Custom::CognitoCallbackUrls"));
  assert.equal(resources.length, 1);
  const props = resources[0].Properties;
  assert.deepEqual(
    Object.keys(props).sort(),
    ["CallbackURLs", "ClientId", "LogoutURLs", "ServiceToken", "UserPoolId"],
  );
  assert.equal(props.CallbackURLs[0], "http://localhost:3000");
  assert.equal(props.CallbackURLs.length, 2);
  assert.deepEqual(props.LogoutURLs, props.CallbackURLs);
});

test("no custom resource calls UpdateUserPoolClient with a fixed payload", () => {
  // An AwsCustomResource sends exactly the parameters it was given, and
  // UpdateUserPoolClient resets the rest (this dropped sdpm-mcp/invoke).
  for (const [id, res] of Object.entries(t.findResources("Custom::AWS"))) {
    const calls = JSON.stringify([res.Properties.Create, res.Properties.Update]);
    assert.doesNotMatch(calls, /updateUserPoolClient/i, id);
  }
});

test("the handler can read and update the WebClient, nothing more", () => {
  const statements = Object.values(t.findResources("AWS::IAM::Policy"))
    .flatMap((p) => p.Properties.PolicyDocument.Statement as Array<{ Action: string | string[] }>)
    .filter((s) => JSON.stringify(s.Action).includes("cognito-idp:"));
  assert.equal(statements.length, 1);
  assert.deepEqual(
    [statements[0].Action].flat().sort(),
    ["cognito-idp:DescribeUserPoolClient", "cognito-idp:UpdateUserPoolClient"],
  );
});
