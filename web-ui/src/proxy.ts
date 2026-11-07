// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local mode: every request must name this server by a loopback Host (see requestGuard.ts).
 * No matcher, so it runs before every route — the API routes and pages alike — and a new route
 * cannot opt out. Cloud mode is a static export; `build:cloud` moves this file out with the API
 * routes, so it never reaches the cloud build.
 */
import { rejectForeignHost } from "@/lib/local/requestGuard"
import { IS_LOCAL } from "@/lib/mode"

export function proxy(request: Request): Response | undefined {
  if (!IS_LOCAL) return undefined
  return rejectForeignHost(request) ?? undefined
}
