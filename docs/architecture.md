# Architecture

This document describes the internal structure of `remarkable_mcp_redux` —
how the package is layered, what contracts each layer owns, and the rationale
behind the split. If you only want to *use* the server, the top-level
[`README.md`](../README.md) covers that. This file is for people reading,
extending, or porting the code.

## Why this exists

`remarkable_mcp_redux` exposes a 15-tool surface over the local reMarkable
desktop cache, with opt-in writes, atomic backups, typed schemas, and a
Pydantic-validated cache loader. As the surface area grew, the code went
through an architectural redux to keep it maintainable:

- **Phase 0** introduced the `core/` / `facades/` / `tools/` layering to
  separate mechanism from policy from MCP wiring.
- **Phase 1** split the monolithic test file into per-domain modules and
  privatised internal client attributes.
- **Phase 2** added `ToolAnnotations` + descriptive titles for every tool and
  centralised them in `annotations.py` so the registry is the single source of
  truth.
- **Phase 3** introduced Pydantic response models with `output_schema`
  registration so MCP clients receive a JSON Schema for every response, and
  added sparse-by-default `model_dump` to keep payloads token-tight.
- **Phase 4** replaced the legacy `return {"error": True, ...}` envelope with
  a typed `RemarkableError` exception hierarchy and a `@tool_error_boundary`
  decorator that translates exceptions into a uniform `ToolError` wire shape.
- **Phase 5 (render artifacts)** added a transport-aware return for the
  render tools. `tools/_artifacts.py::render_response_to_tool_result` wraps
  the structured `RenderResponse` plus an MCP `EmbeddedResource` carrying
  the merged PDF (base64 `BlobResourceContents`, `application/pdf`) in a
  `ToolResult`, so MCP clients consume the rendered document from the tool
  result without needing host filesystem access. `pdf_path` is retained on
  the response for in-process/local diagnostics but is deprecated for
  remote consumers.

Phase 6 (`Context` injection) was audited and cancelled — it targets use
cases that don't apply to a local stdio deployment, and its token/complexity
economics didn't justify the implementation cost.

## The three layers

```
┌────────────────────────────────────────────────────────────────────┐
│ tools/             FastMCP registrations — thin wrappers           │
│   read.py, render.py, write.py, _boundary.py, _artifacts.py        │
└────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ facades/           Per-domain orchestration — business logic       │
│   documents.py, folders.py, render.py, status.py, writes.py        │
└────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ core/              Mechanisms — no MCP awareness                   │
│   cache.py, render.py, writes.py, page_sources.py,                 │
│   rm_format.py, pdf_passthrough.py                                 │
└────────────────────────────────────────────────────────────────────┘
```

Cross-cutting contracts (`annotations.py`, `responses.py`, `exceptions.py`)
sit at the package root and are imported by every layer.

### `core/` — mechanisms

Pure plumbing with no opinions about MCP, no validation of higher-level
business rules, and no error envelopes. Three concerns live here:

- **Cache loading** (`cache.py`) — walks the local reMarkable cache directory,
  parses each `.metadata` and `.content` JSON via `schemas.py` Pydantic
  models, and returns typed records. Provides `is_descendant_of` and
  `count_descendants` for cycle-safe folder operations.
- **Rendering** (`render.py`, `page_sources.py`, `rm_format.py`,
  `pdf_passthrough.py`) — given a list of pages, dispatch each to the right
  renderer (`rm_v6` via rmc → cairosvg, `pdf_passthrough` via pypdf, `rm_v5`
  surfaces a typed `RenderError`, `missing` surfaces another). Successful
  pages are merged via pypdf into a single `<doc_id>.pdf`.
- **Writes** (`writes.py`) — atomic mutation primitives. `MetadataWriter` for
  rename/move/pin, `MetadataRestorer` for undo from the latest backup,
  `MetadataCreator` for two-file folder creation with rollback, and
  `cleanup_backups` for bulk pruning.

Everything in `core/` is callable and testable without instantiating any
facade or registering any MCP tool.

### `facades/` — orchestration

One facade per domain (`DocumentsFacade`, `FoldersFacade`, `RenderFacade`,
`StatusFacade`, `WritesFacade`). Each facade:

1. Receives a `RemarkableCache` (and a `RemarkableRenderer` for `RenderFacade`,
   a base path for write/status) at construction.
2. Validates inputs against the shared helpers in `_helpers.py`
   (`expect_kind`, `validate_pagination`, `validate_parent_for_listing`, etc.).
3. Calls into `core/` to do the actual work.
4. **Returns** a Pydantic model from `responses.py` on success, or
   **raises** a typed exception from `exceptions.py` on failure.

Facades never return `{"error": True, ...}` dictionaries — that pattern was
retired in Phase 4. The full success/failure contract is now expressible as
either "you got a typed model" or "an exception propagated to the caller".

### `tools/` — MCP wiring

Each module under `tools/` registers a small group of FastMCP tools.
Registration is mechanical: pull `title` and `annotations` from
`annotations.py`, declare `output_schema=Model.model_json_schema()`, apply
`@tool_error_boundary`, and call the matching facade method.

```python
@mcp.tool(
    title=TITLES["remarkable_get_document_info"],
    annotations=ANNOTATIONS["remarkable_get_document_info"],
    output_schema=DocumentInfoResponse.model_json_schema(),
)
@tool_error_boundary
def remarkable_get_document_info(doc_id: str) -> dict:
    return documents.get_info(doc_id).model_dump()
```

Three things to notice:

- **No business logic.** If you find yourself writing a conditional inside a
  tool, push it down into the facade.
- **`@tool_error_boundary` lives inside the `@mcp.tool(...)` decorator.**
  FastMCP introspects the wrapped function via `functools.wraps`, so the
  boundary is invisible to schema generation but catches every
  `RemarkableError` and serializes a `ToolError` envelope. Generic
  `Exception` subclasses are *not* caught — those are bugs and surface as
  MCP-level failures.
- **`.model_dump()` is sparse by default.** `_BaseResponse` overrides
  `model_dump` with `exclude_unset=True`, so optional fields the facade
  didn't set drop off the wire automatically. Tools never have to think about
  serialization shape.

`tools/__init__.py::register_tools` calls each domain's registrar in turn,
gating `register_write_tools` on `REMARKABLE_ENABLE_WRITE_TOOLS`.

## The three cross-cutting contracts

### `annotations.py` — the tool registry

Two dictionaries keyed by tool name (`remarkable_check_status`,
`remarkable_list_documents`, …). `TITLES` provides a human-readable display
name for clients that show one. `ANNOTATIONS` provides the
`mcp.types.ToolAnnotations` object with `readOnlyHint`, `destructiveHint`,
`idempotentHint`, `openWorldHint`. Read-only tools all have
`readOnlyHint=True`; write tools have `readOnlyHint=False` and either
`destructiveHint=True` (for in-place mutations) or `destructiveHint=False`
(for `create_folder`, which is purely additive).

`test_annotations.py` iterates over both registries and parametrizes a
per-tool test, so adding a new tool without registering its annotations is a
test-time error.

### `responses.py` — the response model registry

Every facade method returns a model defined here. `_BaseResponse` is the
shared mixin that:

1. Exposes dict-style accessors (`__getitem__`, `__contains__`, `get`) so
   call sites can transition from the legacy dict shape without touching every
   read site at once.
2. Overrides `model_dump` to default `exclude_unset=True`. This is the
   sparse-serialization rule — explicit nulls (e.g. `first_page_id=None` on
   an empty doc) survive because they were *set* by the facade, but optional
   fields the facade never touched drop out.
3. Defaults `by_alias=False` for predictable snake_case JSON.

`ToolError` is also defined here — it's the wire envelope produced by
`@tool_error_boundary`.

### `exceptions.py` — the typed error hierarchy

`RemarkableError(Exception)` is the base class. Each subclass declares a
stable `code` constant that propagates onto the `ToolError` wire envelope:

- `NotFoundError` — `code="not_found"`
- `KindMismatchError` — `code="kind_mismatch"` (e.g. document id given to a
  folder tool)
- `ValidationError` — `code="validation"` (bad pagination, empty name, etc.)
- `TrashedRecordError` — `code="trashed"` (refused mutation on trashed record)
- `ConflictError` — `code="conflict"` (sibling-uniqueness, cycle-creating
  move)
- `BackupMissingError` — `code="backup_missing"` (restore with no `.bak.*`)

Clients can branch on `code` for stable identifiers instead of grepping the
human-readable `detail` string.

## Test layout

Tests mirror the layered structure:

| File | Tests |
|------|-------|
| `test_documents.py`, `test_folders.py`, `test_writes.py`, `test_render.py` | Per-facade unit tests |
| `test_cache.py`, `test_rm_format.py`, `test_pdf_passthrough.py`, `test_render_dispatch.py` | `core/` mechanism tests |
| `test_annotations.py` | Contract: every tool has a `title` + `ToolAnnotations`, spec rules hold |
| `test_responses.py` | Contract: every response model round-trips and serializes sparsely |
| `test_exceptions.py` | Contract: typed exception hierarchy + boundary decorator |
| `test_server.py` | Integration: tool registration + write-tool gating |
| `test_e2e.py` | End-to-end stdio transport |

The contract tests (`test_annotations.py`, `test_responses.py`,
`test_exceptions.py`) are the safety net for the cross-cutting registries.
If you add a tool without an annotation, a response model that drops
`exclude_unset`, or an exception subclass without a `code`, one of these
tests fails fast.

## Adding a new tool

1. Add the response model to `responses.py` (subclass `_BaseResponse`).
2. Add a facade method that returns the model on success or raises a
   `RemarkableError` subclass on failure.
3. Add `TITLES["..."]` and `ANNOTATIONS["..."]` entries in `annotations.py`.
4. Register the tool in the appropriate `tools/<domain>.py` module with the
   four-piece pattern (title + annotations + output_schema +
   `@tool_error_boundary`).
5. Add a unit test for the facade method and let `test_annotations.py` cover
   the registration contract automatically.

## Adding a new typed error

1. Add a subclass of `RemarkableError` in `exceptions.py` with a unique
   `code` constant.
2. Raise it from the appropriate facade method.
3. Add a single assertion in `test_exceptions.py` confirming the `code`
   propagates onto the `ToolError` wire envelope.

That's it — `@tool_error_boundary` already routes any `RemarkableError`
subclass to the wire envelope.
