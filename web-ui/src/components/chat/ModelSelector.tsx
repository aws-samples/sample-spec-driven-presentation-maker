// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { useState, useEffect } from "react"

interface AcpModel { modelId: string; name: string; description?: string }

export function ModelSelector() {
  const [model, setModelState] = useState<string>("")
  const [models, setModels] = useState<AcpModel[]>([])

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      fetch("/api/agent/models").then(r => r.json()).then(data => {
        if (cancelled) return
        const avail = data.available || []
        if (avail.length > 0) { setModels(avail); setModelState(data.current || "") }
        else setTimeout(poll, 3000)
      }).catch(() => { if (!cancelled) setTimeout(poll, 3000) })
    }
    poll()
    return () => { cancelled = true }
  }, [])

  if (models.length === 0) return null

  return (
    <select
      value={model}
      onChange={async (e) => {
        const v = e.target.value
        setModelState(v)
        sessionStorage.setItem("sdpm-model", v)
        fetch("/api/agent/models", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ modelId: v }),
        }).catch(() => {})
      }}
      className="text-[11px] bg-transparent border border-border rounded px-1.5 py-0.5 text-foreground-muted hover:text-foreground focus:outline-none focus:ring-1 focus:ring-brand-teal max-w-[140px]"
    >
      {models.map(m => <option key={m.modelId} value={m.modelId}>{m.name}</option>)}
    </select>
  )
}
