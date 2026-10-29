// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * HtmlDeckPlayer — In-app view of an HTML deck (output.html, reveal.js).
 *
 * The deck runs its own scripts, so it is isolated in a sandboxed iframe:
 * `allow-scripts allow-popups` only. Never add `allow-same-origin` (the deck
 * would share the app's origin and storage), `allow-modals` or
 * `allow-popups-to-escape-sandbox`. Cloud URLs are S3 presigned URLs on a
 * different origin from the app; local URLs are served with a CSP `sandbox`
 * header as well.
 */

"use client"

import { useEffect, useState } from "react"
import { useTranslations } from "next-intl"
import { previewIdentity } from "@/lib/preview"

/** The iframe sandbox tokens of the in-app player (exported for tests). */
export const HTML_PLAYER_SANDBOX = "allow-scripts allow-popups"

interface HtmlDeckPlayerProps {
  htmlUrl: string
  /** Canvas size in CSS px; sets the player's aspect ratio. */
  slideSize?: { width: number; height: number }
  deckName?: string
}

export function HtmlDeckPlayer({ htmlUrl, slideSize, deckName }: HtmlDeckPlayerProps) {
  const t = useTranslations("carousel")
  const width = slideSize?.width ?? 1920
  const height = slideSize?.height ?? 1080

  // A re-signed URL for the same build must not reload the deck (and lose the
  // current slide); a new build does reload it.
  const [src, setSrc] = useState(htmlUrl)
  useEffect(() => {
    setSrc((current) => (previewIdentity(current) === previewIdentity(htmlUrl) ? current : htmlUrl))
  }, [htmlUrl])

  return (
    <div
      className="slide-shadow mx-auto w-full overflow-hidden rounded-lg bg-black"
      style={{ aspectRatio: `${width}/${height}`, maxWidth: `calc((100vh - 170px) * ${width / height})` }}
    >
      <iframe
        src={src}
        title={deckName ? t("playerTitleNamed", { name: deckName }) : t("playerTitle")}
        sandbox={HTML_PLAYER_SANDBOX}
        allow="fullscreen *"
        referrerPolicy="no-referrer"
        className="h-full w-full border-0"
      />
    </div>
  )
}
