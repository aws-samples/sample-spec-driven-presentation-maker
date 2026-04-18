// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * MyResourcesList — Personal styles / templates viewer with delete confirmation.
 *
 * UX highlights:
 * - shadcn Dialog for focus trap and animation
 * - Skeleton loading state
 * - Visual cards with iconography (not bare list)
 * - AlertDialog for destructive confirmation (replaces window.confirm)
 * - Toast feedback after delete with undo affordance note
 * - Empty state with direct CTA
 */

"use client"

import { useCallback, useEffect, useState } from "react"
import { Trash2, Palette, Files, Plus, Calendar } from "lucide-react"
import { toast } from "sonner"
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  listUserStyles, deleteUserStyle,
  listUserTemplates, deleteUserTemplate,
  type UserStyleEntry, type UserTemplateEntry,
} from "@/services/resourcesService"

type ResourceType = "styles" | "templates"

interface MyResourcesListProps {
  type: ResourceType
  idToken: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreateNew?: () => void
}

interface ListItem {
  id: string
  title: string
  subtitle: string
  meta?: string
}

export function MyResourcesList({
  type, idToken, open, onOpenChange, onCreateNew,
}: MyResourcesListProps) {
  const [items, setItems] = useState<ListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [pendingDelete, setPendingDelete] = useState<ListItem | null>(null)
  const [deleting, setDeleting] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    if (type === "styles") {
      const styles = await listUserStyles(idToken)
      setItems(styles.map((s: UserStyleEntry) => ({
        id: s.name, title: s.name, subtitle: s.description || "Personal style",
      })))
    } else {
      const templates = await listUserTemplates(idToken)
      setItems(templates.map((t: UserTemplateEntry) => ({
        id: t.id, title: t.name, subtitle: t.description || "PowerPoint template",
        meta: t.updatedAt ? new Date(t.updatedAt).toLocaleDateString() : "",
      })))
    }
    setLoading(false)
  }, [type, idToken])

  useEffect(() => { if (open) reload() }, [open, reload])

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      if (type === "styles") await deleteUserStyle(pendingDelete.id, idToken)
      else await deleteUserTemplate(pendingDelete.id, idToken)
      toast.success(`${type === "styles" ? "Style" : "Template"} deleted`, {
        description: `"${pendingDelete.title}" has been removed.`,
      })
      setPendingDelete(null)
      reload()
    } catch {
      toast.error("Delete failed", { description: "Please try again." })
    } finally {
      setDeleting(false)
    }
  }

  const Icon = type === "styles" ? Palette : Files
  const label = type === "styles" ? "Styles" : "Templates"
  const emptyHint = type === "styles"
    ? "Ask the assistant to design one with the Customize menu."
    : "Upload a .pptx from the Customize menu to get started."

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-brand-teal/10">
                <Icon className="h-5 w-5 text-brand-teal" />
              </div>
              <div>
                <DialogTitle>My {label}</DialogTitle>
                <DialogDescription>
                  {loading ? "Loading…" : `${items.length} ${items.length === 1 ? label.slice(0, -1).toLowerCase() : label.toLowerCase()}`}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="max-h-[60vh] overflow-y-auto -mx-2 px-2">
            {loading ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex items-center gap-3 p-3 rounded-lg border border-border/40">
                    <Skeleton className="w-8 h-8 rounded-md" />
                    <div className="flex-1 space-y-1.5">
                      <Skeleton className="h-3 w-1/2" />
                      <Skeleton className="h-2.5 w-2/3" />
                    </div>
                  </div>
                ))}
              </div>
            ) : items.length === 0 ? (
              <div className="flex flex-col items-center text-center py-10 px-4">
                <div className="w-12 h-12 rounded-xl bg-muted/50 flex items-center justify-center mb-3">
                  <Icon className="h-5 w-5 text-foreground-muted" />
                </div>
                <p className="text-sm font-medium mb-1">No {label.toLowerCase()} yet</p>
                <p className="text-xs text-foreground-muted mb-4 max-w-xs">{emptyHint}</p>
                {onCreateNew && (
                  <Button
                    size="sm"
                    onClick={() => { onOpenChange(false); onCreateNew() }}
                    className="bg-brand-teal hover:brightness-110 text-primary-foreground"
                  >
                    <Plus className="h-3.5 w-3.5 mr-1.5" />
                    {type === "styles" ? "New Style" : "Upload Template"}
                  </Button>
                )}
              </div>
            ) : (
              <div className="space-y-1.5">
                {items.map((item) => (
                  <div
                    key={item.id}
                    className="group flex items-center gap-3 p-2.5 rounded-lg border border-border/40 hover:border-border-hover hover:bg-background-hover transition-all animate-card-in"
                  >
                    <div className="w-8 h-8 rounded-md bg-brand-teal/10 flex items-center justify-center flex-none">
                      <Icon className="h-4 w-4 text-brand-teal" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">{item.title}</p>
                      <p className="text-[11px] text-foreground-muted truncate">{item.subtitle}</p>
                    </div>
                    {item.meta && (
                      <span className="flex items-center gap-1 text-[10px] text-foreground-muted">
                        <Calendar className="h-2.5 w-2.5" />
                        {item.meta}
                      </span>
                    )}
                    <button
                      onClick={() => setPendingDelete(item)}
                      className="p-1.5 rounded-md text-foreground-muted hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-all"
                      aria-label={`Delete ${item.title}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Confirmation dialog — replaces window.confirm */}
      <AlertDialog open={!!pendingDelete} onOpenChange={(o) => { if (!o) setPendingDelete(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {pendingDelete?.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              This {type === "styles" ? "style" : "template"} will be permanently removed.
              Decks already using it keep their current look.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              disabled={deleting}
              className="bg-red-500 hover:bg-red-600 text-white"
            >
              {deleting ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
