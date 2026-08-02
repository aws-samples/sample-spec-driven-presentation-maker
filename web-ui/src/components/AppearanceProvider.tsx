// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { ThemeProvider as NextThemesProvider, useTheme } from "next-themes"
import { useEffect } from "react"

const THEME_COLORS = {
  dark: "#1a1a1c",
  light: "#f8f7f2",
} as const

function ThemeChromeSync() {
  const { resolvedTheme } = useTheme()

  useEffect(() => {
    const theme = resolvedTheme === "light" ? "light" : "dark"
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[theme])
  }, [resolvedTheme])

  return null
}

export function AppearanceProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="data-theme"
      defaultTheme="dark"
      enableSystem
      disableTransitionOnChange
    >
      <ThemeChromeSync />
      {children}
    </NextThemesProvider>
  )
}
