// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * DeckActions — Visibility toggle and Share dialog with user search,
 * multi-add, collaborator list, and remove.
 */

"use client"

import { useState, useEffect, useRef } from "react"
import { Globe, Lock, Share2, X, UserPlus, Trash2, Building2 } from "lucide-react"
import { searchUsers, UserSearchResult } from "@/services/deckService"

interface DeckActionsProps {
  visibility?: "public" | "private"
  onVisibilityChange: (v: "public" | "private") => void
  onShare: (sub: string, action: "add" | "remove", alias?: string) => Promise<{collaborators: string[], collaboratorAliases: Record<string, string>}>
  idToken?: string
  collaborators?: string[]
  collaboratorAliases?: Record<string, string>
}

export function DeckActions({ visibility, onVisibilityChange, onShare, idToken, collaborators = [], collaboratorAliases: initialAliases = {} }: DeckActionsProps) {
  const [showPublishConfirm, setShowPublishConfirm] = useState(false)
  const [showShare, setShowShare] = useState(false)
  const [shareQuery, setShareQuery] = useState("")
  const [suggestions, setSuggestions] = useState<UserSearchResult[]>([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [collabList, setCollabList] = useState<string[]>(collaborators)
  const [collabAliases, setCollabAliases] = useState<Record<string, string>>(initialAliases)
  const inputRef = useRef<HTMLInputElement>(null)
  const isPublic = visibility === "public"

  useEffect(() => { setCollabList(collaborators) }, [collaborators])
  useEffect(() => { setCollabAliases(initialAliases) }, [initialAliases])

  // Debounced user search
  useEffect(() => {
    if (!showShare || !idToken || shareQuery.length < 2) { setSuggestions([]); return }
    const timer = setTimeout(async () => {
      const results = await searchUsers(shareQuery, idToken)
      // Filter out already-added collaborators
      setSuggestions(results.filter((u) => !collabList.includes(u.sub)))
      setSelectedIndex(0)
    }, 200)
    return () => clearTimeout(timer)
  }, [shareQuery, showShare, idToken, collabList])

  const addUser = async (user: UserSearchResult) => {
    const result = await onShare(user.sub, "add", user.alias)
    setCollabList(result.collaborators)
    setCollabAliases(result.collaboratorAliases)
    setShareQuery("")
    setSuggestions([])
    inputRef.current?.focus()
  }

  const removeUser = async (sub: string) => {
    const result = await onShare(sub, "remove")
    setCollabList(result.collaborators)
    setCollabAliases(result.collaboratorAliases)
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => { if (isPublic) onVisibilityChange("private"); else setShowPublishConfirm(true) }}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${
          isPublic ? "bg-green-500/10 text-green-400 border border-green-500/30" : "bg-muted/50 text-muted-foreground border border-border/40 hover:text-foreground"
        }`}
      >
        {isPublic ? <Building2 className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
        {isPublic ? "Internal" : "Private"}
      </button>

      <button
        onClick={() => { setShowShare(true); setTimeout(() => inputRef.current?.focus(), 50) }}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-muted/50 text-muted-foreground border border-border/40 hover:text-foreground transition-colors"
      >
        <Share2 className="h-3 w-3" />
        Share{collabList.length > 0 && ` (${collabList.length})`}
      </button>

      {/* Publish confirmation */}
      {showPublishConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-popover border border-border rounded-xl shadow-xl w-full max-w-sm mx-4 p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="p-2 rounded-lg bg-green-500/10"><Building2 className="h-5 w-5 text-green-400" /></div>
              <h3 className="text-sm font-semibold">Share internally?</h3>
            </div>
            <p className="text-xs text-muted-foreground mb-4">This deck will be discoverable by everyone in the organization.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowPublishConfirm(false)} className="px-3 py-1.5 text-xs rounded-lg hover:bg-muted transition-colors">Cancel</button>
              <button onClick={() => { onVisibilityChange("public"); setShowPublishConfirm(false) }} className="px-3 py-1.5 text-xs rounded-lg bg-green-600 text-white hover:bg-green-500 transition-colors">Share</button>
            </div>
          </div>
        </div>
      )}

      {/* Share dialog */}
      {showShare && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-popover border border-border rounded-xl shadow-xl w-full max-w-sm mx-4 p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-blue-500/10"><Share2 className="h-5 w-5 text-blue-400" /></div>
                <h3 className="text-sm font-semibold">Share this deck</h3>
              </div>
              <button onClick={() => { setShowShare(false); setShareQuery(""); setSuggestions([]) }} className="p-1 rounded hover:bg-muted"><X className="h-4 w-4" /></button>
            </div>

            {/* Search input */}
            <div className="relative mb-3">
              <input
                ref={inputRef}
                type="text"
                value={shareQuery}
                onChange={(e) => setShareQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") e.preventDefault()
                  if (suggestions.length === 0) return
                  if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIndex((i) => (i + 1) % suggestions.length) }
                  if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIndex((i) => (i - 1 + suggestions.length) % suggestions.length) }
                  if (e.key === "Enter") { addUser(suggestions[selectedIndex]) }
                }}
                placeholder="Search by alias…"
                className="w-full px-3 py-2 text-sm bg-muted/50 border border-border/40 rounded-lg focus:outline-none focus:ring-1 focus:ring-primary"
                autoFocus
              />
              {suggestions.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-lg shadow-lg py-1 max-h-[160px] overflow-y-auto z-10">
                  {suggestions.map((user, i) => (
                    <button
                      key={user.sub}
                      type="button"
                      onClick={() => addUser(user)}
                      onMouseEnter={() => setSelectedIndex(i)}
                      className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors ${i === selectedIndex ? "bg-muted" : "hover:bg-muted/50"}`}
                    >
                      <div className="w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center text-[9px] font-medium text-primary flex-none">
                        {user.alias[0]?.toUpperCase()}
                      </div>
                      <span className="text-sm">{user.alias}</span>
                      <span className="text-[10px] text-muted-foreground ml-auto">{user.email}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Collaborator list */}
            {collabList.length > 0 && (
              <div className="border-t border-border/30 pt-2">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Collaborators</p>
                <div className="space-y-1 max-h-[120px] overflow-y-auto">
                  {collabList.map((sub) => (
                    <div key={sub} className="flex items-center justify-between px-2 py-1 rounded-md hover:bg-muted/30">
                      <div className="flex items-center gap-2">
                        <div className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center text-[9px] font-medium text-blue-400 flex-none">
                          {(collabAliases[sub] || sub)[0]?.toUpperCase()}
                        </div>
                        <span className="text-xs">{collabAliases[sub] || sub.slice(0, 8)}</span>
                      </div>
                      <button
                        onClick={() => removeUser(sub)}
                        className="p-0.5 rounded hover:bg-red-500/20 text-muted-foreground hover:text-red-400 transition-colors"
                        aria-label={`Remove ${collabAliases[sub] || sub}`}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {collabList.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-2">No collaborators yet</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
