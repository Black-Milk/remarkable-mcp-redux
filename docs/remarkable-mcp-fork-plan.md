# remarkable-mcp — Fork Planning Document

*Schema Reference · Bug Catalogue · Claude Opus Integration Plan*
*April 2026*

---

## Contents

1. [Overview and Goals](#1-overview-and-goals)
2. [Current Architecture](#2-current-architecture)
3. [The .metadata JSON Schema](#3-the-metadata-json-schema)
4. [The .content File Schema](#4-the-content-file-schema)
5. [Representative Examples](#5-representative-examples)
6. [Folder Hierarchy Model](#6-folder-hierarchy-model)
7. [Bug Catalogue](#7-bug-catalogue)
8. [Implementation Plan](#8-implementation-plan)
9. [New Tool Specifications](#9-new-tool-specifications)
10. [Safety Considerations](#10-safety-considerations)
11. [Quick Reference](#11-quick-reference)

---

## 1. Overview and Goals

The remarkable-mcp project is an MCP (Model Context Protocol) server that exposes a reMarkable tablet's local document cache as a set of tools callable by an AI assistant. The server reads the sync cache produced by the reMarkable desktop application, renders handwritten pages through a `rmc → SVG → cairosvg → PDF` pipeline, and returns the rendered PDF paths for the AI to read.

This document serves three purposes:

- Provide a complete, ground-truth reference for the `.metadata` and `.content` JSON schemas as observed in a live cache.
- Catalogue all known defects in the upstream repository (`sambt94/remarkable-mcp`) that should be corrected in a fork.
- Lay out a detailed implementation plan for extending the server to support document renaming, folder organisation, and full conversational access via Claude Opus.

### 1.1 The Conversation Goal

The target end state is a user opening Claude (configured with the `claude-opus-4-6` model) and asking questions such as:

```
"What are the key ideas in my notes on spectral graph theory?"
"Rename all papers with arXiv IDs to proper author-year format."
"Move all my machine learning papers into the ML folder."
"Show me everything tagged Model Calibration."
"Summarise the last three pages of my journal from this week."
```

Achieving this requires: (a) bug-free document enumeration, (b) correct folder-hierarchy awareness, (c) `.content` fields exposed to Claude, (d) write-back tools for renaming and moving, and (e) correct MCP server registration with Claude.

---

## 2. Current Architecture

### 2.1 Component Map

```
remarkable-mcp/
├── server.py                 # FastMCP entry point — 6 tools, stdio transport
├── remarkable_client.py      # All domain logic — reads cache, renders PDFs
├── skills/
│   ├── remarkable-transcribe.md   # Skill: handwriting → Markdown
│   └── remarkable-diagram.md      # Skill: diagram → Excalidraw
└── tests/
    ├── conftest.py           # Synthetic cache fixtures
    ├── test_remarkable_client.py
    ├── test_server.py
    └── test_e2e.py
```

### 2.2 Rendering Pipeline

Every page render is a strict linear composition of four steps:

| Step | Tool | Input | Output | Failure Mode |
|------|------|-------|--------|--------------|
| 1 | `rmc` (subprocess) | `.rm` binary file | SVG file on disk | Non-zero exit; empty/missing SVG |
| 2 | `cairosvg` | SVG file path | PDF bytes in memory | Cairo library not found; malformed SVG |
| 3 | `pypdf PdfReader` | PDF bytes (BytesIO) | Page objects | Corrupted PDF bytes |
| 4 | `pypdf PdfWriter` | Accumulated pages | Merged PDF file | Disk full; permission error |

Failure is handled at the per-page level: a failed page is recorded in `pages_failed` and rendering continues. The absence of a return-code check on `rmc` (Bug #3) creates a silent corruption risk.

### 2.3 Cache Location

The `RemarkableClient` reads from a fixed base path set as `DEFAULT_BASE_PATH` in `remarkable_client.py`. The path varies by platform:

**macOS (the only officially supported platform)**

```
~/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop
```

This is the sync cache written by the reMarkable desktop application. Every document in your reMarkable account — once synced — is represented here as a cluster of files sharing a common UUID stem:

| File | Purpose |
|------|---------|
| `{uuid}.metadata` | Display name, parent folder, timestamps, sync flags |
| `{uuid}.content` | Document type, page index, tags, embedded title/authors |
| `{uuid}/` | Directory containing one `{page_uuid}.rm` binary per page |

The `.metadata` and `.content` files are JSON; the `.rm` files are reMarkable's proprietary binary stroke format (parsed by `rmc`).

**Linux**

The equivalent path on Linux has not been officially tested by the upstream author, but the desktop application follows a standard XDG layout. A likely candidate is:

```
~/.local/share/remarkable/desktop
```

**Overriding the path**

`RemarkableClient` accepts a `base_path` constructor argument, making it straightforward to point the server at an alternative location — useful for testing against a synthetic fixture cache or a non-standard installation:

```python
client = RemarkableClient(base_path=Path("/path/to/custom/cache"))
```

The `check_status()` tool reports the active `cache_path` at runtime, so the effective path is always inspectable without reading source code.

> **NOTE:** The cache is owned and written by the reMarkable desktop app. It should be treated as the app's data, not as a general-purpose document store. Always pause sync before performing bulk write-back operations (see Section 10).

### 2.4 The Six Exposed Tools

| Tool | Purpose | Write? |
|------|---------|--------|
| `remarkable_check_status` | Diagnostics: cache path, doc count, rmc/cairo availability | No |
| `remarkable_list_documents` | List/search documents (optional substring filter on `visibleName`) | No |
| `remarkable_get_document_info` | Metadata + page IDs for a single document | No |
| `remarkable_render_pages` | Render selected pages to a single PDF; supports `page_indices`, `last_n`, `first_n` | No |
| `remarkable_render_document` | Convenience: render all pages (delegates to `render_pages`) | No |
| `remarkable_cleanup_renders` | Delete all files from `/tmp/remarkable-renders/` | Yes (temp dir only) |

> **WARNING:** The server is entirely read-only with respect to the document cache. No tool currently reads `.content` files or writes to any `.metadata` file.

---

## 3. The .metadata JSON Schema

Every item in the reMarkable cache — whether a notebook, an imported PDF, or a folder — is represented by a `UUID.metadata` file. The schema has two variants, distinguished by the `type` field.

### 3.1 The `type` Discriminant

| Value | Meaning |
|-------|---------|
| `"CollectionType"` | A folder or collection. Has no `.content` or `.rm` page files. Rendered page count is always zero. |
| `"DocumentType"` | An actual document: a handwritten notebook, imported PDF, or annotated file. Has an associated `.content` file and one `.rm` file per page. |

The upstream code never filters on this field in `list_documents()` or `check_status()`, causing folders to be silently intermixed with documents in all listings. See BUG-01 and BUG-02.

### 3.2 CollectionType Schema

Observed in all 38 folder entries in the live cache. All fields below are present in every `CollectionType` record.

| Field | Type | Example Value | Notes |
|-------|------|---------------|-------|
| `type` | string | `"CollectionType"` | Discriminant. Always this exact string for folders. |
| `visibleName` | string | `"Python Books"` | The folder name displayed in the reMarkable UI. This is what `rename` writes. |
| `parent` | string | `"7f00de28-e615…"` | UUID of the parent `CollectionType`, or `""` (empty string) for root-level folders. |
| `deleted` | boolean | `false` | Soft-delete flag. Always `false` in observed cache. |
| `lastModified` | string | `"1620677002436"` | Unix epoch in milliseconds, stored as a decimal string — **not a number**. Must be parsed with `int()` for date arithmetic. |
| `metadatamodified` | boolean | `false` | Set to `true` by client software when local metadata has been changed but not yet synced. **Must be set `true` when writing renames.** |
| `modified` | boolean | `false` | Set to `true` when document content has changed locally. **Must be set `true` on any write-back.** |
| `pinned` | boolean | `false` | Whether the item is pinned to the top of the UI. Writable. |
| `synced` | boolean | `true` | Whether the item's current state has been confirmed synced to reMarkable Cloud. |
| `version` | integer | `2` | Internal version counter. Incremented by the sync engine. Do not write this field manually. |

### 3.3 DocumentType Schema

Fields marked *(may be absent)* are missing from some records, particularly older items or those transferred from iOS.

| Field | Type | Example Value | Notes |
|-------|------|---------------|-------|
| `type` | string | `"DocumentType"` | Discriminant. |
| `visibleName` | string | `"Mastering_CatBoost…"` | Display name. The target of any rename operation. |
| `parent` | string | `"7f00de28-e615…"` or `""` | Parent folder UUID, or `""` for root. The target of any move operation. |
| `createdTime` | string | `"1775836891322"` | Unix epoch ms as string. Present on newer documents; absent on older ones. |
| `lastModified` | string | `"1777153383602"` | Unix epoch ms as string. Always present. |
| `lastOpened` | string | `"1776864712321"` or `"0"` | `"0"` means never opened. Present on most records. |
| `lastOpenedPage` | integer | `67` | Zero-indexed page last viewed. Useful for resuming reading context. |
| `new` | boolean | `false` | Whether the document has not yet been opened. Present on most records. |
| `pinned` | boolean | `false` | UI pin flag. |
| `source` | string | `"com.remarkable.ios"` or `""` | The client that created this record. Empty string for device/desktop-native. *(may be absent)* |
| `deleted` | boolean | `false` | Soft-delete flag. *(may be absent)* — treat absence as `false`. |
| `metadatamodified` | boolean | `false` | *(may be absent)* — treat absence as `false`. Must be set `true` on write-back. |
| `modified` | boolean | `false` | *(may be absent)* — treat absence as `false`. Must be set `true` on write-back. |
| `synced` | boolean | `false` | *(may be absent)* — treat absence as `false`. |
| `version` | integer | `0` | *(may be absent)* — do not write manually. |

### 3.4 Timestamp Format

> **WARNING:** Both `lastModified` and `createdTime` are Unix epoch milliseconds stored as **decimal strings**, not numbers. Always parse with `int()` before comparison or arithmetic.

```python
from datetime import datetime, timezone

ts_ms = int(meta['lastModified'])          # '1777153383602' → 1777153383602
dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
# → datetime(2026, 4, 23, 18, 49, 43, tzinfo=timezone.utc)
```

---

## 4. The .content File Schema

Every `DocumentType` entry has a sibling `UUID.content` file. The upstream `remarkable_client.py` reads `.content` files **only** to extract page IDs — it ignores every other field entirely. This section documents what is being missed.

The live cache contains **907** `.content` files.

### 4.1 `fileType` — The Document-Type Discriminant

This is the field that `.metadata` entirely lacks. It distinguishes handwritten notebooks from imported files:

| Value | Count in cache | Meaning |
|-------|---------------|---------|
| `"pdf"` | 857 | Imported PDF (papers, textbooks, scanned documents) |
| `"notebook"` | 37 | Native handwritten notebook created on device |
| `"epub"` | 11 | Imported EPUB |

A `"notebook"` document's `.rm` files contain only stroke data. A `"pdf"` document's `.rm` files contain only the *annotations* made on top of the underlying PDF — the original PDF pages are stored separately. This distinction matters for rendering: `rmc` renders the stroke layer only, so for a PDF the rendered output is just the handwritten annotations, not the original printed content.

### 4.2 `documentMetadata` — Embedded Title and Authors

For PDFs and EPUBs whose source files carry XMP or PDF metadata, the reMarkable app populates this field automatically at import time:

```json
"documentMetadata": {
    "title":   "Ensemble Methods in Data Mining",
    "authors": ["Giovanni Seni, John Elder"]
}
```

**451 of the 907 documents** (roughly half) have a populated `documentMetadata`. For notebooks and PDFs lacking embedded metadata, it is present but empty (`{}`).

This field has a major implication for the rename workflow: for those 451 documents, Claude can read the proper title directly from JSON without rendering a single page. Rendering is only necessary for documents where `documentMetadata.title` is absent — typically bare arXiv papers or scanned documents.

### 4.3 `tags` — User-Applied Semantic Labels

Documents can be tagged in the reMarkable UI. The `tags` field is a list of objects:

```json
"tags": [
    { "name": "Model Calibration", "timestamp": 1715582145953 }
]
```

Tags observed in the live cache include: `"IR"`, `"ML - Fundamentals"`, `"Model Calibration"`, `"Tree Models"`, `"Ensemble ML"`, `"Neural Fusion"`, `"AI - RL Foundations"`, `"Legal - Advice"`. The upstream server does not expose tags in any tool, so Claude currently has no access to this categorisation system.

`pageTags` follows the same structure but applies to individual pages rather than the whole document.

### 4.4 `extraMetadata` — Pen Tool History and Annotation Signal

For native notebooks, this field carries the full history of the last-used pen tool, colours, and sizes:

```json
"extraMetadata": {
    "LastTool":             "SharpPencilv2",
    "LastPen":              "SharpPencilv2",
    "LastFinelinerv2Color": "Black",
    "LastFinelinerv2Size":  "2",
    ...
}
```

For imported PDFs and EPUBs, `extraMetadata` is empty (`{}`) **unless the document has been annotated**, in which case pen-tool entries are populated. A non-empty `extraMetadata` on a `"pdf"` document is therefore a reliable signal that the user has made handwritten annotations on top of the imported file — a useful distinction for workflows that want to find annotated papers specifically.

### 4.5 Page Count Fields

| Field | Notebooks | PDFs/EPUBs | Notes |
|-------|-----------|-----------|-------|
| `pageCount` | Total pages | Total reMarkable pages | Includes any blank pages inserted between original pages. |
| `originalPageCount` | `-1` | Page count of source file | Diverges from `pageCount` if pages have been inserted. |

### 4.6 `formatVersion` and Page Index Format

| `formatVersion` | Count | Page index field |
|---|---|---|
| `1` | 793 | `"pages": ["uuid", "uuid", …]` — flat array of UUID strings |
| `2` | 100 | `"cPages": { "pages": [ { "id": "uuid", "idx": …, "redir": … } ] }` — structured |
| absent | 42 | Older documents; treat as v1 if `"pages"` key is present |

The v2 `cPages` format carries additional per-page metadata: `idx` (a lexicographic sort key used for page ordering) and `redir` (the corresponding page index in the original PDF). The `redirectionPageMap` top-level field in v1 documents serves the same purpose.

### 4.7 Complete Field Inventory

All fields observed across 907 `.content` files, with presence counts:

| Field | Present in | Notes |
|-------|-----------|-------|
| `coverPageNumber` | 907 | `-1` (no cover) or `0` (first page is cover). |
| `documentMetadata` | 907 | Always present; populated in 451. See §4.2. |
| `extraMetadata` | 907 | Always present; non-empty for notebooks and annotated PDFs. See §4.4. |
| `fileType` | 907 | `"pdf"` / `"notebook"` / `"epub"`. See §4.1. |
| `fontName` | 907 | Typography setting for EPUBs; empty string for PDFs and notebooks. |
| `lineHeight` | 907 | EPUB line-height setting; `-1` for PDFs and notebooks. |
| `orientation` | 907 | `"portrait"` or `"landscape"`. |
| `pageCount` | 907 | See §4.5. |
| `textAlignment` | 907 | `"justify"`, `"left"`, etc. Relevant for EPUBs. |
| `textScale` | 907 | Typography zoom for EPUBs; `1` otherwise. |
| `sizeInBytes` | 894 | Size of the original imported file as a string. `"0"` or `""` for notebooks. |
| `formatVersion` | 865 | See §4.6. |
| `tags` | 854 | User-applied labels. See §4.3. |
| `pageTags` | 839 | Per-page labels. |
| `pages` | 808 | v1 page index (flat UUID list). |
| `originalPageCount` | 795 | See §4.5. `-1` for notebooks. |
| `customZoomCenterX/Y` | 792 | Last zoom/pan state; display-only. |
| `customZoomOrientation` | 792 | Display orientation at last zoom. |
| `customZoomPageHeight/Width` | 792 | Page dimensions at last zoom (points). |
| `customZoomScale` | 792 | Last zoom scale factor. |
| `zoomMode` | 792 | `"bestFit"`, `"fitToWidth"`, etc. |
| `redirectionPageMap` | 773 | Maps reMarkable page indices → original PDF page indices. |
| `margins` | 741 | Notebook margin width in points (typically `125`). |
| `dummyDocument` | 270 | `true` for placeholder/template documents. |
| `cPages` | 100 | v2 page index (structured). See §4.6. |
| `keyboardMetadata` | 74 | Count and timestamp of keyboard (text tool) usage. |
| `transform` | 23 | Display transform matrix; present on some annotated PDFs. |

---

## 5. Representative Examples

### 5.1 CollectionType — Root-Level Folder

```json
{
    "deleted":          false,
    "lastModified":     "1615493392058",
    "metadatamodified": false,
    "modified":         false,
    "parent":           "",
    "pinned":           false,
    "synced":           true,
    "type":             "CollectionType",
    "version":          2,
    "visibleName":      "Literature"
}
```

### 5.2 CollectionType — Nested Folder

```json
{
    "deleted":          false,
    "lastModified":     "1615498922116",
    "metadatamodified": false,
    "modified":         false,
    "parent":           "7f00de28-e615-45c1-9a6f-96c4e1dbc500",
    "pinned":           false,
    "synced":           true,
    "type":             "CollectionType",
    "version":          1,
    "visibleName":      "Computation"
}
```

### 5.3 DocumentType — Pinned ArXiv Paper

A document with an arXiv ID as its visible name. It is pinned, unsynced, and was created locally (`source` is empty). A prime candidate for renaming. Its `.content` file will have `fileType: "pdf"` and likely an empty `documentMetadata` — meaning a page render is needed to identify the proper title.

```json
{
    "createdTime":      "1775836891322",
    "deleted":          false,
    "lastModified":     "1777153383602",
    "lastOpened":       "1776864712321",
    "lastOpenedPage":   0,
    "metadatamodified": false,
    "modified":         false,
    "new":              false,
    "parent":           "",
    "pinned":           true,
    "source":           "",
    "synced":           false,
    "type":             "DocumentType",
    "version":          0,
    "visibleName":      "1410.3831"
}
```

### 5.4 DocumentType — iOS Transfer with Raw Filename

Note the absence of `deleted`, `metadatamodified`, `modified`, `synced`, and `version`. These fields can be absent in iOS-sourced records; always use `.get()` with defaults.

```json
{
    "createdTime":    "1777124918411",
    "lastModified":   "1777124918407",
    "lastOpened":     "0",
    "lastOpenedPage": 0,
    "new":            false,
    "parent":         "",
    "pinned":         false,
    "source":         "com.remarkable.ios",
    "type":           "DocumentType",
    "visibleName":    "2604.13860v3"
}
```

### 5.5 DocumentType — Partially Read Document

`lastOpenedPage: 67` allows Claude to offer to resume from the last-read position.

```json
{
    "createdTime":    "1777122767643",
    "lastModified":   "1777123555911",
    "lastOpened":     "1777122822974",
    "lastOpenedPage": 67,
    "new":            false,
    "parent":         "",
    "pinned":         false,
    "source":         "com.remarkable.ios",
    "type":           "DocumentType",
    "visibleName":    "Mastering_CatBoost__The_Hidden_Gem_of_Tabular_AI"
}
```

### 5.6 .content — Native Handwritten Notebook

Note `fileType: "notebook"`, empty `documentMetadata`, populated `extraMetadata` (pen history), and `originalPageCount: -1`.

```json
{
    "documentMetadata": {},
    "extraMetadata": {
        "LastTool":              "SharpPencilv2",
        "LastPen":               "SharpPencilv2",
        "LastSharpPencilv2Size": "1",
        "LastEraserTool":        "Eraser"
    },
    "fileType":          "notebook",
    "formatVersion":     1,
    "margins":           125,
    "orientation":       "portrait",
    "originalPageCount": -1,
    "pageCount":         1,
    "pages":             ["c6d7f71e-3586-4b08-81e2-d9f3160c3491"],
    "sizeInBytes":       "2140",
    "tags":              []
}
```

### 5.7 .content — Imported PDF with Embedded Metadata and Tag

Note `fileType: "pdf"`, populated `documentMetadata` (no render needed for rename), and a user-applied `tags` entry.

```json
{
    "documentMetadata": {
        "title":   "Ensemble Methods in Data Mining: Improving Accuracy Through Combining Predictions",
        "authors": ["Giovanni Seni, John Elder"]
    },
    "extraMetadata":     {},
    "fileType":          "pdf",
    "formatVersion":     1,
    "orientation":       "portrait",
    "originalPageCount": 312,
    "pageCount":         312,
    "sizeInBytes":       "8491023",
    "tags": [
        { "name": "Ensemble ML", "timestamp": 1715582127611 }
    ]
}
```

### 5.8 .content — PDF Annotated by User

`extraMetadata` is populated despite `fileType: "pdf"`, signalling that handwritten annotations have been added on top of the original document.

```json
{
    "documentMetadata": {
        "title":   "\"AI Psychosis\" in Context: How Conversation History Shapes LLM Responses to Delusional Beliefs",
        "authors": ["Luke Nicholls; Robert Hutto; Zephrah Soto; ..."]
    },
    "extraMetadata": {
        "LastTool":           "Ballpointv2",
        "LastPen":            "Ballpointv2",
        "LastBallpointv2Size": "2"
    },
    "fileType":    "pdf",
    "pageCount":   39,
    "sizeInBytes": "1681059",
    "tags":        []
}
```

---

## 6. Folder Hierarchy Model

### 6.1 Formal Definition

Let $U$ be the set of all UUIDs appearing as filenames in the cache. Define a directed graph $G = (U, E)$ where $(u, v) \in E$ if and only if `u.parent == v` and `v` is of type `CollectionType`. Then $G$ is a forest — a disjoint union of rooted trees — where each tree's root $r$ satisfies `r.parent == ""`.

### 6.2 Observed Folder Names in This Cache

A representative sample; the full cache contains 38 folders.

| `visibleName` | UUID (abbreviated) | `parent` |
|---------------|--------------------|---------|
| Literature | `7b299aff…` | `""` (root) |
| Paperwork | `fd8db178…` | `""` (root) |
| Python Books | `7606f424…` | `""` (root) |
| Complexity | `64257e7c…` | `""` (root) |
| Grainger Notes | `b76a2bf7…` | `""` (root) |
| Computation | `d9c01f45…` | `"7f00de28…"` (nested) |

### 6.3 Write Semantics for Move Operations

To move a document `d` into folder `f`, exactly one field must be updated:

```python
meta['parent']           = f_uuid    # target folder UUID
meta['metadatamodified'] = True      # signal: local metadata changed
meta['modified']         = True      # signal: item needs sync
```

To move a document to the root level, set `parent` to the empty string `""`.

> **WARNING:** Never create a cycle. If moving a `CollectionType`, verify that the target folder UUID is not itself a descendant of the item being moved.

---

## 7. Bug Catalogue

Twelve defects have been identified in the upstream repository, listed in descending order of impact.

---

### BUG-01 — `list_documents()` mixes `CollectionType` folders with `DocumentType` documents

| | |
|---|---|
| **Severity** | High |
| **File** | `remarkable_client.py` |
| **Method** | `list_documents()` |
| **Description** | The method iterates all `*.metadata` files without checking the `type` field. All 38 `CollectionType` (folder) records appear as documents with `page_count: 0`. Claude cannot distinguish a folder from a notebook. |
| **Impact** | Claude receives corrupt document listings; attempting to render a folder returns "No pages found" with no explanation. |
| **Fix** | Add a type guard immediately after loading the metadata JSON: `if meta.get("type") != "DocumentType": continue` |

---

### BUG-02 — `check_status()` document count includes `CollectionType` entries

| | |
|---|---|
| **Severity** | High |
| **File** | `remarkable_client.py` |
| **Method** | `check_status()` |
| **Description** | The document count is computed as the total number of `.metadata` files, regardless of `type`. On the observed cache, this inflates the count by 38. |
| **Impact** | Diagnostics report an incorrect document count; Claude may be misled about how many actual notebooks exist. |
| **Fix** | Count only `DocumentType` entries: `doc_count = sum(1 for f in ... if load_type(f) == 'DocumentType')` |

---

### BUG-03 — `rmc` subprocess return code is never checked

| | |
|---|---|
| **Severity** | High |
| **File** | `remarkable_client.py` |
| **Method** | `_render_single_page()` |
| **Description** | The return value of `_run_rmc()` is discarded. The code checks only whether the output SVG file exists and has non-zero size. If `rmc` exits non-zero but still writes a partial or corrupted SVG, the error is silently swallowed. |
| **Impact** | Silent render corruption. The resulting PDF may be blank or malformed with no error reported to the caller. |
| **Fix** | `result = _run_rmc([...])`<br>`if result.returncode != 0:`<br>`    raise RuntimeError(f'rmc failed (exit {result.returncode}): {result.stderr}')` |

---

### BUG-04 — `render_pages()` accepts empty `page_indices=[]` without error

| | |
|---|---|
| **Severity** | Medium |
| **File** | `remarkable_client.py` |
| **Method** | `render_pages()` / `_resolve_page_selection()` |
| **Description** | `_resolve_page_selection` returns `[]` when `page_indices=[]` is passed. The rendering loop executes zero times and the function returns `pdf_path: null`. No warning or error is raised. |
| **Impact** | Callers receive a null `pdf_path` with no indication of why the render produced nothing. |
| **Fix** | `if page_indices is not None and len(page_indices) == 0:`<br>`    return {"error": True, "detail": "page_indices must not be empty"}` |

---

### BUG-05 — `render_pages()` does not validate that `doc_id` is a `DocumentType`

| | |
|---|---|
| **Severity** | Medium |
| **File** | `remarkable_client.py` |
| **Method** | `render_pages()`, `get_document_info()` |
| **Description** | If a `CollectionType` UUID is passed, the code proceeds without checking the `type` field. `render_pages` falls through to "No pages found"; `get_document_info` returns metadata that misleadingly omits the fact that it is a folder. |
| **Impact** | Confusing error messages; Claude cannot determine whether failure is due to a corrupt document or an accidentally passed folder UUID. |
| **Fix** | After loading metadata: `if meta.get("type") != "DocumentType": return {"error": True, "detail": f"{doc_id} is a CollectionType (folder), not a document"}` |

---

### BUG-06 — No `remarkable_list_folders` tool — folder UUIDs are inaccessible

| | |
|---|---|
| **Severity** | Medium |
| **File** | `server.py` |
| **Method** | *(missing tool)* |
| **Description** | There is no tool that enumerates `CollectionType` entries and returns their UUIDs. Without this, it is impossible to implement a move operation because the target folder's UUID cannot be discovered programmatically. |
| **Impact** | The write-back architecture is entirely blocked until this tool exists. |
| **Fix** | Add `remarkable_list_folders()` to `remarkable_client.py` and register it in `server.py`. See Section 9.1 for the full specification. |

---

### BUG-07 — `DYLD_LIBRARY_PATH` is set in two places

| | |
|---|---|
| **Severity** | Low |
| **File** | `server.py`, `remarkable_client.py` |
| **Method** | module-level (`server.py`), `__init__` (`remarkable_client.py`) |
| **Description** | The `os.environ` assignment appears both at module level in `server.py` and in `RemarkableClient.__init__`. The module-level assignment already runs before any import, making the `__init__` assignment redundant. |
| **Impact** | No functional impact, but creates confusion about which assignment is authoritative. |
| **Fix** | Remove from `__init__`. Add a docstring noting that callers outside the MCP context must set `DYLD_LIBRARY_PATH` themselves. |

---

### BUG-08 — `DocumentType` schema fields are inconsistently present

| | |
|---|---|
| **Severity** | Low |
| **File** | `remarkable_client.py` |
| **Method** | All metadata-reading methods |
| **Description** | Fields `deleted`, `metadatamodified`, `modified`, `synced`, `version` are absent from iOS-sourced records. Currently harmless for read-only code, but any write-back code that sets these fields must initialise them if absent. |
| **Impact** | Low for read-only code. High risk if write-back is added without handling absent fields. |
| **Fix** | Use `.get()` with safe defaults: `meta.get('deleted', False)`, `meta.get('metadatamodified', False)`, `meta.get('synced', False)` |

---

### BUG-09 — `list_documents()` does not expose `type` or `parent` fields

| | |
|---|---|
| **Severity** | Low |
| **File** | `remarkable_client.py` |
| **Method** | `list_documents()` |
| **Description** | The returned document dict omits `type` and `parent`. Once BUG-01 is fixed, `parent` still needs to be returned so Claude knows which folder each document lives in. |
| **Impact** | Claude cannot determine a document's location in the folder hierarchy from `list_documents` alone. |
| **Fix** | `documents.append({..., "parent": meta.get("parent", ""), "type": meta.get("type")})` |

---

### BUG-10 — `lastModified` is undocumented as a millisecond string

| | |
|---|---|
| **Severity** | Low |
| **File** | `server.py` (tool docstrings), `remarkable_client.py` |
| **Method** | `list_documents()`, `get_document_info()` |
| **Description** | The `lastModified` field is returned as a raw millisecond timestamp string (e.g., `"1777153383602"`). The tool docstrings do not explain this format. |
| **Impact** | Claude may display timestamps as large integers rather than dates, degrading conversational quality. |
| **Fix** | Convert to ISO-8601 before returning, or document the format explicitly in the tool docstring. |

---

### BUG-11 — `.content` file is never read beyond page IDs — `fileType`, `documentMetadata`, and `tags` are invisible

| | |
|---|---|
| **Severity** | High |
| **File** | `remarkable_client.py` |
| **Method** | `_get_page_ids()`, `get_document_info()`, `list_documents()` |
| **Description** | `remarkable_client.py` reads `.content` files only to extract page IDs (`_get_page_ids`). It ignores `fileType`, `documentMetadata`, `tags`, `originalPageCount`, `sizeInBytes`, and `extraMetadata` entirely. Claude therefore has no way to distinguish a handwritten notebook from an imported PDF, cannot access embedded titles and authors, and cannot see any user-applied tags. |
| **Impact** | High. (1) Claude cannot tell notebooks from PDFs — it may try to transcribe a PDF's annotation layer instead of its text. (2) 451 documents in the live cache already have their proper titles embedded in `documentMetadata.title`; without reading this, every rename requires an unnecessary page render. (3) User-applied tags (`"IR"`, `"ML - Fundamentals"`, `"Model Calibration"`, etc.) are completely invisible, making tag-based queries impossible. |
| **Fix** | Add a `_get_content_info(doc_id)` helper that reads the `.content` file and returns `fileType`, `documentMetadata`, `tags`, `originalPageCount`, and `extraMetadata`. Call it from `get_document_info()` and `list_documents()`. See Section 9 for updated output schemas. |

---

### BUG-12 — `list_documents()` search only filters on `visibleName` — no tag-based filtering

| | |
|---|---|
| **Severity** | Medium |
| **File** | `remarkable_client.py`, `server.py` |
| **Method** | `list_documents()` |
| **Description** | The `search` parameter performs a case-insensitive substring match on `visibleName` only. There is no way to filter by `fileType` (e.g., "show me only notebooks"), by `tag` (e.g., "show me everything tagged Model Calibration"), or by `parent` folder. |
| **Impact** | Claude cannot answer questions like "show me all my annotated papers" or "what have I tagged as IR?" without first listing all documents and filtering manually — an expensive operation given the 907-document cache. |
| **Fix** | Add optional `tag` and `file_type` filter parameters to `list_documents()`. After reading each `.content` file for BUG-11, apply the filters before appending to the result list. See Section 9.2 for the updated specification. |

---

## 8. Implementation Plan

The fork is structured in three phases. Phases 1 and 2 are prerequisites for Phase 3.

### 8.1 Phase 1 — Bug Fixes (No New Features)

Fix all twelve bugs before adding any new functionality.

| Bug ID | Change Required | Test Required |
|--------|----------------|---------------|
| BUG-01 | Add `type != 'DocumentType'` guard in `list_documents()` | Assert folders absent from listing |
| BUG-02 | Recount in `check_status()` using type filter | Assert count equals `DocumentType` count only |
| BUG-03 | Check `returncode` in `_render_single_page()`; raise on failure | Mock `rmc` to return exit 1; assert `RuntimeError` |
| BUG-04 | Guard empty `page_indices` in `render_pages()` | Call with `page_indices=[]`; assert error dict |
| BUG-05 | Type guard in `render_pages()` and `get_document_info()` | Pass `CollectionType` UUID; assert error dict |
| BUG-07 | Remove `DYLD_LIBRARY_PATH` from `__init__` | Smoke test: `RemarkableClient()` still functions |
| BUG-08 | Use `.get()` with defaults for all optional fields | Synthetic fixture without optional fields |
| BUG-09 | Add `parent` and `type` to `list_documents()` output | Assert `parent` field present in returned dicts |
| BUG-10 | Convert `lastModified` to ISO-8601 in returned dicts | Assert returned timestamp matches expected date |
| BUG-11 | Add `_get_content_info()` helper; surface fields in `list_documents()` and `get_document_info()` | Assert `file_type`, `document_title`, `tags` present in returned dicts |
| BUG-12 | Add `tag` and `file_type` filter parameters to `list_documents()` | Call with `tag="IR"`; assert only tagged docs returned |

### 8.2 Phase 2 — Write-Back Tools

Add three new tools to enable document organisation.

| New Tool | Operation | Fields Written |
|----------|-----------|----------------|
| `remarkable_list_folders` | Return all `CollectionType` entries with UUIDs, names, and parent UUIDs. (Fixes BUG-06.) | *(read only)* |
| `remarkable_rename_document` | Update `visibleName` in `doc_id.metadata`. | `visibleName`, `metadatamodified=true`, `modified=true` |
| `remarkable_move_document` | Update `parent` in `doc_id.metadata`. Accepts `target_folder_id` or `""` for root. | `parent`, `metadatamodified=true`, `modified=true` |

> **WARNING:** Perform all writes atomically: read the full JSON, update the target field(s), and write the entire object back. Never patch individual fields in-place.

### 8.3 Phase 3 — Claude Opus Integration

**Step 1: Clone the fork and sync dependencies**

```bash
git clone https://github.com/YOUR-FORK/remarkable-mcp.git
cd remarkable-mcp
uv sync
```

**Step 2: Register in `.mcp.json`**

```json
{
  "mcpServers": {
    "remarkable": {
      "type": "stdio",
      "command": "/bin/bash",
      "args": [
        "-c",
        "export DYLD_LIBRARY_PATH=/opt/homebrew/lib; exec uv --directory '/path/to/remarkable-mcp' run server.py"
      ]
    }
  }
}
```

**Step 3: Configure Claude to use Opus**

In Claude Code, set the model to `claude-opus-4-6` via the `/model` command or the `ANTHROPIC_MODEL` environment variable.

**Step 4: Conversational Rename Workflow**

With BUG-11 fixed, the rename workflow splits into two paths depending on whether `documentMetadata` is populated. This eliminates unnecessary renders for the ~451 documents that already carry embedded titles.

| Step | Claude Action | Tool Called |
|------|--------------|-------------|
| 1 | List all documents; filter by `file_type="pdf"` to find PDF candidates | `remarkable_list_documents(file_type="pdf")` |
| 2 | Inspect `document_title` in each result | *(from list response)* |
| 3a | **If `document_title` is present:** propose rename directly from JSON | *(no render needed)* |
| 3b | **If `document_title` is absent:** render first 2 pages and read title/abstract | `remarkable_render_pages(doc_id, first_n=2)` |
| 4 | Propose the new name to the user for confirmation | *(conversation)* |
| 5 | Apply the rename on confirmation | `remarkable_rename_document(doc_id, new_name)` |
| 6 | Optionally move to the appropriate folder | `remarkable_list_folders()` → `remarkable_move_document(doc_id, folder_id)` |
| 7 | Clean up any rendered PDFs | `remarkable_cleanup_renders()` |

**Step 5: Tag-Based Queries**

With BUG-12 fixed, Claude can answer tag-based questions directly:

| User Request | Claude Action |
|---|---|
| "Show me everything tagged Model Calibration" | `remarkable_list_documents(tag="Model Calibration")` |
| "List all my handwritten notebooks" | `remarkable_list_documents(file_type="notebook")` |
| "Find all annotated papers" | `remarkable_list_documents(file_type="pdf")` then filter on non-empty `extraMetadata` |

---

## 9. New Tool Specifications

### 9.1 `remarkable_list_folders`

Returns all `CollectionType` entries. Analogous to `list_documents` but for folders.

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `search` | string | No | Case-insensitive substring filter on `visibleName`. |

**Output (success)**

```json
{
  "folders": [
    {
      "folder_id":     "7b299aff-f76f-46ce-af88-df804af17b61",
      "name":          "Literature",
      "parent":        "",
      "last_modified": "2021-03-11T22:29:52+00:00"
    },
    {
      "folder_id":     "d9c01f45-48fb-44bc-b979-5759021ecacc",
      "name":          "Computation",
      "parent":        "7f00de28-e615-45c1-9a6f-96c4e1dbc500",
      "last_modified": "2021-03-11T23:55:22+00:00"
    }
  ],
  "count": 38
}
```

---

### 9.2 Updated `remarkable_list_documents`

The existing tool gains two new filter parameters and substantially richer output fields drawn from `.content`.

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `search` | string | No | Case-insensitive substring filter on `visibleName`. |
| `file_type` | string | No | Filter to `"pdf"`, `"notebook"`, or `"epub"` only. |
| `tag` | string | No | Return only documents bearing this exact tag name. |

**Output (success) — updated fields**

```json
{
  "documents": [
    {
      "doc_id":         "03a1399b-cec1-49db-8f29-b19492d3ace4",
      "name":           "Ensemble_Methods_in_Data_Mining",
      "parent":         "",
      "last_modified":  "2021-05-04T12:22:37+00:00",
      "page_count":     312,
      "file_type":      "pdf",
      "document_title": "Ensemble Methods in Data Mining: Improving Accuracy Through Combining Predictions",
      "authors":        ["Giovanni Seni, John Elder"],
      "tags":           ["Ensemble ML"],
      "annotated":      false
    }
  ],
  "count": 1
}
```

New fields explained:

| Field | Source | Notes |
|-------|--------|-------|
| `file_type` | `.content` → `fileType` | `"pdf"`, `"notebook"`, or `"epub"` |
| `document_title` | `.content` → `documentMetadata.title` | `null` if absent |
| `authors` | `.content` → `documentMetadata.authors` | `[]` if absent |
| `tags` | `.content` → `tags[].name` | `[]` if no tags |
| `annotated` | `.content` → `extraMetadata` non-empty | `true` if user has written on the document |

---

### 9.3 Updated `remarkable_get_document_info`

The existing tool gains the same `.content`-derived fields, plus `original_page_count` and `size_in_bytes`.

**Output (success) — updated fields**

```json
{
  "doc_id":              "03a1399b-cec1-49db-8f29-b19492d3ace4",
  "name":                "Ensemble_Methods_in_Data_Mining",
  "parent":              "",
  "page_count":          312,
  "original_page_count": 312,
  "page_ids":            ["uuid1", "uuid2", "..."],
  "content_format":      "v1",
  "file_type":           "pdf",
  "document_title":      "Ensemble Methods in Data Mining",
  "authors":             ["Giovanni Seni, John Elder"],
  "tags":                ["Ensemble ML"],
  "annotated":           false,
  "size_in_bytes":       8491023,
  "last_opened_page":    0
}
```

---

### 9.4 `remarkable_rename_document`

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `doc_id` | string | Yes | UUID of the document or folder to rename. |
| `new_name` | string | Yes | The new `visibleName`. Must be non-empty. |

**Output (success)**

```json
{
  "doc_id":   "73aa8958-b963-4a05-b8d4-88ce74d3e2cb",
  "old_name": "1410.3831",
  "new_name": "Brandes 2014 — A Faster Algorithm for Betweenness Centrality"
}
```

**Python Implementation**

```python
def rename_document(self, doc_id: str, new_name: str) -> dict:
    if not new_name or not new_name.strip():
        return {"error": True, "detail": "new_name must not be empty"}
    meta_path = self.base_path / f"{doc_id}.metadata"
    if not meta_path.exists():
        return {"error": True, "detail": f"Document not found: {doc_id}"}
    with open(meta_path) as f:
        meta = json.load(f)
    old_name = meta.get("visibleName", doc_id)
    meta["visibleName"]      = new_name.strip()
    meta["metadatamodified"] = True
    meta["modified"]         = True
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=4)
    return {"doc_id": doc_id, "old_name": old_name, "new_name": new_name.strip()}
```

---

### 9.5 `remarkable_move_document`

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `doc_id` | string | Yes | UUID of the item to move. |
| `target_folder_id` | string | Yes | UUID of the destination `CollectionType`, or `""` to move to root. |

**Output (success)**

```json
{
  "doc_id":      "73aa8958-b963-4a05-b8d4-88ce74d3e2cb",
  "old_parent":  "",
  "new_parent":  "7b299aff-f76f-46ce-af88-df804af17b61",
  "folder_name": "Literature"
}
```

**Python Implementation**

```python
def move_document(self, doc_id: str, target_folder_id: str) -> dict:
    meta_path = self.base_path / f"{doc_id}.metadata"
    if not meta_path.exists():
        return {"error": True, "detail": f"Document not found: {doc_id}"}
    folder_name = "(root)"
    if target_folder_id:
        folder_path = self.base_path / f"{target_folder_id}.metadata"
        if not folder_path.exists():
            return {"error": True, "detail": f"Target folder not found: {target_folder_id}"}
        with open(folder_path) as f:
            folder_meta = json.load(f)
        if folder_meta.get("type") != "CollectionType":
            return {"error": True, "detail": f"Target is not a CollectionType: {target_folder_id}"}
        folder_name = folder_meta.get("visibleName", target_folder_id)
    with open(meta_path) as f:
        meta = json.load(f)
    old_parent = meta.get("parent", "")
    meta["parent"]           = target_folder_id
    meta["metadatamodified"] = True
    meta["modified"]         = True
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=4)
    return {
        "doc_id":      doc_id,
        "old_parent":  old_parent,
        "new_parent":  target_folder_id,
        "folder_name": folder_name,
    }
```

---

## 10. Safety Considerations

### 10.1 The Sync Engine

The reMarkable desktop application monitors the cache directory. When Claude writes to a `.metadata` file, the desktop app will detect the change and attempt to sync it to reMarkable Cloud.

- Do not write to the cache while the desktop app is actively syncing.
- The `metadatamodified` and `modified` flags must be set to `true` so the sync engine recognises the changes as intentional local edits.
- The `version` field should not be incremented manually; the sync engine manages this counter.

### 10.2 No Backup Mechanism

The upstream code has no backup or rollback mechanism. Before any write-back operation, Claude should:

- Read and log the current value of any field being overwritten.
- Return `old_name` / `old_parent` in the response dict so the user can reverse the operation manually.
- Consider adding a `remarkable_backup_metadata` tool that writes a JSON snapshot of all metadata to a timestamped file before any bulk operation.

### 10.3 Cycle Prevention in Move

Moving a `CollectionType` into one of its own descendants would create a cycle in the folder hierarchy. The `remarkable_move_document` implementation should verify that `target_folder_id` is not a descendant of `doc_id` when `doc_id` is itself a `CollectionType`.

### 10.4 Concurrent Access

> **WARNING:** Do not run the MCP server while the reMarkable desktop application is performing a sync. Pause sync in the desktop app before executing bulk rename or move operations.

---

## 11. Quick Reference

### 11.1 Full Tool Inventory (Post-Fork)

| Tool | R/W | Phase | Key Changes |
|------|-----|-------|-------------|
| `remarkable_check_status` | R | 1 | Bug fix: correct document count |
| `remarkable_list_documents` | R | 1 | Bug fixes + new `file_type`, `document_title`, `tags`, `annotated` fields; new `file_type` and `tag` filter params |
| `remarkable_get_document_info` | R | 1 | Bug fixes + new `.content`-derived fields |
| `remarkable_render_pages` | R | 1 | Bug fixes: empty indices guard, type guard |
| `remarkable_render_document` | R | 1 | No changes needed |
| `remarkable_cleanup_renders` | W | 1 | No changes needed |
| `remarkable_list_folders` | R | 2 | New |
| `remarkable_rename_document` | W | 2 | New |
| `remarkable_move_document` | W | 2 | New |

### 11.2 Field Write-Back Cheat Sheet

| Operation | Field(s) to Write | Also Set |
|-----------|-------------------|----------|
| Rename | `visibleName = new_name` | `metadatamodified = true`, `modified = true` |
| Move to folder | `parent = target_folder_uuid` | `metadatamodified = true`, `modified = true` |
| Move to root | `parent = ""` | `metadatamodified = true`, `modified = true` |
| Pin/unpin | `pinned = true/false` | `metadatamodified = true`, `modified = true` |

### 11.3 Document-Type Decision Tree

```
Read UUID.content → fileType?
    "notebook"  → handwritten notes; extraMetadata has pen history
    "pdf"       → imported PDF
        extraMetadata non-empty? → user has annotated this PDF
        documentMetadata.title present? → use for rename directly (no render needed)
        documentMetadata empty? → render first_n=2 pages to identify
    "epub"      → imported EPUB; fontName/lineHeight/textScale are relevant
```

### 11.4 Timestamp Conversion

```python
from datetime import datetime, timezone

def ms_to_iso(ms_string: str) -> str:
    """Convert a reMarkable millisecond timestamp string to ISO-8601."""
    return datetime.fromtimestamp(
        int(ms_string) / 1000,
        tz=timezone.utc
    ).isoformat()

# Example:
ms_to_iso("1777153383602")  # → "2026-04-23T18:49:43+00:00"
```
