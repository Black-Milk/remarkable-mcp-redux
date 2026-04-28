"""Convert facade RenderResponse into an MCP-transport artifact for tool returns.

Lives in ``tools/`` because it is the only layer allowed to import FastMCP
transport types (``ToolResult``, ``File``, ``ImageContent``,
``TextContent``). Facades and ``core`` stay transport-agnostic.

Default policy is tuned for Claude Desktop, which silently drops
``application/pdf`` ``EmbeddedResource`` blocks: the merged PDF is
rasterized to one PNG ``ImageContent`` block per rendered page so the model
can actually see the page contents. The original merged PDF stays on disk
and remains addressable via ``RenderResponse.pdf_path`` for clients that
can read host paths (Cursor agent mode, Desktop Commander, etc.). The PDF
``EmbeddedResource`` block is still available behind the
``attach_pdf_resource`` opt-in for spec-compliant clients that handle
non-image embedded resources.
"""

from __future__ import annotations

import base64
from pathlib import Path

from fastmcp.tools.tool import ToolResult
from fastmcp.utilities.types import File
from mcp.types import ImageContent, TextContent

from ..core.rasterize import RasterizeError, rasterize_pdf_pages
from ..responses import RenderResponse


def render_response_to_tool_result(
    response: RenderResponse,
    *,
    attach_images: bool = True,
    image_dpi: int = 150,
    max_image_pages: int = 10,
    attach_pdf_resource: bool = False,
) -> ToolResult:
    """Wrap a ``RenderResponse`` in a FastMCP ``ToolResult``.

    Defaults match Claude Desktop's reality:

    - ``attach_images=True``: rasterize the rendered pages of the merged PDF
      and attach one PNG ``ImageContent`` block per page so the model can
      actually see the rendered output. Disable to skip the rasterization
      cost when only structured metadata + ``pdf_path`` are needed.
    - ``image_dpi=150``: balance between legibility and payload size.
      ~150 DPI gives readable handwriting at typical reMarkable page sizes
      without ballooning into multi-MB images.
    - ``max_image_pages=10``: hard cap on how many pages we are willing to
      attach as images in a single tool call. When the render rendered more
      than this, the function attaches **no** images and instead emits a
      ``TextContent`` note explaining the cap and pointing the caller at
      ``pdf_path`` (or a follow-up ``page_indices=[…]`` call). This avoids
      pushing dozens of high-DPI PNGs into one MCP response.
    - ``attach_pdf_resource=False``: opt-in PDF ``EmbeddedResource``
      attachment for clients that can consume non-image resource blocks.
      Off by default because Claude Desktop currently drops PDF resources.

    The returned ``ToolResult`` always carries ``response.model_dump()`` as
    ``structured_content`` so consumers that read the declared output schema
    keep their existing contract.

    A ``pdf_path`` that points at a missing file (e.g. removed by a
    concurrent ``cleanup_renders``) degrades gracefully — the structured
    metadata still surfaces, but no image / resource block is attached.
    Rasterization failures degrade the same way (best-effort imagery, never
    crash the tool call).
    """
    structured = response.model_dump()
    pdf_path = response.pdf_path
    pages_rendered = response.pages_rendered

    # Fast path: no PDF on disk → just structured metadata. Either no
    # pages rendered (every selected page failed) or the file was swept
    # by a concurrent cleanup_renders.
    if not pdf_path or not Path(pdf_path).exists():
        return ToolResult(structured_content=structured)

    blocks: list[ImageContent | TextContent | object] = []

    if attach_images and pages_rendered > 0:
        if pages_rendered > max_image_pages:
            blocks.append(
                TextContent(
                    type="text",
                    text=(
                        f"Skipped image attachment: render produced {pages_rendered} "
                        f"pages, exceeding max_image_pages={max_image_pages}. "
                        f"Open the PDF at pdf_path, or call again with a narrower "
                        f"page_indices/first_n/last_n to get inline images."
                    ),
                )
            )
        else:
            try:
                # The merged PDF only contains successfully rendered pages,
                # numbered 0..pages_rendered-1, regardless of which original
                # document indices were selected — so we always rasterize the
                # full merged PDF here.
                pngs = rasterize_pdf_pages(
                    Path(pdf_path),
                    page_indices=list(range(pages_rendered)),
                    dpi=image_dpi,
                )
                for png in pngs:
                    blocks.append(
                        ImageContent(
                            type="image",
                            data=base64.b64encode(png).decode("ascii"),
                            mimeType="image/png",
                        )
                    )
            except RasterizeError as exc:
                blocks.append(
                    TextContent(
                        type="text",
                        text=(
                            f"Image rasterization failed ({exc}). The merged PDF "
                            f"is still available at pdf_path."
                        ),
                    )
                )

    if attach_pdf_resource:
        blocks.append(File(path=pdf_path, format="pdf").to_resource_content())

    if not blocks:
        return ToolResult(structured_content=structured)
    return ToolResult(content=blocks, structured_content=structured)


__all__ = ["render_response_to_tool_result"]
