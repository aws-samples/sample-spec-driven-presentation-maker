// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * PreviewImage — <img> wrapper that retries on 403 (expired signed URL).
 *
 * On error, fetches a fresh preview URL from the API and retries once.
 */

"use client"

import { useState, useCallback, ImgHTMLAttributes } from "react"

interface PreviewImageProps extends ImgHTMLAttributes<HTMLImageElement> {
  /** Deck ID for refreshing the URL via API. */
  deckId?: string
  /** Slide ID (e.g. "slide_01") for refreshing. */
  slug?: string
  /** Cognito ID token for API auth. */
  idToken?: string
}

export function PreviewImage({ deckId, slug, idToken, src, onError, ...props }: PreviewImageProps) {
  const [currentSrc, setCurrentSrc] = useState(src)
  const [retried, setRetried] = useState(false)

  const handleError = useCallback(async (e: React.SyntheticEvent<HTMLImageElement>) => {
    if (retried || !deckId || !idToken) {
      onError?.(e)
      return
    }
    setRetried(true)
    try {
      const resp = await fetch("/aws-exports.json")
      const config = await resp.json()
      const deckResp = await fetch(`${config.apiBaseUrl}decks/${deckId}`, {
        headers: { Authorization: `Bearer ${idToken}` },
      })
      if (!deckResp.ok) return
      const deck = await deckResp.json()
      const slide = deck.slides?.find((s: { slug: string; previewUrl?: string }) => s.slug === slug)
      if (slide?.previewUrl) {
        setCurrentSrc(slide.previewUrl)
      }
    } catch {
      onError?.(e)
    }
  }, [deckId, slug, idToken, retried, onError])

  return <img {...props} src={currentSrc || src} onError={handleError} />
}
