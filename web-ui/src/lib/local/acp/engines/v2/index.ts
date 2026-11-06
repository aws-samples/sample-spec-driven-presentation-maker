// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** The V2 engine adapter (kiro-cli's agent engine before V3). */
import type { EngineAdapter, EngineCapabilities } from "../../engine"
import type { InitializeResponse } from "../../schema"
import { V2Session } from "./session"

export const v2Adapter: EngineAdapter = {
  id: "v2",
  capabilities(init: InitializeResponse): EngineCapabilities {
    const session = init.agentCapabilities?.sessionCapabilities ?? {}
    return {
      session: { list: Boolean(session.list), close: Boolean(session.close), delete: Boolean(session.delete), fork: false },
      replayMarking: false,
      extensionMethods: new Set(),
      steer: true,
    }
  },
  createSession: (ctx) => new V2Session(ctx),
}
