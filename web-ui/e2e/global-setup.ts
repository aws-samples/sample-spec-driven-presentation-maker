// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Playwright global setup — prepares an isolated sandbox under e2e/.tmp:
 * - decks/  : SDPM_DECK_ROOT for the dev server (keeps ~/Documents untouched)
 * - config/ : acp-config.json pointing the ACP process manager at the
 *             stub agent instead of kiro-cli (via SDPM_ACP_CONFIG_DIR)
 */
import fs from "fs"
import path from "path"

export default async function globalSetup() {
  const tmp = path.resolve(__dirname, ".tmp")
  fs.rmSync(tmp, { recursive: true, force: true })
  fs.mkdirSync(path.join(tmp, "decks"), { recursive: true })
  fs.mkdirSync(path.join(tmp, "config"), { recursive: true })

  const stubPath = path.resolve(__dirname, "stub-agent.mjs")
  const config = {
    activeAgent: "e2e-stub",
    agents: [
      {
        id: "e2e-stub",
        displayName: "E2E Stub Agent",
        path: process.execPath,
        args: [stubPath],
        env: {},
        subagentTool: "use_subagent",
        subagentInstruction: "",
        restartOnNewChat: true,
        subagentQueryField: "query",
      },
    ],
  }
  fs.writeFileSync(path.join(tmp, "config", "acp-config.json"), JSON.stringify(config, null, 2) + "\n")
}
