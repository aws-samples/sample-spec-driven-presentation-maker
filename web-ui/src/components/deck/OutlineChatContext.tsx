// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

"use client"

import { createContext, useContext } from "react"

export interface OutlineChatBridge {
  isLoading: boolean
  sendMessage: (text: string, options?: { displayContent?: string }) => Promise<void>
}

const defaultBridge: OutlineChatBridge = {
  isLoading: false,
  sendMessage: async () => {},
}

export const OutlineChatContext = createContext<OutlineChatBridge>(defaultBridge)

export function useOutlineChat(): OutlineChatBridge {
  return useContext(OutlineChatContext)
}
