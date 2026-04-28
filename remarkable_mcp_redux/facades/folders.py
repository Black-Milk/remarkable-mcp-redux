# ABOUTME: FoldersFacade — read-only operations on CollectionType records.
# ABOUTME: Filters and paginates folder listing responses.

from ..core.cache import RemarkableCache
from ..responses import FolderEntry, FolderListResponse
from ._helpers import (
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
    ) -> FolderListResponse:
        """List CollectionType (folder) records in the cache.

        Returns folder summaries with id, name, parent, pinned flag, and ISO
        timestamp. Optional filters:
          - search: case-insensitive substring match on visibleName.
          - pinned: True returns only pinned (favorited) folders, False returns
            only unpinned, None disables the filter.
          - parent: direct-child filter. None disables the filter, "" matches
            root, "<folder_id>" matches a validated CollectionType folder id.

        Pagination is applied after filtering.

        Raises ``ValidationError`` for bad pagination args, ``NotFoundError``
        for an unknown ``parent``, and ``KindMismatchError`` when ``parent``
        resolves to a document.
        """
        validate_pagination(limit, offset)
        validate_parent_for_listing(self._cache, parent)

        if not self._cache.exists():
            page = paginate_response([], "folders", limit, offset, parent)
            return _folder_list_from_page(page)

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

        page = paginate_response(folders, "folders", limit, offset, parent)
        return _folder_list_from_page(page)


def _folder_list_from_page(page: dict) -> FolderListResponse:
    """Wrap a paginated dict ``page`` into a ``FolderListResponse`` model.

    Uses ``model_validate`` so that fields absent from ``page`` (notably
    ``parent`` when the caller did not filter) stay outside the model's
    ``model_fields_set`` and therefore drop out of the wire dict.
    """
    payload = dict(page)
    payload["folders"] = [FolderEntry.model_validate(f) for f in page["folders"]]
    return FolderListResponse.model_validate(payload)
