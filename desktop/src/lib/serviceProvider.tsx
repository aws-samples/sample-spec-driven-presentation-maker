/**
 * Service Provider — resolves local service implementations for desktop app.
 *
 * Components import services through this provider instead of directly.
 * Web version continues importing from web-ui/src/services/ — unaffected.
 */

"use client";

import React, { createContext, useContext, useMemo, type PropsWithChildren } from "react";
import * as deckService from "@desktop/services/localDeckService";
import * as uploadService from "@desktop/services/localUploadService";
import * as agentService from "@desktop/services/acpAgentService";

export interface ServiceContext {
  deck: typeof deckService;
  upload: typeof uploadService;
  agent: {
    invokeAgent: typeof agentService.invokeAgent;
    generateSessionId: typeof agentService.generateSessionId;
    setAgentConfig: typeof agentService.setAgentConfig;
    startAgent: typeof agentService.startAgent;
    stopAgent: typeof agentService.stopAgent;
  };
  /** Always "authenticated" in local mode. */
  isAuthenticated: true;
  /** Dummy token for API compat. */
  idToken: string;
  /** Local user ID. */
  userId: string;
}

const Ctx = createContext<ServiceContext | null>(null);

export function ServiceProvider({ children }: PropsWithChildren) {
  const value = useMemo<ServiceContext>(
    () => ({
      deck: deckService,
      upload: uploadService,
      agent: {
        invokeAgent: agentService.invokeAgent,
        generateSessionId: agentService.generateSessionId,
        setAgentConfig: agentService.setAgentConfig,
        startAgent: agentService.startAgent,
        stopAgent: agentService.stopAgent,
      },
      isAuthenticated: true,
      idToken: "local",
      userId: "local-user",
    }),
    [],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useServices(): ServiceContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useServices must be used within ServiceProvider");
  return ctx;
}
