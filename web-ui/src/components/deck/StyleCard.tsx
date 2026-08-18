// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * StyleCard — Individual style card with iframe cover preview.
 *
 * Used in the art-direction style gallery. Renders the style's cover HTML
 * in a scaled sandboxed iframe with an optional pin toggle.
 */

"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Star } from "lucide-react"
import type { StyleEntry } from "@/services/deckService"
import { buildCoverDoc } from "@/components/StyleSlidePreview"
import { useTranslations } from "next-intl"

export function StyleCard({ style, index, onClick, onPin }: { style: StyleEntry; index: number; onClick: (name: string) => void; onPin?: (name: string) => void }) {
  const t = useTranslations("stylePicker")
  const iframeWidth = 1920
  const iframeHeight = 1080
  const cardRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.2)
  const [bouncing, setBouncing] = useState(false)

  useEffect(() => {
    const el = cardRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      setScale(entry.contentRect.width / iframeWidth)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const handlePin = (e: React.MouseEvent) => {
    e.stopPropagation()
    setBouncing(true)
    setTimeout(() => setBouncing(false), 300)
    onPin?.(style.name)
  }

  const coverDoc = useMemo(() => style.html ? buildCoverDoc(style.html) : "", [style.html])

  return (
    <div
      ref={cardRef}
      role="button"
      tabIndex={0}
      onClick={() => onClick(style.name)}
      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(style.name) } }}
      className="group text-left rounded-xl border border-border overflow-hidden transition-all duration-300 hover:border-border-hover hover:-translate-y-[2px] hover:shadow-[var(--shadow-lift)] motion-reduce:hover:translate-y-0 focus:outline-none focus:ring-2 focus:ring-ring animate-[card-in_0.5s_ease_both] cursor-pointer"
      style={{ animationDelay: `${index * 60}ms` }}
      aria-label={t("previewStyleAria", { name: style.name })}
    >
      <div className="relative overflow-hidden bg-black/20" style={{ height: iframeHeight * scale }}>
        {coverDoc ? (
          <iframe
            srcDoc={coverDoc}
            sandbox=""
            title={style.name}
            style={{
              width: iframeWidth,
              height: iframeHeight,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
              border: "none",
              pointerEvents: "none",
            }}
            tabIndex={-1}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-foreground-muted text-xs">
            No preview
          </div>
        )}
        <div className="absolute inset-0 bg-brand-teal/0 group-hover:bg-brand-teal/5 transition-colors duration-300" />
        {/* Pin button */}
        {onPin && (
          <button
            onClick={handlePin}
            className={`absolute top-2 right-2 w-7 h-7 rounded-lg flex items-center justify-center transition-all duration-150 ${
              style.pinned
                ? "opacity-100 bg-black/40 text-brand-teal"
                : "opacity-0 group-hover:opacity-100 bg-black/40 text-white/30 hover:text-white/60"
            }`}
            style={{ transform: bouncing ? "scale(1.3)" : "scale(1)", transition: "transform 300ms ease-out" }}
            aria-label={style.pinned ? t("unpinAria", { name: style.name }) : t("pinAria", { name: style.name })}
          >
            <Star className="h-3.5 w-3.5" fill={style.pinned ? "currentColor" : "none"} />
          </button>
        )}
      </div>
      <div className="px-3 py-2.5 border-t border-border">
        <div className="flex items-center gap-1.5">
          <p className="text-sm font-medium text-foreground group-hover:text-brand-teal transition-colors truncate">{style.name}</p>
          {style.source === "user" && (
            <span className="flex-none text-[11px] px-1.5 py-0.5 rounded-full bg-brand-teal/10 text-brand-teal font-medium">{t("custom")}</span>
          )}
        </div>
        {style.description && (
          <p className="text-xs text-foreground-muted mt-0.5 line-clamp-1">{style.description}</p>
        )}
      </div>
    </div>
  )
}
