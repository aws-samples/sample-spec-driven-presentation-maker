// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Local: the stored kiro-cli sessions the configured agent engine can open (`?all=1`: sdpm's own too). */
import { listSessions } from "@/lib/local/kiro-sessions"

export const dynamic = "force-dynamic"

export async function GET(req: Request) {
  const includeAll = new URL(req.url).searchParams.get("all") === "1"
  return Response.json(await listSessions({ includeAll }))
}
