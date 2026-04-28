# ABOUTME: Contract tests for the Pydantic MCP response models in responses.py.
# ABOUTME: Schema sanity, dict-compat behaviour, and round-trip stability for representative payloads.

import pytest

from remarkable_mcp_redux.responses import (
    CleanupBackupsResponse,
    CleanupResponse,
    CreateFolderResponse,
    DocumentEntry,
    DocumentInfoResponse,
    DocumentListResponse,
    FolderEntry,
    FolderListResponse,
    MoveResponse,
    PageFailure,
    PinResponse,
    RenameResponse,
    RenderResponse,
    RestoreResponse,
    StatusResponse,
    ToolError,
)

# Models that map 1:1 onto a tool's output_schema. Skip nested-only models
# (DocumentEntry, FolderEntry, PageFailure) and ToolError (Phase-3 envelope).
TOP_LEVEL_RESPONSES = [
    StatusResponse,
    DocumentListResponse,
    DocumentInfoResponse,
    FolderListResponse,
    RenderResponse,
    CleanupResponse,
    RenameResponse,
    MoveResponse,
    PinResponse,
    CreateFolderResponse,
    RestoreResponse,
    CleanupBackupsResponse,
]


class TestSchemaShape:
    @pytest.mark.unit
    @pytest.mark.parametrize("model", TOP_LEVEL_RESPONSES)
    def test_model_json_schema_is_well_formed(self, model):
        """Each top-level response model emits a JSON Schema object with title + properties."""
        schema = model.model_json_schema()
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"
        assert schema.get("title") == model.__name__
        assert isinstance(schema.get("properties"), dict)
        assert len(schema["properties"]) > 0


class TestDictCompatibility:
    """The mixin in responses._BaseResponse must let legacy dict-style callers
    keep working while in-process consumers gain typed attribute access."""

    @pytest.mark.unit
    def test_attribute_and_subscript_agree_for_set_fields(self):
        resp = StatusResponse(
            cache_path="/tmp/cache",
            cache_exists=True,
            document_count=3,
            rmc_available=True,
            cairo_available=True,
        )
        assert resp.document_count == 3
        assert resp["document_count"] == 3
        assert "document_count" in resp

    @pytest.mark.unit
    def test_unset_field_is_absent(self):
        """A field that was never set must behave like a missing dict key."""
        resp = RenameResponse(
            doc_id="abc", dry_run=True, old_name="X", new_name="Y"
        )
        assert "backup_path" not in resp
        assert resp.get("backup_path") is None
        assert resp.get("backup_path", "MISS") == "MISS"
        with pytest.raises(KeyError):
            _ = resp["backup_path"]

    @pytest.mark.unit
    def test_explicit_none_is_present(self):
        """Fields explicitly set to None must round-trip as present-but-null."""
        resp = DocumentInfoResponse(
            doc_id="d",
            name="n",
            type="DocumentType",
            page_count=0,
            content_format="v2",
            first_page_id=None,
            last_page_id=None,
        )
        assert "first_page_id" in resp
        assert resp["first_page_id"] is None

    @pytest.mark.unit
    def test_get_returns_default_for_missing_field_name(self):
        resp = StatusResponse(
            cache_path="x", cache_exists=False, document_count=0,
            rmc_available=False, cairo_available=False,
        )
        # "totally_unknown_field" isn't in the model at all.
        assert resp.get("totally_unknown_field", "fallback") == "fallback"


class TestWireSerialization:
    """Default ``model_dump()`` keeps the wire JSON sparse (exclude_unset=True).

    See ``_BaseResponse.model_dump`` - this single override controls the wire
    shape for every tool and is what saves LLM tokens on paginated lists
    (one fewer ``parent`` key, missing optional metadata, etc.).
    """

    @pytest.mark.unit
    def test_default_dump_omits_unset_fields(self):
        resp = DocumentListResponse.model_validate(
            {
                "documents": [],
                "count": 0,
                "total_count": 0,
                "limit": 50,
                "offset": 0,
                "has_more": False,
            }
        )
        wire = resp.model_dump()
        assert "parent" not in wire
        assert wire["count"] == 0

    @pytest.mark.unit
    def test_default_dump_keeps_explicit_none(self):
        """Fields explicitly set to None must keep their null on the wire."""
        resp = RenderResponse(
            pdf_path=None,
            document_name="X",
            pages_rendered=0,
            pages_failed=[
                PageFailure(index=0, code="no_source", reason="nope")
            ],
            page_indices=[0],
        )
        wire = resp.model_dump()
        assert "pdf_path" in wire
        assert wire["pdf_path"] is None
        assert "sources_used" not in wire

    @pytest.mark.unit
    def test_dense_dump_via_explicit_override(self):
        """Callers that want every field can opt back in with exclude_unset=False."""
        resp = DocumentListResponse.model_validate(
            {
                "documents": [],
                "count": 0,
                "total_count": 0,
                "limit": 50,
                "offset": 0,
                "has_more": False,
            }
        )
        wire = resp.model_dump(exclude_unset=False)
        assert "parent" in wire
        assert wire["parent"] is None


ROUNDTRIP_CASES: list[tuple[str, type, dict]] = [
    (
        "status",
        StatusResponse,
        {
            "cache_path": "/cache",
            "cache_exists": True,
            "document_count": 7,
            "rmc_available": True,
            "cairo_available": False,
        },
    ),
    (
        "doc_list_with_parent",
        DocumentListResponse,
        {
            "documents": [
                {
                    "doc_id": "doc-1",
                    "name": "Notebook",
                    "type": "DocumentType",
                    "parent": "folder-x",
                    "last_modified": "2024-03-03T20:46:40+00:00",
                    "pinned": False,
                    "page_count": 3,
                    "file_type": "notebook",
                    "document_title": None,
                    "authors": [],
                    "tags": ["Journal"],
                    "annotated": True,
                    "original_page_count": -1,
                    "size_in_bytes": 2140,
                }
            ],
            "count": 1,
            "total_count": 1,
            "limit": 50,
            "offset": 0,
            "has_more": False,
            "parent": "folder-x",
        },
    ),
    (
        "render_with_failures",
        RenderResponse,
        {
            "pdf_path": "/renders/doc.pdf",
            "document_name": "Doc",
            "pages_rendered": 2,
            "pages_failed": [
                {"index": 1, "code": "rmc_failed", "reason": "rmc died"}
            ],
            "page_indices": [0, 1, 2],
            "sources_used": {"rm_v6": 1, "pdf_passthrough": 1},
        },
    ),
    (
        # Failure-only render: pdf_path=None must round-trip as explicit null,
        # sources_used must drop out (unset).
        "render_no_pages",
        RenderResponse,
        {
            "pdf_path": None,
            "document_name": "Doc",
            "pages_rendered": 0,
            "pages_failed": [
                {"index": 0, "code": "v5_unsupported", "reason": "v5"}
            ],
            "page_indices": [0],
        },
    ),
    (
        # include_page_ids=False shape: first/last present, page_ids absent.
        "doc_info_with_endpoints",
        DocumentInfoResponse,
        {
            "doc_id": "d",
            "name": "n",
            "type": "DocumentType",
            "parent": "",
            "last_modified": "",
            "pinned": False,
            "last_opened_page": 0,
            "page_count": 3,
            "content_format": "v2",
            "first_page_id": "page-1",
            "last_page_id": "page-3",
            "file_type": "notebook",
            "document_title": None,
            "authors": [],
            "tags": [],
            "annotated": False,
            "original_page_count": -1,
            "size_in_bytes": 0,
        },
    ),
    (
        # ToolError envelope: ``error`` is set explicitly so it survives
        # exclude_unset; ``code`` is omitted from the payload to verify it
        # stays out of the wire when never set.
        "tool_error_envelope",
        ToolError,
        {"error": True, "detail": "boom"},
    ),
]


class TestRoundTrip:
    """Representative payloads survive validate -> dump unchanged."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "model,payload",
        [(case[1], case[2]) for case in ROUNDTRIP_CASES],
        ids=[case[0] for case in ROUNDTRIP_CASES],
    )
    def test_payload_round_trips(self, model, payload):
        roundtripped = model.model_validate(payload).model_dump()
        assert roundtripped == payload


class TestNestedEntries:
    @pytest.mark.unit
    def test_document_entry_dict_compat(self):
        entry = DocumentEntry.model_validate(
            {
                "doc_id": "d",
                "name": "n",
                "type": "DocumentType",
                "parent": "",
                "last_modified": "",
                "pinned": False,
                "page_count": 0,
                "file_type": "",
                "document_title": None,
                "authors": [],
                "tags": [],
                "annotated": False,
                "original_page_count": -1,
                "size_in_bytes": 0,
            }
        )
        assert entry["doc_id"] == "d"
        assert entry.pinned is False
        assert "pinned" in entry

    @pytest.mark.unit
    def test_folder_entry_dict_compat(self):
        entry = FolderEntry.model_validate(
            {
                "folder_id": "f",
                "name": "Folder",
                "parent": "",
                "last_modified": "",
                "pinned": True,
            }
        )
        assert entry["folder_id"] == "f"
        assert entry.pinned is True
