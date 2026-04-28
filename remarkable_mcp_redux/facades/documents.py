"""DocumentsFacade — read-only operations on DocumentType records.

Filters/paginates list responses and produces detailed get_info responses.
"""

from ..core.cache import RemarkableCache
from ..exceptions import KindMismatchError, NotFoundError
from ..responses import (
    DocumentEntry,
    DocumentInfoResponse,
    DocumentListResponse,
)
from ..schemas import CollectionMetadata, ContentMetadata, DocumentMetadata
from ._helpers import (
    paginate_response,
    validate_pagination,
    validate_parent_for_listing,
)


class DocumentsFacade:
    """Read-only document listing and per-document metadata lookups."""

    def __init__(self, cache: RemarkableCache):
        self._cache = cache

    def list(
        self,
        *,
        search: str | None = None,
        file_type: str | None = None,
        tag: str | None = None,
        pinned: bool | None = None,
        parent: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentListResponse:
        """List DocumentType records in the cache.

        Folders (CollectionType) are filtered out. Optional filters:
          - search: case-insensitive substring match on visibleName.
          - file_type: exact match on the .content fileType (e.g. "pdf", "notebook").
          - tag: exact match against any user-applied tag name in .content.
          - pinned: True returns only pinned (favorited) records, False returns
            only unpinned, None disables the filter.
          - parent: direct-child filter. None disables the filter, "" matches
            root, "<folder_id>" matches a validated CollectionType folder id.

        Pagination is applied after filtering. Combine ``has_more`` with
        ``offset`` + ``limit`` to walk large libraries in chunks that stay
        under MCP per-call response budgets.

        Raises ``ValidationError`` for bad pagination args, ``NotFoundError``
        for an unknown ``parent``, and ``KindMismatchError`` when ``parent``
        resolves to a document. The tools/ boundary translates these into the
        ``ToolError`` wire envelope.
        """
        validate_pagination(limit, offset)
        validate_parent_for_listing(self._cache, parent)

        if not self._cache.exists():
            page = paginate_response([], "documents", limit, offset, parent)
            return _document_list_from_page(page)

        documents: list[dict] = []
        for doc_id, meta in self._cache.iter_documents():
            if parent is not None and (meta.parent or "") != parent:
                continue
            name = meta.visible_name or doc_id
            if search and search.lower() not in name.lower():
                continue
            if pinned is not None and bool(meta.pinned) is not pinned:
                continue
            content = self._cache.load_content(doc_id)
            if file_type is not None and (
                content is None or content.file_type != file_type
            ):
                continue
            if tag is not None and (content is None or tag not in content.tag_names):
                continue
            documents.append(_document_summary(doc_id, name, meta, content))

        page = paginate_response(documents, "documents", limit, offset, parent)
        return _document_list_from_page(page)

    def get_info(
        self, doc_id: str, *, include_page_ids: bool = True
    ) -> DocumentInfoResponse:
        """Detailed metadata for a single DocumentType record.

        When ``include_page_ids`` is False the per-page UUID list is omitted
        and the response carries ``first_page_id``/``last_page_id`` instead;
        useful for very long documents where the full id list would blow past
        MCP per-call response budgets.

        Raises ``NotFoundError`` if ``doc_id`` is not in the cache and
        ``KindMismatchError`` if it resolves to a folder.
        """
        meta = self._cache.load_metadata(doc_id)
        if meta is None:
            raise NotFoundError(f"Document not found: {doc_id}")
        if isinstance(meta, CollectionMetadata):
            raise KindMismatchError(
                f"{doc_id} is a folder (CollectionType), not a document. "
                "Use remarkable_list_folders to enumerate folders."
            )

        content = self._cache.load_content(doc_id)
        page_ids = content.page_ids if content is not None else []
        content_format = content.content_format if content is not None else "unknown"

        info: dict = {
            "doc_id": doc_id,
            "name": meta.visible_name or doc_id,
            "type": meta.type,
            "parent": meta.parent,
            "last_modified": meta.last_modified_iso or "",
            "pinned": bool(meta.pinned),
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
        return DocumentInfoResponse.model_validate(info)


def _document_list_from_page(page: dict) -> DocumentListResponse:
    """Wrap a paginated dict ``page`` into a ``DocumentListResponse`` model.

    Uses ``model_validate`` so that fields absent from ``page`` (notably
    ``parent`` when the caller did not filter) stay outside the model's
    ``model_fields_set`` and therefore drop out of the wire dict.
    """
    payload = dict(page)
    payload["documents"] = [DocumentEntry.model_validate(d) for d in page["documents"]]
    return DocumentListResponse.model_validate(payload)


def _document_summary(
    doc_id: str,
    name: str,
    meta: DocumentMetadata,
    content: ContentMetadata | None,
) -> dict:
    """Build the per-document dict used to construct a ``DocumentEntry``."""
    summary = {
        "doc_id": doc_id,
        "name": name,
        "type": meta.type,
        "parent": meta.parent,
        "last_modified": meta.last_modified_iso or "",
        "pinned": bool(meta.pinned),
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
