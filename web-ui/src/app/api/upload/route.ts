// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Local File Upload API — receives a file from the browser and converts it
 * via mcp-local/upload_tools.upload_file (Python subprocess).
 * Local mode only.
 */

import { spawn } from "child_process"
import fs from "fs"
import os from "os"
import path from "path"
import { getSessionId, ensureAgent } from "@/lib/local/acp-process"

const MCP_LOCAL_DIR = path.resolve(process.cwd(), "..", "mcp-local")

export async function POST(req: Request): Promise<Response> {
  await ensureAgent()
  const sessionId = getSessionId()
  if (!sessionId) {
    return Response.json({ error: "No active session" }, { status: 400 })
  }

  const form = await req.formData()
  const file = form.get("file")
  if (!(file instanceof File)) {
    return Response.json({ error: "file field missing" }, { status: 400 })
  }

  // Write to temp file
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "sdpm-upload-"))
  const tmpPath = path.join(tmpDir, file.name)
  try {
    const buf = Buffer.from(await file.arrayBuffer())
    fs.writeFileSync(tmpPath, buf)

    const result = await runUploadFile(sessionId, tmpPath, file.name)
    return Response.json(result)
  } catch (e) {
    return Response.json({ error: (e as Error).message }, { status: 500 })
  } finally {
    try { fs.rmSync(tmpDir, { recursive: true, force: true }) } catch {}
  }
}

function runUploadFile(sessionId: string, filePath: string, fileName: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const code = [
      "import sys, json",
      "sys.path.insert(0, '.')",
      "sys.path.insert(0, '..')",
      "sys.path.insert(0, '../skill')",
      "from upload_tools import upload_file",
      `print(upload_file(${JSON.stringify(sessionId)}, ${JSON.stringify(filePath)}, ${JSON.stringify(fileName)}))`,
    ].join("\n")
    const proc = spawn("uv", ["run", "--directory", MCP_LOCAL_DIR, "python", "-c", code], {
      cwd: MCP_LOCAL_DIR,
      stdio: ["ignore", "pipe", "pipe"],
    })
    let stdout = ""
    let stderr = ""
    proc.stdout.on("data", (d: Buffer) => { stdout += d.toString() })
    proc.stderr.on("data", (d: Buffer) => { stderr += d.toString() })
    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `upload_file exited with code ${code}`))
        return
      }
      try {
        resolve(JSON.parse(stdout.trim().split("\n").pop() || "{}"))
      } catch (e) {
        reject(new Error(`Failed to parse upload_file output: ${(e as Error).message}\n${stdout}`))
      }
    })
  })
}
