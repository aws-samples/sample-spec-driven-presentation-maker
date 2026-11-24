---
description: "Verifying a built deck — reading the measured facts, and the correspondences only a reader catches"
---

# Verify

Read this when reviewing slides that have been built and measured. It covers what the
machine reports, how to decide whether a reported fact is a defect, and the
correspondences between a slide's form and its meaning that no check reaches.

## The facts you are given

`start_reviewing` hands you `facts` for a PPTX deck. Each slide reports five things.

| Fact | What it reports |
|---|---|
| `visible_words` | The space-delimited words on that slide, beside `density_limit`, the budget the style declares |
| `visible_characters` | The visible characters on that slide, ignoring whitespace |
| `outside_regions` | Elements extending past the region they belong to, and how far, per edge |
| `region_sizes_by_prefix` | Regions whose names share a prefix, with the size of each |
| `stacked_region_groups` | Each row of regions, in top-to-bottom order, with how many it holds |
| `repeated_text` | Strings appearing more than once on the slide, and where |

These are measurements, not findings. Nothing in them says a slide is wrong, because
whether any of them is wrong depends on what the slide means — and that is your call,
made against the structure and writing guides the deck was given.

## Deciding whether a fact is a defect

Work from what the slide is trying to say.

- **Over the density limit** means the slide is carrying more than this style draws
  well. Decide whether the surplus earns its place or belongs in the notes or on
  another slide. A slide well under the limit is not thereby good.
  `density_limit` counts space-delimited words, so compare `visible_words` against it
  only for a language that separates words with spaces. For Japanese and other unspaced
  scripts the word count runs far below the limit however full the slide is: use
  `visible_characters`, and judge it against the style's own sample slides and the
  preview rather than against the limit.
- **Outside its region** is usually a defect: the region is where the style expects
  that content. A deliberate bleed is the exception, and it reads as deliberate only
  when the overflow is large and even.
- **Regions sharing a prefix at different sizes** says the slide draws siblings
  unequally. If they are siblings, match them. If one is genuinely more important, the
  difference has to be large enough to read as a choice rather than a mistake.
- **A row holding a different count from the row above** matters only when the two rows
  are meant to correspond. When they do, a mismatch leaves the reader pairing items
  that do not pair.
- **A repeated string** is worth lifting out when every instance means the same thing:
  a label repeated in each column belongs in a row label. When the instances mean
  different things, the repetition is the problem instead.

Report a fact only once you can say what is wrong and why. Give the slide, the
evidence, what is wrong, and how sure you are.

## What the checks do not see

Look at the preview for each of these. Measurement cannot reach any of them.

- Things drawn in the same form: does the form promise a sameness the content does not
  have?
- Things drawn differently: are they genuinely different, and does a legend or a
  heading say how?
- Rows stacked above each other: do their items correspond one to one?
- The title: does it name what the slide actually holds?
- Items listed side by side: are they the same kind of thing, at the same level?
- A label repeated across items: is it one meaning, and can it be lifted into a row
  label?
- Line breaks: do they fall at word boundaries rather than mid-word?
- The characters themselves: are they the right ones? Visually close characters survive
  every check — in Japanese, 樣 for 様, 狐って for 狙って, 続続月数 for 継続月数.

**Constraints:**
- You MUST look at the preview of every slide, even when every check passed. Passing
  checks mean nothing was measured as wrong, not that the slide reads correctly.
- You MUST report what you see and MUST NOT edit the deck.

## Keeping this guide honest

When a check starts covering one of the perspectives above, delete that perspective
from this guide. A perspective kept after a check covers it costs a reader's attention
and earns nothing.

Do not copy a check's implementation into this guide — no thresholds, no function
names. Write how to call it and how to read what it returns. The check is the source of
truth for how it works, and a copy here would drift from it silently.
