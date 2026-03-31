// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
// Security: This stack follows AWS security best practices for sample code.
// For production use, review and enhance IAM policies, encryption, and logging.
/**
 * PNG Worker Stack — ECS AWS Fargate + SQS for PPTX→PNG conversion.
 *
 * Triggered by generate_pptx via direct SQS message.
 * Uses LibreOffice headless on Fedora 41 (ARM64 Graviton).
 * Optional — customers who don't need PNG previews skip this stack.
 */

import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr_assets from "aws-cdk-lib/aws-ecr-assets";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as sqs from "aws-cdk-lib/aws-sqs";
import { Construct } from "constructs";
import * as path from "path";

interface PngWorkerStackProps extends cdk.StackProps {
  table: dynamodb.TableV2;
  pptxBucket: s3.Bucket;
}

export class PngWorkerStack extends cdk.Stack {
  /** SQS queue URL for PNG generation jobs. */
  public readonly queueUrl: string;
  /** SQS queue for IAM permission grants. */
  public readonly queue: sqs.Queue;

  constructor(scope: Construct, id: string, props: PngWorkerStackProps) {
    super(scope, id, props);

    // --- SQS ---
    const dlq = new sqs.Queue(this, "PngDLQ", {
      retentionPeriod: cdk.Duration.days(14),
    });

    this.queue = new sqs.Queue(this, "PngQueue", {
      visibilityTimeout: cdk.Duration.minutes(5),
      deadLetterQueue: { queue: dlq, maxReceiveCount: 3 },
    });
    this.queueUrl = this.queue.queueUrl;

    // --- ECS AWS Fargate ---
    const vpc = new ec2.Vpc(this, "PngVpc", {
      maxAzs: 2,
      natGateways: 1,
    });

    const cluster = new ecs.Cluster(this, "PngCluster", { vpc });

    const taskDef = new ecs.FargateTaskDefinition(this, "PngTask", {
      cpu: 1024,
      memoryLimitMiB: 2048,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    const image = new ecr_assets.DockerImageAsset(this, "PngImage", {
      directory: path.join(__dirname, "../../png-worker"),
      platform: ecr_assets.Platform.LINUX_ARM64,
    });

    taskDef.addContainer("PngContainer", {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: "png-worker" }),
      environment: {
        QUEUE_URL: this.queue.queueUrl,
        DECKS_TABLE: props.table.tableName,
        AWS_REGION: this.region,
      },
    });

    // IAM permissions
    this.queue.grantConsumeMessages(taskDef.taskRole);
    props.pptxBucket.grantRead(taskDef.taskRole);
    props.pptxBucket.grantPut(taskDef.taskRole);
    props.table.grantReadWriteData(taskDef.taskRole);
    taskDef.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["s3:ListBucket"],
        resources: [props.pptxBucket.bucketArn],
      })
    );

    // AWS Fargate Service with autoscaling
    const service = new ecs.FargateService(this, "PngService", {
      cluster,
      taskDefinition: taskDef,
      desiredCount: 1,
      capacityProviderStrategies: [
        { capacityProvider: "FARGATE", base: 1, weight: 1 },
        { capacityProvider: "FARGATE_SPOT", weight: 4 },
      ],
    });

    const scaling = service.autoScaleTaskCount({ minCapacity: 1, maxCapacity: 10 });
    scaling.scaleOnMetric("QueueDepth", {
      metric: this.queue.metricApproximateNumberOfMessagesVisible(),
      scalingSteps: [
        { upper: 0, change: -9 },   // Scale to min when queue empty
        { lower: 1, change: +1 },
        { lower: 5, change: +2 },
        { lower: 20, change: +5 },
      ],
      adjustmentType: cdk.aws_applicationautoscaling.AdjustmentType.CHANGE_IN_CAPACITY,
    });

    // --- Outputs ---
    new cdk.CfnOutput(this, "QueueUrl", { value: this.queue.queueUrl });
    new cdk.CfnOutput(this, "DlqUrl", { value: dlq.queueUrl });
  }
}
