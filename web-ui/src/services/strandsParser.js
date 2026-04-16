// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Strands Agent Streaming Parser
 *
 * NOTE: Parsed content may include AI-generated text from Amazon Bedrock.
 * Applications should clearly indicate AI-generated content to end users.
 * 
 * Processes Server-Sent Events (SSE) from Strands agents using
 * the Amazon Bedrock Converse API format.
 * 
 * EVENTS HANDLED:
 * 1. messageStart - Signals the beginning of a new assistant message
 * 2. contentBlockDelta - Contains incremental text content
 * 3. toolUse (custom) - Tool execution events from backend
 *
 * Tool events are passed to toolCallback as structured data,
 * NOT inserted into the completion text.
 */

// Track last seen tool use ID to deduplicate
let _lastToolUseId = null;

/**
 * Reset parser state. Call before each new conversation turn.
 */
export const resetParserState = () => {
  _lastToolUseId = null;
};

/**
 * Parse a streaming chunk from a Strands agent.
 * 
 * @param {string} line - The SSE line to parse
 * @param {string} currentCompletion - The accumulated completion text
 * @param {Function} updateCallback - Callback to update the UI with new text
 * @param {Function} [toolCallback] - Callback for tool use events: (toolName, toolUseData)
 * @returns {string} Updated completion text
 */
export const parseStreamingChunk = (line, currentCompletion, updateCallback, toolCallback) => {
  if (!line || !line.trim()) return currentCompletion;
  if (!line.startsWith('data: ')) return currentCompletion;

  const data = line.substring(6).trim();
  if (!data) return currentCompletion;

  try {
    const json = JSON.parse(data);

    // Keep-alive
    if (json.keepalive) return currentCompletion;

    // MCP status event — pass to toolCallback with special type
    if (json.mcp_status) {
      if (toolCallback) toolCallback('__mcp_status__', { mcpStatus: json.mcp_status });
      return currentCompletion;
    }

    // Tool start events — tool is now executing (no input yet)
    if (json.toolStart) {
      const toolUseId = json.toolStart.toolUseId;
      if (toolUseId && toolUseId === _lastToolUseId) return currentCompletion;
      _lastToolUseId = toolUseId;

      if (toolCallback) toolCallback(json.toolStart.name, { toolUseId, name: json.toolStart.name, input: {}, started: true });
      return currentCompletion;
    }

    // Tool use events — pass to callback with input
    if (json.toolUse) {
      const toolUseId = json.toolUse.toolUseId;
      // Don't deduplicate — this is the completion event with full input
      _lastToolUseId = toolUseId;

      if (toolCallback) toolCallback(json.toolUse.name, json.toolUse);
      return currentCompletion;
    }

    // Tool stream events — progress updates from streaming tools (e.g. compose_slides)
    if (json.toolStream) {
      if (toolCallback) {
        toolCallback(json.toolStream.name || '__tool_stream__', {
          toolUseId: json.toolStream.toolUseId,
          name: json.toolStream.name,
          stream: true,
          data: json.toolStream.data,
        });
      }
      return currentCompletion;
    }

    // Tool result events — pass completed result to callback
    if (json.toolResult) {
      let parsedContent = {};
      try {
        if (json.toolResult.content) parsedContent = JSON.parse(json.toolResult.content);
      } catch { /* content may not be JSON */ }
      if (toolCallback) {
        toolCallback(json.toolResult.name, {
          toolUseId: json.toolResult.toolUseId,
          name: json.toolResult.name,
          status: json.toolResult.status || 'success',
          result: parsedContent,
          rawResult: json.toolResult.content,
          completed: true,
        });
      }
      return currentCompletion;
    }

    // Message start — add separator between messages
    if (json.event?.messageStart?.role === 'assistant') {
      if (currentCompletion) {
        const newCompletion = currentCompletion + '\n\n';
        updateCallback(newCompletion);
        return newCompletion;
      }
      return currentCompletion;
    }

    // Text delta
    if (json.event?.contentBlockDelta?.delta?.text) {
      const newCompletion = currentCompletion + json.event.contentBlockDelta.delta.text;
      updateCallback(newCompletion);
      return newCompletion;
    }

    return currentCompletion;
  } catch {
    console.debug('Failed to parse streaming event:', data);
    return currentCompletion;
  }
};
