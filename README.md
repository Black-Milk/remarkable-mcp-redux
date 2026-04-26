# remarkable-mcp-redux

An MCP server that gives Claude direct access to your reMarkable tablet's notebooks. Search documents, render handwritten pages to PDF, and let Claude transcribe your handwriting or convert hand-drawn diagrams into editable formats — all from your local machine, no API keys required.

## About this fork

This is a fork of [SamMorrowDrums/remarkable-mcp](https://github.com/SamMorrowDrums/remarkable-mcp). The core idea and rendering pipeline originate there. This fork reorganises the project into a proper Python package (`remarkable_mcp_redux`) and adds:

- **Pydantic schema validation** at the cache boundary — `.metadata` and `.content` JSON is parsed and validated into typed models, with ISO-8601 timestamp normalisation and discriminated unions for document vs. folder types.
- **Enriched document metadata** — responses include `file_type`, `document_title`, `authors`, `tags`, `annotated`, `original_page_count`, and `size_in_bytes` sourced from `.content`.
- **Folder listing** — `remarkable_list_folders` exposes `CollectionType` records; `remarkable_list_documents` now correctly excludes them.
- **Filtering** — `remarkable_list_documents` accepts `file_type` and `tag` query parameters.
- **Robust render error handling** — non-zero `rmc` exit codes surface as per-page failures in the response rather than being swallowed.
- **Opt-in write-back tools** — `remarkable_rename_document` and `remarkable_move_document`, guarded behind `REMARKABLE_ENABLE_WRITE_TOOLS=true`, with `dry_run` support, atomic writes, and timestamped backups.
- **Expanded test suite** — 66 tests across unit, integration, and e2e layers using entirely synthetic fixtures.

## How it works

The reMarkable desktop app syncs your notebooks to a local cache. This MCP server reads that cache and exposes it as tools that Claude can use directly.

```
reMarkable tablet
    → reMarkable desktop app (cloud sync)
    → Local cache (~/.../remarkable/desktop)
    → remarkable-mcp (rmc → SVG → cairosvg → PDF)
    → Claude reads the PDF
    → Clean Markdown, Excalidraw diagrams, or whatever you need
```

**No API keys. No cloud access. Everything runs locally.** The desktop app handles syncing; this server just reads the files it produces.

## Prerequisites

- **reMarkable desktop app** — installed and synced ([download](https://remarkable.com/desktop))
- **macOS** — the server reads from the standard macOS cache path (Linux support is possible but untested)
- **Python 3.12+**
- **uv** — Python package manager ([install](https://docs.astral.sh/uv/))
- **cairo** — system graphics library for SVG→PDF rendering:
  ```bash
  brew install cairo
  ```

## Installation

```bash
git clone https://github.com/<your-username>/remarkable-mcp-redux.git
cd remarkable-mcp-redux
uv sync
```

## MCP Registration

Add the server to your Claude Code MCP configuration. See `mcp.example.json` for the full template, or add this to your `.mcp.json`:

```json
{
  "mcpServers": {
    "remarkable": {
      "type": "stdio",
      "command": "/bin/bash",
      "args": [
        "-c",
        "cd '/path/to/remarkable-mcp-redux' && exec uv run remarkable-mcp"
      ]
    }
  }
}
```

Replace `/path/to/remarkable-mcp-redux` with the actual path to your cloned repo.

`uv run remarkable-mcp` invokes the `remarkable-mcp` script entry point declared in
`pyproject.toml`. The server sets `DYLD_LIBRARY_PATH=/opt/homebrew/lib` automatically
at startup (via `config.ensure_cairo_library_path()`), so no manual export is needed.

## Tools

### Read-only tools (always registered)

| Tool | Description |
|------|-------------|
| `remarkable_check_status` | Diagnostics — cache exists? rmc available? cairo available? |
| `remarkable_list_documents` | List documents (folders excluded) with optional `search`, `file_type`, and `tag` filters |
| `remarkable_list_folders` | List folder records (`CollectionType`) with their parent ids |
| `remarkable_get_document_info` | Detailed metadata for a document (rejects folders) |
| `remarkable_render_pages` | Render selected pages to a single PDF |
| `remarkable_render_document` | Render all pages of a document to PDF |
| `remarkable_cleanup_renders` | Remove temporary rendered PDFs |

Document responses are enriched from `.content` with `file_type`, `document_title`,
`authors`, `tags`, `annotated`, `original_page_count`, and `size_in_bytes`. Timestamps
(`last_modified`) are normalized to ISO-8601.

### Write-back tools (opt-in)

| Tool | Description |
|------|-------------|
| `remarkable_rename_document` | Update a document's `visibleName` |
| `remarkable_move_document` | Update a document's `parent` (must be `""` or an existing folder) |

These tools mutate the local cache and are **disabled by default**. Enable them by
setting `REMARKABLE_ENABLE_WRITE_TOOLS=true` in the server's environment.

Safety guarantees:

- Both tools accept `dry_run=true` to preview without writing.
- Every successful write creates a timestamped `<doc_id>.metadata.bak.<UTC>` backup
  next to the original before mutation.
- Writes go through a same-directory temp file plus `os.replace`, so a crash mid-write
  cannot leave the cache in a half-written state.
- Targets are validated: rename refuses folders and empty names; move requires
  `""` (root) or an existing `CollectionType` folder id.
- **Pause reMarkable desktop sync** before invoking write tools to avoid racing
  with the desktop app's own writes.

### Page selection

`remarkable_render_pages` supports flexible page selection:

```python
# Last 5 pages of a document
remarkable_render_pages(doc_id="<uuid>", last_n=5)

# First 3 pages
remarkable_render_pages(doc_id="<uuid>", first_n=3)

# Specific pages (0-indexed)
remarkable_render_pages(doc_id="<uuid>", page_indices=[0, 2, 4])

# All pages (no selection args)
remarkable_render_pages(doc_id="<uuid>")
```

Priority: `page_indices` > `last_n` > `first_n` > all pages. An empty
`page_indices=[]` is rejected explicitly.

## Usage with Claude

Once registered, Claude can access your reMarkable notebooks directly:

> "Transcribe the last 3 pages of my journal"

> "Find my notebook called 'Architecture Notes' and render page 5"

> "What documents do I have on my reMarkable?"

The rendered PDFs are saved to `/tmp/remarkable-renders/` and can be cleaned up with `remarkable_cleanup_renders`.

## Companion Skills

The `skills/` directory contains Claude Code skill definitions that wrap the MCP tools into complete workflows:

- **`remarkable-transcribe.md`** — Transcribe handwritten notes to clean Markdown
- **`remarkable-diagram.md`** — Convert hand-drawn diagrams to interactive Excalidraw files

To use these, copy the skill files into your `~/.claude/skills/` directory (or symlink them).

## Architecture

```
remarkable-mcp-redux/
├── remarkable_mcp_redux/           # Package
│   ├── __init__.py
│   ├── config.py                   # Default paths, env-flag helpers, Cairo path setup
│   ├── schemas.py                  # Pydantic models for .metadata and .content JSON
│   ├── cache.py                    # Read-only cache loader (parses raw JSON via schemas)
│   ├── render.py                   # rmc → SVG → cairosvg → PDF pipeline
│   ├── writes.py                   # Atomic, backup-protected metadata writes
│   ├── client.py                   # RemarkableClient facade
│   ├── tools.py                    # MCP tool registration (read + opt-in write)
│   └── server.py                   # FastMCP entry point + build_server()
├── skills/
│   ├── remarkable-transcribe.md    # Handwriting → Markdown skill
│   └── remarkable-diagram.md       # Diagram → Excalidraw skill
└── tests/
    ├── conftest.py                 # Synthetic cache fixtures (docs + folders + iOS-style)
    ├── test_remarkable_client.py   # Unit tests
    ├── test_server.py              # Integration / write-tool gating tests
    └── test_e2e.py                 # End-to-end stdio tests
```

The rendering pipeline:

1. **rmc** parses reMarkable's proprietary `.rm` binary format (v6) into SVG. Non-zero
   `rmc` exit codes now surface as failed pages in the response.
2. **cairosvg** converts SVG to PDF
3. **pypdf** merges per-page PDFs into a single document
4. Claude reads the PDF and does whatever you need — transcription, diagram interpretation, summarization

## Tests

```bash
# All tests
uv run pytest tests/ -v

# By category
uv run pytest tests/ -m unit          # unit tests (synthetic cache)
uv run pytest tests/ -m integration   # tool registration and response shapes
uv run pytest tests/ -m e2e           # full stdio transport
```

Tests use synthetic fixtures — no real reMarkable device or cache required.

## License

MIT — see [LICENSE](LICENSE).
