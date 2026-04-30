// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import * as RadioGroupPrimitive from "@radix-ui/react-radio-group"
import { usePreferences } from "@/hooks/usePreferences"
import { getAllowedModels, getDefaultModelId } from "@/lib/allowedModels"
import { toast } from "sonner"
import { Check, Star } from "lucide-react"
import { useEffect, useMemo } from "react"

interface SettingsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function Settings({ open, onOpenChange }: SettingsProps) {
  const { sendWithEnter, setSendWithEnter, modelId, setModelId } = usePreferences()
  const allowed = useMemo(() => getAllowedModels(), [])
  const defaultId = useMemo(() => getDefaultModelId(), [])

  // Silently drop stale modelId (admin may have removed it from config).
  useEffect(() => {
    if (modelId && allowed.length > 0 && !allowed.some((m) => m.modelId === modelId)) {
      setModelId(undefined)
    }
  }, [modelId, allowed, setModelId])

  const selectedId = modelId ?? defaultId

  const onPick = (value: string) => {
    const m = allowed.find((a) => a.modelId === value)
    if (!m) return
    setModelId(m.modelId)
    toast.success(`Model changed to ${m.displayName}`)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[400px] sm:w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Settings</SheetTitle>
        </SheetHeader>

        {allowed.length > 0 && (
          <section aria-labelledby="model-heading" className="mt-2 px-4">
            <h3 id="model-heading" className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Model
            </h3>
            <p className="text-xs text-muted-foreground/70 mt-1 mb-3">
              Choose which AI model generates your slides.
            </p>
            <RadioGroupPrimitive.Root
              value={selectedId}
              onValueChange={onPick}
              aria-label="Select AI model"
              className="space-y-1.5"
            >
              {allowed.map((m) => {
                const isSelected = selectedId === m.modelId
                const isDefault = m.modelId === defaultId
                return (
                  <RadioGroupPrimitive.Item
                    key={m.modelId}
                    value={m.modelId}
                    className={[
                      "group w-full text-left rounded-lg border p-3 outline-none",
                      "motion-safe:transition-[border-color,background-color] motion-safe:duration-150",
                      "focus-visible:ring-2 focus-visible:ring-brand-teal/40 focus-visible:ring-offset-1 focus-visible:ring-offset-background",
                      isSelected
                        ? "border-brand-teal/60 bg-brand-teal-soft"
                        : "border-white/[0.06] hover:border-white/[0.12] hover:bg-white/[0.03]",
                    ].join(" ")}
                  >
                    <div className="flex items-start gap-3">
                      {/* Radio indicator */}
                      <span
                        aria-hidden="true"
                        className={[
                          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                          "motion-safe:transition-colors motion-safe:duration-150",
                          isSelected
                            ? "border-brand-teal bg-brand-teal"
                            : "border-white/20 group-hover:border-white/30",
                        ].join(" ")}
                      >
                        {isSelected && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
                      </span>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-foreground">{m.displayName}</span>
                          {isDefault && (
                            <span
                              className="inline-flex items-center gap-0.5 rounded-full bg-brand-teal/10 px-1.5 py-px text-[10px] font-medium text-brand-teal"
                              aria-label="Recommended"
                            >
                              <Star className="h-2.5 w-2.5" />
                              Recommended
                            </span>
                          )}
                        </div>
                        {m.description && (
                          <p className="text-xs text-muted-foreground/70 mt-0.5 leading-relaxed">{m.description}</p>
                        )}
                      </div>
                    </div>
                  </RadioGroupPrimitive.Item>
                )
              })}
            </RadioGroupPrimitive.Root>
          </section>
        )}

        <section aria-labelledby="chat-heading" className="mt-8 px-4">
          <h3 id="chat-heading" className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Chat behavior
          </h3>
          <button
            role="switch"
            aria-checked={sendWithEnter}
            onClick={() => setSendWithEnter(!sendWithEnter)}
            className="w-full flex items-center justify-between mt-3 py-1.5 text-sm text-foreground/80 hover:text-foreground motion-safe:transition-colors motion-safe:duration-150"
          >
            <span>Send with Enter</span>
            <span
              aria-hidden="true"
              className={[
                "relative w-8 h-[18px] rounded-full flex items-center px-0.5",
                "motion-safe:transition-colors motion-safe:duration-200",
                sendWithEnter ? "bg-brand-teal justify-end" : "bg-white/10 justify-start",
              ].join(" ")}
            >
              <span className="w-3.5 h-3.5 rounded-full bg-white shadow-sm motion-safe:transition-all motion-safe:duration-200" />
            </span>
          </button>
        </section>
      </SheetContent>
    </Sheet>
  )
}
