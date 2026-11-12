// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AuthStack sign-up settings (self sign-up default, the config switch, the Pre
 * sign-up trigger for auth.allowedEmailDomains) and the WebClient, including who
 * sets its callback/logout URLs.
 */

import { describe, test } from "node:test";
import * as assert from "node:assert/strict";
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { AuthStack, AuthStackProps } from "../lib/auth-stack";

function synth(props: AuthStackProps = {}): Template {
  const app = new cdk.App();
  return Template.fromStack(new AuthStack(app, "SdpmAuth", props));
}

/** Lambda functions other than WebClientUrlsFn, which every mode has. */
function preSignUpFunctionCount(t: Template): number {
  return Object.keys(t.findResources("AWS::Lambda::Function"))
    .filter((id) => !id.startsWith("WebClientUrlsFn")).length;
}

// Logical IDs of the deployed user pool and web client. A change here would make
// CloudFormation replace them (and delete every user).
const USER_POOL_ID = "UserPool6BA7E5F2"; // pragma: allowlist secret
const WEB_CLIENT_ID = "UserPoolWebClient4C9370B0"; // pragma: allowlist secret

describe("AuthStack sign-up", () => {
  test("self sign-up is off by default and no trigger is attached", () => {
    const t = synth();
    t.hasResourceProperties("AWS::Cognito::UserPool", {
      AdminCreateUserConfig: { AllowAdminCreateUserOnly: true },
      LambdaConfig: Match.absent(),
    });
    assert.equal(preSignUpFunctionCount(t), 0);
  });

  test("selfSignUp: true turns self sign-up on without a trigger", () => {
    const t = synth({ selfSignUp: true });
    t.hasResourceProperties("AWS::Cognito::UserPool", {
      AdminCreateUserConfig: { AllowAdminCreateUserOnly: false },
      LambdaConfig: Match.absent(),
    });
    assert.equal(preSignUpFunctionCount(t), 0);
  });

  test("allowedEmailDomains attaches the Pre sign-up trigger with the normalized domains", () => {
    const t = synth({ selfSignUp: true, allowedEmailDomains: ["Example.com", " example.org "] });
    t.hasResourceProperties("AWS::Cognito::UserPool", {
      AdminCreateUserConfig: { AllowAdminCreateUserOnly: false },
      LambdaConfig: { PreSignUp: { "Fn::GetAtt": [Match.stringLikeRegexp("^PreSignUpFn"), "Arn"] } },
    });
    assert.equal(preSignUpFunctionCount(t), 1);
    t.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "index.handler",
      Environment: { Variables: { ALLOWED_EMAIL_DOMAINS: "example.com,example.org" } },
    });
    t.hasResourceProperties("AWS::Lambda::Permission", {
      Action: "lambda:InvokeFunction",
      Principal: "cognito-idp.amazonaws.com",
    });
  });

  test("an empty allowedEmailDomains list attaches no trigger", () => {
    const t = synth({ selfSignUp: true, allowedEmailDomains: [] });
    assert.equal(preSignUpFunctionCount(t), 0);
  });

  test("the user pool and web client keep their logical IDs in every mode", () => {
    for (const props of [{}, { selfSignUp: true }, { selfSignUp: true, allowedEmailDomains: ["example.com"] }]) {
      const t = synth(props);
      assert.ok(t.findResources("AWS::Cognito::UserPool")[USER_POOL_ID], `UserPool id with ${JSON.stringify(props)}`);
      assert.ok(t.findResources("AWS::Cognito::UserPoolClient")[WEB_CLIENT_ID], `WebClient id with ${JSON.stringify(props)}`);
    }
  });

  test("allowedEmailDomains without selfSignUp is a config error", () => {
    assert.throws(() => synth({ allowedEmailDomains: ["example.com"] }), /auth\.selfSignUp: true/);
  });

  test("entries that are not domain names are config errors", () => {
    for (const bad of ["user@example.com", "*.example.com", "example", ".example.com", "exa mple.com", ""]) {
      assert.throws(() => synth({ selfSignUp: true, allowedEmailDomains: [bad] }), /not a domain name/, bad);
    }
  });

  test("duplicate domains (ignoring case) are a config error", () => {
    assert.throws(
      () => synth({ selfSignUp: true, allowedEmailDomains: ["example.com", "EXAMPLE.com"] }),
      /duplicate "example.com"/,
    );
  });
});

describe("AuthStack WebClient", () => {
  test("declares every OAuth setting the Web UI needs, including the MCP custom scope", () => {
    const client = synth().findResources("AWS::Cognito::UserPoolClient")[WEB_CLIENT_ID].Properties;
    // Authorization code flow (the Web UI adds PKCE; the client has no secret).
    assert.deepEqual(client.AllowedOAuthFlows, ["code"]);
    assert.equal(client.AllowedOAuthFlowsUserPoolClient, true);
    assert.equal(client.GenerateSecret, false);
    assert.deepEqual(client.SupportedIdentityProviders, ["COGNITO"]);
    // sdpm-mcp/invoke: the MCP runtime's JWT authorizer rejects tokens without it.
    const [openid, profile, email, mcp, ...rest] = client.AllowedOAuthScopes;
    assert.deepEqual([openid, profile, email, rest], ["openid", "profile", "email", []]);
    const [, [resourceServer, scopeName]] = mcp["Fn::Join"];
    assert.match(resourceServer.Ref, /^UserPoolMcpResourceServer/);
    assert.equal(scopeName, "/invoke");
    // The explicit auth flows WebUiStack's custom resource used to set.
    assert.deepEqual(
      [...client.ExplicitAuthFlows].sort(),
      ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_PASSWORD_AUTH", "ALLOW_USER_SRP_AUTH"],
    );
  });

  test("the published MCP custom scope names the scope the WebClient carries", () => {
    const t = synth();
    t.hasResourceProperties("AWS::Cognito::UserPoolResourceServer", {
      Identifier: "sdpm-mcp",
      Scopes: [{ ScopeName: "invoke", ScopeDescription: Match.anyValue() }],
    });
    t.hasResourceProperties("AWS::SSM::Parameter", {
      Name: "/sdpm/auth/mcp-custom-scope",
      Value: "sdpm-mcp/invoke",
    });
  });

  test("the template's callback/logout URLs are exactly the dev URL", () => {
    const client = synth().findResources("AWS::Cognito::UserPoolClient")[WEB_CLIENT_ID].Properties;
    assert.deepEqual(client.CallbackURLs, ["http://localhost:3000"]);
    assert.deepEqual(client.LogoutURLs, ["http://localhost:3000"]);
  });

  test("WebClientUrlsFn adds only the Web UI site URL that WebUiStack publishes", () => {
    const t = synth();
    const fns = Object.entries(t.findResources("AWS::Lambda::Function"))
      .filter(([id]) => id.startsWith("WebClientUrlsFn"));
    assert.equal(fns.length, 1);
    const [fnId, fn] = fns[0];
    const env = fn.Properties.Environment.Variables;
    assert.equal(env.DEV_URL, "http://localhost:3000");
    assert.equal(env.SITE_URL_PARAM, "/sdpm/web-ui/site-url");
    assert.deepEqual(env.CLIENT_ID, { Ref: WEB_CLIENT_ID });
    assert.deepEqual(env.USER_POOL_ID, { Ref: USER_POOL_ID });
    // Its ARN is the service token WebUiStack's custom resource uses.
    t.hasResourceProperties("AWS::SSM::Parameter", {
      Name: "/sdpm/auth/web-client-urls-fn-arn",
      Value: { "Fn::GetAtt": [fnId, "Arn"] },
    });
  });

  test("WebClientUrlsFn can read the site URL parameter and update the WebClient, nothing more", () => {
    const t = synth();
    const roleRef = Object.entries(t.findResources("AWS::Lambda::Function"))
      .find(([id]) => id.startsWith("WebClientUrlsFn"))![1].Properties.Role["Fn::GetAtt"][0];
    const statements = Object.values(t.findResources("AWS::IAM::Policy"))
      .filter((p) => p.Properties.Roles.some((r: { Ref: string }) => r.Ref === roleRef))
      .flatMap((p) => p.Properties.PolicyDocument.Statement);
    assert.equal(statements.length, 2);
    const [cognitoStmt, ssmStmt] = statements;
    assert.deepEqual(
      [cognitoStmt.Action].flat().sort(),
      ["cognito-idp:DescribeUserPoolClient", "cognito-idp:UpdateUserPoolClient"],
    );
    assert.deepEqual(cognitoStmt.Resource, { "Fn::GetAtt": [USER_POOL_ID, "Arn"] });
    assert.equal(ssmStmt.Action, "ssm:GetParameter");
    assert.match(JSON.stringify(ssmStmt.Resource), /:parameter\/sdpm\/web-ui\/site-url"/);
  });

  test("WebClientUrls runs after the client and again whenever the client's template changes", () => {
    const hashOf = (stack: AuthStack): string => {
      const t = Template.fromStack(stack);
      const resources = Object.entries(t.findResources("Custom::WebClientUrls"));
      assert.equal(resources.length, 1);
      const [, res] = resources[0];
      assert.ok([res.DependsOn].flat().includes(WEB_CLIENT_ID));
      assert.deepEqual(Object.keys(res.Properties).sort(), ["ClientConfigHash", "ServiceToken"]);
      return res.Properties.ClientConfigHash;
    };
    const stack = (): AuthStack => new AuthStack(new cdk.App(), "SdpmAuth");
    const base = hashOf(stack());
    assert.match(base, /^[0-9a-f]{64}$/);
    // Same template, same hash: a deploy that leaves the client alone runs nothing.
    assert.equal(hashOf(stack()), base);
    // Any change to the client, made at any point before synth, changes the hash,
    // so CloudFormation calls the function after it rewrites the client.
    const changed = stack();
    (changed.userPoolClient.node.defaultChild as cdk.CfnResource)
      .addPropertyOverride("AccessTokenValidity", 30);
    assert.notEqual(hashOf(changed), base);
  });
});
