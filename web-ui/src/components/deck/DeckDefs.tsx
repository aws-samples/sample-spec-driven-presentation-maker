// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

"use client"

import { useEffect, useState } from "react"

interface DefsData {
  version: number
  defs: string
}

export function DeckDefs({ defsUrl }: { defsUrl: string }) {
  const [defs, setDefs] = useState("")

  useEffect(() => {
    let cancelled = false
    fetch(defsUrl)
      .then((response) => response.ok ? response.json() as Promise<DefsData> : Promise.reject())
      .then((data) => {
        if (!cancelled && data.version === 1) setDefs(data.defs)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [defsUrl])

  return (
    <svg
      aria-hidden="true"
      focusable="false"
      style={{ position: "absolute", width: 0, height: 0 }}
      dangerouslySetInnerHTML={{ __html: defs }}
    />
  )
}
