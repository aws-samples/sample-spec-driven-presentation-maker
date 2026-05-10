// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { useAuth as useOidcAuth } from "react-oidc-context"
import { useEffect, useState } from "react"
import { WebStorageStateStore } from "oidc-client-ts"
import { createCognitoAuthConfig } from "@/lib/auth"

const IS_LOCAL = process.env.NEXT_PUBLIC_MODE === "local"

interface CognitoAuthConfig {
  authority?: string
  client_id?: string
  redirect_uri?: string
  post_logout_redirect_uri?: string
  response_type?: string
  scope?: string
  automaticSilentRenew?: boolean
  userStore?: WebStorageStateStore
}

const LOCAL_AUTH = {
  isAuthenticated: true,
  user: { id_token: "local", access_token: "local", profile: { sub: "local-user" } },
  signIn: () => {},
  signOut: () => {},
  isLoading: false,
  error: null,
  token: "local",
}

/**
 * Wrapper that always calls useOidcAuth (satisfying rules-of-hooks)
 * but catches throws when OidcAuthProvider is absent (local mode).
 */
function useSafeOidcAuth(): ReturnType<typeof useOidcAuth> | undefined {
  try {
    return useOidcAuth()
  } catch {
    return undefined
  }
}

export function useAuth() {
  // useOidcAuth() must be called unconditionally (React rules of hooks).
  // In local mode OidcAuthProvider is absent; the hook may throw, so we
  // wrap it in a helper that catches and returns undefined.
  const oidcAuth = useSafeOidcAuth()

  const [authConfig, setAuthConfig] = useState<CognitoAuthConfig | null>(null)

  useEffect(() => {
    if (IS_LOCAL) return
    createCognitoAuthConfig()
      .then(setAuthConfig)
      .catch(e => console.error("Failed to load auth configuration for signOut:", e))
  }, [])

  // Local mode: always return mock auth
  if (IS_LOCAL || !oidcAuth) {
    return LOCAL_AUTH
  }

  return {
    isAuthenticated: oidcAuth.isAuthenticated,
    user: oidcAuth.user,
    signIn: oidcAuth.signinRedirect,
    signOut: () => {
      const clientId = authConfig?.client_id || process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID || ""
      const logoutUri =
        authConfig?.redirect_uri ||
        process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI ||
        "http://localhost:3000"

      oidcAuth!.signoutRedirect({
        extraQueryParams: {
          client_id: clientId,
          logout_uri: logoutUri,
        },
      })
    },
    isLoading: oidcAuth.isLoading,
    error: oidcAuth.error,
    token: oidcAuth.user?.id_token,
  }
}
