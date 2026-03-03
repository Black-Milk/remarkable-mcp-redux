# remarkable-mcp

An MCP server that gives Claude direct access to your reMarkable tablet's notebooks. Search documents, render handwritten pages to PDF, and let Claude transcribe your handwriting or convert hand-drawn diagrams into editable formats — all from your local machine, no API keys required.

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
git clone https://github.com/sambt94/remarkable-mcp.git
cd remarkable-mcp
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
        "export DYLD_LIBRARY_PATH=/opt/homebrew/lib; exec uv --directory '/path/to/remarkable-mcp' run server.py"
      ]
    }
  }
}
```

Replace `/path/to/remarkable-mcp` with the actual path to your cloned repo.

The `DYLD_LIBRARY_PATH` is needed so Python can find the Homebrew-installed cairo library on macOS.

## Tools

The server exposes 6 tools:

| Tool | Description |
|------|-------------|
| `remarkable_check_status` | Diagnostics — cache exists? rmc available? cairo available? |
| `remarkable_list_documents` | Search/list documents in the cache (optional substring filter) |
| `remarkable_get_document_info` | Detailed metadata for a document (page count, page IDs, format) |
| `remarkable_render_pages` | Render selected pages to a single PDF |
| `remarkable_render_document` | Render all pages of a document to PDF |
| `remarkable_cleanup_renders` | Remove temporary rendered PDFs |

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

Priority: `page_indices` > `last_n` > `first_n` > all pages.

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
remarkable-mcp/
├── server.py                 # MCP server entry point (FastMCP, stdio transport)
├── remarkable_client.py      # Client library (cache reading, rendering pipeline)
├── skills/
│   ├── remarkable-transcribe.md   # Handwriting → Markdown skill
│   └── remarkable-diagram.md      # Diagram → Excalidraw skill
└── tests/
    ├── conftest.py           # Synthetic cache fixtures
    ├── test_remarkable_client.py  # Unit tests
    ├── test_server.py        # Integration tests
    └── test_e2e.py           # End-to-end stdio tests
```

The rendering pipeline:

1. **rmc** parses reMarkable's proprietary `.rm` binary format (v6) into SVG
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
