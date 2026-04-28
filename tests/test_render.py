"""Unit tests for the RenderFacade plus StatusFacade diagnostics.

Covers page-source dispatch, render_pages selection, status checks, and cleanup.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from remarkable_mcp_redux.client import RemarkableClient
from remarkable_mcp_redux.exceptions import (
    KindMismatchError,
    NotFoundError,
    ValidationError,
)
from tests.conftest import (
    LEGACY_V5_DOC_ID,
    MIXED_PDF_DOC_ID,
    UNANNOTATED_PDF_DOC_ID,
    WORK_FOLDER_ID,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_rendering():
    """Context manager that patches rmc subprocess and cairosvg to produce fake PDFs.

    rmc: writes a minimal SVG to the output path.
    cairosvg.svg2pdf: returns minimal valid PDF bytes.
    """
    minimal_pdf = (
        b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000043 00000 n \n0000000098 00000 n \n"
        b"trailer<</Root 1 0 R/Size 4>>\nstartxref\n174\n%%EOF"
    )
    minimal_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'

    def fake_rmc(args, **kwargs):
        if "-o" in args:
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(minimal_svg)
        return MagicMock(returncode=0)

    def fake_svg2pdf(**kwargs):
        return minimal_pdf

    return patch.multiple(
        "remarkable_mcp_redux.core.render",
        _run_rmc=fake_rmc,
        _svg_to_pdf_bytes=fake_svg2pdf,
    )


# ---------------------------------------------------------------------------
# render.render_pages
# ---------------------------------------------------------------------------


class TestRenderPages:
    @pytest.mark.unit
    def test_last_n_selection(self, fake_cache, render_dir):
        """last_n=2 on a 3-page doc should only render pages at index 1 and 2."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render.render_pages("aaaa-1111-2222-3333", last_n=2)
        assert result["pages_rendered"] == 2
        assert result["page_indices"] == [1, 2]
        assert Path(result["pdf_path"]).exists()

    @pytest.mark.unit
    def test_first_n_selection(self, fake_cache, render_dir):
        """first_n=1 on a 3-page doc should render only page at index 0."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render.render_pages("aaaa-1111-2222-3333", first_n=1)
        assert result["pages_rendered"] == 1
        assert result["page_indices"] == [0]

    @pytest.mark.unit
    def test_by_indices(self, fake_cache, render_dir):
        """Explicit page_indices selection."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render.render_pages(
                "aaaa-1111-2222-3333", page_indices=[0, 2]
            )
        assert result["pages_rendered"] == 2
        assert result["page_indices"] == [0, 2]

    @pytest.mark.unit
    def test_indices_priority_over_last_n(self, fake_cache, render_dir):
        """page_indices takes priority over last_n."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render.render_pages(
                "aaaa-1111-2222-3333", page_indices=[0], last_n=3
            )
        assert result["pages_rendered"] == 1
        assert result["page_indices"] == [0]

    @pytest.mark.unit
    def test_failed_pages_no_rm_file(self, fake_cache, render_dir):
        """Notebook with no .rm files (and no source PDF) reports all pages as failed.

        ``Empty Notebook`` is a notebook fixture, so PDF passthrough is not
        applicable — the only thing the dispatcher can do is emit ``no_source``.
        """
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        result = client.render.render_pages("cccc-7777-8888-9999")
        assert result["pages_rendered"] == 0
        assert len(result["pages_failed"]) == 1
        assert result["pages_failed"][0]["code"] == "no_source"

    @pytest.mark.unit
    def test_out_of_bounds_indices(self, fake_cache, render_dir):
        """Out-of-range indices should appear in pages_failed with code=out_of_bounds."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render.render_pages(
                "aaaa-1111-2222-3333", page_indices=[0, 99]
            )
        failed = [f for f in result["pages_failed"] if f["index"] == 99]
        assert len(failed) == 1
        assert failed[0]["code"] == "out_of_bounds"

    @pytest.mark.unit
    def test_missing_document_raises_not_found(self, fake_cache, render_dir):
        """Rendering a non-existent doc should raise NotFoundError."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with pytest.raises(NotFoundError, match="not found"):
            client.render.render_pages("does-not-exist")

    @pytest.mark.unit
    def test_render_all_pages(self, fake_cache, render_dir):
        """No selection args renders all pages."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render.render_pages("aaaa-1111-2222-3333")
        assert result["pages_rendered"] == 3
        assert result["page_indices"] == [0, 1, 2]

    @pytest.mark.unit
    def test_rejects_empty_page_indices(self, fake_cache, render_dir):
        """BUG-05: page_indices=[] should raise ValidationError, not render everything."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering(), pytest.raises(ValidationError, match="page_indices"):
            client.render.render_pages("aaaa-1111-2222-3333", page_indices=[])

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache, render_dir):
        """BUG-04: render_pages should refuse CollectionType records."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with pytest.raises(KindMismatchError, match="(?i)folder|collection"):
            client.render.render_pages(WORK_FOLDER_ID)

    @pytest.mark.unit
    def test_rmc_nonzero_returncode_marks_page_failed(self, fake_cache, render_dir):
        """BUG-03: rmc non-zero exit must surface as a failed page even if it produced output.

        rmc occasionally writes partial SVGs before failing. Without an explicit returncode
        check we'd mistakenly treat that as success.
        """
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        partial_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'

        def fake_rmc_fail(args, **kwargs):
            if "-o" in args:
                out_idx = args.index("-o") + 1
                Path(args[out_idx]).write_bytes(partial_svg)
            return MagicMock(returncode=1, stderr="rmc died")

        with patch.multiple(
            "remarkable_mcp_redux.core.render",
            _run_rmc=fake_rmc_fail,
        ):
            result = client.render.render_pages("aaaa-1111-2222-3333", first_n=1)

        assert result["pages_rendered"] == 0
        assert len(result["pages_failed"]) == 1
        assert "rmc" in result["pages_failed"][0]["reason"].lower()
        assert result["pages_failed"][0]["code"] == "rmc_failed"


# ---------------------------------------------------------------------------
# render.render_pages — page-source dispatch (PDF passthrough, v5 detection, mixed)
# ---------------------------------------------------------------------------


class TestRenderPagesSourceDispatch:
    """Exercises the ``PageSource`` dispatch surface end-to-end via render_pages."""

    @pytest.mark.unit
    def test_unannotated_pdf_is_passthrough_rendered(
        self, unannotated_pdf_cache, render_dir
    ):
        """Bug 1: an unannotated PDF must render via pypdf passthrough."""
        client = RemarkableClient(
            base_path=unannotated_pdf_cache, render_dir=render_dir
        )
        result = client.render.render_pages(UNANNOTATED_PDF_DOC_ID)
        assert result.get("error") is None or result.get("error") is False or "error" not in result
        assert result["pages_rendered"] == 3
        assert result["pages_failed"] == []
        assert result["pdf_path"] is not None
        assert Path(result["pdf_path"]).exists()
        assert result["sources_used"] == {"pdf_passthrough": 3}

    @pytest.mark.unit
    def test_legacy_v5_notebook_yields_structured_failure(
        self, legacy_v5_cache, render_dir
    ):
        """Bug 2: pre-firmware-v3 v5 notebook surfaces v5_unsupported, not a traceback."""
        client = RemarkableClient(base_path=legacy_v5_cache, render_dir=render_dir)
        result = client.render.render_pages(LEGACY_V5_DOC_ID)
        assert result["pages_rendered"] == 0
        assert result["pdf_path"] is None
        assert len(result["pages_failed"]) == 2
        for entry in result["pages_failed"]:
            assert entry["code"] == "v5_unsupported"
            assert "Traceback" not in entry["reason"]
            assert "version=5" in entry["reason"] or "v5" in entry["reason"].lower()
        assert "sources_used" not in result or result["sources_used"] == {}

    @pytest.mark.unit
    def test_mixed_pdf_uses_both_sources(self, mixed_pdf_cache, render_dir):
        """A partially annotated PDF: rm_v6 for annotated pages, passthrough otherwise."""
        client = RemarkableClient(base_path=mixed_pdf_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render.render_pages(MIXED_PDF_DOC_ID)
        assert result["pages_rendered"] == 3
        assert result["pages_failed"] == []
        assert result["sources_used"] == {"rm_v6": 1, "pdf_passthrough": 2}

    @pytest.mark.unit
    def test_sources_used_omitted_when_no_pages_rendered(
        self, legacy_v5_cache, render_dir
    ):
        """Failure-only responses should not advertise an empty sources_used dict."""
        client = RemarkableClient(base_path=legacy_v5_cache, render_dir=render_dir)
        result = client.render.render_pages(LEGACY_V5_DOC_ID)
        assert result.get("sources_used", {}) == {}

    @pytest.mark.unit
    def test_unannotated_notebook_pages_are_no_source(self, fake_cache, render_dir):
        """Empty Notebook is type=notebook with no source PDF; expect code=no_source."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        result = client.render.render_pages("cccc-7777-8888-9999")
        assert result["pages_failed"]
        for entry in result["pages_failed"]:
            assert entry["code"] == "no_source"


# ---------------------------------------------------------------------------
# status.check
# ---------------------------------------------------------------------------


class TestCheckStatus:
    @pytest.mark.unit
    def test_cache_exists(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.status.check()
        assert result["cache_exists"] is True
        assert result["document_count"] == 5

    @pytest.mark.unit
    def test_cache_missing(self, empty_cache):
        client = RemarkableClient(base_path=empty_cache)
        result = client.status.check()
        assert result["cache_exists"] is False
        assert result["document_count"] == 0


# ---------------------------------------------------------------------------
# render.cleanup_renders
# ---------------------------------------------------------------------------


class TestCleanupRenders:
    @pytest.mark.unit
    def test_removes_files(self, render_dir):
        (render_dir / "doc1.pdf").write_bytes(b"fake pdf content 1")
        (render_dir / "doc2.pdf").write_bytes(b"fake pdf content 2")
        client = RemarkableClient(
            base_path=Path("/nonexistent"), render_dir=render_dir
        )
        result = client.render.cleanup_renders()
        assert result["files_removed"] == 2
        assert result["bytes_freed"] > 0
        assert not list(render_dir.iterdir())

    @pytest.mark.unit
    def test_empty_dir(self, render_dir):
        client = RemarkableClient(
            base_path=Path("/nonexistent"), render_dir=render_dir
        )
        result = client.render.cleanup_renders()
        assert result["files_removed"] == 0
        assert result["bytes_freed"] == 0
