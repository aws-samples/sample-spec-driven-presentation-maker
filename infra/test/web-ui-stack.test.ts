// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AuthStack owns the WebClient, including its callback/logout URLs. WebUiStack
 * publishes its CloudFront site URL in SSM and calls AuthStack's WebClientUrls
 * function (infra/lambdas/cognito-callback-urls,
 * tests/test_cognito_callback_urls.py) when the URL is created or changes.
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

test("the site URL is published for AuthStack and AuthStack's function is called with it", () => {
  // The CloudFront URL reaches the WebClient only through AuthStack's
  // WebClientUrls function (service token from SSM), which reads this parameter.
  const params = Object.values(t.findResources("AWS::SSM::Parameter"))
    .filter((p) => p.Properties.Name === "/sdpm/web-ui/site-url");
  assert.equal(params.length, 1);
  const [scheme, domain] = params[0].Properties.Value["Fn::Join"][1];
  assert.equal(scheme, "https://");
  assert.match(domain["Fn::GetAtt"][0], /^Distribution/);
  assert.equal(domain["Fn::GetAtt"][1], "DomainName");

  const resources = Object.entries(t.findResources("Custom::WebClientUrls"));
  assert.equal(resources.length, 1);
  const [, res] = resources[0];
  assert.deepEqual(Object.keys(res.Properties).sort(), ["ServiceToken", "SiteUrl"]);
  assert.deepEqual(res.Properties.SiteUrl, params[0].Properties.Value);
  const tokenParam = res.Properties.ServiceToken.Ref;
  assert.equal(t.toJSON().Parameters[tokenParam].Default, "/sdpm/auth/web-client-urls-fn-arn");
  // Runs after the parameter holds the new URL.
  const [paramId] = Object.entries(t.findResources("AWS::SSM::Parameter"))
    .find(([, p]) => p.Properties.Name === "/sdpm/web-ui/site-url")!;
  assert.ok([res.DependsOn].flat().includes(paramId));
});

test("no other writer of the WebClient URLs is left in this stack", () => {
  assert.deepEqual(t.findResources("Custom::CognitoCallbackUrls"), {});
});

test("no custom resource calls UpdateUserPoolClient with a fixed payload", () => {
  // An AwsCustomResource sends exactly the parameters it was given, and
  // UpdateUserPoolClient resets the rest (this dropped sdpm-mcp/invoke).
  for (const [id, res] of Object.entries(t.findResources("Custom::AWS"))) {
    const calls = JSON.stringify([res.Properties.Create, res.Properties.Update]);
    assert.doesNotMatch(calls, /updateUserPoolClient/i, id);
  }
});

test("this stack cannot change the WebClient", () => {
  const actions = Object.values(t.findResources("AWS::IAM::Policy"))
    .flatMap((p) => p.Properties.PolicyDocument.Statement as Array<{ Action: string | string[] }>)
    .flatMap((s) => [s.Action].flat());
  assert.ok(!actions.some((a) => /^cognito-idp:(UpdateUserPoolClient|\*)$/.test(a)), JSON.stringify(actions));
});
