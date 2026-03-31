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

const AuthProvider = ({ children }: PropsWithChildren) => {
  const [authConfig, setAuthConfig] = useState<CognitoAuthConfig | null>(null)
  const [loading, setLoading] = useState(true)
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
        Failed to load authentication configuration
      </div>
    )
  }

  return (
    <OidcAuthProvider
      {...authConfig}
      // This callback removes the `?code=` from the URL, which will break page refreshes
      onSigninCallback={() => {
        // Restore the URL the user was on before OIDC redirect (saved by AutoSignin)
        const returnUrl = sessionStorage.getItem("post_signin_return_url") || ""
        sessionStorage.removeItem("post_signin_return_url")
        window.history.replaceState({}, document.title, returnUrl || window.location.pathname)
      }}
    >
      <AutoSignin>{children}</AutoSignin>
    </OidcAuthProvider>
  )
}

export { AuthProvider }
