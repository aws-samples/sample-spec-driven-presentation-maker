// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Runtime platform detection.
 * Single source of truth for Tauri vs Browser branching in shared UI code.
 */
export const isTauri = !!(globalThis as Record<string, unknown>).__TAURI_INTERNALS__
export const isBrowser = !isTauri
