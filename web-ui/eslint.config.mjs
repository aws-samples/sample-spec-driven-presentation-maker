// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import nextConfig from "eslint-config-next"

const eslintConfig = [
  {
    ignores: ["node_modules/**", "build/**", "delete/**", "tmp/**", ".next/**"],
  },
  // Base Next.js config (react, hooks, import, jsx-a11y, @next/next)
  nextConfig[0],
  // Downgrade set-state-in-effect to warning (valid patterns: fetch loading, dialog reset)
  // Disable no-img-element (project uses dynamic URLs from API / S3 signed URLs)
  {
    rules: {
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/immutability": "warn",
      "@next/next/no-img-element": "off",
    },
  },
  // TypeScript config with rule overrides
  {
    ...nextConfig[1],
    rules: {
      ...nextConfig[1].rules,
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": "warn",
    },
  },
  // Next.js default ignores
  ...(nextConfig.length > 2 ? nextConfig.slice(2) : []),
  // Local ACP layers (lib/local): dependencies point one way, and kiro-cli's engine differences
  // stay in acp/engines/<id>/. One block per file group: a later block that matches a file
  // replaces an earlier block's options for this rule.
  ...localAcpLayers(),
]

function restrict(files, patterns, ignores = []) {
  return {
    files,
    ignores,
    rules: { "@typescript-eslint/no-restricted-imports": ["error", { patterns }] },
  }
}

function localAcpLayers() {
  const L = "src/lib/local"
  const TESTS = ["**/*.test.ts", "**/*.test.tsx", "src/test/**"]
  const engines = { regex: "(^|/)engines(/|$)", message: "Only acp/engine.ts (the registry) imports an engine adapter." }
  const registry = { regex: "(^|/)engine$", message: "The engine registry loads the engine adapters; only hosts.ts uses it." }
  const processManager = { regex: "(^|/)acp-process$", message: "The chat registry depends on this layer, not the other way round." }
  const transport = { regex: "(^|/)acp/transport$", message: "Only hosts.ts and the engine adapters speak to the transport." }
  const chat = { regex: "(^|/)chat$", message: "hosts.ts knows chats only as SessionSinks." }
  const bridge = { regex: "(^|/)sse-bridge$", message: "The SSE bridge is the outermost layer of lib/local." }
  const routes = { regex: "^@/app/", message: "lib/local does not import API routes." }
  const conversation = { regex: "(^|/)conversation(/(compose|tools|steer|turn|index))?$", message: "An engine adapter outputs LocalEvents; the conversation model is not its dependency." }
  const conversationEvents = { regex: "(^|/)conversation/events$", allowTypeImports: true, message: "An engine adapter imports only the LocalEvent types." }
  return [
    restrict(["src/**/*.ts", "src/**/*.tsx"], [engines], [
      `${L}/acp/engine.ts`, `${L}/acp/engines/**`, `${L}/conversation/**`, `${L}/sse-bridge.ts`, ...TESTS,
    ]),
    restrict([`${L}/conversation/**/*.ts`, `${L}/sse-bridge.ts`], [engines, registry, processManager, transport, bridge, routes], TESTS),
    restrict([`${L}/acp/transport.ts`, `${L}/acp/schema.ts`, `${L}/acp/process-tree.ts`], [
      { regex: "(^|/)conversation(/|$)", message: "The transport knows JSON-RPC, not the conversation." },
      engines, registry, processManager, bridge,
    ]),
    restrict([`${L}/hosts.ts`], [engines, processManager, chat, bridge, routes, conversation], TESTS),
    // The registry and the chats reach kiro-cli only through hosts.ts (types excepted).
    restrict([`${L}/acp-process.ts`], [engines, { ...registry, allowTypeImports: true }, { ...transport, allowTypeImports: true }, bridge, routes], TESTS),
    restrict([`${L}/chat.ts`], [engines, { ...registry, allowTypeImports: true }, { ...transport, allowTypeImports: true }, bridge, routes, processManager], TESTS),
    restrict([`${L}/compose-run.ts`], [engines, { ...registry, allowTypeImports: true }, { ...transport, allowTypeImports: true }, bridge, routes, processManager], TESTS),
    restrict([`${L}/acp/engines/v2/**/*.ts`], [
      { regex: "(^|/)v3(/|$)", message: "An engine adapter does not depend on another engine." },
      processManager, bridge, routes, conversation, conversationEvents,
    ], TESTS),
    restrict([`${L}/acp/engines/v3/**/*.ts`], [
      { regex: "(^|/)v2(/|$)", message: "An engine adapter does not depend on another engine." },
      processManager, bridge, routes, conversation, conversationEvents,
    ], TESTS),
  ]
}

export default eslintConfig
