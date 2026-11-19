// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { NextConfig } from "next"

const isLocal = process.env.NEXT_PUBLIC_MODE === "local"

const nextConfig: NextConfig = {
  distDir: "build",
  // The dev-only "N" badge sits in a corner, and every corner holds a control (rail, send button).
  // Build and runtime errors still open the dev overlay.
  devIndicators: false,
  ...(isLocal ? {} : { output: "export" as const, trailingSlash: true }),
}

export default nextConfig
