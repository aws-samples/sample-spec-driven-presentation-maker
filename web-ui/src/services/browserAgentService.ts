/**
 * Browser ACP service — uses WebSocket to sdpm_app server instead of Tauri shell.
 * Enabled when NEXT_PUBLIC_SDPM_MODE=browser or window.__SDPM_BROWSER__ is set.
 */

let ws: WebSocket | null = null;
let requestId = 0;
const pending = new Map<number, (v: unknown) => void>();
let streamCallback: ((text: string) => void) | null = null;
let toolCallback: ((name: string, data: unknown) => void) | null = null;
let turnEndResolve: (() => void) | null = null;
let sessionId: string | null = null;

type Agent = {
  id: string; displayName: string; path: string; args: string[];
  env: Record<string, string>; subagentTool: string; restartOnNewChat: boolean;
  subagentQueryField: "query" | "prompt";
};

function getActiveAgent(): Agent {
  try {
    const stored = localStorage.getItem("sdpm-acp-agents");
    const activeId = localStorage.getItem("sdpm-acp-active") || "kiro-cli";
    if (stored) {
      const agents: Agent[] = JSON.parse(stored);
      return agents.find(a => a.id === activeId) || agents[0];
    }
  } catch { /* ignore */ }
  return {
    id: "kiro-cli", displayName: "Kiro CLI",
    path: "kiro-cli", args: ["acp", "--agent", "sdpm-spec"], env: {},
    subagentTool: "use_subagent", restartOnNewChat: true,
    subagentQueryField: "query",
  };
}

async function rpc(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  if (!ws) throw new Error("ACP not connected");
  const id = ++requestId;
  ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  return new Promise(resolve => pending.set(id, resolve));
}

function handleLine(line: string) {
  if (!line.trim()) return;
  let msg: Record<string, unknown>;
  try { msg = JSON.parse(line); } catch { return; }

  if (msg.id != null && pending.has(msg.id as number)) {
    const r = pending.get(msg.id as number)!;
    pending.delete(msg.id as number);
    r(msg.result);
    const res = msg.result as Record<string, unknown> | undefined;
    if ((res?.stopReason === "end_turn" || res?.stopReason === "cancelled") && turnEndResolve) {
      turnEndResolve(); turnEndResolve = null;
    }
    return;
  }

  if (msg.method === "session/request_permission") {
    const reqId = msg.id as string;
    if (reqId && ws) ws.send(JSON.stringify({ jsonrpc: "2.0", id: reqId, result: { optionId: "allow_always" } }));
    return;
  }

  if (msg.method === "session/update" || msg.method === "_kiro.dev/session/update") {
    const params = msg.params as Record<string, unknown>;
    const update = params.update as Record<string, unknown> | undefined;
    if (!update) return;
    const type = update.sessionUpdate as string;
    if (type === "agent_message_chunk") {
      const content = update.content as { text?: string } | undefined;
      if (content?.text && streamCallback) streamCallback(content.text);
    } else if (type === "tool_call" || type === "tool_call_update") {
      if (toolCallback) toolCallback(String(update.title || update.name || ""), update);
    }
  }
}

async function ensureConnected(): Promise<void> {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  const a = getActiveAgent();
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/acp`;
  ws = new WebSocket(url);
  await new Promise<void>((resolve, reject) => {
    ws!.onopen = () => resolve();
    ws!.onerror = reject;
  });
  // Send agent config as first message
  ws.send(JSON.stringify({ cmd: a.path, args: a.args, env: a.env }));
  ws.onmessage = e => handleLine(String(e.data));
  ws.onclose = () => { ws = null; sessionId = null; };

  await rpc("initialize", {
    protocolVersion: 1,
    clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } },
    clientInfo: { name: "sdpm-browser", version: "0.1.0" },
  });
  const result = await rpc("session/new", { cwd: "/tmp", mcpServers: [] }) as Record<string, unknown>;
  sessionId = result.sessionId as string;
}

export async function invokeAgent(
  query: string,
  _sessionId: string,
  onStreamUpdate: (t: string) => void,
  _accessToken: string,
  _userId: string,
  onToolUse?: (name: string, data: unknown) => void,
): Promise<string> {
  await ensureConnected();
  streamCallback = onStreamUpdate;
  toolCallback = onToolUse || null;
  let completion = "";
  const originalStream = streamCallback;
  streamCallback = (t: string) => { completion += t; originalStream(t); };
  await new Promise<void>(resolve => {
    turnEndResolve = resolve;
    rpc("session/prompt", { sessionId, prompt: [{ type: "text", text: query }] });
  });
  return completion;
}

export function generateSessionId(): string {
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
export function setAgentConfig(_cfg: unknown): void { /* no-op */ }
export async function startAgent(): Promise<void> { await ensureConnected(); }
export async function stopAgent(): Promise<void> { ws?.close(); ws = null; sessionId = null; }
export async function ensureAgent(): Promise<void> { await ensureConnected(); }
