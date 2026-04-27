# Follow-up A: Annotated-PDF Compositing — Investigation & Limitations

## Status

**Paused for direction.** No code changes pending; production state is unaffected. This document is the analytical companion to the Follow-up A entry in [`docs/ongoing-mcp-bugs.md`](ongoing-mcp-bugs.md) and captures the design review that led to the pause. It exists so that whoever picks this up next (likely future-me) does not have to reconstruct the analysis from chat history.

---

## What this document is and is not

**Is**: a record of (a) the case for compositing, (b) the architecture we converged on, (c) the technical risks and unknowns identified, and (d) the alternatives that emerged once those risks were named honestly.

**Is not**: a commitment to implement, a final design, or a substitute for the implementation plan in [`docs/ongoing-mcp-bugs.md`](ongoing-mcp-bugs.md). When (if) Follow-up A is resumed, the implementation plan there is still the source of truth for *what to build*; this document is the source of truth for *why* and *with what caveats*.

---

## 1. Problem statement

For PDF documents that the user has annotated on the device, [`_build_page_plan`](../remarkable_mcp_redux/client.py) currently emits `RmV6Source`. The renderer in [`_render.py`](../remarkable_mcp_redux/_render.py) takes the `.rm` strokes through `rmc → SVG → cairosvg → PDF` and returns a single-page PDF containing **only the strokes**. The underlying source PDF page is dropped on the floor.

Visually this does not match what the user sees on the device, which is strokes-on-PDF. For partially annotated PDFs, the response mixes `pdf_passthrough` (clean source page) and `rm_v6` (strokes only on a transparent canvas) on a per-page basis, which is jarring when adjacent pages are flipped through.

Follow-up A is the proposal to close this gap by compositing strokes onto the source PDF page for annotated-PDF pages.

---

## 2. The case for compositing

The realistic invocations of `remarkable_render_pages` (and `remarkable_render_document`) on annotated PDFs are dominated by these patterns:

- **Transcribing contextual marks.** "Transcribe my notes on page 3 of this paper." Strokes-only gives Claude isolated handwriting floating in empty space. The annotation almost always makes sense only relative to printed content — "underline under the word `monad` with a question mark in the margin". Without the underlying PDF, "what was the user reacting to" is lost.
- **Summarising mark-ups.** "What did I highlight in this paper?" Strokes-only is meaningless: marks without a substrate. Composited is the only useful answer.
- **Multi-page summaries that include comments.** "Summarise pages 5–10 including my comments." Strokes-only forces two passes (annotated render + unannotated render) and a manual reconciliation across page indices that the MCP cannot currently do. Composited is one pass, one `pdf_path`.
- **Faithful render.** "Render this annotated PDF." The user's mental model is "give me what I see on the device". Composited matches that model; strokes-only is a leaky abstraction.

**Counter-cases** considered:
- Tasks that prefer strokes-only as input (e.g. an OCR pipeline that performs better on isolated handwriting). No concrete MCP-invocation example was constructed that beats "render composited and let the model handle the noise". The strokes-only escape hatch (`composite_annotated_pdfs=False`) exists primarily as a debug/test surface, not for production callers.
- Documents with very few annotations. The `pdf_passthrough` path already does the right thing for unannotated pages; compositing's marginal value is bounded by how many pages have strokes.

**Net.** Compositing is the right default for the realistic call patterns. The strokes-only path is worth keeping as an opt-out for testability and debugging, but the asymmetry is heavy.

---

## 3. Proposed architecture

The architecture mirrors the existing PageSource dispatch (see [`_page_sources.py`](../remarkable_mcp_redux/_page_sources.py)). One new variant, one new render arm, one new policy branch.

### New `PageSource` variant

In [`_page_sources.py`](../remarkable_mcp_redux/_page_sources.py):

```python
@dataclass(frozen=True)
class AnnotatedPdfPageSource:
    rm_path: Path
    source_pdf: Path
    pdf_page_index: int
```

Plus an `"rm_v6_over_pdf"` entry in `SOURCE_LABEL` so `sources_used` distinguishes plain strokes from composited pages.

### New backend

`remarkable_mcp_redux/_pdf_composite.py` (new) — single function:

```python
def composite_strokes_on_pdf(
    strokes_pdf_bytes: bytes,
    source_pdf: Path,
    pdf_page_index: int,
    *,
    transform: Transformation | None = None,
) -> bytes
```

The `transform` slot is the seam where the empirically-validated coord-space alignment lives (see section 6). Default `None` means identity, which we expect to be wrong but will be the diagnostic baseline.

### New render arm

In [`_render.py`](../remarkable_mcp_redux/_render.py)'s `render_page_source`:

```python
case AnnotatedPdfPageSource(rm_path, source_pdf, pdf_page_index):
    strokes_bytes = _render_rm_v6(rm_path)  # reused
    return composite_strokes_on_pdf(strokes_bytes, source_pdf, pdf_page_index, transform=...)
```

Plus a typed `CompositeFailedError(RenderError)` with stable `code = "composite_failed"`.

### New policy branch

In [`_build_page_plan`](../remarkable_mcp_redux/client.py): when `rm_path.exists()` AND `parse_rm_version(rm_path) == 6` AND `file_type == "pdf"` AND the source PDF exists, emit `AnnotatedPdfPageSource` instead of `RmV6Source`. `RmV6Source` continues to handle non-PDF annotated content (notebooks, EPUBs).

### Tool surface

Add `composite_annotated_pdfs: bool = True` to `remarkable_render_pages` and `remarkable_render_document` in [`_tools.py`](../remarkable_mcp_redux/_tools.py). Default-on; opt-out for debug/test. Hard-fail on composite errors with structured `composite_failed` code (no silent fallback to strokes-only — silent fallbacks make the response shape unpredictable).

### Tests

- `tests/test_pdf_composite.py` (new) — happy path, missing source, out-of-range page index, merge failure.
- Extend `tests/test_render_dispatch.py` with the `AnnotatedPdfPageSource` arm.
- New `annotated_pdf_cache` fixture in `tests/conftest.py` with detectable per-page PDF text (so post-merge tests can verify both layers survived).
- Extend `tests/test_remarkable_client.py` with default-on, opt-out, and the three failure subcodes.

---

## 4. The coordinate-space challenge

This is the dominant unknown. Everything else in section 3 is mechanical; this is where the real risk lives.

### What `rmc` emits

Empirically (smoke-tested on a real annotated page from this device):

- A `<svg>` element whose `viewBox` is **bbox-cropped to the actual stroke extent**, not aligned to the device canvas origin. The `viewBox` typically has non-zero `x` and `y` and dimensions much smaller than the full page.
- Stroke point coordinates inside the SVG are in `rmc`'s internal point system (not raw `.rm` device pixels).
- The cairosvg-rendered PDF page therefore has a **MediaBox that is the bbox of the strokes**, not the source PDF page's MediaBox.

### What `pypdf.merge_page` expects

`pypdf.PageObject.merge_page(other)` overlays `other` onto `self` using `other`'s content stream as-is, with no implicit scaling or translation. It assumes both pages share a coordinate origin and scale.

### The misalignment

Because the strokes-PDF MediaBox is bbox-cropped (origin shifted, dimensions different from the source PDF), a naive `merge_page` will:

1. Draw the strokes at the wrong position (the bbox shift becomes a draw-position shift).
2. Possibly at the wrong scale (if `rmc`'s point system and the source PDF's point system differ).

### What we need

A per-page `pypdf.Transformation`:

```python
transform = (
    Transformation()
    .scale(sx, sy)         # rmc point system -> PDF point system
    .translate(tx, ty)     # source-bbox-origin -> source-MediaBox origin
)
strokes_page.add_transformation(transform)
source_page.merge_page(strokes_page)
```

The values of `sx`, `sy`, `tx`, `ty` are derivable from:
- The strokes SVG's `viewBox` (parsed from the SVG before cairosvg conversion, or recoverable from the rendered PDF's MediaBox).
- The source PDF page's MediaBox.
- A constant for the rmc-to-PDF-points scale (likely 1.0 since both use PDF points, but unverified).

### Why this can only be validated empirically

The relationship between `rmc`'s viewBox and the device canvas is not formally documented and likely varies with `.rm` version and device model. Until we run a real annotated PDF page through the pipeline and eyeball the output, we cannot know whether the transform is uniform-linear (tractable), nonlinear (hard), or device-dependent (very hard). The first 30–60 minutes of any resume of Follow-up A should be a no-code-yet spike: render one real page with `transform=None` and look at the misalignment.

---

## 5. Contingency path and honest limitations

The original plan named "skip the SVG and draw strokes directly from `rmscene` onto the source PDF via `reportlab`" as a contingency if the cairosvg+pypdf path's coord-space could not be solved. This section is honest about what that contingency actually costs.

### What we'd be reimplementing

`rmc` is a non-trivial renderer. Its visual output reflects all of the following:

- **Pen pressure → stroke width modulation.** Per-point pressure values, modulated through a piecewise-linear width curve. A naive "constant-width line" path renders all strokes uniformly — visibly worse for pressure-sensitive content (signatures, sketches, expressive notes).
- **Brush types.** rM exposes ~8 tools (ballpoint, fineliner, marker, highlighter, pencil, mechanical pencil, paintbrush, calligraphy). Each has a distinct visual signature. Critical regressions:
  - **Highlighter** is semi-transparent, wide, colour-tinted. Uniform-line rendering produces opaque marker → underlying text obscured. Highlighter-on-PDF is a heavy-use pattern; this is unacceptable for that workflow.
  - **Pencil** and **paintbrush** have texture variation that vector-line drawing cannot reproduce.
- **Eraser strokes — the showstopper.** v6 `.rm` blocks include eraser strokes that *subtract* from existing ink rather than add. Correct rendering requires either:
  - layered subtractive vector composition (`reportlab.Canvas` does not natively support this), or
  - rasterise to Pillow, mask, convert back to PDF — destroys the vector advantage that motivated the contingency.

  Skipping eraser strokes makes erased content reappear, which is a visibly wrong render for any user who has ever corrected a mark.
- **Color palette.** rM Paper Pro has color (red, blue, green, yellow). Hardcoding black drops semantic information ("blue = imported, red = TODO"). Cheap to fix once we have Pro content to test against.
- **Selection moves and rotations.** v6 supports moving a selected region, encoded as transform blocks. Without handling, content appears in pre-move positions.
- **Layer ordering and visibility.** v6 has multiple layers per page with independent visibility; rmc respects this.
- **Stroke smoothing.** `rmc` applies Catmull-Rom or similar spline smoothing. Drawing raw point sequences produces visibly polygonal strokes at high zoom.

### Risk profile

- **Bare-bones contingency** (uniform-width black strokes, no pressure, no brush types, no eraser, single layer): roughly 1 day of work. Output is **legible but visibly wrong**. Acceptable for "I just need to read what's there"; unacceptable for "give me what I see on the device".
- **High-fidelity contingency** (matching rmc on pressure, basic brushes, eraser, layers): multi-day, real reimplementation of `rmc`. The eraser problem in particular has no good vector solution; any serious approach probably routes through Pillow, losing the vector advantage.

### Reframing

The contingency was originally described as a fallback. It is not a casual fallback. **Reframe**: last-resort, with explicit fidelity caveats, for use only if the primary path's coordinate transform turns out to be structurally unsolvable (which is unlikely on the evidence so far). If the primary path's transform is the problem, the right next move is to invest more time in the transform math, not to reach for the contingency.

---

## 6. Device-canvas inference

### Primary path: not required

The primary path (cairosvg + pypdf) consumes `rmc`'s output, which has already been transformed out of device canvas coordinates. We never touch device-canvas pixels, so device-model inference is not needed. The transform we derive in section 4 is rmc-points-to-PDF-points, not device-pixels-to-PDF-points.

### Contingency path: required

If the contingency is ever reached, we are drawing directly from `rmscene`'s point streams, which *are* in the device canvas. Device model would need inferring because:

| Model                    | Display canvas       |
|--------------------------|----------------------|
| reMarkable 1             | 1404 × 1872 px       |
| reMarkable 2             | 1404 × 1872 px       |
| reMarkable Paper Pro     | 1620 × 2160 px       |
| reMarkable Paper Pro Move| ~954 × 1696 px       |

The `.rm` v6 file does not carry the originating model. Sources of evidence, ranked:

1. **`.content` file's `pageSize` / `cPages` / dimensions field.** Sometimes present. Cheap if available.
2. **Empirical from the `.rm` file itself.** Read all stroke point coordinates; max `(x, y)` is a lower bound on canvas extent. If max under (1500, 1900) → rM 1/2; otherwise → Pro variant. Robust but requires a full pass over all blocks before drawing.
3. **Heuristic default.** Hardcode rM 1/2; document the limitation. Fast; gets physical size wrong on Pro content.

---

## 7. Decision space

Five alternatives identified during the design review, with pros and cons.

### A. Defer both follow-ups; ship current state

**Pros**: zero new risk; current state already fixes both reported bugs cleanly; no maintenance tax. **Cons**: annotated PDFs continue rendering strokes-only; legacy v5 continues failing structured. Both are *correctly handled* (no crash), just not optimally.

### B. Switch to Follow-up B (v5 rendering backend)

**Pros**: simpler, more bounded work than A; v5 has none of A's coord-space risk; restores access to currently unrenderable docs (at least "Notebook 4" `0956c0d9-...` and "Real Analysis" `74ceb1f9-...`). **Cons**: adds a non-Python dependency (`lines-are-rusty` is the strongest backend candidate, requires either `cargo install` or shipping a binary); doesn't address the use cases motivating A.

### C. Research spike on coord-space, then decide

**Pros**: lowest-cost path to a real decision; converts the open-ended risk into measured information; output is data, not commitment. **Cons**: requires 30–60 minutes of focused work on a real annotated PDF; may produce ambiguous results if the test page is unrepresentative.

### D. Reduced-scope A: side-by-side rendering

Instead of compositing onto the source page, return a PDF where annotated pages are duplicated — page N is the source, page N+1 is the strokes-only render of the same page. **Pros**: eliminates coord-space risk entirely; preserves both information layers for Claude. **Cons**: doubled page count is real UX friction; doesn't match device appearance; output size grows linearly with annotated pages; meaningful change to response shape (`pages_rendered != len(page_indices)`).

### E. Keep A as currently planned

**Pros**: directly addresses the use cases motivating Follow-up A; matches device appearance; cleanest UX. **Cons**: coord-space risk is real; contingency is weaker than originally framed.

### Working recommendation

**C, then act on results.** A spike is the cheapest possible way to convert the dominant unknown into a measured decision. From the spike's outcome:

- Strokes naively merge close-to-right → commit to E (A as planned).
- Strokes need a tractable uniform transform → commit to E with confidence in the math.
- Strokes need nonlinear correction or device-canvas information rmc doesn't expose → defer A; consider B or just A-defer (option A).

If skipping the spike, **B** is the cleaner next deliverable than A on its own merits — different risk profile, more bounded work, restores currently-unrenderable cache content.

---

## 8. Open questions worth answering before committing

- **Annotated-PDF prevalence in the cache.** How many PDFs in `~/Library/Application Support/remarkable/desktop/` have `<doc_id>/<page_uuid>.rm` files? This is the population A actually serves. Quick `find` against the cache root would answer.
- **What does naive `merge_page` actually produce?** Section 4's analysis is a priori; it should be replaced with a smoke-test artefact (one annotated PDF page rendered through the cairosvg + pypdf path with `transform=None`, eyeballed).
- **v5 prevalence.** How many `.rm` files in the cache have `version=5`? Sizes B's relative impact. Iterating `parse_rm_version` over all `.rm` files would answer.
- **Does `.content` carry `pageSize` or device hints?** Spot-check several `.content` files (one per file type, ideally one per device model represented in the cache) for fields that would short-circuit section 6's empirical inference.

---

## 9. Cross-references

### In-repo

- [`docs/ongoing-mcp-bugs.md`](ongoing-mcp-bugs.md) — Follow-up A entry, implementation plan.
- [`remarkable_mcp_redux/_page_sources.py`](../remarkable_mcp_redux/_page_sources.py) — `PageSource` union, where `AnnotatedPdfPageSource` would slot in.
- [`remarkable_mcp_redux/_render.py`](../remarkable_mcp_redux/_render.py) — `render_page_source` dispatch, where the new arm would live.
- [`remarkable_mcp_redux/client.py`](../remarkable_mcp_redux/client.py) — `_build_page_plan` policy, where the new branch would be added.
- [`remarkable_mcp_redux/_pdf_passthrough.py`](../remarkable_mcp_redux/_pdf_passthrough.py) — shape model for the new `_pdf_composite.py`.
- [`remarkable_mcp_redux/_rm_format.py`](../remarkable_mcp_redux/_rm_format.py) — version detection used by the policy branch.
- [`remarkable_mcp_redux/_tools.py`](../remarkable_mcp_redux/_tools.py) — tool surface for the `composite_annotated_pdfs` flag.
- [`tests/conftest.py`](../tests/conftest.py) — shape model for the new `annotated_pdf_cache` fixture.

### External

- `rmc` (CLI, current renderer): https://github.com/ricklupton/rmc
- `rmscene` (Python lib used by rmc, v6 only): https://pypi.org/project/rmscene/
- `pypdf` (PDF manipulation): https://pypdf.readthedocs.io/
- `pypdf.Transformation` API: https://pypdf.readthedocs.io/en/stable/user/cropping-and-transforming.html
- `reportlab` (contingency draw library): https://www.reportlab.com/
- `lines-are-rusty` (v5 renderer, relevant for Follow-up B): https://github.com/ax3l/lines-are-rusty
- reMarkable hardware spec sheet: https://remarkable.com/store/remarkable-paper/pro
