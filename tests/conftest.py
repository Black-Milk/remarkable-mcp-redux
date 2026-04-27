# ABOUTME: Shared pytest fixtures for remarkable-mcp tests.
# ABOUTME: Provides synthetic reMarkable cache directories, folders, and helper factories.

import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

# Folder UUIDs used by fixtures (kept stable so tests can refer to them by id)
WORK_FOLDER_ID = "ffff-folder-work"
PERSONAL_FOLDER_ID = "ffff-folder-personal"

# Trashed and pinned doc ids for write-path tests
TRASHED_DOC_ID = "tttt-trashed-doc"
PINNED_DOC_ID = "pppp-pinned-doc"

# Nested-folder fixture ids: A > B > C (linear) plus sibling D under root
NESTED_FOLDER_A = "nest-a"
NESTED_FOLDER_B = "nest-b"
NESTED_FOLDER_C = "nest-c"
NESTED_FOLDER_D = "nest-d"
NESTED_DOC_INSIDE_C = "nest-doc-c"

# Render-pipeline fixture ids
UNANNOTATED_PDF_DOC_ID = "uuuu-unannotated-pdf"
LEGACY_V5_DOC_ID = "vvvv-legacy-v5"
MIXED_PDF_DOC_ID = "mmmm-mixed-pdf"

# Real .rm headers are 43 bytes: a literal version banner padded with spaces.
# We replicate that shape so parse_rm_version sees realistic input.
_RM_HEADER_LEN = 43


@pytest.fixture
def fake_cache(tmp_path):
    """Create a synthetic reMarkable cache directory with sample documents and folders.

    Layout mirrors the real cache:
      <base>/<doc_id>.metadata   - JSON with type, visibleName, parent, lastModified, ...
      <base>/<doc_id>.content    - JSON with fileType, documentMetadata, tags, pages, ...
      <base>/<doc_id>/<page>.rm  - binary .rm stub files (DocumentType only)

    Documents:
      Morning Journal      - notebook, no embedded title, has user tag
      Architecture Sketch  - PDF with embedded title and authors, annotated
      Empty Notebook       - notebook with one page id but no .rm files
      Trashed Note         - deleted=True (used to test write-tool refusals)
      Pinned Reference     - pinned=True (used to test pin/unpin round-trips)

    Folders:
      Work                 - root folder
      Personal             - root folder
    """
    _create_folder(
        tmp_path,
        folder_id=WORK_FOLDER_ID,
        name="Work",
        parent="",
        last_modified="1709500000000",
    )
    _create_folder(
        tmp_path,
        folder_id=PERSONAL_FOLDER_ID,
        name="Personal",
        parent="",
        last_modified="1709400000000",
    )

    _create_document(
        tmp_path,
        doc_id="aaaa-1111-2222-3333",
        name="Morning Journal",
        page_ids=["page-a1", "page-a2", "page-a3"],
        content_format="v2",
        last_modified="1709500000000",
        file_type="notebook",
        tags=["Journal"],
        extra_metadata={"LastTool": "Ballpointv2"},
        original_page_count=-1,
        size_in_bytes="2140",
    )

    _create_document(
        tmp_path,
        doc_id="bbbb-4444-5555-6666",
        name="Architecture Sketch",
        page_ids=["page-b1", "page-b2"],
        content_format="v1",
        last_modified="1709400000000",
        parent=WORK_FOLDER_ID,
        file_type="pdf",
        document_title="Software Architecture Patterns",
        authors=["Mark Richards"],
        tags=["Reference", "Architecture"],
        extra_metadata={"LastTool": "Finelinerv2"},
        original_page_count=42,
        size_in_bytes="123456",
    )

    _create_document(
        tmp_path,
        doc_id="cccc-7777-8888-9999",
        name="Empty Notebook",
        page_ids=["page-c1"],
        content_format="v2",
        last_modified="1709300000000",
        create_rm_files=False,
        file_type="notebook",
        original_page_count=-1,
        size_in_bytes="0",
    )

    _create_document(
        tmp_path,
        doc_id=TRASHED_DOC_ID,
        name="Trashed Note",
        page_ids=["page-trashed"],
        content_format="v2",
        last_modified="1709200000000",
        file_type="notebook",
        original_page_count=-1,
        size_in_bytes="50",
        deleted=True,
    )

    _create_document(
        tmp_path,
        doc_id=PINNED_DOC_ID,
        name="Pinned Reference",
        page_ids=["page-pinned"],
        content_format="v2",
        last_modified="1709100000000",
        file_type="notebook",
        original_page_count=-1,
        size_in_bytes="25",
        pinned=True,
    )

    return tmp_path


@pytest.fixture
def nested_folder_cache(tmp_path):
    """Cache with a linear A>B>C folder chain plus a sibling D under root.

    Layout:
        root
          ├── A (NESTED_FOLDER_A)
          │     └── B (NESTED_FOLDER_B)
          │           └── C (NESTED_FOLDER_C)
          │                 └── doc (NESTED_DOC_INSIDE_C)
          └── D (NESTED_FOLDER_D)

    Used by ancestry, descendant-counting, and sibling-uniqueness tests.
    """
    _create_folder(tmp_path, folder_id=NESTED_FOLDER_A, name="A", parent="")
    _create_folder(
        tmp_path, folder_id=NESTED_FOLDER_B, name="B", parent=NESTED_FOLDER_A
    )
    _create_folder(
        tmp_path, folder_id=NESTED_FOLDER_C, name="C", parent=NESTED_FOLDER_B
    )
    _create_folder(tmp_path, folder_id=NESTED_FOLDER_D, name="D", parent="")
    _create_document(
        tmp_path,
        doc_id=NESTED_DOC_INSIDE_C,
        name="Doc inside C",
        page_ids=["nested-page-1"],
        content_format="v2",
        parent=NESTED_FOLDER_C,
        file_type="notebook",
        original_page_count=-1,
        size_in_bytes="100",
    )
    return tmp_path


@pytest.fixture
def render_dir(tmp_path):
    """Provide a temporary render output directory."""
    d = tmp_path / "renders"
    d.mkdir()
    return d


@pytest.fixture
def unannotated_pdf_cache(tmp_path):
    """Cache containing one PDF document with no .rm files but a real source PDF.

    Mirrors the on-device shape of an unread/unannotated PDF: a 3-page
    ``<doc_id>/<doc_id>.pdf`` is present, but no ``<page>.rm`` files exist.
    Drives Bug 1 (PDF passthrough) coverage end-to-end.
    """
    page_ids = ["pdf-page-1", "pdf-page-2", "pdf-page-3"]
    _create_document(
        tmp_path,
        doc_id=UNANNOTATED_PDF_DOC_ID,
        name="Unannotated PDF",
        page_ids=page_ids,
        content_format="v2",
        file_type="pdf",
        create_rm_files=False,
        create_source_pdf=True,
        original_page_count=3,
        size_in_bytes="4096",
    )
    return tmp_path


@pytest.fixture
def legacy_v5_cache(tmp_path):
    """Cache containing one notebook whose .rm files are pre-firmware-v3 v5 format.

    Drives Bug 2 (legacy v5 detection) coverage. The .rm files carry a real
    43-byte v5 header so ``parse_rm_version`` returns 5.
    """
    page_ids = ["v5-page-1", "v5-page-2"]
    _create_document(
        tmp_path,
        doc_id=LEGACY_V5_DOC_ID,
        name="Real Analysis (legacy)",
        page_ids=page_ids,
        content_format="v2",
        file_type="notebook",
        rm_version=5,
        original_page_count=-1,
        size_in_bytes="200",
    )
    return tmp_path


@pytest.fixture
def mixed_pdf_cache(tmp_path):
    """Cache containing a partially-annotated PDF.

    Three pages: index 1 has a .rm file (annotated v6), indexes 0 and 2 are
    unannotated. The source PDF has all three pages. Lets the dispatcher
    exercise both ``RmV6Source`` and ``PdfPassthroughSource`` in one document.
    """
    page_ids = ["mix-page-1", "mix-page-2", "mix-page-3"]
    _create_document(
        tmp_path,
        doc_id=MIXED_PDF_DOC_ID,
        name="Mixed PDF",
        page_ids=page_ids,
        content_format="v2",
        file_type="pdf",
        create_rm_files=True,
        rm_pages=["mix-page-2"],
        rm_version=6,
        create_source_pdf=True,
        original_page_count=3,
        size_in_bytes="6000",
    )
    return tmp_path


@pytest.fixture
def empty_cache(tmp_path):
    """Provide an empty directory (no documents)."""
    return tmp_path / "empty"


@pytest.fixture
def ios_doc_cache(tmp_path):
    """Cache containing a single iOS-sourced document missing optional metadata fields."""
    metadata = {
        "type": "DocumentType",
        "visibleName": "iOS Transfer",
        "parent": "",
        "lastModified": "1777124918407",
        "createdTime": "1777124918411",
        "lastOpened": "0",
        "lastOpenedPage": 0,
        "new": False,
        "pinned": False,
        "source": "com.remarkable.ios",
    }
    doc_id = "ios-aaaa-1111"
    (tmp_path / f"{doc_id}.metadata").write_text(json.dumps(metadata))
    content = {
        "fileType": "pdf",
        "formatVersion": 1,
        "pages": ["ios-page-1"],
        "pageCount": 1,
        "originalPageCount": 1,
        "sizeInBytes": "1024",
        "documentMetadata": {},
        "extraMetadata": {},
        "tags": [],
    }
    (tmp_path / f"{doc_id}.content").write_text(json.dumps(content))
    doc_dir = tmp_path / doc_id
    doc_dir.mkdir(exist_ok=True)
    (doc_dir / "ios-page-1.rm").write_bytes(b"\x00" * 64)
    return tmp_path


def _create_folder(
    base_path: Path,
    folder_id: str,
    name: str,
    parent: str = "",
    last_modified: str = "1709500000000",
    deleted: bool = False,
    pinned: bool = False,
) -> None:
    """Helper to create a synthetic CollectionType folder record."""
    metadata = {
        "type": "CollectionType",
        "visibleName": name,
        "parent": parent,
        "lastModified": last_modified,
        "deleted": deleted,
        "pinned": pinned,
        "metadatamodified": False,
        "modified": False,
        "synced": True,
        "version": 1,
    }
    (base_path / f"{folder_id}.metadata").write_text(json.dumps(metadata))
    content: dict = {}
    (base_path / f"{folder_id}.content").write_text(json.dumps(content))


def _create_document(
    base_path: Path,
    doc_id: str,
    name: str,
    page_ids: list[str],
    content_format: str = "v2",
    last_modified: str = "1709500000000",
    create_rm_files: bool = True,
    parent: str = "",
    file_type: str = "notebook",
    document_title: str | None = None,
    authors: list[str] | None = None,
    tags: list[str] | None = None,
    extra_metadata: dict | None = None,
    original_page_count: int = -1,
    size_in_bytes: str = "0",
    deleted: bool = False,
    pinned: bool = False,
    create_source_pdf: bool = False,
    rm_version: int | None = None,
    rm_pages: list[str] | None = None,
) -> None:
    """Helper to create a synthetic DocumentType record with .metadata and .content files.

    ``rm_version`` controls how the on-disk .rm bytes look:
      - ``None`` (default): legacy 64-byte zero stub — preserves backward
        compatibility with tests that mock rmc but never inspect headers.
      - ``5``/``6``: write a real reMarkable .lines header so format-aware code
        paths can dispatch correctly.

    ``rm_pages`` lets callers create .rm files for only a subset of page_ids
    (used by the mixed-source fixture). When ``None``, all page_ids get .rm
    stubs as long as ``create_rm_files`` is True.

    ``create_source_pdf`` writes ``<doc_id>/<doc_id>.pdf`` containing a blank
    page per page id, using pypdf — the on-device cache layout for PDFs.
    """
    metadata = {
        "type": "DocumentType",
        "visibleName": name,
        "parent": parent,
        "lastModified": last_modified,
        "deleted": deleted,
        "metadatamodified": False,
        "modified": False,
        "pinned": pinned,
        "synced": True,
        "version": 1,
    }
    (base_path / f"{doc_id}.metadata").write_text(json.dumps(metadata))

    document_metadata: dict = {}
    if document_title is not None:
        document_metadata["title"] = document_title
    if authors:
        document_metadata["authors"] = authors

    content: dict = {
        "fileType": file_type,
        "documentMetadata": document_metadata,
        "extraMetadata": extra_metadata or {},
        "tags": [{"name": t, "timestamp": 0} for t in (tags or [])],
        "pageCount": len(page_ids),
        "originalPageCount": original_page_count,
        "sizeInBytes": size_in_bytes,
    }
    if content_format == "v1":
        content["pages"] = page_ids
        content["formatVersion"] = 1
    else:
        content["cPages"] = {"pages": [{"id": pid} for pid in page_ids]}
        content["formatVersion"] = 2
    (base_path / f"{doc_id}.content").write_text(json.dumps(content))

    doc_dir = base_path / doc_id
    doc_dir.mkdir(exist_ok=True)
    if create_rm_files:
        rm_payload = _rm_stub_bytes(rm_version)
        eligible_pages = page_ids if rm_pages is None else rm_pages
        for pid in eligible_pages:
            (doc_dir / f"{pid}.rm").write_bytes(rm_payload)
    if create_source_pdf:
        # Real cache layout: source PDF is a sibling of <doc_id>.metadata/.content
        # (i.e. <base_path>/<doc_id>.pdf), not inside the page directory.
        writer = PdfWriter()
        for _ in page_ids:
            writer.add_blank_page(width=612, height=792)
        with open(base_path / f"{doc_id}.pdf", "wb") as f:
            writer.write(f)


def _rm_stub_bytes(rm_version: int | None) -> bytes:
    """Build .rm file bytes. None => zero stub; 5/6 => realistic 43-byte header."""
    if rm_version is None:
        return b"\x00" * 64
    banner = f"reMarkable .lines file, version={rm_version}".encode()
    header = banner.ljust(_RM_HEADER_LEN, b" ")
    return header + b"\x00" * 21
