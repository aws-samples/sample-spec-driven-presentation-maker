// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { KeyboardEvent as ReactKeyboardEvent, ReactElement, ReactNode } from "react"
import {
  DragDropProvider,
  DragOverlay,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  useDroppable,
} from "@dnd-kit/react"
import { useSortable } from "@dnd-kit/react/sortable"
import { AnimatePresence, MotionConfig, motion } from "motion/react"
import TextareaAutosize from "react-textarea-autosize"
import {
  Check,
  Code2,
  Copy,
  GripVertical,
  LayoutGrid,
  List,
  Plus,
  Redo2,
  Send,
  Trash2,
  Undo2,
  X,
} from "lucide-react"
import { toast } from "sonner"
import { useTranslations } from "next-intl"
import { useLocale } from "@/i18n/LocaleProvider"
import { putOutline } from "@/services/deckService"
import { renderColorSwatches } from "./colorSwatches"
import {
  getDeckName,
  getSubItemText,
  type OutlineDocument,
  type OutlineNode,
  type ProseNode,
  type SectionNode,
  type SlideNode,
} from "./outlineDocument"
import type { SubItemKey } from "./outlineParser"
import { buildOutlineEditMessage } from "./outlineEditMessage"
import { useOutlineChat } from "./OutlineChatContext"
import { useOutlineEditor, type OutlineEditor, type SlideDropTarget } from "./useOutlineEditor"

const LAYOUT_STORAGE_KEY = "sdpm-outline-layout"
const POLISH_STORAGE_KEY = "sdpm-outline-polish"

type StoryboardLayout = "grid" | "column"

type ChapterGroup = {
  id: string
  section: SectionNode | null
  nodes: OutlineNode[]
}

function readStoredLayout(): StoryboardLayout {
  if (typeof window === "undefined") return "grid"
  return localStorage.getItem(LAYOUT_STORAGE_KEY) === "column" ? "column" : "grid"
}

function readStoredPolish(): boolean {
  if (typeof window === "undefined") return true
  return localStorage.getItem(POLISH_STORAGE_KEY) !== "false"
}

function chapterGroups(doc: OutlineDocument): ChapterGroup[] {
  const groups: ChapterGroup[] = []
  let current: ChapterGroup = { id: "root", section: null, nodes: [] }
  groups.push(current)
  let skippedDeckTitle = false

  for (const node of doc.nodes) {
    if (node.type === "section") {
      current = { id: node.id, section: node, nodes: [] }
      groups.push(current)
      continue
    }
    if (!skippedDeckTitle && node.type === "prose" && /^#\s+/.test(node.text)) {
      skippedDeckTitle = true
      continue
    }
    current.nodes.push(node)
  }
  return groups.filter((group) => group.section || group.nodes.some((node) => node.type !== "prose" || node.text.trim() !== ""))
}

function slideNodes(doc: OutlineDocument): SlideNode[] {
  return doc.nodes.filter((node): node is SlideNode => node.type === "slide")
}

function EditableText({
  value,
  onChange,
  editor,
  ariaLabel,
  placeholder,
  multiline = false,
  className,
  onConfirm,
}: {
  value: string
  onChange: (value: string) => void
  editor: OutlineEditor
  ariaLabel: string
  placeholder: string
  multiline?: boolean
  className: string
  onConfirm?: () => void
}): ReactElement {
  const beforeRef = useRef<OutlineDocument | null>(null)
  const beforeValueRef = useRef(value)
  const focusedRef = useRef(false)
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    if (!focusedRef.current) setDraft(value)
  }, [value])

  const commit = () => {
    focusedRef.current = false
    if (beforeRef.current) editor.commitSnapshot(beforeRef.current)
    beforeRef.current = null
    onConfirm?.()
  }

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    event.stopPropagation()
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    if (event.key === "Escape") {
      event.preventDefault()
      if (beforeRef.current) editor.restoreSnapshot(beforeRef.current)
      setDraft(beforeValueRef.current)
      beforeRef.current = null
      event.currentTarget.blur()
      return
    }
    if (event.key === "Enter" && (!multiline || event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      event.currentTarget.blur()
    }
  }

  return (
    <TextareaAutosize
      value={draft}
      onChange={(event) => {
        setDraft(event.target.value)
        onChange(event.target.value)
      }}
      onFocus={() => {
        focusedRef.current = true
        beforeRef.current = editor.snapshot()
        beforeValueRef.current = value
        setDraft(value)
      }}
      onBlur={commit}
      onKeyDown={handleKeyDown}
      aria-label={ariaLabel}
      placeholder={placeholder}
      rows={1}
      className={className}
      spellCheck
    />
  )
}

function GhostCard({ sectionId, onAdd, label }: { sectionId: string; onAdd: () => void; label: string }): ReactElement {
  const { ref, isDropTarget } = useDroppable({
    id: `ghost:${sectionId}`,
    type: "chapter-end",
    accept: "slide",
    data: { kind: "chapter-end", sectionId },
  })
  return (
    <motion.button
      ref={ref}
      layout
      type="button"
      className="storyboard-ghost"
      data-drop-target={isDropTarget || undefined}
      onClick={onAdd}
      aria-label={label}
    >
      <Plus aria-hidden="true" />
      <span>{label}</span>
    </motion.button>
  )
}

function SlidePreview({ slide }: { slide: SlideNode }): ReactElement {
  return (
    <article className="storyboard-slide storyboard-drag-preview" aria-hidden="true">
      <div className="storyboard-paper">
        <div className="storyboard-slug">{slide.slug}</div>
        <h3 className="storyboard-slide-title">{slide.message || slide.slug}</h3>
        <p className="storyboard-body">{getSubItemText(slide, "body")}</p>
      </div>
    </article>
  )
}

function StoryboardSlide({
  slide,
  number,
  sectionId,
  index,
  editor,
  focused,
  onFocus,
  onDelete,
  onDuplicate,
  onNudge,
  onNavigate,
  t,
  landing,
}: {
  slide: SlideNode
  number: number
  sectionId: string
  index: number
  editor: OutlineEditor
  focused: boolean
  onFocus: () => void
  onDelete: () => void
  onDuplicate: () => void
  onNudge: (direction: -1 | 1) => void
  onNavigate: (direction: -1 | 1) => void
  t: ReturnType<typeof useTranslations<"outline">>
  landing: boolean
}): ReactElement {
  const { ref, isDragging, isDropTarget } = useSortable({
    id: slide.id,
    index,
    group: sectionId,
    type: "slide",
    accept: "slide",
    data: { kind: "slide", sectionId },
    transition: { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)", idle: true },
  })

  const handleCardKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget) return
    if (event.key === "Backspace" || event.key === "Delete") {
      event.preventDefault()
      onDelete()
    } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault()
      onNudge(event.key === "ArrowUp" ? -1 : 1)
    } else if (["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"].includes(event.key)) {
      event.preventDefault()
      onNavigate(event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1)
    }
  }

  const field = (key: SubItemKey) => (
    <EditableText
      value={getSubItemText(slide, key)}
      onChange={(value) => editor.updateSubItem(slide.id, key, value)}
      editor={editor}
      multiline
      ariaLabel={t("fieldLabel", { field: t(key), number })}
      placeholder={t(`${key}Placeholder`)}
      className={key === "body" ? "storyboard-edit storyboard-body-edit" : "storyboard-edit storyboard-meta-edit"}
    />
  )

  return (
    <motion.article
      ref={ref}
      layout
      initial={{ opacity: 0, y: 8, scale: 0.97 }}
      animate={{ opacity: isDragging ? 0.18 : 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.92 }}
      transition={{ duration: 0.26, ease: [0.2, 0.8, 0.2, 1] }}
      className="storyboard-slide"
      data-slide-slug={slide.slug}
      data-slide-id={slide.id}
      data-drop-target={isDropTarget || undefined}
      data-landing={landing || undefined}
      tabIndex={focused ? 0 : -1}
      onFocus={onFocus}
      onKeyDown={handleCardKeyDown}
      aria-label={t("slideCardLabel", { number, title: slide.message || slide.slug })}
    >
      <span className="storyboard-slide-number">{number}</span>
      <div className="storyboard-paper">
        <div className="storyboard-card-tools">
          <button type="button" data-drag-handle title={t("reorderTitle")} aria-label={t("reorderSlide", { number })}>
            <GripVertical aria-hidden="true" />
          </button>
          <button type="button" onClick={onDuplicate} title={t("duplicate")} aria-label={t("duplicateSlide", { number })}>
            <Copy aria-hidden="true" />
          </button>
          <button type="button" onClick={onDelete} title={t("deleteSlideTitle")} aria-label={t("deleteSlide", { number })}>
            <Trash2 aria-hidden="true" />
          </button>
        </div>
        <span className="storyboard-slug">{slide.slug}</span>
        <h3 className="storyboard-slide-title">
          <EditableText
            value={slide.message}
            onChange={(value) => editor.updateSlideMessage(slide.id, value)}
            editor={editor}
            ariaLabel={t("titleFieldLabel", { number })}
            placeholder={t("titlePlaceholder")}
            className="storyboard-edit storyboard-title-edit"
          />
        </h3>
        {field("body")}
        <footer className="storyboard-footer storyboard-edit-footer">
          <div><b>{t("visual")}</b>{field("visual")}</div>
          <div><b>{t("evidenceShort")}</b>{field("evidence")}</div>
        </footer>
      </div>
    </motion.article>
  )
}

function ProseBlock({ entry }: { entry: ProseNode }): ReactElement | null {
  if (!entry.text.trim()) return null
  return <p className="storyboard-prose" data-entry-type="prose">{renderColorSwatches(entry.text)}</p>
}

interface OutlineViewProps {
  content: string | null
  deckId?: string
  idToken?: string
}

export function OutlineView({ content, deckId, idToken = "" }: OutlineViewProps): ReactElement {
  const t = useTranslations("outline")
  const { locale } = useLocale()
  const chat = useOutlineChat()
  const editor = useOutlineEditor(content)
  const [layout, setLayout] = useState<StoryboardLayout>("grid")
  const [polish, setPolish] = useState(true)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [focusedSlideId, setFocusedSlideId] = useState<string | null>(null)
  const [activeSlideId, setActiveSlideId] = useState<string | null>(null)
  const [landingId, setLandingId] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState("")
  const [sending, setSending] = useState(false)
  const sendingRef = useRef(false)
  const dragBeforeRef = useRef<OutlineDocument | null>(null)
  const focusAfterRenderRef = useRef<{ id: string; field?: "title" } | null>(null)

  const slides = useMemo(() => slideNodes(editor.doc), [editor.doc])
  const groups = useMemo(() => chapterGroups(editor.doc), [editor.doc])
  const deckName = getDeckName(editor.doc) ?? ""
  const sendDisabled = chat.isLoading || sending || !deckId

  useEffect(() => {
    setLayout(readStoredLayout())
    setPolish(readStoredPolish())
  }, [])

  useEffect(() => {
    if (!focusedSlideId && slides[0]) setFocusedSlideId(slides[0].id)
    if (focusedSlideId && !slides.some((slide) => slide.id === focusedSlideId)) setFocusedSlideId(slides[0]?.id ?? null)
  }, [focusedSlideId, slides])

  useEffect(() => {
    const pending = focusAfterRenderRef.current
    if (!pending) return
    const card = document.querySelector<HTMLElement>(`[data-slide-id="${pending.id}"]`)
    const target = pending.field ? card?.querySelector<HTMLElement>(".storyboard-title-edit") : card
    if (target) {
      focusAfterRenderRef.current = null
      target.focus({ preventScroll: true })
      target.scrollIntoView({ block: "nearest", behavior: "smooth" })
    }
  }, [editor.doc])

  useEffect(() => {
    if (!editor.dirty) return
    const preventUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", preventUnload)
    return () => window.removeEventListener("beforeunload", preventUnload)
  }, [editor.dirty])

  const announce = useCallback((message: string) => {
    setAnnouncement("")
    window.setTimeout(() => setAnnouncement(message), 20)
  }, [])

  const flashLanding = useCallback((id: string) => {
    setLandingId(id)
    window.setTimeout(() => setLandingId((current) => current === id ? null : current), 900)
  }, [])

  const focusLogicalSlide = useCallback((id: string, delta: number) => {
    const index = slides.findIndex((slide) => slide.id === id)
    const next = slides[index + delta]
    if (!next) return
    setFocusedSlideId(next.id)
    focusAfterRenderRef.current = { id: next.id }
  }, [slides])

  const removeSlide = useCallback((slide: SlideNode) => {
    const index = slides.findIndex((candidate) => candidate.id === slide.id)
    const next = slides[index + 1] ?? slides[index - 1]
    editor.deleteSlide(slide.id)
    setFocusedSlideId(next?.id ?? null)
    if (next) focusAfterRenderRef.current = { id: next.id }
    const remaining = Math.max(0, slides.length - 1)
    announce(t("slideDeletedAnnouncement", { title: slide.message || slide.slug, count: remaining }))
    toast(t("slideDeleted", { title: slide.message || slide.slug }), {
      duration: 6000,
      action: {
        label: t("undo"),
        onClick: () => {
          editor.undo()
          setFocusedSlideId(slide.id)
          focusAfterRenderRef.current = { id: slide.id }
          announce(t("undoAnnouncement"))
        },
      },
    })
  }, [announce, editor, slides, t])

  const addSlide = useCallback((sectionId: string) => {
    const id = editor.addSlide(sectionId)
    if (id) {
      setFocusedSlideId(id)
      focusAfterRenderRef.current = { id, field: "title" }
      announce(t("slideAddedAnnouncement"))
    }
  }, [announce, editor, t])

  const duplicate = useCallback((slide: SlideNode) => {
    const id = editor.duplicateSlide(slide.id)
    if (id) {
      setFocusedSlideId(id)
      focusAfterRenderRef.current = { id }
      flashLanding(id)
      announce(t("slideDuplicatedAnnouncement"))
    }
  }, [announce, editor, flashLanding, t])

  const nudge = useCallback((slide: SlideNode, direction: -1 | 1) => {
    if (!editor.nudgeSlide(slide.id, direction)) return
    setFocusedSlideId(slide.id)
    focusAfterRenderRef.current = { id: slide.id }
    flashLanding(slide.id)
    const current = slides.findIndex((candidate) => candidate.id === slide.id)
    announce(t("slideMovedAnnouncement", { number: current + direction + 1 }))
  }, [announce, editor, flashLanding, slides, t])

  const removeSection = useCallback((section: SectionNode) => {
    editor.deleteSection(section.id)
    announce(t("chapterDeletedAnnouncement", { title: section.title }))
    toast(t("chapterDeleted", { title: section.title }), {
      duration: 6000,
      action: { label: t("undo"), onClick: () => { editor.undo(); announce(t("undoAnnouncement")) } },
    })
  }, [announce, editor, t])

  const addChapter = useCallback(() => {
    const id = editor.addSection()
    window.setTimeout(() => document.querySelector<HTMLElement>(`[data-section-id="${id}"] textarea`)?.focus(), 0)
    announce(t("chapterAddedAnnouncement"))
  }, [announce, editor, t])

  const handleDragStart = useCallback((event: DragStartEvent) => {
    const id = String(event.operation.source?.id ?? "")
    if (!id) return
    dragBeforeRef.current = editor.snapshot()
    setActiveSlideId(id)
  }, [editor])

  const handleDragOver = useCallback((event: DragOverEvent) => {
    const sourceId = String(event.operation.source?.id ?? "")
    const target = event.operation.target
    if (!sourceId || !target) return
    const targetId = String(target.id)
    const dropTarget: SlideDropTarget = targetId.startsWith("ghost:")
      ? { kind: "chapter-end", sectionId: targetId.slice("ghost:".length) }
      : { kind: "slide", id: targetId }
    editor.moveSlide(sourceId, dropTarget)
  }, [editor])

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const id = activeSlideId
    const before = dragBeforeRef.current
    setActiveSlideId(null)
    dragBeforeRef.current = null
    if (!id || !before) return
    if (event.canceled) editor.restoreSnapshot(before)
    else {
      editor.commitSnapshot(before)
      setFocusedSlideId(id)
      focusAfterRenderRef.current = { id }
      flashLanding(id)
      const number = slideNodes(editor.doc).findIndex((slide) => slide.id === id) + 1
      announce(t("slideMovedAnnouncement", { number }))
    }
  }, [activeSlideId, announce, editor, flashLanding, t])

  const catalog = useMemo(() => ({
    edited: t("messageEdited"),
    largeEdit: (count: number) => t("messageLargeEdit", { count }),
    placeholderSlugs: (slugs: string) => t("messagePlaceholderSlugs", { slugs }),
    polish: t("messagePolish"),
    overwritten: t("messageOverwritten"),
    display: (added: number, deleted: number) => t("messageDisplay", { added, deleted }),
  }), [locale, t])

  const sendChanges = useCallback(async () => {
    if (!editor.dirty || sendDisabled || !deckId || sendingRef.current) return
    sendingRef.current = true
    const baseBeforeSend = editor.base
    const text = editor.currentText
    const message = buildOutlineEditMessage({
      base: baseBeforeSend,
      text,
      latestSeen: editor.latestSeen,
      polish,
      catalog,
    })
    setSending(true)
    try {
      await putOutline(deckId, text, idToken)
      editor.markSaved(text)
      void chat.sendMessage(message.body, { displayContent: message.displayContent })
      toast.success(t("sent"), { icon: <Check className="h-4 w-4" /> })
      announce(t("sentAnnouncement"))
    } catch (error) {
      toast.error(t("sendFailed"), { description: error instanceof Error ? error.message : String(error) })
    } finally {
      sendingRef.current = false
      setSending(false)
    }
  }, [catalog, chat, deckId, editor, idToken, polish, sendDisabled, t, announce])

  const sendChangesRef = useRef(sendChanges)
  sendChangesRef.current = sendChanges

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault()
        target?.closest<HTMLTextAreaElement>("textarea")?.blur()
        window.setTimeout(() => void sendChangesRef.current(), 0)
        return
      }
      if (target?.closest("textarea, input, [contenteditable='true']")) return
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault()
        if (event.shiftKey) {
          editor.redo()
          announce(t("redoAnnouncement"))
        } else {
          editor.undo()
          announce(t("undoAnnouncement"))
        }
      }
      if (event.key === "Escape" && drawerOpen) setDrawerOpen(false)
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [announce, drawerOpen, editor, t])

  const selectLayout = (next: StoryboardLayout) => {
    setLayout(next)
    localStorage.setItem(LAYOUT_STORAGE_KEY, next)
  }
  const togglePolish = () => {
    setPolish((value) => {
      localStorage.setItem(POLISH_STORAGE_KEY, String(!value))
      return !value
    })
  }

  const activeSlide = slides.find((slide) => slide.id === activeSlideId) ?? null
  let slideNumber = 0
  let chapterNumber = 0

  const renderedGroups: ReactNode[] = groups.map((group) => {
    const groupSlides = group.nodes.filter((node): node is SlideNode => node.type === "slide")
    if (group.section) chapterNumber++
    return (
      <motion.section layout key={group.id} className="storyboard-chapter-group">
        {group.section && (
          <motion.div layout className="storyboard-chapter" data-entry-type="section" data-section-id={group.section.id}>
            <span className="storyboard-chapter-number">{String(chapterNumber).padStart(2, "0")}</span>
            <h2>
              <EditableText
                value={group.section.title}
                onChange={(value) => editor.updateSectionTitle(group.section!.id, value)}
                editor={editor}
                ariaLabel={t("chapterTitleField", { number: chapterNumber })}
                placeholder={t("chapterPlaceholder")}
                className="storyboard-edit storyboard-chapter-edit"
              />
            </h2>
            <span className="storyboard-chapter-count">{t("slideCount", { count: groupSlides.length })}</span>
            <button type="button" className="storyboard-delete-chapter" onClick={() => removeSection(group.section!)} title={t("deleteChapterTitle")}>
              {t("deleteChapter")}
            </button>
            <div className="storyboard-chapter-rule" aria-hidden="true" />
          </motion.div>
        )}
        <div className="storyboard-slides">
          <AnimatePresence initial={false}>
            {group.nodes.map((node) => {
              if (node.type === "prose") return <ProseBlock key={node.id} entry={node} />
              if (node.type === "section") return null
              slideNumber++
              return (
                <StoryboardSlide
                  key={node.id}
                  slide={node}
                  number={slideNumber}
                  sectionId={group.id}
                  index={groupSlides.findIndex((slide) => slide.id === node.id)}
                  editor={editor}
                  focused={(focusedSlideId ?? slides[0]?.id) === node.id}
                  onFocus={() => setFocusedSlideId(node.id)}
                  onDelete={() => removeSlide(node)}
                  onDuplicate={() => duplicate(node)}
                  onNudge={(direction) => nudge(node, direction)}
                  onNavigate={(direction) => focusLogicalSlide(node.id, direction)}
                  t={t}
                  landing={landingId === node.id}
                />
              )
            })}
          </AnimatePresence>
          <GhostCard sectionId={group.id} onAdd={() => addSlide(group.id)} label={t("addSlide")} />
        </div>
      </motion.section>
    )
  })

  const markdownLines = editor.operations.filter((operation) => operation.kind !== "del")

  return (
    <MotionConfig reducedMotion="user">
      <DragDropProvider onDragStart={handleDragStart} onDragOver={handleDragOver} onDragEnd={handleDragEnd}>
        <div className="document-surface storyboard-scroll flex-1 overflow-y-auto">
          <motion.main layout className={`storyboard-view storyboard-layout-${layout}`} data-layout={layout}>
            <header className="storyboard-header">
              <div className="storyboard-title-block">
                <h1>
                  <EditableText
                    value={deckName}
                    onChange={editor.updateDeckName}
                    editor={editor}
                    ariaLabel={t("deckNameField")}
                    placeholder={t("deckNamePlaceholder")}
                    className="storyboard-edit storyboard-deck-title-edit"
                  />
                </h1>
                <p>{t("slideCount", { count: slides.length })}<span aria-hidden="true"> · </span>{t("chapterCount", { count: groups.filter((group) => group.section).length })}</p>
              </div>
              <div className="storyboard-header-actions">
                <button type="button" className="storyboard-chrome-button" onClick={() => setDrawerOpen(true)} aria-expanded={drawerOpen}>
                  <Code2 aria-hidden="true" /> {t("markdown")}
                </button>
                <div className="storyboard-layout-toggle" role="group" aria-label={t("layoutLabel")}>
                  <button type="button" aria-pressed={layout === "grid"} onClick={() => selectLayout("grid")} aria-label={t("gridLayout")}><LayoutGrid aria-hidden="true" /></button>
                  <button type="button" aria-pressed={layout === "column"} onClick={() => selectLayout("column")} aria-label={t("columnLayout")}><List aria-hidden="true" /></button>
                </div>
              </div>
            </header>

            {slides.length === 0 && groups.length === 0 ? (
              <div className="storyboard-empty">
                <h2>{t("emptyTitle")}</h2>
                <p>{t("emptyDescription")}</p>
                <button type="button" className="storyboard-primary-button" onClick={addChapter}><Plus aria-hidden="true" />{t("createFirstChapter")}</button>
              </div>
            ) : renderedGroups}

            {(groups.length > 0 || slides.length > 0) && (
              <motion.button layout type="button" className="storyboard-add-chapter" onClick={addChapter}><Plus aria-hidden="true" />{t("addChapter")}</motion.button>
            )}

            <div className="storyboard-keyboard-help" aria-hidden="true">
              {t("keyboardHelp")}
            </div>
          </motion.main>

          <AnimatePresence>
            {editor.dirty && (
              <motion.div
                className="storyboard-sendbar"
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 18 }}
              >
                <div className="storyboard-dirty-summary"><span aria-hidden="true" />{t("unsentChanges", { count: editor.stats.added + editor.stats.deleted })}</div>
                <button type="button" className="storyboard-polish-toggle" role="switch" aria-checked={polish} onClick={togglePolish}>
                  <span data-on={polish || undefined}><i /></span>{t("polish")}
                </button>
                {chat.isLoading && <p className="storyboard-streaming-hint">{t("streamingHint")}</p>}
                <div className="storyboard-send-actions">
                  <button type="button" onClick={editor.undo} disabled={!editor.canUndo} aria-label={t("undo")} title={t("undoShortcut")}><Undo2 aria-hidden="true" /></button>
                  <button type="button" onClick={editor.redo} disabled={!editor.canRedo} aria-label={t("redo")} title={t("redoShortcut")}><Redo2 aria-hidden="true" /></button>
                  <button type="button" className="storyboard-discard-button" onClick={editor.discard}>{t("discard")}</button>
                  <button type="button" className="storyboard-send-button" onClick={() => void sendChanges()} disabled={sendDisabled} title={chat.isLoading ? t("sendDisabledStreaming") : undefined}>
                    <Send aria-hidden="true" />{sending ? t("sending") : t("sendChanges")}<kbd>⌘S</kbd>
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence>
            {drawerOpen && (
              <>
                <motion.button className="storyboard-drawer-scrim" type="button" aria-label={t("closeMarkdown")} onClick={() => setDrawerOpen(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
                <motion.aside className="storyboard-drawer" aria-label="specs/outline.md" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ duration: 0.25, ease: "easeOut" }}>
                  <header><div><span>{t("markdown")}</span><h2>specs/outline.md</h2></div><button type="button" onClick={() => setDrawerOpen(false)} aria-label={t("closeMarkdown")}><X aria-hidden="true" /></button></header>
                  <pre>{markdownLines.map((line, index) => <span key={`${index}-${line.text}`} data-changed={line.kind === "add" || undefined}>{line.text || " "}{"\n"}</span>)}</pre>
                </motion.aside>
              </>
            )}
          </AnimatePresence>
          <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
        </div>
        <DragOverlay dropAnimation={{ duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" }}>
          {activeSlide ? <SlidePreview slide={activeSlide} /> : null}
        </DragOverlay>
      </DragDropProvider>
    </MotionConfig>
  )
}
