// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
"use client"

import { ReactNode, useSyncExternalStore } from "react"
import { useAutoSignin } from "react-oidc-context"

/**
 * AutoSigninContent — uses the official useAutoSignin hook from react-oidc-context.
 * Handles hasAuthParams check, redirect loop prevention, and error states internally.
 */
function AutoSigninContent({ children }: { children: ReactNode }) {
  const { isLoading, isAuthenticated, error } = useAutoSignin({
    signinMethod: "signinRedirect",
  })

  if (isLoading) {
    return <div className="flex items-center justify-center min-h-screen text-xl">Signing in...</div>
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen text-xl text-red-400">
        Authentication error: {error.message}
      </div>
    )
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
