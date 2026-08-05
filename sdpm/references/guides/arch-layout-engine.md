---
description: "Nested-JSON architecture layout engine (auto-routing) — read when building an AWS/system architecture diagram from logical structure instead of hand-placing coordinates"
---

# Architecture Layout Engine (nested-JSON auto-router)

The layout engine turns a **logical structure** (groups, icons, connections) into
fully-placed elements with auto-routed orthogonal arrows. You describe *what
connects to what*; the engine computes coordinates, clusters related icons,
chooses arrow ports/bends, and minimizes crossings and icon pierces.

Prefer this over hand-placing coordinates (the manual style in
[arch-elements.md](arch-elements.md)) for any diagram with more than a few
connections. Hand-placement is for fine-tuning or non-flow art.

> Companion: [arch-elements.md](arch-elements.md) covers group colors,
> groupType catalog, boundary/logo, box nodes, and manual arrows.

---

## How to run it

Two equivalent front-ends call the same engine. Use whichever your host offers.

**MCP tool (`arch_diagram`)** — preferred when available. Returns the routed
layout AND the QA metrics in one call, so you can render, read the numbers, and
fix the structure without a second command:

```
arch_diagram(spec="<logical-structure JSON string>",
             x=100, y=180, width=1720, height=800, theme="dark",
             pt_per_px=0.5)
```

Default target area (x=100, y=180, width=1720, height=800) assumes 16:9 canvas.
For non-16:9 templates, derive height from slideSize: e.g. `height = H - 180 - 130`
(H from `deck.json` `slideSize`; 4:3 H=1440 → height=1130).

**`pt_per_px`** — the pt-to-px conversion rate from `deck.json`
`slideSize.ptPerPx`. Defaults to 0.5 (16:9). For non-16:9 templates, pass the
value reported by `analyze_template` (e.g. 4:3 = 0.375). The engine uses this
to calculate box auto-height from text content, so passing the correct value
ensures boxes are sized accurately regardless of aspect ratio.

> **Box auto-height (fixed in #285):** Text-to-box sizing now uses the
> `pt_per_px` parameter for calibration, so non-16:9 templates produce
> correctly-sized boxes. Explicit `"height"` on box nodes is still supported
> for manual fine-tuning.

**CLI** — same engine, for SKILL.md/script hosts:

```bash
python3 scripts/pptx_builder.py layout input.json \
  --x 100 --y 180 --width 1720 --height 800 -o elements.json
```

- Input: one logical-structure JSON (see below).
- Output: `{ "elements": [...], "bbox": {...}, "warnings": [...] }`. The MCP tool
  additionally returns `"metrics"` (crossings / pierces / group_pierces /
  overflow / score — see "Reading the output"); the CLI omits it (run
  `layout_qa.py` for the CLI path).
- Drop the `elements` array straight into a slide, or reference the whole file
  with `{"type": "include", "src": "elements.json"}`.
- `targetArea` in the JSON (`{x, y, width, height}`) overrides the x/y/width/
  height args (both front-ends).
- The engine scales the whole diagram to fit the target box, so author at any
  scale — relationships matter, absolute sizes don't.
- The `metrics`/`warnings` catch geometry, but a wrong-looking label or awkward
  bend only shows in the render. In the normal slide flow the review step
  (`create-new-3-review`) previews every slide as a PNG, so the diagram gets
  eyeballed there — no separate preview needed. Outside that flow, drop the
  elements into a one-slide deck and run `pptx_builder.py preview <deck-dir>`.

---

## Logical structure JSON

```json
{
  "direction": "horizontal",
  "iconSize": 56,
  "children": [
    {"id": "client", "icon": "assets:aws-internal/user_dark", "label": "Client"},
    {"id": "apigw",  "icon": "icons:Arch_Amazon-API-Gateway_48", "label": "API Gateway"},
    {"id": "models", "direction": "vertical", "groupType": "generic-dashed", "label": "Model Serving",
      "children": [
        {"id": "vision",  "icon": "icons:Arch_Amazon-SageMaker_48", "label": "Vision"},
        {"id": "nlp",     "icon": "icons:Arch_Amazon-SageMaker_48", "label": "NLP"},
        {"id": "tabular", "icon": "icons:Arch_Amazon-SageMaker_48", "label": "Tabular"}
      ]}
  ],
  "connections": [
    {"from": "client", "to": "apigw"},
    {"from": "apigw",  "to": "models", "label": "route"}
  ]
}
```

### Node / group fields

| Field | Where | Meaning |
|-------|-------|---------|
| `id` | every node | Unique id, referenced by `connections`. |
| `icon` | leaf | Icon source (`icons:...` / `assets:...`). |
| `box` | leaf | Text box instead of an icon (see arch-elements.md). |
| `label` | leaf / group | Caption. On a **group** it also forces the visible frame (see "Hiding group frames"). |
| `children` | group | Nested nodes (groups can nest groups). |
| `direction` | group | `"horizontal"` or `"vertical"` — main axis of this group. |
| `groupType` | group | Draws a frame (`generic-dashed`, `generic-solid`, `vpc`, …). Omit → no frame. |
| `iconSize` | root | Base icon size in px (engine scales to fit). |
| `align` | group | Cross-axis alignment: `center` (default) / `top` / `bottom` / `left` / `right`. |
| `reverse` | group | Reverse child order (flip flow direction). |

### Connection fields

| Field | Meaning |
|-------|---------|
| `from` / `to` | Endpoint ids. **May be a leaf id OR a group id** (see "Connect to a group"). |
| `label` | Optional arrow caption. |
| `fan` | `"merge"` to bundle this edge with its siblings onto one trunk (see "Fan merge"). |

---

## The engine decides position — you decide relationships

You set the group structure and the direction. **Within those constraints the
engine is free** to reorder children, pick arrow ports, and shift icons to:

- cluster connected icons close together (shorter total wire length),
- minimize edge **crossings** and icon **pierces** (an arrow cutting through a
  non-endpoint icon),
- keep the layout on-slide (overflow is ranked worse than any crossing),
- **straighten arrows where a straight run fits** — a solo arrow between two
  side-by-side endpoints (icon↔icon, icon↔group box, or two group boxes of
  unequal height) is drawn as one straight line, not an L-bend, by attaching it
  at the smaller endpoint's center. Many-to-one arrows into a group box stay
  bundled as a parallel bus instead (so they don't all pile onto one point).

A multi-objective "judge" scores candidate layouts lexicographically:
`(off-slide overflow) → (weighted defects: pierce 1.5 > crossing 1.0 > backwards
0.7) → (soft: wire length + aspect)`. You don't invoke it; it runs inside the
engine. The practical consequence: **express the right structure and the
routing usually takes care of itself.**

---

## Three techniques that make complex diagrams clean

These are the levers to reach 0 crossings / 0 pierces on dense diagrams. Reach
for them in this order.

### 1. Connect to a GROUP, not to every icon (many-to-many → many-to-one)

Dense many-to-many wiring is the #1 source of crossings. Example: 3 compute
services each writing to 4 backend resources = 12 arrows that *must* cross.

Instead of wiring every compute icon to every resource icon, **point one arrow
at the resource GROUP's box**. `from`/`to` accept a group id:

```json
{"from": "web",    "to": "data"},
{"from": "api",    "to": "data"},
{"from": "worker", "to": "data"}
```

Here `data` is a group `{aurora, cache}`. Three arrows land on the group's edge
instead of nine landing on scattered icons. The engine excludes the group's own
member icons from that edge's obstacle set, so the arrow enters the box cleanly.

This single change took the three-tier observed diagram from **21 crossings to
0**. Use it whenever a set of sources all talk to "the data tier" / "the
observability stack" / "the services layer" as a unit.

### 2. Fan merge — bundle arrows that share a hub onto one trunk

When several edges share a source (fan-out) or a target (fan-in) — whether or
not they carry the same purpose — set `"fan": "merge"` on each. They unify onto
one port and a shared trunk, then split near the spokes:

```json
{"from": "stepfn", "to": "lambda1", "fan": "merge"},
{"from": "stepfn", "to": "lambda2", "fan": "merge"},
{"from": "stepfn", "to": "lambda3", "fan": "merge"}
```

- Apply `fan: "merge"` to **every** edge in the bundle (≥2 needed).
- A merged bundle is a **hard constraint**: the engine locks the trunk and
  routes everything else around it.
- **Self-protecting**: if the merged trunk would pierce any icon, the engine
  silently rolls that bundle back to individual routing (a locked trunk can't be
  cleaned up later, so it refuses to create one that cuts through an icon).
  → You can safely mark a bundle `merge`; a geometrically-impossible merge just
  won't happen. It is NOT a way to force a bad trunk.
- Don't blanket-apply `merge` to everything. The clearest case is a genuine
  "same flow" bundle (a fan-out to workers, a fan-in to a queue). But `merge`
  also **tidies any group of edges that share one hub** — a single node that
  fans out to several services, or several sources that all converge on one
  node — even when the edges carry *different* labels/purposes. If N arrows
  leave or enter the same icon and read as a loose spray, merging them makes
  that icon emit/receive **one clean trunk** that only splits near the far
  ends. Prefer merging such a hub bundle; the per-edge labels still render on
  each spoke, so the distinct purposes stay legible.
  - The exception is edges that merely *cross paths* without sharing an
    endpoint — those aren't a bundle and shouldn't be merged.

### 3. Branch nodes go perpendicular (keep the main line straight)

A **degree-1 auxiliary node** sitting *on* the main flow line gets pierced by
the through-arrow. Humans place such a node perpendicular to the flow (a
fallback LLM below the router, an auth service above the load balancer). The
engine does this automatically **when you express the stack**:

Put the auxiliary node in a small **invisible group** (no `groupType`, no
`label`) together with its anchor, oriented along the flow's main axis:

```json
{"id": "router_col", "direction": "vertical", "children": [
  {"id": "router",  "icon": "icons:Arch_AWS-Lambda_48", "label": "Router"},
  {"id": "bedrock", "icon": "icons:Arch_Amazon-Bedrock_48", "label": "Fallback LLM"}
]}
```

The engine recognizes that `router` is the flow node (it connects outside the
group) and `bedrock` is the branch, and keeps **router on the straight main
line** while bedrock hangs below. `API GW → Router → models` stays a straight
horizontal line; the fallback drops down.

The engine also auto-detects and fixes this even without the wrapper group when
a clear branch sits between two flow nodes, but writing the invisible group is
the explicit, reliable way to control which side the branch lands on.

---

## Hiding group frames

`groupType` controls the frame:

| JSON | Result |
|------|--------|
| `"groupType": "generic-dashed"` | dashed frame + label |
| `"groupType": "generic-solid"`  | solid frame + label |
| *(no `groupType`)* | **no frame** — grouping still works for layout |

Omitting `groupType` gives an **invisible group**: icons still cluster and you
can still aim a connection at the group, but no box is drawn. Use this for the
branch-node wrapper above, or to get a clean icons-and-arrows-only diagram.

⚠️ A frameless group also drops its **label** (label renders on the frame
element). If you need the cluster named, keep a `groupType`.

---

## Recipe: take a dense AWS diagram to 0 crossings

1. **Lay out the main flow left→right (or top→bottom)** as the root `direction`.
   Data pipelines and request flows read best horizontally; don't stack 5 tiers
   vertically (it overflows and compresses).
2. **Group by tier/role**: services, data, observability each become a group.
3. **Replace many-to-many with many-to-one to the group box** (technique 1).
4. **Mark genuine bundles `fan: "merge"`** (technique 2).
5. **Wrap degree-1 auxiliaries (fallback, auth, cache-aside) in an invisible
   perpendicular group** with their anchor (technique 3).
6. Run `layout`, read `warnings`, and check crossings/pierces. Iterate on
   structure — not coordinates — if defects remain.

### Worked examples (all reach 0 crossings / 0 pierces)

- **3-tier web**: ECS group → Data group, ECS group → Observability group
  (many-to-one); `alb → web/api/worker` as a `fan: "merge"` fan-out. 12 → 0
  crossings. ⚠️ Place Observability so `ECS→Obs` does not have to cross the
  Data box (e.g. Obs as its own row below, not on the far side of Data) — laying
  Data *between* ECS and Obs causes a group-frame pierce.
- **Microservices + events**: `apigw → services` group, `bus → services` group,
  `services → queue` group. Per-service `{Lambda, DB}` vertical stacks. 10
  pierces → 0.
- **ML inference**: `{router, bedrock}` invisible vertical column; `router →
  models` group, `models → shared` group. Router stays on the straight flow,
  Bedrock drops below.
- **Data pipeline**: horizontal flow `sources → kinesis → stepfn → lambdas →
  s3 → analytics`; producers fan-in to Kinesis, stepfn fans-out to Lambdas,
  Lambdas fan-in to S3 — all `fan: "merge"`.

---

## Anti-patterns

- **Wiring every icon to every icon** across two groups → use a group endpoint.
- **`fan: "merge"` on edges that DON'T share an endpoint** (two arrows that
  merely cross paths) → merge only bundles edges sharing one hub node. Edges
  sharing a hub but carrying different purposes CAN merge (see technique 2).
- **Forcing a merge the engine rolled back** → the trunk pierced an icon;
  restructure (split the bundle, reorder, or route to a group) instead.
- **Deep vertical nesting** (5+ stacked tiers) → overflows height and compresses
  spacing; flip the root to horizontal.
- **Putting a degree-1 helper inline on the flow** and expecting no pierce →
  wrap it perpendicular.
- **One source set fanning into TWO separate targets** (e.g. three workers each
  writing to both a *feature store* and a *prediction stream*) → the two
  fan-in bundles overlap on one shared trunk and every spoke crosses the other
  bundle. Don't aim a many-source fan at two scattered targets. Instead put the
  two targets in ONE group and fan into that group box (technique 1), or give
  each target its own row so the two bundles don't share a trunk lane.
- **Routing a line past a framed group that sits across its path** → the line
  cuts through an unrelated container's box (a *group-frame pierce*). See below.

---

## Group-frame pierces (a line crossing an unrelated container)

A line that slices through a **framed** group's box without connecting to that
group or any icon inside it reads as broken — it looks like it belongs to the
container but doesn't. The engine reports this as `group_pierces` and tries to
**auto-detour around the box, but ONLY when it can clear it completely**. If a
group sits squarely across the line's path (so no detour escapes without going
off-slide or through something else), the engine leaves the line straight and
emits a warning — because this is a **structural** problem you must fix, not a
routing one.

When you see `Edge X→Y cuts through group "Z"`:

1. **Reorder the groups** so X and Y are adjacent with no group between them.
   (Three-tier: putting Observability *between* ECS and Data — or below — instead
   of on the far side of Data, so `ECS→Obs` doesn't cross the Data box.)
2. **Move the offending group off the path** (different row/column).
3. **Connect to the group box itself** (many-to-one) if the flow genuinely
   enters it — then it's no longer an unrelated container.

Invisible groups (no `groupType`) have no box and never trigger this — only
framed groups do.

---

## Reading the output

- `warnings`: human-readable facts about what's wrong, NOT prescriptions.
  Routing warnings state only the defect — `Edges A→B and C→D cross.`,
  `Edge X→Y passes through node "Z".`, `Edge X→Y passes through group "Z"
  without connecting to it.` — they deliberately do **not** tell you how to
  fix it. You have the JSON and the rendered image; decide the structural fix
  yourself (connect to a group box, `fan: "merge"`, reorder, change
  `direction`, …) using the techniques above. Size warnings (tall/wide group,
  overflow, compressed spacing) still carry a short hint. The edge-crossing
  warning uses the **same** detector as the QA `crossings` metric, so a
  `fan: "merge"` trunk's structural T-junction is NOT reported — if `warnings`
  lists an `Edges … cross`, the QA metric will show `crossings > 0` too. A
  "tall/wide group" hint is advisory only: if `overflow` is 0 the layout fits,
  so don't restructure just to silence it.
- `bbox`: final bounding box after scale-to-fit.
- `metrics`: objective QA numbers, returned inline by the `arch_diagram` MCP
  tool. For the CLI, get the same numbers from the QA harness:

  ```bash
  python3 scripts/layout_qa.py input.json --width 1720 --height 800
  ```

  - `crossings` — edge segments that intersect.
  - `pierces` — a line through a non-endpoint **icon**.
  - `group_pierces` — a line through an unrelated **framed group box** (above).
  - `overflow` — fraction the layout spills off the target box (0 == fits;
    ranks worse than any crossing).
  - `score` — the judge's lexicographic tuple `(overflow, weighted defects,
    soft)`, lower is better.
  - A clean diagram has crossings / pierces / group_pierces all at 0.

  Loop on this: render → read `metrics` → change **structure** (not
  coordinates) → re-render, until the three defect counts are 0.

---
**Updated**: 2026-07-09
