// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Cross-platform path utilities for client-side code that receives
 * filesystem paths from Python/MCP (which may use \ on Windows).
 */

/** Extract the last segment of a path, handling both / and \ separators. */
export function basename(p: string): string {
  return p.split(/[/\\]/).pop() || p
}
