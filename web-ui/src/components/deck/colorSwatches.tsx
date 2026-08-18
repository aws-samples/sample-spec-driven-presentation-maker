// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React from "react"

const HEX_RE = /(#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))\b/g

/** Render accessible inline color swatches next to HEX codes in text. */
export function renderColorSwatches(text: string): (string | React.ReactElement)[] {
  return text.split(HEX_RE).map((part, index) => {
    if (!/^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.test(part)) return part
    return (
      <span key={index} className="inline-flex items-center gap-1">
        <span
          className="inline-block w-3 h-3 rounded-full border border-foreground/20 flex-none"
          style={{ backgroundColor: part }}
          aria-label={`Color ${part}`}
        />
        <code className="text-xs px-1 py-0.5 rounded bg-foreground/[0.06]">{part}</code>
      </span>
    )
  })
}
