1# ABOUTME: FoldersFacade — read-only operations on CollectionType records.
# ABOUTME: Filters and paginates list_folders responses.

from ._cache import RemarkableCache
from ._record_ops import (
    paginate_response,
    validate_pagination,
    validate_parent_for_listing,
)


class FoldersFacade:
    """Read-only folder listing."""

    def __init__(self, cache: RemarkableCache):
        self._cache = cache

    def list(
        self,
        *,
        search: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """List CollectionType (folder) records in the cache.

        Returns folder summaries with id, name, parent, pinned flag, and ISO
        timestamp. Optional filters:
          - search: case-insensitive substring match on visibleName.
          - pinned: True returns only pinned (favorited) folders, False returns
            only unpinned, None disables the filter.
          - parent: direct-child filter. None disables the filter, "" matches
            root, "<folder_id>" matches a validated CollectionType folder id.

        Pagination is applied after filtering.
        """
        page_error = validate_pagination(limit, offset)
        if page_error is not None:
            return page_error
        parent_error = validate_parent_for_listing(self._cache, parent)
        if parent_error is not None:
            return parent_error

        if not self._cache.exists():
            return paginate_response([], "folders", limit, offset, parent)

        folders: list[dict] = []
        for folder_id, meta in self._cache.iter_folders():
            if parent is not None and (meta.parent or "") != parent:
                continue
            name = meta.visible_name or folder_id
            if search and search.lower() not in name.lower():
                continue
            if pinned is not None and bool(meta.pinned) is not pinned:
                continue
            folders.append(
                {
                    "folder_id": folder_id,
                    "name": name,
                    "parent": meta.parent,
                    "last_modified": meta.last_modified_iso or "",
                    "pinned": bool(meta.pinned),
                }
            )

        return paginate_response(folders, "folders", limit, offset, parent)
