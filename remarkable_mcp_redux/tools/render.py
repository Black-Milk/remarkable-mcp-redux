# ABOUTME: Render-pipeline MCP tools: page-range render, full-document render, render-dir cleanup.
# ABOUTME: Each tool delegates to the RenderFacade which owns the cache+renderer dependencies.

from fastmcp import FastMCP

from ..facades import RenderFacade


def register_render_tools(mcp: FastMCP, *, render: RenderFacade) -> None:
    """Register the render-pipeline tools on the FastMCP app."""

    @mcp.tool()
    def remarkable_render_pages(
        doc_id: str,
        page_indices: list[int] | None = None,
        last_n: int | None = None,
        first_n: int | None = None,
    ) -> dict:
        """Render selected pages of a reMarkable document to a single PDF.
        Priority: page_indices > last_n > first_n > all pages.
        For a 200-page doc with last_n=5, only the last 5 pages are rendered.
        Returns the PDF path, document name, pages rendered/failed, and indices."""
        return render.render_pages(
            doc_id, page_indices=page_indices, last_n=last_n, first_n=first_n
        )

    @mcp.tool()
    def remarkable_render_document(doc_id: str) -> dict:
        """Render all pages of a reMarkable document to a single PDF.
        Convenience wrapper - equivalent to render_pages with no selection args.
        Returns the PDF path, document name, pages rendered/failed, and indices."""
        return render.render_pages(doc_id)

    @mcp.tool()
    def remarkable_cleanup_renders() -> dict:
        """Remove temporary rendered PDFs from the render directory.
        Returns the number of files removed and bytes freed.
        Call this after you're done reading rendered PDFs."""
        return render.cleanup_renders()
