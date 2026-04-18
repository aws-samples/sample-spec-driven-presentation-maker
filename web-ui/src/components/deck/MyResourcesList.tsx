// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * MyResourcesList — Dialog showing My Styles or My Templates with delete action.
 */

"use client"

import { useCallback, useEffect, useState } from "react"
import { X, Trash2, Palette, Files } from "lucide-react"
import {
  listUserStyles, deleteUserStyle,
  listUserTemplates, deleteUserTemplate,
  type UserStyleEntry, type UserTemplateEntry,
} from "@/services/resourcesService"

type ResourceType = "styles" | "templates"

interface MyResourcesListProps {
  type: ResourceType
  idToken: string
  onClose: () => void
}

export function MyResourcesList({ type, idToken, onClose }: MyResourcesListProps) {
  const [styles, setStyles] = useState<UserStyleEntry[]>([])
  const [templates, setTemplates] = useState<UserTemplateEntry[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    if (type === "styles") setStyles(await listUserStyles(idToken))
    else setTemplates(await listUserTemplates(idToken))
    setLoading(false)
  }, [type, idToken])

  useEffect(() => { reload() }, [reload])

  const handleDelete = async (id: string) => {
    if (!confirm(`Delete "${id}"?`)) return
    if (type === "styles") await deleteUserStyle(id, idToken)
    else await deleteUserTemplate(id, idToken)
    reload()
  }

  const items = type === "styles"
    ? styles.map(s => ({ id: s.name, title: s.name, subtitle: s.description }))
    : templates.map(t => ({ id: t.id, title: t.name, subtitle: t.description || t.updatedAt }))

  const Icon = type === "styles" ? Palette : Files

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-popover border border-border rounded-xl shadow-xl w-full max-w-md mx-4 p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-brand-teal/10">
              <Icon className="h-5 w-5 text-brand-teal" />
            </div>
            <h3 className="text-sm font-semibold">
              My {type === "styles" ? "Styles" : "Templates"}
            </h3>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto">
          {loading ? (
            <p className="text-xs text-foreground-muted text-center py-8">Loading…</p>
          ) : items.length === 0 ? (
            <p className="text-xs text-foreground-muted text-center py-8">
              No {type} yet
            </p>
          ) : (
            <div className="space-y-1">
              {items.map(item => (
                <div
                  key={item.id}
                  className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-muted/30"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{item.title}</p>
                    {item.subtitle && (
                      <p className="text-[11px] text-foreground-muted truncate">{item.subtitle}</p>
                    )}
                  </div>
                  <button
                    onClick={() => handleDelete(item.id)}
                    className="p-1.5 rounded hover:bg-red-500/20 text-foreground-muted hover:text-red-400 transition-colors flex-none"
                    aria-label={`Delete ${item.title}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
