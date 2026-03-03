# ABOUTME: Unit tests for RemarkableClient using synthetic cache fixtures.
# ABOUTME: Covers document listing, metadata, page rendering, status checks, and cleanup.

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from remarkable_client import RemarkableClient


# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------

class TestListDocuments:
    @pytest.mark.unit
    def test_list_all_documents(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents()
        assert result["count"] == 3
        names = {d["name"] for d in result["documents"]}
        assert names == {"Morning Journal", "Architecture Sketch", "Empty Notebook"}

    @pytest.mark.unit
    def test_list_documents_with_search(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(search="journal")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Morning Journal"

    @pytest.mark.unit
    def test_list_documents_case_insensitive(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(search="ARCHITECTURE")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"

    @pytest.mark.unit
    def test_list_documents_no_match(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(search="nonexistent")
        assert result["count"] == 0
        assert result["documents"] == []

    @pytest.mark.unit
    def test_list_documents_empty_cache(self, empty_cache):
        client = RemarkableClient(base_path=empty_cache)
        result = client.list_documents()
        assert result["count"] == 0
        assert result["documents"] == []

    @pytest.mark.unit
    def test_list_documents_returns_metadata_fields(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(search="Morning")
        doc = result["documents"][0]
        assert "doc_id" in doc
        assert "name" in doc
        assert "page_count" in doc
        assert "last_modified" in doc
        assert doc["page_count"] == 3


# ---------------------------------------------------------------------------
# get_document_info
# ---------------------------------------------------------------------------

class TestGetDocumentInfo:
    @pytest.mark.unit
    def test_v2_format(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.get_document_info("aaaa-1111-2222-3333")
        assert result["name"] == "Morning Journal"
        assert result["page_count"] == 3
        assert result["page_ids"] == ["page-a1", "page-a2", "page-a3"]
        assert result["doc_id"] == "aaaa-1111-2222-3333"

    @pytest.mark.unit
    def test_v1_format(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.get_document_info("bbbb-4444-5555-6666")
        assert result["name"] == "Architecture Sketch"
        assert result["page_count"] == 2
        assert result["page_ids"] == ["page-b1", "page-b2"]

    @pytest.mark.unit
    def test_missing_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.get_document_info("does-not-exist")
        assert result["error"] is True
        assert "not found" in result["detail"].lower()


# ---------------------------------------------------------------------------
# render_pages
# ---------------------------------------------------------------------------

class TestRenderPages:
    @pytest.mark.unit
    def test_last_n_selection(self, fake_cache, render_dir):
        """last_n=2 on a 3-page doc should only render pages at index 1 and 2."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages("aaaa-1111-2222-3333", last_n=2)
        assert result["pages_rendered"] == 2
        assert result["page_indices"] == [1, 2]
        assert Path(result["pdf_path"]).exists()

    @pytest.mark.unit
    def test_first_n_selection(self, fake_cache, render_dir):
        """first_n=1 on a 3-page doc should render only page at index 0."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages("aaaa-1111-2222-3333", first_n=1)
        assert result["pages_rendered"] == 1
        assert result["page_indices"] == [0]

    @pytest.mark.unit
    def test_by_indices(self, fake_cache, render_dir):
        """Explicit page_indices selection."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages("aaaa-1111-2222-3333", page_indices=[0, 2])
        assert result["pages_rendered"] == 2
        assert result["page_indices"] == [0, 2]

    @pytest.mark.unit
    def test_indices_priority_over_last_n(self, fake_cache, render_dir):
        """page_indices takes priority over last_n."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages(
                "aaaa-1111-2222-3333", page_indices=[0], last_n=3
            )
        assert result["pages_rendered"] == 1
        assert result["page_indices"] == [0]

    @pytest.mark.unit
    def test_failed_pages_no_rm_file(self, fake_cache, render_dir):
        """Document with no .rm files should report all pages as failed."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        result = client.render_pages("cccc-7777-8888-9999")
        assert result["pages_rendered"] == 0
        assert len(result["pages_failed"]) == 1

    @pytest.mark.unit
    def test_out_of_bounds_indices(self, fake_cache, render_dir):
        """Out-of-range indices should appear in pages_failed."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages("aaaa-1111-2222-3333", page_indices=[0, 99])
        # Index 0 should render, index 99 should fail
        assert 99 in [f["index"] for f in result["pages_failed"]]

    @pytest.mark.unit
    def test_missing_document_error(self, fake_cache, render_dir):
        """Rendering a non-existent doc should return an error dict."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        result = client.render_pages("does-not-exist")
        assert result["error"] is True

    @pytest.mark.unit
    def test_render_all_pages(self, fake_cache, render_dir):
        """No selection args renders all pages."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages("aaaa-1111-2222-3333")
        assert result["pages_rendered"] == 3
        assert result["page_indices"] == [0, 1, 2]


# ---------------------------------------------------------------------------
# check_status
# ---------------------------------------------------------------------------

class TestCheckStatus:
    @pytest.mark.unit
    def test_cache_exists(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.check_status()
        assert result["cache_exists"] is True
        assert result["document_count"] == 3

    @pytest.mark.unit
    def test_cache_missing(self, empty_cache):
        client = RemarkableClient(base_path=empty_cache)
        result = client.check_status()
        assert result["cache_exists"] is False
        assert result["document_count"] == 0


# ---------------------------------------------------------------------------
# cleanup_renders
# ---------------------------------------------------------------------------

class TestCleanupRenders:
    @pytest.mark.unit
    def test_removes_files(self, render_dir):
        # Create some fake PDF files
        (render_dir / "doc1.pdf").write_bytes(b"fake pdf content 1")
        (render_dir / "doc2.pdf").write_bytes(b"fake pdf content 2")
        client = RemarkableClient(
            base_path=Path("/nonexistent"), render_dir=render_dir
        )
        result = client.cleanup_renders()
        assert result["files_removed"] == 2
        assert result["bytes_freed"] > 0
        assert not list(render_dir.iterdir())

    @pytest.mark.unit
    def test_empty_dir(self, render_dir):
        client = RemarkableClient(
            base_path=Path("/nonexistent"), render_dir=render_dir
        )
        result = client.cleanup_renders()
        assert result["files_removed"] == 0
        assert result["bytes_freed"] == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_rendering():
    """Context manager that patches rmc subprocess and cairosvg to produce fake PDFs.

    rmc: writes a minimal SVG to the output path.
    cairosvg.svg2pdf: returns minimal valid PDF bytes.
    """
    # Minimal valid PDF (enough for pypdf to parse)
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
        """Simulate rmc by writing a minimal SVG to the -o output path."""
        # args = ["rmc", "<input.rm>", "-o", "<output.svg>"]
        if "-o" in args:
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(minimal_svg)
        return MagicMock(returncode=0)

    def fake_svg2pdf(**kwargs):
        return minimal_pdf

    return patch.multiple(
        "remarkable_client",
        _run_rmc=fake_rmc,
        _svg_to_pdf_bytes=fake_svg2pdf,
    )
