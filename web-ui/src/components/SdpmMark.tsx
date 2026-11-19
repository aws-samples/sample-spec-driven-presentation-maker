// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * SdpmMark — the SDPM mark without its app-icon tile (public/icon.svg is the tiled form).
 *
 * A 16:9 slide frame holds a green and an amber face; the violet block breaks out over
 * the top-left corner, tilted, above its faint-violet slot. Colours come from the
 * --mark-* tokens in globals.css, so the mark follows the dark/light theme.
 *
 * @param props.className - Size and layout classes for the <svg>
 * @returns Decorative inline SVG (aria-hidden; label the surrounding link instead)
 */

import { useId } from "react"

/** The slot and the falling block share one shape: a rounded 7.7 × 7.45 face. */
const SLOT = { x: 3.9, y: 10.9, width: 7.7, height: 7.45, rx: 0.8 }
const BLOCK_TRANSFORM = "translate(-1 -4.6) rotate(-12 7.75 14.625)"

export function SdpmMark({ className }: { className?: string }) {
  // useId may contain characters that are awkward inside url(#…); keep it to [A-Za-z0-9_-].
  const maskId = `sdpm-mark-cut-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`

  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" focusable="false">
      <defs>
        {/* Cuts a 1.25 gap around the falling block out of the frame and the faces below it. */}
        <mask id={maskId} maskUnits="userSpaceOnUse" x="-4" y="-4" width="32" height="32">
          <rect x="-4" y="-4" width="32" height="32" fill="#fff" />
          <rect {...SLOT} transform={BLOCK_TRANSFORM} fill="#000" stroke="#000" strokeWidth="2.5" strokeLinejoin="round" />
        </mask>
      </defs>
      <g transform="translate(0 -1.3)">
        <g mask={`url(#${maskId})`}>
          <rect x="2" y="9" width="20" height="11.25" rx="2.3" fill="none" strokeWidth="1.9" style={{ stroke: "var(--mark-frame)" }} />
          <rect {...SLOT} style={{ fill: "var(--mark-visual)", opacity: "var(--mark-slot-opacity)" }} />
          <rect x="12.6" y="10.9" width="7.5" height="3.225" rx="0.8" style={{ fill: "var(--mark-content)" }} />
          <rect x="12.6" y="15.125" width="7.5" height="3.225" rx="0.8" style={{ fill: "var(--mark-data)" }} />
        </g>
        <rect {...SLOT} transform={BLOCK_TRANSFORM} style={{ fill: "var(--mark-visual)" }} />
      </g>
    </svg>
  )
}
