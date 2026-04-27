# ABOUTME: RemarkableClient composition root: owns cache + renderer, exposes per-domain facades.
# ABOUTME: Forwarder methods (REMOVE IN PHASE 1) preserve the pre-refactor API for existing tests.

from pathlib import Path

from .config import DEFAULT_BASE_PATH, DEFAULT_RENDER_DIR, ensure_cairo_library_path
from .core.cache import RemarkableCache
from .core.render import RemarkableRenderer
from .facades import (
    DocumentsFacade,
    FoldersFacade,
    RenderFacade,
    StatusFacade,
    WritesFacade,
)


class RemarkableClient:
    """Composition root for reMarkable read + write surfaces.

    Owns long-lived resources (cache, renderer) and exposes one facade per
    domain. All business logic lives on the facades; this class only wires
    them together.

    Domain access (preferred, post-Phase-1):
        client.documents.list(...)
        client.folders.list(...)
        client.render.render_pages(...)
        client.render.cleanup_renders()
        client.status.check()
        client.writes.rename_document(...)
        ... etc.

    The flat methods below are temporary forwarders that preserve the
    pre-refactor surface for tests still calling ``client.list_documents(...)``.
    They are removed in Phase 1 alongside the test split.
    """

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

        self.documents = DocumentsFacade(self.cache)
        self.folders = FoldersFacade(self.cache)
        self.render = RenderFacade(self.base_path, self.cache, self.renderer)
        self.status = StatusFacade(self.base_path, self.cache)
        self.writes = WritesFacade(self.base_path, self.cache)

    # ------------------------------------------------------------------
    # Forwarder methods — REMOVE IN PHASE 1
    # ------------------------------------------------------------------
    # These thin delegations preserve the pre-refactor public surface so
    # existing tests can call ``client.list_documents(...)`` unchanged.
    # Phase 1 splits the test suite and rewrites call sites to the
    # facade-direct style (``client.documents.list(...)``); these methods
    # are deleted at the same time.

    def check_status(self) -> dict:  # REMOVE IN PHASE 1
        return self.status.check()

    def list_documents(  # REMOVE IN PHASE 1
        self,
        search: str | None = None,
        file_type: str | None = None,
        tag: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        return self.documents.list(
            search=search,
            file_type=file_type,
            tag=tag,
            pinned=pinned,
            parent=parent,
            limit=limit,
            offset=offset,
        )

    def list_folders(  # REMOVE IN PHASE 1
        self,
        search: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        return self.folders.list(
            search=search,
            pinned=pinned,
            parent=parent,
            limit=limit,
            offset=offset,
        )

    def get_document_info(  # REMOVE IN PHASE 1
        self, doc_id: str, include_page_ids: bool = True
    ) -> dict:
        return self.documents.get_info(doc_id, include_page_ids=include_page_ids)

    def render_pages(  # REMOVE IN PHASE 1
        self,
        doc_id: str,
        page_indices: list[int] | None = None,
        last_n: int | None = None,
        first_n: int | None = None,
    ) -> dict:
        return self.render.render_pages(
            doc_id, page_indices=page_indices, last_n=last_n, first_n=first_n
        )

    def cleanup_renders(self) -> dict:  # REMOVE IN PHASE 1
        return self.render.cleanup_renders()

    def rename_document(  # REMOVE IN PHASE 1
        self, doc_id: str, new_name: str, dry_run: bool = False
    ) -> dict:
        return self.writes.rename_document(doc_id, new_name, dry_run=dry_run)

    def rename_folder(  # REMOVE IN PHASE 1
        self, folder_id: str, new_name: str, dry_run: bool = False
    ) -> dict:
        return self.writes.rename_folder(folder_id, new_name, dry_run=dry_run)

    def move_document(  # REMOVE IN PHASE 1
        self, doc_id: str, new_parent: str, dry_run: bool = False
    ) -> dict:
        return self.writes.move_document(doc_id, new_parent, dry_run=dry_run)

    def move_folder(  # REMOVE IN PHASE 1
        self, folder_id: str, new_parent: str, dry_run: bool = False
    ) -> dict:
        return self.writes.move_folder(folder_id, new_parent, dry_run=dry_run)

    def pin_document(  # REMOVE IN PHASE 1
        self, doc_id: str, pinned: bool, dry_run: bool = False
    ) -> dict:
        return self.writes.pin_document(doc_id, pinned, dry_run=dry_run)

    def restore_metadata(  # REMOVE IN PHASE 1
        self, doc_id: str, dry_run: bool = False
    ) -> dict:
        return self.writes.restore_metadata(doc_id, dry_run=dry_run)

    def cleanup_metadata_backups(  # REMOVE IN PHASE 1
        self,
        older_than_days: int | None = None,
        doc_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        return self.writes.cleanup_metadata_backups(
            older_than_days=older_than_days,
            doc_id=doc_id,
            dry_run=dry_run,
        )

    def create_folder(  # REMOVE IN PHASE 1
        self, name: str, parent: str = "", dry_run: bool = False
    ) -> dict:
        return self.writes.create_folder(name, parent=parent, dry_run=dry_run)
