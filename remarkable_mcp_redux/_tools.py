# ABOUTME: MCP tool registrations for the remarkable-mcp server.
# ABOUTME: Tools are thin wrappers that delegate to RemarkableClient and return JSON-friendly dicts.

from fastmcp import FastMCP

from .client import RemarkableClient
from .config import is_write_tools_enabled


def register_tools(mcp: FastMCP, client: RemarkableClient) -> None:
    """Register MCP tools on the given FastMCP app.

    Read-only tools are always registered. Write-back tools are only registered
    when REMARKABLE_ENABLE_WRITE_TOOLS is set to a truthy value.
    """
    _register_read_tools(mcp, client)
    if is_write_tools_enabled():
        _register_write_tools(mcp, client)


def _register_read_tools(mcp: FastMCP, client: RemarkableClient) -> None:

    @mcp.tool()
    def remarkable_list_documents(
        search: str | None = None,
        file_type: str | None = None,
        tag: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
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
        return client.list_documents(
            search=search,
            file_type=file_type,
            tag=tag,
            pinned=pinned,
            parent=parent,
            limit=limit,
            offset=offset,
        )

    @mcp.tool()
    def remarkable_list_folders(
        search: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
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
        return client.list_folders(
            search=search,
            pinned=pinned,
            parent=parent,
            limit=limit,
            offset=offset,
        )

    @mcp.tool()
    def remarkable_get_document_info(
        doc_id: str, include_page_ids: bool = True
    ) -> dict:
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
        return client.get_document_info(doc_id, include_page_ids=include_page_ids)

    @mcp.tool()
    def remarkable_render_pages(
        doc_id: str,
        page_indices: list[int] | None = None,
        last_n: int | None = None,
        first_n: int | None = None,
    ) -> dict:
        """Render selected pages of a reMarkable document to a single PDF.
        Priority: page_indices > last_n > first_n > all pages.
        For a 200-page doc with last_n=5, only the last 5 pages are rendered.
        Returns the PDF path, document name, pages rendered/failed, and indices."""
        return client.render_pages(
            doc_id, page_indices=page_indices, last_n=last_n, first_n=first_n
        )

    @mcp.tool()
    def remarkable_render_document(doc_id: str) -> dict:
        """Render all pages of a reMarkable document to a single PDF.
        Convenience wrapper - equivalent to render_pages with no selection args.
        Returns the PDF path, document name, pages rendered/failed, and indices."""
        return client.render_pages(doc_id)

    @mcp.tool()
    def remarkable_check_status() -> dict:
        """Check reMarkable system status and tool availability.
        Returns whether the cache exists, document count, and rmc/cairo availability.
        Use this to diagnose issues before rendering."""
        return client.check_status()

    @mcp.tool()
    def remarkable_cleanup_renders() -> dict:
        """Remove temporary rendered PDFs from the render directory.
        Returns the number of files removed and bytes freed.
        Call this after you're done reading rendered PDFs."""
        return client.cleanup_renders()


def _register_write_tools(mcp: FastMCP, client: RemarkableClient) -> None:
    """Register the opt-in write-back tools.

    Pause reMarkable desktop sync before invoking these tools - they mutate the
    local cache and can race with sync writes. Each call creates a timestamped
    .metadata.bak backup before any change. Use dry_run=true to preview safely.
    Per-document backups are auto-pruned to keep the most recent N (default 5,
    overridable via REMARKABLE_BACKUP_RETENTION_COUNT).
    """

    @mcp.tool()
    def remarkable_rename_document(
        doc_id: str,
        new_name: str,
        dry_run: bool = False,
    ) -> dict:
        """Rename a reMarkable document (DocumentType only; folders are rejected).
        With dry_run=true, returns the planned old_name/new_name without writing.
        Otherwise writes .metadata atomically with a timestamped backup and
        returns old_name, new_name, and backup_path. Pause reMarkable desktop
        sync before invoking this tool."""
        return client.rename_document(doc_id, new_name, dry_run=dry_run)

    @mcp.tool()
    def remarkable_rename_folder(
        folder_id: str,
        new_name: str,
        dry_run: bool = False,
    ) -> dict:
        """Rename a reMarkable folder (CollectionType only; documents are rejected).
        Sibling uniqueness is enforced: a folder name cannot duplicate an existing
        sibling under the same parent. With dry_run=true, returns the planned
        old_name/new_name without writing. Otherwise writes .metadata atomically
        with a timestamped backup. Pause reMarkable desktop sync before invoking
        this tool."""
        return client.rename_folder(folder_id, new_name, dry_run=dry_run)

    @mcp.tool()
    def remarkable_move_document(
        doc_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> dict:
        """Move a reMarkable document into a folder (or to root with new_parent="").
        Validates that new_parent is "" or an existing CollectionType folder id.
        Refuses 'trash' as a destination. With dry_run=true, returns the planned
        old_parent/new_parent without writing. Otherwise writes .metadata atomically
        with a timestamped backup and returns old_parent, new_parent, and backup_path.
        Pause reMarkable desktop sync before invoking this tool."""
        return client.move_document(doc_id, new_parent, dry_run=dry_run)

    @mcp.tool()
    def remarkable_move_folder(
        folder_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> dict:
        """Move a reMarkable folder into a different parent (or to root with new_parent="").
        Refuses 'trash', moves into the source's own subtree, and missing or
        document targets. The response includes descendants_affected - the number
        of records whose parent chain passes through this folder, since moving a
        folder transitively relocates everything inside it. With dry_run=true,
        returns the planned change without writing. Pause reMarkable desktop sync
        before invoking this tool."""
        return client.move_folder(folder_id, new_parent, dry_run=dry_run)

    @mcp.tool()
    def remarkable_create_folder(
        name: str,
        parent: str = "",
        dry_run: bool = False,
    ) -> dict:
        """Create a new folder (CollectionType) under ``parent`` (default: root).
        Sibling uniqueness is enforced: a folder name cannot duplicate an existing
        sibling under the same parent (case-insensitive). Refuses 'trash' as a
        parent. Two-file atomic write: writes .content first, then .metadata,
        rolling back the .content if the metadata write fails. With dry_run=true,
        returns the planned name/parent without writing. Pause reMarkable desktop
        sync before invoking this tool."""
        return client.create_folder(name, parent=parent, dry_run=dry_run)

    @mcp.tool()
    def remarkable_pin_document(
        doc_id: str,
        pinned: bool,
        dry_run: bool = False,
    ) -> dict:
        """Set or clear the ``pinned`` flag on a reMarkable document.
        Refuses CollectionType records and trashed records. With dry_run=true,
        returns the planned old_pinned/new_pinned without writing. Otherwise writes
        .metadata atomically with a timestamped backup. Pause reMarkable desktop
        sync before invoking this tool."""
        return client.pin_document(doc_id, pinned, dry_run=dry_run)

    @mcp.tool()
    def remarkable_restore_metadata(
        doc_id: str,
        dry_run: bool = False,
    ) -> dict:
        """Restore a record's .metadata from its most recent timestamped backup.
        Acts as an undo lever after rename, move, or pin. The current live
        metadata is itself backed up before being overwritten, so the restore
        is reversible. With dry_run=true, reports which backup file would be
        consumed without modifying anything. Errors cleanly if no backup exists.
        Pause reMarkable desktop sync before invoking this tool."""
        return client.restore_metadata(doc_id, dry_run=dry_run)

    @mcp.tool()
    def remarkable_cleanup_metadata_backups(
        older_than_days: int | None = None,
        doc_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Bulk-delete .metadata.bak.* files across the reMarkable cache.
        At least one filter is required: ``older_than_days`` (set to 0 to wipe
        every backup) or ``doc_id`` (target a single record's backup chain).
        With dry_run=true, reports files_removed/bytes_freed/backups_remaining
        without unlinking anything. This complements the per-write auto-pruning
        that already keeps each document's chain bounded."""
        return client.cleanup_metadata_backups(
            older_than_days=older_than_days,
            doc_id=doc_id,
            dry_run=dry_run,
        )
