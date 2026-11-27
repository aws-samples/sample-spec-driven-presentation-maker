// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** The guide name rule, as sdpm.knowledge.reference.is_guide_name states it. */

/**
 * Whether `name` names one guide: a single path component with no `.` anywhere.
 *
 * Stricter than a style name, which admits `acme.v2`, and looser than the local style
 * route's `[a-zA-Z0-9_-]+`, which would refuse `社内標準`. A guide name is also the key a
 * caller passes back from a listing, so it carries no separator and no dot.
 */
export function isGuideName(name: unknown): name is string {
  return (
    typeof name === "string" &&
    name.length > 0 &&
    !name.includes(".") &&
    !name.includes("/") &&
    !name.includes("\\") &&
    !name.includes("\0")
  )
}
