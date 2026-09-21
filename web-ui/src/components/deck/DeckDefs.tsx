// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

"use client"

import { useEffect, useRef, useState } from "react"

interface DefsData {
  version: number
  defs: string
}

export type DeckDefsStatus = "loading" | "loaded" | "error"

interface DeckDefsProps {
  defsUrl: string
  onStatusChange?: (status: DeckDefsStatus) => void
}

export function DeckDefs({ defsUrl, onStatusChange }: DeckDefsProps) {
  const [loadedDefs, setLoadedDefs] = useState({ url: "", defs: "" })
  const onStatusChangeRef = useRef(onStatusChange)
  onStatusChangeRef.current = onStatusChange

  useEffect(() => {
    let cancelled = false
    setLoadedDefs({ url: defsUrl, defs: "" })
    onStatusChangeRef.current?.("loading")
    fetch(defsUrl)
      .then((response) => response.ok ? response.json() as Promise<DefsData> : Promise.reject())
      .then((data) => {
        if (cancelled) return
        if (data.version !== 1 || !data.defs) throw new Error("Unsupported or empty deck defs")
        setLoadedDefs({ url: defsUrl, defs: data.defs })
        onStatusChangeRef.current?.("loaded")
      })
      .catch(() => {
        if (!cancelled) onStatusChangeRef.current?.("error")
      })
    return () => {
      cancelled = true
      onStatusChangeRef.current?.("loading")
    }
  }, [defsUrl])

  return (
    <svg
      aria-hidden="true"
      focusable="false"
      style={{ position: "absolute", width: 0, height: 0, overflow: "hidden", pointerEvents: "none" }}
      // LibreOffice can reuse IDs across slides. This was already true when each
      // slide owned its defs; retaining those IDs preserves existing rendering.
      dangerouslySetInnerHTML={{ __html: loadedDefs.url === defsUrl ? loadedDefs.defs : "" }}
    />
  )
}
