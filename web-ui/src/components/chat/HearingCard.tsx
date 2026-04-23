// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { useState } from "react"
import { Lightbulb, Send } from "lucide-react"

/**
 * Hearing accent — oklch violet matching ToolCard "produce" category
 * but slightly warmer to distinguish interactive cards from output tools.
 */
const ACCENT = "oklch(0.74 0.16 305)"
const ACCENT_DIM = "oklch(0.74 0.16 305 / 12%)"
const ACCENT_BORDER = "oklch(0.74 0.16 305 / 20%)"
const ACCENT_GLOW = "oklch(0.74 0.16 305 / 8%)"

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
  onCancel: () => void
}

function isRecommended(option: string, rec?: string | string[]): boolean {
  if (!rec) return false
  return Array.isArray(rec) ? rec.includes(option) : rec === option
}

function formatAnswers(questions: Question[], answers: Record<string, string | string[]>): string {
  return questions
    .map((q) => {
      const a = answers[q.id]
      if (!a || (Array.isArray(a) && a.length === 0)) return null
      const val = Array.isArray(a) ? a.join(", ") : a
      return val ? `${q.text}: ${val}` : null
    })
    .filter(Boolean)
    .join("\n")
}

export function HearingCard({ inference, questions, disabled = false, onSubmit, onCancel }: HearingCardProps) {
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [submitted, setSubmitted] = useState(false)

  const setSingle = (id: string, value: string) => setAnswers((p) => ({ ...p, [id]: value }))
  const toggleMulti = (id: string, value: string) =>
    setAnswers((p) => {
      const cur = (p[id] as string[]) || []
      return { ...p, [id]: cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value] }
    })
  const setText = (id: string, value: string) => setAnswers((p) => ({ ...p, [id]: value }))

  const handleSubmit = () => {
    const text = formatAnswers(questions, answers)
    if (text) {
      setSubmitted(true)
      onSubmit(text)
    }
  }

  const hasAnswer = questions.some((q) => {
    const a = answers[q.id]
    return a && (typeof a === "string" ? a.trim() : a.length > 0)
  })

  const isDisabled = disabled || submitted

  /* Style objects using oklch accent — avoids Tailwind purple mismatch with project palette */
  const optionBase = { border: `1px solid oklch(1 0 0 / 5%)`, background: "oklch(1 0 0 / 3%)" }
  const optionHover = { border: `1px solid oklch(1 0 0 / 8%)`, background: "oklch(1 0 0 / 5%)" }
  const optionSelected = { border: `1px solid ${ACCENT_BORDER}`, background: ACCENT_DIM }

  return (
    <div
      role="form"
      aria-label="Agent questions"
      aria-disabled={isDisabled}
      className={`rounded-xl transition-all duration-300 ${isDisabled ? "opacity-50 pointer-events-none" : ""}`}
      style={{
        border: `1px solid ${isDisabled ? "oklch(1 0 0 / 5%)" : ACCENT_BORDER}`,
        background: isDisabled ? "oklch(1 0 0 / 2%)" : ACCENT_GLOW,
        boxShadow: isDisabled ? "none" : `0 0 24px -6px ${ACCENT_GLOW}`,
      }}
    >
      {/* Inference */}
      <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-2">
        <Lightbulb className="h-4 w-4 mt-0.5 flex-none" style={{ color: ACCENT }} />
        <p className="text-[13px] leading-relaxed" style={{ color: `${ACCENT}dd` }}>{inference}</p>
      </div>

      {/* Questions */}
      <div className="px-4 pb-3 space-y-4" role="group">
        {questions.map((q) => (
          <fieldset key={q.id} className="space-y-2">
            <legend className="text-[13px] font-medium text-foreground/80">{q.text}</legend>

            {q.type === "single_select" && q.options && (
              <div className="space-y-1.5" role="radiogroup" aria-label={q.text}>
                {q.options.map((opt) => {
                  const selected = answers[q.id] === opt
                  return (
                    <label
                      key={opt}
                      className="flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-all duration-150"
                      style={{
                        ...(selected ? optionSelected : optionBase),
                        transform: selected ? "scale(1.01)" : "scale(1)",
                      }}
                      onMouseEnter={(e) => { if (!selected) Object.assign(e.currentTarget.style, optionHover) }}
                      onMouseLeave={(e) => { if (!selected) Object.assign(e.currentTarget.style, optionBase) }}
                    >
                      <input type="radio" name={q.id} value={opt} checked={selected} onChange={() => setSingle(q.id, opt)} className="sr-only" />
                      <div
                        className="w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center transition-colors duration-150"
                        style={{ borderColor: selected ? ACCENT : "oklch(1 0 0 / 12%)" }}
                      >
                        {selected && <div className="w-1.5 h-1.5 rounded-full animate-in zoom-in-50 duration-150" style={{ background: ACCENT }} />}
                      </div>
                      <span className="text-[12px] text-foreground/70 flex-1">{opt}</span>
                      {isRecommended(opt, q.recommended) && (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ background: ACCENT_DIM, color: ACCENT }}>
                          Recommended
                        </span>
                      )}
                    </label>
                  )
                })}
              </div>
            )}

            {q.type === "multi_select" && q.options && (
              <div className="space-y-1.5" role="group" aria-label={q.text}>
                {q.options.map((opt) => {
                  const checked = ((answers[q.id] as string[]) || []).includes(opt)
                  return (
                    <label
                      key={opt}
                      className="flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-all duration-150"
                      style={{
                        ...(checked ? optionSelected : optionBase),
                        transform: checked ? "scale(1.01)" : "scale(1)",
                      }}
                      onMouseEnter={(e) => { if (!checked) Object.assign(e.currentTarget.style, optionHover) }}
                      onMouseLeave={(e) => { if (!checked) Object.assign(e.currentTarget.style, optionBase) }}
                    >
                      <input type="checkbox" checked={checked} onChange={() => toggleMulti(q.id, opt)} className="sr-only" aria-label={opt} />
                      <div
                        className="w-3.5 h-3.5 rounded border-2 flex items-center justify-center transition-all duration-150"
                        style={{
                          borderColor: checked ? ACCENT : "oklch(1 0 0 / 12%)",
                          background: checked ? ACCENT : "transparent",
                          transform: checked ? "scale(1.05)" : "scale(1)",
                        }}
                      >
                        {checked && (
                          <svg className="w-2.5 h-2.5 text-white animate-in zoom-in-50 duration-150" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M2 6l3 3 5-5" />
                          </svg>
                        )}
                      </div>
                      <span className="text-[12px] text-foreground/70 flex-1">{opt}</span>
                      {isRecommended(opt, q.recommended) && (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ background: ACCENT_DIM, color: ACCENT }}>
                          Recommended
                        </span>
                      )}
                    </label>
                  )
                })}
              </div>
            )}

            {q.type === "free_text" && (
              <textarea
                value={(answers[q.id] as string) || ""}
                onChange={(e) => setText(q.id, e.target.value)}
                placeholder={q.placeholder}
                rows={2}
                aria-label={q.text}
                className="w-full px-3 py-2 rounded-lg text-[12px] text-foreground/70 placeholder:text-foreground/25 focus:outline-none resize-y min-h-[2.5rem] transition-colors duration-150"
                style={{
                  background: "oklch(1 0 0 / 3%)",
                  border: `1px solid oklch(1 0 0 / 5%)`,
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = ACCENT_BORDER }}
                onBlur={(e) => { e.currentTarget.style.borderColor = "oklch(1 0 0 / 5%)" }}
              />
            )}
          </fieldset>
        ))}
      </div>

      {/* Actions */}
      {!isDisabled && (
        <div className="flex justify-end gap-2 px-4 pb-3.5">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-[12px] text-foreground/40 hover:text-foreground/60 transition-colors rounded-lg focus:outline-none"
            style={{ boxShadow: "none" }}
          >
            Skip
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!hasAnswer}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium active:scale-[0.97] disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 focus:outline-none"
            style={{
              background: ACCENT_DIM,
              color: ACCENT,
              boxShadow: hasAnswer ? `0 0 12px -3px ${ACCENT_GLOW}` : "none",
            }}
            onMouseEnter={(e) => { if (hasAnswer) e.currentTarget.style.background = "oklch(0.74 0.16 305 / 20%)" }}
            onMouseLeave={(e) => { e.currentTarget.style.background = ACCENT_DIM }}
          >
            <Send className="h-3 w-3" />
            Submit
          </button>
        </div>
      )}
    </div>
  )
}
