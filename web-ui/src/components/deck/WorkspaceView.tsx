// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * WorkspaceView — Full-width slide preview grid with toolbar.
 *
 * Displays when a deck is selected. Shows slide thumbnails in a responsive
 * grid with Share/PPTX action buttons in a toolbar.
 *
 * @param props.deck - Deck detail with slides
 * @param props.onShare - Callback to open share dialog
 * @param props.onDownload - Callback to download PPTX
 */

"use client"

import { useState } from "react"
import { DeckDetail } from "@/services/deckService"
import { Share2, Download, Layers } from "lucide-react"
import { PreviewImage } from "@/components/ui/PreviewImage"
import { useAuth } from "@/hooks/useAuth"
import { formatDate } from "@/lib/utils"
import { useTranslations } from "next-intl"
import { useLocale } from "@/i18n/LocaleProvider"

interface WorkspaceViewProps {
  deck: DeckDetail
  onShare?: () => void
  onDownload?: () => void
}

export function WorkspaceView({ deck, onShare, onDownload }: WorkspaceViewProps) {
  const slideCount = deck.slides?.length || 0
  const auth = useAuth()
  const t = useTranslations("workspace")
  const { locale } = useLocale()

  return (
    <div className="h-full flex flex-col animate-card-in">
      {/* Toolbar */}
      <div className="flex-none flex items-center justify-between px-5 sm:px-8 py-3 border-b border-border">
        <div className="text-xs text-foreground-muted font-medium">
          {t("slideCount", { count: slideCount })}
          {deck.updatedAt && (
            <>
              <span className="mx-1.5 opacity-40">·</span>
              {t("lastEdited", { date: formatDate(deck.updatedAt, locale) })}
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {onShare && (
            <button
              onClick={onShare}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-border text-foreground-secondary hover:text-foreground hover:border-border-hover hover:bg-background-hover transition-all"
            >
              <Share2 className="h-3 w-3" />
              {t("share")}
            </button>
          )}
          {onDownload && deck.pptxUrl && (
            <a
              href={deck.pptxUrl}
              download
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-border text-foreground-secondary hover:text-foreground hover:border-border-hover hover:bg-background-hover transition-all no-underline"
            >
              <Download className="h-3 w-3" />
              PPTX
            </a>
          )}
        </div>
      </div>

      {/* Slide grid */}
      <div className="flex-1 overflow-y-auto px-5 sm:px-8 py-6">
        {slideCount > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 max-w-5xl">
            {deck.slides.map((slide, i) => (
              <WorkspaceSlideCard
                key={slide.slug}
                slide={slide}
                index={i}
                deckId={deck.deckId}
                idToken={auth.user?.id_token}
                t={t}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Layers className="h-10 w-10 text-foreground-muted/20 mb-4" />
            <p className="text-sm text-foreground-muted">
              {t("noSlides")}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

/** Per-slide card that detects natural image dimensions for aspect ratio. */
function WorkspaceSlideCard({ slide, index, deckId, idToken, t }: {
  slide: { slug: string; previewUrl?: string | null }
  index: number
  deckId: string
  idToken?: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any
}) {
  const [aspectRatio, setAspectRatio] = useState("16/9")

  return (
    <div
      className="animate-card-in rounded-xl overflow-hidden border border-border bg-card cursor-pointer group hover:-translate-y-[2px] hover:border-border-hover hover:shadow-[0_6px_24px_oklch(0_0_0/40%)] transition-all duration-300"
      style={{ "--delay": `${index * 50}ms` } as React.CSSProperties}
    >
      <div className="relative bg-muted/30" style={{ aspectRatio }}>
        {slide.previewUrl ? (
          <PreviewImage
            src={slide.previewUrl}
            deckId={deckId}
            slug={slide.slug}
            idToken={idToken}
            alt={t("slideAlt", { number: index + 1 })}
            className="absolute inset-0 w-full h-full object-contain"
            onLoad={(e: React.SyntheticEvent<HTMLImageElement>) => {
              const img = e.currentTarget
              if (img.naturalWidth > 0 && img.naturalHeight > 0) {
                setAspectRatio(`${img.naturalWidth}/${img.naturalHeight}`)
              }
            }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Layers className="h-6 w-6 text-foreground-muted/20" />
          </div>
        )}
        <div className="absolute bottom-2 right-2.5 text-[11px] font-medium text-white/20">
          {index + 1}
        </div>
      </div>
    </div>
  )
}
