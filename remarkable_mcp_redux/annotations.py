"""Per-tool ToolAnnotations + human-readable titles for the FastMCP wire surface.

Centralized so tools/*.py modules stay free of annotation boilerplate at every @mcp.tool() site.
"""

from mcp.types import ToolAnnotations

# Human-readable titles surfaced by MCP clients (Cursor, Claude Desktop, etc.)
# alongside the technical tool name. Kept short; the tool docstring carries the
# operational detail.
TITLES: dict[str, str] = {
    # Read
    "remarkable_list_documents": "List reMarkable documents",
    "remarkable_list_folders": "List reMarkable folders",
    "remarkable_get_document_info": "Get reMarkable document metadata",
    "remarkable_check_status": "Check reMarkable cache + tool status",
    # Render
    "remarkable_render_pages": "Render reMarkable pages to PDF",
    "remarkable_render_document": "Render full reMarkable document to PDF",
    "remarkable_cleanup_renders": "Clean up rendered PDF files",
    # Write
    "remarkable_rename_document": "Rename reMarkable document",
    "remarkable_rename_folder": "Rename reMarkable folder",
    "remarkable_rename_documents_batch": "Rename reMarkable documents in batch",
    "remarkable_rename_folders_batch": "Rename reMarkable folders in batch",
    "remarkable_move_document": "Move reMarkable document",
    "remarkable_move_folder": "Move reMarkable folder",
    "remarkable_create_folder": "Create reMarkable folder",
    "remarkable_pin_document": "Pin or unpin reMarkable document",
    "remarkable_update_document_tags": "Update reMarkable document tags",
    "remarkable_update_document_tags_batch": "Update reMarkable document tags in batch",
    "remarkable_set_document_authors": "Set reMarkable document authors",
    "remarkable_restore_metadata": "Restore reMarkable metadata from backup",
    "remarkable_restore_content": "Restore reMarkable content from backup",
    "remarkable_cleanup_metadata_backups": "Clean up reMarkable backups",
}

# ToolAnnotations registry. Hint semantics (per MCP spec):
#   readOnlyHint     - tool does not modify any state visible to the user
#   destructiveHint  - tool may overwrite or delete state (only meaningful when
#                      readOnlyHint is False)
#   idempotentHint   - calling twice with the same arguments has the same effect
#                      as calling once (only meaningful when readOnlyHint is False)
#   openWorldHint    - tool may interact with services beyond the local server
#                      (web fetches, external APIs, etc.). False here because
#                      every tool reads/writes the local reMarkable cache only.
ANNOTATIONS: dict[str, ToolAnnotations] = {
    # Read tools — pure cache reads.
    "remarkable_list_documents": ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    ),
    "remarkable_list_folders": ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    ),
    "remarkable_get_document_info": ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    ),
    "remarkable_check_status": ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    ),
    # Render tools — cache-only reads that emit transient PDFs into render_dir.
    # render_pages / render_document don't mutate the cache itself; the
    # rendered files are temp output managed by cleanup_renders.
    "remarkable_render_pages": ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    ),
    "remarkable_render_document": ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=False,
    ),
    # cleanup_renders deletes files in render_dir; destructive but idempotent
    # (running it twice removes the same files; the second call is a no-op).
    "remarkable_cleanup_renders": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
    # Write tools — cache mutations. All non-idempotent unless explicitly marked.
    "remarkable_rename_document": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    "remarkable_rename_folder": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    # Batch rename tools — same destructive semantics as the singular versions;
    # continue-on-error per item is reflected in the response shape, not the
    # annotation hints (the tool itself still mutates state).
    "remarkable_rename_documents_batch": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    "remarkable_rename_folders_batch": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    "remarkable_move_document": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    "remarkable_move_folder": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    "remarkable_pin_document": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    # Tag/author tools mutate .content (with a paired .metadata sync bump).
    # destructiveHint=True because each call overwrites the existing tag /
    # author state and generates new timestamped backups; idempotentHint=False
    # because backup filenames embed a timestamp that differs between calls.
    "remarkable_update_document_tags": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    "remarkable_update_document_tags_batch": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    "remarkable_set_document_authors": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
    # create_folder is additive (creates a new record); never overwrites
    # existing state, so destructiveHint=False. Not idempotent because each
    # call generates a new folder UUID.
    "remarkable_create_folder": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
    # restore_metadata is destructive (overwrites live metadata) but
    # idempotent: restoring the same backup twice yields the same final state.
    "remarkable_restore_metadata": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
    # restore_content is the .content sibling of restore_metadata; same
    # destructive-but-idempotent semantics, scoped to .content.bak.* backups.
    "remarkable_restore_content": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
    # cleanup_metadata_backups deletes .metadata.bak.* AND .content.bak.*
    # files; idempotent because repeating the same filter set removes nothing
    # on the second call.
    "remarkable_cleanup_metadata_backups": ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False,
    ),
}


__all__ = ["ANNOTATIONS", "TITLES"]
