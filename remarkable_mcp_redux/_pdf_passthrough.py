# ABOUTME: Single-page PDF extraction via pypdf for the unannotated-PDF passthrough.
# ABOUTME: Lets the renderer hand back source PDF pages when no .rm file exists.

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter


def extract_pdf_page(source_pdf: Path, page_index: int) -> bytes:
    """Return a single-page PDF (as bytes) sliced from ``source_pdf``.

    Raises:
        FileNotFoundError: if ``source_pdf`` does not exist.
        IndexError: if ``page_index`` is negative or beyond the PDF's page count.
    """
    if not Path(source_pdf).exists():
        raise FileNotFoundError(f"Source PDF not found: {source_pdf}")
    if page_index < 0:
        raise IndexError(f"Negative page_index: {page_index}")

    reader = PdfReader(str(source_pdf))
    if page_index >= len(reader.pages):
        raise IndexError(
            f"page_index {page_index} out of range for {source_pdf} "
            f"(has {len(reader.pages)} pages)"
        )

    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
