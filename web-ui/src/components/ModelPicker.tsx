// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import * as React from "react"
import { Check, ChevronsUpDown, Sparkles } from "lucide-react"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import type { AllowedModel } from "@/lib/allowedModels"
import { cn } from "@/lib/utils"

interface ModelPickerProps {
  models: AllowedModel[]
  value: string | undefined
  onChange: (modelId: string | undefined) => void
  defaultId?: string
  inheritLabel?: string
  triggerId?: string
  ariaLabel?: string
}

/**
 * ModelPicker — Inline collapsible combobox for selecting an AI model.
 *
 * Instead of a Popover/Portal (which fights with Sheet overflow),
 * the command list expands inline below the trigger button.
 * The parent Sheet's overflow-y-auto handles scrolling naturally.
 */
export function ModelPicker({
  models,
  value,
  onChange,
  defaultId,
  inheritLabel,
  triggerId,
  ariaLabel,
}: ModelPickerProps) {
  const [open, setOpen] = React.useState(false)
  const listRef = React.useRef<HTMLDivElement>(null)

  const selected = value ? models.find((m) => m.modelId === value) : undefined
  const isInherit = inheritLabel !== undefined && value === undefined

  const displayName = isInherit
    ? inheritLabel
    : selected?.displayName ??
      (defaultId
        ? models.find((m) => m.modelId === defaultId)?.displayName ?? "Select model"
        : "Select model")

  // Scroll the expanded list into view after opening
  React.useEffect(() => {
    if (open && listRef.current) {
      // Small delay to let the DOM render
      requestAnimationFrame(() => {
        listRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
      })
    }
  }, [open])

  const listId = triggerId ? `${triggerId}-list` : undefined

  return (
    <div>
      {/* Trigger button */}
      <button
        id={triggerId}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={ariaLabel}
        onClick={() => setOpen((prev) => !prev)}
        className={cn(
          "group w-full flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left",
          "border-white/[0.1] bg-background/30 hover:bg-background/60 hover:border-white/[0.2]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal/40",
          "motion-safe:transition-colors motion-safe:duration-150",
          open && "border-brand-teal/50 bg-background/70",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span
            className={cn(
              "truncate text-sm font-medium",
              isInherit ? "text-muted-foreground italic" : "text-foreground",
            )}
          >
            {displayName}
          </span>
          {selected && selected.modelId === defaultId && (
            <span
              aria-label="Recommended"
              className="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-brand-teal/15 px-1.5 py-px text-[11px] font-semibold text-brand-teal"
            >
              <Sparkles className="h-2.5 w-2.5" />
              Recommended
            </span>
          )}
        </span>
        <ChevronsUpDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground/60 motion-safe:transition-transform motion-safe:duration-150",
            open && "rotate-180",
          )}
        />
      </button>

      {/* Inline expandable list */}
      {open && (
        <div
          ref={listRef}
          className="mt-1.5 rounded-lg border border-white/[0.1] bg-popover overflow-hidden"
        >
          <Command>
            <CommandInput placeholder="Search models..." />
            <CommandList id={listId} className="max-h-[280px] overflow-y-auto">
              <CommandEmpty>No model found.</CommandEmpty>
              <CommandGroup>
                {inheritLabel !== undefined && (
                  <CommandItem
                    value="__inherit__"
                    keywords={["inherit", "main", "default", "same"]}
                    onSelect={() => {
                      onChange(undefined)
                      setOpen(false)
                    }}
                    className="gap-3"
                  >
                    <Check
                      className={cn(
                        "size-4",
                        isInherit ? "opacity-100 text-brand-teal" : "opacity-0",
                      )}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm italic text-muted-foreground">
                        {inheritLabel}
                      </div>
                    </div>
                  </CommandItem>
                )}
                {models.map((m) => {
                  const isSelected = !isInherit && value === m.modelId
                  const isDefault = m.modelId === defaultId
                  return (
                    <CommandItem
                      key={m.modelId}
                      value={m.modelId}
                      keywords={[m.displayName, m.description ?? ""]}
                      onSelect={(v) => {
                        onChange(v)
                        setOpen(false)
                      }}
                      className="gap-3 py-2"
                    >
                      <Check
                        className={cn(
                          "size-4",
                          isSelected ? "opacity-100 text-brand-teal" : "opacity-0",
                        )}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-medium text-foreground">
                            {m.displayName}
                          </span>
                          {isDefault && (
                            <span
                              aria-label="Recommended"
                              className="inline-flex items-center gap-0.5 rounded-full bg-brand-teal/15 px-1.5 py-px text-[11px] font-semibold text-brand-teal"
                            >
                              <Sparkles className="h-2.5 w-2.5" />
                              Recommended
                            </span>
                          )}
                        </div>
                        {m.description && (
                          <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                            {m.description}
                          </p>
                        )}
                      </div>
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </div>
      )}
    </div>
  )
}
