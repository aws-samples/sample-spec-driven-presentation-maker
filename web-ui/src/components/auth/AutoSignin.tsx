// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { ReactNode, useEffect, useRef, useSyncExternalStore } from "react"
import { useAuth, useAutoSignin } from "react-oidc-context"

/**
 * AutoSigninContent — uses the official useAutoSignin hook from react-oidc-context.
 * Handles hasAuthParams check, redirect loop prevention, and error states internally.
 */
function AutoSigninContent({ children }: { children: ReactNode }) {
  // Save current URL once on mount (before potential OIDC redirect).
  // Using useEffect to avoid re-saving on re-renders after the OIDC callback.
  useEffect(() => {
    if (!window.location.search.includes("code=")) {
      sessionStorage.setItem("post_signin_return_url", window.location.pathname + window.location.hash)
    }
  }, [])

  const { isLoading, isAuthenticated, error } = useAutoSignin({
    signinMethod: "signinRedirect",
  })

  // On auth error, clear stale OIDC state and retry sign-in once
  const auth = useAuth()
  const retried = useRef(false)
  useEffect(() => {
    if (error && !retried.current) {
      retried.current = true
      auth.removeUser().then(() => auth.signinRedirect())
    }
  }, [error, auth])

  if (isLoading) {
    return <div className="flex items-center justify-center min-h-screen text-xl">Signing in...</div>
  }

  if (error) {
    return <div className="flex items-center justify-center min-h-screen text-xl">Signing in...</div>
  }

  if (!isAuthenticated) {
    return <div className="flex items-center justify-center min-h-screen text-xl">Unable to sign in</div>
  }

  return <>{children}</>
}

const subscribe = () => () => {}
const getSnapshot = () => true
const getServerSnapshot = () => false

/**
 * AutoSignin — delays rendering until client-side mount to avoid SSR hydration mismatch.
 */
export function AutoSignin({ children }: { children: ReactNode }) {
  const mounted = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  if (!mounted) {
    return null
  }

  return <AutoSigninContent>{children}</AutoSigninContent>
}
