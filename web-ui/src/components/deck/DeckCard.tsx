// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * DeckCard — Editorial card with mesh gradient, teal edge glow, and staggered entrance.
 *
 * Uses `<div role="button">` instead of `<button>` to allow nested interactive
 * elements (favorite toggle, context menu) without HTML nesting violations.
 *
 * Context menu uses shadcn DropdownMenu (Radix UI) for proper a11y:
 * Escape closes, focus trapping, aria attributes are automatic.
 *
 * @param props.deck - Deck summary data
 * @param props.index - Position in grid for staggered animation delay
 * @param props.isFavorite - Whether this deck is favorited by current user
 * @param props.isOwner - Whether current user owns this deck
 * @param props.onOpen - Callback when card is clicked to open workspace
 * @param props.onToggleFavorite - Callback to toggle favorite status
 * @param props.onDelete - Callback to delete deck (owner only)
 */

"use client"

import { DeckSummary } from "@/services/deckService"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Layers, Star, MoreHorizontal, Trash2, Building2, Lock, Share2, Download, Users, Link, FolderOpen } from "lucide-react"
import { isTauri } from "@/lib/platform"


interface DeckCardProps {
  deck: DeckSummary
  index: number
  isFavorite?: boolean
  isOwner?: boolean
  onOpen: (deckId: string) => void
  onToggleFavorite?: (deckId: string, action: "add" | "remove") => void
  onDelete?: (deckId: string) => void
  onToggleVisibility?: (deckId: string, visibility: "public" | "private") => void
  onShare?: (deckId: string) => void
  onDownload?: (deckId: string) => void
}

/**
 * Format an ISO timestamp as a relative date string.
 *
 * @param iso - ISO 8601 timestamp
 * @returns Human-readable relative date (e.g. "Today", "3d ago", "Feb 14")
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

/**
 * Generate a deterministic mesh gradient from a deck ID.
 * Combines multiple radial gradients for an organic, unique appearance.
 *
 * @param id - Deck identifier used as seed
 * @returns CSS background value with layered gradients
 */
function meshGradient(id: string): string {
  const seed = id.charCodeAt(0) * 47 + (id.charCodeAt(id.length - 1) || 0) * 31
  const h1 = seed % 360
  const h2 = (h1 + 60) % 360
  const h3 = (h1 + 180) % 360
  return [
    `radial-gradient(ellipse at 20% 20%, oklch(0.28 0.04 ${h1}) 0%, transparent 50%)`,
    `radial-gradient(ellipse at 80% 80%, oklch(0.22 0.03 ${h2}) 0%, transparent 50%)`,
    `radial-gradient(ellipse at 60% 30%, oklch(0.18 0.02 ${h3}) 0%, transparent 60%)`,
    `linear-gradient(135deg, oklch(0.14 0.01 ${h1}) 0%, oklch(0.11 0.005 260) 100%)`,
  ].join(", ")
}

export function DeckCard({ deck, index, isFavorite = false, isOwner = true, onOpen, onToggleFavorite, onDelete, onToggleVisibility, onShare, onDownload }: DeckCardProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(deck.deckId)}
      onKeyDown={(e) => { if (e.key === "Enter") onOpen(deck.deckId) }}
      className="animate-card-in group relative rounded-xl overflow-hidden bg-card border border-border hover:border-border-hover hover:-translate-y-[3px] transition-all duration-350 cursor-pointer hover:shadow-[0_8px_40px_oklch(0_0_0/50%)]"
      style={{ "--delay": `${index * 60}ms` } as React.CSSProperties}
    >
      {/* Teal edge glow on hover */}
      <div className="card-glow rounded-xl" />

      {/* Action buttons */}
      <div className="absolute top-2.5 right-2.5 z-10 flex items-center gap-0.5">
        <button
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            navigator.vibrate?.(10)
            onToggleFavorite?.(deck.deckId, isFavorite ? "remove" : "add")
          }}
          className={`p-1 transition-all flex items-center justify-center drop-shadow-[0_1px_2px_oklch(0_0_0/60%)] ${
            isFavorite
              ? "text-brand-amber"
              : "text-white/30 sm:opacity-0 sm:group-hover:opacity-100 hover:text-brand-amber/70"
          }`}
          aria-label={isFavorite ? "Remove from favorites" : "Add to favorites"}
        >
          <Star className={`h-3.5 w-3.5 ${isFavorite ? "fill-current" : ""}`} strokeWidth={isFavorite ? 0 : 1.5} />
        </button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              onClick={(e) => { e.preventDefault(); e.stopPropagation() }}
              className="p-1 transition-all flex items-center justify-center drop-shadow-[0_1px_2px_oklch(0_0_0/60%)] text-white/30 sm:opacity-0 sm:group-hover:opacity-100 hover:text-white/70"
              aria-label="Deck actions"
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-44"
            style={{ background: "oklch(0.14 0.005 260 / 95%)", backdropFilter: "blur(16px)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <DropdownMenuItem
              onClick={() => navigator.clipboard.writeText(`${window.location.origin}/decks#${deck.deckId}`)}
            >
              <Link className="h-3.5 w-3.5" />
              Copy URL
            </DropdownMenuItem>
            {onDownload && (
              <DropdownMenuItem onClick={() => onDownload(deck.deckId)}>
                {isTauri ? <FolderOpen className="h-3.5 w-3.5" /> : <Download className="h-3.5 w-3.5" />}
                {isTauri ? "Open PPTX" : "Download PPTX"}
              </DropdownMenuItem>
            )}
            {!isTauri && isOwner && onToggleVisibility && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => onToggleVisibility(deck.deckId, deck.visibility === "public" ? "private" : "public")}
                >
                  {deck.visibility === "public" ? <Lock className="h-3.5 w-3.5" /> : <Building2 className="h-3.5 w-3.5" />}
                  {deck.visibility === "public" ? "Make Private" : "Make Internal"}
                </DropdownMenuItem>
              </>
            )}
            {!isTauri && isOwner && onShare && (
              <DropdownMenuItem onClick={() => onShare(deck.deckId)}>
                <Share2 className="h-3.5 w-3.5" />
                Share
              </DropdownMenuItem>
            )}
            {isOwner && onDelete && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => onDelete(deck.deckId)}
                  className="text-red-400 focus:text-red-400 focus:bg-red-500/10"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Delete
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Thumbnail */}
      <div className="aspect-[16/9.5] relative overflow-hidden">
        {deck.thumbnailUrl ? (
          <img
            src={deck.thumbnailUrl}
            alt={`Preview of ${deck.name}`}
            className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-700 ease-out"
          />
        ) : (
          <div className="w-full h-full" style={{ background: meshGradient(deck.deckId) }}>
            <div
              className="absolute inset-0 opacity-[0.03]"
              style={{
                backgroundImage: "linear-gradient(var(--foreground) 1px, transparent 1px), linear-gradient(90deg, var(--foreground) 1px, transparent 1px)",
                backgroundSize: "40px 40px",
              }}
            />
          </div>
        )}
        {/* Badges */}
        <div className="absolute bottom-2.5 left-3 flex items-center gap-1.5">
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium text-foreground-secondary bg-black/50 backdrop-blur-md">
            <Layers className="h-2.5 w-2.5" />
            {deck.slideCount}
          </div>
          {!isTauri && ((deck.visibility || "private") === "public" ? (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium backdrop-blur-md"
              style={{ background: "oklch(0.55 0.15 160 / 0.35)", color: "oklch(0.9 0.1 160)" }}>
              <Building2 className="h-2.5 w-2.5" />
              Internal
            </div>
          ) : (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium text-foreground-secondary bg-black/50 backdrop-blur-md">
              <Lock className="h-2.5 w-2.5" />
              Private
            </div>
          ))}
          {!isTauri && deck.collaborators && deck.collaborators.length > 0 && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium backdrop-blur-md"
              style={{ background: "oklch(0.55 0.12 220 / 0.35)", color: "oklch(0.9 0.08 220)" }}
              title={deck.collaborators.join(", ")}
            >
              <Users className="h-2.5 w-2.5" />
              {deck.collaborators.length}
            </div>
          )}
        </div>
      </div>

      {/* Meta */}
      <div className="px-3.5 py-3">
        <h3 className="text-[13px] font-semibold text-foreground truncate leading-snug tracking-[-0.01em]">
          {deck.name}
        </h3>
        <div className="flex items-center gap-2 mt-2 text-[12px] text-foreground/50">
          {deck.owner && <span>{deck.owner}</span>}
          {deck.owner && deck.updatedAt && <span className="opacity-40">·</span>}
          {deck.updatedAt && <span>{formatDate(deck.updatedAt)}</span>}
        </div>
      </div>
    </div>
  )
}
