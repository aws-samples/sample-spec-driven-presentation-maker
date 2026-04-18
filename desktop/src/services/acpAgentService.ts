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

/** Resolve project root via Tauri command. */
async function resolveProjectRoot(): Promise<string> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<string>("get_project_root");
}

let child: Child | null = null;
let requestId = 0;
let sessionId: string | null = null;
let currentChatSessionId: string | null = null;

type PendingResolve = (value: unknown) => void;
const pending = new Map<number, PendingResolve>();

let streamCallback: ((text: string) => void) | null = null;
let toolCallback: ((name: string, data: unknown) => void) | null = null;
let turnEndResolve: (() => void) | null = null;
let subagentToolCallId: string | null = null; // Track the parent's subagent tool call
let totalGroups = 0; // Number of subagents spawned in current crew
let subagentQueryQueue: string[] = []; // Pending slugs, consumed in arrival order
const subagentGroups = new Map<string, { group: number; slugs: string }>(); // msgSessionId → group/slugs

/** Extract slide slugs from subagent query string.
 *  e.g. "deck_id=/x/y. Build slides: title, agenda, closing. See specs/." → "title, agenda, closing"
 */
function extractSlugs(query: string): string {
  const m = query.match(/slides?:\s*([a-z0-9,\-\s]+?)(?:\.|$|\n)/i);
  return m ? m[1].trim() : "";
}

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
  console.log("[acp raw]", line.substring(0, 500));
  let msg: Record<string, unknown>;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }

  // JSON-RPC response (has id)
  if (msg.id != null && pending.has(msg.id as number)) {
    console.log("[acp] resolving pending id:", msg.id);
    const resolve = pending.get(msg.id as number)!;
    pending.delete(msg.id as number);
    resolve(msg.result);
    // Also check if this is end_turn
    const r = msg.result as Record<string, unknown> | undefined;
    if ((r?.stopReason === "end_turn" || r?.stopReason === "cancelled") && turnEndResolve) {
      turnEndResolve();
      turnEndResolve = null;
    }
    return;
  }

  // Subsequent response (id not in pending) — check for end_turn
  if (msg.id != null && msg.result) {
    const result = msg.result as Record<string, unknown>;
    console.log("[acp] unmatched response id:", msg.id, "stopReason:", result.stopReason);
    if ((result.stopReason === "end_turn" || result.stopReason === "cancelled") && turnEndResolve) {
      turnEndResolve();
      turnEndResolve = null;
    }
    return;
  }

  // Permission request — auto-approve
  if (msg.method === "session/request_permission") {
    const params = msg.params as Record<string, unknown>;
    const reqId = msg.id as string;
    console.log("[acp] permission request, id:", reqId, "tool:", JSON.stringify((params.toolCall as Record<string,unknown>)?.title));
    if (reqId && child) {
      const reply = JSON.stringify({
        jsonrpc: "2.0",
        id: reqId,
        result: { optionId: "allow_always" },
      }) + "\n";
      child.write(reply).catch(() => {});
    }
    return;
  }

  // JSON-RPC notification (no id) — only process our session
  if (msg.method === "session/update" || msg.method === "_kiro.dev/session/update") {
    const params = msg.params as Record<string, unknown>;
    const msgSessionId = params.sessionId as string;

    // Subagent session — forward tool events as progress to parent's subagent ToolCard
    if (msgSessionId !== sessionId && subagentToolCallId && toolCallback) {
      const update = params.update as Record<string, unknown>;
      if (!update) return;
      const type = update.sessionUpdate as string;

      // Resolve group/slugs for this subagent session
      let groupInfo = subagentGroups.get(msgSessionId);
      if (!groupInfo) {
        const idx = subagentGroups.size;
        const slugs = subagentQueryQueue[idx] || `group ${idx + 1}`;
        groupInfo = { group: idx + 1, slugs };
        subagentGroups.set(msgSessionId, groupInfo);
        // Emit "starting" status for this new group
        toolCallback("compose_slides", {
          toolUseId: subagentToolCallId,
          name: "compose_slides",
          stream: true,
          data: { group: groupInfo.group, total_groups: totalGroups, slugs: groupInfo.slugs, status: "starting" },
        });
      }

      const emit = (data: Record<string, unknown>) => toolCallback!("compose_slides", {
        toolUseId: subagentToolCallId,
        name: "compose_slides",
        stream: true,
        data: { group: groupInfo!.group, slugs: groupInfo!.slugs, ...data },
      });

      if (type === "tool_call") {
        const title = (update.title || "") as string;
        const toolName = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title;
        emit({ tool: toolName, toolUseId: update.toolCallId as string || "", input: update.rawInput || {} });
      } else if (type === "tool_call_update") {
        const status = update.status as string;
        if (status === "completed" || status === "error" || status === "failed") {
          emit({
            toolResult: update.toolCallId as string || "",
            toolStatus: status === "completed" ? "success" : "error",
          });
        }
      } else if (type === "turn_end" || type === "end_turn") {
        emit({ status: "done" });
      }
      return;
    }

    if (msgSessionId !== sessionId) return; // Ignore other sessions
    const update = params.update as Record<string, unknown>;
    if (!update) return;

    const type = update.sessionUpdate as string;

    if (type === "agent_message_chunk") {
      const content = update.content as Record<string, unknown>;
      if (content?.text && streamCallback) {
        streamCallback(content.text as string);
      }
    }

    if (type === "tool_call" || type === "tool_call_chunk") {
      if (toolCallback) {
        const toolCallId = update.toolCallId as string || "";
        const title = (update.title || update.name || "") as string;
        let name = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title;
        const input = (update.rawInput || update.input || {}) as Record<string, unknown>;
        // Track subagent tool call for progress forwarding
        if (title === "Spawning agent crew" || name === "subagent" || name === "use_subagent") {
          subagentToolCallId = toolCallId;
          subagentGroups.clear();
          // Parse subagent queries to count groups and pre-register slugs by arrival order
          const content = (input.content as Record<string, unknown> | undefined);
          const subagents = (content?.subagents as Array<Record<string, unknown>> | undefined) || [];
          totalGroups = subagents.length;
          subagentQueryQueue = subagents.map((s) => extractSlugs(String(s.query || "")));
          // Rename to "compose_slides" so Web UI TOOL_META matches and subagent
          // stream events (also using "compose_slides") attach to this toolUse.
          name = "compose_slides";
        }
        toolCallback(name, { toolUseId: toolCallId, name, input, started: true });
      }
    }

    if (type === "tool_call_update") {
      if (toolCallback) {
        const toolCallId = update.toolCallId as string || "";
        const title = (update.title || "") as string;
        const status = update.status as string;
        // Extract tool name from title like "Running: @sdpm/init_presentation"
        let toolName = title.replace(/^Running:\s*@sdpm\//, "").replace(/^Running:\s*/, "") || title;
        // If this update corresponds to the tracked subagent, rename for UI match
        if (toolCallId && toolCallId === subagentToolCallId) {
          toolName = "compose_slides";
        }

        if (status === "completed") {
          // Parse rawOutput to extract result
          let result: Record<string, unknown> = {};
          try {
            const rawOutput = update.rawOutput as Record<string, unknown>;
            const items = rawOutput?.items as Array<Record<string, unknown>>;
            if (items?.[0]) {
              const json = items[0].Json as Record<string, unknown>;
              const content = json?.content as Array<Record<string, unknown>>;
              if (content?.[0]?.text) {
                result = JSON.parse(content[0].text as string);
              }
            }
          } catch {}

          // Derive deckId from output_dir if present (mcp-local returns output_dir, not deckId)
          if (result.output_dir && !result.deckId) {
            const dirName = (result.output_dir as string).split("/").pop() || "";
            result.deckId = dirName;
          }
          console.log("[acp tool completed]", toolName, "deckId:", result.deckId, "result keys:", Object.keys(result));

          toolCallback(toolName, {
            toolUseId: toolCallId, name: toolName,
            status: "success",
            result,
            completed: true,
          });
        } else {
          // In-progress update — ensure the toolUse is registered (in case tool_call was missed)
          const input = (update.rawInput || update.input || {}) as Record<string, unknown>;
          toolCallback(toolName, {
            toolUseId: toolCallId, name: toolName,
            input,
            started: true,
          });
        }
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

/** Current model override (null = kiro-cli default). */
let currentModel: string | null = null;

/** Start the ACP agent process. */
export async function startAgent(): Promise<void> {
  if (child) return;

  // kiro-cli + --agent flag (required by kiro-cli's ACP impl).
  // Other ACP agents: customize this spawn call.
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
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
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

  // Populate model selector — prefer ACP standard configOptions, fall back to kiro-cli's `models`
  type ConfigOption = { id: string; category?: string; currentValue: string; options: { value: string; name: string; description?: string }[] };
  const configOptions = result.configOptions as ConfigOption[] | undefined;
  const modelOpt = configOptions?.find(o => o.category === "model" || o.id === "model");

  let currentModelId = "";
  let availableModels: { modelId: string; name: string; description?: string }[] = [];
  if (modelOpt) {
    currentModelId = modelOpt.currentValue;
    availableModels = modelOpt.options.map(o => ({ modelId: o.value, name: o.name, description: o.description }));
  } else {
    // kiro-cli non-standard shape
    const modelsInfo = result.models as { currentModelId?: string; availableModels?: typeof availableModels } | undefined;
    if (modelsInfo?.availableModels) {
      currentModelId = modelsInfo.currentModelId || "";
      availableModels = modelsInfo.availableModels;
    }
  }
  if (availableModels.length > 0) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const g = globalThis as any;
    if (g.__sdpmModels) {
      g.__sdpmModels.current = currentModelId;
      g.__sdpmModels.available = availableModels.filter(
        m => !m.description?.startsWith("[Internal]") && !m.description?.startsWith("[Deprecated]")
      );
      g.__sdpmModels.listeners.forEach((fn: () => void) => fn());
    }
  }

  // Apply stored model preference via ACP standard method
  const storedModel = typeof sessionStorage !== "undefined" ? sessionStorage.getItem("sdpm-model") : null;
  if (storedModel && storedModel !== currentModelId) {
    try {
      await rpcRequest("session/set_config_option", {
        sessionId, configId: "model", value: storedModel,
      });
    } catch { /* agent may not support configOptions yet */ }
  }
}

/** Stop the kiro-cli acp process. */
export async function stopAgent(): Promise<void> {
  if (child) {
    try { await child.kill(); } catch { /* already dead */ }
    child = null;
    sessionId = null;
    pending.clear();
    subagentGroups.clear();
    subagentToolCallId = null;
    subagentQueryQueue = [];
    totalGroups = 0;
    turnEndResolve = null;
  }
}

/**
 * Invoke the agent with a prompt. Same signature as agentCoreService.invokeAgentCore
 * so ChatPanel.tsx works unchanged.
 */
/** Ensure the agent process is running (idempotent). Call early to populate model list. */
let startPromise: Promise<void> | null = null;
export async function ensureAgent(): Promise<void> {
  if (child) return;
  if (!startPromise) startPromise = startAgent().finally(() => { startPromise = null; });
  return startPromise;
}

/** Set a session config option via ACP standard method. */
export async function setConfigOption(configId: string, value: string): Promise<void> {
  if (!child || !sessionId) return;
  await rpcRequest("session/set_config_option", { sessionId, configId, value });
}

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
    await ensureAgent();
    currentChatSessionId = _sessionId;
    console.log("[acp] agent started, sessionId:", sessionId);
  } else if (_sessionId !== currentChatSessionId) {
    // New chat — create new ACP session (standard). If agent identity is lost
    // after session/new (kiro-cli bug), fall back to process restart.
    console.log("[acp] new chat session, creating new ACP session");
    try {
      const { homeDir } = await import("@tauri-apps/api/path");
      const home = await homeDir();
      const cwd = `${home.replace(/\/+$/, "")}/Documents/SDPM-Presentations`;
      const result = await rpcRequest("session/new", { cwd, mcpServers: [] }) as Record<string, unknown>;
      sessionId = result.sessionId as string;
      currentChatSessionId = _sessionId;
    } catch {
      // Fallback: full process restart (kiro-cli workaround)
      console.log("[acp] session/new failed, restarting process");
      await stopAgent();
      await startAgent();
      currentChatSessionId = _sessionId;
    }
    console.log("[acp] new ACP session:", sessionId);
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
    // Send cancel directly without rpcRequest (don't consume an id)
    if (child && sessionId) {
      const msg = JSON.stringify({ jsonrpc: "2.0", method: "session/cancel", params: { sessionId } }) + "\n";
      child.write(msg).catch(() => {});
    }
  });

  // Send prompt — don't await (response comes as stopReason later)
  rpcRequest("session/prompt", {
    sessionId,
    prompt: [{ type: "text", text: query }],
  }).then((res) => {
    // Only resolve on end_turn, not tool_use
    const r = res as Record<string, unknown> | undefined;
    console.log("[acp] prompt response:", JSON.stringify(r));
    if (r?.stopReason === "end_turn" || r?.stopReason === "cancelled") {
      if (turnEndResolve) { turnEndResolve(); turnEndResolve = null; }
    }
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
