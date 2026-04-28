"""Render-pipeline MCP tools: page-range render, full-document render, render-dir cleanup.

Each tool delegates to the RenderFacade which owns the cache+renderer dependencies.
"""

from fastmcp import FastMCP

from ..annotations import ANNOTATIONS, TITLES
from ..facades import RenderFacade
from ..responses import CleanupResponse, RenderResponse
from ._artifacts import render_response_to_tool_result
from ._boundary import tool_error_boundary


def register_render_tools(mcp: FastMCP, *, render: RenderFacade) -> None:
    """Register the render-pipeline tools on the FastMCP app."""

    @mcp.tool(
        title=TITLES["remarkable_render_pages"],
        annotations=ANNOTATIONS["remarkable_render_pages"],
        output_schema=RenderResponse.model_json_schema(),
    )
    @tool_error_boundary
    def remarkable_render_pages(
        doc_id: str,
        page_indices: list[int] | None = None,
        last_n: int | None = None,
        first_n: int | None = None,
    ):
        """Render selected pages of a reMarkable document to a single PDF.
        Priority: page_indices > last_n > first_n > all pages.
        For a 200-page doc with last_n=5, only the last 5 pages are rendered.
        Returns structured render metadata (pages rendered/failed, indices,
        sources_used, and a deprecated local pdf_path) plus the rendered PDF
        attached as an MCP EmbeddedResource so clients without host
        filesystem access can still read it."""
        response = render.render_pages(
            doc_id, page_indices=page_indices, last_n=last_n, first_n=first_n
        )
        return render_response_to_tool_result(response)

    @mcp.tool(
        title=TITLES["remarkable_render_document"],
        annotations=ANNOTATIONS["remarkable_render_document"],
        output_schema=RenderResponse.model_json_schema(),
    )
    @tool_error_boundary
    def remarkable_render_document(doc_id: str):
        """Render all pages of a reMarkable document to a single PDF.
        Convenience wrapper - equivalent to render_pages with no selection args.
        Returns the same structured metadata + embedded PDF artifact as
        remarkable_render_pages."""
        response = render.render_pages(doc_id)
        return render_response_to_tool_result(response)

    @mcp.tool(
        title=TITLES["remarkable_cleanup_renders"],
        annotations=ANNOTATIONS["remarkable_cleanup_renders"],
        output_schema=CleanupResponse.model_json_schema(),
    )
    @tool_error_boundary
    def remarkable_cleanup_renders():
        """Remove temporary rendered PDFs from the render directory.
        Returns the number of files removed and bytes freed.
        Call this after you're done reading rendered PDFs."""
        return render.cleanup_renders()
