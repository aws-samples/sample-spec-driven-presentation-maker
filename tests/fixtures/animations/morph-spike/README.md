# Morph spike fixture

This manifest freezes the contract tested before the generic transition writer is implemented.

- PowerPoint's documented deterministic object matching uses the same Selection Pane name on adjacent slides, prefixed with `!!`.
- sdpm maps JSON `morphId: "hero"` to `!!sdpm-morph-hero`.
- Duplicate `morphId` values on one slide are rejected because they make a forced pair ambiguous.
- Morph is stored on the destination slide as `p159:morph` with one of `byObject`, `byWord`, or `byChar` and a standard fade fallback.
- The automated fixture checks package structure and geometry deltas. Final Task 8 checks visible interpolation and forbids cross-fade in PowerPoint.

Official source: [Morph transition: Tips and tricks](https://support.microsoft.com/en-us/office/morph-tips-and-tricks-bc7f48ff-f152-4ee8-9081-d3121788024f)
