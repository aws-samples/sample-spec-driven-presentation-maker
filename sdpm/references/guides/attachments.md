---
name: attachments
description: "read_attachment / import_attachment — formats, paging, the import bundle layout, and retry"
category: guide
---

# Attachments

Two tools handle user-supplied material. `read_attachment` looks at it; `import_attachment`
copies it into the deck so slides can use it. Both take the same `source`: an absolute path
(local), an S3 key (cloud), or an `https://` URL. URLs are fetched with the same safety checks
in both.

## read_attachment — look, don't store

Returns a `header` (JSON metadata) and a `body` of line-numbered text. Nothing is written.

| Source | What comes back |
|---|---|
| text / md / csv / html / json | UTF-8 text with line numbers |
| pdf / docx / xlsx | Markdown conversion, paged |
| pptx | `deck_text_summary`, `slideCount`, `themeHints`, and a `guideInstruction` pointing to the `import-pptx` guide |
| image | metadata only — locally a path plus `colorAnalysis`; on the cloud stack the image itself as content |

Paging: `offset` is a UTF-8 byte offset into the text projection, `limit` the maximum bytes
returned (header + body; 512–10240, default 10240). The header says whether more follows;
continue with the next offset. Read only the parts your slides need — the brief's Sources
list says which section or page range matters.

## import_attachment — commit into the deck

Converts the source and commits the result atomically to
`{deck}/attachments/imports/{importKey}/`. The same source with the same options yields the
same `importKey`, so a repeat call is a no-op that returns the existing bundle. A committed
bundle is never modified.

| Source | Bundle contents |
|---|---|
| image | `images/{hash}_{name}` (webp converted to PNG) plus `imageMapping` from the original name |
| pdf / docx / xlsx | extracted text and the embedded images |
| pptx | the full deck structure — `deck.json`, `slides/`, `template.pptx` (see the `import-pptx` guide) |
| URL | downloaded, then handled as one of the above |

The result lists `importKey`, `sourceHash`, `files` and `imageMapping`. Reference an imported
image from a slide by its path under `attachments/`.

### Retry

A long conversion can exceed the tool timeout. The response then carries
`code: "IMPORT_INCOMPLETE"`, `retryable: true` and `completedStages`. Call
`import_attachment` again with exactly the same `source`, `deck_id` and `filename`; finished
stages are reused and the import continues.
