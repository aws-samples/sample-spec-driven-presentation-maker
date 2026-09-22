// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import { Check, Search, X } from "lucide-react"
import { useLocale, useTranslations } from "next-intl"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { listKiroSessions } from "@/services/kiroSessionsService"
import type { KiroSessionGroup, KiroSessionSummary } from "@/lib/local/kiro-sessions.types"

interface SessionPickerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (session: KiroSessionSummary) => void
}

function relativeTime(value: string, locale: string): string {
  const deltaSeconds = Math.round((new Date(value).getTime() - Date.now()) / 1000)
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "auto" })
  if (Math.abs(deltaSeconds) < 60) return formatter.format(deltaSeconds, "second")
  const minutes = Math.round(deltaSeconds / 60)
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute")
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour")
  return formatter.format(Math.round(hours / 24), "day")
}

export function SessionPickerDialog({ open, onOpenChange, onSelect }: SessionPickerDialogProps) {
  const t = useTranslations("sessionPicker")
  const tCommon = useTranslations("common")
  const locale = useLocale()
  const [query, setQuery] = useState("")
  const [showAll, setShowAll] = useState(false)
  const [groups, setGroups] = useState<KiroSessionGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [activeIndex, setActiveIndex] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const listId = useId()

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    listKiroSessions(showAll, controller.signal)
      .then((data) => setGroups(data.groups))
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) setError(true)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [open, showAll, reloadKey])

  useEffect(() => {
    if (!open) {
      setQuery("")
      setShowAll(false)
      setActiveIndex(0)
    }
  }, [open])

  const filteredGroups = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return groups
    return groups
      .map((group) => ({
        ...group,
        sessions: group.sessions.filter((session) =>
          session.title.toLocaleLowerCase().includes(normalized)
        ),
      }))
      .filter((group) => group.sessions.length > 0)
  }, [groups, query])

  const sessions = useMemo(
    () => filteredGroups.flatMap((group) => group.sessions),
    [filteredGroups]
  )

  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(0, sessions.length - 1)))
  }, [sessions.length])

  const selectActive = useCallback(() => {
    const selected = sessions[activeIndex]
    if (selected) onSelect(selected)
  }, [activeIndex, onSelect, sessions])

  const focusList = () => {
    if (sessions.length === 0) return
    listRef.current?.focus()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="max-h-screen gap-0 overflow-hidden p-0 sm:max-w-xl motion-reduce:animate-none"
        aria-labelledby={`${listId}-title`}
        aria-describedby={`${listId}-description`}
      >
        <DialogClose
          className="absolute right-2 top-2 z-10 flex h-11 w-11 items-center justify-center rounded-lg text-foreground-muted motion-safe:transition-colors hover:bg-background-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
          aria-label={tCommon("close")}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </DialogClose>
        <DialogHeader className="border-b border-border px-5 pb-4 pt-5 pr-12">
          <DialogTitle id={`${listId}-title`}>{t("title")}</DialogTitle>
          <DialogDescription id={`${listId}-description`}>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-3 border-b border-border px-5 py-3">
          <label className="relative min-w-0 flex-1">
            <span className="sr-only">{t("searchPlaceholder")}</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground-muted" />
            <input
              ref={searchRef}
              autoFocus
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault()
                  focusList()
                }
              }}
              placeholder={t("searchPlaceholder")}
              className="h-11 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm outline-none motion-safe:transition-colors placeholder:text-foreground-muted focus:border-brand-teal focus:ring-2 focus:ring-brand-teal/20"
            />
          </label>
          <button
            type="button"
            role="switch"
            aria-checked={showAll}
            onClick={() => setShowAll((value) => !value)}
            className="flex min-h-11 flex-none items-center gap-2 rounded-lg px-2 text-sm text-foreground-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
          >
            <span>{t("showAll")}</span>
            <span className={`relative h-5 w-9 rounded-full motion-safe:transition-colors ${showAll ? "bg-brand-teal" : "bg-foreground/15"}`} aria-hidden="true">
              <span className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow-sm motion-safe:transition-transform ${showAll ? "translate-x-4" : ""}`} />
            </span>
          </button>
        </div>

        <div
          ref={listRef}
          id={`${listId}-listbox`}
          role="listbox"
          aria-label={t("title")}
          aria-activedescendant={sessions[activeIndex] ? `${listId}-option-${activeIndex}` : undefined}
          tabIndex={sessions.length > 0 ? 0 : -1}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault()
              setActiveIndex((index) => Math.min(index + 1, sessions.length - 1))
            } else if (event.key === "ArrowUp") {
              event.preventDefault()
              setActiveIndex((index) => Math.max(index - 1, 0))
            } else if (event.key === "Enter") {
              event.preventDefault()
              selectActive()
            } else if (event.key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
              searchRef.current?.focus()
            }
          }}
          className="min-h-0 flex-1 overflow-y-auto px-3 py-3 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-teal"
        >
          {loading ? (
            <div role="status" aria-live="polite" className="space-y-3 px-2 py-1">
              <span className="sr-only">{t("loading")}</span>
              {[0, 1, 2, 3].map((item) => (
                <div key={item} className="h-16 rounded-lg bg-foreground/5 motion-safe:animate-pulse" />
              ))}
            </div>
          ) : error ? (
            <div role="alert" className="flex min-h-64 flex-col items-center justify-center gap-3 px-6 text-center text-sm text-red-600 dark:text-red-400">
              <p>{t("error")}</p>
              <button
                type="button"
                onClick={() => setReloadKey((key) => key + 1)}
                className="min-h-11 rounded-lg border border-current px-4 font-medium motion-safe:transition-colors hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 dark:hover:bg-red-950"
              >
                {tCommon("retry")}
              </button>
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
              <p className="text-sm font-medium text-foreground">{t("empty")}</p>
              <p className="mt-2 text-sm leading-relaxed text-foreground-muted">{t("emptyHint")}</p>
            </div>
          ) : (
            filteredGroups.map((group) => (
              <section key={group.cwd} role="group" className="mb-4 last:mb-0" aria-label={group.project}>
                <h3 title={group.cwd} className="px-3 pb-1 pt-1 text-xs font-semibold uppercase tracking-wide text-foreground-muted">
                  {group.project}
                </h3>
                <div className="space-y-1">
                  {group.sessions.map((session) => {
                    const index = sessions.indexOf(session)
                    const active = index === activeIndex
                    return (
                      <button
                        key={session.sessionId}
                        id={`${listId}-option-${index}`}
                        type="button"
                        role="option"
                        tabIndex={-1}
                        aria-selected={active}
                        onMouseMove={() => setActiveIndex(index)}
                        onFocus={() => setActiveIndex(index)}
                        onClick={() => onSelect(session)}
                        className={`flex min-h-14 w-full items-center gap-3 rounded-lg px-3 py-2 text-left motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal ${active ? "bg-brand-teal-soft" : "hover:bg-background-hover"}`}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-foreground">{session.title}</span>
                          <span className="mt-0.5 block text-xs text-foreground-muted">
                            {relativeTime(session.updatedAt, locale)} · {t("messages", { count: session.messageCount })}
                          </span>
                        </span>
                        {active && <Check className="h-4 w-4 flex-none text-brand-teal" aria-hidden="true" />}
                      </button>
                    )
                  })}
                </div>
              </section>
            ))
          )}
        </div>

        <div className="border-t border-border px-5 py-3 text-xs text-foreground-muted">
          {t("keyboardHint")}
        </div>
      </DialogContent>
    </Dialog>
  )
}
