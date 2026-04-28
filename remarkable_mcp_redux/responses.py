"""Pydantic response models that define the MCP wire shape for every tool.

Distinct from schemas.py (on-disk reMarkable JSON); they MUST NOT depend on each other.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class _BaseResponse(BaseModel):
    """Common base for MCP wire response models.

    Configures Pydantic to:
      - Accept both attribute and dict-style access (mixin below) so existing
        callers using ``result["count"]`` work unchanged alongside the new
        ``result.count`` style.
      - Treat fields that were not explicitly set at construction as absent
        for ``__contains__`` / ``__getitem__``, mirroring the pre-Phase-3
        dict shape where optional fields were simply omitted from the
        response payload. This is distinct from "field present but value is
        None" (which exists for include_page_ids=False on an empty doc, where
        ``first_page_id``/``last_page_id`` must round-trip as null).
      - Default ``model_dump`` to ``exclude_unset=True`` so the wire JSON
        stays sparse no matter who calls it (FastMCP's auto-serialization,
        in-process consumers, tests). Saves real LLM tokens on paginated list
        responses (e.g. an unfiltered list_documents drops one ``parent`` key
        and one ``document_title``/``authors``/``tags`` quartet per row).
        Callers that want the dense form pass ``exclude_unset=False``
        explicitly.
    """

    model_config = ConfigDict(populate_by_name=True)

    def __getitem__(self, key: str) -> Any:
        if key not in type(self).model_fields:
            raise KeyError(key)
        if key not in self.model_fields_set:
            raise KeyError(key)
        return getattr(self, key)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key not in type(self).model_fields:
            return False
        return key in self.model_fields_set

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Sparse-by-default serialization (see class docstring).

        ``exclude_unset=True`` (not ``exclude_none``) preserves explicit nulls
        like ``first_page_id=None`` on an empty doc — those were *set* by the
        facade — while still dropping never-set optional fields.
        """
        kwargs.setdefault("exclude_unset", True)
        kwargs.setdefault("by_alias", False)
        return super().model_dump(**kwargs)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class StatusResponse(_BaseResponse):
    """remarkable_check_status: cache + render-toolchain diagnostics."""

    cache_path: str
    cache_exists: bool
    document_count: int
    rmc_available: bool
    cairo_available: bool


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentEntry(_BaseResponse):
    """A single row in remarkable_list_documents results."""

    doc_id: str
    name: str
    type: str
    parent: str | None = None
    last_modified: str = ""
    pinned: bool = False
    page_count: int = 0
    file_type: str = ""
    document_title: str | None = None
    authors: list[str] = []
    tags: list[str] = []
    annotated: bool = False
    original_page_count: int = -1
    size_in_bytes: int = 0


class DocumentListResponse(_BaseResponse):
    """remarkable_list_documents: paginated DocumentEntry list + metadata."""

    documents: list[DocumentEntry]
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    parent: str | None = None  # echoed back only when caller filtered by parent


class DocumentInfoResponse(_BaseResponse):
    """remarkable_get_document_info: detailed metadata for a single document."""

    doc_id: str
    name: str
    type: str
    parent: str | None = None
    last_modified: str = ""
    pinned: bool = False
    last_opened_page: int = 0
    page_count: int = 0
    content_format: str = "unknown"
    page_ids: list[str] | None = None  # present when include_page_ids=True
    first_page_id: str | None = None  # present when include_page_ids=False
    last_page_id: str | None = None  # present when include_page_ids=False
    file_type: str = ""
    document_title: str | None = None
    authors: list[str] = []
    tags: list[str] = []
    annotated: bool = False
    original_page_count: int = -1
    size_in_bytes: int = 0


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------


class FolderEntry(_BaseResponse):
    """A single row in remarkable_list_folders results."""

    folder_id: str
    name: str
    parent: str | None = None
    last_modified: str = ""
    pinned: bool = False


class FolderListResponse(_BaseResponse):
    """remarkable_list_folders: paginated FolderEntry list + metadata."""

    folders: list[FolderEntry]
    count: int
    total_count: int
    limit: int
    offset: int
    has_more: bool
    parent: str | None = None  # echoed back only when caller filtered by parent


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class PageFailure(_BaseResponse):
    """Per-page failure entry inside RenderResponse.pages_failed."""

    index: int
    code: str
    reason: str


class RenderResponse(_BaseResponse):
    """remarkable_render_pages / remarkable_render_document: render-pipeline output.

    ``pdf_path`` is None when no pages rendered (every selected page failed).
    ``sources_used`` maps source-kind labels (e.g. ``"rm_v6"``,
    ``"pdf_passthrough"``) to per-kind page counts; absent when no pages rendered.

    Note (deprecated path): ``pdf_path`` is a local-filesystem path. Phase 5
    introduces transport-aware ``EmbeddedResource`` / ``ResourceLink`` returns
    and marks ``pdf_path`` for removal.
    """

    pdf_path: str | None = None
    document_name: str
    pages_rendered: int
    pages_failed: list[PageFailure]
    page_indices: list[int]
    sources_used: dict[str, int] | None = None


class CleanupResponse(_BaseResponse):
    """remarkable_cleanup_renders: render-dir sweeper result."""

    files_removed: int
    bytes_freed: int


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


class RenameResponse(_BaseResponse):
    """remarkable_rename_document / remarkable_rename_folder result.

    Carries either ``doc_id`` (for documents) or ``folder_id`` (for folders),
    never both. The unused field is omitted from the wire shape because it was
    never set (default ``model_dump`` runs with ``exclude_unset=True``).
    """

    doc_id: str | None = None
    folder_id: str | None = None
    dry_run: bool
    old_name: str
    new_name: str
    backup_path: str | None = None  # absent on dry-run


class MoveResponse(_BaseResponse):
    """remarkable_move_document / remarkable_move_folder result.

    ``descendants_affected`` is only populated for folder moves.
    """

    doc_id: str | None = None
    folder_id: str | None = None
    dry_run: bool
    old_parent: str | None = None
    new_parent: str
    backup_path: str | None = None  # absent on dry-run
    descendants_affected: int | None = None  # set only for folder moves


class PinResponse(_BaseResponse):
    """remarkable_pin_document result."""

    doc_id: str
    dry_run: bool
    old_pinned: bool
    new_pinned: bool
    backup_path: str | None = None  # absent on dry-run


class CreateFolderResponse(_BaseResponse):
    """remarkable_create_folder result.

    On dry_run, only ``name``/``parent`` are populated. On a real write,
    ``folder_id``, ``metadata_path``, and ``content_path`` join the response.
    """

    dry_run: bool
    name: str
    parent: str
    folder_id: str | None = None
    metadata_path: str | None = None
    content_path: str | None = None


class RestoreResponse(_BaseResponse):
    """remarkable_restore_metadata result.

    On dry_run, ``would_restore_from`` carries the backup file the real
    restore would consume. On a real restore, ``restored_from`` and
    ``pre_restore_backup`` are populated instead.
    """

    doc_id: str
    dry_run: bool
    would_restore_from: str | None = None  # dry_run only
    restored_from: str | None = None  # real restore only
    pre_restore_backup: str | None = None  # real restore only


class CleanupBackupsResponse(_BaseResponse):
    """remarkable_cleanup_metadata_backups result."""

    dry_run: bool
    files_removed: int
    bytes_freed: int
    scanned_docs: int
    backups_remaining: int


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(_BaseResponse):
    """Wire envelope produced by ``tools/_boundary.py`` for any caught
    ``RemarkableError`` raised inside a facade.

    Carries:
      - ``error``: always True. Always set explicitly by the boundary so it
        survives ``model_dump(exclude_unset=True)``.
      - ``detail``: human-readable message (the exception's ``.detail``).
      - ``code``: optional stable identifier mirroring ``RemarkableError.code``
        (``"not_found"``, ``"kind_mismatch"``, ``"validation"``, ``"trashed"``,
        ``"conflict"``, ``"backup_missing"``). Omitted from the wire when not
        set, preserving backwards-compatibility with clients that only look at
        ``error`` and ``detail``.
    """

    error: bool = True
    detail: str
    code: str | None = None


__all__ = [
    "CleanupBackupsResponse",
    "CleanupResponse",
    "CreateFolderResponse",
    "DocumentEntry",
    "DocumentInfoResponse",
    "DocumentListResponse",
    "FolderEntry",
    "FolderListResponse",
    "MoveResponse",
    "PageFailure",
    "PinResponse",
    "RenameResponse",
    "RenderResponse",
    "RestoreResponse",
    "StatusResponse",
    "ToolError",
]
