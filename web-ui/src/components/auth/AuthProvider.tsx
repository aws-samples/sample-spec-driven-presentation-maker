// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { createCognitoAuthConfig } from "@/lib/auth"
import { useEffect, useState, useRef, PropsWithChildren } from "react"
import { AuthProvider as OidcAuthProvider } from "react-oidc-context"
import { WebStorageStateStore } from "oidc-client-ts"
import { AutoSignin } from "./AutoSignin"

interface CognitoAuthConfig {
  authority: string
  client_id: string | undefined
  redirect_uri: string | undefined
  post_logout_redirect_uri: string | undefined
  response_type: string
  scope: string
  automaticSilentRenew: boolean
  userStore?: WebStorageStateStore
}

const IS_LOCAL = process.env.NEXT_PUBLIC_MODE === 'local'

const AuthProvider = ({ children }: PropsWithChildren) => {
  // Local mode: skip Cognito entirely
  if (IS_LOCAL) return <>{children}</>

  return <CloudAuthProvider>{children}</CloudAuthProvider>
}

const CloudAuthProvider = ({ children }: PropsWithChildren) => {
  const [authConfig, setAuthConfig] = useState<CognitoAuthConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const initRef = useRef(false)

  useEffect(() => {
    // Guard against double-mount (React StrictMode or re-render)
    if (initRef.current) return
    initRef.current = true

    async function loadConfig() {
      try {
        const config = await createCognitoAuthConfig()
        setAuthConfig(config)
      } catch (error) {
        console.error("Failed to load auth configuration:", error)
        const msg = error instanceof Error ? error.message : String(error)
        if (msg.includes("403")) {
          setError("Access denied. Your network may not be permitted to access this application. Please contact your administrator.")
        } else {
          setError(msg)
        }
      } finally {
        setLoading(false)
      }
    }

    loadConfig()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-xl">
        Loading authentication configuration...
      </div>
    )
  }

  if (!authConfig) {
    return (
      <div className="flex items-center justify-center min-h-screen text-xl">
        <div className="text-center max-w-lg">
          <p className="font-semibold">Failed to load authentication configuration</p>
          {error && <p className="mt-2 text-sm text-gray-500">{error}</p>}
        </div>
      </div>
    )
  }

  return (
    <OidcAuthProvider
      {...authConfig}
      // This callback removes the `?code=` from the URL, which will break page refreshes
      onSigninCallback={() => {
        window.history.replaceState({}, document.title, window.location.pathname)
      }}
    >
      <AutoSignin>{children}</AutoSignin>
    </OidcAuthProvider>
  )
}

export { AuthProvider }
