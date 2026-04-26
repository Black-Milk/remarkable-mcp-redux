# ABOUTME: Atomic, backup-protected metadata writes for the reMarkable cache.
# ABOUTME: Used only by the opt-in write-back MCP tools (rename, move).

import json
import logging
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("remarkable-mcp")


class MetadataWriter:
    """Mutating helper for reMarkable .metadata files.

    Each update creates a timestamped backup next to the original, then writes
    atomically via a same-directory temp file followed by os.replace, so a
    partial write cannot leave the cache in an inconsistent state.
    """

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)

    def update_metadata(
        self, doc_id: str, updates: dict
    ) -> tuple[dict, dict, Path]:
        """Update a .metadata file in place.

        Reads the current JSON, merges in `updates`, refreshes lastModified to
        the current time, backs up the original, then atomically writes the new
        content. Returns (old_meta, new_meta, backup_path).
        """
        meta_path = self.base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata not found: {meta_path}")

        with open(meta_path) as f:
            current = json.load(f)

        new_meta = {**current, **updates, "lastModified": _now_ms()}
        backup_path = self._backup(meta_path)
        try:
            self._atomic_write_json(meta_path, new_meta)
        except Exception:
            logger.exception(
                "Atomic write failed for %s; original preserved at %s",
                meta_path,
                backup_path,
            )
            raise
        return current, new_meta, backup_path

    @staticmethod
    def _backup(meta_path: Path) -> Path:
        """Copy the metadata file to a timestamped sibling .bak.<ts> file."""
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = meta_path.parent / f"{meta_path.name}.bak.{ts}"
        shutil.copy2(meta_path, backup_path)
        return backup_path

    @staticmethod
    def _atomic_write_json(meta_path: Path, data: dict) -> None:
        """Write JSON to meta_path atomically using a same-directory temp file."""
        fd, tmp_path = tempfile.mkstemp(
            dir=meta_path.parent,
            prefix=f"{meta_path.name}.tmp.",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, meta_path)
        except Exception:
            tmp = Path(tmp_path)
            if tmp.exists():
                tmp.unlink()
            raise


def _now_ms() -> str:
    """Current Unix epoch milliseconds as a decimal string (matches reMarkable format)."""
    return str(int(datetime.now(UTC).timestamp() * 1000))
