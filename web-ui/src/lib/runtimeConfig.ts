// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Runtime configuration — `/aws-exports.json`, written by the CDK deploy next to the
 * static export. Fetched once per page load and shared by every consumer (auth,
 * deck/upload services, agent config).
 */

export interface RuntimeConfig {
  /** REST API base URL ending with "/" (e.g. https://xxx.execute-api.../prod/). */
  apiBaseUrl?: string
  agentRuntimeArn?: string
  awsRegion?: string
  // Cognito / OIDC settings read by lib/auth.ts
  authority?: string
  client_id?: string
  redirect_uri?: string
  post_logout_redirect_uri?: string
  response_type?: string
  scope?: string
  automaticSilentRenew?: boolean
}

let configPromise: Promise<RuntimeConfig> | null = null

/**
 * Load `/aws-exports.json` once and cache it. A failed load is not cached, so the
 * next call retries.
 *
 * @returns The parsed runtime configuration
 * @throws Error when the file cannot be fetched
 */
export function loadRuntimeConfig(): Promise<RuntimeConfig> {
  if (!configPromise) {
    configPromise = (async () => {
      const response = await fetch("/aws-exports.json")
      if (!response.ok) throw new Error(`Failed to load aws-exports.json: ${response.status}`)
      return (await response.json()) as RuntimeConfig
    })()
    configPromise.catch(() => { configPromise = null })
  }
  return configPromise
}
