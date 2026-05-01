// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Resolve NEXT_PUBLIC_* env vars from config.yaml + model-metadata.ts.
 * Used by buildspec.yml to inject model config into the web-ui build.
 *
 * Usage: cd infra && node lib/resolve-model-env.js
 * Output: export KEY=VALUE lines suitable for `eval "$(...)"`.
 */
const fs = require("fs");
const path = require("path");
const yaml = require("yaml");

// Parse MODEL_METADATA from the .ts source directly (simple regex, no TS compiler needed).
const metadataSource = fs.readFileSync(path.join(__dirname, "model-metadata.ts"), "utf8");
const metadata = {};
const re = /"([^"]+)":\s*\{[^}]*displayName:\s*"([^"]*)"(?:[^}]*description:\s*"([^"]*)")?(?:[^}]*composable:\s*(false))?/g;
let match;
while ((match = re.exec(metadataSource)) !== null) {
  metadata[match[1]] = { displayName: match[2], description: match[3], composable: match[4] !== "false" };
}

const config = yaml.parse(fs.readFileSync(path.join(__dirname, "../config.yaml"), "utf8"));
const ids = config.model?.allowedModelIds ?? [];
const models = ids.map((id) => ({
  modelId: id,
  displayName: metadata[id]?.displayName,
  description: metadata[id]?.description,
  composable: metadata[id]?.composable !== false,
}));

console.log(`export NEXT_PUBLIC_ALLOWED_MODELS=${JSON.stringify(JSON.stringify(models))}`);
console.log(`export NEXT_PUBLIC_DEFAULT_CHAT_MODEL_ID=${config.model?.defaults?.chat || ""}`);
console.log(`export NEXT_PUBLIC_DEFAULT_CREATE_MODEL_ID=${config.model?.defaults?.create || config.model?.defaults?.chat || ""}`);
