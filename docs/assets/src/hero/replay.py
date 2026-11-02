# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Record the README key visual: replay a deck's compose history in the Local Web UI.

The Local server writes compose/<slug>_<epoch>.json after every build of a slide, and the
Web UI animates the components marked `changed` when a slide's newest compose file changes.
This script stages that history again in a scratch deck folder, runs the Local Web UI on it
(`npm run dev:local`, bound to 127.0.0.1), places the files one step at a time and records
the browser with Playwright (record.cjs). Nothing in the product is changed or mocked; the
only difference from a live run is that the files come from the committed history instead
of a composer.

The GIF has two parts (ACTIONS below), the same for every language:

1. The cover, large (1000x728 viewport, Slides view): the layout pass draws the frame of
   every slide (only the cover is in view), then the composer's final cover is placed and
   the agents fill it. Played FIRST_SPEED times faster.
2. Real time: the viewport grows to LIST_VIEWPORT, which shows two slides of the list at
   once, centred in the GIF. The list scrolls to slides 2-3 and their final payloads land
   together (the Web UI animates at most two slides at a time), then to slides 4-5, whose
   payloads land with those of slides 6-7 (out of view, drawn finished). Each pair is shown
   for SHOW_MS, the rest of its animation is cut; a 1 px wheel tick keeps the list from
   following the updates to slide 7. The grid view then shows all seven slides (it shows the
   preview PNGs) and holds.

Payloads: "first" / "last" are the oldest / newest file of a slug's history, the first one
being the layout pass. deck-ja was translated from deck-en and has no layout pass: its cover
uses deck-en's (no translatable text in it) and for the other slides one is made the same
way the orchestrator makes one: each slide reduced to its regions plus the elements that
deck-en's layout pass drew (top bar, label, title), written through the Local server's
run_python in a scratch copy, which renders the compose payloads. The `changed` flag of each
placed payload is recomputed against the one placed before it for the same slug
(sdpm.engine.preview.compose.mark_changed, the server's rule), because the replay skips the
intermediate builds. preview/<slug>.png (what the grid view shows) is rendered from the deck
like the server does: PDF, then pdftoppm at 1280 px.

record.cjs cuts the idle time between placing a file and the animation starting; the GIF
opens OPEN_AT_S into the first animation. ffmpeg turns the frames (padded to one size)
into a GIF (palettegen / paletteuse), gifsicle optimises it.

The stills are the deck itself: generate_pptx, LibreOffice to PDF, pdftoppm at 1920 px, then
the cover large on top and the other slides in rows of three below it.

Usage (from the repository root; needs web-ui/node_modules, Google Chrome, ffmpeg, gifsicle,
LibreOffice and poppler):
    uv run python docs/assets/src/hero/replay.py               # en and ja, GIFs and stills
    uv run python docs/assets/src/hero/replay.py ja --no-stills
    uv run python docs/assets/src/hero/replay.py --keep /tmp/hero-replay   # keep frames
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess  # nosec B404
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
WEBUI = REPO / "web-ui"
ASSETS = REPO / "docs" / "assets"

sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(REPO / "sdpm"))

from render import BUILDER, WIDTH, run  # noqa: E402

from sdpm.engine.preview.compose import mark_changed  # noqa: E402

# Part 1 viewport: the full-view slide is width-bound (952 x 536 px) and ends 12 px above
# the bottom edge, so the whole cover is in view and the next slide is not.
VIEWPORT = (1000, 728)
# Part 2 viewport: two full-view slides one above the other, and the grid view of all seven
# slides (two columns, four rows). Recorded into the same frame
# size, so it is shown at 53 % and centred.
LIST_VIEWPORT = (1000, 1380)
ZOOM_STEPS = 12
# Captured at 2x and scaled to GIF_WIDTH (README width is ~880 px), so it stays sharp on
# high-density screens.
SCALE = 2
GIF_WIDTH = 1200
FPS = 20
FIRST_SPEED = 2.2
# Each pair of slides is shown for this long, from the moment its animation starts.
SHOW_MS = 2200
# Cut from the end of each cover animation: the overlays fade out, nothing else moves.
TAIL_CUT_MS = 600
GRID_HOLD_MS = 2400
HOLD_START_MS = 1000
# Of each idle stretch (file placed -> animation on screen) keep this much on each side.
KEEP_BEFORE_S, KEEP_AFTER_S = 0.25, 0.15
# Recording time into the first animation at which the GIF opens: the cover's first layout
# region is drawn; the frames before it are a near-empty slide.
OPEN_AT_S = 0.9
# Around the narrower part-2 frames.
PAD_COLOUR, PAD_EDGE = "#050507", "#24262D"

STORIES = {
    "en": {
        "deck": "deck-en",
        "locale": "en-US",
        "ui_locale": "en",
        "grid_button": "Grid view",
        "name": "Spec-Driven Presentation Maker",
        "gif": "hero-en.gif",
        "still": "hero-slides-en.png",
        "layout": {"*": "first"},
    },
    "ja": {
        "deck": "deck-ja",
        "locale": "ja-JP",
        "ui_locale": "ja",
        "grid_button": "グリッド表示",
        "name": "Spec-Driven Presentation Maker",
        "gif": "hero-ja.gif",
        "still": "hero-slides-ja.png",
        "layout": {"cover": "deck-en:first", "*": "made"},
    },
}

# Pairs of slides animated in view in part 2, and the slides finished out of view.
PAIRS = [["blank-slide", "spec-first"], ["parallel-build", "two-outputs"]]
OUT_OF_VIEW = ["fix-by-drawing", "get-started"]


def outline_slugs(deck: Path) -> list[str]:
    slugs = []
    for line in (deck / "specs" / "outline.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("- [") and "]" in line:
            slugs.append(line[3 : line.index("]")])
    return slugs


def history(deck: Path, slug: str) -> list[Path]:
    """The slug's compose files, oldest first."""
    files = [p for p in (deck / "compose").glob(f"{slug}_*.json") if p.stem[len(slug) + 1 :].isdigit()]
    return sorted(files, key=lambda p: int(p.stem.rsplit("_", 1)[1]))


def latest_defs(deck: Path) -> Path:
    return max((deck / "compose").glob("defs_*.json"), key=lambda p: int(p.stem.split("_")[1]))


def pick(deck: Path, slug: str, how: str) -> Path:
    src, _, which = how.rpartition(":")
    files = history(HERE / src if src else deck, slug)
    if not files:
        raise SystemExit(f"{deck.name}: no compose history for {slug}")
    return files[0] if which == "first" else files[-1]


def is_region(element: dict) -> bool:
    return str(element.get("_comment", "")).startswith("region:")


def make_layout_pass(src: Path, slugs: list[str], work: Path) -> Path:
    """Render a layout pass of `slugs` through the Local server; return the scratch deck."""
    sys.path.insert(0, str(REPO / "servers" / "local"))
    from sandbox_tools import run_python

    deck = work / "layout-pass"
    shutil.rmtree(deck, ignore_errors=True)
    shutil.copytree(
        src, deck, ignore=shutil.ignore_patterns("compose", "translate", "preview", "_work", "*.pptx", "README.md")
    )
    layout = {}
    for slug in slugs:
        slide = json.loads((deck / "slides" / f"{slug}.json").read_text(encoding="utf-8"))
        drawn = len(json.loads(pick(src, slug, "deck-en:first").read_text(encoding="utf-8"))["components"])
        regions = [e for e in slide["elements"] if is_region(e)]
        others = [e for e in slide["elements"] if not is_region(e)]
        layout[slug] = {**slide, "elements": regions + others[:drawn]}
    code = f"slides = {layout!r}\nfor slug, slide in slides.items():\n    write_json(f'slides/{{slug}}.json', slide)\n"
    res = json.loads(run_python("Layout pass: frames and titles of every slide", code, str(deck)))
    if res.get("compose") != f"{len(slugs)} slides composed":
        raise SystemExit(f"layout pass failed: {json.dumps(res, ensure_ascii=False)[:2000]}")
    return deck


def render_pages(src: Path, width: int, tmp: Path) -> list[Path]:
    """The deck's slides as PNGs `width` px wide, in order."""
    from sdpm.engine.preview import export_pdf

    deck = tmp / "deck"
    shutil.copytree(src, deck, ignore=shutil.ignore_patterns("compose", "translate", "preview", "_work", "README.md"))
    pptx = tmp / "out.pptx"
    run([sys.executable, str(BUILDER), "generate_pptx", str(deck), "-o", str(pptx)])
    pdf = tmp / "out.pdf"
    if not export_pdf(pptx, pdf, work_dir=tmp):
        raise SystemExit("PDF export failed: LibreOffice (soffice) is required")
    run(["pdftoppm", "-png", "-scale-to", str(width), str(pdf), str(tmp / "p")])
    return sorted(tmp.glob("p-*.png"))


def build_plan(lang: str, story: dict, work: Path, port: int) -> dict:
    """Stage the scratch deck and the recomputed payloads; return the recorder's plan."""
    src = HERE / story["deck"]
    deck_id = "spec-driven-presentation-maker"
    root = work / "decks"
    deck = root / deck_id
    stage = work / "stage"
    for d in (root, stage):
        shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(src / "specs", deck / "specs")
    meta = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    meta["name"] = story["name"]
    (deck / "deck.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    stage.mkdir(parents=True)

    slugs = outline_slugs(src)
    made = None
    if "made" in story["layout"].values():
        made = make_layout_pass(src, [s for s in slugs if story["layout"].get(s, story["layout"]["*"]) == "made"], work)
    with tempfile.TemporaryDirectory(prefix=f"sdpm-hero-{lang}-preview-") as tmp:
        for slug, png in zip(slugs, render_pages(src, 1280, Path(tmp)), strict=True):
            shutil.copy(png, stage / f"{slug}.png")

    epoch = int(time.time())
    previous: dict[str, list[dict]] = {}

    def payload(slug: str, how: str, n: int) -> list[str]:
        path = history(made, slug)[-1] if how == "made" else pick(src, slug, how)
        data = json.loads(path.read_text(encoding="utf-8"))
        mark_changed(data["components"], previous.get(slug))
        previous[slug] = data["components"]
        out = stage / f"{slug}_{epoch + n}.json"
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        changed = sum(c["changed"] for c in data["components"])
        print(f"  {lang} {n}: {slug} <- {how} ({changed}/{len(data['components'])} changed)")
        return [str(out), str(deck / "compose" / out.name)]

    # Slides appear together with their layout pass and their previews.
    first = [[str(p), str(deck / "slides" / p.name)] for p in sorted((src / "slides").glob("*.json"))]
    first.append([str(latest_defs(src)), str(deck / "compose" / f"defs_{epoch}.json")])
    first += [[str(stage / f"{s}.png"), str(deck / "preview" / f"{s}.png")] for s in slugs]
    first += [payload(s, story["layout"].get(s, story["layout"]["*"]), 0) for s in slugs]
    zoom = [
        [VIEWPORT[0], round(VIEWPORT[1] + (LIST_VIEWPORT[1] - VIEWPORT[1]) * (i + 1) / ZOOM_STEPS)]
        for i in range(ZOOM_STEPS)
    ]
    actions = [
        {"speed": FIRST_SPEED},
        {"place": first, "tail_cut_ms": TAIL_CUT_MS},
        {"place": [payload("cover", "last", 1)], "tail_cut_ms": TAIL_CUT_MS},
        {"speed": 1},
        {"resize": zoom, "step_ms": 40},
        {"sleep": 150},
        {"scroll": PAIRS[0][0], "ms": 650},
        {"place": [payload(s, "last", 2) for s in PAIRS[0]], "show_ms": SHOW_MS, "pin": True},
        {"scroll": PAIRS[1][0], "ms": 650},
        {"place": [payload(s, "last", 3) for s in PAIRS[1] + OUT_OF_VIEW], "show_ms": SHOW_MS, "pin": True},
        {"click": story["grid_button"], "ms": GRID_HOLD_MS, "cut_until_images": True},
    ]
    return {
        "webui": str(WEBUI),
        "url": f"http://127.0.0.1:{port}/decks/#{deck_id}",
        "locale": story["locale"],
        "ui_locale": story["ui_locale"],
        "viewport": list(VIEWPORT),
        "scale": SCALE,
        "hold_start_ms": HOLD_START_MS,
        "frames_dir": str(work / "frames"),
        "deck_root": str(root),
        "actions": actions,
    }


class DevServer:
    """`npm run dev:local` on 127.0.0.1:<port> with a scratch deck root and config dir."""

    def __init__(self, deck_root: Path, config: Path, port: int, log: Path):
        self.args = (deck_root, config, port, log)
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> DevServer:
        deck_root, config, port, log = self.args
        env = {**os.environ, "SDPM_DECK_ROOT": str(deck_root), "XDG_CONFIG_HOME": str(config)}
        self.log = log.open("w")
        self.proc = subprocess.Popen(  # nosec B603 B607
            ["npm", "run", "dev:local", "--", "-p", str(port)],
            cwd=WEBUI,
            env=env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.time() + 120
        while time.time() < deadline:
            if "Ready" in log.read_text(errors="replace"):
                return self
            if self.proc.poll() is not None:
                raise SystemExit(f"dev server exited:\n{log.read_text(errors='replace')}")
            time.sleep(0.5)
        raise SystemExit("dev server did not become ready")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
        self.log.close()


def gif_clock(rec: dict):
    """Map recording time to GIF time: cuts removed, speed changes applied, 0 at the open."""
    cuts = []
    for a, b, kind in rec["cuts"]:
        if kind == "idle":
            a, b = a + KEEP_BEFORE_S, b - KEEP_AFTER_S
        if b > a:
            cuts.append((a, b))
    speeds = sorted(rec["speeds"])
    open_at = rec["first_animation"] + OPEN_AT_S
    marks = sorted({x for ab in cuts for x in ab} | {t for t, _ in speeds})

    def rate(t: float) -> float:
        if any(a < t < b for a, b in cuts):
            return 0.0
        factor = 1.0
        for at, f in speeds:
            if at <= t:
                factor = f
        return 1.0 / factor

    def clock(t: float) -> float:
        if t <= open_at:
            return 0.0
        points = [open_at, *(m for m in marks if open_at < m < t), t]
        return sum((q - p) * rate((p + q) / 2) for p, q in zip(points, points[1:], strict=False))

    return clock


def padded(file: str, size: tuple[int, int], cache: Path) -> str:
    """The frame, centred on a `size` canvas when it is smaller (part 2 is narrower)."""
    img = Image.open(file)
    if img.size == size:
        return file
    canvas = Image.new("RGB", size, PAD_COLOUR)
    x, y = (size[0] - img.width) // 2, (size[1] - img.height) // 2
    canvas.paste(img.convert("RGB"), (x, y))
    ImageDraw.Draw(canvas).rectangle((x - 2, y - 1, x + img.width + 1, y + img.height), outline=PAD_EDGE, width=2)
    out = cache / Path(file).name
    canvas.save(out, compress_level=1)
    return str(out)


def assemble_gif(frames_dir: Path, out: Path) -> tuple[float, int]:
    """Cut, retime and pad the frames, write the GIF; return (duration s, bytes)."""
    rec = json.loads((frames_dir / "frames.json").read_text())
    clock = gif_clock(rec)
    size = (VIEWPORT[0] * SCALE, VIEWPORT[1] * SCALE)
    cache = frames_dir / "padded"
    cache.mkdir(exist_ok=True)

    timeline: list[tuple[float, str]] = []
    for f in rec["frames"]:
        t = clock(f["t"])
        if timeline and t - timeline[-1][0] < 1e-3:
            timeline[-1] = (timeline[-1][0], f["file"])  # same instant after a cut: keep the newest
        else:
            timeline.append((t, f["file"]))
    end = clock(rec["end"])
    lines = []
    for i, (t, file) in enumerate(timeline):
        nxt = timeline[i + 1][0] if i + 1 < len(timeline) else end
        lines += [f"file '{padded(file, size, cache)}'", f"duration {max(nxt - t, 0.001):.4f}"]
    lines.append(lines[-2])
    listing = frames_dir / "concat.txt"
    listing.write_text("\n".join(lines) + "\n")

    raw = frames_dir / "raw.gif"
    vf = (
        f"fps={FPS},scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=256:stats_mode=full[p];"
        "[b][p]paletteuse=dither=none:diff_mode=rectangle"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-vf",
            vf,
            "-loop",
            "0",
            str(raw),
        ]
    )
    run(["gifsicle", "-O3", str(raw), "-o", str(out)])
    return end, out.stat().st_size


def record(lang: str, work: Path, port: int) -> None:
    story = STORIES[lang]
    work.mkdir(parents=True, exist_ok=True)
    plan = build_plan(lang, story, work, port)
    plan_path = work / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    shutil.rmtree(plan["frames_dir"], ignore_errors=True)
    (work / "config").mkdir(exist_ok=True)
    with DevServer(Path(plan["deck_root"]), work / "config", port, work / "dev.log"):
        res = subprocess.run(["node", str(HERE / "record.cjs"), str(plan_path)], cwd=REPO)  # nosec B603 B607
    if res.returncode != 0:
        raise SystemExit(f"{lang}: recording failed")
    out = ASSETS / story["gif"]
    duration, size = assemble_gif(Path(plan["frames_dir"]), out)
    print(f"{lang}: {out.relative_to(REPO)} {duration:.1f} s, {size / 1e6:.2f} MB, {GIF_WIDTH} px wide, {FPS} fps")
    if not 12 <= duration <= 15 or size > 8e6:
        print("  warning: outside the 12-15 s / 8 MB target")


def stills(lang: str) -> None:
    """Cover large on top, the other slides in rows of three below."""
    story = STORIES[lang]
    with tempfile.TemporaryDirectory(prefix=f"sdpm-hero-{lang}-") as tmp:
        pages = [Image.open(p).convert("RGB") for p in render_pages(HERE / story["deck"], WIDTH, Path(tmp))]

    width, gap, cols = 1760, 24, 3
    inner = width - 2 * gap
    cover = pages[0].resize((inner, round(pages[0].height * inner / pages[0].width)), Image.Resampling.LANCZOS)
    tw = (inner - (cols - 1) * gap) // cols
    small = [p.resize((tw, round(p.height * tw / p.width)), Image.Resampling.LANCZOS) for p in pages[1:]]
    th = small[0].height
    rows = (len(small) + cols - 1) // cols
    sheet = Image.new("RGB", (width, gap + cover.height + rows * (gap + th) + gap), "#161A22")
    draw = ImageDraw.Draw(sheet)

    def paste(img: Image.Image, x: int, y: int) -> None:
        sheet.paste(img, (x, y))
        draw.rectangle((x - 1, y - 1, x + img.width, y + img.height), outline="#2C3240", width=1)

    paste(cover, gap, gap)
    for i, img in enumerate(small):
        r, c = divmod(i, cols)
        x0 = gap + (inner - (min(cols, len(small) - r * cols) * (tw + gap) - gap)) // 2
        paste(img, x0 + c * (tw + gap), gap + cover.height + gap + r * (th + gap))
    out = ASSETS / story["still"]
    sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(out, optimize=True)
    print(f"{lang}: {out.relative_to(REPO)} ({sheet.width}x{sheet.height}, {out.stat().st_size // 1024} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("langs", nargs="*", help=f"languages (default: all of {list(STORIES)})")
    parser.add_argument("--port", type=int, default=3917, help="dev server port on 127.0.0.1 (default 3917)")
    parser.add_argument("--keep", metavar="DIR", help="work in DIR and keep it (frames, plan, dev.log)")
    parser.add_argument("--no-gif", action="store_true", help="skip the recording")
    parser.add_argument("--no-stills", action="store_true", help="skip the stills")
    args = parser.parse_args()
    for lang in args.langs:
        if lang not in STORIES:
            raise SystemExit(f"unknown language: {lang} (have {list(STORIES)})")
    for lang in args.langs or list(STORIES):
        if not args.no_gif:
            if args.keep:
                record(lang, Path(args.keep) / lang, args.port)
            else:
                with tempfile.TemporaryDirectory(prefix=f"sdpm-hero-{lang}-") as tmp:
                    record(lang, Path(tmp), args.port)
        if not args.no_stills:
            stills(lang)


if __name__ == "__main__":
    main()
