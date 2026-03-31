// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * LangGraph Agent Streaming Parser
 * 
 * This parser processes Server-Sent Events (SSE) from LangGraph agents that use
 * the LangChain message format. LangGraph agents stream responses as AIMessageChunk
 * objects with content arrays.
 * 
 * EVENTS HANDLED:
 * 1. AIMessageChunk with empty content - Signals message start
 *    Format: {"type": "AIMessageChunk", "content": []}
 *    Action: Adds newline separator between messages
 * 
 * 2. AIMessageChunk with text content - Contains incremental text
 *    Format: {"type": "AIMessageChunk", "content": [{"type": "text", "text": "Hello", "index": 0}]}
 *    Action: Extracts and appends text from content blocks
 */

/**
 * Parse a streaming chunk from a LangGraph agent.
 * 
 * @param {string} line - The SSE line to parse
 * @param {string} currentCompletion - The accumulated completion text
 * @param {Function} updateCallback - Callback to update the UI with new text
 * @returns {string} Updated completion text
 */
export const parseStreamingChunk = (line, currentCompletion, updateCallback) => {
  // Skip empty lines
  if (!line || !line.trim()) {
    return currentCompletion;
  }

  // Strip "data: " prefix from SSE format
  if (!line.startsWith('data: ')) {
    return currentCompletion;
  }

  const data = line.substring(6).trim();

  // Skip empty data
  if (!data) {
    return currentCompletion;
  }

  // Parse JSON events
  try {
    const json = JSON.parse(data);

    // Handle LangGraph format: AIMessageChunk only
    // Example: {"content": [{"type": "text", "text": "Hello", "index": 0}], "type": "AIMessageChunk"}
    if (json.type === 'AIMessageChunk' && Array.isArray(json.content)) {
      // Handle empty content array (message start)
      if (json.content.length === 0) {
        if (currentCompletion) {  // Only add newline if there's previous content
          const newCompletion = currentCompletion + '\n\n';
          updateCallback(newCompletion);
          return newCompletion;
        }
        return currentCompletion;
      }
      
      // Extract text from content blocks
      const textContent = json.content
        .filter(block => block.type === 'text' && block.text)
        .map(block => block.text)
        .join('');
      
      if (textContent) {
        const newCompletion = currentCompletion + textContent;
        updateCallback(newCompletion);
        return newCompletion;
      }
    }

    // All other events are ignored (tool messages, metadata, etc.)
    return currentCompletion;
  } catch {
    // If JSON parsing fails, skip this line
    console.debug('Failed to parse streaming event:', data);
    return currentCompletion;
  }
};
