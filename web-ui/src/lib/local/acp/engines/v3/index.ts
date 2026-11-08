// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** The V3 engine adapter (kiro-cli 3.0's default engine): `kiro-cli acp --agent-engine v3`. */
import type { EngineAdapter, EngineCapabilities } from "../../engine"
import type { InitializeResponse } from "../../schema"
import { V3Session } from "./session"
import { listV3Sessions } from "./stored-sessions"
import { v3McpEvents } from "./translate"
import type { V3AgentCapabilities } from "./types"

export const v3Adapter: EngineAdapter = {
  id: "v3",
  // The flag is optional on 3.0 (V3 is the default), but `--help` says otherwise: name it.
  spawnArgs: () => ["acp", "--agent-engine", "v3"],
  capabilities(init: InitializeResponse): EngineCapabilities {
    const caps = (init.agentCapabilities ?? {}) as V3AgentCapabilities
    const session = caps.sessionCapabilities ?? {}
    const kiro = caps._meta?.kiro ?? {}
    return {
      session: { list: Boolean(session.list), close: Boolean(session.close), delete: Boolean(session.delete), fork: Boolean(session.fork) },
      replayMarking: kiro.replayMarking === true,
      extensionMethods: new Set(Array.isArray(kiro.extensionMethods) ? kiro.extensionMethods.filter((m) => typeof m === "string") : []),
      steer: true,
    }
  },
  translateMcp: v3McpEvents,
  createSession: (ctx) => new V3Session(ctx),
  sessionsOpenableBy: ["v3"],
  listStoredSessions: listV3Sessions,
}
