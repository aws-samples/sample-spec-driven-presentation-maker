// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Playwright E2E config — runs the Web UI in Local mode against a stub
 * ACP agent (e2e/stub-agent.mjs), so no AWS and no kiro-cli are needed.
 *
 * Sandbox: decks and agent config live under e2e/.tmp (see global-setup.ts).
 */
import { defineConfig } from "@playwright/test"
import path from "path"

const TMP = path.resolve(__dirname, "e2e", ".tmp")
const PORT = 3199

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  // Single worker: tests share one dev server and one deck sandbox
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npx next dev --turbopack --port ${PORT}`,
    port: PORT,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_MODE: "local",
      SDPM_DECK_ROOT: path.join(TMP, "decks"),
      SDPM_ACP_CONFIG_DIR: path.join(TMP, "config"),
    },
  },
})
