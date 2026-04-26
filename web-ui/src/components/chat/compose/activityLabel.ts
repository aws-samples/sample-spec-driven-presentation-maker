// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * activityLabel — Convert tool invocation to natural English verb phrase.
 *
 * Priority:
 *   1. input.purpose (agent's own words — highest signal)
 *   2. tool-specific natural phrase
 *   3. "Thinking" fallback
 */

export function stripPrefix(name: string): string {
  return name.replace(/^spec_driven_presentation_maker_/, "")
}

export type ActivityCategory = "build" | "explore" | "produce" | "compute" | "other"

/** Map a tool (without MCP prefix) to its category for color coding. */
export function activityCategory(tool: string): ActivityCategory {
  const name = stripPrefix(tool)
  switch (name) {
    case "run_python":
    case "grid":
      return "compute"
    case "generate_pptx":
    case "code_to_slide":
    case "get_preview":
    case "import_attachment":
      return "produce"
    case "apply_style":
    case "init_presentation":
      return "build"
    case "search_assets":
    case "read_examples":
    case "read_guides":
    case "read_workflows":
    case "list_styles":
    case "list_guides":
    case "list_workflows":
    case "list_templates":
    case "list_asset_sources":
    case "read_uploaded_file":
    case "analyze_template":
      return "explore"
    default:
      return "other"
  }
}

export function activityLabel(tool: string, input?: Record<string, unknown>): string {
  const name = stripPrefix(tool)

  const purpose = input?.purpose
  if (typeof purpose === "string" && purpose.trim()) return purpose.trim()

  switch (name) {
    case "run_python": {
      const slugs = input?.measure_slides
      return Array.isArray(slugs) && slugs.length ? `Editing ${slugs.join(", ")}` : "Working"
    }
    case "grid": return "Planning layout"
    case "search_assets": {
      const q = input?.query
      return typeof q === "string" && q ? `Searching icons: "${q}"` : "Searching icons"
    }
    case "read_examples": return "Reviewing examples"
    case "read_guides": return "Consulting guide"
    case "read_workflows": return "Consulting workflow"
    case "apply_style": return "Applying style"
    case "get_preview": return "Previewing slides"
    case "generate_pptx": return "Assembling deck"
    case "code_to_slide": return "Formatting code"
    case "import_attachment": return "Importing file"
    case "analyze_template": return "Analyzing template"
    case "list_styles": return "Browsing styles"
    case "list_guides": return "Listing guides"
    case "list_workflows": return "Listing workflows"
    case "list_templates": return "Listing templates"
    case "list_asset_sources": return "Listing asset sources"
    case "read_uploaded_file": return "Reading upload"
    case "init_presentation": return "Initializing deck"
    default: return "Thinking"
  }
}
