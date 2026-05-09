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


def _validate_tag_op(
    tags: list[str] | None,
    add: list[str] | None,
    remove: list[str] | None,
) -> tuple[list[str] | None, list[str], list[str]]:
    """Validate and canonicalize a tag-update operation.

    Returns ``(replace_or_None, add_list, remove_list)`` with each list
    stripped, deduplicated case-insensitively (first occurrence wins), and
    free of empty/whitespace-only entries.

    Raises ``ValidationError`` if:
      - all three inputs are ``None`` (no-op call),
      - ``tags`` is mixed with ``add``/``remove`` (modes are exclusive),
      - any list element is not a string or is empty/whitespace-only,
      - the same tag appears in both ``add`` and ``remove`` (case-insensitive).

    Note: ``tags=[]`` is a valid replace-mode call meaning "clear all tags".
    """
    if tags is None and add is None and remove is None:
        raise ValidationError(
            "tag update requires at least one of tags, add, or remove"
        )
    if tags is not None and (add is not None or remove is not None):
        raise ValidationError(
            "tag update modes are mutually exclusive: pass either tags "
            "(replace mode) or add/remove (incremental mode), not both"
        )

    canonical_tags = (
        _canonicalize_tag_list(tags, "tags") if tags is not None else None
    )
    canonical_add = _canonicalize_tag_list(add, "add") if add is not None else []
    canonical_remove = (
        _canonicalize_tag_list(remove, "remove") if remove is not None else []
    )

    if canonical_add and canonical_remove:
        add_lower = {t.lower() for t in canonical_add}
        overlap = [t for t in canonical_remove if t.lower() in add_lower]
        if overlap:
            raise ValidationError(
                f"tag(s) appear in both add and remove: {overlap}; "
                "each tag may belong to one set only"
            )

    return canonical_tags, canonical_add, canonical_remove


def _canonicalize_tag_list(values: object, param_name: str) -> list[str]:
    """Strip, dedupe (case-insensitive), and validate a tag input list.

    Empty input lists are allowed (e.g. ``tags=[]`` clears all tags); empty
    or whitespace-only individual entries are rejected via ``ValidationError``.
    """
    if not isinstance(values, list):
        raise ValidationError(f"{param_name} must be a list of strings")
    canonical: list[str] = []
    seen_lower: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValidationError(
                f"{param_name} entries must be strings; "
                f"got {type(raw).__name__}"
            )
        stripped = raw.strip()
        if not stripped:
            raise ValidationError(
                f"{param_name} contains an empty or whitespace-only tag"
            )
        lower = stripped.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        canonical.append(stripped)
    return canonical


def _apply_tag_op(
    current_names: list[str],
    replace: list[str] | None,
    add: list[str],
    remove: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """Compute the post-op tag list plus per-call ``added``/``removed`` deltas.

    Matching is case-insensitive: adding ``"Foo"`` when ``"foo"`` is already
    present is a no-op (the existing entry's case is preserved); removing
    ``"Foo"`` when ``"foo"`` is present drops the ``"foo"`` entry. Replace
    mode adopts the user-supplied case verbatim.

    Returns ``(new_names, added_delta, removed_delta)``. All three preserve
    insertion order so the wire shape is deterministic.
    """
    if replace is not None:
        current_lower = {n.lower() for n in current_names}
        new_names = list(replace)
        new_lower = {n.lower() for n in new_names}
        added = [n for n in new_names if n.lower() not in current_lower]
        removed = [n for n in current_names if n.lower() not in new_lower]
        return new_names, added, removed

    remove_lower = {t.lower() for t in remove}
    new_names = [n for n in current_names if n.lower() not in remove_lower]
    removed = [n for n in current_names if n.lower() in remove_lower]

    surviving_lower = {n.lower() for n in new_names}
    added: list[str] = []
    for tag in add:
        if tag.lower() in surviving_lower:
            continue
        new_names.append(tag)
        surviving_lower.add(tag.lower())
        added.append(tag)

    return new_names, added, removed


def _canonicalize_authors(values: object) -> list[str]:
    """Strip, dedupe (case-insensitive), and validate the authors input list.

    Returns the canonical author list. Empty list is allowed (clears the
    author block); empty or whitespace-only individual entries raise
    ``ValidationError``.
    """
    if not isinstance(values, list):
        raise ValidationError("authors must be a list of strings")
    canonical: list[str] = []
    seen_lower: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValidationError(
                f"authors entries must be strings; got {type(raw).__name__}"
            )
        stripped = raw.strip()
        if not stripped:
            raise ValidationError(
                "authors contains an empty or whitespace-only entry"
            )
        lower = stripped.lower()
        if lower in seen_lower:
            continue
        seen_lower.add(lower)
        canonical.append(stripped)
    return canonical


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
