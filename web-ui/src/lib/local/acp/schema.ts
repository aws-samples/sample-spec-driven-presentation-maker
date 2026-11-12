// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * The Agent Client Protocol types this client uses, from the ACP SDK (`@agentclientprotocol/sdk`
 * 2.4.x, a devDependency; protocol version 1). Types only: every import of the SDK is
 * `import type` / `export type` (layers.test.ts checks it), so the package never reaches a bundle,
 * and the transport never validates kiro-cli's lines against these types at run time (it reads
 * them as they come, in line order). The fork types are still in the SDK's `/unstable` schema.
 *
 * Kept here: what the SDK does not name, a raw notification as the transport reads it (before any
 * validation) and a JSON-RPC error object. Kiro's extensions (`_meta.kiro`, its own notification
 * methods, extra response fields) are not here; each engine adapter keeps the shapes it reads in
 * its own folder (`engines/<id>/types.ts`).
 */

export type {
  AgentCapabilities,
  CloseSessionRequest,
  ContentBlock,
  DeleteSessionRequest,
  Implementation,
  InitializeResponse,
  ListSessionsRequest,
  ListSessionsResponse,
  LoadSessionResponse,
  NewSessionResponse,
  PermissionOption,
  PromptResponse,
  RequestPermissionOutcome,
  RequestPermissionRequest,
  RequestPermissionResponse,
  SessionCapabilities,
  SessionConfigOption,
  SessionInfo,
  SessionMode,
  SessionModeState,
  SessionNotification,
  SessionUpdate,
  StopReason,
  ToolCall,
  ToolCallUpdate,
} from "@agentclientprotocol/sdk"
export type { ForkSessionRequest, ForkSessionResponse } from "@agentclientprotocol/sdk/unstable"

/** A JSON-RPC error object, as ACP answers a failed request. */
export interface AcpError {
  code: number
  message: string
  data?: unknown
}

/** A notification from the agent (a JSON-RPC message with a method and no id). */
export interface AcpNotification {
  method: string
  params?: unknown
}
