"""Unit tests for the FoldersFacade (list) using synthetic cache fixtures.

Exercises filtering, pagination, and parent-direct-child semantics.
"""

import pytest

from remarkable_mcp_redux.client import RemarkableClient
from remarkable_mcp_redux.exceptions import (
    KindMismatchError,
    NotFoundError,
    ValidationError,
)
from tests.conftest import (
    NESTED_FOLDER_A,
    PERSONAL_FOLDER_ID,
    PINNED_FOLDER_ID,
    WORK_FOLDER_ID,
)

# ---------------------------------------------------------------------------
# folders.list
# ---------------------------------------------------------------------------


class TestListFolders:
    @pytest.mark.unit
    def test_list_folders_returns_collection_records(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list()
        assert result["count"] == 3
        names = {f["name"] for f in result["folders"]}
        assert names == {"Work", "Personal", "Favorites"}

    @pytest.mark.unit
    def test_list_folders_includes_parent_and_id(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list()
        ids = {f["folder_id"] for f in result["folders"]}
        assert ids == {WORK_FOLDER_ID, PERSONAL_FOLDER_ID, PINNED_FOLDER_ID}
        for folder in result["folders"]:
            assert folder["parent"] == ""

    @pytest.mark.unit
    def test_list_folders_search_filter(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list(search="work")
        assert result["count"] == 1
        assert result["folders"][0]["name"] == "Work"

    @pytest.mark.unit
    def test_list_folders_excludes_documents(self, fake_cache):
        """list_folders must not surface DocumentType records."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list()
        for folder in result["folders"]:
            assert "doc_id" not in folder

    @pytest.mark.unit
    def test_list_folders_empty_cache(self, empty_cache):
        client = RemarkableClient(base_path=empty_cache)
        result = client.folders.list()
        assert result["count"] == 0
        assert result["folders"] == []

    @pytest.mark.unit
    def test_list_folders_filter_by_pinned_true(self, fake_cache):
        """pinned=True should return only pinned/favorited folders."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list(pinned=True)
        assert result["count"] == 1
        assert result["folders"][0]["folder_id"] == PINNED_FOLDER_ID
        assert result["folders"][0]["pinned"] is True

    @pytest.mark.unit
    def test_list_folders_includes_pinned_field(self, fake_cache):
        """Every list_folders row should expose the pinned boolean."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list()
        by_id = {f["folder_id"]: f for f in result["folders"]}
        assert by_id[PINNED_FOLDER_ID]["pinned"] is True
        for folder_id, folder in by_id.items():
            assert isinstance(folder["pinned"], bool)
            if folder_id != PINNED_FOLDER_ID:
                assert folder["pinned"] is False


# ---------------------------------------------------------------------------
# folders.list pagination + parent filter
# ---------------------------------------------------------------------------


class TestListFoldersPagination:
    @pytest.mark.unit
    def test_default_includes_pagination_metadata(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list()
        assert result["count"] == 3
        assert result["total_count"] == 3
        assert result["limit"] == 100
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert "parent" not in result

    @pytest.mark.unit
    def test_limit_truncates_page_and_sets_has_more(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.folders.list(limit=1)
        assert result["count"] == 1
        assert result["total_count"] == 3
        assert result["has_more"] is True

    @pytest.mark.unit
    def test_offset_advances_to_disjoint_page(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        first = client.folders.list(limit=1, offset=0)["folders"]
        second = client.folders.list(limit=1, offset=1)["folders"]
        assert first[0]["folder_id"] != second[0]["folder_id"]

    @pytest.mark.unit
    def test_parent_root_filter(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.folders.list(parent="")
        names = {f["name"] for f in result["folders"]}
        assert names == {"A", "D"}
        assert result["total_count"] == 2
        assert result["parent"] == ""

    @pytest.mark.unit
    def test_parent_folder_filter_returns_direct_children(self, nested_folder_cache):
        """B is the only direct child of A; C lives under B and must not appear."""
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.folders.list(parent=NESTED_FOLDER_A)
        assert result["count"] == 1
        assert result["folders"][0]["name"] == "B"
        assert result["parent"] == NESTED_FOLDER_A

    @pytest.mark.unit
    def test_parent_unknown_raises_not_found(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="not found"):
            client.folders.list(parent="does-not-exist")

    @pytest.mark.unit
    def test_parent_non_folder_raises_kind_mismatch(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder"):
            client.folders.list(parent="aaaa-1111-2222-3333")

    @pytest.mark.unit
    def test_invalid_limit_raises_validation(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)limit"):
            client.folders.list(limit=0)

    @pytest.mark.unit
    def test_invalid_offset_raises_validation(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)offset"):
            client.folders.list(offset=-1)
