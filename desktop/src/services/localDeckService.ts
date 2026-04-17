/**
 * Local Deck Service — filesystem-based deck operations.
 *
 * Same interface as web-ui/src/services/deckService.ts so components work unchanged.
 * Storage: ~/Documents/SDPM-Presentations/{deckId}/
 */

import { readDir, readTextFile, writeTextFile, exists, mkdir, remove } from "@tauri-apps/plugin-fs";
import { homeDir, join } from "@tauri-apps/api/path";
import { convertFileSrc } from "@tauri-apps/api/core";

import type { DeckSummary, DeckDetail, SlidePreview, SpecFiles, ChatMessage, StyleEntry } from "@/services/deckService";

const BASE_DIR_NAME = "Documents/SDPM-Presentations";

// Stable references to avoid React re-render loops
const _emptyArray: string[] = [];
const _emptyObject: Record<string, string> = {};

async function basePath(): Promise<string> {
  const home = await homeDir();
  return await join(home, BASE_DIR_NAME);
}

async function deckPath(deckId: string): Promise<string> {
  return await join(await basePath(), deckId);
}

async function ensureDir(path: string): Promise<void> {
  if (!(await exists(path))) {
    await mkdir(path, { recursive: true });
  }
}

/** Index file tracking all decks and favorites. */
interface DeckIndex {
  decks: { deckId: string; name: string; updatedAt: string }[];
  favoriteIds: string[];
}

async function readIndex(): Promise<DeckIndex> {
  const indexPath = await join(await basePath(), "decks.json");
  try {
    const text = await readTextFile(indexPath);
    return JSON.parse(text);
  } catch {
    return { decks: [], favoriteIds: [] };
  }
}

async function writeIndex(index: DeckIndex): Promise<void> {
  const base = await basePath();
  await ensureDir(base);
  const indexPath = await join(base, "decks.json");
  await writeTextFile(indexPath, JSON.stringify(index, null, 2));
}

export async function listDecks(_idToken?: string): Promise<{ decks: DeckSummary[]; favoriteIds: string[] }> {
  const base = await basePath();
  await ensureDir(base);
  const summaries: DeckSummary[] = [];

  // Read favorites from index if exists
  const index = await readIndex();

  // Scan directories directly (each subdirectory is a deck)
  try {
    const entries = await readDir(base);
    for (const entry of entries) {
      if (!entry.isDirectory || !entry.name) continue;
      const deckId = entry.name;
      const dp = await join(base, deckId);
      let slideCount = 0;
      let name = deckId;

      // Read deck name from presentation.json or deck.json
      for (const fname of ["deck.json", "presentation.json"]) {
        const p = await join(dp, fname);
        if (await exists(p)) {
          try {
            const json = JSON.parse(await readTextFile(p));
            name = json.name || deckId;
          } catch {}
          break;
        }
      }

      // Count slides
      const slidesDir = await join(dp, "slides");
      if (await exists(slidesDir)) {
        const files = await readDir(slidesDir);
        slideCount = files.filter((f) => f.name?.endsWith(".json")).length;
      }

      summaries.push({
        deckId,
        name,
        slideCount,
        updatedAt: new Date().toISOString(),
        thumbnailUrl: null,
      });
    }
  } catch {}

  // Sort by name (newest first since names start with date)
  summaries.sort((a, b) => b.deckId.localeCompare(a.deckId));

  return { decks: summaries, favoriteIds: index.favoriteIds };
}

export async function getDeck(deckId: string, _idToken?: string): Promise<DeckDetail> {
  const dp = await deckPath(deckId);
  // Support both deck.json (web) and presentation.json (mcp-local)
  let deckJson: Record<string, unknown> = {};
  for (const fname of ["deck.json", "presentation.json"]) {
    const p = await join(dp, fname);
    if (await exists(p)) {
      deckJson = JSON.parse(await readTextFile(p));
      break;
    }
  }

  const slides: SlidePreview[] = [];
  const slidesDir = await join(dp, "slides");
  const slideOrder: string[] = deckJson.slideOrder || [];

  // Index compose files by slug → latest epoch
  const composeBySlug = new Map<string, string>(); // slug → filename
  let defsFilename: string | null = null;
  const composeDir = await join(dp, "compose");
  if (await exists(composeDir)) {
    const composeFiles = await readDir(composeDir);
    const epochOf = (name: string): number => {
      const m = name.match(/_(\d+)\.json$/);
      return m ? parseInt(m[1], 10) : 0;
    };
    let defsEpoch = -1;
    for (const f of composeFiles) {
      const n = f.name;
      if (!n?.endsWith(".json")) continue;
      if (n.startsWith("defs_")) {
        const e = epochOf(n);
        if (e > defsEpoch) { defsEpoch = e; defsFilename = n; }
        continue;
      }
      // Parse "{slug}_{epoch}.json"
      const m = n.match(/^(.+)_(\d+)\.json$/);
      if (!m) continue;
      const [, slug, epochStr] = m;
      const e = parseInt(epochStr, 10);
      const cur = composeBySlug.get(slug);
      if (!cur || epochOf(cur) < e) composeBySlug.set(slug, n);
    }
  }

  // Parse outline.md for slide order (matches skill/sdpm.api.parse_outline_slugs)
  const parseOutlineSlugs = async (): Promise<string[]> => {
    const specsDir = await join(dp, "specs");
    const outlineText = await safeRead(await join(specsDir, "outline.md"));
    if (!outlineText) return [];
    const re = /^-\s*\[([a-z0-9-]+)\]\s*/;
    return outlineText.split("\n").map((l) => re.exec(l)?.[1]).filter((s): s is string => !!s);
  };
  const outlineSlugs = await parseOutlineSlugs();

  // Index preview PNG files by page number (page01-*.png → 1)
  const previewByPage = new Map<number, string>(); // page num (1-based) → filename
  const previewDir = await join(dp, "preview");
  if (await exists(previewDir)) {
    const previewFiles = await readDir(previewDir);
    for (const f of previewFiles) {
      if (!f.name?.endsWith(".png")) continue;
      const m = f.name.match(/^page(\d+)[-.]/);
      if (m) previewByPage.set(parseInt(m[1], 10), f.name);
    }
  }

  if (await exists(slidesDir)) {
    // Iterate in outline order; fall back to readdir order if outline missing
    let slugList = outlineSlugs;
    if (slugList.length === 0) {
      const files = await readDir(slidesDir);
      slugList = files.filter((f) => f.name?.endsWith(".json")).map((f) => f.name!.replace(".json", ""));
    }
    // PPTX page number advances only for slugs that have a slides/*.json file
    // (the builder skips missing slides). Keep a separate counter.
    let pageNum = 0;
    for (let i = 0; i < slugList.length; i++) {
      const slug = slugList[i];
      const slideJsonPath = await join(slidesDir, `${slug}.json`);
      if (!(await exists(slideJsonPath))) continue;
      pageNum++;
      const previewFile = previewByPage.get(pageNum);
      const previewPath = previewFile ? await join(dp, "preview", previewFile) : null;
      const composeFile = composeBySlug.get(slug);
      const composePath = composeFile ? await join(dp, "compose", composeFile) : null;
      slides.push({
        slideId: slug,
        previewUrl: previewPath ? convertFileSrc(previewPath) : null,
        composeUrl: composePath ? convertFileSrc(composePath) : null,
        updatedAt: new Date().toISOString(),
      });
    }
  }

  // Read specs
  let specs: SpecFiles | null = null;
  try {
    const specsDir = await join(dp, "specs");
    const brief = await safeRead(await join(specsDir, "brief.md"));
    const outline = await safeRead(await join(specsDir, "outline.md"));
    const artDirection = await safeRead(await join(specsDir, "art-direction.html"))
      || await safeRead(await join(specsDir, "art-direction.md"));
    if (brief || outline || artDirection) {
      specs = { brief, outline, artDirection };
    }
  } catch { /* ignore */ }

  const pptxPath = await join(dp, "output.pptx");
  const defsPath = defsFilename ? await join(dp, "compose", defsFilename) : null;

  return {
    deckId,
    name: deckJson.name || deckId,
    slideOrder,
    slides,
    defsUrl: defsPath ? convertFileSrc(defsPath) : null,
    pptxUrl: (await exists(pptxPath)) ? convertFileSrc(pptxPath) : null,
    specs,
    updatedAt: new Date().toISOString(),
    chatSessionId: deckJson.chatSessionId,
    visibility: "private" as const,
    isOwner: true,
    collaborators: _emptyArray,
    collaboratorAliases: _emptyObject,
  };
}

export async function patchDeck(deckId: string, updates: Record<string, string>, _idToken?: string): Promise<void> {
  const dp = await deckPath(deckId);
  for (const fname of ["deck.json", "presentation.json"]) {
    const p = await join(dp, fname);
    if (await exists(p)) {
      const deckJson = JSON.parse(await readTextFile(p));
      Object.assign(deckJson, updates);
      await writeTextFile(p, JSON.stringify(deckJson, null, 2));
      return;
    }
  }
}

export async function deleteDeck(deckId: string, _idToken?: string): Promise<void> {
  const dp = await deckPath(deckId);
  await remove(dp, { recursive: true });
  const index = await readIndex();
  index.decks = index.decks.filter((d) => d.deckId !== deckId);
  index.favoriteIds = index.favoriteIds.filter((id) => id !== deckId);
  await writeIndex(index);
}

export async function toggleFavorite(deckId: string, action: "add" | "remove", _idToken?: string): Promise<boolean> {
  const index = await readIndex();
  if (action === "add" && !index.favoriteIds.includes(deckId)) {
    index.favoriteIds.push(deckId);
  } else if (action === "remove") {
    index.favoriteIds = index.favoriteIds.filter((id) => id !== deckId);
  }
  await writeIndex(index);
  return action === "add";
}

export async function getChatHistory(sessionId: string, _idToken?: string): Promise<ChatMessage[]> {
  // Chat history is managed by kiro-cli ACP sessions (~/.kiro/sessions/cli/)
  // For now, return empty — kiro-cli persists its own history
  return [];
}

export async function fetchStyles(_idToken?: string): Promise<StyleEntry[]> {
  // Read style HTML files from skill/references/examples/styles/
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const projectRoot = await invoke<string>("get_project_root");
    const stylesDir = await join(projectRoot, "skill", "references", "examples", "styles");
    if (!(await exists(stylesDir))) return [];
    const files = await readDir(stylesDir);
    const styles: StyleEntry[] = [];
    for (const f of files) {
      if (!f.name?.endsWith(".html")) continue;
      const name = f.name.replace(".html", "");
      const htmlPath = await join(stylesDir, f.name);
      const coverHtml = await readTextFile(htmlPath);
      styles.push({ name, description: name, coverHtml });
    }
    return styles;
  } catch {
    return [];
  }
}

async function safeRead(path: string): Promise<string | null> {
  try {
    if (await exists(path)) return await readTextFile(path);
  } catch { /* ignore */ }
  return null;
}

// Stubs for Web-only features (no-op in local mode)
export async function getDeckWithJson(deckId: string, idToken?: string) { return getDeck(deckId, idToken); }
export async function searchSlides() { return []; }
export async function updateVisibility() {}
export async function listPublicDecks() { return []; }
export async function shareDeck() { return { collaborators: [], collaboratorAliases: {} }; }
export async function listSharedDecks() { return []; }
export async function searchUsers() { return []; }
export async function listFavorites(_idToken?: string) { return []; }
export async function batchGetSlidePreviewUrls() { return new Map(); }
export async function fetchStyleHtml(name: string, _idToken?: string): Promise<string> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const projectRoot = await invoke<string>("get_project_root");
    const htmlPath = await join(projectRoot, "skill", "references", "examples", "styles", `${name}.html`);
    if (await exists(htmlPath)) return await readTextFile(htmlPath);
  } catch {}
  return "";
}
