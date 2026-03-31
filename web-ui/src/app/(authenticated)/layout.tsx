// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Layout for authenticated routes — wraps children with AuthProvider.
 */

import { AuthProvider } from "@/components/auth/AuthProvider"

export default function AuthenticatedLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return <AuthProvider>{children}</AuthProvider>
}
