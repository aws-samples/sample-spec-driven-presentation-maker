// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * LocalModelPicker — the Local chat's model and effort, above the chat input.
 *
 * A pill with the chat's model (and effort) that opens a menu of the models kiro-cli offers and,
 * for a model with effort levels, those levels. A choice changes this chat's kiro session: at
 * once when it is idle, otherwise from the next message (the menu says so either way). The list
 * comes from the server without starting kiro-cli; until one is known (the first turn of a first
 * run) the pill is not shown. Model names are kiro-cli's.
 */

"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Sparkles } from "lucide-react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  getLocalSessionModels, setLocalSessionModel, type LocalModelChoice, type LocalSessionModels,
} from "@/services/localService"

interface LocalModelPickerProps {
  /** The chat's session id (ChatPanel's). */
  sessionId: string
  /** A new chat before its first message: the pill reads "Default model" until kiro-cli reports one. */
  isNewChat: boolean
  /** A turn runs; the list is read again when it ends. */
  busy: boolean
  disabled?: boolean
}

/** What the pill shows: the chosen model (pending first), its effort and that model's levels. */
function shown(view: LocalSessionModels) {
  const modelId = view.pending?.model ?? view.current?.model ?? null
  const option = modelId ? view.available.find((model) => model.modelId === modelId) : undefined
  const live = view.current && modelId === view.current.model ? view.current : null
  const levels = live ? live.effortLevels : option?.effortLevels ?? []
  const effort = view.pending?.effort ?? (live ? live.effort : option?.defaultEffort ?? null)
  return { modelId, name: option?.name ?? modelId, effort: levels.length ? effort : null, levels }
}

export function LocalModelPicker({ sessionId, isNewChat, busy, disabled = false }: LocalModelPickerProps) {
  const t = useTranslations("chatModel")
  const [view, setView] = useState<LocalSessionModels | null>(null)
  const request = useRef(0)

  const load = useCallback(() => {
    const n = ++request.current
    getLocalSessionModels(sessionId)
      .then((next) => { if (n === request.current) setView(next) })
      .catch(() => { if (n === request.current) setView(null) })
  }, [sessionId])

  useEffect(() => { load() }, [load])

  // The turn's end: kiro-cli may have applied a held choice, or reported the list for the first time.
  const wasBusy = useRef(busy)
  useEffect(() => {
    if (wasBusy.current && !busy) load()
    wasBusy.current = busy
  }, [busy, load])

  const choose = useCallback((choice: LocalModelChoice) => {
    if (!view) return
    const before = view
    const pending = choice.model && choice.model !== view.pending?.model ? { model: choice.model } : { ...view.pending, ...choice }
    setView({ ...view, pending })
    const n = ++request.current
    setLocalSessionModel(sessionId, choice)
      .then((next) => { if (n === request.current && next) setView(next) })
      .catch(() => {
        if (n === request.current) setView(before)
        toast.error(t("errorChange"))
      })
  }, [sessionId, t, view])

  if (!view || !Array.isArray(view.available) || !view.available.length) return null

  const { modelId, name, effort, levels } = shown(view)
  const effortLabel = (level: string) => (t.has(`effortLevel.${level}`) ? t(`effortLevel.${level}`) : level)
  const label = name ?? (isNewChat ? t("defaultModel") : t("chatModel"))
  const ariaLabel = effort ? t("triggerWithEffort", { model: label, effort: effortLabel(effort) }) : t("trigger", { model: label })

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          aria-label={ariaLabel}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-full px-2 text-xs text-foreground-muted hover:text-foreground disabled:opacity-50 disabled:pointer-events-none motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{effort ? `${label} · ${effortLabel(effort)}` : label}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-64 max-h-80 overflow-y-auto">
        <DropdownMenuLabel className="text-xs text-foreground-muted">{t("modelHeading")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={modelId ?? ""}
          onValueChange={(value) => { if (value !== modelId) choose({ model: value }) }}
        >
          {view.available.map((model) => (
            <DropdownMenuRadioItem key={model.modelId} value={model.modelId} className="text-sm">
              <span className="flex flex-col">
                <span>{model.name}</span>
                {model.rate !== undefined && (
                  <span className="text-xs text-foreground-muted">{t("credits", { rate: model.rate })}</span>
                )}
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {levels.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs text-foreground-muted">{t("effortHeading")}</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={effort ?? ""}
              onValueChange={(value) => { if (value !== effort) choose({ effort: value }) }}
            >
              {levels.map((level) => (
                <DropdownMenuRadioItem key={level} value={level} className="text-sm">
                  {effortLabel(level)}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </>
        )}
        <DropdownMenuSeparator />
        <p className="px-2 py-1.5 text-xs text-foreground-muted">{t("appliesNextMessage")}</p>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
