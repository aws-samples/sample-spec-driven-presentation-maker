// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentCore Service - Streaming Response Handler
 *
 * Handles streaming responses from AgentCore agents using Server-Sent Events (SSE).
 */

import * as parser from './strandsParser.js';
import { getAllowedModels } from "@/lib/allowedModels";
import { IS_LOCAL } from "@/lib/mode";

// Read the user's selected chat model from localStorage, validated against the allowed list.
function readSelectedChatModelId() {
  try {
    const allowed = getAllowedModels();
    if (allowed.length === 0) return undefined;
    const prefs = JSON.parse(localStorage.getItem("sdpm-prefs") || "{}");
    if (prefs.chatModelId && allowed.some((m) => m.modelId === prefs.chatModelId)) {
      return prefs.chatModelId;
    }
  } catch { /* ignore */ }
  return undefined;
}

function readSelectedCreateModelId() {
  try {
    const allowed = getAllowedModels();
    if (allowed.length === 0) return undefined;
    const prefs = JSON.parse(localStorage.getItem("sdpm-prefs") || "{}");
    if (prefs.createModelId) {
      const model = allowed.find((m) => m.modelId === prefs.createModelId);
      if (model && model.composable !== false) return prefs.createModelId;
    }
  } catch { /* ignore */ }
  return undefined;
}

// Generate a UUID
const generateId = () => {
  return crypto.randomUUID();
}

// Configuration - will be populated from aws-exports.json
const AGENT_CONFIG = {
  AGENT_RUNTIME_ARN: "",
  AWS_REGION: "us-east-1",
}

// Set configuration from environment or aws-exports
export const setAgentConfig = (runtimeArn, region = "us-east-1") => {
  AGENT_CONFIG.AGENT_RUNTIME_ARN = runtimeArn
  AGENT_CONFIG.AWS_REGION = region
}

/**
 * Invokes the AgentCore runtime with streaming support
 */
export const invokeAgentCore = async (query, sessionId, onStreamUpdate, accessToken, userId, onToolUse, signal, mode, deckId, continuedFrom) => {
  // Local mode: proxy through Next.js API Route → kiro-cli acp
  if (IS_LOCAL) {
    return invokeLocalAgent(query, sessionId, onStreamUpdate, onToolUse, signal, mode, deckId, continuedFrom);
  }

  try {
    if (!userId) {
      throw new Error("No valid user ID found in session. Please ensure you are authenticated.")
    }

    if (!accessToken) {
      throw new Error("No valid access token found. Please ensure you are authenticated.")
    }

    if (!AGENT_CONFIG.AGENT_RUNTIME_ARN) {
      throw new Error("Agent Runtime ARN not configured")
    }

    // Bedrock Agent Core endpoint
    const endpoint = `https://bedrock-agentcore.${AGENT_CONFIG.AWS_REGION}.amazonaws.com`

    // URL encode the agent ARN
    const escapedAgentArn = encodeURIComponent(AGENT_CONFIG.AGENT_RUNTIME_ARN)

    // Construct the URL
    const url = `${endpoint}/runtimes/${escapedAgentArn}/invocations?qualifier=DEFAULT`

    // Generate trace ID
    const traceId = `1-${Math.floor(Date.now() / 1000).toString(16)}-${generateId()}`

    // Set up headers
    const headers = {
      Authorization: `Bearer ${accessToken}`,
      "X-Amzn-Trace-Id": traceId,
      "Content-Type": "application/json",
      "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
    }

    // Create the payload
    const selectedChatModelId = readSelectedChatModelId();
    const selectedCreateModelId = readSelectedCreateModelId();
    const payload = {
      prompt: query,
      runtimeSessionId: sessionId,
      userId: userId,
      mode: mode || "spec",
      ...(selectedChatModelId ? { chatModelId: selectedChatModelId } : {}),
      ...(selectedCreateModelId ? { createModelId: selectedCreateModelId } : {}),
    }

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal,
    })

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(`HTTP ${response.status}: ${errorText}`)
    }

    let completion = '';
    let buffer = '';

    // Reset parser state for new request
    if (parser.resetParserState) parser.resetParserState();

    // Handle streaming response
    if (response.body) {
      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value, { stream: true });
          buffer += chunk;

          // Process complete lines (SSE format uses newlines as delimiters)
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // Keep incomplete line in buffer

          for (const line of lines) {
            if (line.trim()) {
              completion = parser.parseStreamingChunk(line, completion, onStreamUpdate, onToolUse);
            }
          }
        }
      } finally {
        reader.releaseLock()
      }
    } else {
      // Fallback for non-streaming response
      completion = await response.text()
      onStreamUpdate(completion)
    }

    return completion
  } catch (error) {
    console.error("Error invoking AgentCore:", error)
    throw error
  }
}

/**
 * Stop a running AgentCore Runtime session.
 * Immediately terminates the specified session and stops any ongoing streaming responses,
 * including all ThreadPool-based composer agents inside the container.
 * Fire-and-forget: errors are logged but not thrown.
 */
export const stopRuntimeSession = async (sessionId, accessToken) => {
  try {
    if (!sessionId || !accessToken || !AGENT_CONFIG.AGENT_RUNTIME_ARN) return
    const endpoint = `https://bedrock-agentcore.${AGENT_CONFIG.AWS_REGION}.amazonaws.com`
    const escapedAgentArn = encodeURIComponent(AGENT_CONFIG.AGENT_RUNTIME_ARN)
    const url = `${endpoint}/runtimes/${escapedAgentArn}/stopruntimesession?qualifier=DEFAULT`
    await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": sessionId,
      },
    })
  } catch (error) {
    console.error("Error stopping AgentCore session:", error)
  }
}

/**
 * Generate a new session ID
 */
export const generateSessionId = () => {
  return generateId()
}

/**
 * Invoke the local ACP agent via API Route.
 * Reads SSE stream from /api/agent/invoke and feeds events through the same
 * strandsParser used by the cloud path, so ChatPanel works unchanged.
 */
const invokeLocalAgent = async (query, sessionId, onStreamUpdate, onToolUse, signal, mode, deckId, continuedFrom) => {
  const response = await fetch('/api/agent/invoke', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      sessionId,
      mode: mode || 'spec',
      deckId: deckId || undefined,
      continuedFrom: continuedFrom || undefined,
    }),
    signal,
  });

  if (!response.ok) {
    const errorText = await response.text();
    console.error('[invokeLocal] error:', errorText);
    const error = new Error(`Local agent error: ${response.status}: ${errorText}`);
    // 409 session conflicts carry a stable `code` (lib/local/sessionErrors.ts) the chat UI translates.
    try { error.code = JSON.parse(errorText).code; } catch { /* non-JSON body */ }
    throw error;
  }

  let completion = '';
  let buffer = '';

  if (parser.resetParserState) parser.resetParserState();

  if (response.body) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.trim()) {
            if (line.startsWith('data: ')) {
              let event;
              try { event = JSON.parse(line.substring(6).trim()); } catch { /* parser handles malformed lines */ }
              if (event?.status === 'error' && event.error) throw new Error(event.error);
            }
            completion = parser.parseStreamingChunk(line, completion, onStreamUpdate, onToolUse);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  return completion;
}
