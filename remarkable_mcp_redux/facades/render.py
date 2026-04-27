# ABOUTME: RenderFacade — orchestrates page-source resolution and PDF rendering.
# ABOUTME: Owns the cleanup_renders sweeper. Diagnostics live in StatusFacade.

from pathlib import Path

from ..core.cache import RemarkableCache
from ..core.page_sources import (
    MissingSource,
    PageSource,
    PdfPassthroughSource,
    RmV5Source,
    RmV6Source,
)
from ..core.render import RemarkableRenderer
from ..core.rm_format import parse_rm_version
from ..schemas import CollectionMetadata, ContentMetadata


class RenderFacade:
    """Document rendering and render-directory cleanup."""

    def __init__(
        self,
        base_path: Path,
        cache: RemarkableCache,
        renderer: RemarkableRenderer,
    ):
        self._base_path = base_path
        self._cache = cache
        self._renderer = renderer

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

        meta = self._cache.load_metadata(doc_id)
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

        all_page_ids = self._cache.get_page_ids(doc_id)
        if not all_page_ids:
            return {"error": True, "detail": "No pages found in document"}

        doc_name = meta.visible_name or doc_id
        content = self._cache.load_content(doc_id)

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

        return self._renderer.render_document_pages(
            doc_id=doc_id,
            document_name=doc_name,
            plan=plan,
            selected_indices=selected_indices,
        )

    def cleanup_renders(self) -> dict:
        """Remove all files from the render directory."""
        return self._renderer.cleanup()

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
        page_dir = self._base_path / doc_id
        file_type = content.file_type if content is not None else ""
        # The source PDF lives as a sibling of <doc_id>.metadata/.content
        # (e.g. <cache>/<doc_id>.pdf), not inside the page directory.
        source_pdf = self._base_path / f"{doc_id}.pdf"
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
