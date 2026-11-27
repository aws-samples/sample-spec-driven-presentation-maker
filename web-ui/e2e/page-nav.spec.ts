// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * E2E: the rail moves between Decks, Styles and Templates without reloading the page.
 *
 * A reload repainted the whole screen (the rail, the language read back from storage, the
 * sign-in check). The rail and the logo navigate on the client, so the document stays and the
 * chosen language shows throughout. A value set on `window` survives every move.
 */
import { test, expect, type Page } from "@playwright/test"

async function railLink(page: Page, name: string) {
  return page.getByRole("navigation").getByRole("link", { name, exact: true }).filter({ hasText: name })
}

test("the rail and the logo change pages without a reload, in the chosen language", async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem("sdpm-locale", "ja") })
  await page.goto("/decks")
  await expect(page.getByRole("textbox", { name: "チャットメッセージ入力" })).toBeFocused({ timeout: 30_000 })
  await page.evaluate(() => { (window as unknown as { __sameDocument: boolean }).__sameDocument = true })
  const sameDocument = () => page.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument === true)

  for (const [name, path] of [["スタイル", "/styles"], ["テンプレート", "/templates"], ["デッキ", "/decks"]] as const) {
    await (await railLink(page, name)).click()
    await expect(page).toHaveURL((url) => url.pathname.startsWith(path))
    expect(await sameDocument()).toBe(true)
    await expect(await railLink(page, name)).toHaveAttribute("aria-current", "page")
  }

  // The logo, from another page.
  await (await railLink(page, "スタイル")).click()
  await expect(page).toHaveURL((url) => url.pathname.startsWith("/styles"))
  await page.getByRole("navigation").getByRole("link", { name: "デッキ", exact: true }).filter({ hasNotText: "デッキ" }).click()
  await expect(page).toHaveURL((url) => url.pathname.startsWith("/decks"))
  expect(await sameDocument()).toBe(true)
})
