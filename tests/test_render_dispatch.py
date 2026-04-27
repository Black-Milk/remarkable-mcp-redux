# ABOUTME: Unit tests for the page-source dispatcher in core.render.
# ABOUTME: Covers each PageSource variant in isolation, mocking rmc/cairosvg only for v6.

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pypdf import PdfWriter

from remarkable_mcp_redux.core.page_sources import (
    MissingSource,
    PdfPassthroughSource,
    RmV5Source,
    RmV6Source,
)
from remarkable_mcp_redux.core.render import (
    LegacyV5Error,
    NoSourceError,
    RmcFailedError,
    render_page_source,
)

_MIN_PDF = (
    b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000043 00000 n \n0000000098 00000 n \n"
    b"trailer<</Root 1 0 R/Size 4>>\nstartxref\n174\n%%EOF"
)
_MIN_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'


def _mock_rmc_success():
    """Patch rmc to write a minimal SVG and cairosvg to return a minimal PDF."""

    def fake_rmc(args, **kwargs):
        if "-o" in args:
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(_MIN_SVG)
        return MagicMock(returncode=0)

    return patch.multiple(
        "remarkable_mcp_redux.core.render",
        _run_rmc=fake_rmc,
        _svg_to_pdf_bytes=lambda **_: _MIN_PDF,
    )


def _mock_rmc_failure(stderr_text: str = "rmc died"):
    def fake_rmc(args, **kwargs):
        return MagicMock(returncode=1, stderr=stderr_text)

    return patch.multiple(
        "remarkable_mcp_redux.core.render",
        _run_rmc=fake_rmc,
    )


@pytest.mark.unit
def test_rm_v6_source_renders_via_rmc(tmp_path):
    rm_path = tmp_path / "page.rm"
    rm_path.write_bytes(b"\x00" * 64)
    with _mock_rmc_success():
        out = render_page_source(RmV6Source(rm_path=rm_path))
    assert isinstance(out, bytes) and out.startswith(b"%PDF")


@pytest.mark.unit
def test_rm_v6_source_rmc_failure_raises_typed_error(tmp_path):
    rm_path = tmp_path / "page.rm"
    rm_path.write_bytes(b"\x00" * 64)
    with _mock_rmc_failure("rmc died horribly"), pytest.raises(RmcFailedError) as exc_info:
        render_page_source(RmV6Source(rm_path=rm_path))
    assert exc_info.value.code == "rmc_failed"
    assert "rmc" in str(exc_info.value).lower()


@pytest.mark.unit
def test_rm_v5_source_raises_legacy_error(tmp_path):
    rm_path = tmp_path / "v5.rm"
    rm_path.write_bytes(b"v5 stub")
    with pytest.raises(LegacyV5Error) as exc_info:
        render_page_source(RmV5Source(rm_path=rm_path))
    assert exc_info.value.code == "v5_unsupported"


@pytest.mark.unit
def test_pdf_passthrough_source_extracts_page(tmp_path):
    src = tmp_path / "src.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    with open(src, "wb") as f:
        writer.write(f)

    out = render_page_source(PdfPassthroughSource(source_pdf=src, pdf_page_index=1))
    assert isinstance(out, bytes) and out.startswith(b"%PDF")


@pytest.mark.unit
def test_missing_source_raises_no_source_error():
    with pytest.raises(NoSourceError) as exc_info:
        render_page_source(MissingSource())
    assert exc_info.value.code == "no_source"
