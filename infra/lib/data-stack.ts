// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// Security: This stack follows AWS security best practices for sample code.
// For production use, review and enhance IAM policies, encryption, and logging.
/**
 * Data Stack — Amazon DynamoDB table, S3 buckets, and default resource deployment.
 *
 * Creates the shared data layer used by all other stacks.
 */

import * as cdk from "aws-cdk-lib";
import * as cr from "aws-cdk-lib/custom-resources";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";
import * as path from "path";

interface DataStackProps extends cdk.StackProps {
  /** Enable semantic slide search (Amazon Bedrock KB + S3 Vectors). */
  searchSlides?: boolean;
  /** Enable observability (Model Invocation Logging). Opt-in, default false. */
  observability?: boolean;
}

export class DataStack extends cdk.Stack {
  /** Amazon DynamoDB table for decks, slides, and templates. */
  public readonly table: dynamodb.TableV2;
  /** S3 bucket for generated PPTX files and previews. */
  public readonly pptxBucket: s3.Bucket;
  /** S3 bucket for templates, assets, and reference documents. */
  public readonly resourceBucket: s3.Bucket;
  /** KB ID SSM parameter name (empty if KB not enabled). */
  public readonly kbSsmParamName: string;
  /** S3 Vector Bucket name (empty if KB not enabled). */
  public readonly vectorBucketName: string;
  /** S3 Vector Index name (empty if KB not enabled). */
  public readonly vectorIndexName: string;

  constructor(scope: Construct, id: string, props?: DataStackProps) {
    super(scope, id, props);

    // --- Amazon DynamoDB ---
    this.table = new dynamodb.TableV2(this, "DecksTable", {
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billing: dynamodb.Billing.onDemand(),
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryptionV2.awsManagedKey(),
      globalSecondaryIndexes: [
        {
          indexName: "PublicDecks",
          partitionKey: { name: "GSI1PK", type: dynamodb.AttributeType.STRING },
          sortKey: { name: "GSI1SK", type: dynamodb.AttributeType.STRING },
        },
      ],
    });

    // --- S3 Buckets ---
    this.pptxBucket = new s3.Bucket(this, "PptxBucket", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      serverAccessLogsPrefix: "access-logs/",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      eventBridgeEnabled: true,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.HEAD],
          allowedOrigins: ["*"],
          allowedHeaders: ["*"],
          exposedHeaders: ["ETag"],
        },
      ],
      lifecycleRules: [
        {
          // Clean up old PPTX versions after 90 days
          prefix: "pptx/",
          expiration: cdk.Duration.days(90),
          noncurrentVersionExpiration: cdk.Duration.days(30),
        },
        {
          // Clean up version history after 30 days
          prefix: "history/",
          expiration: cdk.Duration.days(30),
        },
      ],
    });

    this.resourceBucket = new s3.Bucket(this, "ResourceBucket", {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // --- Deploy default resources to S3 ---
    new s3deploy.BucketDeployment(this, "DeployReferences", {
      sources: [
        s3deploy.Source.asset(path.join(__dirname, "../../skill/references")),
      ],
      destinationBucket: this.resourceBucket,
      destinationKeyPrefix: "references/",
    });

    new s3deploy.BucketDeployment(this, "DeployAssets", {
      sources: [
        s3deploy.Source.asset(path.join(__dirname, "../../skill/templates")),
      ],
      destinationBucket: this.resourceBucket,
      destinationKeyPrefix: "templates/",
    });

    // Deploy asset icons — auto-download if not present
    const assetsDir = path.join(__dirname, "../../skill/assets");
    const scriptsDir = path.join(__dirname, "../../skill/scripts");
    new s3deploy.BucketDeployment(this, "DeployIcons", {
      sources: [
        s3deploy.Source.asset(scriptsDir, {
          bundling: {
            image: cdk.DockerImage.fromRegistry("python:3.13-slim"),
            command: [
              "bash", "-c",
              "python3 /asset-input/download_aws_icons.py && " +
              "python3 /asset-input/download_material_icons.py && " +
              "cp -r /asset-input/../assets/* /asset-output/",
            ],
            local: {
              tryBundle(outputDir: string): boolean {
                const fs = require("fs");
                const { execSync } = require("child_process");
                const awsManifest = path.join(assetsDir, "aws", "manifest.json");
                if (!fs.existsSync(awsManifest)) {
                  execSync(`python3 ${path.join(scriptsDir, "download_aws_icons.py")}`, { stdio: "inherit" });
                  execSync(`python3 ${path.join(scriptsDir, "download_material_icons.py")}`, { stdio: "inherit" });
                }
                execSync(`cp -r ${assetsDir}/* ${outputDir}/`, { stdio: "inherit" });
                return true;
              },
            },
          },
        }),
      ],
      destinationBucket: this.resourceBucket,
      destinationKeyPrefix: "assets/",
      memoryLimit: 1024,
    });

    // --- Outputs ---
    new cdk.CfnOutput(this, "TableName", { value: this.table.tableName });
    new cdk.CfnOutput(this, "PptxBucketName", { value: this.pptxBucket.bucketName });
    new cdk.CfnOutput(this, "ResourceBucketName", { value: this.resourceBucket.bucketName });

    // --- Register default templates in Amazon DynamoDB ---
    const templates = [
      { id: "sample_template_dark", name: "sample_template_dark", isDefault: true },
      { id: "sample_template_light", name: "sample_template_light", isDefault: false },
    ];

    for (const tmpl of templates) {
      new cr.AwsCustomResource(this, `RegisterTemplate_${tmpl.id}`, {
        onCreate: {
          service: "DynamoDB",
          action: "putItem",
          parameters: {
            TableName: this.table.tableName,
            Item: {
              PK: { S: `TEMPLATE#${tmpl.id}` },
              SK: { S: "META" },
              name: { S: tmpl.name },
              s3Key: { S: `templates/${tmpl.name}.pptx` },
              analysisJson: { S: "{}" },
              isDefault: { BOOL: tmpl.isDefault },
              createdAt: { S: new Date().toISOString() },
              updatedAt: { S: new Date().toISOString() },
            },
            ConditionExpression: "attribute_not_exists(PK)",
          },
          physicalResourceId: cr.PhysicalResourceId.of(`template-${tmpl.id}`),
          ignoreErrorCodesMatching: "ConditionalCheckFailedException",
        },
        policy: cr.AwsCustomResourcePolicy.fromSdkCalls({
          resources: [this.table.tableArn],
        }),
      });
    }

    // --- Observability (optional, gated by features.observability) ---
    if (props?.observability) {
      // CloudWatch Logs group for Amazon Bedrock model invocation logs
      const bedrockLogGroup = new logs.LogGroup(this, "BedrockInvocationLogs", {
        logGroupName: "/aws/bedrock/model-invocation-logs",
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      });

      // IAM role for Amazon Bedrock to write to CloudWatch Logs
      const bedrockLoggingRole = new iam.Role(this, "BedrockLoggingRole", {
        assumedBy: new iam.ServicePrincipal("bedrock.amazonaws.com"),
        description: "Allows Bedrock to write model invocation logs",
      });
      bedrockLogGroup.grantWrite(bedrockLoggingRole);
      bedrockLoggingRole.addToPolicy(new iam.PolicyStatement({
        actions: [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents",
        ],
        resources: [
          bedrockLogGroup.logGroupArn,
          `${bedrockLogGroup.logGroupArn}:*`,
        ],
      }));
      this.pptxBucket.grantWrite(bedrockLoggingRole, "bedrock-logs/*");

      // S3 bucket policy required by Amazon Bedrock for model invocation logging
      this.pptxBucket.addToResourcePolicy(new iam.PolicyStatement({
        sid: "BedrockModelInvocationLogsWrite",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("bedrock.amazonaws.com")],
        actions: ["s3:PutObject"],
        resources: [`${this.pptxBucket.bucketArn}/bedrock-logs/*`],
        conditions: {
          StringEquals: { "aws:SourceAccount": this.account },
          ArnLike: { "aws:SourceArn": `arn:aws:bedrock:${this.region}:${this.account}:*` },
        },
      }));

      // Custom Resource Lambda for Amazon Bedrock logging + Transaction Search
      const loggingFn = new lambda.Function(this, "BedrockLoggingFn", {
        runtime: lambda.Runtime.PYTHON_3_13,
        architecture: lambda.Architecture.ARM_64,
        handler: "index.handler",
        code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "bedrock-logging")),
        timeout: cdk.Duration.minutes(2),
        logGroup: new logs.LogGroup(this, "BedrockLoggingFnLogs", {
          logGroupName: "/aws/lambda/sdpm-bedrock-logging",
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      });

      loggingFn.addToRolePolicy(new iam.PolicyStatement({
        actions: [
          "bedrock:PutModelInvocationLoggingConfiguration",
          "bedrock:GetModelInvocationLoggingConfiguration",
          "bedrock:DeleteModelInvocationLoggingConfiguration",
        ],
        resources: ["*"],
      }));
      loggingFn.addToRolePolicy(new iam.PolicyStatement({
        actions: ["iam:PassRole"],
        resources: [bedrockLoggingRole.roleArn],
      }));

      new cdk.CustomResource(this, "BedrockLoggingConfig", {
        serviceToken: loggingFn.functionArn,
        properties: {
          LogGroupName: bedrockLogGroup.logGroupName,
          S3BucketName: this.pptxBucket.bucketName,
          S3Prefix: "bedrock-logs",
          BedrockRoleArn: bedrockLoggingRole.roleArn,
          AccountId: this.account,
          Region: this.region,
        },
      });
    }

    // --- Knowledge Base (optional, gated by features.searchSlides) ---
    this.kbSsmParamName = "";
    this.vectorBucketName = "";
    this.vectorIndexName = "";

    if (props?.searchSlides) {
      const kbName = `sdpm-slide-kb`;
      this.vectorBucketName = `sdpm-slide-vectors`;
      this.vectorIndexName = `${kbName}-index`;
      this.kbSsmParamName = `/sdpm/kb-id`;

      // KB execution role (assumed by Amazon Bedrock)
      const kbRole = new iam.Role(this, "KbRole", {
        assumedBy: new iam.ServicePrincipal("bedrock.amazonaws.com"),
      });
      kbRole.addToPolicy(new iam.PolicyStatement({
        actions: ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
        resources: [this.pptxBucket.bucketArn, `${this.pptxBucket.bucketArn}/*`],
      }));
      kbRole.addToPolicy(new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: [`arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`],
      }));
      kbRole.addToPolicy(new iam.PolicyStatement({
        actions: ["s3vectors:*"],
        resources: ["*"],
      }));

      // KB Provisioner Lambda (Custom Resource)
      const provisionerFn = new lambda.Function(this, "KbProvisionerFn", {
        runtime: lambda.Runtime.PYTHON_3_13,
        architecture: lambda.Architecture.ARM_64,
        handler: "index.handler",
        code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambdas", "kb-provisioner")),
        timeout: cdk.Duration.minutes(5),
        environment: { SSM_KB_ID_PARAM: this.kbSsmParamName },
        logGroup: new logs.LogGroup(this, "KbProvisionerLogGroup", {
          logGroupName: `/aws/lambda/sdpm-kb-provisioner`,
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      });
      provisionerFn.addToRolePolicy(new iam.PolicyStatement({
        actions: [
          "bedrock:CreateKnowledgeBase", "bedrock:GetKnowledgeBase", "bedrock:DeleteKnowledgeBase",
          "bedrock:CreateDataSource", "bedrock:DeleteDataSource", "bedrock:ListDataSources",
          "s3vectors:CreateVectorBucket", "s3vectors:GetVectorBucket", "s3vectors:DeleteVectorBucket",
          "s3vectors:CreateIndex", "s3vectors:GetIndex", "s3vectors:DeleteIndex", "s3vectors:ListIndexes",
          "sts:GetCallerIdentity",
        ],
        resources: ["*"],
      }));
      provisionerFn.addToRolePolicy(new iam.PolicyStatement({
        actions: ["ssm:PutParameter"],
        resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${this.kbSsmParamName}`],
      }));
      provisionerFn.addToRolePolicy(new iam.PolicyStatement({
        actions: ["iam:PassRole"],
        resources: [kbRole.roleArn],
      }));

      new cdk.CustomResource(this, "SlideKB", {
        serviceToken: provisionerFn.functionArn,
        properties: {
          KbName: kbName,
          RoleArn: kbRole.roleArn,
          VectorBucketName: this.vectorBucketName,
          DataSourceBucketArn: this.pptxBucket.bucketArn,
          Region: this.region,
          EmbeddingDimension: "1024",
        },
      });

      // SSM parameter for KB ID (provisioner writes the value)
      new ssm.StringParameter(this, "KbIdParam", {
        parameterName: this.kbSsmParamName,
        stringValue: "pending",  // Overwritten by provisioner
        description: "Bedrock Knowledge Base ID for slide search",
      });
    }
  }
}
