// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useCurrentTemplate — Reads the confirmed template name from deck.json.
 *
 * The agent writes `"template": "<name>.pptx"` into deck.json during the
 * Art Direction phase. The deck API exposes deck.json via `defsUrl`.
 *
 * Note: `useWorkspace` stabilises `defsUrl` by base path, and the deck.json
 * S3 key never changes — so a template change does NOT change the URL string.
 * We therefore poll with `cache: "no-store"` while mounted instead of relying
 * on prop changes. This hook is only mounted while the Art Direction tab is
 * visible, which naturally scopes the polling.
 */

import { useEffect, useState } from "react"

const DEFAULT_POLL_MS = 5000

/**
 * Poll deck.json via defsUrl and return the confirmed template name.
 *
 * @param defsUrl - URL to deck.json (presigned S3 URL or local API route)
 * @param pollMs - Poll interval in milliseconds
 * @returns Template name without directory or `.pptx` extension, or null
 *          when unconfirmed (deck.json missing or `template` empty)
 */
export function useCurrentTemplate(defsUrl?: string | null, pollMs: number = DEFAULT_POLL_MS): string | null {
  const [template, setTemplate] = useState<string | null>(null)

  useEffect(() => {
    if (!defsUrl) {
      setTemplate(null)
      return
    }
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(defsUrl!, { cache: "no-store" })
        if (!res.ok) return
        const data = await res.json()
        if (cancelled) return
        const raw = typeof data.template === "string" ? data.template : ""
        // "templates/corporate.pptx" → "corporate"
        const name = raw.replace(/\.pptx$/, "").split("/").pop() || ""
        setTemplate(name || null)
      } catch {
        // deck.json may not exist yet — keep previous state
      }
    }

    load()
    const id = setInterval(load, pollMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [defsUrl, pollMs])

  return template
}
