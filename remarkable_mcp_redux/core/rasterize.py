"""PDF page rasterization to PNG bytes via pypdfium2.

Mechanism-only: facades/tools own the policy of whether to rasterize, how
many pages to render, and at what DPI. This module just executes a single
``rasterize_pdf_pages`` call and returns one PNG bytestring per requested
page index.

Lives in ``core/`` because it has no MCP awareness — the FastMCP
``ImageContent`` wrapping happens in ``tools/`` so the renderer stays
transport-agnostic.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

# 72 is the PDF default user-space unit (points per inch). pypdfium2's
# ``render(scale=...)`` multiplies the native page size, so dpi/72 is the
# correct conversion factor to honour the requested DPI.
_PDF_POINTS_PER_INCH = 72


class RasterizeError(Exception):
    """Raised when a PDF cannot be opened or a page cannot be rendered."""


def rasterize_pdf_pages(
    pdf_path: Path,
    *,
    page_indices: list[int] | None = None,
    dpi: int = 150,
) -> list[bytes]:
    """Rasterize selected pages of a PDF on disk to a list of PNG bytestrings.

    ``page_indices`` defaults to all pages in the PDF. ``dpi`` is converted
    to a pypdfium2 scale factor of ``dpi / 72``. Each entry in the returned
    list is the full PNG payload for the matching index in
    ``page_indices``, ready to be base64-encoded for ``ImageContent``.

    Raises ``RasterizeError`` on any failure (PDF parse failure, page
    out-of-range, render error). The caller decides whether to surface the
    error to the user or degrade silently to "no images attached".
    """
    if dpi <= 0:
        raise RasterizeError(f"dpi must be positive, got {dpi}")

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - import is guaranteed by deps
        raise RasterizeError(
            "pypdfium2 is required for image rendering but is not installed"
        ) from exc

    try:
        from PIL import Image  # noqa: F401  - imported for failure visibility
    except ImportError as exc:  # pragma: no cover - import is guaranteed by deps
        raise RasterizeError(
            "Pillow is required for PNG encoding but is not installed"
        ) from exc

    path = Path(pdf_path)
    if not path.exists():
        raise RasterizeError(f"PDF not found: {pdf_path}")

    scale = dpi / _PDF_POINTS_PER_INCH

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise RasterizeError(f"failed to open PDF {pdf_path}: {exc}") from exc

    try:
        total_pages = len(pdf)
        if page_indices is None:
            page_indices = list(range(total_pages))

        pngs: list[bytes] = []
        for idx in page_indices:
            if idx < 0 or idx >= total_pages:
                raise RasterizeError(
                    f"page index {idx} out of range (PDF has {total_pages} pages)"
                )
            try:
                page = pdf[idx]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                pngs.append(buf.getvalue())
            except Exception as exc:
                raise RasterizeError(
                    f"failed to rasterize page {idx} of {pdf_path}: {exc}"
                ) from exc
        return pngs
    finally:
        # pypdfium2 PdfDocument is context-managed via close(); release
        # native resources promptly so stale handles don't accumulate when
        # rasterize_pdf_pages is called many times in a session.
        with contextlib.suppress(Exception):
            pdf.close()


__all__ = ["RasterizeError", "rasterize_pdf_pages"]
