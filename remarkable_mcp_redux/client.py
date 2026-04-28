# ABOUTME: RemarkableClient composition root: owns cache + renderer, exposes per-domain facades.
# ABOUTME: All business logic lives on the facades; this class only wires them together.

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

    Domain access:
        client.documents.list(...)
        client.folders.list(...)
        client.render.render_pages(...)
        client.render.cleanup_renders()
        client.status.check()
        client.writes.rename_document(...)
        ... etc.
    """

    def __init__(
        self,
        base_path: Path = DEFAULT_BASE_PATH,
        render_dir: Path = DEFAULT_RENDER_DIR,
    ):
        ensure_cairo_library_path()
        self.base_path = Path(base_path)
        self.render_dir = Path(render_dir)
        self._cache = RemarkableCache(self.base_path)
        self._renderer = RemarkableRenderer(self.render_dir)

        self.documents = DocumentsFacade(self._cache)
        self.folders = FoldersFacade(self._cache)
        self.render = RenderFacade(self.base_path, self._cache, self._renderer)
        self.status = StatusFacade(self.base_path, self._cache)
        self.writes = WritesFacade(self.base_path, self._cache)
