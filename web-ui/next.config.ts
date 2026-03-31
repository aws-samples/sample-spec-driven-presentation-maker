// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  distDir: "build",
  output: "export",
  trailingSlash: true,
  typescript: {
    ignoreBuildErrors: true,
  },
}

export default nextConfig
