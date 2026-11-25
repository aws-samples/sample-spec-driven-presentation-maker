---
description: "Universal slide rules — the form-to-meaning correspondences and text accuracy every deck owes, whatever its style or guides"
---

# Verify

Read this before writing slide text, and again when reviewing slides. These rules hold
for every deck. A style, a structure guide and a writing guide carry the user's
preferences and can be replaced; these cannot, because breaking one is not a matter of
taste — it leaves the reader with a slide that says something other than what it means.

Nothing here is measured. The build catches overflow, overlap, clipped text and font
tokens; a reviewer is given measured facts about regions, repetition and density. What
follows is what neither reaches.

## Form carries meaning

- Things drawn in the same form must mean the same kind of thing. A form promises a
  sameness, and a reader believes the promise before reading the words.
- A typeface is a form. One kind of thing takes one typeface across a deck; the same
  identifier set in two faces reads as two kinds of thing. Where a style reserves a
  typeface for one role, that role is the only thing it is for.
- Things drawn differently must differ in meaning, and a legend or a heading must say
  how. A difference nobody explains reads as an accident.
- Rows stacked above each other must correspond item by item where they are meant to
  correspond. A mismatch leaves the reader pairing things that do not pair.
- Items listed side by side must be the same kind of thing at the same level. A list is
  a claim that its items are peers.
- A title must name what its slide actually holds.
- A label repeated across items must carry one meaning, and then belongs in a row label
  rather than repeated. Where the repetitions mean different things, the repetition is
  itself the defect.

## Text accuracy

- A line must break where the reader expects a pause: at a word boundary in a language
  that spaces its words, at a phrase boundary in Japanese and other unspaced ones.
  Never leave a particle, a suffix or a unit stranded at the start of a line, and never
  split a compound or a number from its unit.
- A line breaks only because the text does not fit. A style's sample slides are written
  in one language and may show their titles over two lines; the same claim in another
  language takes a different width, so a break copied from the samples breaks a line
  that fits. Take the space a style reserves, not the number of lines it happens to
  use, and measure before deciding.
- The characters must be the right ones. Visually close characters survive every check
  — in Japanese, 樣 for 様, 狐って for 狙って, 続続月数 for 継続月数.

**Constraints:**
- You MUST look at the preview of every slide before calling it done, even when every
  check passed. Passing checks mean nothing was measured as wrong, not that the slide
  reads correctly.

## Keeping this guide honest

When a check starts covering one of the rules above, delete that rule from this guide. A
rule kept after a check covers it costs a reader's attention and earns nothing.

Do not copy a check's implementation into this guide — no thresholds, no function names.
The check is the source of truth for how it works, and a copy here would drift from it
silently. How a reviewer reads the measured facts is in the review role document.
