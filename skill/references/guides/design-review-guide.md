---
description: "Review checklist for visual quality — read during preview review phase"
---

# Design Review Guide

Review preview PNG images and report design quality issues.

## Input

1. **Preview image path**: Directory or file path of PNG images generated from the PPTX
2. **Output JSON path**: For reference when fixes are needed

## Procedure

### 1. Read preview images

Read slide preview images with fs_read Image mode.

### 2. Check each slide

Detect issues from the following perspectives:

**Clarity**:
- Is the slide easy to understand?
- Is the composition effective?
- Are there structural improvements to make?

**Layout**:
- Are elements overflowing outside the slide?
- Is there unnatural whitespace at the top or bottom?
- Are elements overlapping?
- Is text clipped?
- Is text on shapes positioned at the visual sweet spot (e.g. vertically centered)?

**Text**:
- Is the text content correct?
- Is text too small to read?
- Are line breaks awkward?

**Design**:
- Is color contrast sufficient (e.g. dark text on dark background)?
- Is there overall visual consistency?
- Is whitespace used appropriately?

### 3. Report review results

Report issues in the following format:

```
## Review Results

### Slide N: Title
- [Issue type] Specific description of the problem
- [Fix suggestion] How to fix it

### No issues
- Slides 1, 3, 5, 7 have no issues
```

**Constraints:**
- You MUST read ALL preview images before reporting
- You MUST be specific about what is wrong and where
- You MUST suggest concrete fixes (e.g. "move y coordinate down by 50px", "change fontSize to 20pt")
- You MUST NOT report minor aesthetic preferences as issues — focus on actual problems
