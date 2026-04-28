"""WritesFacade — opt-in mutating operations on .metadata records.

Renames, moves, pin toggles, folder creation, restore, and backup cleanup.
"""

from pathlib import Path

from ..core.cache import RemarkableCache
from ..core.writes import (
    MetadataCreator,
    MetadataRestorer,
    MetadataWriter,
    cleanup_backups,
)
from ..exceptions import (
    BackupMissingError,
    ConflictError,
    KindMismatchError,
    NotFoundError,
    TrashedRecordError,
    ValidationError,
)
from ..responses import (
    BatchRenameResponse,
    CleanupBackupsResponse,
    CreateFolderResponse,
    MoveResponse,
    PinResponse,
    RenameResponse,
    RestoreResponse,
)
from ..schemas import CollectionMetadata
from ._helpers import (
    apply_rename_batch,
    move_record,
    rename_record,
    sibling_name_taken,
)


class WritesFacade:
    """Mutating operations on the local reMarkable cache.

    All operations write a timestamped backup before mutating .metadata and
    surface the backup path in the response so callers can roll back.
    """

    def __init__(self, base_path: Path, cache: RemarkableCache):
        self._base_path = base_path
        self._cache = cache

    def rename_document(
        self,
        doc_id: str,
        new_name: str,
        dry_run: bool = False,
    ) -> RenameResponse:
        """Rename a document by mutating its .metadata visibleName field.

        In dry_run mode, returns the planned change without writing anything.
        Otherwise writes atomically and returns the timestamped backup path.
        Raises ``ValidationError`` (empty name), ``NotFoundError``,
        ``KindMismatchError`` (folder id), or ``TrashedRecordError``.
        """
        result = rename_record(
            self._cache,
            self._base_path,
            doc_id,
            new_name,
            expected_kind="document",
            dry_run=dry_run,
        )
        return RenameResponse.model_validate(result)

    def rename_folder(
        self,
        folder_id: str,
        new_name: str,
        dry_run: bool = False,
    ) -> RenameResponse:
        """Rename a folder by mutating its .metadata visibleName field.

        Raises ``ValidationError`` (empty name), ``NotFoundError``,
        ``KindMismatchError`` (document id), ``TrashedRecordError``, or
        ``ConflictError`` (sibling-name collision).
        """
        result = rename_record(
            self._cache,
            self._base_path,
            folder_id,
            new_name,
            expected_kind="folder",
            dry_run=dry_run,
        )
        return RenameResponse.model_validate(result)

    def rename_documents_batch(
        self,
        items: list[dict],
        dry_run: bool = False,
    ) -> BatchRenameResponse:
        """Rename N documents in a single MCP turn (continue-on-error).

        ``items`` is a list of ``{"id": str, "new_name": str}`` dicts. Per-item
        failures (missing record, wrong kind, trashed, empty name) are
        embedded in the response as ``BatchRenameItem`` rows with
        ``success=False`` rather than aborting the batch — the loop keeps
        going so callers see every outcome in one response.

        Whole-request errors (empty list, non-dict items, missing keys,
        duplicate ids within the batch) raise ``ValidationError`` at the
        boundary; nothing is written in that case.
        """
        _validate_batch_items(items)
        rows = apply_rename_batch(
            self._cache,
            self._base_path,
            items,
            expected_kind="document",
            dry_run=dry_run,
        )
        return _build_batch_response(rows, dry_run=dry_run)

    def rename_folders_batch(
        self,
        items: list[dict],
        dry_run: bool = False,
    ) -> BatchRenameResponse:
        """Rename N folders in a single MCP turn (continue-on-error).

        Same shape as ``rename_documents_batch`` plus an in-memory sibling-
        uniqueness bucket: ``[A->Foo, B->Foo]`` under the same parent
        succeeds for the first item and reports ``code=conflict`` on the
        second, even though the cache itself isn't reloaded mid-loop.

        Whole-request validation is identical to the document path.
        """
        _validate_batch_items(items)
        rows = apply_rename_batch(
            self._cache,
            self._base_path,
            items,
            expected_kind="folder",
            dry_run=dry_run,
        )
        return _build_batch_response(rows, dry_run=dry_run)

    def move_document(
        self,
        doc_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> MoveResponse:
        """Move a document to a different folder by mutating .metadata parent.

        ``new_parent`` must be either "" (root) or an existing CollectionType
        folder id. Raises ``NotFoundError`` (missing source/target),
        ``KindMismatchError`` (folder source or document target),
        ``TrashedRecordError``, or ``ValidationError`` (self-move, trash
        sentinel, or descendant-of-self cycle).
        """
        result = move_record(
            self._cache,
            self._base_path,
            doc_id,
            new_parent,
            expected_kind="document",
            dry_run=dry_run,
        )
        return MoveResponse.model_validate(result)

    def move_folder(
        self,
        folder_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> MoveResponse:
        """Move a folder to a different parent by mutating .metadata parent.

        Same validation as move_document plus a cycle check that prevents moving
        a folder into its own subtree. Response includes ``descendants_affected``
        — the number of records (folders or documents) whose parent chain passes
        through this folder, so callers can see the blast radius before confirming.
        Raises the same exception set as ``move_document``.
        """
        result = move_record(
            self._cache,
            self._base_path,
            folder_id,
            new_parent,
            expected_kind="folder",
            dry_run=dry_run,
        )
        result["descendants_affected"] = self._cache.count_descendants(folder_id)
        return MoveResponse.model_validate(result)

    def pin_document(
        self,
        doc_id: str,
        pinned: bool,
        dry_run: bool = False,
    ) -> PinResponse:
        """Set or clear the ``pinned`` flag on a document.

        ``dry_run`` returns the would-be change without writing. Successful
        writes return the backup path and the boolean that was set. Raises
        ``NotFoundError``, ``KindMismatchError`` (folder id), or
        ``TrashedRecordError``.
        """
        meta = self._cache.load_metadata(doc_id)
        if meta is None:
            raise NotFoundError(f"Document not found: {doc_id}")
        if isinstance(meta, CollectionMetadata):
            raise KindMismatchError(
                f"{doc_id} is a folder (CollectionType); "
                "pinning folders is not supported by this tool"
            )
        if meta.deleted:
            raise TrashedRecordError(
                f"{doc_id} is in the trash (deleted=True); "
                "restore it from the reMarkable app before pinning"
            )

        old_pinned = bool(meta.pinned)
        if dry_run:
            return PinResponse(
                doc_id=doc_id,
                dry_run=True,
                old_pinned=old_pinned,
                new_pinned=bool(pinned),
            )

        writer = MetadataWriter(self._base_path)
        _old, _new, backup = writer.update_metadata(doc_id, {"pinned": bool(pinned)})
        return PinResponse(
            doc_id=doc_id,
            dry_run=False,
            old_pinned=old_pinned,
            new_pinned=bool(pinned),
            backup_path=str(backup),
        )

    def restore_metadata(
        self,
        doc_id: str,
        dry_run: bool = False,
    ) -> RestoreResponse:
        """Restore a record's .metadata from its most recent timestamped backup.

        Useful as an undo lever after rename, move, or pin. The current live
        metadata is itself backed up first so the restore is reversible.
        Returns the backup file consumed and the path of the pre-restore safety
        copy. ``dry_run`` reports which backup *would* be consumed without
        modifying anything. Raises ``NotFoundError`` if the record's
        ``.metadata`` is missing, or ``BackupMissingError`` if no backup chain
        exists for this record.
        """
        meta_path = self._base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            raise NotFoundError(f"Metadata not found: {doc_id}")

        restorer = MetadataRestorer(self._base_path)
        source = restorer.latest_backup(doc_id)
        if source is None:
            raise BackupMissingError(
                f"No backups available for {doc_id}; nothing to restore"
            )

        if dry_run:
            return RestoreResponse(
                doc_id=doc_id,
                dry_run=True,
                would_restore_from=str(source),
            )

        try:
            _old, _restored, pre_restore_backup, source_path = restorer.restore_latest(
                doc_id
            )
        except FileNotFoundError as exc:
            # The backup chain we observed above raced with another writer.
            # Surface as BackupMissingError so the boundary translates it
            # into the same code as the "no backups" path.
            raise BackupMissingError(str(exc)) from exc
        return RestoreResponse(
            doc_id=doc_id,
            dry_run=False,
            restored_from=str(source_path),
            pre_restore_backup=str(pre_restore_backup),
        )

    def cleanup_metadata_backups(
        self,
        older_than_days: int | None = None,
        doc_id: str | None = None,
        dry_run: bool = False,
    ) -> CleanupBackupsResponse:
        """Bulk-delete .metadata.bak.* files across the cache.

        Raises ``ValidationError`` when both filters are None - callers must
        opt in explicitly via ``older_than_days`` (set to 0 to wipe everything)
        or by targeting a specific ``doc_id``. ``dry_run`` reports the same
        numbers without unlinking anything.

        Returns files_removed, bytes_freed, scanned_docs, and backups_remaining
        (matched but not removed - either too new under the age filter or
        retained when ``dry_run=True``).
        """
        if older_than_days is None and doc_id is None:
            raise ValidationError(
                "cleanup_metadata_backups requires at least one filter "
                "(older_than_days or doc_id). Pass older_than_days=0 to "
                "delete every backup unconditionally."
            )

        if dry_run:
            payload = _cleanup_backups_dry_run(
                self._base_path,
                older_than_days=older_than_days,
                doc_id=doc_id,
            )
            return CleanupBackupsResponse.model_validate(payload)

        files_removed, bytes_freed, scanned, backups_remaining = cleanup_backups(
            self._base_path,
            older_than_days=older_than_days,
            doc_id=doc_id,
        )
        return CleanupBackupsResponse(
            dry_run=False,
            files_removed=files_removed,
            bytes_freed=bytes_freed,
            scanned_docs=scanned,
            backups_remaining=backups_remaining,
        )

    def create_folder(
        self,
        name: str,
        parent: str = "",
        dry_run: bool = False,
    ) -> CreateFolderResponse:
        """Create a new CollectionType folder record.

        ``parent`` must be ``""`` (root) or an existing CollectionType id. The
        ``"trash"`` sentinel is rejected explicitly. Sibling uniqueness is
        enforced: a folder name (case-insensitive trim) cannot duplicate an
        existing sibling under the same parent. Returns ``folder_id`` and the
        on-disk paths on success.

        Raises ``ValidationError`` (empty name, trash parent), ``NotFoundError``
        (missing parent), ``KindMismatchError`` (document parent),
        ``TrashedRecordError`` (parent in trash), or ``ConflictError``
        (duplicate sibling name).
        """
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            raise ValidationError("name must be a non-empty string")
        if parent == "trash":
            raise ValidationError(
                "Refusing to create folders inside 'trash'; use the "
                "reMarkable app to manage the trash"
            )
        if parent != "":
            target = self._cache.load_metadata(parent)
            if target is None:
                raise NotFoundError(f"Parent folder not found: {parent}")
            if not isinstance(target, CollectionMetadata):
                raise KindMismatchError(
                    f"Parent {parent} is not a folder (CollectionType); "
                    "new folders can only be created under existing folders"
                )
            if target.deleted:
                raise TrashedRecordError(
                    f"Parent {parent} is in the trash; cannot create children"
                )

        if sibling_name_taken(self._cache, parent, cleaned_name):
            raise ConflictError(
                f"A folder named '{cleaned_name}' already exists under "
                f"parent '{parent or 'root'}'"
            )

        if dry_run:
            return CreateFolderResponse(
                dry_run=True,
                name=cleaned_name,
                parent=parent,
            )

        creator = MetadataCreator(self._base_path)
        folder_id, _meta, meta_path, content_path = creator.create_collection(
            cleaned_name, parent=parent
        )
        return CreateFolderResponse(
            dry_run=False,
            folder_id=folder_id,
            name=cleaned_name,
            parent=parent,
            metadata_path=str(meta_path),
            content_path=str(content_path),
        )


def _validate_batch_items(items: object) -> None:
    """Whole-request validation for the rename batch tools.

    Enforces non-empty list of ``{id: str, new_name: str}`` dicts with unique
    ids. Per-item content errors (missing record, wrong kind, trashed,
    whitespace-only name) are NOT checked here — those flow through
    ``apply_rename_batch`` as continue-on-error rows. The split keeps
    "the request itself is malformed" distinct from "this one item failed".
    """
    if not isinstance(items, list):
        raise ValidationError("items must be a non-empty list of {id, new_name} dicts")
    if not items:
        raise ValidationError("items must be a non-empty list of {id, new_name} dicts")
    seen_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(
                f"items[{index}] must be a dict with 'id' and 'new_name' keys"
            )
        if "id" not in item or "new_name" not in item:
            raise ValidationError(
                f"items[{index}] must include both 'id' and 'new_name'"
            )
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id:
            raise ValidationError(f"items[{index}].id must be a non-empty string")
        if item_id in seen_ids:
            raise ValidationError(
                f"duplicate id in batch: {item_id} (each id may appear at most once)"
            )
        seen_ids.add(item_id)


def _build_batch_response(rows: list[dict], dry_run: bool) -> BatchRenameResponse:
    """Wrap per-item rows into ``BatchRenameResponse`` with aggregate counts."""
    succeeded = sum(1 for row in rows if row.get("success"))
    failed = len(rows) - succeeded
    return BatchRenameResponse.model_validate(
        {
            "dry_run": dry_run,
            "results": rows,
            "succeeded": succeeded,
            "failed": failed,
        }
    )


def _cleanup_backups_dry_run(
    base_path: Path,
    older_than_days: int | None,
    doc_id: str | None,
) -> dict:
    """Compute what cleanup_metadata_backups would do without unlinking anything."""
    from datetime import UTC, datetime

    cutoff_ts: float | None = None
    if older_than_days is not None:
        cutoff_ts = datetime.now(UTC).timestamp() - older_than_days * 86400

    if doc_id is not None:
        scan_paths = [base_path / f"{doc_id}.metadata"]
    else:
        scan_paths = sorted(base_path.glob("*.metadata"))

    files_to_remove = 0
    bytes_freed = 0
    backups_remaining = 0
    scanned = 0
    for meta_path in scan_paths:
        if not meta_path.parent.exists():
            continue
        scanned += 1
        for backup in sorted(meta_path.parent.glob(f"{meta_path.name}.bak.*")):
            try:
                stat = backup.stat()
            except OSError:
                backups_remaining += 1
                continue
            if cutoff_ts is not None and stat.st_mtime >= cutoff_ts:
                backups_remaining += 1
                continue
            files_to_remove += 1
            bytes_freed += stat.st_size
    return {
        "dry_run": True,
        "files_removed": files_to_remove,
        "bytes_freed": bytes_freed,
        "scanned_docs": scanned,
        "backups_remaining": backups_remaining,
    }
