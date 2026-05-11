// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// Security: This stack follows AWS security best practices for sample code.
// For production use, review and enhance IAM policies, encryption, and logging.
/**
 * Runtime Stack — Amazon Bedrock AgentCore Runtime MCP Server + ECR image.
 *
 * Deploys the spec-driven-presentation-maker FastMCP server as an Amazon Bedrock AgentCore Runtime via CfnRuntime.
 * JWT Bearer authentication configured from config.yaml (IdP-agnostic).
 */

import * as cdk from "aws-cdk-lib";
import * as apigatewayv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as apigatewayv2_integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";
import * as path from "path";
import { AUTH_SSM_PARAMS } from "./auth-stack";

interface RuntimeStackProps extends cdk.StackProps {
  /** Amazon DynamoDB table from DataStack. */
  table: dynamodb.TableV2;
  /** S3 bucket for PPTX output. */
  pptxBucket: s3.Bucket;
  /** S3 bucket for templates, assets, references. */
  resourceBucket: s3.Bucket;
  /**
   * OIDC discovery URL for JWT authorizer.
   * Used only when useAuthStack=false (external IdP). When useAuthStack=true,
   * the value is read from SSM instead.
   */
  oidcDiscoveryUrl?: string;
  /** Allowed client IDs for JWT authorizer (used only when useAuthStack=false, i.e. external IdP). */
  allowedClients: string[];
  /** KB SSM parameter name (empty if KB not enabled). */
  kbSsmParamName?: string;
  /** S3 Vector Bucket name (empty if KB not enabled). */
  vectorBucketName?: string;
  /** S3 Vector Index name (empty if KB not enabled). */
  vectorIndexName?: string;
  /**
   * When true, this stack reads Auth values from SSM Parameter Store
   * (published by AuthStack) and enables the OAuth discovery endpoint for
   * external MCP clients. When false (external IdP), Auth values are not
   * available and the discovery endpoint is skipped.
   */
  useAuthStack: boolean;
  /** Enable Dynamic Client Registration (RFC 7591) for external MCP clients. Default: true. */
  enableDCR?: boolean;
}

export class RuntimeStack extends cdk.Stack {
  /** Runtime ARN for Agent to connect to. */
  public readonly runtimeArn: string;

  constructor(scope: Construct, id: string, props: RuntimeStackProps) {
    super(scope, id, props);

    // --- Docker image → ECR ---
    const image = new ecr_assets.DockerImageAsset(this, "RuntimeImage", {
      directory: path.join(__dirname, "../.."),
      file: "mcp-server/Dockerfile",
      platform: ecr_assets.Platform.LINUX_ARM64,
    });

    // --- IAM Role for Runtime ---
    const runtimeRole = new iam.Role(this, "RuntimeRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      description: "Execution role for spec-driven-presentation-maker AgentCore Runtime",
    });

    props.table.grantReadWriteData(runtimeRole);
    props.pptxBucket.grantReadWrite(runtimeRole);
    props.resourceBucket.grantRead(runtimeRole);
    runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["s3:ListBucket"],
        resources: [props.pptxBucket.bucketArn, props.resourceBucket.bucketArn],
      })
    );

    // CloudWatch Logs (AgentCore writes stdout/stderr directly via execution role)
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogGroup", "logs:DescribeLogStreams"],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:DescribeLogGroups"],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:*`],
    }));
    runtimeRole.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`],
    }));
    runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:GetAuthorizationToken",
        ],
        resources: ["*"],
      })
    );

    // CloudWatch Logs / X-Ray / Metrics — required for AgentCore Runtime observability
    // https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html
    runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
        ],
        resources: [
          `arn:aws:logs:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/runtimes/*`,
          `arn:aws:logs:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`,
        ],
      })
    );
    runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
        ],
        resources: ["*"],
      })
    );
    runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: { StringEquals: { "cloudwatch:namespace": "bedrock-agentcore" } },
      })
    );

    image.repository.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com")],
        actions: ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"],
      })
    );
    image.repository.grant(runtimeRole, "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage");

    // --- Code Interpreter permissions ---
    runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:StartCodeInterpreterSession",
          "bedrock-agentcore:InvokeCodeInterpreter",
          "bedrock-agentcore:StopCodeInterpreterSession",
        ],
        resources: [
          `arn:aws:bedrock-agentcore:${cdk.Aws.REGION}:aws:code-interpreter/aws.codeinterpreter.v1`,
        ],
      })
    );

    // --- KB permissions (Amazon Titan Embed + S3 Vectors + Amazon Bedrock Retrieve) ---
    if (props.vectorBucketName) {
      runtimeRole.addToPolicy(
        new iam.PolicyStatement({
          actions: ["bedrock:InvokeModel"],
          resources: [
            `arn:aws:bedrock:${cdk.Aws.REGION}::foundation-model/amazon.titan-embed-text-v2:0`,
          ],
        })
      );
      runtimeRole.addToPolicy(
        new iam.PolicyStatement({
          actions: ["s3vectors:PutVectors", "s3vectors:DeleteVectors"],
          resources: [
            `arn:aws:s3vectors:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:bucket/${props.vectorBucketName}/index/${props.vectorIndexName}`,
          ],
        })
      );
      runtimeRole.addToPolicy(
        new iam.PolicyStatement({
          actions: ["bedrock:Retrieve"],
          resources: ["*"],  // KB ID not known at synth time (Custom Resource)
        })
      );
      runtimeRole.addToPolicy(
        new iam.PolicyStatement({
          actions: ["ssm:GetParameter"],
          resources: [
            `arn:aws:ssm:${cdk.Aws.REGION}:${cdk.Aws.ACCOUNT_ID}:parameter${props.kbSsmParamName}`,
          ],
        })
      );
    }

    // --- Amazon Bedrock AgentCore Runtime (JWT Bearer authorizer) ---
    const defaultPolicy = runtimeRole.node.findChild("DefaultPolicy") as iam.Policy;

    // When AuthStack is in play, prefer scope-based auth (DCR-compatible):
    // read the MCP custom scope from SSM and use it as allowedScopes.
    // Otherwise (external IdP), fall back to the static allowedClients list.
    const mcpCustomScope = props.useAuthStack
      ? ssm.StringParameter.valueForStringParameter(this, AUTH_SSM_PARAMS.mcpCustomScope)
      : undefined;
    const discoveryUrl = props.useAuthStack
      ? ssm.StringParameter.valueForStringParameter(this, AUTH_SSM_PARAMS.oidcDiscoveryUrl)
      : props.oidcDiscoveryUrl!;
    const authorizerConfig = props.useAuthStack
      ? { discoveryUrl, allowedScopes: [mcpCustomScope!] }
      : { discoveryUrl, allowedClients: props.allowedClients };

    const runtime = new bedrockagentcore.CfnRuntime(this, "SdpmRuntime", {
      agentRuntimeName: "sdpm",
      roleArn: runtimeRole.roleArn,
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: image.imageUri,
        },
      },
      networkConfiguration: {
        networkMode: "PUBLIC",
      },
      protocolConfiguration: "MCP",
      authorizerConfiguration: {
        customJwtAuthorizer: authorizerConfig,
      },
      requestHeaderConfiguration: {
        requestHeaderAllowlist: ["Authorization"],
      },
      environmentVariables: {
        DECKS_TABLE: props.table.tableName,
        PPTX_BUCKET: props.pptxBucket.bucketName,
        RESOURCE_BUCKET: props.resourceBucket.bucketName,
        AWS_DEFAULT_REGION: this.region,
        KB_SSM_PARAM: props.kbSsmParamName ?? "",
        VECTOR_BUCKET_NAME: props.vectorBucketName ?? "",
        VECTOR_INDEX_NAME: props.vectorIndexName ?? "",
        DEPLOY_TIMESTAMP: new Date().toISOString(),
      },
      description: "spec-driven-presentation-maker MCP Server — AI-powered presentation generation",
    });
    runtime.node.addDependency(defaultPolicy);

    const endpoint = new bedrockagentcore.CfnRuntimeEndpoint(
      this,
      "SdpmEndpoint",
      {
        agentRuntimeId: runtime.ref,
        name: "sdpm_endpoint",
        description: "spec-driven-presentation-maker MCP Server endpoint",
      }
    );
    endpoint.addDependency(runtime);

    // --- Outputs ---
    this.runtimeArn = runtime.attrAgentRuntimeArn;

    new cdk.CfnOutput(this, "RuntimeId", {
      value: runtime.ref,
      description: "AgentCore Runtime ID",
    });
    new cdk.CfnOutput(this, "RuntimeArn", {
      value: runtime.attrAgentRuntimeArn,
      description: "AgentCore Runtime ARN",
    });
    new cdk.CfnOutput(this, "EndpointId", {
      value: endpoint.attrId,
      description: "AgentCore Runtime Endpoint ID",
    });
    new cdk.CfnOutput(this, "RuntimeRoleArn", {
      value: runtimeRole.roleArn,
    });

    // --- OAuth 2.1 Discovery for external MCP clients (RFC 9728 / RFC 8414) ---
    // HTTP API + Lambda for OAuth discovery, 401 challenge, and proxy routes.
    // Enables Claude.ai, Kiro, and other MCP clients to auto-discover OAuth config.
    // Only enabled when AuthStack is in play (Cognito-backed). External IdP
    // users (useAuthStack=false) handle discovery at their IdP directly.
    if (props.useAuthStack) {
      // Read Auth values from SSM Parameter Store (published by AuthStack).
      const userPoolId = ssm.StringParameter.valueForStringParameter(
        this, AUTH_SSM_PARAMS.userPoolId,
      );
      const cognitoDomainPrefix = ssm.StringParameter.valueForStringParameter(
        this, AUTH_SSM_PARAMS.cognitoDomainPrefix,
      );
      const mcpClientIdRaw = ssm.StringParameter.valueForStringParameter(
        this, AUTH_SSM_PARAMS.mcpClientId,
      );
      // mcpCustomScope already fetched above for authorizerConfig.

      const cognitoDomain = cdk.Fn.join("", [
        "https://", cognitoDomainPrefix, ".auth.", this.region, ".amazoncognito.com",
      ]);
      const issuer = cdk.Fn.join("", [
        "https://cognito-idp.", this.region, ".amazonaws.com/", userPoolId,
      ]);

      // Lambda handles OAuth discovery, 401 challenge, and MCP proxy to AgentCore
      // AgentCore uses JWT Bearer auth — Lambda forwards the token directly (no SigV4)
      const runtimeInvokeUrl = cdk.Fn.join("", [
        `https://bedrock-agentcore.${this.region}.amazonaws.com/runtimes/`,
        "arn%3Aaws%3Abedrock-agentcore%3A", this.region, "%3A", this.account, "%3Aruntime%2F",
        runtime.ref,
        "/invocations?qualifier=DEFAULT",
      ]);

      const discoveryFn = new lambda.Function(this, "McpDiscoveryFn", {
        runtime: lambda.Runtime.PYTHON_3_13,
        handler: "index.handler",
        code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "mcp-discovery")),
        environment: {
          COGNITO_DOMAIN: cognitoDomain,
          ISSUER: issuer,
          RUNTIME_URL: runtimeInvokeUrl,
          USER_POOL_ID: userPoolId,
          // SSM-backed scope is always present (AuthStack always publishes it).
          MCP_SCOPES: cdk.Fn.join(",", ["openid", "profile", "email", mcpCustomScope!]),
          ENABLE_DCR: (props.enableDCR !== false) ? "true" : "false",
        },
        timeout: cdk.Duration.seconds(30),
        memorySize: 256,
        description: "OAuth 2.1 discovery + MCP proxy for external clients",
      });

      // Grant Lambda permission to manage Cognito App Clients (for idempotent DCR)
      const cognitoActions = props.enableDCR !== false
        ? [
            "cognito-idp:CreateUserPoolClient",
            "cognito-idp:ListUserPoolClients",
            "cognito-idp:DescribeUserPoolClient",
            "cognito-idp:UpdateUserPoolClient",
          ]
        : [
            "cognito-idp:DescribeUserPoolClient",
          ];
      discoveryFn.addToRolePolicy(new iam.PolicyStatement({
        actions: cognitoActions,
        resources: [cdk.Fn.join("", [
          "arn:aws:cognito-idp:", this.region, ":", this.account, ":userpool/", userPoolId,
        ])],
      }));

      const httpApi = new apigatewayv2.HttpApi(this, "McpHttpApi", {
        apiName: "sdpm-mcp-discovery",
        description: "OAuth 2.1 discovery + MCP proxy for external MCP clients",
      });

      const lambdaIntegration = new apigatewayv2_integrations.HttpLambdaIntegration(
        "McpDiscoveryIntegration", discoveryFn,
      );

      // All routes → Lambda (handles routing internally)
      for (const p of ["/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server",
                        "/authorize", "/token", "/register", "/mcp", "/"]) {
        httpApi.addRoutes({ path: p, methods: [apigatewayv2.HttpMethod.ANY], integration: lambdaIntegration });
      }

      new cdk.CfnOutput(this, "McpServerUrl", {
        value: httpApi.url!,
        description: "MCP Server URL for external MCP clients",
      });
      // SSM tokens are not synth-time strings, so we cannot conditionally emit
      // this Output based on whether mcpClientId is set. AuthStack publishes
      // the sentinel "-" when no static MCP client exists (DCR-only mode).
      new cdk.CfnOutput(this, "McpOAuthClientId", {
        value: mcpClientIdRaw,
        description: "OAuth Client ID for external MCP clients ('-' means DCR-only; clients register dynamically)",
      });
    }
  }
}
