// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * User Resources Service — My Styles and My Templates CRUD.
 */

let apiBaseUrl = ""

async function getApiBaseUrl(): Promise<string> {
  if (apiBaseUrl) return apiBaseUrl
  const response = await fetch("/aws-exports.json")
  const config = await response.json()
  apiBaseUrl = config.apiBaseUrl || ""
  return apiBaseUrl
}

export interface UserStyleEntry {
  name: string
  description: string
  coverHtml?: string
}

export interface UserTemplateEntry {
  id: string
  name: string
  description: string
  updatedAt: string
}

/** List current user's styles. */
export async function listUserStyles(idToken: string): Promise<UserStyleEntry[]> {
  const base = await getApiBaseUrl()
  const res = await fetch(`${base}resources/user/styles`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!res.ok) return []
  const data = await res.json()
  return data.styles || []
}

/** Fetch full HTML for a user style. */
export async function getUserStyle(name: string, idToken: string): Promise<string> {
  const base = await getApiBaseUrl()
  const res = await fetch(`${base}resources/user/styles/${encodeURIComponent(name)}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!res.ok) return ""
  const data = await res.json()
  return data.fullHtml || ""
}

/** Delete a user style. */
export async function deleteUserStyle(name: string, idToken: string): Promise<void> {
  const base = await getApiBaseUrl()
  await fetch(`${base}resources/user/styles/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${idToken}` },
  })
}

/** List current user's templates. */
export async function listUserTemplates(idToken: string): Promise<UserTemplateEntry[]> {
  const base = await getApiBaseUrl()
  const res = await fetch(`${base}resources/user/templates`, {
    headers: { Authorization: `Bearer ${idToken}` },
  })
  if (!res.ok) return []
  const data = await res.json()
  return data.templates || []
}

/**
 * Upload a .pptx and register as a user template.
 * Uses the existing /uploads/presign flow, then calls /resources/user/templates.
 */
export async function uploadUserTemplate(
  file: File,
  name: string,
  description: string,
  idToken: string,
): Promise<UserTemplateEntry> {
  const base = await getApiBaseUrl()

  // 1. presign
  const presignRes = await fetch(`${base}uploads/presign`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      fileName: file.name,
      contentType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      fileSize: file.size,
    }),
  })
  if (!presignRes.ok) throw new Error(`presign failed: ${presignRes.status}`)
  const { uploadId, presignedUrl } = await presignRes.json()

  // 2. PUT to S3
  const putRes = await fetch(presignedUrl, {
    method: "PUT",
    headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.presentationml.presentation" },
    body: file,
  })
  if (!putRes.ok) throw new Error(`S3 upload failed: ${putRes.status}`)

  // 3. Register
  const regRes = await fetch(`${base}resources/user/templates`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ uploadId, name, description }),
  })
  if (!regRes.ok) {
    const err = await regRes.text()
    throw new Error(`template register failed: ${err}`)
  }
  return regRes.json()
}

/** Delete a user template. */
export async function deleteUserTemplate(id: string, idToken: string): Promise<void> {
  const base = await getApiBaseUrl()
  await fetch(`${base}resources/user/templates/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${idToken}` },
  })
}
