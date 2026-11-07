// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Request guards for the Local server.
 *
 * Local mode has no authentication (single user, bound to 127.0.0.1). Two checks keep other
 * sites open in the same browser out:
 *
 * - `rejectForeignHost` (every request, from src/proxy.ts): the `Host` header must name this
 *   server by a loopback name on its own port. A page on another domain that resolves to
 *   127.0.0.1 sends its own domain as `Host`, so it is refused before any route runs.
 * - `rejectCrossSite` (routes that write): a browser always sends `Origin` on cross-origin and
 *   non-GET requests; a request whose Origin host is not the request host is refused. Requiring
 *   `application/json` on writes rules out simple (preflight-free) form posts.
 */

/** The `Host` values the Local server answers to: loopback names on its own port. */
export function allowedHosts(port: string = process.env.PORT || "3000"): Set<string> {
  return new Set([`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`])
}

/**
 * Refuse a request whose `Host` header is missing or not a loopback name on this server's port.
 * The port is the one Next listens on (`PORT`, which `next dev` / `next start` set; Next's
 * default 3000 otherwise).
 */
export function rejectForeignHost(req: Request, port?: string): Response | null {
  const host = (req.headers.get("host") || "").toLowerCase()
  if (allowedHosts(port).has(host)) return null
  return Response.json({ error: "Host not allowed" }, { status: 403 })
}

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
