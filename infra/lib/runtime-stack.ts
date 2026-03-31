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
import * as bedrockagentcore from "aws-cdk-lib/aws-bedrockagentcore";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";
import * as path from "path";

interface RuntimeStackProps extends cdk.StackProps {
  /** Amazon DynamoDB table from DataStack. */
  table: dynamodb.TableV2;
  /** S3 bucket for PPTX output. */
  pptxBucket: s3.Bucket;
  /** S3 bucket for templates, assets, references. */
  resourceBucket: s3.Bucket;
  /** OIDC discovery URL for JWT authorizer. */
  oidcDiscoveryUrl: string;
  /** Allowed client IDs for JWT authorizer. */
  allowedClients: string[];
  /** SQS queue URL for PNG generation jobs. Empty if PNG Worker not deployed. */
  pngQueueUrl?: string;
  /** SQS queue for IAM permission grants. Undefined if PNG Worker not deployed. */
  pngQueue?: sqs.IQueue;
  /** KB SSM parameter name (empty if KB not enabled). */
  kbSsmParamName?: string;
  /** S3 Vector Bucket name (empty if KB not enabled). */
  vectorBucketName?: string;
  /** S3 Vector Index name (empty if KB not enabled). */
  vectorIndexName?: string;
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

    // --- SQS permissions for PNG job submission ---
    if (props.pngQueue) {
      props.pngQueue.grantSendMessages(runtimeRole);
    }

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
        customJwtAuthorizer: {
          discoveryUrl: props.oidcDiscoveryUrl,
          allowedClients: props.allowedClients,
        },
      },
      requestHeaderConfiguration: {
        requestHeaderAllowlist: ["Authorization"],
      },
      environmentVariables: {
        DECKS_TABLE: props.table.tableName,
        PPTX_BUCKET: props.pptxBucket.bucketName,
        RESOURCE_BUCKET: props.resourceBucket.bucketName,
        PNG_QUEUE_URL: props.pngQueueUrl ?? "",
        AWS_DEFAULT_REGION: this.region,
        KB_SSM_PARAM: props.kbSsmParamName ?? "",
        VECTOR_BUCKET_NAME: props.vectorBucketName ?? "",
        VECTOR_INDEX_NAME: props.vectorIndexName ?? "",
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
  }
}
