# ABOUTME: Shared helpers for the facades subpackage: pagination, parent/kind validation,
# ABOUTME: sibling-name uniqueness, and the rename/move record operations.

from pathlib import Path

from ..core.cache import RemarkableCache
from ..core.writes import MetadataWriter
from ..schemas import CollectionMetadata, DocumentMetadata


def expect_kind(
    meta: DocumentMetadata | CollectionMetadata,
    record_id: str,
    expected_kind: str,
    action: str,
) -> dict | None:
    """Verify ``meta`` matches the expected kind. Returns an error dict on mismatch.

    ``expected_kind`` is "document" or "folder". The returned error dict steers
    the caller to the correct dedicated tool so the type-vs-tool relationship
    stays explicit at the MCP surface.
    """
    if expected_kind == "document" and isinstance(meta, CollectionMetadata):
        return {
            "error": True,
            "detail": (
                f"{record_id} is a folder (CollectionType); "
                f"use remarkable_{action}_folder for folder operations"
            ),
        }
    if expected_kind == "folder" and isinstance(meta, DocumentMetadata):
        return {
            "error": True,
            "detail": (
                f"{record_id} is a document (DocumentType); "
                f"use remarkable_{action}_document for document operations"
            ),
        }
    return None


def validate_pagination(limit: int, offset: int) -> dict | None:
    """Validate ``limit``/``offset`` arg pair. Returns an error dict or None."""
    if not isinstance(limit, int) or limit < 1:
        return {"error": True, "detail": "limit must be a positive integer"}
    if not isinstance(offset, int) or offset < 0:
        return {"error": True, "detail": "offset must be a non-negative integer"}
    return None


def paginate_response(
    items: list[dict],
    items_key: str,
    limit: int,
    offset: int,
    parent: str | None,
) -> dict:
    """Slice ``items`` by ``offset``/``limit`` and wrap with pagination metadata.

    ``parent`` is echoed back only when the caller supplied a folder filter so
    the response shape stays minimal for unfiltered queries.
    """
    total = len(items)
    page = items[offset : offset + limit]
    response: dict = {
        items_key: page,
        "count": len(page),
        "total_count": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < total,
    }
    if parent is not None:
        response["parent"] = parent
    return response


def validate_parent_for_listing(
    cache: RemarkableCache, parent: str | None
) -> dict | None:
    """Verify ``parent`` is None, "" (root), or an existing CollectionType id.

    Returns an error dict on mismatch so list_documents/list_folders can
    surface a clear failure instead of silently returning empty pages.
    """
    if parent is None or parent == "":
        return None
    target = cache.load_metadata(parent)
    if target is None:
        return {"error": True, "detail": f"Parent folder not found: {parent}"}
    if not isinstance(target, CollectionMetadata):
        return {
            "error": True,
            "detail": (
                f"Parent {parent} is not a folder (CollectionType); "
                "use an existing folder id or omit parent"
            ),
        }
    return None


def sibling_name_taken(
    cache: RemarkableCache,
    parent: str,
    name: str,
    exclude_id: str | None = None,
) -> bool:
    """True if a sibling folder under ``parent`` already has this name (case-insensitive)."""
    target = name.strip().lower()
    for folder_id, folder_meta in cache.iter_folders():
        if exclude_id is not None and folder_id == exclude_id:
            continue
        if (folder_meta.parent or "") != parent:
            continue
        existing = (folder_meta.visible_name or "").strip().lower()
        if existing == target:
            return True
    return False


def rename_record(
    cache: RemarkableCache,
    base_path: Path,
    record_id: str,
    new_name: str,
    expected_kind: str,
    dry_run: bool,
) -> dict:
    """Rename a document or folder. ``expected_kind`` is "document" or "folder"."""
    cleaned_name = (new_name or "").strip()
    if not cleaned_name:
        return {"error": True, "detail": "new_name must be a non-empty string"}

    meta = cache.load_metadata(record_id)
    if meta is None:
        label = expected_kind.capitalize()
        return {"error": True, "detail": f"{label} not found: {record_id}"}
    kind_error = expect_kind(meta, record_id, expected_kind, action="rename")
    if kind_error is not None:
        return kind_error
    if meta.deleted:
        return {
            "error": True,
            "detail": (
                f"{record_id} is in the trash (deleted=True); "
                "restore it from the reMarkable app before renaming"
            ),
        }

    old_name = meta.visible_name or record_id
    if expected_kind == "folder":
        parent = meta.parent or ""
        if cleaned_name.lower() != old_name.lower() and sibling_name_taken(
            cache, parent, cleaned_name, exclude_id=record_id
        ):
            return {
                "error": True,
                "detail": (
                    f"A folder named '{cleaned_name}' already exists under "
                    f"parent '{parent or 'root'}'"
                ),
            }

    id_key = f"{expected_kind}_id"
    if dry_run:
        return {
            id_key: record_id,
            "dry_run": True,
            "old_name": old_name,
            "new_name": cleaned_name,
        }

    writer = MetadataWriter(base_path)
    _old, _new, backup = writer.update_metadata(
        record_id, {"visibleName": cleaned_name}
    )
    return {
        id_key: record_id,
        "dry_run": False,
        "old_name": old_name,
        "new_name": cleaned_name,
        "backup_path": str(backup),
    }


def move_record(
    cache: RemarkableCache,
    base_path: Path,
    record_id: str,
    new_parent: str,
    expected_kind: str,
    dry_run: bool,
) -> dict:
    """Move a document or folder. ``expected_kind`` is "document" or "folder"."""
    meta = cache.load_metadata(record_id)
    if meta is None:
        label = expected_kind.capitalize()
        return {"error": True, "detail": f"{label} not found: {record_id}"}
    kind_error = expect_kind(meta, record_id, expected_kind, action="move")
    if kind_error is not None:
        return kind_error
    if meta.deleted:
        return {
            "error": True,
            "detail": (
                f"{record_id} is in the trash (deleted=True); "
                "restore it from the reMarkable app before moving"
            ),
        }
    if new_parent == record_id:
        return {
            "error": True,
            "detail": f"Cannot move a {expected_kind} into itself",
        }
    if new_parent == "trash":
        return {
            "error": True,
            "detail": (
                "Refusing to move into 'trash' via this tool; "
                "use the reMarkable app to send records to the trash"
            ),
        }

    if new_parent != "":
        target = cache.load_metadata(new_parent)
        if target is None:
            return {
                "error": True,
                "detail": f"Target folder not found: {new_parent}",
            }
        if not isinstance(target, CollectionMetadata):
            return {
                "error": True,
                "detail": (
                    f"Target {new_parent} is not a folder (CollectionType); "
                    "records cannot be moved into a document"
                ),
            }
        if target.deleted:
            return {
                "error": True,
                "detail": f"Target folder {new_parent} is in the trash",
            }
        if cache.is_descendant_of(new_parent, record_id):
            return {
                "error": True,
                "detail": (
                    f"Cannot move {record_id} into {new_parent}: target is "
                    "inside the source's own subtree"
                ),
            }

    old_parent = meta.parent
    id_key = f"{expected_kind}_id"
    if dry_run:
        return {
            id_key: record_id,
            "dry_run": True,
            "old_parent": old_parent,
            "new_parent": new_parent,
        }

    writer = MetadataWriter(base_path)
    _old, _new, backup = writer.update_metadata(record_id, {"parent": new_parent})
    return {
        id_key: record_id,
        "dry_run": False,
        "old_parent": old_parent,
        "new_parent": new_parent,
        "backup_path": str(backup),
    }
