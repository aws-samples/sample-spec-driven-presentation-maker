// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Playwright global setup — prepares an isolated sandbox under e2e/.tmp:
 * - decks/  : SDPM_DECK_ROOT for the dev server (keeps ~/Documents untouched)
 * - config/ : acp-config.json pointing the ACP process manager at the
 *             stub agent instead of kiro-cli (via SDPM_ACP_CONFIG_DIR), on the
 *             V3 engine; a test switches it with PUT /api/agent/engine, which
 *             keeps the command
 */
import fs from "fs"
import path from "path"

export default async function globalSetup() {
  const tmp = path.resolve(__dirname, ".tmp")
  fs.rmSync(tmp, { recursive: true, force: true })
  fs.mkdirSync(path.join(tmp, "decks"), { recursive: true })
  fs.mkdirSync(path.join(tmp, "config"), { recursive: true })

  const stubPath = path.resolve(__dirname, "stub-agent.mjs")
  const config = { version: 2, engine: "v3", command: process.execPath, commandArgs: [stubPath], env: {} }
  fs.writeFileSync(path.join(tmp, "config", "acp-config.json"), JSON.stringify(config, null, 2) + "\n")
}
