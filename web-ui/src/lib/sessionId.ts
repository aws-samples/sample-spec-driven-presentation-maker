// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Runtime session ids bound to their owner — mirrors shared/session_owner.py.
 *
 * A Cloud session id starts with the owner prefix of the signed-in user: the first
 * 16 hex characters of SHA-256 over the token's `sub`. The agent and the MCP server
 * admit an owner-prefixed id only for that user. Both test suites pin the same vector.
 *
 * SHA-256 runs synchronously (`@aws-crypto/sha256-js`) because ids are created in
 * `useState` / `useRef` initialisers; Web Crypto is async only.
 */

import { Sha256 } from "@aws-crypto/sha256-js"

const PREFIXED = /^[0-9a-f]{16}-/

/** Session id prefix of `sub` (16 lowercase hex characters). */
export function ownerPrefix(sub: string): string {
  const hash = new Sha256()
  hash.update(new TextEncoder().encode(sub))
  return Array.from(hash.digestSync(), (b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16)
}

/** A new session id for `sub`: `<prefix>-<uuid>` (53 characters). */
export function newSessionId(sub: string): string {
  return `${ownerPrefix(sub)}-${crypto.randomUUID()}`
}

/**
 * The session id of a deck that has no linked chat yet: `<prefix>-<deckId padded to 36>`
 * (53 characters, the same on every page load for this user and deck).
 *
 * Ids never collide across users: the prefix comes from the caller's own `sub`, so
 * another user's id for the same deck has a different prefix, and the agent and the
 * MCP server refuse an id whose prefix is not the caller's. Two users share a 16-hex
 * prefix with probability 2^-64 per pair, and each runtime process still serves only
 * one user.
 */
export function deckSessionId(sub: string, deckId: string): string {
  return `${ownerPrefix(sub)}-${deckId.padEnd(36, "0")}`
}

/** True when `id` has the owner-prefixed shape (ids of earlier formats do not). */
export function isOwnerPrefixed(id: string): boolean {
  return PREFIXED.test(id)
}
