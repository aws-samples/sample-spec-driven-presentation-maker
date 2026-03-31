// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Root page — restores saved return URL after OIDC redirect, or defaults to /decks.
 */

"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

export default function RootPage() {
  const router = useRouter()

  useEffect(() => {
    const returnUrl = sessionStorage.getItem("post_signin_return_url")
    console.log("[RootPage] returnUrl from sessionStorage:", returnUrl)
    if (returnUrl) {
      sessionStorage.removeItem("post_signin_return_url")
      router.replace(returnUrl)
    } else {
      router.replace("/decks")
    }
  }, [router])

  return null
}
