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
}

export class AuthStack extends cdk.Stack {
  /** OIDC discovery URL for Runtime/Agent JWT authorizer. */
  public readonly oidcDiscoveryUrl: string;
  /** App client ID (used as allowedClients for JWT authorizer). */
  public readonly clientId: string;
  /** Amazon Cognito User Pool (passed to WebUiStack for API GW authorizer). */
  public readonly userPool: cognito.UserPool;
  /** Amazon Cognito User Pool Client. */
  public readonly userPoolClient: cognito.UserPoolClient;

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

    this.userPool.addDomain("Domain", {
      cognitoDomain: {
        domainPrefix: `sdpm-auth-${this.account}-${this.region}`,
      },
    });

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

    const issuer = `https://cognito-idp.${this.region}.amazonaws.com/${this.userPool.userPoolId}`;
    this.oidcDiscoveryUrl = `${issuer}/.well-known/openid-configuration`;
    this.clientId = this.userPoolClient.userPoolClientId;

    // --- Outputs ---
    new cdk.CfnOutput(this, "UserPoolId", { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, "UserPoolClientId", { value: this.clientId });
    new cdk.CfnOutput(this, "OidcDiscoveryUrl", { value: this.oidcDiscoveryUrl });
  }
}
