# ABOUTME: RemarkableClient facade that orchestrates cache loading and PDF rendering.
# ABOUTME: Public API consumed by the MCP tool layer; returns plain JSON-friendly dicts.

from pathlib import Path

from .cache import RemarkableCache
from .config import DEFAULT_BASE_PATH, DEFAULT_RENDER_DIR, ensure_cairo_library_path
from .render import (
    RemarkableRenderer,
    check_cairo_available,
    check_rmc_available,
)
from .schemas import (
    CollectionMetadata,
    ContentMetadata,
    DocumentMetadata,
)
from .writes import MetadataWriter


class RemarkableClient:
    """Reads and renders reMarkable documents from the local desktop app cache."""

    def __init__(
        self,
        base_path: Path = DEFAULT_BASE_PATH,
        render_dir: Path = DEFAULT_RENDER_DIR,
    ):
        ensure_cairo_library_path()
        self.base_path = Path(base_path)
        self.render_dir = Path(render_dir)
        self.cache = RemarkableCache(self.base_path)
        self.renderer = RemarkableRenderer(self.render_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_status(self) -> dict:
        """Diagnostics: cache existence, tool availability, document count.

        document_count counts only DocumentType records (folders excluded).
        """
        cache_exists = self.cache.exists()
        doc_count = self.cache.count_documents() if cache_exists else 0
        return {
            "cache_path": str(self.base_path),
            "cache_exists": cache_exists,
            "document_count": doc_count,
            "rmc_available": check_rmc_available(),
            "cairo_available": check_cairo_available(),
        }

    def list_documents(
        self,
        search: str | None = None,
        file_type: str | None = None,
        tag: str | None = None,
    ) -> dict:
        """List DocumentType records in the cache.

        Folders (CollectionType) are filtered out. Optional filters:
          - search: case-insensitive substring match on visibleName.
          - file_type: exact match on the .content fileType (e.g. "pdf", "notebook").
          - tag: exact match against any user-applied tag name in .content.
        """
        if not self.cache.exists():
            return {"documents": [], "count": 0}

        documents = []
        for doc_id, meta in self.cache.iter_documents():
            name = meta.visible_name or doc_id
            if search and search.lower() not in name.lower():
                continue
            content = self.cache.load_content(doc_id)
            if file_type is not None and (
                content is None or content.file_type != file_type
            ):
                continue
            if tag is not None and (content is None or tag not in content.tag_names):
                continue
            documents.append(_document_summary(doc_id, name, meta, content))

        return {"documents": documents, "count": len(documents)}

    def list_folders(self, search: str | None = None) -> dict:
        """List CollectionType (folder) records in the cache.

        Returns a list of folder summaries with id, name, parent, and ISO timestamp.
        """
        if not self.cache.exists():
            return {"folders": [], "count": 0}

        folders = []
        for folder_id, meta in self.cache.iter_folders():
            name = meta.visible_name or folder_id
            if search and search.lower() not in name.lower():
                continue
            folders.append(
                {
                    "folder_id": folder_id,
                    "name": name,
                    "parent": meta.parent,
                    "last_modified": meta.last_modified_iso or "",
                }
            )

        return {"folders": folders, "count": len(folders)}

    def get_document_info(self, doc_id: str) -> dict:
        """Detailed metadata for a single DocumentType record.

        Refuses CollectionType records (folders) with an explicit error.
        """
        meta = self.cache.load_metadata(doc_id)
        if meta is None:
            return {"error": True, "detail": f"Document not found: {doc_id}"}
        if isinstance(meta, CollectionMetadata):
            return {
                "error": True,
                "detail": (
                    f"{doc_id} is a folder (CollectionType), not a document. "
                    "Use remarkable_list_folders to enumerate folders."
                ),
            }

        content = self.cache.load_content(doc_id)
        page_ids = content.page_ids if content is not None else []
        content_format = content.content_format if content is not None else "unknown"

        info = {
            "doc_id": doc_id,
            "name": meta.visible_name or doc_id,
            "type": meta.type,
            "parent": meta.parent,
            "last_modified": meta.last_modified_iso or "",
            "last_opened_page": meta.last_opened_page,
            "page_count": len(page_ids),
            "page_ids": page_ids,
            "content_format": content_format,
        }
        info.update(_content_summary(content))
        return info

    def render_pages(
        self,
        doc_id: str,
        page_indices: list[int] | None = None,
        last_n: int | None = None,
        first_n: int | None = None,
    ) -> dict:
        """Render selected pages of a document to a single PDF.

        Priority: page_indices > last_n > first_n > all pages.
        Empty page_indices=[] is rejected with an error.
        Refuses CollectionType records (folders) with an explicit error.
        """
        if page_indices is not None and len(page_indices) == 0:
            return {
                "error": True,
                "detail": "page_indices must contain at least one index",
            }

        meta = self.cache.load_metadata(doc_id)
        if meta is None:
            return {"error": True, "detail": f"Document not found: {doc_id}"}
        if isinstance(meta, CollectionMetadata):
            return {
                "error": True,
                "detail": (
                    f"{doc_id} is a folder (CollectionType), not a document; "
                    "rendering folders is not supported."
                ),
            }

        all_page_ids = self.cache.get_page_ids(doc_id)
        if not all_page_ids:
            return {"error": True, "detail": "No pages found in document"}

        doc_name = meta.visible_name or doc_id

        selected_indices = _resolve_page_selection(
            total=len(all_page_ids),
            page_indices=page_indices,
            last_n=last_n,
            first_n=first_n,
        )

        return self.renderer.render_document_pages(
            doc_id=doc_id,
            document_name=doc_name,
            page_ids=all_page_ids,
            page_dir=self.base_path / doc_id,
            selected_indices=selected_indices,
        )

    def cleanup_renders(self) -> dict:
        """Remove all files from the render directory."""
        return self.renderer.cleanup()

    # ------------------------------------------------------------------
    # Write API (opt-in via REMARKABLE_ENABLE_WRITE_TOOLS env flag at the MCP layer)
    # ------------------------------------------------------------------

    def rename_document(
        self,
        doc_id: str,
        new_name: str,
        dry_run: bool = False,
    ) -> dict:
        """Rename a document by mutating its .metadata visibleName field.

        Validates target doc_id exists and is DocumentType. Refuses empty names.
        In dry_run mode, returns the planned change without writing anything.
        Otherwise writes atomically and returns the timestamped backup path.
        """
        cleaned_name = (new_name or "").strip()
        if not cleaned_name:
            return {"error": True, "detail": "new_name must be a non-empty string"}

        meta = self.cache.load_metadata(doc_id)
        if meta is None:
            return {"error": True, "detail": f"Document not found: {doc_id}"}
        if isinstance(meta, CollectionMetadata):
            return {
                "error": True,
                "detail": (
                    f"{doc_id} is a folder (CollectionType); "
                    "folder rename is not supported by this tool"
                ),
            }

        old_name = meta.visible_name or doc_id
        if dry_run:
            return {
                "doc_id": doc_id,
                "dry_run": True,
                "old_name": old_name,
                "new_name": cleaned_name,
            }

        writer = MetadataWriter(self.base_path)
        _old, _new, backup = writer.update_metadata(
            doc_id, {"visibleName": cleaned_name}
        )
        return {
            "doc_id": doc_id,
            "dry_run": False,
            "old_name": old_name,
            "new_name": cleaned_name,
            "backup_path": str(backup),
        }

    def move_document(
        self,
        doc_id: str,
        new_parent: str,
        dry_run: bool = False,
    ) -> dict:
        """Move a document to a different folder by mutating .metadata parent.

        new_parent must be either "" (root) or an existing CollectionType folder id.
        Refuses targets that are documents, missing, or the doc itself.
        In dry_run mode, returns the planned change without writing anything.
        """
        meta = self.cache.load_metadata(doc_id)
        if meta is None:
            return {"error": True, "detail": f"Document not found: {doc_id}"}
        if isinstance(meta, CollectionMetadata):
            return {
                "error": True,
                "detail": (
                    f"{doc_id} is a folder (CollectionType); "
                    "folder moves are not supported by this tool"
                ),
            }
        if new_parent == doc_id:
            return {"error": True, "detail": "Cannot move a document into itself"}

        if new_parent != "":
            target = self.cache.load_metadata(new_parent)
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
                        "documents cannot contain other documents"
                    ),
                }

        old_parent = meta.parent
        if dry_run:
            return {
                "doc_id": doc_id,
                "dry_run": True,
                "old_parent": old_parent,
                "new_parent": new_parent,
            }

        writer = MetadataWriter(self.base_path)
        _old, _new, backup = writer.update_metadata(doc_id, {"parent": new_parent})
        return {
            "doc_id": doc_id,
            "dry_run": False,
            "old_parent": old_parent,
            "new_parent": new_parent,
            "backup_path": str(backup),
        }


def _document_summary(
    doc_id: str,
    name: str,
    meta: DocumentMetadata,
    content: ContentMetadata | None,
) -> dict:
    """Build the per-document dict returned by list_documents."""
    summary = {
        "doc_id": doc_id,
        "name": name,
        "type": meta.type,
        "parent": meta.parent,
        "last_modified": meta.last_modified_iso or "",
        "page_count": len(content.page_ids) if content is not None else 0,
    }
    summary.update(_content_summary(content))
    return summary


def _content_summary(content: ContentMetadata | None) -> dict:
    """Project ContentMetadata into the JSON fields exposed by list/get tools."""
    if content is None:
        return {
            "file_type": "",
            "document_title": None,
            "authors": [],
            "tags": [],
            "annotated": False,
            "original_page_count": -1,
            "size_in_bytes": 0,
        }
    return {
        "file_type": content.file_type,
        "document_title": content.document_metadata.title,
        "authors": list(content.document_metadata.authors),
        "tags": content.tag_names,
        "annotated": content.annotated,
        "original_page_count": content.original_page_count,
        "size_in_bytes": content.size_in_bytes_int,
    }


def _resolve_page_selection(
    total: int,
    page_indices: list[int] | None,
    last_n: int | None,
    first_n: int | None,
) -> list[int]:
    """Resolve page-selection args to an ordered list of page indices."""
    if page_indices is not None:
        return page_indices
    if last_n is not None:
        start = max(0, total - last_n)
        return list(range(start, total))
    if first_n is not None:
        return list(range(min(first_n, total)))
    return list(range(total))
