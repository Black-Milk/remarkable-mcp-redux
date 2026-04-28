"""Shared helpers for the facades subpackage: pagination, parent/kind validation,
sibling-name uniqueness, and the rename/move record operations. Raises typed
RemarkableError subclasses on validation failure (Phase 4).
"""

from pathlib import Path

from ..core.cache import RemarkableCache
from ..core.writes import MetadataWriter
from ..exceptions import (
    ConflictError,
    KindMismatchError,
    NotFoundError,
    RemarkableError,
    TrashedRecordError,
    ValidationError,
)
from ..schemas import CollectionMetadata, DocumentMetadata


def expect_kind(
    meta: DocumentMetadata | CollectionMetadata,
    record_id: str,
    expected_kind: str,
    action: str,
) -> None:
    """Verify ``meta`` matches the expected kind. Raises ``KindMismatchError`` on mismatch.

    ``expected_kind`` is "document" or "folder". The exception detail steers
    the caller to the correct dedicated tool so the type-vs-tool relationship
    stays explicit at the MCP surface.
    """
    if expected_kind == "document" and isinstance(meta, CollectionMetadata):
        raise KindMismatchError(
            f"{record_id} is a folder (CollectionType); "
            f"use remarkable_{action}_folder for folder operations"
        )
    if expected_kind == "folder" and isinstance(meta, DocumentMetadata):
        raise KindMismatchError(
            f"{record_id} is a document (DocumentType); "
            f"use remarkable_{action}_document for document operations"
        )


def validate_pagination(limit: int, offset: int) -> None:
    """Validate ``limit``/``offset`` arg pair. Raises ``ValidationError`` on bad input."""
    if not isinstance(limit, int) or limit < 1:
        raise ValidationError("limit must be a positive integer")
    if not isinstance(offset, int) or offset < 0:
        raise ValidationError("offset must be a non-negative integer")


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
) -> None:
    """Verify ``parent`` is None, "" (root), or an existing CollectionType id.

    Raises ``NotFoundError`` for unknown ids and ``KindMismatchError`` when
    ``parent`` resolves to a DocumentType, so list_documents/list_folders
    surface a clear failure instead of silently returning empty pages.
    """
    if parent is None or parent == "":
        return
    target = cache.load_metadata(parent)
    if target is None:
        raise NotFoundError(f"Parent folder not found: {parent}")
    if not isinstance(target, CollectionMetadata):
        raise KindMismatchError(
            f"Parent {parent} is not a folder (CollectionType); "
            "use an existing folder id or omit parent"
        )


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


def _validate_rename_target(
    cache: RemarkableCache,
    record_id: str,
    new_name: str,
    expected_kind: str,
) -> tuple[DocumentMetadata | CollectionMetadata, str, str]:
    """Run the kind-agnostic rename precondition checks.

    Returns ``(meta, cleaned_name, old_name)`` on success. Sibling-uniqueness
    is intentionally NOT checked here — for the singular path it consults the
    live cache, and for the batch path it consults a running in-memory bucket
    (so ``[A->Foo, B->Foo]`` flags the second item). Both paths layer their
    own collision check on top of this helper.

    Raises:
      - ``ValidationError``: empty/whitespace ``new_name``.
      - ``NotFoundError``: ``record_id`` not present in the cache.
      - ``KindMismatchError``: ``record_id`` is the wrong kind.
      - ``TrashedRecordError``: target is in the trash.
    """
    cleaned_name = (new_name or "").strip()
    if not cleaned_name:
        raise ValidationError("new_name must be a non-empty string")

    meta = cache.load_metadata(record_id)
    if meta is None:
        label = expected_kind.capitalize()
        raise NotFoundError(f"{label} not found: {record_id}")
    expect_kind(meta, record_id, expected_kind, action="rename")
    if meta.deleted:
        raise TrashedRecordError(
            f"{record_id} is in the trash (deleted=True); "
            "restore it from the reMarkable app before renaming"
        )

    old_name = meta.visible_name or record_id
    return meta, cleaned_name, old_name


def rename_record(
    cache: RemarkableCache,
    base_path: Path,
    record_id: str,
    new_name: str,
    expected_kind: str,
    dry_run: bool,
) -> dict:
    """Rename a document or folder. ``expected_kind`` is "document" or "folder".

    Raises:
      - ``ValidationError``: empty ``new_name``.
      - ``NotFoundError``: ``record_id`` not present in the cache.
      - ``KindMismatchError``: ``record_id`` is the wrong kind.
      - ``TrashedRecordError``: target is in the trash.
      - ``ConflictError``: folder rename collides with an existing sibling.
    """
    meta, cleaned_name, old_name = _validate_rename_target(
        cache, record_id, new_name, expected_kind
    )

    if expected_kind == "folder":
        parent = meta.parent or ""
        if cleaned_name.lower() != old_name.lower() and sibling_name_taken(
            cache, parent, cleaned_name, exclude_id=record_id
        ):
            raise ConflictError(
                f"A folder named '{cleaned_name}' already exists under "
                f"parent '{parent or 'root'}'"
            )

    if dry_run:
        return {
            "record_id": record_id,
            "dry_run": True,
            "old_name": old_name,
            "new_name": cleaned_name,
        }

    writer = MetadataWriter(base_path)
    _old, _new, backup = writer.update_metadata(
        record_id, {"visibleName": cleaned_name}
    )
    return {
        "record_id": record_id,
        "dry_run": False,
        "old_name": old_name,
        "new_name": cleaned_name,
        "backup_path": str(backup),
    }


def _build_folder_sibling_bucket(cache: RemarkableCache) -> dict[str, set[str]]:
    """Pre-compute ``parent_id -> {lowercased folder names}`` for the folder rename batch.

    Walking ``cache.iter_folders()`` once up front is O(F) instead of O(N*F)
    (one scan per item). Callers mutate the returned dict as successful renames
    land so subsequent items in the same batch see the new state and detect
    in-batch collisions like ``[A->Foo, B->Foo]``.
    """
    bucket: dict[str, set[str]] = {}
    for _folder_id, folder_meta in cache.iter_folders():
        parent = folder_meta.parent or ""
        name_lower = (folder_meta.visible_name or "").strip().lower()
        bucket.setdefault(parent, set()).add(name_lower)
    return bucket


def apply_rename_batch(
    cache: RemarkableCache,
    base_path: Path,
    items: list[dict],
    expected_kind: str,
    dry_run: bool,
) -> list[dict]:
    """Apply N rename items independently; per-item failures are returned as rows.

    ``items`` is a list of ``{"id": str, "new_name": str}`` dicts. The whole-
    request validation (non-empty, dict shape, unique ids) is the caller's
    responsibility — this helper trusts the input shape and focuses on the
    per-item walk.

    For ``expected_kind="folder"`` the function pre-builds an in-memory
    sibling bucket via ``_build_folder_sibling_bucket`` and updates it as
    each successful rename lands, so ``[A->Foo, B->Foo]`` under the same
    parent flags the second item with ``ConflictError`` even though the
    on-disk cache has not yet seen the first write (or has, but the cache
    object is not reloaded mid-loop).

    Returns one dict per input item, in input order, suitable for passing
    straight into ``BatchRenameItem.model_validate``.
    """
    sibling_bucket: dict[str, set[str]] | None = None
    if expected_kind == "folder":
        sibling_bucket = _build_folder_sibling_bucket(cache)

    writer = MetadataWriter(base_path) if not dry_run else None
    results: list[dict] = []
    for item in items:
        record_id = item["id"]
        raw_new_name = item["new_name"]
        try:
            meta, cleaned_name, old_name = _validate_rename_target(
                cache, record_id, raw_new_name, expected_kind
            )

            if expected_kind == "folder":
                assert sibling_bucket is not None
                parent = meta.parent or ""
                bucket_for_parent = sibling_bucket.get(parent, set())
                old_name_lower = old_name.lower()
                new_name_lower = cleaned_name.lower()
                if (
                    new_name_lower != old_name_lower
                    and new_name_lower in bucket_for_parent
                ):
                    raise ConflictError(
                        f"A folder named '{cleaned_name}' already exists under "
                        f"parent '{parent or 'root'}'"
                    )

            row: dict = {
                "id": record_id,
                "new_name": cleaned_name,
                "success": True,
                "old_name": old_name,
            }
            if not dry_run:
                assert writer is not None
                _old, _new, backup = writer.update_metadata(
                    record_id, {"visibleName": cleaned_name}
                )
                row["backup_path"] = str(backup)

            if expected_kind == "folder":
                assert sibling_bucket is not None
                parent = meta.parent or ""
                bucket_for_parent = sibling_bucket.setdefault(parent, set())
                bucket_for_parent.discard(old_name.lower())
                bucket_for_parent.add(cleaned_name.lower())

            results.append(row)
        except RemarkableError as exc:
            results.append(
                {
                    "id": record_id,
                    "new_name": (raw_new_name or "").strip() or raw_new_name,
                    "success": False,
                    "error": exc.detail,
                    "code": exc.code,
                }
            )
    return results


def move_record(
    cache: RemarkableCache,
    base_path: Path,
    record_id: str,
    new_parent: str,
    expected_kind: str,
    dry_run: bool,
) -> dict:
    """Move a document or folder. ``expected_kind`` is "document" or "folder".

    Raises:
      - ``NotFoundError``: source or target folder is missing.
      - ``KindMismatchError``: source is the wrong kind, or target is a document.
      - ``TrashedRecordError``: source or target is in the trash.
      - ``ValidationError``: ``new_parent`` is the source itself, the trash
        sentinel, or a descendant of the source (cycle).
    """
    meta = cache.load_metadata(record_id)
    if meta is None:
        label = expected_kind.capitalize()
        raise NotFoundError(f"{label} not found: {record_id}")
    expect_kind(meta, record_id, expected_kind, action="move")
    if meta.deleted:
        raise TrashedRecordError(
            f"{record_id} is in the trash (deleted=True); "
            "restore it from the reMarkable app before moving"
        )
    if new_parent == record_id:
        raise ValidationError(f"Cannot move a {expected_kind} into itself")
    if new_parent == "trash":
        raise ValidationError(
            "Refusing to move into 'trash' via this tool; "
            "use the reMarkable app to send records to the trash"
        )

    if new_parent != "":
        target = cache.load_metadata(new_parent)
        if target is None:
            raise NotFoundError(f"Target folder not found: {new_parent}")
        if not isinstance(target, CollectionMetadata):
            raise KindMismatchError(
                f"Target {new_parent} is not a folder (CollectionType); "
                "records cannot be moved into a document"
            )
        if target.deleted:
            raise TrashedRecordError(
                f"Target folder {new_parent} is in the trash"
            )
        if cache.is_descendant_of(new_parent, record_id):
            raise ValidationError(
                f"Cannot move {record_id} into {new_parent}: target is "
                "inside the source's own subtree"
            )

    old_parent = meta.parent
    if dry_run:
        return {
            "record_id": record_id,
            "dry_run": True,
            "old_parent": old_parent,
            "new_parent": new_parent,
        }

    writer = MetadataWriter(base_path)
    _old, _new, backup = writer.update_metadata(record_id, {"parent": new_parent})
    return {
        "record_id": record_id,
        "dry_run": False,
        "old_parent": old_parent,
        "new_parent": new_parent,
        "backup_path": str(backup),
    }
