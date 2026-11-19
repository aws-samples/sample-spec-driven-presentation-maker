// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ChoiceChip — a style or template choice in the composer's footer row on the initial chat
 * screen. Dashed while nothing is chosen (the agent picks); solid with the name once chosen.
 *
 * Holds no state of its own: the choice is the input's first `@style:` / `@template:` token,
 * so a choice made with `/` or removed by hand shows here too. Opening it shows a gallery —
 * a cover preview per style, the theme per template — with search and an "agent picks" card.
 */

"use client"

import { useMemo, useState } from "react"
import { Popover } from "radix-ui"
import { LayoutTemplate, Palette, Search, X } from "lucide-react"
import { useTranslations } from "next-intl"
import { gridMove } from "@/lib/gridNav"
import { setKindToken, tokenName, type PickerItem } from "@/lib/slashToken"
import { AutoCard, ChoiceCard } from "./ChoiceGallery"

type ChoiceKind = "style" | "template"

interface ChoiceChipProps {
  kind: ChoiceKind
  /** Current chat input text. */
  text: string
  /** Replace the chat input with the changed text. */
  onChange: (next: string) => void
  /** Catalogue (styles and templates; other kinds are ignored). */
  items: PickerItem[]
  loading: boolean
  /** Load the catalogue (called when the gallery opens). */
  onOpen: () => void
}

/** Gallery columns (desktop); arrow keys move by a row. */
const COLS = 3

export function ChoiceChip({ kind, text, onChange, items, loading, onOpen }: ChoiceChipProps) {
  const t = useTranslations("choiceChip")
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const [byKey, setByKey] = useState(false)
  const current = tokenName(text, kind)
  const Icon = kind === "style" ? Palette : LayoutTemplate
  const K = kind === "style" ? "Style" : "Template"

  const candidates = useMemo(() => {
    const q = query.trim().toLowerCase()
    return items
      .filter((item) => item.kind === kind)
      .filter((item) => !q || item.name.toLowerCase().includes(q) || item.description.toLowerCase().includes(q))
      .sort((a, b) => Number(b.pinned) - Number(a.pinned))
  }, [items, kind, query])
  // Index 0 is "agent picks"; the cards follow.
  const count = candidates.length + 1

  const choose = (name: string | null) => {
    onChange(setKindToken(text, kind, name))
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    const next = gridMove([count], active, e.key, COLS)
    if (next !== null) {
      e.preventDefault()
      setByKey(true)
      setActive(next)
    } else if (e.key === "Enter") {
      e.preventDefault()
      choose(active === 0 ? null : candidates[active - 1]?.name ?? null)
    }
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          onOpen()
          setQuery("")
          const at = current ? candidates.findIndex((c) => c.name === current) : -1
          setActive(at >= 0 ? at + 1 : 0)
        }
      }}
    >
      <span className={`inline-flex h-8 items-center rounded-full border text-sm motion-safe:transition-colors ${
        current
          ? "border-border-hover text-foreground"
          : "border-dashed border-border-hover text-foreground-muted hover:text-foreground-secondary"
      }`}>
        <Popover.Trigger asChild>
          <button
            type="button"
            aria-label={current ? t("chosen", { kind: t(kind), name: current }) : t(`choose${K}`)}
            className={`inline-flex h-full min-w-0 items-center gap-1.5 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal ${current ? "pl-3 pr-1" : "px-3"}`}
          >
            <Icon className="h-3.5 w-3.5 flex-none" aria-hidden="true" />
            <span className={current ? "max-w-[160px] truncate font-medium" : ""}>{current ?? t(kind)}</span>
          </button>
        </Popover.Trigger>
        {current && (
          <button
            type="button"
            onClick={() => choose(null)}
            aria-label={t(`clear${K}`)}
            className="mr-1 grid h-6 w-6 place-items-center rounded-full text-foreground-muted hover:bg-background-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
          >
            <X className="h-3 w-3" aria-hidden="true" />
          </button>
        )}
      </span>

      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="start"
          sideOffset={8}
          collisionPadding={12}
          onKeyDown={onKeyDown}
          className="z-50 flex max-h-[min(480px,var(--radix-popover-content-available-height))] w-[720px] max-w-[calc(100vw-24px)] flex-col overflow-hidden rounded-2xl border border-border-hover bg-popover shadow-[var(--shadow-float)] motion-safe:animate-[slash-pop-in_160ms_ease-out]"
        >
          <div className="flex flex-none items-center gap-2 border-b border-border px-3 py-2">
            <Search className="h-4 w-4 flex-none text-foreground-muted" aria-hidden="true" />
            <input
              autoFocus
              value={query}
              onChange={(e) => { setQuery(e.target.value); setActive(0) }}
              placeholder={t(`search${K}`)}
              aria-label={t(`search${K}`)}
              className="h-8 min-w-0 flex-1 bg-transparent text-sm focus:outline-none placeholder:text-foreground-muted"
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
          <div role="listbox" aria-label={t(kind)} className="grid grid-cols-2 gap-2.5 p-3 sm:grid-cols-3">
            <AutoCard
              selected={!current}
              ariaSelected={!current}
              active={active === 0}
              scrollOnActive={byKey}
              onHover={() => { setByKey(false); setActive(0) }}
              onChoose={() => choose(null)}
            />
            {loading && candidates.length === 0 && (
              <p className="col-span-full px-1 py-2 text-sm text-foreground-muted">{t("loading")}</p>
            )}
            {!loading && candidates.length === 0 && (
              <p className="col-span-full px-1 py-2 text-sm text-foreground-muted">{t("noMatch")}</p>
            )}
            {candidates.map((item, i) => (
              <ChoiceCard
                key={`${item.kind}-${item.name}`}
                item={item}
                selected={item.name === current}
                ariaSelected={item.name === current}
                active={active === i + 1}
                scrollOnActive={byKey}
                onHover={() => { setByKey(false); setActive(i + 1) }}
                onChoose={() => choose(item.name)}
              />
            ))}
          </div>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
