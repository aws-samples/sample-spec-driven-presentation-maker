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
}

export const MODEL_METADATA: Record<string, ModelMetadata> = {
  // --- Anthropic Claude ---
  "global.anthropic.claude-opus-4-7": {
    displayName: "Claude Opus 4.7",
    description: "Highest quality, complex tasks",
  },
  "global.anthropic.claude-sonnet-4-6": {
    displayName: "Claude Sonnet 4.6",
    description: "Balanced quality and speed",
  },
  "global.anthropic.claude-haiku-4-5-20251001-v1:0": {
    displayName: "Claude Haiku 4.5",
    description: "Fast and economical",
  },
  // --- Moonshot AI ---
  "moonshotai.kimi-k2.5": {
    displayName: "Kimi K2.5",
    description: "High performance, 256K context, cost-efficient",
  },
  // --- DeepSeek ---
  "deepseek.v3.2": {
    displayName: "DeepSeek V3.2",
    description: "Strong reasoning, very low cost",
  },
  // --- Qwen ---
  "qwen.qwen3-235b-a22b-2507-v1:0": {
    displayName: "Qwen3 235B",
    description: "Alibaba's flagship, agent-capable",
  },
  // --- Amazon Nova ---
  "us.amazon.nova-pro-v1:0": {
    displayName: "Nova Pro",
    description: "Amazon's multimodal model",
  },
  "us.amazon.nova-lite-v1:0": {
    displayName: "Nova Lite",
    description: "Lightweight, fastest and cheapest",
  },
};
