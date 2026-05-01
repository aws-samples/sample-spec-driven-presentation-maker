// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { NextConfig } from "next"

const isLocal = process.env.NEXT_PUBLIC_MODE === "local"

const nextConfig: NextConfig = {
  distDir: "build",
  ...(isLocal ? {} : { output: "export" as const, trailingSlash: true }),
  typescript: {
    ignoreBuildErrors: true,
  },
  bundler: "webpack",
}

export default nextConfig
