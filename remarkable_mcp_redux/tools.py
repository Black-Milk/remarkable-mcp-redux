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
    ) -> dict:
        """List documents in the reMarkable local cache (folders are excluded).
        Optional filters:
          - search: case-insensitive substring match on document name.
          - file_type: exact match on .content fileType ("pdf", "notebook", "epub").
          - tag: exact match on a user-applied tag name from .content.
        Each entry includes doc_id, name, type, parent, page_count, last_modified (ISO-8601),
        file_type, document_title, authors, tags, annotated, original_page_count,
        and size_in_bytes."""
        return client.list_documents(search=search, file_type=file_type, tag=tag)

    @mcp.tool()
    def remarkable_list_folders(search: str | None = None) -> dict:
        """List folders (CollectionType records) in the reMarkable local cache.
        Optional case-insensitive substring filter on folder names.
        Returns folder_id, name, parent (folder id or empty for root), and
        last_modified (ISO-8601). Use parent ids together with list_documents to
        navigate folder hierarchies."""
        return client.list_folders(search=search)

    @mcp.tool()
    def remarkable_get_document_info(doc_id: str) -> dict:
        """Get detailed metadata for a single reMarkable document (folders are rejected).
        Returns doc_id, name, type, parent, last_modified (ISO-8601), last_opened_page,
        page_count, page_ids, content_format (v1/v2), file_type, document_title, authors,
        tags, annotated, original_page_count, and size_in_bytes.
        Lightweight - reads JSON only, no rendering."""
        return client.get_document_info(doc_id)

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
    def remarkable_move_document(
        doc_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> dict:
        """Move a reMarkable document into a folder (or to root with new_parent="").
        Validates that new_parent is "" or an existing CollectionType folder id.
        With dry_run=true, returns the planned old_parent/new_parent without writing.
        Otherwise writes .metadata atomically with a timestamped backup and
        returns old_parent, new_parent, and backup_path. Pause reMarkable desktop
        sync before invoking this tool."""
        return client.move_document(doc_id, new_parent, dry_run=dry_run)
