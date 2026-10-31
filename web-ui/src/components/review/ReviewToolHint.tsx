// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** ReviewToolHint — sticky pill at the top of the preview while the tool is on, until the first frame (R1.3). */

"use client"

import { useTranslations } from "next-intl"

export function ReviewToolHint() {
  const t = useTranslations("review")
  return (
    <div className="pointer-events-none sticky top-0 z-20 -mb-3 flex justify-center">
      <div className="flex items-center gap-3 rounded-full bg-human px-3 py-1 text-xs text-human-ink shadow-[0_6px_18px_oklch(0_0_0/35%)]" role="status">
        {t("hintDrag")}
        <span className="opacity-75" aria-hidden>·</span>
        {t("hintClick")}
        <span className="opacity-75" aria-hidden>·</span>
        {t("hintExit")}
      </div>
    </div>
  )
}
