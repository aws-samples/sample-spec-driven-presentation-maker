# Brief: Spec-Driven Presentation Maker — the README key visual deck

Agreed with the user on 2026-11-01.

## Audience
Someone who opens the GitHub README of aws-samples/sample-spec-driven-presentation-maker, sent by a workshop or a
colleague. They decide in a few seconds whether to try it; if yes, they install locally or use One-Click Deploy.

## What they should believe or do afterwards
- You only agree on *what to say*. AI builds *how to show it*, and you correct it by drawing on the slides.
- Next step: run the one-line install.

## How the deck is seen
Mostly inside the README as a 10–15 second animated GIF of the slides being composed, plus stills. Nobody presents it.
Every slide must read at a glance: a short headline, one strong drawn figure, very little body text.

## Language and length
English (a Japanese variant is made later with translate). 7 slides.

## Flow
1. Cover — Spec-Driven Presentation Maker. Decide what to say; AI builds how to show it.
2. Problem — from a blank slide, time goes to layout and the message gets diluted (before / after).
3. Spec first — three documents, brief → style → outline, agree on the content first.
4. Built in parallel — a layout pass sets the frame, then several composers build slides at once.
5. PPTX or HTML — one spec, two outputs: PowerPoint and an interactive HTML deck.
6. Fix by drawing — draw frames on the preview, comment, send them together as one change request.
7. Get started — one command; then ask your AI agent, open `sdpm webui`, or deploy on AWS.

## Constraints
- No internal tool names (`start_presentation`, …) or protocol names (MCP, ACP) on slides; say "your AI agent".
- No invented numbers or claims (no "10x faster"); only what is true of the product today.
- Generic examples only; nothing internal or tied to a customer.
- Headlines and supporting lines in the outline are fixed wording, approved by the user; use them verbatim.

## Sources
- `README.md` and `docs/en/` user guide — features and install (the install one-liner is the README's).
- `sdpm/references/workflows/orchestrator.md` — the phases (brief, style, outline, layout pass, content, review).
- Web UI region review comments (merged in #473; `web-ui/src/components/review/`).
- HTML output mode (v0.11.0; `sdpm/references/workflows/composer-html.md`).
- `docs/assets/workflow-en.png` — the current workflow diagram.
