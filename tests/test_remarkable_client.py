# ABOUTME: Unit tests for RemarkableClient using synthetic cache fixtures.
# ABOUTME: Covers document listing, metadata, page rendering, status checks, cleanup, and writes.

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from remarkable_mcp_redux.client import RemarkableClient
from tests.conftest import PERSONAL_FOLDER_ID, WORK_FOLDER_ID

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

    @pytest.mark.unit
    def test_list_documents_excludes_folders(self, fake_cache):
        """BUG-01: CollectionType records must not appear in list_documents results."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents()
        ids = {d["doc_id"] for d in result["documents"]}
        assert WORK_FOLDER_ID not in ids
        assert PERSONAL_FOLDER_ID not in ids
        types = {d.get("type") for d in result["documents"]}
        assert types == {"DocumentType"}

    @pytest.mark.unit
    def test_list_documents_includes_parent(self, fake_cache):
        """BUG-09: list_documents responses should expose the parent folder id."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(search="Architecture")
        doc = result["documents"][0]
        assert doc["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_list_documents_last_modified_is_iso(self, fake_cache):
        """BUG-09: lastModified should be returned as ISO-8601 instead of millis."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(search="Morning")
        last_mod = result["documents"][0]["last_modified"]
        assert isinstance(last_mod, str)
        parsed = datetime.fromisoformat(last_mod)
        expected = datetime.fromtimestamp(1709500000, tz=UTC)
        assert parsed == expected

    @pytest.mark.unit
    def test_list_documents_includes_content_fields(self, fake_cache):
        """BUG-11: enriched .content fields should land in list_documents responses."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(search="Architecture")
        doc = result["documents"][0]
        assert doc["file_type"] == "pdf"
        assert doc["document_title"] == "Software Architecture Patterns"
        assert doc["authors"] == ["Mark Richards"]
        assert doc["tags"] == ["Reference", "Architecture"]
        assert doc["annotated"] is True

    @pytest.mark.unit
    def test_list_documents_filter_by_file_type(self, fake_cache):
        """list_documents should support filtering on .content fileType."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(file_type="pdf")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"

    @pytest.mark.unit
    def test_list_documents_filter_by_tag(self, fake_cache):
        """list_documents should support filtering on a user-applied tag name."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(tag="Reference")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"


# ---------------------------------------------------------------------------
# list_folders
# ---------------------------------------------------------------------------


class TestListFolders:
    @pytest.mark.unit
    def test_list_folders_returns_collection_records(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders()
        assert result["count"] == 2
        names = {f["name"] for f in result["folders"]}
        assert names == {"Work", "Personal"}

    @pytest.mark.unit
    def test_list_folders_includes_parent_and_id(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders()
        ids = {f["folder_id"] for f in result["folders"]}
        assert ids == {WORK_FOLDER_ID, PERSONAL_FOLDER_ID}
        for folder in result["folders"]:
            assert folder["parent"] == ""

    @pytest.mark.unit
    def test_list_folders_search_filter(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders(search="work")
        assert result["count"] == 1
        assert result["folders"][0]["name"] == "Work"

    @pytest.mark.unit
    def test_list_folders_excludes_documents(self, fake_cache):
        """list_folders must not surface DocumentType records."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders()
        for folder in result["folders"]:
            assert "doc_id" not in folder

    @pytest.mark.unit
    def test_list_folders_empty_cache(self, empty_cache):
        client = RemarkableClient(base_path=empty_cache)
        result = client.list_folders()
        assert result["count"] == 0
        assert result["folders"] == []


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

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache):
        """BUG-04: get_document_info should refuse CollectionType records."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.get_document_info(WORK_FOLDER_ID)
        assert result["error"] is True
        assert "folder" in result["detail"].lower() or "collection" in result["detail"].lower()

    @pytest.mark.unit
    def test_includes_enriched_content_fields(self, fake_cache):
        """BUG-11: get_document_info should include file_type, title, authors, tags, etc."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.get_document_info("bbbb-4444-5555-6666")
        assert result["file_type"] == "pdf"
        assert result["document_title"] == "Software Architecture Patterns"
        assert result["authors"] == ["Mark Richards"]
        assert result["tags"] == ["Reference", "Architecture"]
        assert result["annotated"] is True
        assert result["original_page_count"] == 42
        assert result["size_in_bytes"] == 123456
        assert result["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_handles_ios_doc_with_missing_optional_fields(self, ios_doc_cache):
        """BUG-08: iOS-sourced records lack optional fields; client should not error."""
        client = RemarkableClient(base_path=ios_doc_cache)
        result = client.get_document_info("ios-aaaa-1111")
        assert result.get("error") is not True
        assert result["name"] == "iOS Transfer"
        assert result["page_count"] == 1


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

    @pytest.mark.unit
    def test_rejects_empty_page_indices(self, fake_cache, render_dir):
        """BUG-05: page_indices=[] should produce a clear error, not render everything."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages("aaaa-1111-2222-3333", page_indices=[])
        assert result["error"] is True
        assert "page_indices" in result["detail"]

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache, render_dir):
        """BUG-04: render_pages should refuse CollectionType records."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        result = client.render_pages(WORK_FOLDER_ID)
        assert result["error"] is True
        assert "folder" in result["detail"].lower() or "collection" in result["detail"].lower()

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
            "remarkable_mcp_redux.render",
            _run_rmc=fake_rmc_fail,
        ):
            result = client.render_pages("aaaa-1111-2222-3333", first_n=1)

        assert result["pages_rendered"] == 0
        assert len(result["pages_failed"]) == 1
        assert "rmc" in result["pages_failed"][0]["reason"].lower()


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
# rename_document
# ---------------------------------------------------------------------------


class TestRenameDocument:
    @pytest.mark.unit
    def test_renames_visible_name_on_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_document("aaaa-1111-2222-3333", "Renamed Journal")
        assert result.get("error") is not True
        assert result["dry_run"] is False
        assert result["old_name"] == "Morning Journal"
        assert result["new_name"] == "Renamed Journal"

        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Renamed Journal"

    @pytest.mark.unit
    def test_dry_run_does_not_modify_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_document(
            "aaaa-1111-2222-3333", "X", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["old_name"] == "Morning Journal"
        assert result["new_name"] == "X"
        assert "backup_path" not in result

        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Morning Journal"
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_creates_timestamped_backup(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_document("aaaa-1111-2222-3333", "Renamed")
        backup_path = Path(result["backup_path"])
        assert backup_path.exists()
        assert backup_path.name.startswith("aaaa-1111-2222-3333.metadata.bak.")
        backup_data = json.loads(backup_path.read_text())
        assert backup_data["visibleName"] == "Morning Journal"

    @pytest.mark.unit
    def test_updates_last_modified_timestamp(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        before = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["lastModified"]
        client.rename_document("aaaa-1111-2222-3333", "Renamed")
        after = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["lastModified"]
        assert int(after) > int(before)

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_document(WORK_FOLDER_ID, "X")
        assert result["error"] is True
        assert "folder" in result["detail"].lower()
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Work"

    @pytest.mark.unit
    def test_rejects_missing_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_document("does-not-exist", "X")
        assert result["error"] is True
        assert "not found" in result["detail"].lower()

    @pytest.mark.unit
    def test_rejects_empty_name(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_document("aaaa-1111-2222-3333", "   ")
        assert result["error"] is True
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Morning Journal"


# ---------------------------------------------------------------------------
# move_document
# ---------------------------------------------------------------------------


class TestMoveDocument:
    @pytest.mark.unit
    def test_moves_doc_into_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document("aaaa-1111-2222-3333", WORK_FOLDER_ID)
        assert result.get("error") is not True
        assert result["old_parent"] == ""
        assert result["new_parent"] == WORK_FOLDER_ID
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_moves_doc_to_root(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document("bbbb-4444-5555-6666", "")
        assert result.get("error") is not True
        assert result["old_parent"] == WORK_FOLDER_ID
        assert result["new_parent"] == ""
        on_disk = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.metadata").read_text()
        )
        assert on_disk["parent"] == ""

    @pytest.mark.unit
    def test_dry_run_does_not_modify_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document(
            "aaaa-1111-2222-3333", WORK_FOLDER_ID, dry_run=True
        )
        assert result["dry_run"] is True
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["parent"] == ""
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_rejects_unknown_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document(
            "aaaa-1111-2222-3333", "nonexistent-folder"
        )
        assert result["error"] is True
        assert "folder" in result["detail"].lower()

    @pytest.mark.unit
    def test_rejects_document_as_parent(self, fake_cache):
        """Moving into another document is invalid: targets must be CollectionType."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document(
            "aaaa-1111-2222-3333", "bbbb-4444-5555-6666"
        )
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_self_as_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document(
            "aaaa-1111-2222-3333", "aaaa-1111-2222-3333"
        )
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_collection_source(self, fake_cache):
        """Cannot move a folder via this tool (folder moves are out of scope)."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document(WORK_FOLDER_ID, "")
        assert result["error"] is True

    @pytest.mark.unit
    def test_creates_timestamped_backup(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document("aaaa-1111-2222-3333", WORK_FOLDER_ID)
        backup_path = Path(result["backup_path"])
        assert backup_path.exists()
        assert backup_path.name.startswith("aaaa-1111-2222-3333.metadata.bak.")


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
        "remarkable_mcp_redux.render",
        _run_rmc=fake_rmc,
        _svg_to_pdf_bytes=fake_svg2pdf,
    )
