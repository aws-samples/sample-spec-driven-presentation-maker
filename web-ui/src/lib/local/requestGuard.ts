// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Cross-site request guard for Local API routes.
 *
 * Local mode has no authentication (single user, bound to 127.0.0.1), so another site open in
 * the same browser could otherwise post to these routes. A browser always sends `Origin` on
 * cross-origin and non-GET requests; a request whose Origin host is not the request host is
 * refused. Requiring `application/json` on writes rules out simple (preflight-free) form posts.
 */

export function rejectCrossSite(req: Request, { requireJson = false }: { requireJson?: boolean } = {}): Response | null {
  const origin = req.headers.get("origin")
  if (origin !== null) {
    let originHost: string | null = null
    try { originHost = new URL(origin).host } catch { /* "null" or malformed origin */ }
    const host = req.headers.get("host") || new URL(req.url).host
    if (!originHost || originHost !== host) {
      return Response.json({ error: "Cross-site request refused" }, { status: 403 })
    }
  }
  if (requireJson) {
    const type = (req.headers.get("content-type") || "").toLowerCase()
    if (!type.startsWith("application/json")) {
      return Response.json({ error: "Content-Type must be application/json" }, { status: 415 })
    }
  }
  return null
}
