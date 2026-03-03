# ABOUTME: Shared pytest fixtures for remarkable-mcp tests.
# ABOUTME: Provides synthetic reMarkable cache directories and helper factories.

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def fake_cache(tmp_path):
    """Create a synthetic reMarkable cache directory with sample documents.

    Layout mirrors the real cache:
      <base>/<doc_id>.metadata   — JSON with visibleName, lastModified, type, parent
      <base>/<doc_id>.content    — JSON with page IDs (v1 or v2 format)
      <base>/<doc_id>/<page>.rm  — binary .rm stub files
    """
    # Document 1: v2 format, 3 pages
    doc1_id = "aaaa-1111-2222-3333"
    _create_document(
        tmp_path,
        doc1_id,
        name="Morning Journal",
        page_ids=["page-a1", "page-a2", "page-a3"],
        content_format="v2",
        last_modified="1709500000",
    )

    # Document 2: v1 format, 2 pages
    doc2_id = "bbbb-4444-5555-6666"
    _create_document(
        tmp_path,
        doc2_id,
        name="Architecture Sketch",
        page_ids=["page-b1", "page-b2"],
        content_format="v1",
        last_modified="1709400000",
    )

    # Document 3: v2 format, 1 page, no .rm file (blank page)
    doc3_id = "cccc-7777-8888-9999"
    _create_document(
        tmp_path,
        doc3_id,
        name="Empty Notebook",
        page_ids=["page-c1"],
        content_format="v2",
        last_modified="1709300000",
        create_rm_files=False,
    )

    return tmp_path


def _create_document(
    base_path,
    doc_id,
    name,
    page_ids,
    content_format="v2",
    last_modified="1709500000",
    create_rm_files=True,
):
    """Helper to create a synthetic reMarkable document in the cache."""
    # Write .metadata
    metadata = {
        "visibleName": name,
        "lastModified": last_modified,
        "type": "DocumentType",
        "parent": "",
    }
    meta_path = base_path / f"{doc_id}.metadata"
    meta_path.write_text(json.dumps(metadata))

    # Write .content
    if content_format == "v1":
        content = {"pages": page_ids}
    else:
        content = {"cPages": {"pages": [{"id": pid} for pid in page_ids]}}
    content_path = base_path / f"{doc_id}.content"
    content_path.write_text(json.dumps(content))

    # Create document directory with .rm stub files
    doc_dir = base_path / doc_id
    doc_dir.mkdir(exist_ok=True)
    if create_rm_files:
        for pid in page_ids:
            rm_file = doc_dir / f"{pid}.rm"
            # Write minimal bytes so the file exists (not valid .rm but enough for unit tests)
            rm_file.write_bytes(b"\x00" * 64)


@pytest.fixture
def render_dir(tmp_path):
    """Provide a temporary render output directory."""
    d = tmp_path / "renders"
    d.mkdir()
    return d


@pytest.fixture
def empty_cache(tmp_path):
    """Provide an empty directory (no documents)."""
    return tmp_path / "empty"
