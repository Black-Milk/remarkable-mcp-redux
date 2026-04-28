# ABOUTME: Unit tests for the DocumentsFacade (list + get_info) using synthetic cache fixtures.
# ABOUTME: Exercises filtering, pagination, and the include_page_ids opt-out.

import json
from datetime import UTC, datetime

import pytest

from remarkable_mcp_redux.client import RemarkableClient
from remarkable_mcp_redux.exceptions import (
    KindMismatchError,
    NotFoundError,
    ValidationError,
)
from tests.conftest import (
    PERSONAL_FOLDER_ID,
    PINNED_DOC_ID,
    WORK_FOLDER_ID,
)

# ---------------------------------------------------------------------------
# documents.list
# ---------------------------------------------------------------------------


class TestListDocuments:
    @pytest.mark.unit
    def test_list_all_documents(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list()
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
        result = client.documents.list(search="journal")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Morning Journal"

    @pytest.mark.unit
    def test_list_documents_case_insensitive(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(search="ARCHITECTURE")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"

    @pytest.mark.unit
    def test_list_documents_no_match(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(search="nonexistent")
        assert result["count"] == 0
        assert result["documents"] == []

    @pytest.mark.unit
    def test_list_documents_empty_cache(self, empty_cache):
        client = RemarkableClient(base_path=empty_cache)
        result = client.documents.list()
        assert result["count"] == 0
        assert result["documents"] == []

    @pytest.mark.unit
    def test_list_documents_returns_metadata_fields(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(search="Morning")
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
        result = client.documents.list()
        ids = {d["doc_id"] for d in result["documents"]}
        assert WORK_FOLDER_ID not in ids
        assert PERSONAL_FOLDER_ID not in ids
        types = {d.get("type") for d in result["documents"]}
        assert types == {"DocumentType"}

    @pytest.mark.unit
    def test_list_documents_includes_parent(self, fake_cache):
        """BUG-09: list_documents responses should expose the parent folder id."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(search="Architecture")
        doc = result["documents"][0]
        assert doc["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_list_documents_last_modified_is_iso(self, fake_cache):
        """BUG-09: lastModified should be returned as ISO-8601 instead of millis."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(search="Morning")
        last_mod = result["documents"][0]["last_modified"]
        assert isinstance(last_mod, str)
        parsed = datetime.fromisoformat(last_mod)
        expected = datetime.fromtimestamp(1709500000, tz=UTC)
        assert parsed == expected

    @pytest.mark.unit
    def test_list_documents_includes_content_fields(self, fake_cache):
        """BUG-11: enriched .content fields should land in list_documents responses."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(search="Architecture")
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
        result = client.documents.list(file_type="pdf")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"

    @pytest.mark.unit
    def test_list_documents_filter_by_tag(self, fake_cache):
        """list_documents should support filtering on a user-applied tag name."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(tag="Reference")
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"

    @pytest.mark.unit
    def test_list_documents_filter_by_pinned_true(self, fake_cache):
        """pinned=True should return only pinned/favorited documents."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(pinned=True)
        assert result["count"] == 1
        assert result["documents"][0]["doc_id"] == PINNED_DOC_ID
        assert result["documents"][0]["pinned"] is True

    @pytest.mark.unit
    def test_list_documents_filter_by_pinned_false(self, fake_cache):
        """pinned=False should exclude pinned records and return the rest."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(pinned=False)
        ids = {d["doc_id"] for d in result["documents"]}
        assert PINNED_DOC_ID not in ids
        assert result["total_count"] == 4
        assert all(d["pinned"] is False for d in result["documents"])

    @pytest.mark.unit
    def test_list_documents_includes_pinned_field(self, fake_cache):
        """Every list_documents row should expose the pinned boolean."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list()
        by_id = {d["doc_id"]: d for d in result["documents"]}
        assert by_id[PINNED_DOC_ID]["pinned"] is True
        for doc_id, doc in by_id.items():
            assert isinstance(doc["pinned"], bool)
            if doc_id != PINNED_DOC_ID:
                assert doc["pinned"] is False


# ---------------------------------------------------------------------------
# documents.list pagination + parent filter
# ---------------------------------------------------------------------------


class TestListDocumentsPagination:
    @pytest.mark.unit
    def test_default_includes_pagination_metadata(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list()
        assert result["count"] == 5
        assert result["total_count"] == 5
        assert result["limit"] == 50
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert "parent" not in result

    @pytest.mark.unit
    def test_limit_truncates_page_and_sets_has_more(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(limit=2)
        assert result["count"] == 2
        assert result["total_count"] == 5
        assert result["limit"] == 2
        assert result["offset"] == 0
        assert result["has_more"] is True
        assert len(result["documents"]) == 2

    @pytest.mark.unit
    def test_offset_advances_to_disjoint_page(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        first = client.documents.list(limit=2, offset=0)["documents"]
        second = client.documents.list(limit=2, offset=2)["documents"]
        first_ids = {d["doc_id"] for d in first}
        second_ids = {d["doc_id"] for d in second}
        assert first_ids.isdisjoint(second_ids)

    @pytest.mark.unit
    def test_offset_past_end_returns_empty_page(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(limit=10, offset=100)
        assert result["count"] == 0
        assert result["documents"] == []
        assert result["total_count"] == 5
        assert result["has_more"] is False

    @pytest.mark.unit
    def test_parent_root_filter_excludes_subfolder_docs(self, fake_cache):
        """parent="" returns only root-level docs; the doc under WORK_FOLDER_ID is excluded."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(parent="")
        names = {d["name"] for d in result["documents"]}
        assert "Architecture Sketch" not in names
        assert result["parent"] == ""
        assert result["total_count"] == 4

    @pytest.mark.unit
    def test_parent_folder_filter_returns_direct_children(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(parent=WORK_FOLDER_ID)
        assert result["count"] == 1
        assert result["documents"][0]["name"] == "Architecture Sketch"
        assert result["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_parent_unknown_raises_not_found(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="not found"):
            client.documents.list(parent="does-not-exist")

    @pytest.mark.unit
    def test_parent_non_folder_raises_kind_mismatch(self, fake_cache):
        """Filtering by a document id (not a folder) is a hard error."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match=r"(?i)folder"):
            client.documents.list(parent="aaaa-1111-2222-3333")

    @pytest.mark.unit
    def test_invalid_limit_raises_validation(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match=r"(?i)limit"):
            client.documents.list(limit=0)

    @pytest.mark.unit
    def test_invalid_offset_raises_validation(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match=r"(?i)offset"):
            client.documents.list(offset=-1)

    @pytest.mark.unit
    def test_pagination_composes_with_filters(self, fake_cache):
        """Filters apply before pagination so total_count reflects the filtered set."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.list(file_type="notebook", limit=2)
        assert result["total_count"] == 4
        assert result["count"] == 2
        assert result["has_more"] is True
        for doc in result["documents"]:
            assert doc["file_type"] == "notebook"


# ---------------------------------------------------------------------------
# documents.get_info
# ---------------------------------------------------------------------------


class TestGetDocumentInfo:
    @pytest.mark.unit
    def test_v2_format(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.get_info("aaaa-1111-2222-3333")
        assert result["name"] == "Morning Journal"
        assert result["page_count"] == 3
        assert result["page_ids"] == ["page-a1", "page-a2", "page-a3"]
        assert result["doc_id"] == "aaaa-1111-2222-3333"

    @pytest.mark.unit
    def test_v1_format(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.get_info("bbbb-4444-5555-6666")
        assert result["name"] == "Architecture Sketch"
        assert result["page_count"] == 2
        assert result["page_ids"] == ["page-b1", "page-b2"]

    @pytest.mark.unit
    def test_missing_document_raises_not_found(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="not found"):
            client.documents.get_info("does-not-exist")

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache):
        """BUG-04: get_document_info should refuse CollectionType records."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match=r"(?i)folder|collection"):
            client.documents.get_info(WORK_FOLDER_ID)

    @pytest.mark.unit
    def test_includes_enriched_content_fields(self, fake_cache):
        """BUG-11: get_document_info should include file_type, title, authors, tags, etc."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.get_info("bbbb-4444-5555-6666")
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
        result = client.documents.get_info("ios-aaaa-1111")
        assert result.get("error") is not True
        assert result["name"] == "iOS Transfer"
        assert result["page_count"] == 1

    @pytest.mark.unit
    def test_includes_pinned_field(self, fake_cache):
        """get_document_info should expose the pinned boolean for both states."""
        client = RemarkableClient(base_path=fake_cache)
        pinned_result = client.documents.get_info(PINNED_DOC_ID)
        assert pinned_result["pinned"] is True
        unpinned_result = client.documents.get_info("aaaa-1111-2222-3333")
        assert unpinned_result["pinned"] is False


# ---------------------------------------------------------------------------
# documents.get_info include_page_ids opt-out
# ---------------------------------------------------------------------------


class TestGetDocumentInfoIncludePageIds:
    @pytest.mark.unit
    def test_default_includes_full_page_ids(self, fake_cache):
        """Default behavior must remain backward compatible."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.get_info("aaaa-1111-2222-3333")
        assert result["page_ids"] == ["page-a1", "page-a2", "page-a3"]
        assert result["page_count"] == 3
        assert "first_page_id" not in result
        assert "last_page_id" not in result

    @pytest.mark.unit
    def test_opt_out_omits_page_ids_and_exposes_endpoints(self, fake_cache):
        """include_page_ids=False drops the array but keeps page_count + endpoints."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.documents.get_info(
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
        result = client.documents.get_info("no-pages", include_page_ids=False)
        assert result["page_count"] == 0
        assert result["first_page_id"] is None
        assert result["last_page_id"] is None
