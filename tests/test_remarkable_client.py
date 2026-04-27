# ABOUTME: Unit tests for RemarkableClient using synthetic cache fixtures.
# ABOUTME: Covers document listing, metadata, page rendering, status checks, cleanup, and writes.

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from remarkable_mcp_redux.client import RemarkableClient
from remarkable_mcp_redux.config import BACKUP_RETENTION_ENV_VAR
from tests.conftest import (
    LEGACY_V5_DOC_ID,
    MIXED_PDF_DOC_ID,
    NESTED_DOC_INSIDE_C,
    NESTED_FOLDER_A,
    NESTED_FOLDER_B,
    NESTED_FOLDER_C,
    NESTED_FOLDER_D,
    PERSONAL_FOLDER_ID,
    PINNED_DOC_ID,
    PINNED_FOLDER_ID,
    TRASHED_DOC_ID,
    UNANNOTATED_PDF_DOC_ID,
    WORK_FOLDER_ID,
)

# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------

class TestListDocuments:
    @pytest.mark.unit
    def test_list_all_documents(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents()
        assert result["count"] == 5
        names = {d["name"] for d in result["documents"]}
        assert names == {
            "Morning Journal",
            "Architecture Sketch",
            "Empty Notebook",
            "Trashed Note",
            "Pinned Reference",
        }

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

    @pytest.mark.unit
    def test_list_documents_filter_by_pinned_true(self, fake_cache):
        """pinned=True should return only pinned/favorited documents."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(pinned=True)
        assert result["count"] == 1
        assert result["documents"][0]["doc_id"] == PINNED_DOC_ID
        assert result["documents"][0]["pinned"] is True

    @pytest.mark.unit
    def test_list_documents_filter_by_pinned_false(self, fake_cache):
        """pinned=False should exclude pinned records and return the rest."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(pinned=False)
        ids = {d["doc_id"] for d in result["documents"]}
        assert PINNED_DOC_ID not in ids
        assert result["total_count"] == 4
        assert all(d["pinned"] is False for d in result["documents"])

    @pytest.mark.unit
    def test_list_documents_includes_pinned_field(self, fake_cache):
        """Every list_documents row should expose the pinned boolean."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents()
        by_id = {d["doc_id"]: d for d in result["documents"]}
        assert by_id[PINNED_DOC_ID]["pinned"] is True
        for doc_id, doc in by_id.items():
            assert isinstance(doc["pinned"], bool)
            if doc_id != PINNED_DOC_ID:
                assert doc["pinned"] is False


# ---------------------------------------------------------------------------
# list_documents pagination + parent filter
# ---------------------------------------------------------------------------


class TestListDocumentsPagination:
    @pytest.mark.unit
    def test_default_includes_pagination_metadata(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents()
        assert result["count"] == 5
        assert result["total_count"] == 5
        assert result["limit"] == 50
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert "parent" not in result

    @pytest.mark.unit
    def test_limit_truncates_page_and_sets_has_more(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(limit=2)
        assert result["count"] == 2
        assert result["total_count"] == 5
        assert result["limit"] == 2
        assert result["offset"] == 0
        assert result["has_more"] is True
        assert len(result["documents"]) == 2

    @pytest.mark.unit
    def test_offset_advances_to_disjoint_page(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        first = client.list_documents(limit=2, offset=0)["documents"]
        second = client.list_documents(limit=2, offset=2)["documents"]
        first_ids = {d["doc_id"] for d in first}
        second_ids = {d["doc_id"] for d in second}
        assert first_ids.isdisjoint(second_ids)

    @pytest.mark.unit
    def test_offset_past_end_returns_empty_page(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(limit=10, offset=100)
        assert result["count"] == 0
        assert result["documents"] == []
        assert result["total_count"] == 5
        assert result["has_more"] is False

    @pytest.mark.unit
    def test_parent_root_filter_excludes_subfolder_docs(self, fake_cache):
        """parent="" returns only root-level docs; the doc under WORK_FOLDER_ID is excluded."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(parent="")
        names = {d["name"] for d in result["documents"]}
        assert "Architecture Sketch" not in names
        assert result["parent"] == ""
        assert result["total_count"] == 4

    @pytest.mark.unit
    def test_parent_folder_filter_returns_direct_children(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(parent=WORK_FOLDER_ID)
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"
        assert result["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_parent_unknown_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(parent="does-not-exist")
        assert result["error"] is True
        assert "not found" in result["detail"].lower()

    @pytest.mark.unit
    def test_parent_non_folder_returns_error(self, fake_cache):
        """Filtering by a document id (not a folder) is a hard error."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(parent="aaaa-1111-2222-3333")
        assert result["error"] is True
        assert "folder" in result["detail"].lower()

    @pytest.mark.unit
    def test_invalid_limit_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(limit=0)
        assert result["error"] is True
        assert "limit" in result["detail"].lower()

    @pytest.mark.unit
    def test_invalid_offset_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(offset=-1)
        assert result["error"] is True
        assert "offset" in result["detail"].lower()

    @pytest.mark.unit
    def test_pagination_composes_with_filters(self, fake_cache):
        """Filters apply before pagination so total_count reflects the filtered set."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_documents(file_type="notebook", limit=2)
        assert result["total_count"] == 4
        assert result["count"] == 2
        assert result["has_more"] is True
        for doc in result["documents"]:
            assert doc["file_type"] == "notebook"


# ---------------------------------------------------------------------------
# list_folders
# ---------------------------------------------------------------------------


class TestListFolders:
    @pytest.mark.unit
    def test_list_folders_returns_collection_records(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders()
        assert result["count"] == 3
        names = {f["name"] for f in result["folders"]}
        assert names == {"Work", "Personal", "Favorites"}

    @pytest.mark.unit
    def test_list_folders_includes_parent_and_id(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders()
        ids = {f["folder_id"] for f in result["folders"]}
        assert ids == {WORK_FOLDER_ID, PERSONAL_FOLDER_ID, PINNED_FOLDER_ID}
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

    @pytest.mark.unit
    def test_list_folders_filter_by_pinned_true(self, fake_cache):
        """pinned=True should return only pinned/favorited folders."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders(pinned=True)
        assert result["count"] == 1
        assert result["folders"][0]["folder_id"] == PINNED_FOLDER_ID
        assert result["folders"][0]["pinned"] is True

    @pytest.mark.unit
    def test_list_folders_includes_pinned_field(self, fake_cache):
        """Every list_folders row should expose the pinned boolean."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders()
        by_id = {f["folder_id"]: f for f in result["folders"]}
        assert by_id[PINNED_FOLDER_ID]["pinned"] is True
        for folder_id, folder in by_id.items():
            assert isinstance(folder["pinned"], bool)
            if folder_id != PINNED_FOLDER_ID:
                assert folder["pinned"] is False


# ---------------------------------------------------------------------------
# list_folders pagination + parent filter
# ---------------------------------------------------------------------------


class TestListFoldersPagination:
    @pytest.mark.unit
    def test_default_includes_pagination_metadata(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders()
        assert result["count"] == 3
        assert result["total_count"] == 3
        assert result["limit"] == 100
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert "parent" not in result

    @pytest.mark.unit
    def test_limit_truncates_page_and_sets_has_more(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders(limit=1)
        assert result["count"] == 1
        assert result["total_count"] == 3
        assert result["has_more"] is True

    @pytest.mark.unit
    def test_offset_advances_to_disjoint_page(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        first = client.list_folders(limit=1, offset=0)["folders"]
        second = client.list_folders(limit=1, offset=1)["folders"]
        assert first[0]["folder_id"] != second[0]["folder_id"]

    @pytest.mark.unit
    def test_parent_root_filter(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.list_folders(parent="")
        names = {f["name"] for f in result["folders"]}
        assert names == {"A", "D"}
        assert result["total_count"] == 2
        assert result["parent"] == ""

    @pytest.mark.unit
    def test_parent_folder_filter_returns_direct_children(self, nested_folder_cache):
        """B is the only direct child of A; C lives under B and must not appear."""
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.list_folders(parent=NESTED_FOLDER_A)
        assert result["count"] == 1
        assert result["folders"][0]["name"] == "B"
        assert result["parent"] == NESTED_FOLDER_A

    @pytest.mark.unit
    def test_parent_unknown_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders(parent="does-not-exist")
        assert result["error"] is True
        assert "not found" in result["detail"].lower()

    @pytest.mark.unit
    def test_parent_non_folder_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders(parent="aaaa-1111-2222-3333")
        assert result["error"] is True
        assert "folder" in result["detail"].lower()

    @pytest.mark.unit
    def test_invalid_limit_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders(limit=0)
        assert result["error"] is True
        assert "limit" in result["detail"].lower()

    @pytest.mark.unit
    def test_invalid_offset_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.list_folders(offset=-1)
        assert result["error"] is True
        assert "offset" in result["detail"].lower()


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

    @pytest.mark.unit
    def test_includes_pinned_field(self, fake_cache):
        """get_document_info should expose the pinned boolean for both states."""
        client = RemarkableClient(base_path=fake_cache)
        pinned_result = client.get_document_info(PINNED_DOC_ID)
        assert pinned_result["pinned"] is True
        unpinned_result = client.get_document_info("aaaa-1111-2222-3333")
        assert unpinned_result["pinned"] is False


# ---------------------------------------------------------------------------
# get_document_info include_page_ids opt-out
# ---------------------------------------------------------------------------


class TestGetDocumentInfoIncludePageIds:
    @pytest.mark.unit
    def test_default_includes_full_page_ids(self, fake_cache):
        """Default behavior must remain backward compatible."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.get_document_info("aaaa-1111-2222-3333")
        assert result["page_ids"] == ["page-a1", "page-a2", "page-a3"]
        assert result["page_count"] == 3
        assert "first_page_id" not in result
        assert "last_page_id" not in result

    @pytest.mark.unit
    def test_opt_out_omits_page_ids_and_exposes_endpoints(self, fake_cache):
        """include_page_ids=False drops the array but keeps page_count + endpoints."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.get_document_info(
            "aaaa-1111-2222-3333", include_page_ids=False
        )
        assert "page_ids" not in result
        assert result["page_count"] == 3
        assert result["first_page_id"] == "page-a1"
        assert result["last_page_id"] == "page-a3"

    @pytest.mark.unit
    def test_opt_out_on_empty_document_returns_none_endpoints(self, tmp_path):
        """An empty cPages list yields None for first_page_id and last_page_id."""
        metadata = {
            "type": "DocumentType",
            "visibleName": "No Pages",
            "parent": "",
            "lastModified": "1709500000000",
        }
        content = {
            "fileType": "notebook",
            "formatVersion": 2,
            "cPages": {"pages": []},
            "documentMetadata": {},
            "extraMetadata": {},
            "tags": [],
            "pageCount": 0,
            "originalPageCount": -1,
            "sizeInBytes": "0",
        }
        (tmp_path / "no-pages.metadata").write_text(json.dumps(metadata))
        (tmp_path / "no-pages.content").write_text(json.dumps(content))
        client = RemarkableClient(base_path=tmp_path)
        result = client.get_document_info("no-pages", include_page_ids=False)
        assert result["page_count"] == 0
        assert result["first_page_id"] is None
        assert result["last_page_id"] is None


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
        """Notebook with no .rm files (and no source PDF) reports all pages as failed.

        ``Empty Notebook`` is a notebook fixture, so PDF passthrough is not
        applicable — the only thing the dispatcher can do is emit ``no_source``.
        """
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        result = client.render_pages("cccc-7777-8888-9999")
        assert result["pages_rendered"] == 0
        assert len(result["pages_failed"]) == 1
        assert result["pages_failed"][0]["code"] == "no_source"

    @pytest.mark.unit
    def test_out_of_bounds_indices(self, fake_cache, render_dir):
        """Out-of-range indices should appear in pages_failed with code=out_of_bounds."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        with _mock_rendering():
            result = client.render_pages("aaaa-1111-2222-3333", page_indices=[0, 99])
        failed = [f for f in result["pages_failed"] if f["index"] == 99]
        assert len(failed) == 1
        assert failed[0]["code"] == "out_of_bounds"

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
            "remarkable_mcp_redux._render",
            _run_rmc=fake_rmc_fail,
        ):
            result = client.render_pages("aaaa-1111-2222-3333", first_n=1)

        assert result["pages_rendered"] == 0
        assert len(result["pages_failed"]) == 1
        assert "rmc" in result["pages_failed"][0]["reason"].lower()
        assert result["pages_failed"][0]["code"] == "rmc_failed"


# ---------------------------------------------------------------------------
# render_pages — page-source dispatch (PDF passthrough, v5 detection, mixed)
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
        result = client.render_pages(UNANNOTATED_PDF_DOC_ID)
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
        result = client.render_pages(LEGACY_V5_DOC_ID)
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
            result = client.render_pages(MIXED_PDF_DOC_ID)
        assert result["pages_rendered"] == 3
        assert result["pages_failed"] == []
        assert result["sources_used"] == {"rm_v6": 1, "pdf_passthrough": 2}

    @pytest.mark.unit
    def test_sources_used_omitted_when_no_pages_rendered(
        self, legacy_v5_cache, render_dir
    ):
        """Failure-only responses should not advertise an empty sources_used dict."""
        client = RemarkableClient(base_path=legacy_v5_cache, render_dir=render_dir)
        result = client.render_pages(LEGACY_V5_DOC_ID)
        assert result.get("sources_used", {}) == {}

    @pytest.mark.unit
    def test_unannotated_notebook_pages_are_no_source(self, fake_cache, render_dir):
        """Empty Notebook is type=notebook with no source PDF; expect code=no_source."""
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        result = client.render_pages("cccc-7777-8888-9999")
        assert result["pages_failed"]
        for entry in result["pages_failed"]:
            assert entry["code"] == "no_source"


# ---------------------------------------------------------------------------
# check_status
# ---------------------------------------------------------------------------

class TestCheckStatus:
    @pytest.mark.unit
    def test_cache_exists(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.check_status()
        assert result["cache_exists"] is True
        assert result["document_count"] == 5

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
        "remarkable_mcp_redux._render",
        _run_rmc=fake_rmc,
        _svg_to_pdf_bytes=fake_svg2pdf,
    )


# ---------------------------------------------------------------------------
# Sync flags - every write path must set metadatamodified and modified
# ---------------------------------------------------------------------------


class TestSyncFlags:
    """All write paths must set metadatamodified=True and modified=True so the
    reMarkable desktop sync engine recognises the change as a local edit."""

    @pytest.mark.unit
    def test_rename_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.rename_document("aaaa-1111-2222-3333", "Renamed")
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_move_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.move_document("aaaa-1111-2222-3333", WORK_FOLDER_ID)
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_pin_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.pin_document("aaaa-1111-2222-3333", True)
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_create_folder_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Newly Created")
        folder_id = result["folder_id"]
        on_disk = json.loads((fake_cache / f"{folder_id}.metadata").read_text())
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_restore_writes_resurrect_sync_flags(self, fake_cache):
        """A restore writes the backup contents back; the backup itself was made
        before sync flags were set, but the post-restore safety backup must
        capture the live (sync-flags-True) state. The restored file matches
        whatever was in the backup."""
        client = RemarkableClient(base_path=fake_cache)
        # First write to create a backup that has sync flags True
        client.rename_document("aaaa-1111-2222-3333", "First Rename")
        client.rename_document("aaaa-1111-2222-3333", "Second Rename")
        client.restore_metadata("aaaa-1111-2222-3333")
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        # Restored content originated from a backup taken after a write,
        # so it carries sync flags True.
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True


# ---------------------------------------------------------------------------
# Refuse trashed records on rename/move/pin
# ---------------------------------------------------------------------------


class TestRefuseDeleted:
    @pytest.mark.unit
    def test_rename_refuses_trashed(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_document(TRASHED_DOC_ID, "Anything")
        assert result["error"] is True
        assert "trash" in result["detail"].lower()

    @pytest.mark.unit
    def test_move_refuses_trashed(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document(TRASHED_DOC_ID, WORK_FOLDER_ID)
        assert result["error"] is True
        assert "trash" in result["detail"].lower()

    @pytest.mark.unit
    def test_move_rejects_trash_destination(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_document("aaaa-1111-2222-3333", "trash")
        assert result["error"] is True
        assert "trash" in result["detail"].lower()

    @pytest.mark.unit
    def test_pin_refuses_trashed(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.pin_document(TRASHED_DOC_ID, True)
        assert result["error"] is True
        assert "trash" in result["detail"].lower()


# ---------------------------------------------------------------------------
# is_descendant_of cache helper
# ---------------------------------------------------------------------------


class TestIsDescendantOf:
    @pytest.mark.unit
    def test_direct_child(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        assert client.cache.is_descendant_of(NESTED_FOLDER_B, NESTED_FOLDER_A) is True

    @pytest.mark.unit
    def test_transitive_descendant(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        assert client.cache.is_descendant_of(NESTED_FOLDER_C, NESTED_FOLDER_A) is True

    @pytest.mark.unit
    def test_self_is_descendant_of_self(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        assert client.cache.is_descendant_of(NESTED_FOLDER_A, NESTED_FOLDER_A) is True

    @pytest.mark.unit
    def test_sibling_is_not_descendant(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        assert client.cache.is_descendant_of(NESTED_FOLDER_D, NESTED_FOLDER_A) is False

    @pytest.mark.unit
    def test_unknown_id_returns_false(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        assert client.cache.is_descendant_of("nope", NESTED_FOLDER_A) is False

    @pytest.mark.unit
    def test_handles_malformed_cycle(self, tmp_path):
        """If two folders illegally refer to each other as parents, the helper
        must terminate via its visited-set rather than loop forever."""
        cycle_a = "cycle-a"
        cycle_b = "cycle-b"
        (tmp_path / f"{cycle_a}.metadata").write_text(
            json.dumps(
                {
                    "type": "CollectionType",
                    "visibleName": "A",
                    "parent": cycle_b,
                    "lastModified": "1",
                }
            )
        )
        (tmp_path / f"{cycle_b}.metadata").write_text(
            json.dumps(
                {
                    "type": "CollectionType",
                    "visibleName": "B",
                    "parent": cycle_a,
                    "lastModified": "1",
                }
            )
        )
        client = RemarkableClient(base_path=tmp_path)
        # Asking whether a cycle node is a descendant of an outsider must just
        # return False without hanging.
        assert client.cache.is_descendant_of(cycle_a, "outsider") is False

    @pytest.mark.unit
    def test_count_descendants_includes_transitive(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        # A's subtree contains B, C, and the doc inside C: 3 descendants.
        assert client.cache.count_descendants(NESTED_FOLDER_A) == 3

    @pytest.mark.unit
    def test_count_descendants_leaf_folder(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        # D has no descendants.
        assert client.cache.count_descendants(NESTED_FOLDER_D) == 0


# ---------------------------------------------------------------------------
# Backup retention - auto-prune and env override
# ---------------------------------------------------------------------------


class TestBackupRetention:
    @pytest.mark.unit
    def test_keeps_last_five_by_default(self, fake_cache, monkeypatch):
        monkeypatch.delenv(BACKUP_RETENTION_ENV_VAR, raising=False)
        client = RemarkableClient(base_path=fake_cache)
        for i in range(8):
            client.rename_document("aaaa-1111-2222-3333", f"Name {i}")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 5

    @pytest.mark.unit
    def test_retention_zero_keeps_only_pre_write_backup(self, fake_cache, monkeypatch):
        """retention=0 means "delete every backup older than the one just made".
        After a single rename, the backup chain is empty (the backup made by the
        rename itself is also pruned because retention=0 is "keep zero")."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "0")
        client = RemarkableClient(base_path=fake_cache)
        client.rename_document("aaaa-1111-2222-3333", "Once")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 0

    @pytest.mark.unit
    def test_env_override_keeps_two(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "2")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(5):
            client.rename_document("aaaa-1111-2222-3333", f"Name {i}")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 2

    @pytest.mark.unit
    def test_invalid_env_falls_back_to_default(
        self, fake_cache, monkeypatch
    ):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "not-a-number")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(7):
            client.rename_document("aaaa-1111-2222-3333", f"Name {i}")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 5  # default

    @pytest.mark.unit
    def test_retention_isolates_documents(self, fake_cache, monkeypatch):
        """Pruning one document's chain must not delete another document's backups."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "1")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(3):
            client.rename_document("aaaa-1111-2222-3333", f"A{i}")
        for i in range(3):
            client.rename_document("bbbb-4444-5555-6666", f"B{i}")
        a_backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        b_backups = list(fake_cache.glob("bbbb-4444-5555-6666.metadata.bak.*"))
        assert len(a_backups) == 1
        assert len(b_backups) == 1


# ---------------------------------------------------------------------------
# cleanup_metadata_backups bulk tool
# ---------------------------------------------------------------------------


class TestCleanupBackupsTool:
    @pytest.mark.unit
    def test_refuses_no_filters(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.cleanup_metadata_backups()
        assert result["error"] is True
        assert "filter" in result["detail"].lower()

    @pytest.mark.unit
    def test_doc_id_filter_targets_single_chain(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")  # do not auto-prune
        client = RemarkableClient(base_path=fake_cache)
        for i in range(3):
            client.rename_document("aaaa-1111-2222-3333", f"A{i}")
        for i in range(3):
            client.rename_document("bbbb-4444-5555-6666", f"B{i}")
        result = client.cleanup_metadata_backups(doc_id="aaaa-1111-2222-3333")
        assert result.get("error") is not True
        assert result["files_removed"] == 3
        # B's chain untouched
        b_backups = list(fake_cache.glob("bbbb-4444-5555-6666.metadata.bak.*"))
        assert len(b_backups) == 3

    @pytest.mark.unit
    def test_older_than_zero_wipes_everything(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(2):
            client.rename_document("aaaa-1111-2222-3333", f"A{i}")
        result = client.cleanup_metadata_backups(older_than_days=0)
        assert result.get("error") is not True
        assert result["files_removed"] >= 2
        backups = list(fake_cache.glob("*.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_older_than_high_keeps_recent(self, fake_cache, monkeypatch):
        """With a future cutoff (older_than_days=365), recent backups stay put."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(3):
            client.rename_document("aaaa-1111-2222-3333", f"A{i}")
        result = client.cleanup_metadata_backups(older_than_days=365)
        assert result["files_removed"] == 0
        assert result["backups_remaining"] == 3

    @pytest.mark.unit
    def test_dry_run_preserves_files(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(2):
            client.rename_document("aaaa-1111-2222-3333", f"A{i}")
        result = client.cleanup_metadata_backups(older_than_days=0, dry_run=True)
        assert result["dry_run"] is True
        assert result["files_removed"] == 2
        # disk untouched
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 2


# ---------------------------------------------------------------------------
# pin_document
# ---------------------------------------------------------------------------


class TestPinTool:
    @pytest.mark.unit
    def test_pins_a_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.pin_document("aaaa-1111-2222-3333", True)
        assert result.get("error") is not True
        assert result["new_pinned"] is True
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["pinned"] is True

    @pytest.mark.unit
    def test_unpins_a_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.pin_document(PINNED_DOC_ID, False)
        assert result.get("error") is not True
        assert result["old_pinned"] is True
        assert result["new_pinned"] is False
        on_disk = json.loads((fake_cache / f"{PINNED_DOC_ID}.metadata").read_text())
        assert on_disk["pinned"] is False

    @pytest.mark.unit
    def test_idempotent_repin(self, fake_cache):
        """Pinning an already-pinned doc still succeeds and writes."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.pin_document(PINNED_DOC_ID, True)
        assert result.get("error") is not True
        assert result["new_pinned"] is True

    @pytest.mark.unit
    def test_dry_run_no_change(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        before = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["pinned"]
        result = client.pin_document(
            "aaaa-1111-2222-3333", True, dry_run=True
        )
        assert result["dry_run"] is True
        after = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["pinned"]
        assert before == after

    @pytest.mark.unit
    def test_rejects_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.pin_document(WORK_FOLDER_ID, True)
        assert result["error"] is True


# ---------------------------------------------------------------------------
# restore_metadata
# ---------------------------------------------------------------------------


class TestRestoreTool:
    @pytest.mark.unit
    def test_round_trip_restore(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        original = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        client.rename_document("aaaa-1111-2222-3333", "Renamed")
        result = client.restore_metadata("aaaa-1111-2222-3333")
        assert result.get("error") is not True
        restored = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert restored["visibleName"] == original["visibleName"]

    @pytest.mark.unit
    def test_creates_pre_restore_backup(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.rename_document("aaaa-1111-2222-3333", "Renamed")
        before_count = len(
            list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        )
        result = client.restore_metadata("aaaa-1111-2222-3333")
        after_count = len(
            list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        )
        # Pre-restore backup added; the consumed backup was the latest one.
        # Net change depends on retention; pre_restore_backup exists either way.
        assert Path(result["pre_restore_backup"]).exists()
        assert after_count >= before_count or Path(result["pre_restore_backup"]).exists()

    @pytest.mark.unit
    def test_no_backups_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.restore_metadata("aaaa-1111-2222-3333")
        assert result["error"] is True
        assert "backup" in result["detail"].lower()

    @pytest.mark.unit
    def test_missing_doc_returns_error(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.restore_metadata("nonexistent-doc")
        assert result["error"] is True

    @pytest.mark.unit
    def test_dry_run_reports_source(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.rename_document("aaaa-1111-2222-3333", "Renamed")
        result = client.restore_metadata("aaaa-1111-2222-3333", dry_run=True)
        assert result["dry_run"] is True
        assert "would_restore_from" in result
        # disk content was NOT reverted by dry-run
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Renamed"


# ---------------------------------------------------------------------------
# create_folder
# ---------------------------------------------------------------------------


class TestCreateFolder:
    @pytest.mark.unit
    def test_creates_root_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Brand New")
        assert result.get("error") is not True
        folder_id = result["folder_id"]
        meta = json.loads((fake_cache / f"{folder_id}.metadata").read_text())
        assert meta["type"] == "CollectionType"
        assert meta["visibleName"] == "Brand New"
        assert meta["parent"] == ""
        assert meta["deleted"] is False
        assert (fake_cache / f"{folder_id}.content").exists()

    @pytest.mark.unit
    def test_creates_nested_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Subfolder", parent=WORK_FOLDER_ID)
        assert result.get("error") is not True
        meta = json.loads((fake_cache / f"{result['folder_id']}.metadata").read_text())
        assert meta["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_rejects_empty_name(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("   ")
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_trash_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Doomed", parent="trash")
        assert result["error"] is True
        assert "trash" in result["detail"].lower()

    @pytest.mark.unit
    def test_rejects_missing_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Lost", parent="nonexistent-folder")
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_document_as_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Bad", parent="aaaa-1111-2222-3333")
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_duplicate_sibling_name(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Work")  # collides with WORK_FOLDER_ID
        assert result["error"] is True
        assert "exists" in result["detail"].lower()

    @pytest.mark.unit
    def test_duplicate_check_is_case_insensitive(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("WORK")
        assert result["error"] is True

    @pytest.mark.unit
    def test_duplicate_allowed_under_different_parents(self, fake_cache):
        """Same folder name is fine when parents differ."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Work", parent=PERSONAL_FOLDER_ID)
        assert result.get("error") is not True

    @pytest.mark.unit
    def test_dry_run_does_not_write(self, fake_cache):
        before = set(fake_cache.glob("*.metadata"))
        client = RemarkableClient(base_path=fake_cache)
        result = client.create_folder("Plan-only", dry_run=True)
        assert result["dry_run"] is True
        after = set(fake_cache.glob("*.metadata"))
        assert before == after

    @pytest.mark.unit
    def test_orphan_content_cleaned_on_metadata_failure(
        self, fake_cache, monkeypatch
    ):
        """If the .metadata write fails, the .content sibling must be removed."""
        from remarkable_mcp_redux import _writes as writes_module

        original_write = writes_module._atomic_write_json
        calls = {"n": 0}

        def flaky_write(target, data):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("boom")
            return original_write(target, data)

        monkeypatch.setattr(writes_module, "_atomic_write_json", flaky_write)
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(OSError):
            client.create_folder("Doomed Folder")
        # No orphan .content should remain.
        orphans = [
            p for p in fake_cache.glob("*.content") if not (p.with_suffix(".metadata")).exists()
        ]
        assert orphans == []


# ---------------------------------------------------------------------------
# rename_folder
# ---------------------------------------------------------------------------


class TestFolderRename:
    @pytest.mark.unit
    def test_renames_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_folder(WORK_FOLDER_ID, "Workspace")
        assert result.get("error") is not True
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Workspace"

    @pytest.mark.unit
    def test_rejects_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_folder("aaaa-1111-2222-3333", "Should fail")
        assert result["error"] is True
        assert "document" in result["detail"].lower()

    @pytest.mark.unit
    def test_rejects_duplicate_sibling(self, fake_cache):
        """Renaming Work to "Personal" collides with the existing sibling Personal."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_folder(WORK_FOLDER_ID, "Personal")
        assert result["error"] is True

    @pytest.mark.unit
    def test_idempotent_self_rename_allowed(self, fake_cache):
        """Renaming to the same name is a no-conflict sibling-uniqueness case."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_folder(WORK_FOLDER_ID, "Work")
        assert result.get("error") is not True

    @pytest.mark.unit
    def test_dry_run_no_change(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.rename_folder(WORK_FOLDER_ID, "Workspace", dry_run=True)
        assert result["dry_run"] is True
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Work"


# ---------------------------------------------------------------------------
# move_folder
# ---------------------------------------------------------------------------


class TestFolderMove:
    @pytest.mark.unit
    def test_moves_folder(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.move_folder(NESTED_FOLDER_D, NESTED_FOLDER_A)
        assert result.get("error") is not True
        on_disk = json.loads(
            (nested_folder_cache / f"{NESTED_FOLDER_D}.metadata").read_text()
        )
        assert on_disk["parent"] == NESTED_FOLDER_A

    @pytest.mark.unit
    def test_reports_descendants_affected(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.move_folder(NESTED_FOLDER_A, NESTED_FOLDER_D)
        # A's subtree contains B, C, and the doc inside C: 3 descendants.
        assert result["descendants_affected"] == 3

    @pytest.mark.unit
    def test_rejects_self_as_parent(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.move_folder(NESTED_FOLDER_A, NESTED_FOLDER_A)
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_descendant_as_parent(self, nested_folder_cache):
        """Cycle prevention: cannot move A under its own descendant C."""
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.move_folder(NESTED_FOLDER_A, NESTED_FOLDER_C)
        assert result["error"] is True
        assert "subtree" in result["detail"].lower()

    @pytest.mark.unit
    def test_rejects_trash_destination(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.move_folder(NESTED_FOLDER_A, "trash")
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_document_target(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.move_folder(NESTED_FOLDER_A, NESTED_DOC_INSIDE_C)
        assert result["error"] is True

    @pytest.mark.unit
    def test_rejects_document_source(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.move_folder("aaaa-1111-2222-3333", "")
        assert result["error"] is True
        assert "document" in result["detail"].lower()

    @pytest.mark.unit
    def test_dry_run_no_change(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.move_folder(NESTED_FOLDER_D, NESTED_FOLDER_A, dry_run=True)
        assert result["dry_run"] is True
        on_disk = json.loads(
            (nested_folder_cache / f"{NESTED_FOLDER_D}.metadata").read_text()
        )
        assert on_disk["parent"] == ""
