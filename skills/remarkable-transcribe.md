---
name: remarkable-transcribe
description: Transcribes handwritten reMarkable notebook pages to clean Markdown. Uses MCP tools to search, render, and manage reMarkable documents from the local cache, then Claude reads and transcribes the handwriting.
---

# reMarkable Handwriting Transcription

## When This Skill Activates

Claude uses this skill when:
- The user asks to transcribe a reMarkable notebook or journal entry
- The user mentions handwritten notes that need to be digitized
- The user wants to import reMarkable content into their local files
- The user asks "what's in my reMarkable?" or "grab my latest notes"

## Prerequisites

The following must be available on the system:
- **reMarkable desktop app** synced (files cached locally)
- **remarkable MCP server** registered in `.mcp.json`
- **cairo** system library via Homebrew (`brew install cairo`)

## How It Works

### Pipeline
```
reMarkable cloud → Desktop app sync → Local .rm files (v6)
    → remarkable MCP tools (rmc → SVG → cairosvg → PDF)
    → Claude reads PDF → Clean Markdown output
```

## Step-by-Step Process

### 1. Check System Status

First verify the reMarkable cache and tools are available:
```
remarkable_check_status()
```
If `cache_exists` is false, the reMarkable desktop app needs to be synced.

### 2. Find the Document

Search for documents by name:
```
remarkable_list_documents(search="journal")
```
This returns document IDs, names, page counts, and timestamps.

For more detail on a specific document:
```
remarkable_get_document_info(doc_id="<uuid>")
```

### 3. Render Pages to PDF

Render specific pages — only the selected pages go through the rendering pipeline:
```
remarkable_render_pages(doc_id="<uuid>", last_n=5)
remarkable_render_pages(doc_id="<uuid>", first_n=3)
remarkable_render_pages(doc_id="<uuid>", page_indices=[0, 2, 4])
```

Or render the entire document:
```
remarkable_render_document(doc_id="<uuid>")
```

### 4. Read and Transcribe

Read the rendered PDF (from the `pdf_path` in the response), then transcribe the handwriting to clean Markdown.

### 5. Clean Up

After transcription is complete, remove the temporary PDFs:
```
remarkable_cleanup_renders()
```

### 6. Save Output

Save the transcribed Markdown to the appropriate location. Always ask the user where to save if the destination isn't obvious.

## Output Format

### For Journal Entries
```markdown
---
tags: [log, remarkable]
date: YYYY-MM-DD
source: remarkable/Journal
---

# Journal - [Date]

[Transcribed content organized with headers and bullet points as appropriate]
```

### For General Notes
```markdown
---
tags: [reference, remarkable]
source: remarkable/[Document Name]
---

# [Document Name]

[Transcribed content]
```

## Important Notes

- The `rmc` tool may emit warnings about unread data — these are safe to ignore
- Page order comes from the `.content` file's `cPages.pages` array (v2 format)
- Empty pages (no .rm file) are skipped automatically and listed in `pages_failed`
- Always ask the user where to save the output if the destination isn't obvious
