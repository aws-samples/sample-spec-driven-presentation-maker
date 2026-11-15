// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SteerQueue — the messages sent while the agent works that it has not read yet, as cards
 * stacked above the input in sent order (useChatStream `steerQueue`).
 *
 * A card shows the typed text (two lines at most), its files, snippets and review comments,
 * and its state: sending, waiting for the agent's next step, or not delivered. A not-delivered
 * card offers "back to input" (when it has text) and dismiss. Once the agent reads a steer it
 * leaves the queue and becomes a user message in the chat.
 */

"use client"

import { useMemo } from "react"
import { useTranslations } from "next-intl"
import { AlertCircle, Clock, CornerDownLeft, Loader2, X } from "lucide-react"
import type { QueuedSteer } from "@/hooks/useChatStream"
import { parseReviewMessage } from "@/lib/review/marker"
import { cn } from "@/lib/utils"

interface SteerQueueProps {
  steers: QueuedSteer[]
  /** Put a not-delivered steer's text back into the input (the panel then dismisses it). */
  onBackToInput: (steer: QueuedSteer, text: string) => void
  onDismiss: (id: string) => void
}

export function SteerQueue({ steers, onBackToInput, onDismiss }: SteerQueueProps) {
  const t = useTranslations("chat")
  if (steers.length === 0) return null
  return (
    <section aria-label={t("steerQueue")} className="flex-none px-4 pb-2">
      <ul aria-live="polite" className="flex max-h-44 flex-col gap-1.5 overflow-y-auto">
        {steers.map((steer) => (
          <SteerCard key={steer.id} steer={steer} onBackToInput={onBackToInput} onDismiss={onDismiss} />
        ))}
      </ul>
    </section>
  )
}

function SteerCard({ steer, onBackToInput, onDismiss }: { steer: QueuedSteer } & Omit<SteerQueueProps, "steers">) {
  const t = useTranslations("chat")
  const review = useMemo(() => parseReviewMessage(steer.display), [steer.display])
  // A change request shows its note; the input gets back what was typed (the note).
  const text = review ? (review.note ?? "") : steer.inputText
  const notDelivered = steer.state === "notDelivered"
  const meta = [
    ...(steer.attachments?.length ? [t("steerFiles", { count: steer.attachments.length })] : []),
    ...(steer.snippets?.length ? [t("steerSnippets", { count: steer.snippets.length })] : []),
    ...(review ? [t("steerComments", { count: review.comments.length })] : []),
  ]
  const status = steer.state === "sending" ? t("steerSending") : steer.state === "waiting" ? t("steerWaiting") : t("steerNotDelivered")
  return (
    <li
      data-state={steer.state}
      className={cn(
        "msg-user-enter flex items-start gap-2.5 rounded-xl border px-3 py-2",
        notDelivered ? "border-destructive/30 bg-destructive/5" : "border-dashed border-brand-teal/30 bg-brand-teal-soft/40",
      )}
    >
      <span className="mt-0.5 flex h-4 w-4 flex-none items-center justify-center" aria-hidden="true">
        {steer.state === "sending" ? (
          <Loader2 className="h-3.5 w-3.5 text-foreground-muted motion-safe:animate-spin" />
        ) : steer.state === "waiting" ? (
          <Clock className="h-3.5 w-3.5 text-brand-teal" />
        ) : (
          <AlertCircle className="h-3.5 w-3.5 text-destructive" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        {text.trim() && <p className="line-clamp-2 whitespace-pre-wrap break-words text-sm text-foreground">{text}</p>}
        <p className="mt-0.5 text-xs text-foreground-muted">
          {[status, ...meta].join(" · ")}
        </p>
        {notDelivered && text.trim() && (
          <button
            type="button"
            onClick={() => onBackToInput(steer, text)}
            className="-ml-2 mt-1 inline-flex min-h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-brand-teal motion-safe:transition-colors hover:bg-brand-teal-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
          >
            <CornerDownLeft className="h-3.5 w-3.5" aria-hidden="true" />
            {t("steerBackToInput")}
          </button>
        )}
      </div>
      {notDelivered && (
        <button
          type="button"
          onClick={() => onDismiss(steer.id)}
          aria-label={t("steerDismiss")}
          title={t("steerDismiss")}
          className="-mr-1.5 -mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-lg text-foreground-muted motion-safe:transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      )}
    </li>
  )
}
