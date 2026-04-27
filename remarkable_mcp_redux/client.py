# ABOUTME: RemarkableClient facade that orchestrates cache loading and PDF rendering.
# ABOUTME: Public API consumed by the MCP tool layer; returns plain JSON-friendly dicts.

from pathlib import Path

from ._cache import RemarkableCache
from ._page_sources import (
    MissingSource,
    PageSource,
    PdfPassthroughSource,
    RmV5Source,
    RmV6Source,
)
from ._render import (
    RemarkableRenderer,
    check_cairo_available,
    check_rmc_available,
)
from ._rm_format import parse_rm_version
from ._writes import (
    MetadataCreator,
    MetadataRestorer,
    MetadataWriter,
    cleanup_backups,
)
from .config import DEFAULT_BASE_PATH, DEFAULT_RENDER_DIR, ensure_cairo_library_path
from .schemas import (
    CollectionMetadata,
    ContentMetadata,
    DocumentMetadata,
)


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
        parent: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """List DocumentType records in the cache.

        Folders (CollectionType) are filtered out. Optional filters:
          - search: case-insensitive substring match on visibleName.
          - file_type: exact match on the .content fileType (e.g. "pdf", "notebook").
          - tag: exact match against any user-applied tag name in .content.
          - parent: direct-child filter. None disables the filter, "" matches
            root, "<folder_id>" matches a validated CollectionType folder id.

        Pagination is applied after filtering. Combine ``has_more`` with
        ``offset`` + ``limit`` to walk large libraries in chunks that stay
        under MCP per-call response budgets.
        """
        page_error = _validate_pagination(limit, offset)
        if page_error is not None:
            return page_error
        parent_error = self._validate_parent(parent)
        if parent_error is not None:
            return parent_error

        if not self.cache.exists():
            return _paginate_response([], "documents", limit, offset, parent)

        documents: list[dict] = []
        for doc_id, meta in self.cache.iter_documents():
            if parent is not None and (meta.parent or "") != parent:
                continue
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

        return _paginate_response(documents, "documents", limit, offset, parent)

    def list_folders(
        self,
        search: str | None = None,
        parent: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """List CollectionType (folder) records in the cache.

        Returns folder summaries with id, name, parent, and ISO timestamp.
        Optional filters:
          - search: case-insensitive substring match on visibleName.
          - parent: direct-child filter. None disables the filter, "" matches
            root, "<folder_id>" matches a validated CollectionType folder id.

        Pagination is applied after filtering.
        """
        page_error = _validate_pagination(limit, offset)
        if page_error is not None:
            return page_error
        parent_error = self._validate_parent(parent)
        if parent_error is not None:
            return parent_error

        if not self.cache.exists():
            return _paginate_response([], "folders", limit, offset, parent)

        folders: list[dict] = []
        for folder_id, meta in self.cache.iter_folders():
            if parent is not None and (meta.parent or "") != parent:
                continue
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

        return _paginate_response(folders, "folders", limit, offset, parent)

    def get_document_info(self, doc_id: str, include_page_ids: bool = True) -> dict:
        """Detailed metadata for a single DocumentType record.

        Refuses CollectionType records (folders) with an explicit error.
        When ``include_page_ids`` is False the per-page UUID list is omitted
        and the response carries ``first_page_id``/``last_page_id`` instead;
        useful for very long documents where the full id list would blow past
        MCP per-call response budgets.
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
            "content_format": content_format,
        }
        if include_page_ids:
            info["page_ids"] = page_ids
        else:
            info["first_page_id"] = page_ids[0] if page_ids else None
            info["last_page_id"] = page_ids[-1] if page_ids else None
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

        Per-page source dispatch:
          - .rm file present and v6 -> rendered via rmc + cairosvg.
          - .rm file present and v5 -> reported as ``code: "v5_unsupported"``
            (legacy pre-firmware-v3 format, rmscene cannot parse).
          - .rm absent and document is a PDF with a cached source PDF ->
            extracted directly via pypdf passthrough.
          - Otherwise -> reported as ``code: "no_source"``.

        On success the response carries ``sources_used`` with non-zero counts
        per source kind (e.g. ``{"rm_v6": 3, "pdf_passthrough": 5}``).
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
        content = self.cache.load_content(doc_id)

        selected_indices = _resolve_page_selection(
            total=len(all_page_ids),
            page_indices=page_indices,
            last_n=last_n,
            first_n=first_n,
        )

        plan = self._build_page_plan(
            doc_id=doc_id,
            page_ids=all_page_ids,
            content=content,
            selected_indices=selected_indices,
        )

        return self.renderer.render_document_pages(
            doc_id=doc_id,
            document_name=doc_name,
            plan=plan,
            selected_indices=selected_indices,
        )

    def _build_page_plan(
        self,
        doc_id: str,
        page_ids: list[str],
        content: ContentMetadata | None,
        selected_indices: list[int],
    ) -> list[PageSource | None]:
        """Resolve each selected index to a PageSource (or None for out-of-bounds).

        Policy lives here so the renderer stays mechanism-only. New source
        kinds (annotated-PDF compositing, EPUB layout PDFs, v5 backend) plug
        in by adding a branch here and a variant in ``_page_sources.py``.
        """
        page_dir = self.base_path / doc_id
        file_type = content.file_type if content is not None else ""
        # The source PDF lives as a sibling of <doc_id>.metadata/.content
        # (e.g. <cache>/<doc_id>.pdf), not inside the page directory.
        source_pdf = self.base_path / f"{doc_id}.pdf"
        source_pdf_exists = source_pdf.exists()

        plan: list[PageSource | None] = []
        for idx in selected_indices:
            if idx < 0 or idx >= len(page_ids):
                plan.append(None)
                continue

            page_id = page_ids[idx]
            rm_path = page_dir / f"{page_id}.rm"

            if rm_path.exists():
                version = parse_rm_version(rm_path)
                if version == 5:
                    plan.append(RmV5Source(rm_path=rm_path))
                else:
                    # Treat unknown/None as v6: keeps the dispatcher's default
                    # path identical to pre-refactor behaviour for any .rm bytes
                    # that don't carry a recognised banner.
                    plan.append(RmV6Source(rm_path=rm_path))
                continue

            if file_type == "pdf" and source_pdf_exists:
                plan.append(
                    PdfPassthroughSource(source_pdf=source_pdf, pdf_page_index=idx)
                )
                continue

            plan.append(MissingSource())
        return plan

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

        Validates target doc_id exists and is DocumentType. Refuses empty names
        and trashed records (records with deleted=True).
        In dry_run mode, returns the planned change without writing anything.
        Otherwise writes atomically and returns the timestamped backup path.
        """
        return self._rename_record(doc_id, new_name, expected_kind="document", dry_run=dry_run)

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
        return self._rename_record(folder_id, new_name, expected_kind="folder", dry_run=dry_run)

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
        return self._move_record(doc_id, new_parent, expected_kind="document", dry_run=dry_run)

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
        result = self._move_record(
            folder_id, new_parent, expected_kind="folder", dry_run=dry_run
        )
        if not result.get("error"):
            result["descendants_affected"] = self.cache.count_descendants(folder_id)
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
        meta = self.cache.load_metadata(doc_id)
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

        writer = MetadataWriter(self.base_path)
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
        meta_path = self.base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            return {"error": True, "detail": f"Metadata not found: {doc_id}"}

        restorer = MetadataRestorer(self.base_path)
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
            return self._cleanup_backups_dry_run(
                older_than_days=older_than_days, doc_id=doc_id
            )

        files_removed, bytes_freed, scanned, backups_remaining = cleanup_backups(
            self.base_path,
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
            target = self.cache.load_metadata(parent)
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

        if self._sibling_name_taken(parent, cleaned_name):
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

        creator = MetadataCreator(self.base_path)
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

    # ------------------------------------------------------------------
    # Private write helpers (shared by document and folder write methods)
    # ------------------------------------------------------------------

    def _rename_record(
        self,
        record_id: str,
        new_name: str,
        expected_kind: str,
        dry_run: bool,
    ) -> dict:
        """Rename a document or folder. ``expected_kind`` is "document" or "folder"."""
        cleaned_name = (new_name or "").strip()
        if not cleaned_name:
            return {"error": True, "detail": "new_name must be a non-empty string"}

        meta = self.cache.load_metadata(record_id)
        if meta is None:
            label = expected_kind.capitalize()
            return {"error": True, "detail": f"{label} not found: {record_id}"}
        kind_error = _expect_kind(meta, record_id, expected_kind, action="rename")
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
            if cleaned_name.lower() != old_name.lower() and self._sibling_name_taken(
                parent, cleaned_name, exclude_id=record_id
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

        writer = MetadataWriter(self.base_path)
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

    def _move_record(
        self,
        record_id: str,
        new_parent: str,
        expected_kind: str,
        dry_run: bool,
    ) -> dict:
        """Move a document or folder. ``expected_kind`` is "document" or "folder"."""
        meta = self.cache.load_metadata(record_id)
        if meta is None:
            label = expected_kind.capitalize()
            return {"error": True, "detail": f"{label} not found: {record_id}"}
        kind_error = _expect_kind(meta, record_id, expected_kind, action="move")
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
                        "records cannot be moved into a document"
                    ),
                }
            if target.deleted:
                return {
                    "error": True,
                    "detail": f"Target folder {new_parent} is in the trash",
                }
            if self.cache.is_descendant_of(new_parent, record_id):
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

        writer = MetadataWriter(self.base_path)
        _old, _new, backup = writer.update_metadata(record_id, {"parent": new_parent})
        return {
            id_key: record_id,
            "dry_run": False,
            "old_parent": old_parent,
            "new_parent": new_parent,
            "backup_path": str(backup),
        }

    def _validate_parent(self, parent: str | None) -> dict | None:
        """Verify ``parent`` is None, "" (root), or an existing CollectionType id.

        Returns an error dict on mismatch so list_documents/list_folders can
        surface a clear failure instead of silently returning empty pages.
        """
        if parent is None or parent == "":
            return None
        target = self.cache.load_metadata(parent)
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

    def _sibling_name_taken(
        self,
        parent: str,
        name: str,
        exclude_id: str | None = None,
    ) -> bool:
        """True if a sibling folder under ``parent`` already has this name (case-insensitive)."""
        target = name.strip().lower()
        for folder_id, folder_meta in self.cache.iter_folders():
            if exclude_id is not None and folder_id == exclude_id:
                continue
            if (folder_meta.parent or "") != parent:
                continue
            existing = (folder_meta.visible_name or "").strip().lower()
            if existing == target:
                return True
        return False

    def _cleanup_backups_dry_run(
        self,
        older_than_days: int | None,
        doc_id: str | None,
    ) -> dict:
        """Compute what cleanup_metadata_backups would do without unlinking anything."""
        from datetime import UTC, datetime

        cutoff_ts: float | None = None
        if older_than_days is not None:
            cutoff_ts = datetime.now(UTC).timestamp() - older_than_days * 86400

        if doc_id is not None:
            scan_paths = [self.base_path / f"{doc_id}.metadata"]
        else:
            scan_paths = sorted(self.base_path.glob("*.metadata"))

        files_to_remove = 0
        bytes_freed = 0
        backups_remaining = 0
        scanned = 0
        for meta_path in scan_paths:
            if not meta_path.parent.exists():
                continue
            scanned += 1
            for backup in sorted(
                meta_path.parent.glob(f"{meta_path.name}.bak.*")
            ):
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


def _expect_kind(
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


def _validate_pagination(limit: int, offset: int) -> dict | None:
    """Validate ``limit``/``offset`` arg pair. Returns an error dict or None."""
    if not isinstance(limit, int) or limit < 1:
        return {"error": True, "detail": "limit must be a positive integer"}
    if not isinstance(offset, int) or offset < 0:
        return {"error": True, "detail": "offset must be a non-negative integer"}
    return None


def _paginate_response(
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
