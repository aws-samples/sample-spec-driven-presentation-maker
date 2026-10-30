# PowerPoint animation catalog tools

Development-only tools in this directory create native PowerPoint evidence used by sdpm's checked-in animation and transition catalog. Runtime generation never invokes PowerPoint, AppleScript, or GUI automation.

## Morph spike

Run from `/Users/naohitoa/dev/sdpm-animations`:

```bash
uv run python scripts/animation_catalog/morph_probe.py --verify-package
```

The probe applies Microsoft's documented forced-Morph naming convention: matching adjacent objects are named with the same `!!`-prefixed Selection Pane name. It builds destination slides for `byObject`, `byWord`, and `byChar` using the Office 2015/09 `p159:morph` transition inside `mc:AlternateContent`, with a standard fade fallback.

The automated probe verifies package structure only. This dashboard's sandbox cannot control PowerPoint through Apple Events (`-10004` privilege violation), so visible interpolation versus cross-fade is verified once in the final PowerPoint acceptance flow.

Source: [Morph transition: Tips and tricks](https://support.microsoft.com/en-us/office/morph-tips-and-tricks-bc7f48ff-f152-4ee8-9081-d3121788024f)
