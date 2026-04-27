# ABOUTME: Unit tests for single-page PDF extraction in core.pdf_passthrough.
# ABOUTME: Covers round-trip extraction, out-of-range, and missing-source cases.

import io

import pytest
from pypdf import PdfReader, PdfWriter

from remarkable_mcp_redux.core.pdf_passthrough import extract_pdf_page


def _write_blank_pdf(path, num_pages: int) -> None:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        writer.write(f)


@pytest.mark.unit
def test_extracts_each_page_as_valid_single_page_pdf(tmp_path):
    src = tmp_path / "src.pdf"
    _write_blank_pdf(src, num_pages=5)

    for idx in range(5):
        page_bytes = extract_pdf_page(src, idx)
        reader = PdfReader(io.BytesIO(page_bytes))
        assert len(reader.pages) == 1, f"page {idx} should produce a 1-page PDF"


@pytest.mark.unit
def test_negative_index_raises_index_error(tmp_path):
    src = tmp_path / "src.pdf"
    _write_blank_pdf(src, num_pages=3)
    with pytest.raises(IndexError):
        extract_pdf_page(src, -1)


@pytest.mark.unit
def test_out_of_range_raises_index_error(tmp_path):
    src = tmp_path / "src.pdf"
    _write_blank_pdf(src, num_pages=3)
    with pytest.raises(IndexError):
        extract_pdf_page(src, 99)


@pytest.mark.unit
def test_missing_source_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_pdf_page(tmp_path / "nope.pdf", 0)
