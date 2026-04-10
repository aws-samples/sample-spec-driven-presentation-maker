// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * McpStatusBar — Displays MCP server connection status at the start of a chat response.
 *
 * Two visual modes:
 * - All OK: Single compact bar with check icon and dot-separated server names
 * - Partial failure: OK servers in compact bar + individual error cards for failed servers
 *
 * Design language matches ToolCard (oklch colors, rounded-xl, inset borders).
 */

"use client"

import { Check, AlertCircle } from "lucide-react"

export interface McpServerStatus {
  name: string
  status: "ok" | "error"
  error?: string
}

interface McpStatusBarProps {
  servers: McpServerStatus[]
}

const OK_COLOR = {
  accent: "oklch(0.72 0.15 155)",
  bg: "oklch(0.72 0.15 155 / 6%)",
  border: "oklch(0.72 0.15 155 / 18%)",
}

const ERR_COLOR = {
  accent: "oklch(0.65 0.2 25)",
  bg: "oklch(0.65 0.2 25 / 6%)",
  border: "oklch(0.65 0.2 25 / 18%)",
}

export function McpStatusBar({ servers }: McpStatusBarProps) {
  if (!servers || servers.length === 0) return null

  const okServers = servers.filter((s) => s.status === "ok")
  const errServers = servers.filter((s) => s.status === "error")

  return (
    <div className="flex flex-col gap-1.5 tool-card-enter">
      {/* OK servers — compact single line */}
      {okServers.length > 0 && (
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl"
          style={{
            background: OK_COLOR.bg,
            boxShadow: `inset 0 0 0 1px ${OK_COLOR.border}`,
          }}
          role="status"
          aria-label={`Connected: ${okServers.map((s) => s.name).join(", ")}`}
        >
          <div
            className="flex-none w-5 h-5 rounded-md flex items-center justify-center"
            style={{ background: `${OK_COLOR.accent}18` }}
          >
            <Check className="h-3 w-3" style={{ color: OK_COLOR.accent }} />
          </div>
          <span className="text-[12px] font-medium" style={{ color: OK_COLOR.accent }}>
            {okServers.map((s) => s.name).join(" · ")}
          </span>
        </div>
      )}

      {/* Error servers — individual cards */}
      {errServers.map((server) => (
        <div
          key={server.name}
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl"
          style={{
            background: ERR_COLOR.bg,
            boxShadow: `inset 0 0 0 1px ${ERR_COLOR.border}`,
          }}
          role="alert"
          aria-label={`Unavailable: ${server.name}`}
        >
          <div
            className="flex-none w-5 h-5 rounded-md flex items-center justify-center"
            style={{ background: `${ERR_COLOR.accent}18` }}
          >
            <AlertCircle className="h-3 w-3" style={{ color: ERR_COLOR.accent }} />
          </div>
          <div className="min-w-0">
            <span className="text-[12px] font-medium" style={{ color: ERR_COLOR.accent }}>
              {server.name}
            </span>
            {server.error && (
              <p className="text-[11px] truncate mt-0.5 leading-tight" style={{ color: `${ERR_COLOR.accent}99` }}>
                {server.error.length > 80 ? server.error.slice(0, 80) + "…" : server.error}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
