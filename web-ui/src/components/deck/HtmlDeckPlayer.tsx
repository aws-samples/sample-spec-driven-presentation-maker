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

import { useEffect, useRef, useState } from "react"
import { useTranslations } from "next-intl"
import { previewIdentity } from "@/lib/preview"

/** The iframe sandbox tokens of the in-app player (exported for tests). */
export const HTML_PLAYER_SANDBOX = "allow-scripts allow-popups"

/** A request to show a slide; a new `seq` repeats the jump to the same index. */
export interface HtmlPlayerSlide {
  /** 0-based slide index in the deck. */
  index: number
  seq: number
}

interface HtmlDeckPlayerProps {
  htmlUrl: string
  /** Canvas size in CSS px; sets the player's aspect ratio. */
  slideSize?: { width: number; height: number }
  deckName?: string
  /** Slide to show (thumbnail click, search jump). */
  slide?: HtmlPlayerSlide | null
}

function withoutFragment(url: string): string {
  return url.split("#")[0]
}

/**
 * The deck URL opened at a slide. reveal.js runs with `hash: true`, so `#/<index>`
 * selects the slide; a fragment does not change an S3 presigned URL's signature.
 */
export function deckUrlAtSlide(url: string, index: number | undefined): string {
  return index ? `${withoutFragment(url)}#/${index}` : withoutFragment(url)
}

export function HtmlDeckPlayer({ htmlUrl, slideSize, deckName, slide }: HtmlDeckPlayerProps) {
  const t = useTranslations("carousel")
  const width = slideSize?.width ?? 1920
  const height = slideSize?.height ?? 1080
  const frameRef = useRef<HTMLIFrameElement>(null)
  const loadedRef = useRef(false)

  // A re-signed URL for the same build must not reload the deck (and lose the
  // current slide); a new build does reload it.
  const [src, setSrc] = useState(() => deckUrlAtSlide(htmlUrl, slide?.index))
  useEffect(() => {
    setSrc((current) => {
      if (previewIdentity(withoutFragment(current)) === previewIdentity(htmlUrl)) return current
      loadedRef.current = false
      return htmlUrl
    })
  }, [htmlUrl])

  // The initial src already opens the requested slide; later requests go to the
  // loaded deck through reveal.js's postMessage API. The sandboxed deck has an
  // opaque origin, so the target origin cannot be narrower than "*"; the message
  // carries only a slide index.
  const initialSeq = useRef(slide?.seq)
  const index = slide?.index
  const seq = slide?.seq
  useEffect(() => {
    if (index === undefined || seq === initialSeq.current) return
    initialSeq.current = seq
    const target = frameRef.current?.contentWindow
    if (loadedRef.current && target) {
      target.postMessage(JSON.stringify({ method: "slide", args: [index] }), "*")
    } else {
      setSrc((current) => deckUrlAtSlide(current, index))
    }
  }, [index, seq])

  return (
    <div
      className="slide-shadow mx-auto w-full overflow-hidden rounded-lg bg-black"
      style={{ aspectRatio: `${width}/${height}`, maxWidth: `calc((100vh - 170px) * ${width / height})` }}
    >
      <iframe
        ref={frameRef}
        src={src}
        title={deckName ? t("playerTitleNamed", { name: deckName }) : t("playerTitle")}
        sandbox={HTML_PLAYER_SANDBOX}
        allow="fullscreen *"
        referrerPolicy="no-referrer"
        onLoad={() => { loadedRef.current = true }}
        className="h-full w-full border-0"
      />
    </div>
  )
}
