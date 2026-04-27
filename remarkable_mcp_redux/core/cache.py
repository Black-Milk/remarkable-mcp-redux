# ABOUTME: Loading helpers for reMarkable .metadata and .content JSON files.
# ABOUTME: Parses raw cache files into validated Pydantic schema objects.

import json
import logging
from collections.abc import Iterator
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ..schemas import (
    CacheItemMetadata,
    CollectionMetadata,
    ContentMetadata,
    DocumentMetadata,
)

logger = logging.getLogger("remarkable-mcp")

_CACHE_ITEM_ADAPTER: TypeAdapter[CacheItemMetadata] = TypeAdapter(CacheItemMetadata)


class RemarkableCache:
    """Read .metadata and .content files from a reMarkable desktop cache directory."""

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)

    def exists(self) -> bool:
        return self.base_path.exists() and self.base_path.is_dir()

    def iter_metadata_paths(self) -> Iterator[Path]:
        """Yield all *.metadata file paths in sorted order."""
        if not self.exists():
            return
        yield from sorted(self.base_path.glob("*.metadata"))

    def iter_metadata(self) -> Iterator[tuple[str, DocumentMetadata | CollectionMetadata]]:
        """Yield (doc_id, metadata) pairs for all readable .metadata files."""
        for meta_path in self.iter_metadata_paths():
            meta = self._load_metadata_path(meta_path)
            if meta is None:
                continue
            yield meta_path.stem, meta

    def iter_documents(self) -> Iterator[tuple[str, DocumentMetadata]]:
        """Yield (doc_id, metadata) pairs for DocumentType records only."""
        for doc_id, meta in self.iter_metadata():
            if isinstance(meta, DocumentMetadata):
                yield doc_id, meta

    def iter_folders(self) -> Iterator[tuple[str, CollectionMetadata]]:
        """Yield (folder_id, metadata) pairs for CollectionType records only."""
        for doc_id, meta in self.iter_metadata():
            if isinstance(meta, CollectionMetadata):
                yield doc_id, meta

    def count_documents(self) -> int:
        """Number of DocumentType records in the cache."""
        return sum(1 for _ in self.iter_documents())

    def load_metadata(self, doc_id: str) -> DocumentMetadata | CollectionMetadata | None:
        """Load and validate a single .metadata file. Returns None if missing or invalid."""
        meta_path = self.base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            return None
        return self._load_metadata_path(meta_path)

    def _load_metadata_path(
        self, meta_path: Path
    ) -> DocumentMetadata | CollectionMetadata | None:
        try:
            with open(meta_path) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", meta_path, exc)
            return None
        try:
            return _CACHE_ITEM_ADAPTER.validate_python(raw)
        except ValidationError as exc:
            logger.warning("Invalid metadata in %s: %s", meta_path, exc)
            return None

    def load_content(self, doc_id: str) -> ContentMetadata | None:
        """Load and validate a .content file. Returns None if missing or invalid."""
        content_path = self.base_path / f"{doc_id}.content"
        if not content_path.exists():
            return None
        try:
            with open(content_path) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", content_path, exc)
            return None
        try:
            return ContentMetadata.model_validate(raw)
        except ValidationError as exc:
            logger.warning("Invalid content in %s: %s", content_path, exc)
            return None

    def get_page_ids(self, doc_id: str) -> list[str]:
        """Extract page IDs from a document, supporting v1 and v2 content formats."""
        content = self.load_content(doc_id)
        if content is None:
            return []
        return content.page_ids

    def detect_content_format(self, doc_id: str) -> str:
        """Detect whether a document uses v1 or v2 content format."""
        content = self.load_content(doc_id)
        if content is None:
            return "unknown"
        return content.content_format

    def get_document_name(self, doc_id: str) -> str:
        """Get the visible name of a document. Falls back to doc_id if missing or empty."""
        meta = self.load_metadata(doc_id)
        if meta is None:
            return doc_id
        return meta.visible_name or doc_id

    def is_descendant_of(self, candidate_id: str, ancestor_id: str) -> bool:
        """True if ``candidate_id`` sits anywhere in ``ancestor_id``'s parent chain.

        Walks the parent links upward from ``candidate_id`` with a visited-set so
        a malformed cycle in the cache cannot loop forever. Returns False if any
        link in the chain is missing, or if the chain reaches the root without
        encountering ``ancestor_id``. A node is treated as a descendant of itself
        (i.e. ``is_descendant_of(x, x)`` is True), which matches the cycle-prevention
        semantics callers want: "is this proposed parent already in the subtree?"
        """
        if candidate_id == ancestor_id:
            return True
        visited: set[str] = set()
        current = candidate_id
        while current and current not in visited:
            visited.add(current)
            meta = self.load_metadata(current)
            if meta is None:
                return False
            parent = meta.parent or ""
            if parent == ancestor_id:
                return True
            current = parent
        return False

    def count_descendants(self, ancestor_id: str) -> int:
        """Count records whose parent chain passes through ``ancestor_id``.

        Used by folder-move to surface a blast-radius count in the response.
        Cycle-safe: each candidate is walked with its own visited-set via
        ``is_descendant_of``. Excludes ``ancestor_id`` itself.
        """
        if not ancestor_id:
            return 0
        count = 0
        for child_id, _ in self.iter_metadata():
            if child_id == ancestor_id:
                continue
            if self.is_descendant_of(child_id, ancestor_id):
                count += 1
        return count
