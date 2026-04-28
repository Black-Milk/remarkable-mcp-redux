# remarkable-mcp — Project Conventions

## What this is

MCP server for reMarkable tablet document rendering and (opt-in) metadata
mutation. Python 3.13+, managed with `uv`, exposes 15 tools over FastMCP stdio.

## Architecture

Three layers, top to bottom:

- **`tools/`** — FastMCP tool registrations. Each module (`read.py`, `render.py`,
  `write.py`) is a thin wrapper that pulls `title` + `annotations` from
  `annotations.py`, declares `output_schema=Model.model_json_schema()`, applies
  `@tool_error_boundary`, and calls a facade. No domain logic lives here.
- **`facades/`** — Per-domain orchestration. `DocumentsFacade`, `FoldersFacade`,
  `RenderFacade`, `StatusFacade`, `WritesFacade`. Facades validate inputs,
  raise typed `RemarkableError` subclasses on failure, and return Pydantic
  models from `responses.py` on success.
- **`core/`** — Low-level mechanisms with no MCP awareness: cache loading
  (`cache.py`), rendering pipeline (`render.py`), atomic metadata writes
  (`writes.py`), `.rm` format probing (`rm_format.py`), single-page PDF
  extraction (`pdf_passthrough.py`), and the typed `PageSource` union
  (`page_sources.py`).

The composition root is `client.py`; it owns one `RemarkableCache` and one
`RemarkableRenderer` and hands them to the facades. `server.py` builds the
FastMCP app and registers tools via `tools/__init__.py::register_tools`.

For the long-form architectural rationale see [`docs/architecture.md`](docs/architecture.md).

## Code conventions

- Every `.py` file starts with a **module docstring** (PEP 257) — a one-line
  summary, optionally followed by a blank line and an extended description.
  This populates `__doc__`, surfaces in IDE hover, and is checked by Ruff's
  `D100` rule. Do not use `# ABOUTME:` comments — they're invisible to tooling.
- Use `uv` for everything (`uv sync`, `uv run`, `uv add`).
- Match the style of surrounding code when editing.
- Tool registrations live under `tools/<domain>.py`. Each one pulls `title` and
  `annotations` from `annotations.py` (single source of truth for the registry)
  and exposes `output_schema=<ResponseModel>.model_json_schema()`.

## Response & error contract

- Facades **return** Pydantic models defined in `responses.py` on success. The
  base class `_BaseResponse` overrides `model_dump` to default
  `exclude_unset=True` so unset optional fields drop off the wire — keeps
  responses sparse without per-tool boilerplate.
- Facades **raise** typed exceptions from `exceptions.py` on failure
  (`NotFoundError`, `KindMismatchError`, `ValidationError`, `TrashedRecordError`,
  `ConflictError`, `BackupMissingError`). Never return `{"error": True, ...}`
  dicts from facade methods — that pattern was retired in Phase 4.
- `@tool_error_boundary` (in `tools/_boundary.py`) catches `RemarkableError` at
  the MCP boundary and serializes it as a `ToolError` envelope with `error`,
  `detail`, and `code`. Generic `Exception` subclasses are *not* caught — they
  represent bugs and should surface as MCP server-level failures.

## Testing

TDD workflow — write tests first, then implementation.

```bash
uv run pytest tests/ -v              # all tests
uv run pytest tests/ -m unit         # unit tests
uv run pytest tests/ -m integration  # integration tests
uv run pytest tests/ -m e2e          # end-to-end tests
```

Tests use synthetic fixtures (no real reMarkable cache needed). Never use mock
mode — always real data/APIs. Per-domain test files mirror the facade layout:
`test_documents.py`, `test_folders.py`, `test_writes.py`, `test_render.py`,
`test_cache.py`. Contract tests for the cross-cutting layers live in
`test_annotations.py`, `test_responses.py`, `test_exceptions.py`.

## Key files

- `client.py` — composition root (cache + renderer + facades)
- `server.py` — FastMCP entry point + `build_server()`
- `annotations.py` — registry of `title` + `ToolAnnotations` for all 15 tools
- `responses.py` — Pydantic response models + `_BaseResponse` (sparse `model_dump`)
- `exceptions.py` — typed `RemarkableError` hierarchy
- `tools/_boundary.py` — `@tool_error_boundary` decorator
- `core/render.py` — rendering pipeline (rmc → SVG → cairosvg → PDF → pypdf merge)
- `tests/conftest.py` — shared fixtures with synthetic cache
