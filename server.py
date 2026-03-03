# ABOUTME: MCP server entry point for reMarkable tablet document rendering.
# ABOUTME: Exposes document listing, rendering, and cache management as tools via FastMCP.

import os
import sys
import logging

from fastmcp import FastMCP

from remarkable_client import RemarkableClient

# Ensure cairosvg can find Homebrew's cairo on macOS
if "DYLD_LIBRARY_PATH" not in os.environ:
    os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib"

logging.basicConfig(stream=sys.stderr, level=logging.INFO)

mcp = FastMCP("remarkable")
client = RemarkableClient()


@mcp.tool()
def remarkable_list_documents(search: str = None) -> dict:
    """List documents in the reMarkable local cache.
    Optional case-insensitive substring filter on document names.
    Returns document IDs, names, page counts, and last modified timestamps."""
    return client.list_documents(search=search)


@mcp.tool()
def remarkable_get_document_info(doc_id: str) -> dict:
    """Get detailed metadata for a single reMarkable document.
    Returns document ID, name, page count, page IDs, and content format (v1/v2).
    Lightweight — reads JSON only, no rendering."""
    return client.get_document_info(doc_id)


@mcp.tool()
def remarkable_render_pages(
    doc_id: str,
    page_indices: list[int] = None,
    last_n: int = None,
    first_n: int = None,
) -> dict:
    """Render selected pages of a reMarkable document to a single PDF.
    Priority: page_indices > last_n > first_n > all pages.
    For a 200-page doc with last_n=5, only the last 5 pages are rendered.
    Returns the PDF path, document name, pages rendered/failed, and indices."""
    return client.render_pages(
        doc_id, page_indices=page_indices, last_n=last_n, first_n=first_n
    )


@mcp.tool()
def remarkable_render_document(doc_id: str) -> dict:
    """Render all pages of a reMarkable document to a single PDF.
    Convenience wrapper — equivalent to render_pages with no selection args.
    Returns the PDF path, document name, pages rendered/failed, and indices."""
    return client.render_pages(doc_id)


@mcp.tool()
def remarkable_check_status() -> dict:
    """Check reMarkable system status and tool availability.
    Returns whether the cache exists, document count, and rmc/cairo availability.
    Use this to diagnose issues before rendering."""
    return client.check_status()


@mcp.tool()
def remarkable_cleanup_renders() -> dict:
    """Remove temporary rendered PDFs from the render directory.
    Returns the number of files removed and bytes freed.
    Call this after you're done reading rendered PDFs."""
    return client.cleanup_renders()


if __name__ == "__main__":
    mcp.run(transport="stdio")
