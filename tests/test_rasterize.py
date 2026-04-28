"""Unit tests for the core PDF-to-PNG rasterization helper.

Exercises the real pypdfium2 + Pillow stack against the same minimal PDF
fixture used elsewhere in the suite, plus the error-handling contract:
missing files, out-of-range pages, and invalid DPI all raise
``RasterizeError`` rather than a bare third-party exception.
"""

from pathlib import Path

import pytest

from remarkable_mcp_redux.core.rasterize import RasterizeError, rasterize_pdf_pages


def _minimal_pdf_bytes() -> bytes:
    """A tiny one-page PDF blob; identical to the renderer-output stub."""
    return (
        b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000043 00000 n \n0000000098 00000 n \n"
        b"trailer<</Root 1 0 R/Size 4>>\nstartxref\n174\n%%EOF"
    )


def _multi_page_pdf_bytes(n_pages: int) -> bytes:
    """Build an n-page PDF via pypdf so we can exercise multi-page rasterization."""
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.mark.unit
class TestRasterizePdfPages:
    def test_default_renders_all_pages(self, tmp_path: Path):
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(_multi_page_pdf_bytes(3))

        pngs = rasterize_pdf_pages(pdf_path)

        assert len(pngs) == 3
        for png in pngs:
            assert png.startswith(b"\x89PNG\r\n\x1a\n"), (
                "rasterizer must emit real PNG bytestrings"
            )

    def test_explicit_page_indices_subset(self, tmp_path: Path):
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(_multi_page_pdf_bytes(4))

        pngs = rasterize_pdf_pages(pdf_path, page_indices=[0, 2])

        assert len(pngs) == 2

    def test_dpi_changes_payload_size(self, tmp_path: Path):
        """Higher DPI must yield a strictly larger PNG for the same blank page."""
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(_minimal_pdf_bytes())

        small = rasterize_pdf_pages(pdf_path, dpi=72)[0]
        large = rasterize_pdf_pages(pdf_path, dpi=300)[0]

        assert len(large) > len(small), (
            "300 DPI render must be larger than 72 DPI render of the same page"
        )

    def test_missing_file_raises_rasterize_error(self, tmp_path: Path):
        with pytest.raises(RasterizeError, match="not found"):
            rasterize_pdf_pages(tmp_path / "nope.pdf")

    def test_out_of_range_page_raises_rasterize_error(self, tmp_path: Path):
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(_minimal_pdf_bytes())

        with pytest.raises(RasterizeError, match="out of range"):
            rasterize_pdf_pages(pdf_path, page_indices=[5])

    def test_zero_dpi_rejected(self, tmp_path: Path):
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(_minimal_pdf_bytes())

        with pytest.raises(RasterizeError, match="dpi"):
            rasterize_pdf_pages(pdf_path, dpi=0)
