// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local ACP Agent Stop — cancel the current session prompt.
 * Local mode only.
 */



export async function POST(req: Request) {
  // The actual cancel is handled by the AbortSignal in the browser's fetch.
  // This endpoint exists for explicit stop requests.
  return new Response(JSON.stringify({ ok: true }), {
    headers: { "Content-Type": "application/json" },
  })
}
