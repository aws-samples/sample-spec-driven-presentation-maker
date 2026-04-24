// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * usePreferences — Read/write user preferences from localStorage.
 *
 * @returns { sendWithEnter, setSendWithEnter, viewMode, setViewMode }
 */

import { useState, useCallback } from "react"

const KEY = "sdpm-prefs"

interface Prefs {
  sendWithEnter: boolean
  viewMode: "full" | "grid"
  fetchWebImages: boolean
  parallelAgents: boolean
  agentMode: "spec" | "vibe"
}

const DEFAULTS: Prefs = { sendWithEnter: false, viewMode: "full", fetchWebImages: false, parallelAgents: false, agentMode: "spec" }

/**
 * Read preferences from localStorage, falling back to defaults.
 *
 * @returns Merged preferences object
 */
function read(): Prefs {
  if (typeof window === "undefined") return DEFAULTS
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS
  } catch {
    return DEFAULTS
  }
}

export function usePreferences() {
  const [prefs, setPrefs] = useState<Prefs>(read)

  const update = useCallback((patch: Partial<Prefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch }
      localStorage.setItem(KEY, JSON.stringify(next))
      return next
    })
  }, [])

  return {
    sendWithEnter: prefs.sendWithEnter,
    setSendWithEnter: useCallback((v: boolean) => update({ sendWithEnter: v }), [update]),
    viewMode: prefs.viewMode,
    setViewMode: useCallback((v: "full" | "grid") => update({ viewMode: v }), [update]),
    fetchWebImages: prefs.fetchWebImages,
    setFetchWebImages: useCallback((v: boolean) => update({ fetchWebImages: v }), [update]),
    parallelAgents: prefs.parallelAgents,
    setParallelAgents: useCallback((v: boolean) => update({ parallelAgents: v }), [update]),
    agentMode: prefs.agentMode,
    setAgentMode: useCallback((v: "spec" | "vibe") => update({ agentMode: v }), [update]),
  }
}
