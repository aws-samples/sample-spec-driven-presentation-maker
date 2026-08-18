// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/** Convert compose tool invocations to observable labels and semantic categories. */

export function stripPrefix(name: string): string {
  return name.replace(/^spec_driven_presentation_maker_/, "")
}

export type ActivityCategory = "build" | "explore" | "produce" | "compute" | "other"

export function activityCategory(tool: string): ActivityCategory {
  const name = stripPrefix(tool)
  switch (name) {
    case "run_python":
    case "grid":
      return "compute"
    case "generate_pptx":
    case "generate_preview":
    case "code_to_slide":
    case "get_preview":
      return "produce"
    case "create_deck":
    case "write_slide":
    case "remove_slide":
    case "reorder_slides":
    case "clone_deck":
    case "clone_slide":
    case "apply_style":
    case "init_presentation":
    case "import_attachment":
    case "run_style_python":
      return "build"
    case "read_reference":
    case "list_references":
    case "search_icons":
    case "search_slides":
    case "get_deck":
    case "web_search":
    case "web_fetch":
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

export type ActivityTranslator = (key: string, values?: Record<string, string | number>) => string

export function activityLabel(tool: string, input?: Record<string, unknown>, t?: ActivityTranslator): string {
  const name = stripPrefix(tool)
  const purpose = input?.purpose
  if (typeof purpose === "string" && purpose.trim()) return purpose.trim()

  const tr = (key: string, en: string, values?: Record<string, string | number>) => (t ? t(`activity.${key}`, values) : en)

  switch (name) {
    case "write_slide": {
      const slug = input?.slide_id
      return typeof slug === "string" && slug
        ? tr("writingSlide", `Writing slide · ${slug}`, { slug })
        : tr("writingSlideBare", "Writing slide")
    }
    case "run_python": {
      const slugs = input?.measure_slides
      return Array.isArray(slugs) && slugs.length
        ? tr("editing", `Editing ${slugs.join(", ")}`, { slugs: slugs.join(", ") })
        : tr("working", "Working")
    }
    case "grid": return tr("planningLayout", "Planning layout")
    case "search_assets":
    case "search_icons": {
      const query = input?.query ?? input?.keyword
      return typeof query === "string" && query
        ? tr("searchingIconsQuery", `Searching icons: "${query}"`, { query })
        : tr("searchingIcons", "Searching icons")
    }
    case "read_reference": return tr("readingReference", "Reading reference")
    case "read_examples": return tr("reviewingExamples", "Reviewing examples")
    case "read_guides": return tr("consultingGuide", "Consulting guide")
    case "read_workflows": return tr("consultingWorkflow", "Consulting workflow")
    case "apply_style": return tr("applyingStyle", "Applying style")
    case "get_preview":
    case "generate_preview": return tr("previewingSlides", "Previewing slides")
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
