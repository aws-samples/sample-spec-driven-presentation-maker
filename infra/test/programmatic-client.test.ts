// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * auth.programmaticClient: off by default (no client, authorizers as before); on,
 * AuthStack creates the native-app client and the Agent runtime authorizer and the
 * REST API JWT authorizer accept its ID. Stacks wired as bin/infra.ts does in
 * AuthStack mode, with asset bundling skipped.
 */

import { describe, test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import {
  AuthStack,
  normalizeProgrammaticClient,
  ProgrammaticClientSettings,
} from "../lib/auth-stack";
import { AgentStack } from "../lib/agent-stack";
import { DataStack } from "../lib/data-stack";
import { WebUiStack } from "../lib/web-ui-stack";

const ENV = { account: "111122223333", region: "ap-northeast-1" };
const MODEL = "global.anthropic.claude-sonnet-4-6";
const WEB_CLIENT_ID = "UserPoolWebClient4C9370B0"; // pragma: allowlist secret
const WEB_CLIENT_PARAM = "/sdpm/auth/web-client-id";
const PROGRAMMATIC_PARAM = "/sdpm/auth/programmatic-client-id";

function synthAuth(programmaticClient?: ProgrammaticClientSettings): Template {
  return Template.fromStack(new AuthStack(new cdk.App(), "SdpmAuth", { programmaticClient }));
}

function synthDownstream(programmaticClient: boolean): { agent: Template; webUi: Template } {
  const app = new cdk.App({ context: { "aws:cdk:bundling-stacks": [] } });
  const data = new DataStack(app, "SdpmData", { env: ENV, enableInvocationLogging: false, enableTransactionSearch: false });
  const agent = new AgentStack(app, "SdpmAgent", {
    env: ENV,
    mcpRuntimeArn: "arn:aws:bedrock-agentcore:ap-northeast-1:111122223333:runtime/sdpm-test",
    allowedClients: [],
    useAuthStack: true,
    programmaticClient,
    chatModelId: MODEL,
    createModelId: MODEL,
    allowedModelIds: [MODEL],
  });
  const webUi = new WebUiStack(app, "SdpmWebUi", {
    env: ENV,
    table: data.table,
    pptxBucket: data.pptxBucket,
    resourceBucket: data.resourceBucket,
    agentRuntimeArn: agent.agentRuntimeArn,
    programmaticClient,
    defaultChatModelId: MODEL,
    defaultCreateModelId: MODEL,
    allowedModels: [],
  });
  return { agent: Template.fromStack(agent), webUi: Template.fromStack(webUi) };
}

/** SSM parameter names behind a list of `{Ref: <template parameter>}` values. */
function ssmNames(t: Template, refs: Array<{ Ref: string }>): string[] {
  const params = t.toJSON().Parameters;
  return refs.map((r) => params[r.Ref].Default);
}

function agentAllowedClients(t: Template): string[] {
  const [runtime] = Object.values(t.findResources("AWS::BedrockAgentCore::Runtime"));
  return ssmNames(t, runtime.Properties.AuthorizerConfiguration.CustomJWTAuthorizer.AllowedClients);
}

function apiAudience(t: Template): string[] {
  const authorizers = Object.values(t.findResources("AWS::ApiGatewayV2::Authorizer"));
  assert.equal(authorizers.length, 1);
  return ssmNames(t, authorizers[0].Properties.JwtConfiguration.Audience);
}

function webClientUrlsHash(t: Template): string {
  const [res] = Object.values(t.findResources("Custom::WebClientUrls"));
  return res.Properties.ClientConfigHash;
}

describe("auth.programmaticClient config", () => {
  test("absent or not enabled means no client", () => {
    for (const raw of [undefined, null, {}, { enabled: false }, { enabled: false, refreshTokenValidityDays: 7 }]) {
      assert.equal(normalizeProgrammaticClient(raw, true), undefined, JSON.stringify(raw));
    }
  });

  test("enabled defaults the refresh-token validity to 90 days", () => {
    assert.deepEqual(normalizeProgrammaticClient({ enabled: true }, true), { refreshTokenValidityDays: 90 });
    assert.deepEqual(
      normalizeProgrammaticClient({ enabled: true, refreshTokenValidityDays: 30 }, true),
      { refreshTokenValidityDays: 30 },
    );
  });

  test("malformed blocks are config errors", () => {
    assert.throws(() => normalizeProgrammaticClient(true, true), /must be a mapping/);
    assert.throws(() => normalizeProgrammaticClient(["x"], true), /must be a mapping/);
    assert.throws(() => normalizeProgrammaticClient({ enabled: "yes" }, true), /enabled must be true or false/);
    for (const days of [0, 3651, 1.5, "90", -1]) {
      assert.throws(
        () => normalizeProgrammaticClient({ enabled: true, refreshTokenValidityDays: days }, true),
        /refreshTokenValidityDays must be a whole number of days from 1 to 3650/,
        String(days),
      );
    }
  });

  test("enabled with an external IdP fails with a clear message; disabled is ignored", () => {
    assert.throws(
      () => normalizeProgrammaticClient({ enabled: true }, false),
      /auth\.programmaticClient needs the default Cognito user pool.*auth\.oidcDiscoveryUrl/,
    );
    assert.equal(normalizeProgrammaticClient({ enabled: false }, false), undefined);
  });
});

describe("AuthStack programmatic client", () => {
  test("off: only the WebClient, no parameter, no output", () => {
    const t = synthAuth();
    assert.deepEqual(Object.keys(t.findResources("AWS::Cognito::UserPoolClient")), [WEB_CLIENT_ID]);
    const names = Object.values(t.findResources("AWS::SSM::Parameter")).map((p) => p.Properties.Name);
    assert.ok(!names.includes(PROGRAMMATIC_PARAM));
    assert.equal(t.toJSON().Outputs.ProgrammaticClientId, undefined);
  });

  test("on: a public code + PKCE client on the loopback callback with the MCP scope", () => {
    const t = synthAuth({ refreshTokenValidityDays: 90 });
    const clients = Object.entries(t.findResources("AWS::Cognito::UserPoolClient"))
      .filter(([id]) => id !== WEB_CLIENT_ID);
    assert.equal(clients.length, 1);
    const [clientId, client] = clients[0];
    assert.match(clientId, /^UserPoolProgrammaticClient/);
    const p = client.Properties;
    assert.equal(p.GenerateSecret, false);
    assert.deepEqual(p.AllowedOAuthFlows, ["code"]);
    assert.equal(p.AllowedOAuthFlowsUserPoolClient, true);
    assert.deepEqual(p.SupportedIdentityProviders, ["COGNITO"]);
    assert.deepEqual(p.CallbackURLs, ["http://127.0.0.1:8765"]);
    assert.deepEqual(p.LogoutURLs, ["http://127.0.0.1:8765"]);
    const [openid, profile, email, mcp, ...rest] = p.AllowedOAuthScopes;
    assert.deepEqual([openid, profile, email, rest], ["openid", "profile", "email", []]);
    const [, [resourceServer, scopeName]] = mcp["Fn::Join"];
    assert.match(resourceServer.Ref, /^UserPoolMcpResourceServer/);
    assert.equal(scopeName, "/invoke");
    // 90 days, rotation off, no plain-password API sign-in.
    assert.equal(p.RefreshTokenValidity, 90 * 24 * 60);
    assert.equal(p.TokenValidityUnits.RefreshToken, "minutes");
    assert.equal(p.RefreshTokenRotation, undefined);
    assert.deepEqual([...p.ExplicitAuthFlows].sort(), ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]);
    // Published for AgentStack / WebUiStack and as an output for the client's settings.
    t.hasResourceProperties("AWS::SSM::Parameter", { Name: PROGRAMMATIC_PARAM, Value: { Ref: clientId } });
    assert.deepEqual(t.toJSON().Outputs.ProgrammaticClientId.Value, { Ref: clientId });
  });

  test("the refresh-token validity follows the config", () => {
    const t = synthAuth({ refreshTokenValidityDays: 30 });
    const [, client] = Object.entries(t.findResources("AWS::Cognito::UserPoolClient"))
      .find(([id]) => id !== WEB_CLIENT_ID)!;
    assert.equal(client.Properties.RefreshTokenValidity, 30 * 24 * 60);
  });

  test("turning it on leaves the WebClient as it is", () => {
    const off = synthAuth();
    const on = synthAuth({ refreshTokenValidityDays: 90 });
    assert.deepEqual(
      on.findResources("AWS::Cognito::UserPoolClient")[WEB_CLIENT_ID],
      off.findResources("AWS::Cognito::UserPoolClient")[WEB_CLIENT_ID],
    );
    assert.equal(webClientUrlsHash(on), webClientUrlsHash(off));
  });
});

describe("authorizers", () => {
  test("off: the Agent runtime and the REST API accept the WebClient only", () => {
    const { agent, webUi } = synthDownstream(false);
    assert.deepEqual(agentAllowedClients(agent), [WEB_CLIENT_PARAM]);
    assert.deepEqual(apiAudience(webUi), [WEB_CLIENT_PARAM]);
  });

  test("on: both also accept the programmatic client", () => {
    const { agent, webUi } = synthDownstream(true);
    assert.deepEqual(agentAllowedClients(agent), [WEB_CLIENT_PARAM, PROGRAMMATIC_PARAM]);
    assert.deepEqual(apiAudience(webUi), [WEB_CLIENT_PARAM, PROGRAMMATIC_PARAM]);
  });
});
