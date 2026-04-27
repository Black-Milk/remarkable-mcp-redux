# ABOUTME: Atomic, backup-protected metadata writes for the reMarkable cache.
# ABOUTME: Used only by the opt-in write-back MCP tools (rename, move, pin, restore, folders).

import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..config import backup_retention_count

logger = logging.getLogger("remarkable-mcp")

BACKUP_SUFFIX = ".bak."


class MetadataWriter:
    """Mutating helper for reMarkable .metadata files.

    Each update creates a timestamped backup next to the original, then writes
    atomically via a same-directory temp file followed by os.replace, so a
    partial write cannot leave the cache in an inconsistent state. After every
    successful write the per-document backup chain is pruned to retain only the
    most recent N siblings (configurable via REMARKABLE_BACKUP_RETENTION_COUNT).
    """

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)

    def update_metadata(
        self, doc_id: str, updates: dict
    ) -> tuple[dict, dict, Path]:
        """Update a .metadata file in place.

        Reads the current JSON, merges in `updates`, refreshes lastModified to
        the current time, and forces metadatamodified=True and modified=True so
        the reMarkable sync engine recognises the change as an intentional local
        edit. Backs up the original, then atomically writes the new content.
        Returns (old_meta, new_meta, backup_path).

        Caller responsibility: the writer trusts the merged record. Cycle-safe
        validation (e.g. preventing parent-chain loops on move) and any
        higher-level invariants (e.g. refusing trashed records) must be enforced
        before this method is called.
        """
        meta_path = self.base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata not found: {meta_path}")

        with open(meta_path) as f:
            current = json.load(f)

        new_meta = {
            **current,
            **updates,
            "lastModified": _now_ms(),
            "metadatamodified": True,
            "modified": True,
        }
        backup_path = _backup(meta_path)
        try:
            _atomic_write_json(meta_path, new_meta)
        except Exception:
            logger.exception(
                "Atomic write failed for %s; original preserved at %s",
                meta_path,
                backup_path,
            )
            raise
        _prune_old_backups(meta_path, retain=backup_retention_count())
        return current, new_meta, backup_path


class MetadataRestorer:
    """Restore a .metadata file from its most recent timestamped backup.

    The restore itself creates a pre-restore backup of the live metadata before
    overwriting, so it is reversible: the user can always re-restore from the
    chain. Pruning runs afterwards to keep the chain bounded.
    """

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)

    def latest_backup(self, doc_id: str) -> Path | None:
        """Return the most recent .metadata.bak.* sibling, or None if none exist.

        Backup filenames carry a UTC timestamp (YYYYMMDDTHHMMSS.fZ) so a plain
        sort gives chronological order.
        """
        meta_path = self.base_path / f"{doc_id}.metadata"
        backups = sorted(meta_path.parent.glob(f"{meta_path.name}{BACKUP_SUFFIX}*"))
        return backups[-1] if backups else None

    def restore_latest(self, doc_id: str) -> tuple[dict, dict, Path, Path]:
        """Restore .metadata from its most recent backup.

        Returns (old_meta, restored_meta, pre_restore_backup, source_backup).
        ``old_meta`` is the live state we just replaced; ``restored_meta`` is
        the contents of the backup we wrote into place; ``pre_restore_backup``
        is the timestamped copy of ``old_meta`` we made before mutating;
        ``source_backup`` is the .bak.* file that supplied the restored bytes.

        Raises FileNotFoundError if the live metadata is missing or no backups
        exist for the given doc.
        """
        meta_path = self.base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata not found: {meta_path}")

        source = self.latest_backup(doc_id)
        if source is None:
            raise FileNotFoundError(
                f"No backup files available for {doc_id}; nothing to restore"
            )

        with open(meta_path) as f:
            old_meta = json.load(f)
        with open(source) as f:
            restored_meta = json.load(f)

        pre_restore_backup = _backup(meta_path)
        try:
            _atomic_write_json(meta_path, restored_meta)
        except Exception:
            logger.exception(
                "Restore atomic write failed for %s; original preserved at %s",
                meta_path,
                pre_restore_backup,
            )
            raise
        _prune_old_backups(meta_path, retain=backup_retention_count())
        return old_meta, restored_meta, pre_restore_backup, source


class MetadataCreator:
    """Create brand-new .metadata + .content records (currently folders only).

    Two-file writes are atomic per file via temp+os.replace. If the second
    write fails, the first file is rolled back so partial creations cannot
    leave the cache with an orphaned record. The reMarkable desktop app
    indexes by .metadata, so an orphan .content alone would be invisible to
    sync, but we clean it up regardless to keep the cache tidy.
    """

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)

    def create_collection(
        self, name: str, parent: str = ""
    ) -> tuple[str, dict, Path, Path]:
        """Mint a new CollectionType (folder) record.

        Returns (folder_id, metadata, metadata_path, content_path). The new
        record is written with sync flags set so the desktop app picks it up
        on the next sync.

        Raises ValueError if the candidate UUID already collides with an
        existing record (vanishingly rare, but checked).
        """
        folder_id = str(uuid.uuid4())
        meta_path = self.base_path / f"{folder_id}.metadata"
        content_path = self.base_path / f"{folder_id}.content"
        if meta_path.exists() or content_path.exists():
            raise ValueError(
                f"UUID collision creating folder: {folder_id} already in use"
            )

        now = _now_ms()
        metadata = {
            "type": "CollectionType",
            "visibleName": name,
            "parent": parent,
            "lastModified": now,
            "deleted": False,
            "metadatamodified": True,
            "modified": True,
            "pinned": False,
            "synced": False,
            "version": 0,
        }
        content: dict = {}

        _atomic_write_json(content_path, content)
        try:
            _atomic_write_json(meta_path, metadata)
        except Exception:
            if content_path.exists():
                try:
                    content_path.unlink()
                except OSError:
                    logger.exception(
                        "Failed to clean up orphan .content after metadata "
                        "write failure: %s",
                        content_path,
                    )
            raise
        return folder_id, metadata, meta_path, content_path


# ---------------------------------------------------------------------------
# Module-level helpers (shared by writers/restorer/creator)
# ---------------------------------------------------------------------------


def _backup(meta_path: Path) -> Path:
    """Copy the metadata file to a timestamped sibling .bak.<ts> file."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = meta_path.parent / f"{meta_path.name}{BACKUP_SUFFIX}{ts}"
    shutil.copy2(meta_path, backup_path)
    return backup_path


def _atomic_write_json(target: Path, data: dict) -> None:
    """Write JSON to ``target`` atomically using a same-directory temp file."""
    fd, tmp_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f"{target.name}.tmp.",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, target)
    except Exception:
        tmp = Path(tmp_path)
        if tmp.exists():
            tmp.unlink()
        raise


def _prune_old_backups(meta_path: Path, retain: int) -> list[Path]:
    """Delete all but the most recent ``retain`` backups for ``meta_path``.

    Backups are sorted by filename; the embedded UTC timestamp keeps that
    ordering chronological. Returns the paths that were deleted (for tests
    and logging). retain<=0 deletes every backup.
    """
    pattern = f"{meta_path.name}{BACKUP_SUFFIX}*"
    backups = sorted(meta_path.parent.glob(pattern))
    to_delete = backups[:-retain] if retain > 0 else backups
    deleted: list[Path] = []
    for path in to_delete:
        try:
            path.unlink()
            deleted.append(path)
        except OSError:
            logger.exception("Failed to prune backup: %s", path)
    return deleted


def cleanup_backups(
    base_path: Path,
    older_than_days: int | None = None,
    doc_id: str | None = None,
) -> tuple[int, int, int, int]:
    """Bulk-prune .metadata.bak.* files across the cache.

    Returns (files_removed, bytes_freed, scanned_docs, backups_remaining).
    Either filter may be supplied independently; callers are responsible for
    refusing the no-filter case if they want to require explicit confirmation.

    older_than_days: only remove backups older than this many days (computed
        from file mtime). None means no age filter.
    doc_id: only scan the given document's backup chain. None means scan all
        documents in base_path.
    """
    base_path = Path(base_path)
    cutoff_ts: float | None = None
    if older_than_days is not None:
        cutoff_ts = datetime.now(UTC).timestamp() - older_than_days * 86400

    if doc_id is not None:
        scan_paths = [base_path / f"{doc_id}.metadata"]
    else:
        scan_paths = sorted(base_path.glob("*.metadata"))

    files_removed = 0
    bytes_freed = 0
    backups_remaining = 0
    scanned = 0
    for meta_path in scan_paths:
        if not meta_path.parent.exists():
            continue
        scanned += 1
        for backup in sorted(
            meta_path.parent.glob(f"{meta_path.name}{BACKUP_SUFFIX}*")
        ):
            if cutoff_ts is not None:
                try:
                    if backup.stat().st_mtime >= cutoff_ts:
                        backups_remaining += 1
                        continue
                except OSError:
                    backups_remaining += 1
                    continue
            try:
                size = backup.stat().st_size
                backup.unlink()
                files_removed += 1
                bytes_freed += size
            except OSError:
                logger.exception("Failed to remove backup: %s", backup)
                backups_remaining += 1
    return files_removed, bytes_freed, scanned, backups_remaining


def _now_ms() -> str:
    """Current Unix epoch milliseconds as a decimal string (matches reMarkable format)."""
    return str(int(datetime.now(UTC).timestamp() * 1000))
