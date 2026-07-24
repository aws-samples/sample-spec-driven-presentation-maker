// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

/**
 * LocaleProvider — NextIntlClientProvider wired to localStorage.
 *
 * No locale routing: the app is a static-export SPA, so the locale lives
 * in localStorage (`sdpm-locale`) instead of the URL. Both message bundles
 * are imported statically (small) and switched client-side.
 */

import { NextIntlClientProvider } from "next-intl"
import { createContext, useCallback, useContext, useEffect, useState } from "react"
import en from "../../messages/en.json"
import ja from "../../messages/ja.json"

export type Locale = "en" | "ja"

const KEY = "sdpm-locale"
const MESSAGES: Record<Locale, typeof en> = { en, ja }

interface LocaleContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: "en",
  setLocale: () => {},
})

function detectLocale(): Locale {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === "en" || saved === "ja") return saved
    if (navigator.language.toLowerCase().startsWith("ja")) return "ja"
  } catch {
    // intentional: best-effort — SSR or storage-disabled browsers fall back to en
  }
  return "en"
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  // Start with "en" for the SSR/first paint, then hydrate from localStorage
  // after mount (same pattern as usePreferences) to avoid hydration mismatch.
  const [locale, setLocaleState] = useState<Locale>("en")

  useEffect(() => {
    setLocaleState(detectLocale())
  }, [])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      // intentional: best-effort — locale still applies for this session
    }
  }, [])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]} timeZone={Intl.DateTimeFormat().resolvedOptions().timeZone}>
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  )
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext)
}
