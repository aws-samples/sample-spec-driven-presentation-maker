/**
 * ACP Agent Service — communicates with kiro-cli acp via Tauri Shell plugin.
 *
 * Spawns `kiro-cli acp --agent sdpm-spec`, sends JSON-RPC requests over stdin,
 * and receives streaming notifications over stdout.
 *
 * Exposes the same callback interface as agentCoreService.js so ChatPanel.tsx
 * works unchanged.
 */

import { Command, type Child } from "@tauri-apps/plugin-shell";

let child: Child | null = null;
let requestId = 0;
let sessionId: string | null = null;

type PendingResolve = (value: unknown) => void;
const pending = new Map<number, PendingResolve>();

let streamCallback: ((text: string) => void) | null = null;
let toolCallback: ((name: string, data: unknown) => void) | null = null;
let turnEndResolve: (() => void) | null = null;

/** Send a JSON-RPC request to kiro-cli acp. */
async function rpcRequest(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!child) throw new Error("ACP agent not started");
  const id = ++requestId;
  const msg = JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n";
  await child.write(msg);
  return new Promise((resolve) => {
    pending.set(id, resolve);
  });
}

/** Handle a line of stdout from kiro-cli acp. */
function handleLine(line: string) {
  if (!line.trim()) return;
  let msg: Record<string, unknown>;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }

  // JSON-RPC response (has id)
  if (msg.id != null && pending.has(msg.id as number)) {
    const resolve = pending.get(msg.id as number)!;
    pending.delete(msg.id as number);
    resolve(msg.result);
    return;
  }

  // JSON-RPC notification (no id)
  if (msg.method === "session/notification") {
    const params = msg.params as Record<string, unknown>;
    const update = params.update as Record<string, unknown>;
    if (!update) return;

    const type = update.type as string;

    if (type === "AgentMessageChunk") {
      const content = update.content as string;
      if (content && streamCallback) {
        streamCallback(content);
      }
    }

    if (type === "ToolCall") {
      if (toolCallback) {
        const status = update.status as string;
        const name = update.name as string || "";
        const toolUseId = update.toolUseId as string || "";
        const input = update.input as Record<string, unknown> || {};

        if (status === "started") {
          toolCallback(name, { toolUseId, name, input: {}, started: true });
        } else if (status === "completed") {
          toolCallback(name, {
            toolUseId, name,
            status: update.error ? "error" : "success",
            result: update.result || {},
            completed: true,
          });
        } else {
          toolCallback(name, { toolUseId, name, input });
        }
      }
    }

    if (type === "ToolCallUpdate") {
      if (toolCallback) {
        toolCallback(update.name as string || "__tool_stream__", {
          toolUseId: update.toolUseId,
          name: update.name,
          stream: true,
          data: update.data || {},
        });
      }
    }

    if (type === "TurnEnd") {
      if (turnEndResolve) {
        turnEndResolve();
        turnEndResolve = null;
      }
    }
  }
}

/** Start the kiro-cli acp process. */
export async function startAgent(): Promise<void> {
  if (child) return;

  const cmd = Command.create("kiro-cli", ["acp", "--agent", "sdpm-spec"]);

  cmd.stdout.on("data", (line: string) => {
    // stdout may contain multiple JSON lines
    for (const l of line.split("\n")) {
      handleLine(l);
    }
  });

  cmd.stderr.on("data", (line: string) => {
    console.warn("[acp stderr]", line);
  });

  cmd.on("close", () => {
    child = null;
    sessionId = null;
  });

  child = await cmd.spawn();

  // Initialize ACP connection
  await rpcRequest("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: true, writeTextFile: true } },
    clientInfo: { name: "sdpm-desktop", version: "0.1.0" },
  });

  // Create session
  const result = await rpcRequest("session/new", {
    cwd: process.env.HOME + "/Documents/SDPM-Presentations",
  }) as Record<string, unknown>;
  sessionId = result.sessionId as string;
}

/** Stop the kiro-cli acp process. */
export async function stopAgent(): Promise<void> {
  if (child) {
    await child.kill();
    child = null;
    sessionId = null;
  }
}

/**
 * Invoke the agent with a prompt. Same signature as agentCoreService.invokeAgentCore
 * so ChatPanel.tsx works unchanged.
 */
export async function invokeAgent(
  query: string,
  _sessionId: string,
  onStreamUpdate: (text: string) => void,
  _accessToken: string,
  _userId: string,
  onToolUse?: (name: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<string> {
  if (!child || !sessionId) {
    await startAgent();
  }

  let completion = "";
  streamCallback = (chunk: string) => {
    completion += chunk;
    onStreamUpdate(completion);
  };
  toolCallback = onToolUse || null;

  const turnEnd = new Promise<void>((resolve) => {
    turnEndResolve = resolve;
  });

  signal?.addEventListener("abort", () => {
    rpcRequest("session/cancel", { sessionId }).catch(() => {});
  });

  await rpcRequest("session/prompt", {
    sessionId,
    content: [{ type: "text", text: query }],
  });

  await turnEnd;

  streamCallback = null;
  toolCallback = null;
  return completion;
}

/** Generate a session ID (for compatibility with agentCoreService). */
export function generateSessionId(): string {
  return crypto.randomUUID();
}

/** No-op config setter (for compatibility with agentCoreService). */
export async function setAgentConfig(): Promise<void> {}

// Alias for ChatPanel.tsx compatibility
export { invokeAgent as invokeAgentCore };
