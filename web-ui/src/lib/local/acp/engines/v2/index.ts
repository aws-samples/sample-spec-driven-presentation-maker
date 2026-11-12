// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** The V2 engine adapter (kiro-cli's agent engine before V3): `kiro-cli acp --agent <name>`. */
import type { EngineAdapter, EngineCapabilities } from "../../engine"
import type { InitializeResponse } from "../../schema"
import { V2Session } from "./session"
import { listV2Sessions, v2SessionsDir } from "./stored-sessions"
import { v2McpEvents } from "./translate"

export const v2Adapter: EngineAdapter = {
  id: "v2",
  spawnArgs: (agentName) => ["acp", "--agent", agentName],
  capabilities(init: InitializeResponse): EngineCapabilities {
    const session = init.agentCapabilities?.sessionCapabilities ?? {}
    return {
      session: { list: Boolean(session.list), close: Boolean(session.close), delete: Boolean(session.delete), fork: false },
      replayMarking: false,
      extensionMethods: new Set(),
      steer: true,
    }
  },
  translateMcp: v2McpEvents,
  createSession: (ctx) => new V2Session(ctx),
  // V3 imports a V2 session when it loads or forks it.
  sessionsOpenableBy: ["v2", "v3"],
  listStoredSessions: (ctx) => listV2Sessions(v2SessionsDir(ctx.env)),
}
