# Bug Report: `remarkable_render_pages` — Comprehensive Failure Mode Analysis

## Tool Overview

`remarkable_render_pages` (and its convenience wrapper `remarkable_render_document`) renders selected pages of a reMarkable document to a single output PDF. The tool accepts a `doc_id` and optional page selectors (`page_indices`, `first_n`, `last_n`) with the priority `page_indices > last_n > first_n > all pages`.

On success it returns:
```json
{
  "pdf_path": "/absolute/path/to/output.pdf",
  "document_name": "My Document",
  "pages_rendered": 3,
  "pages_failed": [],
  "page_indices": [0, 1, 2]
}
```

On failure, `pdf_path` is `null` and each failed page carries an index and a `reason` string.

### Rendering Pipeline

The tool's rendering pipeline depends on two system components, both confirmed present via `remarkable_check_status`:

- **`rmc`** — the reMarkable converter CLI, which parses `.rm` vector stroke files using the `rmscene` Python library and outputs SVG/PDF
- **`cairo`** — the graphics rendering library used to draw the converted strokes to PDF

The pipeline assumes the following document structure in the reMarkable desktop cache:

```
<cache_root>/
  <doc_id>.metadata      # JSON: type, visibleName, parent, lastModified, ...
  <doc_id>.content       # JSON: fileType, page index, tags, documentMetadata, ...
  <doc_id>.pdf           # source PDF (only present for fileType=pdf)
  <doc_id>/
    <page_uuid>.rm       # one vector stroke file per annotated page
```

The pipeline processes `.rm` files — it does not directly read the underlying PDF for PDF-type documents.

---

## Failure Mode 1: Unannotated PDF — No `.rm` Files

**Status: Resolved.** Implemented as `PdfPassthroughSource` in the new dispatch pipeline. See _Implementation Notes_ below. The original analysis is preserved here as historical context.

### Observed Behavior

Calling `remarkable_render_pages` on any PDF that has not been written on returns:

```json
{
  "pdf_path": null,
  "pages_rendered": 0,
  "pages_failed": [{ "index": 0, "reason": "no .rm file" }]
}
```

### Root Cause

For PDF documents on the reMarkable, `.rm` annotation files are only created when a user writes on a page. An unannotated PDF page has no `.rm` file — there is no annotation layer to render. Since the tool's pipeline is built exclusively around `.rm` files, it has nothing to process and fails immediately.

This is a **design gap**, not an error in the conventional sense. The tool was built to render annotations, not to extract content from the underlying PDFs themselves.

### Impact

The majority of PDFs on the device are research papers that have been read but not annotated. All of these are completely inaccessible to the render tool. This includes all unnamed arxiv-numbered PDFs in the root collection, whose content cannot be inferred without an alternative mechanism.

Concretely: of 857 PDFs on this device, a substantial proportion are unannotated and will return `pages_rendered: 0` unconditionally.

### Proposed Fix

Add a PDF passthrough path to the render pipeline. When the document is a PDF and a page has no `.rm` file, extract that page directly from the cached source PDF using `pypdf` (if available in the venv) or `PyMuPDF`. The output contract of the tool — a PDF at `pdf_path` — remains unchanged.

```python
# Pseudocode for the PDF passthrough path
if file_type == "pdf" and not rm_file_exists(page):
    extract_page_from_pdf(source_pdf_path, page_index, output_pdf)
else:
    render_rm_file(rm_path, output_pdf)  # existing path
```

For annotated PDF pages, the existing `rmc` path continues to apply.

---

## Failure Mode 2: Legacy v5 `.rm` Format — `rmscene` Incompatibility

**Status: Partially resolved.** v5 files are now detected up-front and surfaced as `code: "v5_unsupported"` instead of a Python traceback (Option 1 from the original analysis). Rendering of v5 content remains unimplemented and is tracked as Follow-up B below.

### Observed Behavior

Calling `remarkable_render_pages` on a notebook created before reMarkable firmware version 3.0 returns:

```json
{
  "pdf_path": null,
  "pages_rendered": 0,
  "pages_failed": [
    {
      "index": 0,
      "reason": "rmc failed (exit 1) for <path>.rm: Traceback (most recent call last):\n  ...\n  File \"rmscene/tagged_block_common.py\", line 63, in read_header\n    raise ValueError(\"Wrong header: %r\" % header)\nValueError: Wrong header: b'reMarkable .lines file, version=5'"
    }
  ]
}
```

### Root Cause

The reMarkable device uses two distinct internal file formats for handwritten notes:

- **v5** (`reMarkable .lines file, version=5`): The legacy format used by all notebooks created before reMarkable software version 3.0.
- **v6**: The current format introduced with reMarkable software version 3.0 (released 2022).

When the firmware was updated to v3, old notebooks were **not re-encoded**. They remain on the device in v5 format indefinitely.

The `rmscene` library — which `rmc` depends on — was designed from its first release (v0.1.0, January 2023) exclusively for the v6 format. It has never supported v5, and the current latest release (v0.8.0, April 2026) still does not. The failure occurs in `tagged_block_common.py` at `read_header()`, which validates the file header and raises `ValueError` on any non-v6 header.

**This is not a dependency staleness issue. Upgrading `rmscene` will not resolve it.**

### Impact

Any notebook created before the user's firmware v3 upgrade cannot be rendered. The failure surfaces as a raw Python traceback embedded in the `reason` field — there is no graceful, structured error indicating that the file format is unsupported. Confirmed affected document on this device: "Real Analysis" (`doc_id: 74ceb1f9-b9b3-4395-820c-d9ecf57c551b`).

### Proposed Fixes

**Option 1 — Detect v5 and return a meaningful error (minimal fix)**

Before invoking `rmc`, read the first bytes of the `.rm` file and check the version header:

```python
with open(rm_path, "rb") as f:
    header = f.read(43)
if b"version=5" in header:
    return {
        "error": "v5_unsupported",
        "message": "This notebook was created before reMarkable firmware v3 "
                   "and uses the legacy v5 format. Rendering is not supported."
    }
```

This does not restore rendering but makes the failure comprehensible.

**Option 2 — Add v5 rendering support via a compatible library**

The v5 format is supported by:

- [`lines-are-rusty`](https://github.com/ax3l/lines-are-rusty) — a mature Rust-based renderer for v5 `.rm` files
- [`rmu`](https://github.com/rowancallahan/rmu) — a Python utility for v5 files

Integrating one of these as a fallback renderer for v5 files would restore rendering for the full document history.

**Option 3 — Provide a migration path**

Re-opening affected notebooks on the device (or via the reMarkable desktop app) triggers automatic re-encoding to v6. This is a user-facing workaround, not a code fix.

### Recommended Resolution

Implement Option 1 immediately to surface a clear error. Follow up with Option 2 using `lines-are-rusty` as the v5 backend, given its maturity and active maintenance.

---

## Failure Mode Summary

| Document Type               | Condition                          | Failure Reason / `code`     | `pdf_path` | Status |
|-----------------------------|------------------------------------|-----------------------------|------------|--------|
| PDF (unannotated)           | No `.rm` files exist               | n/a (rendered via passthrough) | Set        | Fixed via `PdfPassthroughSource` dispatch |
| PDF (partially annotated)   | Some pages have no `.rm` file      | n/a (mixed sources)         | Set        | Fixed; response carries `sources_used: {"rm_v6": N, "pdf_passthrough": M}` |
| Notebook (pre-firmware v3)  | `.rm` file is v5 format            | `code: "v5_unsupported"`    | `null`     | Detected and reported cleanly; rendering not yet restored — see Follow-up B |
| Notebook (post-firmware v3) | `.rm` file is v6 format            | rendered normally           | Set        | N/A |
| EPUB / notebook (no .rm, no source PDF) | Stray page id with no on-disk source | `code: "no_source"`         | `null` (or partial) | Surfaced as structured failure |

---

## Implementation Notes (post-fix)

The render pipeline was refactored around a typed `PageSource` dispatch:

- `remarkable_mcp_redux/_page_sources.py` defines the variant union (`RmV6Source`, `RmV5Source`, `PdfPassthroughSource`, `MissingSource`).
- `remarkable_mcp_redux/_rm_format.py:parse_rm_version` reads the 43-byte `.rm` header and returns 5/6/None.
- `remarkable_mcp_redux/_pdf_passthrough.py:extract_pdf_page` slices a single page out of the cached source PDF via `pypdf`.
- `remarkable_mcp_redux/_render.py` is now mechanism-only: `render_page_source` is a `match` over the variants, with typed `RenderError` subclasses (`LegacyV5Error`, `NoSourceError`, `RmcFailedError`, `CairoSvgFailedError`, `PdfExtractError`) carrying stable `code` strings.
- `remarkable_mcp_redux/client.py:_build_page_plan` is the single place where per-page source policy lives: it probes `.rm` existence + version, falls back to PDF passthrough for `file_type == "pdf"` cache layouts, and emits `MissingSource` otherwise.

Each `pages_failed[]` entry now carries a `code` field alongside the human `reason` string, and successful renders include a `sources_used` dict (non-zero counts only).

---

## Follow-ups

### Follow-up A — Annotated-PDF compositing

**Status:** open. Currently, when a PDF page has user annotations (a matching `.rm` file), `RmV6Source` renders only the strokes — the underlying PDF page content is dropped. Visually this does not match what the user sees on the device.

**Plan when picked up:**

- Add a fifth variant to `remarkable_mcp_redux/_page_sources.py`:
  ```python
  @dataclass(frozen=True)
  class AnnotatedPdfPageSource:
      rm_path: Path
      source_pdf: Path
      pdf_page_index: int
  ```
- Extend `render_page_source` in `remarkable_mcp_redux/_render.py` with a new `match` arm that:
  1. Renders the strokes via the existing `_render_rm_v6` path into a single-page PDF.
  2. Loads the underlying source PDF page via `pypdf.PdfReader.pages[idx]`.
  3. Calls `pypdf.PageObject.merge_page` (or `merge_translated_page` if reMarkable's stroke coordinate space requires offset/scale fixes) to overlay the strokes onto the source page.
  4. Writes the merged page back out as PDF bytes.
- Decide whether overlay is opt-in (new arg on `render_pages`, e.g. `composite_annotated_pdfs: bool = True`) or unconditional. Defaulting to compositing is more user-faithful but a behavioural change for any caller that currently expects strokes-only output. Lean toward making it the default and gating the legacy strokes-only output behind an explicit flag.
- Update `_build_page_plan` in `client.py`: when `rm_path.exists()` AND `file_type == "pdf"` AND the source PDF exists, emit `AnnotatedPdfPageSource` instead of `RmV6Source`. `RmV6Source` continues to handle non-PDF annotated content (notebooks, EPUB).
- Add a `"rm_v6_over_pdf"` (or similar) label in `SOURCE_LABEL` so `sources_used` distinguishes plain strokes from composited pages.
- New test fixture: a PDF whose pages contain detectable text content (so post-merge tests can verify both layers survived). Synthetic SVG strokes mocked through the existing `_run_rmc` patch.
- Coordinate space caveat: reMarkable internally renders `.rm` content at a specific stroke canvas size that may not match the source PDF's MediaBox. Empirically determine whether `merge_page` aligns correctly or if `merge_translated_page` / `add_transformation` is required. Worth probing on at least one annotated PDF from this device before locking in the merge call.

### Follow-up B — Real v5 rendering backend

**Status:** open. `RmV5Source` currently raises `LegacyV5Error` (clean structured failure, but no actual rendering). The dispatch surface added in this PR makes restoring rendering a single `match` arm change.

**Plan when picked up:**

- Pick a v5 backend:
  - `lines-are-rusty` ([github.com/ax3l/lines-are-rusty](https://github.com/ax3l/lines-are-rusty)) — Rust binary, mature, requires either a `cargo install` step or shipping a pre-built binary alongside the venv. Most realistic option.
  - `rmu` ([github.com/rowancallahan/rmu](https://github.com/rowancallahan/rmu)) — Python utility, no native compile, but less mature.
- Add a `_v5_backend.py` module mirroring the shape of `_pdf_passthrough.py`: a single `render_v5_rm(rm_path: Path) -> bytes` function that shells out to (or imports) the chosen backend and returns single-page PDF bytes.
- Replace the `RmV5Source` branch in `render_page_source` with a call to that backend. Wrap any backend-specific exceptions in a typed `V5RenderError(RenderError)` so the failure code and reason stay structured if the backend itself crashes.
- Update `_build_page_plan` doc string and the failure-mode summary table above to reflect that v5 renders normally.
- Add a CLI/availability check in `_render.check_*_available` for the chosen backend, plumbed into `remarkable_check_status` so users can diagnose missing dependencies without having to call `render_pages` first.
- Confirmed affected document on this device: "Real Analysis" (`doc_id: 74ceb1f9-b9b3-4395-820c-d9ecf57c551b`). Smoke test must verify the new backend produces non-empty PDF bytes for at least one page of that doc.

---

## References

- `rmscene` PyPI (v6 only, by design): https://pypi.org/project/rmscene/
- `lines-are-rusty` (v5 renderer): https://github.com/ax3l/lines-are-rusty
- Claude Code MCP per-call token limit: https://code.claude.com/docs/en/mcp
- reMarkable software v3 format change: https://support.remarkable.com
