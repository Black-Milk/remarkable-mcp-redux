# ABOUTME: Pydantic models for raw reMarkable .metadata and .content JSON files.
# ABOUTME: Normalizes optional fields, type discriminants, page formats, and tags.

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag


def _ms_string_to_iso(value: str) -> str | None:
    """Convert a Unix epoch milliseconds string to an ISO-8601 UTC timestamp.

    reMarkable stores timestamps as decimal millisecond strings (e.g. "1709500000000").
    Returns None for empty, non-numeric, or zero values.
    """
    if not value:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


class _BaseMetadata(BaseModel):
    """Fields shared between DocumentType and CollectionType .metadata records."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    visible_name: str = Field("", alias="visibleName")
    parent: str = ""
    last_modified: str = Field("", alias="lastModified")
    pinned: bool = False
    deleted: bool = False
    metadata_modified: bool = Field(False, alias="metadatamodified")
    modified: bool = False
    synced: bool = False
    version: int = 0

    @property
    def last_modified_iso(self) -> str | None:
        """ISO-8601 representation of lastModified, or None if missing/invalid."""
        return _ms_string_to_iso(self.last_modified)


class DocumentMetadata(_BaseMetadata):
    """A reMarkable document (notebook, PDF, EPUB) metadata record."""

    type: Literal["DocumentType"] = "DocumentType"
    created_time: str = Field("", alias="createdTime")
    last_opened: str = Field("", alias="lastOpened")
    last_opened_page: int = Field(0, alias="lastOpenedPage")
    new: bool = False
    source: str = ""

    @property
    def created_time_iso(self) -> str | None:
        """ISO-8601 representation of createdTime, or None if missing/invalid."""
        return _ms_string_to_iso(self.created_time)

    @property
    def last_opened_iso(self) -> str | None:
        """ISO-8601 representation of lastOpened, or None if missing/invalid."""
        return _ms_string_to_iso(self.last_opened)


class CollectionMetadata(_BaseMetadata):
    """A reMarkable folder metadata record."""

    type: Literal["CollectionType"] = "CollectionType"


def _metadata_discriminator(v: Any) -> str:
    """Pick the metadata variant. Defaults to DocumentType if absent or unknown."""
    if isinstance(v, dict):
        return v.get("type", "DocumentType")
    return getattr(v, "type", "DocumentType")


CacheItemMetadata = Annotated[
    (
        Annotated[DocumentMetadata, Tag("DocumentType")]
        | Annotated[CollectionMetadata, Tag("CollectionType")]
    ),
    Discriminator(_metadata_discriminator),
]


class EmbeddedDocumentMetadata(BaseModel):
    """The documentMetadata block in .content (XMP/PDF metadata)."""

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    authors: list[str] = Field(default_factory=list)


class TagEntry(BaseModel):
    """A user-applied tag in .content tags / pageTags."""

    model_config = ConfigDict(extra="allow")

    name: str
    timestamp: int = 0


class CPage(BaseModel):
    """A single page entry in v2 cPages."""

    model_config = ConfigDict(extra="allow")

    id: str


class CPages(BaseModel):
    """v2 page index structure."""

    model_config = ConfigDict(extra="allow")

    pages: list[CPage] = Field(default_factory=list)


class ContentMetadata(BaseModel):
    """The reMarkable .content file."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    file_type: str = Field("", alias="fileType")
    format_version: int | None = Field(None, alias="formatVersion")
    pages: list[str] = Field(default_factory=list)
    c_pages: CPages | None = Field(None, alias="cPages")
    document_metadata: EmbeddedDocumentMetadata = Field(
        default_factory=EmbeddedDocumentMetadata, alias="documentMetadata"
    )
    extra_metadata: dict = Field(default_factory=dict, alias="extraMetadata")
    tags: list[TagEntry] = Field(default_factory=list)
    page_count: int = Field(0, alias="pageCount")
    original_page_count: int = Field(-1, alias="originalPageCount")
    size_in_bytes: str = Field("", alias="sizeInBytes")

    @property
    def page_ids(self) -> list[str]:
        """Extract page UUIDs in order, supporting v1 and v2 content formats."""
        if self.pages:
            return list(self.pages)
        if self.c_pages is not None:
            return [p.id for p in self.c_pages.pages]
        return []

    @property
    def content_format(self) -> str:
        """Detect content format: v1 (flat pages list), v2 (cPages), or unknown."""
        if self.pages:
            return "v1"
        if self.c_pages is not None:
            return "v2"
        return "unknown"

    @property
    def annotated(self) -> bool:
        """True when the document has user pen annotations (non-empty extraMetadata)."""
        return bool(self.extra_metadata)

    @property
    def size_in_bytes_int(self) -> int:
        """Parse sizeInBytes from its string form into an int. Returns 0 on failure."""
        if not self.size_in_bytes:
            return 0
        try:
            return int(self.size_in_bytes)
        except (TypeError, ValueError):
            return 0

    @property
    def tag_names(self) -> list[str]:
        """Names of the user-applied .content tags."""
        return [t.name for t in self.tags]
