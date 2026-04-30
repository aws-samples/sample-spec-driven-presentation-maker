// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

export interface AllowedModel {
  modelId: string;
  displayName: string;
  description?: string;
}

export function getAllowedModels(): AllowedModel[] {
  try {
    const raw = process.env.NEXT_PUBLIC_ALLOWED_MODELS;
    if (!raw) return [];
    const parsed = JSON.parse(raw) as AllowedModel[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function getDefaultModelId(): string | undefined {
  return process.env.NEXT_PUBLIC_DEFAULT_MODEL_ID || undefined;
}
