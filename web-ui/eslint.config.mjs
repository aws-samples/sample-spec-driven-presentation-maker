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
  {
    rules: {
      "react-hooks/set-state-in-effect": "warn",
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
]

export default eslintConfig
