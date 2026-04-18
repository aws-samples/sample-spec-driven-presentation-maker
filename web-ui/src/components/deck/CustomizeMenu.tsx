// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * CustomizeMenu — Dropdown for personal resource actions.
 *
 * Emits callbacks for the parent to:
 * - open chat with a preset prompt (New Style)
 * - open template upload dialog (Upload Template)
 * - open resource list dialog (My Styles / My Templates)
 */

"use client"

import { ChevronDown, Palette, Upload, Library, Files } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface CustomizeMenuProps {
  onNewStyle: () => void
  onUploadTemplate: () => void
  onMyStyles: () => void
  onMyTemplates: () => void
}

export function CustomizeMenu({
  onNewStyle, onUploadTemplate, onMyStyles, onMyTemplates,
}: CustomizeMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="inline-flex items-center gap-1.5 px-4 py-2 text-[12px] font-semibold rounded-lg border border-border/60 text-foreground-secondary hover:text-foreground hover:bg-background-hover transition-all"
          aria-label="Customize resources"
        >
          Customize
          <ChevronDown className="h-3 w-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuItem onClick={onNewStyle}>
          <Palette className="h-3.5 w-3.5 mr-2" />
          New Style
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onUploadTemplate}>
          <Upload className="h-3.5 w-3.5 mr-2" />
          Upload Template
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={onMyStyles}>
          <Library className="h-3.5 w-3.5 mr-2" />
          My Styles
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onMyTemplates}>
          <Files className="h-3.5 w-3.5 mr-2" />
          My Templates
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
