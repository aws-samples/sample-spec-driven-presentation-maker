// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Root page — restores saved return URL after OIDC redirect, or defaults to /decks.
 */

"use client"

import { useEffect } from "react"

export default function RootPage() {
  useEffect(() => {
    const returnUrl = sessionStorage.getItem("post_signin_return_url")
    sessionStorage.removeItem("post_signin_return_url")
    // Avoid redirecting to "/" (this page) which would cause an infinite loop
    const target = returnUrl && returnUrl !== "/" ? returnUrl : "/decks/"
    window.location.replace(target)
  }, [])

  return null
}
