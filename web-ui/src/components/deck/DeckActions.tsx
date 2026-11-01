// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * DeckActions — Visibility toggle (private / internal) with a publish confirmation.
 */

"use client"

import { useState } from "react"
import { Lock, Building2 } from "lucide-react"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import { useTranslations } from "next-intl"

interface DeckActionsProps {
  visibility?: "public" | "private"
  onVisibilityChange: (v: "public" | "private") => void
}

export function DeckActions({ visibility, onVisibilityChange }: DeckActionsProps) {
  const t = useTranslations("deckActions")
  const [showPublishConfirm, setShowPublishConfirm] = useState(false)
  const isPublic = visibility === "public"

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => { if (isPublic) onVisibilityChange("private"); else setShowPublishConfirm(true) }}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${
          isPublic ? "bg-green-500/10 text-green-400 border border-green-500/30" : "bg-muted/50 text-muted-foreground border border-border/40 hover:text-foreground"
        }`}
      >
        {isPublic ? <Building2 className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
        {isPublic ? t("internal") : t("private")}
      </button>

      {/* Publish confirmation */}
      <ConfirmDialog
        open={showPublishConfirm}
        onOpenChange={setShowPublishConfirm}
        title={t("shareInternallyTitle")}
        description={t("shareInternallyDescription")}
        confirmLabel={t("share")}
        variant="default"
        onConfirm={() => { onVisibilityChange("public"); setShowPublishConfirm(false) }}
      />
    </div>
  )
}
