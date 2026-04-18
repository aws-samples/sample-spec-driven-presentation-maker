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

import { DeckDetail } from "@/services/deckService"
import { Share2, Download, Layers } from "lucide-react"
import { PreviewImage } from "@/components/ui/PreviewImage"
import { useAuth } from "react-oidc-context"

interface WorkspaceViewProps {
  deck: DeckDetail
  onShare?: () => void
  onDownload?: () => void
}

/**
 * Format an ISO timestamp as a relative date string.
 *
 * @param iso - ISO 8601 timestamp
 * @returns Human-readable relative date
 */
function formatDate(iso: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  const now = new Date()
  const diff = Math.floor((now.getTime() - d.getTime()) / 86400000)
  if (diff === 0) return "Today"
  if (diff === 1) return "Yesterday"
  if (diff < 7) return `${diff}d ago`
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

export function WorkspaceView({ deck, onShare, onDownload }: WorkspaceViewProps) {
  const slideCount = deck.slides?.length || 0
  const auth = useAuth()

  return (
    <div className="h-full flex flex-col animate-card-in">
      {/* Toolbar */}
      <div className="flex-none flex items-center justify-between px-5 sm:px-8 py-3 border-b border-border">
        <div className="text-[12px] text-foreground-muted font-medium">
          {slideCount} {slideCount === 1 ? "slide" : "slides"}
          {deck.updatedAt && (
            <>
              <span className="mx-1.5 opacity-40">·</span>
              Last edited {formatDate(deck.updatedAt)}
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {onShare && (
            <button
              onClick={onShare}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded-lg border border-border text-foreground-secondary hover:text-foreground hover:border-border-hover hover:bg-background-hover transition-all"
            >
              <Share2 className="h-3 w-3" />
              Share
            </button>
          )}
          {onDownload && deck.pptxUrl && (
            <a
              href={deck.pptxUrl}
              download
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded-lg border border-border text-foreground-secondary hover:text-foreground hover:border-border-hover hover:bg-background-hover transition-all no-underline"
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
              <div
                key={slide.slug}
                className="animate-card-in rounded-xl overflow-hidden border border-border bg-card cursor-pointer group hover:-translate-y-[2px] hover:border-border-hover hover:shadow-[0_6px_24px_oklch(0_0_0/40%)] transition-all duration-300"
                style={{ "--delay": `${i * 50}ms` } as React.CSSProperties}
              >
                <div className="aspect-[16/9] relative bg-muted/30">
                  {slide.previewUrl ? (
                    <PreviewImage
                      src={slide.previewUrl}
                      deckId={deck.deckId}
                      slug={slide.slug}
                      idToken={auth.user?.id_token}
                      alt={`Slide ${i + 1}`}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <Layers className="h-6 w-6 text-foreground-muted/20" />
                    </div>
                  )}
                  <div className="absolute bottom-2 right-2.5 text-[10px] font-medium text-white/20">
                    {i + 1}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Layers className="h-10 w-10 text-foreground-muted/20 mb-4" />
            <p className="text-[13px] text-foreground-muted">
              No slides yet. Use the chat to create slides.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
