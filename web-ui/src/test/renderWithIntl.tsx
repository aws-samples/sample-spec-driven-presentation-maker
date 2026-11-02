// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * renderWithIntl — Testing Library render wrapped in NextIntlClientProvider.
 * Components that call useTranslations() need this instead of plain render().
 * Pass `locale: "ja"` to render with the Japanese bundle (default: English).
 */

import { render, type RenderOptions } from "@testing-library/react"
import { NextIntlClientProvider } from "next-intl"
import type { ReactElement, ReactNode } from "react"
import en from "../../messages/en.json"
import ja from "../../messages/ja.json"

const MESSAGES = { en, ja }

type IntlRenderOptions = Omit<RenderOptions, "wrapper"> & { locale?: keyof typeof MESSAGES }

/** NextIntlClientProvider wrapper for renderHook (hooks that call useTranslations()). */
export function intlWrapper(locale: keyof typeof MESSAGES = "en") {
  return function IntlWrapper({ children }: { children: ReactNode }) {
    return (
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]} timeZone="UTC">
        {children}
      </NextIntlClientProvider>
    )
  }
}

export function renderWithIntl(ui: ReactElement, { locale = "en", ...options }: IntlRenderOptions = {}) {
  return render(ui, { wrapper: intlWrapper(locale), ...options })
}
