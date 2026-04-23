// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { useState } from "react"
import { Lightbulb, Send } from "lucide-react"
import { CAT } from "./ToolCard"

const P = CAT.hearing

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
      if (selText && note) return `${q.text}: ${selText}（${note}）`
      if (selText) return `${q.text}: ${selText}`
      return `${q.text}: ${note}`
    })
    .filter(Boolean)
    .join("\n")
}

export function HearingCard({ inference, questions, disabled = false, onSubmit }: HearingCardProps) {
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
      aria-label="Agent questions"
      aria-disabled={isDisabled}
      className={`rounded-xl transition-all duration-300 ${isDisabled ? "opacity-50 pointer-events-none" : ""}`}
      style={{
        border: `1px solid ${isDisabled ? "oklch(1 0 0 / 5%)" : P.border}`,
        background: isDisabled ? "oklch(1 0 0 / 2%)" : P.bg,
        boxShadow: isDisabled ? "none" : `0 0 30px -4px ${P.glow}`,
      }}
    >
      {/* Inference */}
      <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-2">
        <Lightbulb className="h-4 w-4 mt-0.5 flex-none" style={{ color: P.accent }} />
        <p className="text-[13px] leading-relaxed" style={{ color: P.accent }}>{inference}</p>
      </div>

      {/* Questions */}
      <div className="px-4 pb-3 space-y-4" role="group">
        {questions.map((q) => (
          <fieldset key={q.id} className="space-y-2.5 animate-in fade-in-0 duration-300">
            {!q.text ? (
              <div className="space-y-2">
                <div className="h-4 w-2/3 rounded bg-white/[4%] animate-pulse" />
                <div className="flex gap-1.5">
                  <div className="h-7 w-20 rounded-full bg-white/[3%] animate-pulse" />
                  <div className="h-7 w-24 rounded-full bg-white/[3%] animate-pulse" />
                  <div className="h-7 w-16 rounded-full bg-white/[3%] animate-pulse" />
                </div>
              </div>
            ) : (
            <>
            <legend className="text-[13px] font-medium text-foreground">{q.text}</legend>

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
                        className="relative px-3 py-1.5 rounded-full text-[12px] transition-all duration-150 active:scale-[0.96] focus:outline-none"
                        style={{
                          background: selected ? P.border : "oklch(1 0 0 / 6%)",
                          color: selected ? "oklch(0.95 0 0)" : "oklch(0.80 0 0)",
                          border: `1px solid ${selected ? P.accent : "oklch(1 0 0 / 12%)"}`,
                          boxShadow: selected ? `0 0 10px -2px ${P.glow}` : "none",
                        }}
                      >
                        {opt}
                        {rec && !selected && (
                          <span
                            className="absolute -top-1 -right-1 w-2 h-2 rounded-full"
                            style={{ background: P.accent }}
                            title="Recommended"
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
                  placeholder="補足があれば..."
                  aria-label={`${q.text} — additional notes`}
                  className="w-full px-3 py-1.5 rounded-lg text-[12px] text-foreground/70 placeholder:text-foreground/30 focus:outline-none transition-colors duration-150"
                  style={{
                    background: "oklch(1 0 0 / 2%)",
                    border: "1px solid oklch(1 0 0 / 4%)",
                  }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = P.border }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = "oklch(1 0 0 / 4%)" }}
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
                className="w-full px-3 py-2 rounded-lg text-[12px] text-foreground/70 placeholder:text-foreground/25 focus:outline-none resize-y min-h-[2.5rem] transition-colors duration-150"
                style={{
                  background: "oklch(1 0 0 / 3%)",
                  border: "1px solid oklch(1 0 0 / 5%)",
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = P.border }}
                onBlur={(e) => { e.currentTarget.style.borderColor = "oklch(1 0 0 / 5%)" }}
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
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium active:scale-[0.97] disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 focus:outline-none"
            style={{
              background: P.bg,
              color: P.accent,
              boxShadow: hasAnswer ? `0 0 12px -3px ${P.glow}` : "none",
            }}
            onMouseEnter={(e) => { if (hasAnswer) e.currentTarget.style.background = P.border }}
            onMouseLeave={(e) => { e.currentTarget.style.background = P.bg }}
          >
            <Send className="h-3 w-3" />
            Submit
          </button>
        </div>
      )}
    </div>
  )
}
