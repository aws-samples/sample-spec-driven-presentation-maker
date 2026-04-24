// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Deck API Service — REST client for deck list and detail endpoints.
 *
 * Loads API base URL from aws-exports.json (apiBaseUrl).
 * All requests require a Cognito ID token for authorization.
 */

export interface DeckSummary {
  deckId: string
  name: string
  slideCount: number
  updatedAt: string
  thumbnailUrl: string | null
  owner?: string
}

export interface SlidePreview {
  slug: string
  previewUrl: string | null
  composeUrl?: string | null
  updatedAt: string
  slideJson?: string
}

export interface SpecFiles {
  brief: string | null
  outline: string | null
  artDirection: string | null
}

export interface DeckDetail {
  deckId: string
  name: string
  slideOrder: string[]
  slides: SlidePreview[]
  defsUrl?: string | null
  pptxUrl: string | null
  specs?: SpecFiles | null
  updatedAt: string
  chatSessionId?: string
  visibility?: "public" | "private"
  isOwner?: boolean
  role?: "owner" | "collaborator" | "viewer"
  ownerAlias?: string
  collaborators?: string[]
  collaboratorAliases?: Record<string, string>
}

const IS_LOCAL = process.env.NEXT_PUBLIC_MODE === 'local'

let apiBaseUrl = ""

/** Session-level cache for slide preview presigned URLs. */
const previewUrlCache = new Map<string, string | null>()

/**
 * Load the API base URL from aws-exports.json.
 * Reuses apiBaseUrl from aws-exports.json (e.g. https://xxx.execute-api.../prod/).
 *
 * @returns Base URL string ending with /
 */
async function getApiBaseUrl(): Promise<string> {
  if (IS_LOCAL) return "/api/"
  if (apiBaseUrl) return apiBaseUrl

  const response = await fetch("/aws-exports.json")
  const config = await response.json()
  apiBaseUrl = config.apiBaseUrl || ""
  return apiBaseUrl
}

/**
 * Fetch all decks for the authenticated user.
 *
 * @param idToken - Cognito ID token for API Gateway authorization
 * @returns Array of deck summaries with thumbnail presigned URLs
 */
export async function listDecks(idToken: string): Promise<{ decks: DeckSummary[]; favoriteIds: string[] }> {
  if (IS_LOCAL) {
    const response = await fetch("/api/decks")
    if (!response.ok) throw new Error(`Failed to list decks: ${response.status}`)
    return response.json()
  }
  const base = await getApiBaseUrl()
  const response = await fetch(`${base}decks`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })

  if (!response.ok) {
    throw new Error(`Failed to list decks: ${response.status}`)
  }

  const data = await response.json()
  return { decks: data.decks, favoriteIds: data.favoriteIds || [] }
}

/**
 * Fetch deck details with presigned URLs for all slide PNGs and PPTX.
 *
 * @param deckId - Deck identifier
 * @param idToken - Cognito ID token for API Gateway authorization
 * @returns Deck detail with slides array and pptxUrl
 */
export async function getDeck(deckId: string, idToken: string): Promise<DeckDetail> {
  if (IS_LOCAL) {
    const response = await fetch(`/api/decks/${deckId}`)
    if (!response.ok) throw new Error(`Failed to get deck: ${response.status}`)
    return response.json()
  }
  const base = await getApiBaseUrl()
  const response = await fetch(`${base}decks/${deckId}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })

  if (!response.ok) {
    throw new Error(`Failed to get deck: ${response.status}`)
  }

  return response.json()
}

/**
 * Update allowed fields on a deck (e.g. chatSessionId).
 *
 * @param deckId - Deck identifier
 * @param updates - Object with fields to update
 * @param idToken - Cognito ID token
 */
export async function patchDeck(deckId: string, updates: Record<string, string>, idToken: string): Promise<void> {
  const base = await getApiBaseUrl()
  await fetch(`${base}decks/${deckId}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  })
}

/**
 * Fetch deck with slideJson included (for JSON download).
 *
 * @param deckId - Deck identifier
 * @param idToken - Cognito ID token
 * @returns Deck detail with slideJson populated
 */
export async function getDeckWithJson(deckId: string, idToken: string): Promise<DeckDetail> {
  const base = await getApiBaseUrl()
  const response = await fetch(`${base}decks/${deckId}?include=slideJson`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })

  if (!response.ok) {
    throw new Error(`Failed to get deck: ${response.status}`)
  }

  return response.json()
}

export interface SlideSearchResult {
  deckId: string
  slug: string
  deckName: string
  ownerAlias: string
  pageNumber: number
  score: number
  excerpt: string
  previewUrl: string | null
}

/**
 * Search slides via Bedrock Knowledge Base.
 *
 * @param query - Search query string
 * @param idToken - Cognito ID token
 * @returns Array of matching slides with preview URLs
 */
export async function searchSlides(query: string, idToken: string): Promise<SlideSearchResult[]> {
  const base = await getApiBaseUrl()
  const resp = await fetch(`${base}slides/search?q=${encodeURIComponent(query)}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!resp.ok) return []
  const data = await resp.json()
  return data.results || []
}

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp: number
}

/**
 * Fetch chat history for a session.
 *
 * @param sessionId - Conversation session ID
 * @param idToken - Cognito ID token
 * @returns Array of chat messages sorted by timestamp
 */
export async function getChatHistory(sessionId: string, idToken: string, deckId?: string): Promise<ChatMessage[]> {
  if (IS_LOCAL) {
    if (!deckId || deckId === "new") return []
    // Load session context + saved messages
    const res = await fetch("/api/agent/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, deckId }),
    })
    if (!res.ok) return []
    const data = await res.json()
    return data.messages || []
  }
  const base = await getApiBaseUrl()
  const response = await fetch(`${base}chat/${sessionId}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })

  if (!response.ok) return []

  const data = await response.json()
  return data.messages || []
}

/**
 * Update deck visibility (public/private).
 *
 * @param deckId - Deck identifier
 * @param visibility - "public" or "private"
 * @param idToken - Cognito ID token
 */
export async function updateVisibility(deckId: string, visibility: "public" | "private", idToken: string): Promise<void> {
  const base = await getApiBaseUrl()
  await fetch(`${base}decks/${deckId}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ visibility }),
  })
}

/**
 * List public decks.
 *
 * @param idToken - Cognito ID token
 * @returns Array of public deck summaries
 */
export async function listPublicDecks(idToken: string): Promise<DeckSummary[]> {
  if (IS_LOCAL) return []
  const base = await getApiBaseUrl()
  const response = await fetch(`${base}decks/public`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!response.ok) return []
  const data = await response.json()
  return data.decks
}

/**
 * Share or unshare a deck with a collaborator.
 *
 * @param deckId - Deck identifier
 * @param collaboratorId - User sub to share with
 * @param idToken - Cognito ID token
 * @param action - "add" or "remove"
 * @returns Updated collaborators list
 */
export async function shareDeck(deckId: string, collaboratorId: string, idToken: string, action: "add" | "remove" = "add", collaboratorAlias?: string): Promise<{collaborators: string[], collaboratorAliases: Record<string, string>}> {
  const base = await getApiBaseUrl()
  const resp = await fetch(`${base}decks/${deckId}/share`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ collaboratorId, action, collaboratorAlias }),
  })
  if (!resp.ok) return { collaborators: [], collaboratorAliases: {} }
  const data = await resp.json()
  return { collaborators: data.collaborators || [], collaboratorAliases: data.collaboratorAliases || {} }
}

/**
 * List decks shared with the current user.
 *
 * @param idToken - Cognito ID token
 * @returns Array of shared deck summaries
 */
export async function listSharedDecks(idToken: string): Promise<DeckSummary[]> {
  if (IS_LOCAL) return []
  const base = await getApiBaseUrl()
  const response = await fetch(`${base}decks/shared`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!response.ok) return []
  const data = await response.json()
  return data.decks
}

export interface UserSearchResult {
  sub: string
  alias: string
  email: string
}

/**
 * Search users by alias/email prefix for share autocomplete.
 *
 * @param query - Search query (min 2 chars)
 * @param idToken - Cognito ID token
 * @returns Array of matching users
 */
export async function searchUsers(query: string, idToken: string): Promise<UserSearchResult[]> {
  if (query.length < 2) return []
  const base = await getApiBaseUrl()
  const response = await fetch(`${base}users/search?q=${encodeURIComponent(query)}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!response.ok) return []
  const data = await response.json()
  return data.users || []
}


/**
 * Soft-delete a deck.
 *
 * @param deckId - Deck identifier
 * @param idToken - Cognito ID token
 */
export async function deleteDeck(deckId: string, idToken: string): Promise<void> {
  const base = await getApiBaseUrl()
  const resp = await fetch(`${base}decks/${deckId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!resp.ok) throw new Error(`Failed to delete deck: ${resp.status}`)
}

/**
 * Toggle favorite status for a deck.
 *
 * @param deckId - Deck identifier
 * @param action - "add" or "remove"
 * @param idToken - Cognito ID token
 * @returns Whether the deck is now favorited
 */
export async function toggleFavorite(deckId: string, action: "add" | "remove", idToken: string): Promise<boolean> {
  const base = await getApiBaseUrl()
  const resp = await fetch(`${base}decks/${deckId}/favorite`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  })
  if (!resp.ok) throw new Error(`Failed to toggle favorite: ${resp.status}`)
  const data = await resp.json()
  return data.favorited
}

/**
 * List user's favorite decks.
 *
 * @param idToken - Cognito ID token
 * @returns Array of favorite deck summaries
 */
export async function listFavorites(idToken: string): Promise<DeckSummary[]> {
  if (IS_LOCAL) return []
  const base = await getApiBaseUrl()
  const resp = await fetch(`${base}decks/favorites`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!resp.ok) return []
  const data = await resp.json()
  return data.decks
}


/**
 * Batch-fetch presigned URLs for specific slide PNGs.
 * Uses session-level cache to avoid redundant API calls.
 *
 * @param items - Array of {deckId, slug} to fetch
 * @param idToken - Cognito ID token
 * @returns Map of "deckId:slug" to presigned URL (or null)
 */
export async function batchGetSlidePreviewUrls(
  items: { deckId: string; slug: string }[],
  idToken: string,
): Promise<Map<string, string | null>> {
  const result = new Map<string, string | null>()
  const uncached: { deckId: string; slug: string }[] = []

  for (const item of items) {
    const key = `${item.deckId}:${item.slug}`
    if (previewUrlCache.has(key)) {
      result.set(key, previewUrlCache.get(key)!)
    } else {
      uncached.push(item)
    }
  }

  if (uncached.length === 0) return result

  const base = await getApiBaseUrl()
  const response = await fetch(`${base}slides/previews`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${idToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(uncached),
  })

  if (response.ok) {
    const data: { deckId: string; slug: string; previewUrl: string | null }[] = await response.json()
    for (const item of data) {
      const key = `${item.deckId}:${item.slug}`
      previewUrlCache.set(key, item.previewUrl)
      result.set(key, item.previewUrl)
    }
  }

  return result
}

/** Style entry returned by GET /styles. */
export interface StyleEntry {
  name: string
  description: string
  coverHtml: string
}

/**
 * Fetch available styles with cover slide HTML.
 *
 * @param idToken - Cognito ID token for API Gateway authorization
 * @returns Array of style entries
 */
export async function fetchStyles(idToken: string): Promise<StyleEntry[]> {
  const base = await getApiBaseUrl()
  const res = await fetch(`${base}styles`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!res.ok) return []
  const data = await res.json()
  return data.styles || []
}

/**
 * Fetch full HTML for a single style.
 *
 * @param name - Style name
 * @param idToken - Cognito ID token for API Gateway authorization
 * @returns Full HTML string, or empty string on error
 */
export async function fetchStyleHtml(name: string, idToken: string): Promise<string> {
  const base = await getApiBaseUrl()
  const res = await fetch(`${base}styles/${encodeURIComponent(name)}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!res.ok) return ""
  const data = await res.json()
  return data.fullHtml || ""
}
