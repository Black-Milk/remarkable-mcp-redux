# ABOUTME: Opt-in write-back MCP tools: rename, move, pin, create-folder, restore, backup cleanup.
# ABOUTME: Each tool delegates to WritesFacade; only registered when REMARKABLE_ENABLE_WRITE_TOOLS is set.

from fastmcp import FastMCP

from ..facades import WritesFacade


def register_write_tools(mcp: FastMCP, *, writes: WritesFacade) -> None:
    """Register the opt-in write-back tools on the FastMCP app.

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
        return writes.rename_document(doc_id, new_name, dry_run=dry_run)

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
        return writes.rename_folder(folder_id, new_name, dry_run=dry_run)

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
        return writes.move_document(doc_id, new_parent, dry_run=dry_run)

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
        return writes.move_folder(folder_id, new_parent, dry_run=dry_run)

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
        return writes.create_folder(name, parent=parent, dry_run=dry_run)

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
        return writes.pin_document(doc_id, pinned, dry_run=dry_run)

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
        return writes.restore_metadata(doc_id, dry_run=dry_run)

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
        return writes.cleanup_metadata_backups(
            older_than_days=older_than_days,
            doc_id=doc_id,
            dry_run=dry_run,
        )
