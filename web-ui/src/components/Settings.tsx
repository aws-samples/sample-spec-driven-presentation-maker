// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Switch } from "@/components/ui/switch"
import { ModelPicker } from "@/components/ModelPicker"
import { usePreferences } from "@/hooks/usePreferences"
import { getAllowedModels, getDefaultChatModelId, getDefaultCreateModelId } from "@/lib/allowedModels"
import { IS_LOCAL } from "@/lib/mode"
import { toast } from "sonner"
import { notifyError } from "@/lib/errors"
import { useLocale, type Locale } from "@/i18n/LocaleProvider"
import { useTranslations } from "next-intl"
import { useTheme } from "next-themes"
import { useEffect, useMemo, useState, useCallback } from "react"
import type { TextScale } from "@/hooks/usePreferences"

interface SettingsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function Settings({ open, onOpenChange }: SettingsProps) {
  const t = useTranslations("settings")
  const { locale, setLocale } = useLocale()
  const {
    sendWithEnter,
    setSendWithEnter,
    chatModelId,
    setChatModelId,
    createModelId,
    setCreateModelId,
    textScale,
    setTextScale,
  } = usePreferences()
  const { theme, setTheme } = useTheme()
  const allowed = useMemo(() => getAllowedModels(), [])
  const composable = useMemo(() => allowed.filter((m) => m.composable !== false), [allowed])
  const defaultChatId = useMemo(() => getDefaultChatModelId(), [])
  const defaultCreateId = useMemo(() => getDefaultCreateModelId(), [])

  // ── Local: agent definition selection ──
  interface AgentDef { fileName: string; name: string; description: string }
  interface AgentSelection { spec: string; vibe: string; composer: string; single: string; model?: string }
  const [agentDefs, setAgentDefs] = useState<AgentDef[]>([])
  const [agentSelection, setAgentSelection] = useState<AgentSelection>({ spec: "", vibe: "", composer: "", single: "" })
  const [localModels, setLocalModels] = useState<{ modelId: string; displayName: string; description?: string }[]>([])

  useEffect(() => {
    if (!IS_LOCAL || !open) return
    fetch("/api/agent/definitions").then((r) => r.json()).then((d) => {
      setAgentDefs(d.agents || [])
      setAgentSelection(d.selection || {})
    }).catch((err) => notifyError("Failed to load agent definitions", err))
    fetch("/api/agent/models").then((r) => r.json()).then((d) => {
      setLocalModels((d.available || []).map((m: { modelId: string; name: string; description?: string }) => ({
        modelId: m.modelId, displayName: m.name, description: m.description,
      })))
    }).catch((err) => notifyError("Failed to load model list", err))
  }, [open])

  const onAgentChange = useCallback((role: keyof AgentSelection, fileName: string) => {
    const prev = { ...agentSelection }
    const next = { ...agentSelection, [role]: fileName }
    setAgentSelection(next)
    const def = agentDefs.find((a) => a.fileName === fileName)
    fetch("/api/agent/definitions", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [role]: fileName }),
    }).then((r) => {
      if (!r.ok) throw new Error()
      toast.success(`${role} agent updated`, {
        description: `Now using ${def?.name || fileName}. Takes effect on next chat — current chat is not affected.`,
      })
    }).catch(() => {
      setAgentSelection(prev)
      toast.error(`Failed to update ${role} agent`)
    })
  }, [agentSelection, agentDefs])

  const onLocalModelChange = useCallback((modelId: string | undefined) => {
    const prev = { ...agentSelection }
    const next = { ...agentSelection, model: modelId }
    setAgentSelection(next)
    fetch("/api/agent/definitions", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: modelId || null }),
    }).then((r) => {
      if (!r.ok) throw new Error()
      const m = localModels.find((a) => a.modelId === modelId)
      toast.success(m ? `Model: ${m.displayName}` : "Model: default", {
        description: "Takes effect on next chat.",
      })
    }).catch(() => {
      setAgentSelection(prev)
      toast.error("Failed to update model")
    })
  }, [agentSelection, localModels])

  // Silently drop stale selections (admin may have removed the model from config).
  useEffect(() => {
    if (chatModelId && allowed.length > 0 && !allowed.some((m) => m.modelId === chatModelId)) {
      setChatModelId(undefined)
    }
    if (createModelId && composable.length > 0 && !composable.some((m) => m.modelId === createModelId)) {
      setCreateModelId(undefined)
    }
  }, [chatModelId, createModelId, allowed, composable, setChatModelId, setCreateModelId])

  const onChatChange = (id: string | undefined) => {
    setChatModelId(id)
    const m = id ? allowed.find((a) => a.modelId === id) : undefined
    toast.success(m ? `Chat: ${m.displayName}` : "Chat: default")
  }

  const onCreateChange = (id: string | undefined) => {
    setCreateModelId(id)
    if (id === undefined) {
      toast.success("Create: default")
    } else {
      const m = composable.find((a) => a.modelId === id)
      if (m) toast.success(`Create: ${m.displayName}`)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[400px] sm:w-[460px] p-0 flex flex-col">
        <SheetHeader className="px-5 pt-5 pb-3 shrink-0">
          <SheetTitle className="text-lg">{t("title")}</SheetTitle>
        </SheetHeader>

        <div className="flex flex-col gap-4 px-5 pb-6 overflow-y-auto flex-1 min-h-0">
          {/* ── Agents (Local only) ── */}
          {IS_LOCAL && agentDefs.length > 0 && (
            <section
              aria-labelledby="agent-heading"
              className="rounded-xl border border-border bg-card/40 p-4"
            >
              <div className="mb-3">
                <h3
                  id="agent-heading"
                  className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  Agents
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Choose which agent definition each role uses.
                </p>
              </div>
              <div className="flex flex-col gap-3">
                {(["spec", "vibe", "composer", "single"] as const).map((role) => {
                  const models = agentDefs.map((a) => ({
                    modelId: a.fileName,
                    displayName: a.name,
                    description: a.description,
                  }))
                  return (
                    <div key={role}>
                      <label
                        htmlFor={`agent-${role}`}
                        className="mb-1.5 block text-xs font-medium text-foreground capitalize"
                      >
                        {role}
                      </label>
                      <ModelPicker
                        models={models}
                        value={agentSelection[role] || undefined}
                        onChange={(id) => id && onAgentChange(role, id)}
                        triggerId={`agent-${role}`}
                        ariaLabel={`Select ${role} agent`}
                      />
                    </div>
                  )
                })}
                {localModels.length > 0 && (
                  <div>
                    <label
                      htmlFor="agent-model"
                      className="mb-1.5 block text-xs font-medium text-foreground"
                    >
                      Model
                    </label>
                    <ModelPicker
                      models={localModels}
                      value={agentSelection.model || undefined}
                      onChange={onLocalModelChange}
                      inheritLabel="Default"
                      triggerId="agent-model"
                      ariaLabel="Select agent model"
                    />
                  </div>
                )}
              </div>
            </section>
          )}

          {/* ── Models (per-agent) ── */}
          {allowed.length > 0 && (
            <section
              aria-labelledby="model-heading"
              className="rounded-xl border border-border bg-card/40 p-4"
            >
              <div className="mb-3">
                <h3
                  id="model-heading"
                  className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  Models
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Choose which AI model each task uses.
                </p>
              </div>

              <div className="flex flex-col gap-3">
                {/* Chat */}
                <div>
                  <label
                    htmlFor="chat-model"
                    className="mb-1.5 block text-xs font-medium text-foreground"
                  >
                    Chat
                  </label>
                  <ModelPicker
                    models={allowed}
                    value={chatModelId}
                    onChange={onChatChange}
                    defaultId={defaultChatId}
                    triggerId="chat-model"
                    ariaLabel="Select chat model"
                  />
                  <p className="mt-1 text-xs text-muted-foreground/80">
                    Conversations and planning.
                  </p>
                </div>

                {/* Create */}
                <div>
                  <label
                    htmlFor="create-model"
                    className="mb-1.5 block text-xs font-medium text-foreground"
                  >
                    Create
                  </label>
                  <ModelPicker
                    models={composable}
                    value={createModelId}
                    onChange={onCreateChange}
                    defaultId={defaultCreateId}
                    triggerId="create-model"
                    ariaLabel="Select create model"
                  />
                  <p className="mt-1 text-xs text-muted-foreground/80">
                    Slides, styles, and other artifacts. Needs a capable model.
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* ── Appearance ── */}
          <section
            aria-labelledby="appearance-heading"
            className="rounded-xl border border-border bg-card/40 p-4"
          >
            <div className="mb-4">
              <h3
                id="appearance-heading"
                className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
              >
                {t("appearance")}
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("appearanceDescription")}
              </p>
            </div>

            <div className="space-y-4">
              <div>
                <p id="theme-label" className="mb-2 text-sm font-medium text-foreground">
                  {t("theme")}
                </p>
                <div role="radiogroup" aria-labelledby="theme-label" className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
                  {(["light", "dark", "system"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={theme === value}
                      onClick={() => setTheme(value)}
                      className={`min-h-11 rounded-md px-2 text-xs font-semibold transition-[background-color,color,box-shadow] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                        theme === value
                          ? "bg-background-raised text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {t(value === "light" ? "themeLight" : value === "dark" ? "themeDark" : "themeSystem")}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="mb-2">
                  <p id="text-scale-label" className="text-sm font-medium text-foreground">
                    {t("textSize")}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {t("textSizeDescription")}
                  </p>
                </div>
                <div role="radiogroup" aria-labelledby="text-scale-label" className="grid grid-cols-4 gap-1 rounded-lg bg-muted p-1">
                  {([90, 100, 110, 125] as TextScale[]).map((scale) => (
                    <button
                      key={scale}
                      type="button"
                      role="radio"
                      aria-label={t("textScaleLabel", { scale })}
                      aria-checked={textScale === scale}
                      onClick={() => setTextScale(scale)}
                      className={`min-h-11 rounded-md px-1 text-xs font-semibold transition-[background-color,color,box-shadow] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                        textScale === scale
                          ? "bg-background-raised text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {scale}%
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          {/* ── Language ── */}
          <section
            aria-labelledby="language-heading"
            className="rounded-xl border border-border bg-card/40 p-4"
          >
            <div className="mb-3">
              <h3
                id="language-heading"
                className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
              >
                {t("language")}
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("languageDescription")}
              </p>
            </div>
            <div role="radiogroup" aria-labelledby="language-heading" className="flex gap-2">
              {([["en", "English"], ["ja", "日本語"]] as [Locale, string][]).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={locale === value}
                  onClick={() => setLocale(value)}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                    locale === value
                      ? "border-primary/50 bg-primary/10 text-foreground"
                      : "border-border bg-card/40 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          {/* ── Chat ── */}
          <section
            aria-labelledby="chat-heading"
            className="rounded-xl border border-border bg-card/40 p-4"
          >
            <h3
              id="chat-heading"
              className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3"
            >
              Chat
            </h3>
            <label
              htmlFor="send-with-enter"
              className="flex items-center justify-between gap-4 cursor-pointer"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-foreground">Send with Enter</div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  Press Enter to send. Shift+Enter for a new line.
                </div>
              </div>
              <Switch
                id="send-with-enter"
                checked={sendWithEnter}
                onCheckedChange={setSendWithEnter}
              />
            </label>
          </section>
        </div>
      </SheetContent>
    </Sheet>
  )
}
