---
description: "Initial environment setup — read once on first use"
---

# Setup Guide

Setup steps for using the spec-driven-presentation-maker Skill in a new environment.

## Prerequisites

- kiro-cli installed
- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed

## 1. Install dependencies

```bash
cd /path/to/spec-driven-presentation-maker/skill
uv sync
```

## 2. Deploy sub-agent

```bash
cp agents/design-reviewer.json ~/.kiro/agents/
kiro-cli agent list | grep design-reviewer
```

## 3. Verify

```bash
# Check pptx_builder.py works
uv run python3 scripts/pptx_builder.py examples

# Check icon search works
uv run python3 scripts/pptx_builder.py icon-search "lambda"

# Check init works
uv run python3 scripts/pptx_builder.py init -o /tmp/test-pptx && rm -rf /tmp/test-pptx
```

## Troubleshooting

### uv not installed
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### "design-reviewer agent not found"
```bash
cp agents/design-reviewer.json ~/.kiro/agents/
```

### "Missing icons" error
```bash
uv run python3 scripts/download_icons.py
```
