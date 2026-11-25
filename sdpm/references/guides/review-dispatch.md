---
description: "How the orchestrator dispatches reviewers — read only when start_presentation returned review: true"
---

# Dispatching reviewers

The deck is held against each of its guides by a reviewer, twice: once on the outline and
once on the composed slides. Dispatch reviewers the same way you dispatch composers, with
this prompt (replace only the placeholders):

```
You are an sdpm reviewer. First call start_reviewing(deck_id, guide, target) with the
values below and follow the role document it returns.

deck_id: {deck_id}
guide: {structure|writing|style|verify}
target: {outline|slides}
```

With the outline written, dispatch a reviewer against the structure guide. Once the slides
are composed, dispatch reviewers against the writing guide, the style and `verify` in
parallel — each holds the deck against its own guide, and what to look for is in that guide,
not here. `verify` is the one guide a user cannot replace: it holds the rules every deck
owes, which the composers also read before writing text. If your environment has no
sub-agent mechanism at all, hold the deck against each guide yourself: call
`start_reviewing` with the same values and follow the document it returns, then come back
to the orchestrator document.

Reviewers report; they never edit. You decide which findings to act on and dispatch a
composer for each slug that needs changing, with an instruction describing what to fix. A
finding you reject needs no action, but say so if the user asked about it.

Review does not replace the user's confirmation. The findings are material for your
decision; the user's `show_deck` review is theirs.

A user who asks for a review on a deck built without one gets it the same way: dispatch
the reviewers now, against the guides the deck already carries.
