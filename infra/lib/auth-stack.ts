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
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { createHash } from "crypto";
import * as path from "path";
import { Construct } from "constructs";

export interface AuthStackProps extends cdk.StackProps {
  /** OAuth callback URLs for external MCP clients (from config.yaml). */
  mcpCallbackUrls?: string[];
  /**
   * Let people create their own account from the sign-in page (`auth.selfSignUp`).
   * Default false: an administrator creates the users.
   */
  selfSignUp?: boolean;
  /**
   * Email domains allowed to self sign up (`auth.allowedEmailDomains`). Requires
   * `selfSignUp: true`. Enforced by a Cognito Pre sign-up Lambda trigger: exact,
   * case-insensitive match; subdomains are not included.
   */
  allowedEmailDomains?: string[];
  /**
   * The programmatic client (`auth.programmaticClient`), or undefined for none.
   * See `normalizeProgrammaticClient`.
   */
  programmaticClient?: ProgrammaticClientSettings;
}

/** Settings of the programmatic client, validated by `normalizeProgrammaticClient`. */
export interface ProgrammaticClientSettings {
  /** How long a refresh token stays valid, in days. */
  refreshTokenValidityDays: number;
}

/**
 * The programmatic client's only callback and logout URL. The reference client
 * (examples/programmatic-client) listens here on loopback for the one redirect of
 * its sign-in. Cognito matches the URL exactly, port included.
 */
export const PROGRAMMATIC_CLIENT_CALLBACK_URL = "http://127.0.0.1:8765";

/** Default refresh-token validity of the programmatic client. */
export const PROGRAMMATIC_CLIENT_DEFAULT_REFRESH_DAYS = 90;

/**
 * Validate `auth.programmaticClient` and return its settings, or undefined when
 * the block is absent or `enabled` is not true. Throws a config error for a
 * malformed block, for a refresh-token validity outside Cognito's 1–3650 days,
 * and for an enabled block with an external IdP (`useAuthStack: false`), which
 * has no Cognito user pool to hold the client.
 */
export function normalizeProgrammaticClient(
  raw: unknown,
  useAuthStack: boolean,
): ProgrammaticClientSettings | undefined {
  if (raw === undefined || raw === null) return undefined;
  if (typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("Config error: auth.programmaticClient must be a mapping (enabled, refreshTokenValidityDays).");
  }
  const block = raw as { enabled?: unknown; refreshTokenValidityDays?: unknown };
  const enabled = block.enabled ?? false;
  if (typeof enabled !== "boolean") {
    throw new Error("Config error: auth.programmaticClient.enabled must be true or false.");
  }
  if (!enabled) return undefined;
  if (!useAuthStack) {
    throw new Error(
      "Config error: auth.programmaticClient needs the default Cognito user pool and does not work with " +
      "auth.oidcDiscoveryUrl (external IdP). Remove auth.programmaticClient, or remove auth.oidcDiscoveryUrl " +
      "to use the default Cognito user pool.",
    );
  }
  const days = block.refreshTokenValidityDays ?? PROGRAMMATIC_CLIENT_DEFAULT_REFRESH_DAYS;
  if (typeof days !== "number" || !Number.isInteger(days) || days < 1 || days > 3650) {
    throw new Error(
      "Config error: auth.programmaticClient.refreshTokenValidityDays must be a whole number of days from 1 to 3650.",
    );
  }
  return { refreshTokenValidityDays: days };
}

/** One DNS name: labels of letters, digits and inner hyphens, at least two labels. */
const EMAIL_DOMAIN_RE = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

/**
 * Validate `auth.allowedEmailDomains` and return the domains in lower case.
 * Throws a config error for entries that are not plain domain names (no `@`,
 * no wildcard) and for duplicates.
 */
export function normalizeAllowedEmailDomains(domains: string[]): string[] {
  const seen = new Set<string>();
  for (const entry of domains) {
    const domain = entry.trim().toLowerCase();
    if (!EMAIL_DOMAIN_RE.test(domain)) {
      throw new Error(
        `Config error: auth.allowedEmailDomains entry "${entry}" is not a domain name. ` +
        `Use the part after "@" (for example "example.com"), without wildcards.`,
      );
    }
    if (seen.has(domain)) {
      throw new Error(`Config error: auth.allowedEmailDomains contains duplicate "${domain}".`);
    }
    seen.add(domain);
  }
  return [...seen];
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
  /** ARN of the function that sets the WebClient's callback/logout URLs. */
  webClientUrlsFnArn: "/sdpm/auth/web-client-urls-fn-arn",
  /** Programmatic client ID; published only while auth.programmaticClient is enabled. */
  programmaticClientId: "/sdpm/auth/programmatic-client-id",
} as const;

/**
 * SSM parameter where WebUiStack publishes its CloudFront site URL. AuthStack's
 * WebClientUrls function reads it at run time, so AuthStack needs no reference
 * to WebUiStack (which would be a circular dependency).
 */
export const WEB_UI_SITE_URL_PARAM = "/sdpm/web-ui/site-url";

/** The Web UI dev server (`npm run dev`); always an allowed callback/logout URL. */
export const WEB_UI_DEV_URL = "http://localhost:3000";

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

    const selfSignUp = props?.selfSignUp === true;
    const allowedEmailDomains = normalizeAllowedEmailDomains(props?.allowedEmailDomains ?? []);
    if (allowedEmailDomains.length > 0 && !selfSignUp) {
      throw new Error(
        "Config error: auth.allowedEmailDomains applies to self sign-up only. " +
        "Set auth.selfSignUp: true, or remove auth.allowedEmailDomains.",
      );
    }

    // Changing selfSignUpEnabled or the Lambda triggers updates the user pool in
    // place (AdminCreateUserConfig / LambdaConfig); existing users are kept.
    this.userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: "sdpm-users",
      selfSignUpEnabled: selfSignUp,
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

    // Email domain check for self sign-up. It runs inside Cognito, so it applies
    // to every sign-up request, whichever client sends it.
    if (allowedEmailDomains.length > 0) {
      const preSignUpFn = new lambda.Function(this, "PreSignUpFn", {
        runtime: lambda.Runtime.PYTHON_3_13,
        handler: "index.handler",
        code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "pre-signup")),
        environment: {
          ALLOWED_EMAIL_DOMAINS: allowedEmailDomains.join(","),
        },
        // Cognito waits at most 5 seconds for a trigger.
        timeout: cdk.Duration.seconds(5),
        memorySize: 128,
        description: "Cognito Pre sign-up: allow self sign-up only from auth.allowedEmailDomains",
        logGroup: new logs.LogGroup(this, "PreSignUpFnLogs", {
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      });
      this.userPool.addTrigger(cognito.UserPoolOperation.PRE_SIGN_UP, preSignUpFn);
    }

    this.cognitoDomainPrefix = `sdpm-auth-${this.account}-${this.region}`;
    this.userPool.addDomain("Domain", {
      cognitoDomain: {
        domainPrefix: this.cognitoDomainPrefix,
      },
    });

    // Resource Server with custom scope for MCP access. Only clients that call
    // the MCP runtime get this scope: WebClient (the agent forwards the Web UI
    // user's token), McpClient and DCR-registered clients.
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

    // This stack owns every WebClient setting, including the callback/logout
    // URLs: exactly WEB_UI_DEV_URL and the CloudFront site URL. The template can
    // only hold WEB_UI_DEV_URL (the CloudFront URL is created later by WebUiStack,
    // which depends on this stack), so the WebClientUrls function below adds the
    // site URL that WebUiStack publishes in SSM.
    // The MCP runtime's JWT authorizer requires sdpm-mcp/invoke on the token the
    // agent forwards, so the scope is declared here, next to its resource server.
    // authFlows keeps the explicit auth flows the custom resource used to set.
    // Changing scopes or auth flows updates the client in place (same client ID).
    this.userPoolClient = this.userPool.addClient("WebClient", {
      authFlows: { userPassword: true, userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.PROFILE,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.resourceServer(mcpResourceServer, mcpScope),
        ],
        callbackUrls: [WEB_UI_DEV_URL],
        logoutUrls: [WEB_UI_DEV_URL],
      },
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
      generateSecret: false,
    });
    this.addWebClientUrls(this.userPoolClient);

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

    // Programmatic client (auth.programmaticClient): an OAuth native-app client
    // (RFC 8252) for the user's own automation. Public (no secret), code flow with
    // PKCE, one loopback callback. Its refresh token stands in for the user in
    // unattended runs, so its lifetime is its own setting; rotation stays off.
    // The Agent runtime and the REST API accept its ID (AgentStack, WebUiStack);
    // the MCP runtime checks the sdpm-mcp/invoke scope only.
    // SRP stays allowed for the sign-in pages; plain-password API sign-in does not.
    const programmatic = props?.programmaticClient;
    const programmaticClient = programmatic
      ? this.userPool.addClient("ProgrammaticClient", {
          authFlows: { userSrp: true },
          oAuth: {
            flows: { authorizationCodeGrant: true },
            scopes: [
              cognito.OAuthScope.OPENID,
              cognito.OAuthScope.PROFILE,
              cognito.OAuthScope.EMAIL,
              cognito.OAuthScope.resourceServer(mcpResourceServer, mcpScope),
            ],
            callbackUrls: [PROGRAMMATIC_CLIENT_CALLBACK_URL],
            logoutUrls: [PROGRAMMATIC_CLIENT_CALLBACK_URL],
          },
          supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
          generateSecret: false,
          refreshTokenValidity: cdk.Duration.days(programmatic.refreshTokenValidityDays),
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
    if (programmaticClient) {
      new ssm.StringParameter(this, "ProgrammaticClientIdParam", {
        parameterName: AUTH_SSM_PARAMS.programmaticClientId,
        stringValue: programmaticClient.userPoolClientId,
        description: "Programmatic Cognito app client ID (auth.programmaticClient)",
      });
    }

    // --- Outputs ---
    new cdk.CfnOutput(this, "UserPoolId", { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, "UserPoolClientId", { value: this.clientId });
    if (mcpClient) {
      new cdk.CfnOutput(this, "McpClientId", { value: this.mcpClientId });
    }
    if (programmaticClient) {
      new cdk.CfnOutput(this, "ProgrammaticClientId", { value: programmaticClient.userPoolClientId });
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
    // The long hex hashes in the export names below (e.g. 6BA7E5F2Arn686ACC00)
    // are CDK-generated stable resource hashes, not secrets — they encode the
    // construct path. Marked with `pragma: allowlist secret` so detect-secrets
    // does not flag them as Base64 high-entropy strings.
    const userPoolArnExport = new cdk.CfnOutput(this, "LegacyUserPoolArnExport", {
      value: this.userPool.userPoolArn,
      exportName: `${this.stackName}:ExportsOutputFnGetAttUserPool6BA7E5F2Arn686ACC00`, // pragma: allowlist secret
    });
    userPoolArnExport.overrideLogicalId("ExportsOutputFnGetAttUserPool6BA7E5F2Arn686ACC00"); // pragma: allowlist secret

    const userPoolIdExport = new cdk.CfnOutput(this, "LegacyUserPoolIdExport", {
      value: this.userPool.userPoolId,
      exportName: `${this.stackName}:ExportsOutputRefUserPool6BA7E5F296FD7236`, // pragma: allowlist secret
    });
    userPoolIdExport.overrideLogicalId("ExportsOutputRefUserPool6BA7E5F296FD7236"); // pragma: allowlist secret

    const webClientIdExport = new cdk.CfnOutput(this, "LegacyWebClientIdExport", {
      value: this.userPoolClient.userPoolClientId,
      exportName: `${this.stackName}:ExportsOutputRefUserPoolWebClient4C9370B02E2C9FF9`, // pragma: allowlist secret
    });
    webClientIdExport.overrideLogicalId("ExportsOutputRefUserPoolWebClient4C9370B02E2C9FF9"); // pragma: allowlist secret

    // McpClient is conditional (only created when mcpCallbackUrls is
    // configured), so its legacy export must be conditional too — emitting
    // a CfnOutput that references a construct that doesn't exist would fail
    // synth. Environments that never configured mcpCallbackUrls never had
    // this export in the first place, so skipping it is safe for them.
    if (mcpClient) {
      const mcpClientIdExport = new cdk.CfnOutput(this, "LegacyMcpClientIdExport", {
        value: mcpClient.userPoolClientId,
        exportName: `${this.stackName}:ExportsOutputRefUserPoolMcpClient2D19DB876064FDF5`, // pragma: allowlist secret
      });
      mcpClientIdExport.overrideLogicalId("ExportsOutputRefUserPoolMcpClient2D19DB876064FDF5"); // pragma: allowlist secret
    }
  }

  /**
   * Keep the WebClient's callback/logout URLs at exactly WEB_UI_DEV_URL and the
   * Web UI site URL, whichever stack deploys and in whichever order.
   *
   * CloudFormation writes the template's URLs (WEB_UI_DEV_URL only) every time
   * it updates the client. The WebClientUrls custom resource carries a hash of
   * the client's synthesized properties, so CloudFormation runs it right after
   * each such update, and it puts the site URL back in the same deployment.
   * WebUiStack runs the same function (ARN in SSM) when its site URL is created
   * or changes. The function is the only writer of the site URL.
   */
  private addWebClientUrls(client: cognito.UserPoolClient): void {
    const fn = new lambda.Function(this, "WebClientUrlsFn", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "index.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "cognito-callback-urls")),
      timeout: cdk.Duration.minutes(1),
      memorySize: 128,
      description: "Sets the WebClient callback/logout URLs to the dev URL and the published Web UI site URL",
      environment: {
        USER_POOL_ID: this.userPool.userPoolId,
        CLIENT_ID: client.userPoolClientId,
        DEV_URL: WEB_UI_DEV_URL,
        SITE_URL_PARAM: WEB_UI_SITE_URL_PARAM,
      },
      logGroup: new logs.LogGroup(this, "WebClientUrlsFnLogs", {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["cognito-idp:DescribeUserPoolClient", "cognito-idp:UpdateUserPoolClient"],
      resources: [this.userPool.userPoolArn],
    }));
    fn.addToRolePolicy(new iam.PolicyStatement({
      actions: ["ssm:GetParameter"],
      resources: [this.formatArn({
        service: "ssm",
        resource: "parameter",
        resourceName: WEB_UI_SITE_URL_PARAM.slice(1),
      })],
    }));

    // Evaluated at synth, after every change to the client has been made.
    const cfnClient = client.node.defaultChild as cognito.CfnUserPoolClient;
    const clientConfigHash = cdk.Lazy.string({
      produce: () => createHash("sha256")
        .update(JSON.stringify(this.resolve(cfnClient._toCloudFormation())))
        .digest("hex"),
    });
    const webClientUrls = new cdk.CustomResource(this, "WebClientUrls", {
      serviceToken: fn.functionArn,
      resourceType: "Custom::WebClientUrls",
      properties: { ClientConfigHash: clientConfigHash },
    });
    webClientUrls.node.addDependency(client);

    new ssm.StringParameter(this, "WebClientUrlsFnArnParam", {
      parameterName: AUTH_SSM_PARAMS.webClientUrlsFnArn,
      stringValue: fn.functionArn,
      description: "Function that sets the WebClient callback/logout URLs (custom resource service token)",
    });
  }
}
