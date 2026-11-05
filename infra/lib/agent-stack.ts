// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// Security: This stack follows AWS security best practices for sample code.
// For production use, review and enhance IAM policies, encryption, and logging.
/**
 * Agent Stack — Strands Agent Runtime on AgentCore.
 *
 * Deploys the spec-driven-presentation-maker Agent that connects to the L3 MCP Server Runtime.
 * JWT Bearer authentication — Agent forwards caller's JWT to MCP Server.
 */

import * as cdk from "aws-cdk-lib";
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";
import * as path from "path";
import { AUTH_SSM_PARAMS } from "./auth-stack";
import { RuntimeResourcePolicy } from "./construct/runtime-resource-policy";
import { agentCoreServicePrincipal } from "./construct/agentcore-principal";
import { RUNTIME_OTEL_ENVIRONMENT, runtimeLogRetention } from "./construct/runtime-observability";

interface AgentStackProps extends cdk.StackProps {
  /** MCP Server Runtime ARN. */
  mcpRuntimeArn: string;
  /**
   * OIDC discovery URL for JWT authorizer.
   * Used only when useAuthStack=false (external IdP). When useAuthStack=true,
   * the value is read from SSM instead.
   */
  oidcDiscoveryUrl?: string;
  /**
   * Allowed client IDs for JWT authorizer.
   * Used only when useAuthStack=false (external IdP). When useAuthStack=true,
   * the WebClient ID is read from SSM instead.
   */
  allowedClients: string[];
  /**
   * When true, read the WebClient ID from SSM Parameter Store (published by
   * AuthStack) and prepend it to allowedClients. Avoids a direct construct
   * reference to AuthStack that would trigger a cross-stack CFN export.
   */
  useAuthStack: boolean;
  /** Bedrock model ID for the chat (conversation/planning) task. */
  chatModelId?: string;
  /** Bedrock model ID for the create (generation) task. */
  createModelId?: string;
  /** Allowed model IDs for per-user model switching; empty = feature disabled. */
  allowedModelIds: string[];
  /** Retention of the runtime's log group (observability.logRetentionDays). Default: 30 days. */
  logRetention?: logs.RetentionDays;
}

export class AgentStack extends cdk.Stack {
  /** Agent Runtime ARN for web-ui to invoke. */
  public readonly agentRuntimeArn: string;
  /** Amazon Bedrock AgentCore Memory ID for chat history retrieval. */
  public readonly memoryId: string;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);

    // --- Docker image ---
    // Root context: the image installs from the workspace uv.lock. The root
    // .dockerignore (allowlist) keeps the context to what agent/Dockerfile COPYs.
    const image = new ecr_assets.DockerImageAsset(this, "AgentImage", {
      directory: path.join(__dirname, "../.."),
      file: "agent/Dockerfile",
      platform: ecr_assets.Platform.LINUX_ARM64,
    });

    // --- IAM Role ---
    // Execution role: only what the agent code uses. Deck storage (DynamoDB / S3)
    // belongs to the MCP Runtime, which the agent calls with the user's JWT, so
    // the agent role needs no storage or runtime-invoke permissions.
    // Trust: only AgentCore resources of this account (confused-deputy guard).
    const role = new iam.Role(this, "AgentRole", {
      assumedBy: agentCoreServicePrincipal(this),
      description: "Execution role for spec-driven-presentation-maker Agent Runtime",
    });

    // Bedrock Converse / ConverseStream. Resource stays "*": the model can be
    // switched per user among allowedModelIds (cross-region inference profiles).
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: ["*"],
      })
    );

    // CloudWatch Logs (AgentCore writes stdout/stderr directly via execution role)
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogGroup", "logs:DescribeLogStreams"],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:DescribeLogGroups"],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:*`],
    }));
    role.addToPolicy(new iam.PolicyStatement({
      actions: ["logs:CreateLogStream", "logs:PutLogEvents"],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`],
    }));

    // AWS Pricing API (used by aws-pricing-mcp-server, stdio MCP)
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["pricing:GetProducts", "pricing:DescribeServices", "pricing:GetAttributeValues"],
        resources: ["*"],
      })
    );

    // Explicit denies (security best practices for AgentCore Runtime):
    // - user-id delegation: the agent identifies users by the verified JWT only.
    // - calls made through AWS-managed MCP servers: the agent uses the public
    //   AWS Knowledge endpoint, which carries no AWS credentials.
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "DenyUserIdDelegation",
        effect: iam.Effect.DENY,
        actions: [
          "bedrock-agentcore:InvokeAgentRuntimeForUser",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
        ],
        resources: ["*"],
      })
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: "DenyViaAwsManagedMcp",
        effect: iam.Effect.DENY,
        actions: ["*"],
        resources: ["*"],
        conditions: { Bool: { "aws:ViaAWSMCPService": "true" } },
      })
    );

    // ECR pull: the image repository only (GetAuthorizationToken has no resource scope)
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"],
        resources: [image.repository.repositoryArn],
      })
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ecr:GetAuthorizationToken"],
        resources: ["*"],
      })
    );

    // X-Ray / Metrics — required for AgentCore Runtime observability
    // https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html
    role.addToPolicy(
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
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: { StringEquals: { "cloudwatch:namespace": "bedrock-agentcore" } },
      })
    );

    image.repository.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [
          new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
        ],
        actions: ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"],
      })
    );

    // --- Amazon Bedrock AgentCore Memory ---
    const memory = new bedrockagentcore.CfnMemory(this, "AgentMemory", {
      name: "sdpm_memory",
      eventExpiryDuration: 90,
    });
    const memoryId = memory.attrMemoryId;

    // Memory: the short-term event calls of the Strands session manager
    // (AgentCoreMemorySessionManager; no long-term retrieval is configured).
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "bedrock-agentcore:CreateEvent",
          "bedrock-agentcore:ListEvents",
          "bedrock-agentcore:GetEvent",
          "bedrock-agentcore:DeleteEvent",
        ],
        resources: [memory.attrMemoryArn],
      })
    );

    // --- Amazon Bedrock AgentCore Runtime ---
    const defaultPolicy = role.node.findChild("DefaultPolicy") as iam.Policy;

    // When AuthStack is in play, read the WebClient ID from SSM and include it
    // in the allowedClients list. This avoids direct AuthStack construct
    // references that would trigger cross-stack CFN exports.
    const allowedClients = props.useAuthStack
      ? [ssm.StringParameter.valueForStringParameter(this, AUTH_SSM_PARAMS.webClientId)]
      : props.allowedClients;
    const discoveryUrl = props.useAuthStack
      ? ssm.StringParameter.valueForStringParameter(this, AUTH_SSM_PARAMS.oidcDiscoveryUrl)
      : props.oidcDiscoveryUrl!;

    const runtime = new bedrockagentcore.CfnRuntime(this, "AgentRuntime", {
      agentRuntimeName: "sdpm_agent",
      roleArn: role.roleArn,
      // V2 restores each microVM from a snapshot taken after startup. The agent builds
      // its clients, connections and per-session state on the first request, and draws
      // the random module's values from the kernel (shared/snapshot_random.py). Each new
      // version builds a new snapshot, so the environment below holds no per-deploy
      // value: a deploy that changes neither the image nor the configuration creates
      // no version.
      platformVersion: "V2",
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: image.imageUri,
        },
      },
      networkConfiguration: {
        networkMode: "PUBLIC",
      },
      protocolConfiguration: "HTTP",
      authorizerConfiguration: {
        customJwtAuthorizer: {
          discoveryUrl,
          allowedClients,
        },
      },
      requestHeaderConfiguration: {
        requestHeaderAllowlist: ["Authorization"],
      },
      environmentVariables: {
        MCP_RUNTIME_ARN: props.mcpRuntimeArn,
        CHAT_MODEL_ID: this.node.tryGetContext("chatModelId") || props.chatModelId || "global.anthropic.claude-sonnet-4-6",
        CREATE_MODEL_ID: this.node.tryGetContext("createModelId") || props.createModelId || props.chatModelId || "global.anthropic.claude-sonnet-4-6",
        ALLOWED_MODEL_IDS: JSON.stringify(props.allowedModelIds ?? []),
        MEMORY_ID: memoryId,
        AWS_DEFAULT_REGION: this.region,
        COMPOSER_MAX_CONCURRENCY: "10",
        ...RUNTIME_OTEL_ENVIRONMENT,
      },
      description: "spec-driven-presentation-maker Strands Agent — connects to MCP Server for slide generation",
    });
    runtime.node.addDependency(defaultPolicy);

    // Retention of the log group AgentCore creates for this runtime (observability.logRetentionDays).
    runtimeLogRetention(this, "AgentRuntimeLogRetention", runtime.attrAgentRuntimeId, props.logRetention);

    const endpoint = new bedrockagentcore.CfnRuntimeEndpoint(
      this,
      "AgentEndpoint",
      {
        agentRuntimeId: runtime.ref,
        name: "sdpm_agent_endpoint",
        description: "spec-driven-presentation-maker Agent endpoint",
      }
    );
    endpoint.addDependency(runtime);

    // Allow only invoke, the Web UI's WebSocket (/ws) and stop on the runtime and its endpoints.
    new RuntimeResourcePolicy(this, "AgentRuntimeResourcePolicy", {
      runtimeArn: runtime.attrAgentRuntimeArn,
      endpointArns: { AgentEndpoint: endpoint.attrAgentRuntimeEndpointArn },
      allowWebSocket: true,
    });

    this.agentRuntimeArn = runtime.attrAgentRuntimeArn;
    this.memoryId = memoryId;

    // --- Outputs ---
    new cdk.CfnOutput(this, "AgentRuntimeArn", {
      value: runtime.attrAgentRuntimeArn,
    });
  }
}
