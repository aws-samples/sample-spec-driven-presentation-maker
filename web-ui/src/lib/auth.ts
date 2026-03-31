// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { WebStorageStateStore } from "oidc-client-ts"

// Configuration type matching the cognitoAuthConfig structure
type AwsExportsConfig = {
  authority?: string
  client_id?: string
  redirect_uri?: string
  post_logout_redirect_uri?: string
  response_type?: string
  scope?: string
  automaticSilentRenew?: boolean
  userStore: WebStorageStateStore | undefined
}

/**
 * Configuration Priority (highest to lowest):
 * 1. Environment variables (NEXT_PUBLIC_COGNITO_*)
 * 2. aws-exports.json file
 * 3. Default values
 */

// Cache for loaded config
let configCache: AwsExportsConfig | null = null
let configPromise: Promise<AwsExportsConfig | null> | null = null

// Load configuration from aws-exports.json at runtime
async function loadAwsConfig(): Promise<AwsExportsConfig | null> {
  if (configCache) {
    return configCache
  }

  if (configPromise) {
    return configPromise
  }

  configPromise = (async () => {
    try {
      const response = await fetch("/aws-exports.json")
      if (!response.ok) {
        throw new Error(`Failed to load aws-exports.json: ${response.status}`)
      }
      const config = await response.json()
      configCache = config
      return config
    } catch (error) {
      console.error("Failed to load aws-exports.json:", error)
      throw error
    }
  })()

  return configPromise
}

// Create auth config factory function that loads config dynamically
export async function createCognitoAuthConfig(): Promise<AwsExportsConfig> {
  const awsConfig = await loadAwsConfig()

  if (awsConfig === null) {
    throw Error("aws-exports.json file not found")
  }

  // Get environment variables
  const userPoolId = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID
  const clientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID
  const region = process.env.NEXT_PUBLIC_COGNITO_REGION
  const redirectUri = process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI
  const postLogoutRedirectUri = process.env.NEXT_PUBLIC_COGNITO_POST_LOGOUT_REDIRECT_URI
  const responseType = process.env.NEXT_PUBLIC_COGNITO_RESPONSE_TYPE
  const scope = process.env.NEXT_PUBLIC_COGNITO_SCOPE
  const automaticSilentRenew = process.env.NEXT_PUBLIC_COGNITO_AUTOMATIC_SILENT_RENEW

  // Build authority from environment variables if region and userPoolId are provided
  const envAuthority =
    region && userPoolId ? `https://cognito-idp.${region}.amazonaws.com/${userPoolId}` : undefined

  return {
    authority: envAuthority || awsConfig.authority,
    client_id: clientId || awsConfig.client_id,
    redirect_uri: redirectUri || (typeof window !== "undefined" ? window.location.origin : awsConfig.redirect_uri),
    post_logout_redirect_uri:
      postLogoutRedirectUri || redirectUri || (typeof window !== "undefined" ? window.location.origin : awsConfig.post_logout_redirect_uri),
    response_type: responseType || awsConfig.response_type || "code",
    scope: scope || awsConfig.scope || "email openid profile",
    automaticSilentRenew:
      automaticSilentRenew === "false"
        ? false
        : automaticSilentRenew === "true"
        ? true
        : awsConfig.automaticSilentRenew ?? true,
    userStore:
      typeof window !== "undefined"
        ? new WebStorageStateStore({ store: window.localStorage })
        : undefined,
  }
}

// Synchronous version for backwards compatibility (uses env vars as fallback)
export const cognitoAuthConfig = {
  authority: `https://cognito-idp.${process.env.NEXT_PUBLIC_COGNITO_REGION}.amazonaws.com/${process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID}`,
  client_id: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID,
  redirect_uri: process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI,
  post_logout_redirect_uri: process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI,
  response_type: "code",
  scope: "email openid profile",
  automaticSilentRenew: true,
  userStore:
    typeof window !== "undefined"
      ? new WebStorageStateStore({ store: window.localStorage })
      : undefined,
}
