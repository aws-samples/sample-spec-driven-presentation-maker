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
  "global.anthropic.claude-opus-5-5": {
    displayName: "Claude Opus 5.5",
    description: "Most capable Opus, long-running agentic coding and knowledge work",
  },
  "global.anthropic.claude-sonnet-5": {
    displayName: "Claude Sonnet 5",
    description: "Latest Sonnet, near-Opus intelligence for coding and agents",
  },
  "global.anthropic.claude-opus-4-8": {
    displayName: "Claude Opus 4.8",
    description: "Latest Opus, agentic coding and deep reasoning",
  },
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
  // --- OpenAI GPT ---
  "global.openai.gpt-6-astra": {
    displayName: "GPT-6 Astra",
    description: "OpenAI's newest frontier model, deep reasoning (slower output)",
  },
  "global.openai.gpt-6-sol": {
    displayName: "GPT-6 Sol",
    description: "Daily model for complex tasks and coding, Astra-level reliability at lower cost",
  },
  "global.openai.gpt-6-luna": {
    displayName: "GPT-6 Luna",
    description: "Fast and efficient for summarization, extraction and routing",
    composable: false,
  },
  "global.openai.gpt-5.6-terra": {
    displayName: "GPT-5.6 Terra",
    description: "Balanced performance competitive with GPT-5.5 at half the cost",
  },
  // --- Moonshot AI ---
  "global.moonshotai.kimi-k3": {
    displayName: "Kimi K3",
    description: "Moonshot AI's reasoning model, fast output",
  },
};
