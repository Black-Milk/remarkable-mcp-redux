"""Convert facade RenderResponse into an MCP-transport artifact for tool returns.

Lives in ``tools/`` because it is the only layer allowed to import FastMCP
transport types (``ToolResult``, ``File``). Facades and ``core`` stay
transport-agnostic.

The helper attaches the rendered PDF as an MCP ``EmbeddedResource`` content
block whenever ``RenderResponse.pdf_path`` points at an extant file, and
always carries the response's sparse ``model_dump`` as ``structured_content``
so existing JSON Schema clients keep working unchanged.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp.tools.tool import ToolResult
from fastmcp.utilities.types import File

from ..responses import RenderResponse


def render_response_to_tool_result(response: RenderResponse) -> ToolResult:
    """Wrap a ``RenderResponse`` in a FastMCP ``ToolResult`` with PDF artifact.

    The returned ``ToolResult`` always carries ``response.model_dump()`` as
    ``structured_content`` so consumers that read the declared output schema
    keep their existing contract. When ``pdf_path`` is set and the file is
    still present on disk, the PDF is base64-encoded and attached as an
    ``EmbeddedResource`` content block so MCP clients can consume the render
    without any host filesystem access.

    A ``pdf_path`` that points at a missing file (e.g. removed by a
    concurrent ``cleanup_renders``) is treated as "no artifact this time" —
    the structured metadata still surfaces, but no resource block is
    attached. This keeps a previously-successful facade call from crashing
    at the transport boundary on a transient disk-state mismatch.
    """
    structured = response.model_dump()
    pdf_path = response.pdf_path

    if pdf_path and Path(pdf_path).exists():
        artifact = File(path=pdf_path, format="pdf").to_resource_content()
        return ToolResult(content=[artifact], structured_content=structured)

    return ToolResult(structured_content=structured)


__all__ = ["render_response_to_tool_result"]
