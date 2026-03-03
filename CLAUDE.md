# remarkable-mcp — Project Conventions

## What this is

MCP server for reMarkable tablet document rendering. Python 3.12+, managed with `uv`.

## Code conventions

- All Python files start with a 2-line `ABOUTME:` comment explaining what the file does
- Use `uv` for everything (`uv sync`, `uv run`, `uv add`)
- Match the style of surrounding code when editing

## Testing

TDD workflow — write tests first, then implementation.

```bash
uv run pytest tests/ -v              # all tests
uv run pytest tests/ -m unit         # unit tests
uv run pytest tests/ -m integration  # integration tests
uv run pytest tests/ -m e2e          # end-to-end tests
```

Tests use synthetic fixtures (no real reMarkable cache needed). Never use mock mode — always real data/APIs.

## Key files

- `server.py` — MCP entry point, 6 tools
- `remarkable_client.py` — rendering pipeline (rmc → SVG → cairosvg → PDF → pypdf merge)
- `tests/conftest.py` — shared fixtures with synthetic cache
