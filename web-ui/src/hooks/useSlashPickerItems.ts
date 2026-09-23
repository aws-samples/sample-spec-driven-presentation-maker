// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * useSlashPickerItems — Lazy, lifetime-cached template/style candidates.
 */

"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import type { PickerItem } from "@/lib/slashToken"
import { fetchStyles, fetchTemplates } from "@/services/deckService"

interface UseSlashPickerItemsResult {
  items: PickerItem[]
  loading: boolean
  ensure: () => Promise<PickerItem[]>
}

export function useSlashPickerItems(idToken?: string): UseSlashPickerItemsResult {
  const [items, setItems] = useState<PickerItem[]>([])
  const [loading, setLoading] = useState(false)
  const promiseRef = useRef<Promise<PickerItem[]> | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const ensure = useCallback((): Promise<PickerItem[]> => {
    if (!promiseRef.current) {
      setLoading(true)
      promiseRef.current = Promise.all([
        fetchTemplates(idToken ?? ""),
        fetchStyles(idToken ?? ""),
      ])
        .then(([templates, styles]) => {
          const templateItems = templates.map((template) => ({
            kind: "template" as const,
            name: template.name,
            description: template.description,
            source: template.source,
            pinned: false,
            themeColors: template.theme_colors,
            fonts: template.fonts,
            layoutCount: template.layout_count,
          }))
          const styleItems = styles.map((style) => ({
            kind: "style" as const,
            name: style.name,
            description: style.description,
            source: style.source,
            pinned: style.pinned,
            html: style.html,
          }))
          return [...templateItems, ...styleItems]
        })
        .catch(() => [])
        .then((nextItems) => {
          if (mountedRef.current) setItems(nextItems)
          return nextItems
        })
        .finally(() => {
          if (mountedRef.current) setLoading(false)
        })
    }

    return promiseRef.current
  }, [idToken])

  return { items, loading, ensure }
}
