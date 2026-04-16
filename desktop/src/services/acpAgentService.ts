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

/** Resolve project root (one level up from desktop/). */
async function resolveProjectRoot(): Promise<string> {
  const { resolveResource } = await import("@tauri-apps/api/path");
  // In dev mode, Tauri runs from desktop/src-tauri, so go up to project root
  // Use a simple heuristic: go up from current dir until we find prompts/
  // For now, hardcode relative to desktop/
  return "..";
}

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
  console.log("[acp raw]", line.substring(0, 200));
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

  // prompt response with stopReason → treat as turn end
  if (msg.id != null && msg.result) {
    const result = msg.result as Record<string, unknown>;
    if (result.stopReason && turnEndResolve) {
      turnEndResolve();
      turnEndResolve = null;
    }
    return;
  }

  // JSON-RPC notification (no id)
  if (msg.method === "session/update") {
    const params = msg.params as Record<string, unknown>;
    const update = params.update as Record<string, unknown>;
    if (!update) return;

    const type = update.sessionUpdate as string;

    if (type === "agent_message_chunk") {
      const content = update.content as Record<string, unknown>;
      if (content?.text && streamCallback) {
        streamCallback(content.text as string);
      }
    }

    if (type === "tool_use") {
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

    if (type === "tool_call_update") {
      if (toolCallback) {
        toolCallback(update.name as string || "__tool_stream__", {
          toolUseId: update.toolUseId,
          name: update.name,
          stream: true,
          data: update.data || {},
        });
      }
    }

    if (type === "turn_end" || type === "end_turn") {
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

  const cmd = Command.create("kiro-cli", ["acp", "--agent", "sdpm-spec"], {
    cwd: await resolveProjectRoot(),
  });

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
    console.warn("[acp] process closed");
    child = null;
    sessionId = null;
  });

  cmd.on("error", (err: string) => {
    console.error("[acp] process error:", err);
  });

  child = await cmd.spawn();
  console.log("[acp] spawned kiro-cli acp");

  // Initialize ACP connection
  const initResult = await rpcRequest("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: true, writeTextFile: true } },
    clientInfo: { name: "sdpm-desktop", version: "0.1.0" },
  });

  console.log("[acp] initialized:", JSON.stringify(initResult));

  // Create session
  const { homeDir } = await import("@tauri-apps/api/path");
  const home = await homeDir();
  const cwd = `${home.replace(/\/+$/, "")}/Documents/SDPM-Presentations`;
  console.log("[acp] creating session with cwd:", cwd);
  const result = await rpcRequest("session/new", { cwd, mcpServers: [] }) as Record<string, unknown>;
  sessionId = result.sessionId as string;
  console.log("[acp] session created:", sessionId);
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
    console.log("[acp] starting agent...");
    await startAgent();
    console.log("[acp] agent started, sessionId:", sessionId);
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
    prompt: [{ type: "text", text: query }],
  });

  // rpcRequest resolves when stopReason response arrives — turn is done
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
