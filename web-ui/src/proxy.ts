// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Every request must name this server by a loopback Host (see requestGuard.ts). There is no
 * NEXT_PUBLIC_MODE check: it runs wherever the API routes are served (the routes do not check
 * the mode either). No matcher, so it runs before every route — the API routes and pages alike —
 * and a new route cannot opt out. `build:cloud` moves this file out with the API routes, so it
 * never reaches the cloud static export.
 */
import { rejectForeignHost } from "@/lib/local/requestGuard"

export function proxy(request: Request): Response | undefined {
  return rejectForeignHost(request) ?? undefined
}
