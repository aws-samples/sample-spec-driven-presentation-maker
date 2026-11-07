// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

/**
 * Settings → Agent engine (Local only): which kiro-cli engine runs the sdpm agents. Read when the
 * sheet opens; a choice is saved at once and takes effect from the next message. A failed save
 * puts the previous choice back. Rendered on its own, not inside the Agents section, so it is
 * there even when the agent definitions cannot be listed.
 */

import { notifyError } from "@/lib/errors"
import { getAgentEngine, setAgentEngine, type AgentEngine } from "@/services/localService"
import { useTranslations } from "next-intl"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"

const ENGINES: { value: AgentEngine; label: string; description: string }[] = [
  { value: "v3", label: "agentEngineV3", description: "agentEngineV3Description" },
  { value: "v2", label: "agentEngineV2", description: "agentEngineV2Description" },
]

export function LocalEngineSetting({ open }: { open: boolean }) {
  const t = useTranslations("settings")
  const [engine, setEngine] = useState<AgentEngine | null>(null)

  useEffect(() => {
    if (!open) return
    getAgentEngine()
      .then((current) => { if (current) setEngine(current.engine) })
      .catch((err) => notifyError(t("errorLoadAgentEngine"), err))
  }, [open, t])

  const choose = useCallback((next: AgentEngine) => {
    if (next === engine) return
    const previous = engine
    setEngine(next)
    const label = t(ENGINES.find((e) => e.value === next)!.label)
    setAgentEngine(next).then(() => {
      toast.success(t("agentEngineUpdated", { engine: label }), { description: t("agentEngineUpdatedDescription") })
    }).catch(() => {
      setEngine(previous)
      toast.error(t("errorUpdateAgentEngine"))
    })
  }, [engine, t])

  return (
    <section aria-labelledby="agent-engine-heading" className="rounded-xl border border-border bg-card/40 p-4">
      <div className="mb-3">
        <h3 id="agent-engine-heading" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {t("agentEngine")}
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">{t("agentEngineDescription")}</p>
      </div>
      <div role="radiogroup" aria-labelledby="agent-engine-heading" className="flex flex-col gap-2">
        {ENGINES.map(({ value, label, description }) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={engine === value}
            onClick={() => choose(value)}
            className={`rounded-lg border px-3 py-2 text-left transition-colors ${
              engine === value
                ? "border-primary/50 bg-primary/10 text-foreground"
                : "border-border bg-card/40 text-muted-foreground hover:text-foreground"
            }`}
          >
            <span className="block text-sm font-medium">{t(label)}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">{t(description)}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
