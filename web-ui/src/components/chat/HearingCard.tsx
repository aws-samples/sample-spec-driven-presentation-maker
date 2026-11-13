// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * HearingCard — the agent's `hearing` questions, one at a time.
 *
 * Header chips show every question and the progress; the body shows the current question
 * with its options as rows (radio marks for single select, check boxes for multi select)
 * plus an "Other" row the card adds itself. Single select moves on once picked; multi
 * select and free text move on with Next. Keys work once the card has focus (number keys
 * pick, Enter moves on, ⌘↵ / Ctrl+↵ submits); the card never takes focus on its own.
 * After submit, or when the user replied in chat instead (`disabled`), it collapses to
 * an answered summary. Questions still streaming in show as they arrive.
 */
"use client"

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"
import { Check, CheckCircle2, Send } from "lucide-react"
import { useTranslations } from "next-intl"
import {
  EMPTY_ANSWER,
  answerValue,
  fallbackHeader,
  formatAnswers,
  isAnswered,
  type HearingAnswer,
  type HearingQuestion,
} from "./hearingQuestions"

interface HearingCardProps {
  questions: HearingQuestion[]
  /** The tool input is still streaming in: more questions may follow. */
  streaming?: boolean
  /** The user moved on in chat: show the summary without answers. */
  disabled?: boolean
  onSubmit: (text: string) => void
}

/** Pause after a single-select pick before moving on, so the pick is visible. */
const ADVANCE_DELAY_MS = 220

function Spine() {
  return (
    <div
      className="absolute left-0 top-0 bottom-0"
      style={{ width: "3px", background: "var(--team-spine-gradient)", opacity: 0.82 }}
      aria-hidden="true"
    />
  )
}

export function HearingCard({ questions, streaming = false, disabled = false, onSubmit }: HearingCardProps) {
  const t = useTranslations("hearing")
  const baseId = useId()
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState<Record<string, HearingAnswer>>({})
  const [submitted, setSubmitted] = useState(false)
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const otherInput = useRef<HTMLInputElement>(null)
  const focusOther = useRef(false)

  useEffect(() => () => {
    if (advanceTimer.current) clearTimeout(advanceTimer.current)
  }, [])

  useEffect(() => {
    if (focusOther.current && otherInput.current) {
      focusOther.current = false
      otherInput.current.focus()
    }
  })

  const headerOf = (q: HearingQuestion, i: number) => q.header || fallbackHeader(q.text) || t("questionNumber", { n: i + 1 })
  const anyAnswered = questions.some((q) => isAnswered(q, answers[q.id]))

  if (questions.length === 0) return null

  if (submitted || disabled) {
    const shown = submitted ? answers : {}
    const count = questions.filter((q) => isAnswered(q, shown[q.id])).length
    return (
      <div role="group" aria-label={t("answered")} className="hearing-card relative overflow-hidden rounded-[14px] px-4 pl-5 py-3">
        <Spine />
        <div className="flex items-center gap-1.5 text-sm font-medium text-foreground-secondary">
          <CheckCircle2 className="h-4 w-4 flex-none" aria-hidden="true" />
          {t("answered")}
          <span className="ml-1 text-xs font-normal text-foreground-muted">{t("answeredCount", { count, total: questions.length })}</span>
        </div>
        <dl className="mt-2.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {questions.map((q, i) => (
            <div key={q.id} className="contents">
              <dt className="text-xs leading-relaxed text-foreground-muted">{headerOf(q, i)}</dt>
              <dd className="m-0 text-sm leading-normal text-foreground-secondary">{answerValue(q, shown[q.id]) || "—"}</dd>
            </div>
          ))}
        </dl>
      </div>
    )
  }

  const index = Math.min(step, questions.length - 1)
  const current = questions[index]
  const answer = answers[current.id] ?? EMPTY_ANSWER
  const hasNext = index < questions.length - 1
  const isLast = !hasNext && !streaming
  const isSelect = current.type !== "free_text"

  const clearTimer = () => {
    if (advanceTimer.current) clearTimeout(advanceTimer.current)
    advanceTimer.current = null
  }
  const goTo = (i: number) => {
    clearTimer()
    setStep(Math.max(0, Math.min(i, questions.length - 1)))
  }
  const update = (id: string, patch: (a: HearingAnswer) => Partial<HearingAnswer>) =>
    setAnswers((prev) => {
      const a = prev[id] ?? EMPTY_ANSWER
      return { ...prev, [id]: { ...a, ...patch(a) } }
    })

  const submit = () => {
    if (streaming || !anyAnswered) return
    clearTimer()
    setSubmitted(true)
    onSubmit(formatAnswers(questions, answers))
  }
  const advance = () => {
    if (hasNext) goTo(index + 1)
    else if (isLast) submit()
  }

  const pickOption = (label: string) => {
    if (current.type === "multi_select") {
      update(current.id, (a) => ({
        selected: a.selected.includes(label) ? a.selected.filter((l) => l !== label) : [...a.selected, label],
      }))
      return
    }
    const picking = !answer.selected.includes(label)
    clearTimer()
    update(current.id, () => (picking ? { selected: [label], otherOn: false } : { selected: [] }))
    if (picking && hasNext) {
      const at = index
      advanceTimer.current = setTimeout(() => {
        advanceTimer.current = null
        setStep((s) => (s === at ? at + 1 : s))
      }, ADVANCE_DELAY_MS)
    }
  }
  const toggleOther = () => {
    const on = !answer.otherOn
    clearTimer()
    if (on) focusOther.current = true
    update(current.id, () => (on && current.type === "single_select" ? { otherOn: true, selected: [] } : { otherOn: on }))
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
      return
    }
    const target = e.target as HTMLElement
    const composing = e.nativeEvent.isComposing || e.keyCode === 229
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") {
      if (e.key === "Enter" && target.tagName === "INPUT" && !composing && !e.shiftKey) {
        e.preventDefault()
        advance()
      }
      return
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return
    if (isSelect && current.text && /^[1-9]$/.test(e.key)) {
      const i = Number(e.key) - 1
      if (i < current.options.length) {
        e.preventDefault()
        pickOption(current.options[i].label)
      } else if (i === current.options.length) {
        e.preventDefault()
        toggleOther()
      }
    } else if (e.key === "Enter" && !target.closest("button")) {
      e.preventDefault()
      advance()
    }
  }

  const textId = `${baseId}-text`
  const indicator = current.type === "multi_select" ? "hearing-ind-box" : "hearing-ind-radio"
  const rowRole = current.type === "multi_select" ? "checkbox" : "radio"

  const row = (key: string, checked: boolean, n: number, label: string, onClick: () => void, description?: string, recommended?: boolean) => (
    <button
      key={key}
      type="button"
      role={rowRole}
      aria-checked={checked}
      onClick={onClick}
      className="hearing-row flex w-full items-start gap-3 rounded-[10px] px-3 py-2.5 text-left transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className={`hearing-ind ${indicator} mt-0.5 inline-flex flex-none items-center justify-center`} aria-hidden="true">
        {checked && current.type === "multi_select" && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
      <span className="flex flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          {label}
          {recommended && <span className="hearing-rec rounded-full px-1.5 text-[11px] font-medium leading-normal">{t("recommended")}</span>}
        </span>
        {description && <span className="text-xs leading-normal text-foreground-secondary">{description}</span>}
      </span>
      <kbd className="hearing-kbd mt-px rounded-[5px] px-1.5 text-xs" aria-hidden="true">{n}</kbd>
    </button>
  )

  return (
    <div
      role="form"
      aria-label={t("agentQuestions")}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="hearing-card relative overflow-hidden rounded-[14px] focus:outline-none focus-visible:ring-2 focus-visible:ring-ring animate-in fade-in-0 duration-300"
    >
      <Spine />

      {/* Header chips: every question and the progress */}
      <div role="group" aria-label={t("steps")} className="flex flex-wrap gap-1.5 border-b border-border px-4 pl-5 py-3">
        {questions.map((q, i) => {
          if (!q.text) {
            return (
              <span key={q.id} className="hearing-step inline-flex min-h-7 min-w-16 items-center rounded-full px-2.5 py-1 text-xs animate-pulse" aria-hidden="true">
                {q.header}
              </span>
            )
          }
          const done = isAnswered(q, answers[q.id])
          return (
            <button
              key={q.id}
              type="button"
              onClick={() => goTo(i)}
              aria-current={i === index ? "step" : undefined}
              data-done={done || undefined}
              title={done ? answerValue(q, answers[q.id]) : t("unanswered")}
              className={`hearing-step inline-flex min-h-7 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring ${i === index ? "font-medium" : ""}`}
            >
              {done ? <Check className="h-3 w-3" strokeWidth={3} aria-hidden="true" /> : <span className="tabular-nums">{i + 1}</span>}
              {headerOf(q, i)}
            </button>
          )
        })}
      </div>

      {/* Current question */}
      <div className={`px-4 pl-5 pt-3.5 pb-4 ${questions.length > 1 ? "min-h-[300px]" : ""}`}>
        {!current.text ? (
          <div role="status" aria-label={t("loading")} className="space-y-2">
            <div className="h-4 w-2/3 rounded bg-foreground/[4%] animate-pulse" />
            <div className="h-11 w-full rounded-[10px] bg-foreground/[3%] animate-pulse" />
            <div className="h-11 w-full rounded-[10px] bg-foreground/[3%] animate-pulse" />
          </div>
        ) : (
          <>
            <p id={textId} className="mt-1.5 text-sm font-semibold leading-normal text-foreground">{current.text}</p>
            <span className="mb-3 block text-xs text-foreground-muted">
              {current.type === "single_select" ? t("singleHint") : current.type === "multi_select" ? t("multiHint") : t("freeTextHint")}
            </span>
            {isSelect ? (
              <>
                <div role={current.type === "single_select" ? "radiogroup" : "group"} aria-labelledby={textId} className="space-y-1.5">
                  {current.options.map((o, i) =>
                    row(o.label, answer.selected.includes(o.label), i + 1, o.label, () => pickOption(o.label), o.description, o.recommended),
                  )}
                  {row("__other", answer.otherOn, current.options.length + 1, t("other"), toggleOther, t("otherDescription"))}
                </div>
                {answer.otherOn && (
                  <input
                    ref={otherInput}
                    type="text"
                    value={answer.other}
                    onChange={(e) => update(current.id, () => ({ other: e.target.value }))}
                    placeholder={t("otherPlaceholder")}
                    aria-label={`${current.text} — ${t("other")}`}
                    className="hearing-field mt-2 w-full rounded-[10px] px-3 py-2 text-sm leading-normal"
                  />
                )}
              </>
            ) : (
              <textarea
                value={answer.text}
                onChange={(e) => update(current.id, () => ({ text: e.target.value }))}
                placeholder={current.placeholder}
                rows={3}
                aria-labelledby={textId}
                className="hearing-field min-h-16 w-full resize-y rounded-[10px] px-3 py-2 text-sm leading-normal"
              />
            )}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center gap-2.5 border-t border-border px-4 pl-5 pt-3 pb-3.5">
        <button
          type="button"
          onClick={() => goTo(index - 1)}
          disabled={index === 0}
          className="min-h-8 rounded-lg border border-border-hover px-2.5 py-1.5 text-xs text-foreground-secondary transition-colors duration-150 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("back")}
        </button>
        <span className="ml-auto text-xs tabular-nums text-foreground-muted">{t("progress", { current: index + 1, total: questions.length })}</span>
        {isLast ? (
          <button
            type="button"
            onClick={submit}
            disabled={!anyAnswered}
            className="team-action-btn flex min-h-10 items-center gap-1.5 rounded-[10px] px-4 py-2 text-sm font-medium transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-30 focus:outline-none"
          >
            <Send className="h-3 w-3" aria-hidden="true" />
            {t("submit")}
          </button>
        ) : (
          <button
            type="button"
            onClick={advance}
            disabled={!hasNext}
            className="hearing-primary min-h-10 rounded-[10px] px-4 py-2 text-sm font-medium transition-opacity duration-150 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {isAnswered(current, answer) ? t("next") : t("skip")}
          </button>
        )}
      </div>
    </div>
  )
}
