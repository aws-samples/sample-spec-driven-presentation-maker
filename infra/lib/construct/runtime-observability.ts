// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Observability settings shared by the agent and MCP runtimes.
 *
 * Message content: both containers start under `opentelemetry-instrument`
 * (aws-opentelemetry-distro). With AgentCore observability on, the distro sets
 * OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true unless the variable is
 * already set, and the botocore Bedrock instrumentation then writes every model
 * request and response body to the runtime log group. The runtimes set it to
 * "false" so that it stays off. Token counts on the spans do not depend on it.
 *
 * Retention: AgentCore creates the runtime log group
 * `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT` itself, without a
 * retention period. LogRetention (a custom resource calling PutRetentionPolicy,
 * creating the group first if it does not exist yet) sets one. It never deletes
 * the log group: on stack deletion the group and its data stay.
 */

import * as cdk from "aws-cdk-lib";
import * as logs from "aws-cdk-lib/aws-logs";
import { Construct } from "constructs";

/** Environment variables both runtimes carry for OpenTelemetry. */
export const RUNTIME_OTEL_ENVIRONMENT: Record<string, string> = {
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT: "false",
};

/** Retention of the runtime log groups when `observability.logRetentionDays` is not set. */
export const DEFAULT_RUNTIME_LOG_RETENTION = logs.RetentionDays.ONE_MONTH;

/** Retention periods CloudWatch Logs accepts (without "never expire"). */
const VALID_RETENTION_DAYS = Object.values(logs.RetentionDays)
  .filter((v): v is number => typeof v === "number" && v !== logs.RetentionDays.INFINITE)
  .sort((a, b) => a - b);

/**
 * Validate `observability.logRetentionDays` from config.yaml.
 * Undefined gives the default; anything CloudWatch Logs does not accept fails the synth.
 */
export function parseLogRetentionDays(value: unknown): logs.RetentionDays {
  if (value === undefined || value === null) return DEFAULT_RUNTIME_LOG_RETENTION;
  if (typeof value !== "number" || !VALID_RETENTION_DAYS.includes(value)) {
    throw new Error(
      `Config error: observability.logRetentionDays must be one of ${VALID_RETENTION_DAYS.join(", ")} ` +
      `(got ${JSON.stringify(value)}).`,
    );
  }
  return value as logs.RetentionDays;
}

/** Set the retention of the DEFAULT-endpoint log group AgentCore creates for a runtime. */
export function runtimeLogRetention(
  scope: Construct,
  id: string,
  runtimeId: string,
  retention: logs.RetentionDays = DEFAULT_RUNTIME_LOG_RETENTION,
): logs.LogRetention {
  return new logs.LogRetention(scope, id, {
    logGroupName: `/aws/bedrock-agentcore/runtimes/${runtimeId}-DEFAULT`,
    retention,
    // Stack deletion leaves the log group and its data in place.
    removalPolicy: cdk.RemovalPolicy.RETAIN,
  });
}
