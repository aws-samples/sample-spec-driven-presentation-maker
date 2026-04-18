// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * CustomizeMenu — Dropdown for personal resource actions.
 *
 * UX highlights:
 * - Tooltip on trigger explaining what Customize means
 * - Two-section menu with description per item (not icon only)
 * - Keyboard / screen reader ready via radix-ui dropdown
 */

"use client"

import { ChevronDown, Palette, Upload, Library, Files, Wand2 } from "lucide-react"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip, TooltipContent, TooltipTrigger,
} from "@/components/ui/tooltip"

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
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <button
              className="inline-flex items-center gap-1.5 px-4 py-2 text-[12px] font-semibold rounded-lg border border-border/60 text-foreground-secondary hover:text-foreground hover:bg-background-hover transition-all focus:outline-none focus:ring-2 focus:ring-brand-teal/30"
              aria-label="Customize: create styles or upload templates"
            >
              <Wand2 className="h-3.5 w-3.5" />
              Customize
              <ChevronDown className="h-3 w-3 opacity-60" />
            </button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent side="bottom">Create styles and upload templates</TooltipContent>
      </Tooltip>

      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-foreground-muted">
          Create
        </DropdownMenuLabel>
        <DropdownMenuItem onClick={onNewStyle} className="gap-3 py-2">
          <Palette className="h-4 w-4 text-brand-teal" />
          <div className="flex flex-col">
            <span className="text-sm">New Style</span>
            <span className="text-[11px] text-foreground-muted">Design a look with the assistant</span>
          </div>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onUploadTemplate} className="gap-3 py-2">
          <Upload className="h-4 w-4 text-blue-400" />
          <div className="flex flex-col">
            <span className="text-sm">Upload Template</span>
            <span className="text-[11px] text-foreground-muted">Bring your own .pptx</span>
          </div>
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-foreground-muted">
          Manage
        </DropdownMenuLabel>
        <DropdownMenuItem onClick={onMyStyles} className="gap-3 py-2">
          <Library className="h-4 w-4 text-foreground-muted" />
          <span className="text-sm">My Styles</span>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onMyTemplates} className="gap-3 py-2">
          <Files className="h-4 w-4 text-foreground-muted" />
          <span className="text-sm">My Templates</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
