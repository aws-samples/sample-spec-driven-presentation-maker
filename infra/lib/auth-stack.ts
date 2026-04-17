// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Auth Stack — Default Amazon Cognito User Pool for demo/quickstart.
 *
 * Creates a Amazon Cognito User Pool with Authorization Code + PKCE flow.
 * Customers using their own IdP (Entra ID, Auth0, Okta) skip this stack
 * and set auth.oidcDiscoveryUrl + auth.allowedClients in config.yaml.
 */
// Security: AWS manages infrastructure security. You manage access control,
// data classification, and IAM policies. See SECURITY.md for details.

import * as cdk from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import { Construct } from "constructs";

export interface AuthStackProps extends cdk.StackProps {
  /** Amazon CloudFront site URL for OAuth callback (set after WebUiStack creates it). */
  callbackUrls?: string[];
  /** OAuth callback URLs for external MCP clients (from config.yaml). */
  mcpCallbackUrls?: string[];
}

export class AuthStack extends cdk.Stack {
  /** OIDC discovery URL for Runtime/Agent JWT authorizer. */
  public readonly oidcDiscoveryUrl: string;
  /** App client ID (used as allowedClients for JWT authorizer). */
  public readonly clientId: string;
  /** App client ID for external MCP clients (Claude.ai, Claude Desktop, Kiro). */
  public readonly mcpClientId: string;
  /** Amazon Cognito User Pool (passed to WebUiStack for API GW authorizer). */
  public readonly userPool: cognito.UserPool;
  /** Amazon Cognito User Pool Client. */
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

    // External MCP client (Claude.ai, Claude Desktop, Kiro, etc.)
    // Public client with PKCE — no secret, Authorization Code flow only.
    // Callback URLs configured via config.yaml auth.mcpCallbackUrls.
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

    // --- Outputs ---
    new cdk.CfnOutput(this, "UserPoolId", { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, "UserPoolClientId", { value: this.clientId });
    if (mcpClient) {
      new cdk.CfnOutput(this, "McpClientId", { value: this.mcpClientId });
    }
    new cdk.CfnOutput(this, "OidcDiscoveryUrl", { value: this.oidcDiscoveryUrl });
  }
}
