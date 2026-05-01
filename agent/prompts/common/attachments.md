## File Attachments

When user messages contain `[Attached: filename (uploadId: xxx)]`:

1. **Read** the file to understand its content and decide how to use it
2. **Reflect** the content in brief — as Source Material with pointers and summaries, not full transcription
3. **Decide** whether to import — composer needs the file when it must reference the original content directly or process it via `run_python`
4. If importing, write **evidence** in the outline so composer knows which file and lines to reference per slide

### Citation Format

In brief Source Material and outline evidence, cite with line numbers:
- `filename:L42` or `filename:L42-L58`
- Example: `Sales grew 15% YoY [report.md:L142-L145]`

Imported files are placed in `attachments/` or `images/`. Composer accesses them via `open("attachments/xxx")` in `run_python`.

### Source Material in Brief

Source Material is the composer's guide to what information exists and where.
Do not transcribe entire documents — write pointers and summaries so the composer can look up the original via line numbers.

```
### Q1 Sales Report (attachments/a1b2_report.md)
- Overview: revenue +15%, margin improved [report.md:L1-L20]
- Regional breakdown: table at L42-L80, APAC highest growth
- Key chart: images/a1b2_pdf_p3_img1.png
```

### Evidence in Outline

When a slide uses data from an attached file, write it as evidence:

```
- [regional-sales] Regional sales comparison
  - evidence: attachments/report.md:L42-L80 regional sales table
  - evidence: images/a1b2_pdf_p3_img1.png sales trend chart
```
