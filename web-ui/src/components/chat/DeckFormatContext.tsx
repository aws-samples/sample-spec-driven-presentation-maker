// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * DeckFormatContext — the open deck's outputFormat ("pptx" | "html", undefined when
 * unknown or no deck is open) for chat components whose labels depend on it.
 */

"use client"

import { createContext, useContext } from "react"

type DeckFormat = "pptx" | "html" | undefined

const DeckFormatContext = createContext<DeckFormat>(undefined)

export const DeckFormatProvider = DeckFormatContext.Provider

export function useDeckFormat(): DeckFormat {
  return useContext(DeckFormatContext)
}
