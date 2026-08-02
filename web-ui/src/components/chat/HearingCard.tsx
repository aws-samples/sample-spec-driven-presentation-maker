// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { useState } from "react"
import { Lightbulb, Send } from "lucide-react"
import { useTranslations } from "next-intl"

interface Question {
  id: string
  type: "single_select" | "multi_select" | "free_text"
  text: string
  options?: string[]
  recommended?: string | string[]
  placeholder?: string
}

interface HearingCardProps {
  inference: string
  questions: Question[]
  disabled?: boolean
  onSubmit: (text: string) => void
}

function isRecommended(option: string, rec?: string | string[]): boolean {
  if (!rec) return false
  return Array.isArray(rec) ? rec.includes(option) : rec === option
}

interface Answers {
  selections: Record<string, string | string[]>
  notes: Record<string, string>
}

function formatAnswers(questions: Question[], answers: Answers): string {
  return questions
    .map((q) => {
      const sel = answers.selections[q.id]
      const note = answers.notes[q.id]?.trim()
      const selText = sel ? (Array.isArray(sel) ? sel.join(", ") : sel) : ""
      if (!selText && !note) return null
      if (selText && note) return `${q.text}: ${selText} (${note})`
      if (selText) return `${q.text}: ${selText}`
      return `${q.text}: ${note}`
    })
    .filter(Boolean)
    .join("\n")
}

export function HearingCard({ inference, questions, disabled = false, onSubmit }: HearingCardProps) {
  const t = useTranslations("hearing")
  const [answers, setAnswers] = useState<Answers>({ selections: {}, notes: {} })
  const [submitted, setSubmitted] = useState(false)

  const toggleSingle = (id: string, value: string) =>
    setAnswers((p) => ({
      ...p,
      selections: { ...p.selections, [id]: p.selections[id] === value ? "" : value },
    }))

  const toggleMulti = (id: string, value: string) =>
    setAnswers((p) => {
      const cur = (p.selections[id] as string[]) || []
      return {
        ...p,
        selections: { ...p.selections, [id]: cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value] },
      }
    })

  const setNote = (id: string, value: string) =>
    setAnswers((p) => ({ ...p, notes: { ...p.notes, [id]: value } }))

  const setText = (id: string, value: string) =>
    setAnswers((p) => ({ ...p, selections: { ...p.selections, [id]: value } }))

  const handleSubmit = () => {
    const text = formatAnswers(questions, answers)
    if (text) {
      setSubmitted(true)
      onSubmit(text)
    }
  }

  const hasAnswer = questions.some((q) => {
    const sel = answers.selections[q.id]
    const note = answers.notes[q.id]?.trim()
    return note || (sel && (typeof sel === "string" ? sel.trim() : sel.length > 0))
  })

  const isDisabled = disabled || submitted

  return (
    <div
      role="form"
      aria-label={t("agentQuestions")}
      aria-disabled={isDisabled}
      className={`rounded-xl transition-all duration-300 relative overflow-hidden ${isDisabled ? "opacity-50 pointer-events-none" : ""}`}
      style={{
        border: `1px solid ${isDisabled ? "var(--border)" : "var(--border-hover)"}`,
        background: isDisabled ? "var(--surface-subtle)" : "var(--card)",
      }}
    >
      {/* Five-color spine (top to bottom) */}
      <div
        className="absolute left-0 top-0 bottom-0"
        style={{ width: "3px", background: "var(--team-spine-gradient)", opacity: 0.82 }}
        aria-hidden="true"
      />

      {/* Inference */}
      <div className="flex items-start gap-2.5 px-4 pl-5 pt-3.5 pb-2">
        <Lightbulb className="h-4 w-4 mt-0.5 flex-none text-foreground-secondary" />
        <p className="text-sm leading-relaxed text-foreground-secondary">{inference}</p>
      </div>

      {/* Questions */}
      <div className="px-4 pl-5 pb-3 space-y-4" role="group">
        {questions.map((q) => (
          <fieldset key={q.id} className="space-y-2.5 animate-in fade-in-0 duration-300">
            {!q.text ? (
              <div className="space-y-2">
                <div className="h-4 w-2/3 rounded bg-foreground/[4%] animate-pulse" />
                <div className="flex gap-1.5">
                  <div className="h-7 w-20 rounded-full bg-foreground/[3%] animate-pulse" />
                  <div className="h-7 w-24 rounded-full bg-foreground/[3%] animate-pulse" />
                  <div className="h-7 w-16 rounded-full bg-foreground/[3%] animate-pulse" />
                </div>
              </div>
            ) : (
            <>
            <legend className="text-sm font-medium text-foreground">{q.text}</legend>

            {(q.type === "single_select" || q.type === "multi_select") && q.options && (
              <>
                <div className="flex flex-wrap gap-1.5" role={q.type === "single_select" ? "radiogroup" : "group"} aria-label={q.text}>
                  {q.options.map((opt) => {
                    const selected = q.type === "single_select"
                      ? answers.selections[q.id] === opt
                      : ((answers.selections[q.id] as string[]) || []).includes(opt)
                    const rec = isRecommended(opt, q.recommended)
                    return (
                      <button
                        key={opt}
                        type="button"
                        role={q.type === "single_select" ? "radio" : "checkbox"}
                        aria-checked={selected}
                        onClick={() => q.type === "single_select" ? toggleSingle(q.id, opt) : toggleMulti(q.id, opt)}
                        className={`relative min-h-11 px-3 py-1.5 rounded-full text-xs transition-all duration-150 active:scale-[0.96] focus:outline-none ${
                          selected
                            ? "bg-foreground text-background font-medium"
                            : "bg-foreground/[6%] text-foreground-secondary border border-border hover:border-border-hover"
                        }`}
                      >
                        {opt}
                        {rec && !selected && (
                          <span
                            className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-agent-data"
                            title={t("recommended")}
                          />
                        )}
                      </button>
                    )
                  })}
                </div>
                <input
                  type="text"
                  value={answers.notes[q.id] || ""}
                  onChange={(e) => setNote(q.id, e.target.value)}
                  placeholder={t("additionalNotes")}
                  aria-label={`${q.text} — ${t("additionalNotesLabel")}`}
                  className="w-full min-h-11 px-3 py-1.5 rounded-lg text-xs text-foreground/70 placeholder:text-foreground-muted/60 bg-foreground/[2%] border border-border focus:outline-none focus:border-border-hover transition-colors duration-150"
                />
              </>
            )}

            {q.type === "free_text" && (
              <textarea
                value={(answers.selections[q.id] as string) || ""}
                onChange={(e) => setText(q.id, e.target.value)}
                placeholder={q.placeholder}
                rows={2}
                aria-label={q.text}
                className="w-full px-3 py-2 rounded-lg text-xs text-foreground/70 placeholder:text-foreground-muted/50 bg-foreground/[3%] border border-border focus:outline-none focus:border-border-hover resize-y min-h-11 transition-colors duration-150"
              />
            )}
          </>
            )}
          </fieldset>
        ))}
      </div>

      {!isDisabled && (
        <div className="flex justify-end gap-2 px-4 pb-3.5">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!hasAnswer}
            className="team-action-btn flex items-center gap-1.5 min-h-11 px-3 py-1.5 rounded-lg text-xs font-medium active:scale-[0.97] disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 focus:outline-none"
          >
            <Send className="h-3 w-3" />
            {t("submit")}
          </button>
        </div>
      )}
    </div>
  )
}
