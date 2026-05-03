// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Auth Stack — Default Amazon Cognito User Pool for demo/quickstart.
 *
 * Creates a Amazon Cognito User Pool with Authorization Code + PKCE flow.
 * Customers using their own IdP (Entra ID, Auth0, Okta) skip this stack
 * and set auth.oidcDiscoveryUrl + auth.allowedClients in config.yaml.
 *
 * Publishes shared values to SSM Parameter Store for downstream stacks to
 * consume without cross-stack CloudFormation exports. See
 * `docs/internal/ssm-cross-stack-refs.md` for rationale.
 */
// Security: AWS manages infrastructure security. You manage access control,
// data classification, and IAM policies. See SECURITY.md for details.

import * as cdk from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

export interface AuthStackProps extends cdk.StackProps {
  /** Amazon CloudFront site URL for OAuth callback (set after WebUiStack creates it). */
  callbackUrls?: string[];
  /** OAuth callback URLs for external MCP clients (from config.yaml). */
  mcpCallbackUrls?: string[];
}

/**
 * SSM Parameter names for cross-stack references.
 * Downstream stacks read these via `ssm.StringParameter.valueForStringParameter`.
 */
export const AUTH_SSM_PARAMS = {
  userPoolId: "/sdpm/auth/user-pool-id",
  userPoolArn: "/sdpm/auth/user-pool-arn",
  webClientId: "/sdpm/auth/web-client-id",
  mcpClientId: "/sdpm/auth/mcp-client-id",
  mcpCustomScope: "/sdpm/auth/mcp-custom-scope",
  cognitoDomainPrefix: "/sdpm/auth/cognito-domain-prefix",
  oidcDiscoveryUrl: "/sdpm/auth/oidc-discovery-url",
} as const;

export class AuthStack extends cdk.Stack {
  /** OIDC discovery URL for Runtime/Agent JWT authorizer. */
  public readonly oidcDiscoveryUrl: string;
  /** App client ID (used as allowedClients for JWT authorizer). */
  public readonly clientId: string;
  /** App client ID for external MCP clients (Claude.ai, Claude Desktop, Kiro). */
  public readonly mcpClientId: string;
  /** Amazon Cognito User Pool — do NOT pass to downstream stacks; use SSM instead. */
  public readonly userPool: cognito.UserPool;
  /** Amazon Cognito User Pool Client — do NOT pass to downstream stacks; use SSM instead. */
  public readonly userPoolClient: cognito.UserPoolClient;
  /** Cognito domain prefix (used for OAuth endpoints in discovery metadata). */
  public readonly cognitoDomainPrefix: string;
  /** Fully-qualified custom OAuth scope for MCP access (e.g. `sdpm-mcp/invoke`). */
  public readonly mcpCustomScope: string;

  constructor(scope: Construct, id: string, props?: AuthStackProps) {
    super(scope, id, props);

    this.userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: "sdpm-users",
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: {
        minLength: 8,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: false,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.cognitoDomainPrefix = `sdpm-auth-${this.account}-${this.region}`;
    this.userPool.addDomain("Domain", {
      cognitoDomain: {
        domainPrefix: this.cognitoDomainPrefix,
      },
    });

    // Resource Server with custom scope for MCP access — isolates MCP auth
    // from WebUI auth. Only McpClient / DCR-registered clients get this scope.
    const mcpScope = new cognito.ResourceServerScope({
      scopeName: "invoke",
      scopeDescription: "Invoke MCP server",
    });
    const mcpResourceServer = this.userPool.addResourceServer("McpResourceServer", {
      identifier: "sdpm-mcp",
      scopes: [mcpScope],
    });
    /** Fully-qualified custom scope name (e.g. `sdpm-mcp/invoke`). */
    this.mcpCustomScope = `sdpm-mcp/${mcpScope.scopeName}`;

    this.userPoolClient = this.userPool.addClient("WebClient", {
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.PROFILE,
          cognito.OAuthScope.EMAIL,
        ],
        callbackUrls: ["http://localhost:3000", ...(props?.callbackUrls ?? [])],
        logoutUrls: ["http://localhost:3000", ...(props?.callbackUrls ?? [])],
      },
      generateSecret: false,
    });

    // External MCP clients — static app client when mcpCallbackUrls configured,
    // otherwise clients register dynamically via DCR.
    const mcpCallbackUrls = props?.mcpCallbackUrls ?? [];
    const mcpClient = mcpCallbackUrls.length > 0
      ? this.userPool.addClient("McpClient", {
          oAuth: {
            flows: { authorizationCodeGrant: true },
            scopes: [
              cognito.OAuthScope.OPENID,
              cognito.OAuthScope.PROFILE,
              cognito.OAuthScope.EMAIL,
              cognito.OAuthScope.resourceServer(mcpResourceServer, mcpScope),
            ],
            callbackUrls: mcpCallbackUrls,
            logoutUrls: mcpCallbackUrls,
          },
          generateSecret: false,
        })
      : undefined;

    const issuer = `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}`;
    this.oidcDiscoveryUrl = `${issuer}/.well-known/openid-configuration`;
    this.clientId = this.userPoolClient.userPoolClientId;
    this.mcpClientId = mcpClient?.userPoolClientId ?? "";

    // --- SSM Parameters for downstream stacks ---
    // Downstream stacks read these via `ssm.StringParameter.valueForStringParameter`
    // instead of receiving construct references via props. This breaks the
    // CloudFormation Export/Import coupling that makes Auth changes fragile.
    // See `docs/internal/ssm-cross-stack-refs.md`.
    new ssm.StringParameter(this, "UserPoolIdParam", {
      parameterName: AUTH_SSM_PARAMS.userPoolId,
      stringValue: this.userPool.userPoolId,
      description: "Cognito UserPool ID (shared with downstream stacks)",
    });
    new ssm.StringParameter(this, "UserPoolArnParam", {
      parameterName: AUTH_SSM_PARAMS.userPoolArn,
      stringValue: this.userPool.userPoolArn,
      description: "Cognito UserPool ARN (shared with downstream stacks)",
    });
    new ssm.StringParameter(this, "WebClientIdParam", {
      parameterName: AUTH_SSM_PARAMS.webClientId,
      stringValue: this.clientId,
      description: "WebUI Cognito app client ID (shared with downstream stacks)",
    });
    new ssm.StringParameter(this, "McpClientIdParam", {
      parameterName: AUTH_SSM_PARAMS.mcpClientId,
      // Empty string is a valid SSM value; downstream treats empty as "no MCP client".
      stringValue: this.mcpClientId === "" ? "-" : this.mcpClientId,
      description: "External MCP Cognito app client ID ('-' means unset)",
    });
    new ssm.StringParameter(this, "McpCustomScopeParam", {
      parameterName: AUTH_SSM_PARAMS.mcpCustomScope,
      stringValue: this.mcpCustomScope,
      description: "Fully-qualified MCP custom OAuth scope (e.g. sdpm-mcp/invoke)",
    });
    new ssm.StringParameter(this, "CognitoDomainPrefixParam", {
      parameterName: AUTH_SSM_PARAMS.cognitoDomainPrefix,
      stringValue: this.cognitoDomainPrefix,
      description: "Cognito hosted UI domain prefix",
    });
    new ssm.StringParameter(this, "OidcDiscoveryUrlParam", {
      parameterName: AUTH_SSM_PARAMS.oidcDiscoveryUrl,
      stringValue: this.oidcDiscoveryUrl,
      description: "OIDC discovery URL for JWT authorizers",
    });

    // --- Outputs ---
    new cdk.CfnOutput(this, "UserPoolId", { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, "UserPoolClientId", { value: this.clientId });
    if (mcpClient) {
      new cdk.CfnOutput(this, "McpClientId", { value: this.mcpClientId });
    }
    new cdk.CfnOutput(this, "OidcDiscoveryUrl", { value: this.oidcDiscoveryUrl });

    // --- Legacy exports retained for backward compatibility ---
    // Older deployments have downstream stacks importing these auto-generated
    // export names. If we simply remove the construct references in downstream
    // stacks (which we do in this PR), CDK stops emitting these exports,
    // and CloudFormation refuses to delete them as long as any deployed
    // template imports them ("Cannot delete export"). We re-declare them here
    // explicitly, using the exact same logical IDs and export names CDK used
    // to auto-generate, so that in-place upgrades succeed from any prior
    // deployed state.
    //
    // Retain indefinitely. Future maintainers: do NOT delete these unless you
    // are certain every deployed environment has re-synthesized without the
    // old imports, which is not guaranteed given the independent deployment
    // model of this sample.
    const userPoolArnExport = new cdk.CfnOutput(this, "LegacyUserPoolArnExport", {
      value: this.userPool.userPoolArn,
      exportName: `${this.stackName}:ExportsOutputFnGetAttUserPool6BA7E5F2Arn686ACC00`,
    });
    userPoolArnExport.overrideLogicalId("ExportsOutputFnGetAttUserPool6BA7E5F2Arn686ACC00");

    const userPoolIdExport = new cdk.CfnOutput(this, "LegacyUserPoolIdExport", {
      value: this.userPool.userPoolId,
      exportName: `${this.stackName}:ExportsOutputRefUserPool6BA7E5F296FD7236`,
    });
    userPoolIdExport.overrideLogicalId("ExportsOutputRefUserPool6BA7E5F296FD7236");

    const webClientIdExport = new cdk.CfnOutput(this, "LegacyWebClientIdExport", {
      value: this.userPoolClient.userPoolClientId,
      exportName: `${this.stackName}:ExportsOutputRefUserPoolWebClient4C9370B02E2C9FF9`,
    });
    webClientIdExport.overrideLogicalId("ExportsOutputRefUserPoolWebClient4C9370B02E2C9FF9");
  }
}
