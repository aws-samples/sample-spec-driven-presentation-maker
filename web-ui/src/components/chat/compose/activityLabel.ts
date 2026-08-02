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
    case "analyze_template":
      return "explore"
    default:
      return "other"
  }
}

/** Minimal translator shape (subset of next-intl's useTranslations return). */
export type ActivityTranslator = (key: string, values?: Record<string, string | number>) => string

export function activityLabel(tool: string, input?: Record<string, unknown>, t?: ActivityTranslator): string {
  const name = stripPrefix(tool)

  const purpose = input?.purpose
  if (typeof purpose === "string" && purpose.trim()) return purpose.trim()

  // Message keys live under compose.activity.* — fall back to English when no translator.
  const tr = (key: string, en: string, values?: Record<string, string | number>) => (t ? t(`activity.${key}`, values) : en)

  switch (name) {
    case "run_python": {
      const slugs = input?.measure_slides
      return Array.isArray(slugs) && slugs.length
        ? tr("editing", `Editing ${slugs.join(", ")}`, { slugs: slugs.join(", ") })
        : tr("working", "Working")
    }
    case "grid": return tr("planningLayout", "Planning layout")
    case "search_assets": {
      const q = input?.query
      return typeof q === "string" && q
        ? tr("searchingIconsQuery", `Searching icons: "${q}"`, { query: q })
        : tr("searchingIcons", "Searching icons")
    }
    case "read_examples": return tr("reviewingExamples", "Reviewing examples")
    case "read_guides": return tr("consultingGuide", "Consulting guide")
    case "read_workflows": return tr("consultingWorkflow", "Consulting workflow")
    case "apply_style": return tr("applyingStyle", "Applying style")
    case "get_preview": return tr("previewingSlides", "Previewing slides")
    case "generate_pptx": return tr("assemblingDeck", "Assembling deck")
    case "code_to_slide": return tr("formattingCode", "Formatting code")
    case "import_attachment": return tr("importingFile", "Importing file")
    case "analyze_template": return tr("analyzingTemplate", "Analyzing template")
    case "list_styles": return tr("browsingStyles", "Browsing styles")
    case "list_guides": return tr("listingGuides", "Listing guides")
    case "list_workflows": return tr("listingWorkflows", "Listing workflows")
    case "list_templates": return tr("listingTemplates", "Listing templates")
    case "init_presentation": return tr("initializingDeck", "Initializing deck")
    default: return tr("thinking", "Thinking")
  }
}
