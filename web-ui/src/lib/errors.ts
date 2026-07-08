// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { toast } from "sonner"

/**
 * Surface a failed operation to the user and the console.
 *
 * Use this instead of swallowing errors with `.catch(() => {})` — silent
 * failures leave users guessing why nothing happened. Truly best-effort
 * calls may still ignore errors, but must carry an
 * `// intentional: best-effort` comment at the call site.
 *
 * @param message - User-facing description of what failed
 * @param err - Original error, logged to the console for debugging
 * @param opts.retry - When provided, the toast shows a Retry action
 */
export function notifyError(message: string, err?: unknown, opts?: { retry?: () => void }) {
  console.error(message, err)
  toast.error(message, opts?.retry ? { action: { label: "Retry", onClick: opts.retry } } : undefined)
}
