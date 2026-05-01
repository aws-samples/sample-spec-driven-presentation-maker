// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Display metadata for Bedrock models supported by SDPM.
 *
 * To add a new model:
 *   1. Add an entry below with the Bedrock inference profile ID as the key.
 *   2. Add the ID to `model.allowedModelIds` in `infra/config.yaml`.
 *   3. Redeploy (`cdk deploy`).
 */

export interface ModelMetadata {
  displayName: string;
  description?: string;
  /** Whether the model is capable enough for slide generation (compose). Defaults to true. */
  composable?: boolean;
}

export const MODEL_METADATA: Record<string, ModelMetadata> = {
  // --- Anthropic Claude ---
  "global.anthropic.claude-opus-4-7": {
    displayName: "Claude Opus 4.7",
    description: "Highest quality, complex tasks",
  },
  "global.anthropic.claude-opus-4-6-v1": {
    displayName: "Claude Opus 4.6",
    description: "High quality, adaptive thinking",
  },
  "global.anthropic.claude-sonnet-4-6": {
    displayName: "Claude Sonnet 4.6",
    description: "Balanced quality and speed",
  },
  "global.anthropic.claude-haiku-4-5-20251001-v1:0": {
    displayName: "Claude Haiku 4.5",
    description: "Fast and economical",
    composable: false,
  },
  // --- Amazon Nova ---
  "us.amazon.nova-2-lite-v1:0": {
    displayName: "Nova 2 Lite",
    description: "Amazon's 2nd gen, fast and economical",
    composable: false,
  },
};
