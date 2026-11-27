---
description: "How to write a guide of your own: the frontmatter, the tags, when a guide is handed over automatically, and how to say when to read it"
tags: [management, orchestrator]
---

# Writing a guide

A guide is one markdown file that decides one thing. Guides are one collection: the ones
shipped with sdpm and the ones you write sit in the same list, carry the same frontmatter
and are reached the same way, so your guide can shadow a shipped one by taking its name.

Put yours in `guides/` under your sdpm config directory, or point `SDPM_GUIDES_DIR` at a
directory of your own; on the hosted service, create it through the guides endpoint. Your
directory is searched first, so a guide you name `design-rules` replaces the shipped one for
you and for nobody else.

`list_guides()` shows every guide with its description, its tags and whether it is handed
over automatically. `list_guides(role="composer")` narrows it to one role.

## The frontmatter

Three keys, one per line, between two `---` lines:

```
---
description: "One line: what this guide decides, and when to read it"
tags: [composer, composer-pptx]
always: false
---
```

`description` and `tags` are required; `always` defaults to false. Nothing else is allowed —
a fourth key, a comment, an indented sub-key or a missing value makes the guide invalid, and
an invalid guide is reported in the listing instead of being handed over. That is deliberate:
a guide that fails to parse would otherwise disappear silently from every role that needed
it. A single guide's text is capped at 64 KiB, because its body goes into a system prompt.

## When one guide should become two

Split when the two halves are read at different moments, by different roles, or under
different conditions. A guide is loaded whole, so a reader who needs the second half pays
for the first.

- Two roles, one file: the orchestrator reads the first half and the composer the second.
  Split it; each half gets its own tag.
- One role, two conditions: half applies to every deck and half only to Japanese decks.
  Split it; the conditional half says so in its description.
- One role, one moment, two topics: leave it together. A reader who needs the tables also
  needs the charts beside them, and two files mean two reads and two chances to miss one.

The test is the reader, not the length. A 300-line guide read in one moment is one guide;
40 lines read in two unrelated moments are two.

## Which tags to set

Tags say who may be given this guide. The vocabulary is closed:

| Tag | The caller |
|---|---|
| `orchestrator` | planning a deck: brief, style, outline, dispatch |
| `composer` | building slides, in either mode |
| `composer-pptx` | building slides as slide JSON |
| `composer-html` | building slides as HTML |
| `style` | authoring or editing a style |
| `translate` | producing another language edition |
| `management` | working on sdpm itself, in no role |

Carry **every** tag the guide could be called under, not the one you had in mind. A guide
tagged only `composer-pptx` is invisible to an HTML composer, including in the listing — so
if it applies to both, tag `composer` and let both modes see it. Use the mode tags only for
something that genuinely does not exist in the other mode.

`management` is for a guide that is about sdpm rather than about a deck. No role picks it up,
so it is found only by a caller listing guides without a role — this guide is one.

## When always is justified

`always: true` means the guide's whole text is placed in that role's prompt every time the
role starts, without anyone asking for it. It costs that text on every call, so it is
justified only when the guide applies to every single run of the role and the role cannot do
its first step correctly without it.

A format specification qualifies: a composer that has not read it writes invalid output.
A vocabulary of options qualifies when choosing one is the role's first move. Everything
else does not: a guide for tables, a guide for a chart type, a guide for importing a file —
those are read when the work calls for them, and their description is what makes them
findable.

Keep a role to a handful — roughly two to five. Past that the prompt is mostly guides, the
role document competes with them for attention, and the guide that actually mattered on this
deck is buried among the ones that did not.

## Naming a guide, and its one line

The file name is the guide's name, and it is what every caller types. It is a single name
with no dots, no slashes and no extension beyond `.md`: `story-line`, `slide-json-spec`,
`acme-brand-rules`.

Name it after what it decides, not the category it belongs to. `story-line` says the thing it
settles; `structure` does not say what is being structured. If the name needs the description
to make sense, rename it.

The description is one line and it is the only thing a caller sees before deciding to read
the guide. Write what the guide decides and when it applies. Two failure modes:

- Too broad to choose by: "Design guidance." Every guide is design guidance.
- A restatement of the name: "Rules for tables." The caller already read `table`.

Instead, name the decision: "Which table shape fits the data, and the row and column limits
beyond which a table should become a chart."

## Saying when to read it

A guide that applies only sometimes needs its condition in the description, because the
condition is checked by the reader, not by sdpm. No code looks at the deck's language, the
audience or the template and picks guides from it; selection is by tag alone. So write the
condition as the first clause of the description, in words the caller can match against what
it knows.

Worked through, for the Japanese-deck case. `writing-ja` holds how Japanese text is written
on a slide: line breaking, punctuation, the spacing between Japanese and Latin runs. Its
natural tags are `orchestrator` and `composer`, because the outline and the slides both carry
the text.

- `always: true` is wrong. Every English deck would carry Japanese typography rules in its
  prompt, and the rules would compete with the ones that applied.
- A `language` condition in code is also wrong. The hand-over happens when the role starts,
  which is before the outline exists; a deck whose quotes are Japanese and whose body is
  English has no single answer; and one language is not a reason to add a selection axis that
  every future condition would then want.
- What works is the description: **"Read when the deck's language is Japanese — line
  breaking, punctuation and the spacing between Japanese and Latin text."** A composer that
  knows the deck's language reads the first clause and decides. A composer working in English
  skips it at no cost.

Write the condition the same way: a state the caller can observe about the deck, not a
preference about the guide.
