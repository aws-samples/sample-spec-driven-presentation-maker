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
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import * as path from "path";

interface AgentStackProps extends cdk.StackProps {
  /** Amazon DynamoDB table from DataStack. */
  table: dynamodb.TableV2;
  /** S3 bucket for PPTX output. */
  pptxBucket: s3.Bucket;
  /** MCP Server Runtime ARN. */
  mcpRuntimeArn: string;
  /** OIDC discovery URL for JWT authorizer. */
  oidcDiscoveryUrl: string;
  /** Allowed client IDs for JWT authorizer. */
  allowedClients: string[];
  /** Bedrock model ID from config.yaml. Overridable via CDK context -c modelId=... */
  modelId?: string;
}

export class AgentStack extends cdk.Stack {
  /** Agent Runtime ARN for web-ui to invoke. */
  public readonly agentRuntimeArn: string;
  /** Amazon Bedrock AgentCore Memory ID for chat history retrieval. */
  public readonly memoryId: string;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);

    // --- Docker image ---
    const image = new ecr_assets.DockerImageAsset(this, "AgentImage", {
      directory: path.join(__dirname, "../../agent"),
      platform: ecr_assets.Platform.LINUX_ARM64,
    });

    // --- IAM Role ---
    const role = new iam.Role(this, "AgentRole", {
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      description: "Execution role for spec-driven-presentation-maker Agent Runtime",
    });

    // IAM: Least-privilege — Agent role only gets Bedrock InvokeModel and MCP Runtime invoke.
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: ["*"],
      })
    );

    props.table.grantReadWriteData(role);
    props.pptxBucket.grantReadWrite(role);

    // AWS Pricing API (used by aws-pricing-mcp-server, stdio MCP)
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["pricing:GetProducts", "pricing:DescribeServices", "pricing:GetAttributeValues"],
        resources: ["*"],
      })
    );

    // Amazon Bedrock AgentCore Memory
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:*"],
        resources: ["*"],
      })
    );

    // AWS MCP service (IAM-authenticated Knowledge MCP endpoint)
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["aws-mcp:*"],
        resources: ["*"],
      })
    );

    // ECR pull
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:GetAuthorizationToken",
        ],
        resources: ["*"],
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

    // --- Amazon Bedrock AgentCore Runtime ---
    const defaultPolicy = role.node.findChild("DefaultPolicy") as iam.Policy;

    const runtime = new bedrockagentcore.CfnRuntime(this, "AgentRuntime", {
      agentRuntimeName: "sdpm_agent",
      roleArn: role.roleArn,
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
          discoveryUrl: props.oidcDiscoveryUrl,
          allowedClients: props.allowedClients,
        },
      },
      requestHeaderConfiguration: {
        requestHeaderAllowlist: ["Authorization"],
      },
      environmentVariables: {
        MCP_RUNTIME_ARN: props.mcpRuntimeArn,
        MODEL_ID: this.node.tryGetContext("modelId") || props.modelId || "global.anthropic.claude-sonnet-4-6",
        MEMORY_ID: memoryId,
        DECKS_TABLE: props.table.tableName,
        PPTX_BUCKET: props.pptxBucket.bucketName,
        AWS_DEFAULT_REGION: this.region,
        DEPLOY_TIMESTAMP: new Date().toISOString(),
      },
      description: "spec-driven-presentation-maker Strands Agent — connects to MCP Server for slide generation",
    });
    runtime.node.addDependency(defaultPolicy);

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

    this.agentRuntimeArn = runtime.attrAgentRuntimeArn;
    this.memoryId = memoryId;

    // --- Outputs ---
    new cdk.CfnOutput(this, "AgentRuntimeArn", {
      value: runtime.attrAgentRuntimeArn,
    });
  }
}
