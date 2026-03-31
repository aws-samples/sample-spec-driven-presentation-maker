// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * AgentCore Service - Streaming Response Handler
 *
 * Handles streaming responses from AgentCore agents using Server-Sent Events (SSE).
 *
 * CUSTOMIZATION FOR OTHER AGENT TYPES:
 * This service dynamically loads the appropriate parser based on the agent pattern.
 * The parser processes each streaming event. See strandsParser.js and langgraphParser.js for examples.
 * To support other agent frameworks, create a new parser file and update config.yaml.
 */

// Generate a UUID
const generateId = () => {
  return crypto.randomUUID();
}

// Configuration - will be populated from aws-exports.json
const AGENT_CONFIG = {
  AGENT_RUNTIME_ARN: "",
  AWS_REGION: "us-east-1",
}

let currentParser = null;

// Set configuration from environment or aws-exports
export const setAgentConfig = async (runtimeArn, region = "us-east-1", agentPattern = "strands-single-agent") => {
  AGENT_CONFIG.AGENT_RUNTIME_ARN = runtimeArn
  AGENT_CONFIG.AWS_REGION = region
  
  if (agentPattern === 'langgraph-single-agent') {
    currentParser = await import('./langgraphParser.js');
  } else {
    currentParser = await import('./strandsParser.js');
  }
}

/**
 * Invokes the AgentCore runtime with streaming support
 */
export const invokeAgentCore = async (query, sessionId, onStreamUpdate, accessToken, userId, onToolUse, signal) => {
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
    const payload = {
      prompt: query,
      runtimeSessionId: sessionId,
      userId: userId,
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
    if (currentParser.resetParserState) currentParser.resetParserState();

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
              completion = currentParser.parseStreamingChunk(line, completion, onStreamUpdate, onToolUse);
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
 * Generate a new session ID
 */
export const generateSessionId = () => {
  return generateId()
}
