"""Read-only MCP tools: document/folder listing, document metadata, status diagnostics.

Each tool is a thin wrapper that delegates to the appropriate per-domain facade.
"""

from fastmcp import FastMCP

from ..annotations import ANNOTATIONS, TITLES
from ..facades import DocumentsFacade, FoldersFacade, StatusFacade
from ..responses import (
    DocumentInfoResponse,
    DocumentListResponse,
    FolderListResponse,
    StatusResponse,
)
from ._boundary import tool_error_boundary


def register_read_tools(
    mcp: FastMCP,
    *,
    documents: DocumentsFacade,
    folders: FoldersFacade,
    status: StatusFacade,
) -> None:
    """Register read-only document/folder/status tools on the FastMCP app."""

    @mcp.tool(
        title=TITLES["remarkable_list_documents"],
        annotations=ANNOTATIONS["remarkable_list_documents"],
        output_schema=DocumentListResponse.model_json_schema(),
    )
    @tool_error_boundary
    def remarkable_list_documents(
        search: str | None = None,
        file_type: str | None = None,
        tag: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """List documents in the reMarkable local cache (folders are excluded).
        Optional filters:
          - search: case-insensitive substring match on document name.
          - file_type: exact match on .content fileType ("pdf", "notebook", "epub").
          - tag: exact match on a user-applied tag name from .content.
          - pinned: True returns only pinned/favorited documents, False returns
            only unpinned, None disables the filter (default).
          - parent: direct-child folder filter. None = no filter (default),
            "" = root-only, "<folder_id>" = direct children of that folder
            (validated; an unknown id or a non-folder id returns an error).
        Pagination (applied after filtering):
          - limit (default 50): maximum entries to return per call.
          - offset (default 0): zero-based index of the first entry returned.
        Response includes documents (the page), count (page size), total_count
        (filtered total), limit, offset, has_more, and parent when filtered.
        Each document entry includes doc_id, name, type, parent, pinned,
        page_count, last_modified (ISO-8601), file_type, document_title,
        authors, tags, annotated, original_page_count, and size_in_bytes."""
        return documents.list(
            search=search,
            file_type=file_type,
            tag=tag,
            pinned=pinned,
            parent=parent,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(
        title=TITLES["remarkable_list_folders"],
        annotations=ANNOTATIONS["remarkable_list_folders"],
        output_schema=FolderListResponse.model_json_schema(),
    )
    @tool_error_boundary
    def remarkable_list_folders(
        search: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """List folders (CollectionType records) in the reMarkable local cache.
        Optional filters:
          - search: case-insensitive substring match on folder names.
          - pinned: True returns only pinned/favorited folders, False returns
            only unpinned, None disables the filter (default).
          - parent: direct-child folder filter. None = no filter (default),
            "" = root-only, "<folder_id>" = direct children of that folder
            (validated; an unknown id or a non-folder id returns an error).
        Pagination (applied after filtering):
          - limit (default 100): maximum entries to return per call.
          - offset (default 0): zero-based index of the first entry returned.
        Response includes folders (the page), count (page size), total_count
        (filtered total), limit, offset, has_more, and parent when filtered.
        Each folder entry has folder_id, name, parent (folder id or empty for
        root), pinned, and last_modified (ISO-8601). Use parent ids together
        with list_documents to navigate folder hierarchies."""
        return folders.list(
            search=search,
            pinned=pinned,
            parent=parent,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(
        title=TITLES["remarkable_get_document_info"],
        annotations=ANNOTATIONS["remarkable_get_document_info"],
        output_schema=DocumentInfoResponse.model_json_schema(),
    )
    @tool_error_boundary
    def remarkable_get_document_info(doc_id: str, include_page_ids: bool = True):
        """Get detailed metadata for a single reMarkable document (folders are rejected).
        Returns doc_id, name, type, parent, last_modified (ISO-8601), pinned,
        last_opened_page, page_count, content_format (v1/v2), file_type,
        document_title, authors, tags, annotated, original_page_count, and
        size_in_bytes.
        When include_page_ids=True (default) the response also carries page_ids
        (the full ordered list of page UUIDs). Set include_page_ids=False on
        very long documents to drop that list and receive first_page_id and
        last_page_id instead, keeping the response under MCP per-call budgets.
        Lightweight - reads JSON only, no rendering."""
        return documents.get_info(doc_id, include_page_ids=include_page_ids)

    @mcp.tool(
        title=TITLES["remarkable_check_status"],
        annotations=ANNOTATIONS["remarkable_check_status"],
        output_schema=StatusResponse.model_json_schema(),
    )
    @tool_error_boundary
    def remarkable_check_status():
        """Check reMarkable system status and tool availability.
        Returns whether the cache exists, document count, and rmc/cairo availability.
        Use this to diagnose issues before rendering."""
        return status.check()
