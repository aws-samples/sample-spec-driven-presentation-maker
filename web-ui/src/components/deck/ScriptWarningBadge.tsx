// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * ScriptWarningBadge — header badge of an HTML deck whose slide scripts can send data
 * outside the deck (navigation, new tabs, external URLs, WebRTC). Those scripts run in
 * the Present tab and in the downloaded file; the title names the slides and kinds.
 */

"use client"

import { AlertTriangle } from "lucide-react"
import { useLocale, useTranslations } from "next-intl"
import type { ScriptWarning, ScriptWarningKind } from "@/services/deckService"

const KIND_KEYS: Record<ScriptWarningKind, "navigation" | "popup" | "externalUrl" | "webrtc"> = {
  navigation: "navigation",
  popup: "popup",
  "external-url": "externalUrl",
  webrtc: "webrtc",
}

export function ScriptWarningBadge({ warnings }: { warnings: ScriptWarning[] }) {
  const t = useTranslations("carousel")
  const locale = useLocale()
  const list = new Intl.ListFormat(locale, { style: "long", type: "conjunction" })
  const slugs = list.format(warnings.map((w) => w.slug))
  const kinds = list.format(
    (Object.keys(KIND_KEYS) as ScriptWarningKind[])
      .filter((kind) => warnings.some((w) => w.kinds.includes(kind)))
      .map((kind) => t(`scriptKind.${KIND_KEYS[kind]}`)),
  )
  const detail = t("scriptWarningDetail", { slugs, kinds })
  return (
    <span
      role="img"
      className="inline-flex items-center gap-1.5 text-xs text-brand-amber px-2 py-1.5"
      title={detail}
      aria-label={detail}
    >
      <AlertTriangle className="h-3.5 w-3.5" />
      <span aria-hidden="true">{t("scriptWarning")}</span>
    </span>
  )
}
