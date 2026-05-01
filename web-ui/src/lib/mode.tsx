// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Runtime mode detection and conditional rendering helpers.
 *
 * - CloudOnly: renders children only in cloud (default) mode
 * - LocalOnly: renders children only in local mode
 * - IS_LOCAL: boolean flag for handler-level branching (use sparingly)
 */
import type { PropsWithChildren } from "react"

export const IS_LOCAL = process.env.NEXT_PUBLIC_MODE === "local"

export function CloudOnly({ children }: PropsWithChildren) {
  return IS_LOCAL ? null : <>{children}</>
}

export function LocalOnly({ children }: PropsWithChildren) {
  return IS_LOCAL ? <>{children}</> : null
}
