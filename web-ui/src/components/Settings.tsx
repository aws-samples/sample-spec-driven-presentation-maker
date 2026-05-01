// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Switch } from "@/components/ui/switch"
import { ModelPicker } from "@/components/ModelPicker"
import { usePreferences } from "@/hooks/usePreferences"
import { getAllowedModels, getDefaultChatModelId, getDefaultCreateModelId } from "@/lib/allowedModels"
import { toast } from "sonner"
import { useEffect, useMemo } from "react"

interface SettingsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function Settings({ open, onOpenChange }: SettingsProps) {
  const {
    sendWithEnter,
    setSendWithEnter,
    chatModelId,
    setChatModelId,
    createModelId,
    setCreateModelId,
  } = usePreferences()
  const allowed = useMemo(() => getAllowedModels(), [])
  const composable = useMemo(() => allowed.filter((m) => m.composable !== false), [allowed])
  const defaultChatId = useMemo(() => getDefaultChatModelId(), [])
  const defaultCreateId = useMemo(() => getDefaultCreateModelId(), [])

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
          <SheetTitle className="text-lg">Settings</SheetTitle>
        </SheetHeader>

        <div className="flex flex-col gap-4 px-5 pb-6 overflow-y-auto flex-1 min-h-0">
          {/* ── Models (per-agent) ── */}
          {allowed.length > 0 && (
            <section
              aria-labelledby="model-heading"
              className="rounded-xl border border-white/[0.06] bg-card/40 p-4"
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
                  <p className="mt-1 text-[11px] text-muted-foreground/80">
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
                  <p className="mt-1 text-[11px] text-muted-foreground/80">
                    Slides, styles, and other artifacts. Needs a capable model.
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* ── Chat ── */}
          <section
            aria-labelledby="chat-heading"
            className="rounded-xl border border-white/[0.06] bg-card/40 p-4"
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
