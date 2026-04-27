# ABOUTME: WritesFacade — opt-in mutating operations on .metadata records.
# ABOUTME: Renames, moves, pin toggles, folder creation, restore, and backup cleanup.

from pathlib import Path

from ..core.cache import RemarkableCache
from ..core.writes import (
    MetadataCreator,
    MetadataRestorer,
    MetadataWriter,
    cleanup_backups,
)
from ..schemas import CollectionMetadata
from ._helpers import (
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
    ) -> dict:
        """Rename a document by mutating its .metadata visibleName field.

        Validates target doc_id exists and is DocumentType. Refuses empty names
        and trashed records (records with deleted=True).
        In dry_run mode, returns the planned change without writing anything.
        Otherwise writes atomically and returns the timestamped backup path.
        """
        return rename_record(
            self._cache,
            self._base_path,
            doc_id,
            new_name,
            expected_kind="document",
            dry_run=dry_run,
        )

    def rename_folder(
        self,
        folder_id: str,
        new_name: str,
        dry_run: bool = False,
    ) -> dict:
        """Rename a folder by mutating its .metadata visibleName field.

        Validates target folder_id exists and is CollectionType. Refuses empty
        names and trashed records.
        """
        return rename_record(
            self._cache,
            self._base_path,
            folder_id,
            new_name,
            expected_kind="folder",
            dry_run=dry_run,
        )

    def move_document(
        self,
        doc_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> dict:
        """Move a document to a different folder by mutating .metadata parent.

        new_parent must be either "" (root) or an existing CollectionType folder id.
        Refuses trashed records, the trash sentinel as a destination, targets that
        are documents, missing targets, or the doc itself. Also runs a cycle
        check via cache.is_descendant_of.
        """
        return move_record(
            self._cache,
            self._base_path,
            doc_id,
            new_parent,
            expected_kind="document",
            dry_run=dry_run,
        )

    def move_folder(
        self,
        folder_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> dict:
        """Move a folder to a different parent by mutating .metadata parent.

        Same validation as move_document plus a cycle check that prevents moving
        a folder into its own subtree. Response includes ``descendants_affected``
        - the number of records (folders or documents) whose parent chain passes
        through this folder, so callers can see the blast radius before confirming.
        """
        result = move_record(
            self._cache,
            self._base_path,
            folder_id,
            new_parent,
            expected_kind="folder",
            dry_run=dry_run,
        )
        if not result.get("error"):
            result["descendants_affected"] = self._cache.count_descendants(folder_id)
        return result

    def pin_document(
        self,
        doc_id: str,
        pinned: bool,
        dry_run: bool = False,
    ) -> dict:
        """Set or clear the ``pinned`` flag on a document.

        Refuses CollectionType records and trashed records. ``dry_run`` returns
        the would-be change without writing. Successful writes return the
        backup path and the boolean that was set.
        """
        meta = self._cache.load_metadata(doc_id)
        if meta is None:
            return {"error": True, "detail": f"Document not found: {doc_id}"}
        if isinstance(meta, CollectionMetadata):
            return {
                "error": True,
                "detail": (
                    f"{doc_id} is a folder (CollectionType); "
                    "pinning folders is not supported by this tool"
                ),
            }
        if meta.deleted:
            return {
                "error": True,
                "detail": (
                    f"{doc_id} is in the trash (deleted=True); "
                    "restore it from the reMarkable app before pinning"
                ),
            }

        old_pinned = bool(meta.pinned)
        if dry_run:
            return {
                "doc_id": doc_id,
                "dry_run": True,
                "old_pinned": old_pinned,
                "new_pinned": bool(pinned),
            }

        writer = MetadataWriter(self._base_path)
        _old, _new, backup = writer.update_metadata(doc_id, {"pinned": bool(pinned)})
        return {
            "doc_id": doc_id,
            "dry_run": False,
            "old_pinned": old_pinned,
            "new_pinned": bool(pinned),
            "backup_path": str(backup),
        }

    def restore_metadata(
        self,
        doc_id: str,
        dry_run: bool = False,
    ) -> dict:
        """Restore a record's .metadata from its most recent timestamped backup.

        Useful as an undo lever after rename, move, or pin. The current live
        metadata is itself backed up first so the restore is reversible.
        Returns the backup file consumed and the path of the pre-restore safety
        copy. ``dry_run`` reports which backup *would* be consumed without
        modifying anything.
        """
        meta_path = self._base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            return {"error": True, "detail": f"Metadata not found: {doc_id}"}

        restorer = MetadataRestorer(self._base_path)
        source = restorer.latest_backup(doc_id)
        if source is None:
            return {
                "error": True,
                "detail": f"No backups available for {doc_id}; nothing to restore",
            }

        if dry_run:
            return {
                "doc_id": doc_id,
                "dry_run": True,
                "would_restore_from": str(source),
            }

        try:
            _old, _restored, pre_restore_backup, source_path = restorer.restore_latest(
                doc_id
            )
        except FileNotFoundError as exc:
            return {"error": True, "detail": str(exc)}
        return {
            "doc_id": doc_id,
            "dry_run": False,
            "restored_from": str(source_path),
            "pre_restore_backup": str(pre_restore_backup),
        }

    def cleanup_metadata_backups(
        self,
        older_than_days: int | None = None,
        doc_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Bulk-delete .metadata.bak.* files across the cache.

        Refuses with an error when both filters are None - callers must opt in
        explicitly via ``older_than_days`` (set to 0 to wipe everything) or by
        targeting a specific ``doc_id``. ``dry_run`` reports the same numbers
        without unlinking anything.

        Returns files_removed, bytes_freed, scanned_docs, and backups_remaining
        (matched but not removed - either too new under the age filter or
        retained when ``dry_run=True``).
        """
        if older_than_days is None and doc_id is None:
            return {
                "error": True,
                "detail": (
                    "cleanup_metadata_backups requires at least one filter "
                    "(older_than_days or doc_id). Pass older_than_days=0 to "
                    "delete every backup unconditionally."
                ),
            }

        if dry_run:
            return _cleanup_backups_dry_run(
                self._base_path,
                older_than_days=older_than_days,
                doc_id=doc_id,
            )

        files_removed, bytes_freed, scanned, backups_remaining = cleanup_backups(
            self._base_path,
            older_than_days=older_than_days,
            doc_id=doc_id,
        )
        return {
            "dry_run": False,
            "files_removed": files_removed,
            "bytes_freed": bytes_freed,
            "scanned_docs": scanned,
            "backups_remaining": backups_remaining,
        }

    def create_folder(
        self,
        name: str,
        parent: str = "",
        dry_run: bool = False,
    ) -> dict:
        """Create a new CollectionType folder record.

        ``parent`` must be ``""`` (root) or an existing CollectionType id. The
        ``"trash"`` sentinel is rejected explicitly. Sibling uniqueness is
        enforced: a folder name (case-insensitive trim) cannot duplicate an
        existing sibling under the same parent. Returns ``folder_id`` and the
        on-disk paths on success.
        """
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            return {"error": True, "detail": "name must be a non-empty string"}
        if parent == "trash":
            return {
                "error": True,
                "detail": (
                    "Refusing to create folders inside 'trash'; use the "
                    "reMarkable app to manage the trash"
                ),
            }
        if parent != "":
            target = self._cache.load_metadata(parent)
            if target is None:
                return {"error": True, "detail": f"Parent folder not found: {parent}"}
            if not isinstance(target, CollectionMetadata):
                return {
                    "error": True,
                    "detail": (
                        f"Parent {parent} is not a folder (CollectionType); "
                        "new folders can only be created under existing folders"
                    ),
                }
            if target.deleted:
                return {
                    "error": True,
                    "detail": f"Parent {parent} is in the trash; cannot create children",
                }

        if sibling_name_taken(self._cache, parent, cleaned_name):
            return {
                "error": True,
                "detail": (
                    f"A folder named '{cleaned_name}' already exists under "
                    f"parent '{parent or 'root'}'"
                ),
            }

        if dry_run:
            return {
                "dry_run": True,
                "name": cleaned_name,
                "parent": parent,
            }

        creator = MetadataCreator(self._base_path)
        folder_id, _meta, meta_path, content_path = creator.create_collection(
            cleaned_name, parent=parent
        )
        return {
            "dry_run": False,
            "folder_id": folder_id,
            "name": cleaned_name,
            "parent": parent,
            "metadata_path": str(meta_path),
            "content_path": str(content_path),
        }


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
