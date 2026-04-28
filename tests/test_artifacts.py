"""Tests for the render-artifact helper that wraps RenderResponse for MCP tools.

Covers:
  - Default behavior (PNG ``ImageContent`` blocks attached, no PDF resource).
  - ``attach_images=False`` opt-out.
  - ``attach_pdf_resource=True`` opt-in (PDF ``EmbeddedResource``).
  - ``image_dpi`` propagates to the rasterizer.
  - ``max_image_pages`` cap (no images, ``TextContent`` note instead).
  - Failure-only renders (no content blocks).
  - Stale ``pdf_path`` (file removed since the facade returned).
  - Rasterizer failure degrades to a ``TextContent`` note.
  - Integration: the registered FastMCP tool wires the helper end-to-end
    and accepts the new optional flags from a tool-call payload.
"""

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP
from fastmcp.tools.tool import ToolResult
from mcp.types import EmbeddedResource, ImageContent, TextContent

from remarkable_mcp_redux.client import RemarkableClient
from remarkable_mcp_redux.core.rasterize import RasterizeError
from remarkable_mcp_redux.responses import PageFailure, RenderResponse
from remarkable_mcp_redux.tools import register_tools
from remarkable_mcp_redux.tools._artifacts import render_response_to_tool_result


def _minimal_pdf_bytes() -> bytes:
    """A tiny but parseable PDF blob; cheap stand-in for renderer output."""
    return (
        b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000043 00000 n \n0000000098 00000 n \n"
        b"trailer<</Root 1 0 R/Size 4>>\nstartxref\n174\n%%EOF"
    )


def _png_payload(label: int = 1) -> bytes:
    """Tiny PNG-shaped blob whose first 8 bytes are the real PNG signature."""
    return b"\x89PNG\r\n\x1a\n" + bytes([label])


def _make_response(tmp_path: Path, *, pages: int = 2) -> RenderResponse:
    """Build a RenderResponse pointing at an on-disk minimal PDF."""
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())
    return RenderResponse(
        pdf_path=str(pdf_path),
        document_name="Doc",
        pages_rendered=pages,
        pages_failed=[],
        page_indices=list(range(pages)),
        sources_used={"rm_v6": pages},
    )


@pytest.mark.unit
class TestRenderResponseToToolResult:
    def test_default_attaches_image_content_per_page(self, tmp_path):
        """Default policy: one PNG ImageContent block per rendered page,
        no PDF EmbeddedResource (Claude Desktop strips application/pdf)."""
        response = _make_response(tmp_path, pages=2)

        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages",
            return_value=[_png_payload(1), _png_payload(2)],
        ):
            result = render_response_to_tool_result(response)

        assert isinstance(result, ToolResult)
        assert result.structured_content == response.model_dump()

        images = [b for b in result.content if isinstance(b, ImageContent)]
        assert len(images) == 2, "one ImageContent per rendered page"
        for img in images:
            assert img.mimeType == "image/png"
            assert base64.b64decode(img.data).startswith(b"\x89PNG\r\n\x1a\n")

        embedded = [b for b in result.content if isinstance(b, EmbeddedResource)]
        assert embedded == [], (
            "PDF EmbeddedResource must be off by default (Claude Desktop drops it)"
        )

    def test_attach_images_false_skips_rasterization(self, tmp_path):
        """attach_images=False: no rasterization, no ImageContent blocks."""
        response = _make_response(tmp_path, pages=3)

        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages",
        ) as raster:
            result = render_response_to_tool_result(response, attach_images=False)

        raster.assert_not_called()
        assert all(not isinstance(b, ImageContent) for b in result.content)
        assert all(not isinstance(b, EmbeddedResource) for b in result.content)
        assert result.structured_content == response.model_dump()

    def test_attach_pdf_resource_opt_in_attaches_embedded_pdf(self, tmp_path):
        """attach_pdf_resource=True: PDF EmbeddedResource is added alongside images."""
        response = _make_response(tmp_path, pages=1)
        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages",
            return_value=[_png_payload()],
        ):
            result = render_response_to_tool_result(
                response, attach_pdf_resource=True
            )

        embedded = [b for b in result.content if isinstance(b, EmbeddedResource)]
        assert len(embedded) == 1
        assert embedded[0].resource.mimeType == "application/pdf"
        decoded = base64.b64decode(embedded[0].resource.blob)
        assert decoded == _minimal_pdf_bytes()

        images = [b for b in result.content if isinstance(b, ImageContent)]
        assert len(images) == 1, (
            "opt-in PDF resource is additive, not a replacement for images"
        )

    def test_attach_pdf_resource_without_images(self, tmp_path):
        """attach_images=False + attach_pdf_resource=True: only the PDF resource."""
        response = _make_response(tmp_path, pages=2)
        result = render_response_to_tool_result(
            response, attach_images=False, attach_pdf_resource=True
        )

        embedded = [b for b in result.content if isinstance(b, EmbeddedResource)]
        images = [b for b in result.content if isinstance(b, ImageContent)]
        assert len(embedded) == 1
        assert images == []

    def test_image_dpi_propagates_to_rasterizer(self, tmp_path):
        """The image_dpi knob is forwarded verbatim to rasterize_pdf_pages."""
        response = _make_response(tmp_path, pages=1)
        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages",
            return_value=[_png_payload()],
        ) as raster:
            render_response_to_tool_result(response, image_dpi=288)

        raster.assert_called_once()
        _, kwargs = raster.call_args
        assert kwargs["dpi"] == 288
        assert kwargs["page_indices"] == [0]

    def test_max_image_pages_cap_skips_images_with_note(self, tmp_path):
        """When pages_rendered exceeds max_image_pages: no images, TextContent note."""
        response = _make_response(tmp_path, pages=12)
        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages"
        ) as raster:
            result = render_response_to_tool_result(response, max_image_pages=10)

        raster.assert_not_called()
        images = [b for b in result.content if isinstance(b, ImageContent)]
        notes = [b for b in result.content if isinstance(b, TextContent)]
        assert images == []
        assert len(notes) == 1
        assert "max_image_pages" in notes[0].text
        assert "12" in notes[0].text

    def test_max_image_pages_at_cap_still_attaches(self, tmp_path):
        """At-the-cap renders still attach all images (cap is a hard ceiling, not exclusive)."""
        response = _make_response(tmp_path, pages=10)
        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages",
            return_value=[_png_payload(i) for i in range(10)],
        ):
            result = render_response_to_tool_result(response, max_image_pages=10)

        images = [b for b in result.content if isinstance(b, ImageContent)]
        assert len(images) == 10

    def test_failure_only_omits_image_and_resource_blocks(self):
        """No pages rendered: no ImageContent and no EmbeddedResource.

        FastMCP may still emit a fallback TextContent that mirrors
        structured_content for non-structuredContent-aware clients; that's
        harmless and not what we're guarding against here.
        """
        response = RenderResponse(
            pdf_path=None,
            document_name="Doc",
            pages_rendered=0,
            pages_failed=[PageFailure(index=0, code="v5_unsupported", reason="v5")],
            page_indices=[0],
        )

        result = render_response_to_tool_result(response)

        assert isinstance(result, ToolResult)
        assert result.structured_content == response.model_dump()
        assert all(not isinstance(b, ImageContent) for b in result.content)
        assert all(not isinstance(b, EmbeddedResource) for b in result.content)

    def test_stale_pdf_path_does_not_crash(self, tmp_path):
        """Renderer reported a path that no longer exists: no artifact, no crash."""
        missing = tmp_path / "stale.pdf"
        assert not missing.exists()
        response = RenderResponse(
            pdf_path=str(missing),
            document_name="Doc",
            pages_rendered=1,
            pages_failed=[],
            page_indices=[0],
            sources_used={"rm_v6": 1},
        )

        result = render_response_to_tool_result(response, attach_pdf_resource=True)

        assert isinstance(result, ToolResult)
        assert result.structured_content == response.model_dump()
        assert all(not isinstance(b, ImageContent) for b in result.content)
        assert all(not isinstance(b, EmbeddedResource) for b in result.content)

    def test_rasterize_error_degrades_to_text_note(self, tmp_path):
        """If rasterization throws, the tool still returns metadata + a note."""
        response = _make_response(tmp_path, pages=2)
        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages",
            side_effect=RasterizeError("synthetic boom"),
        ):
            result = render_response_to_tool_result(response)

        images = [b for b in result.content if isinstance(b, ImageContent)]
        notes = [b for b in result.content if isinstance(b, TextContent)]
        assert images == []
        assert len(notes) == 1
        assert "synthetic boom" in notes[0].text
        assert "pdf_path" in notes[0].text
        assert result.structured_content == response.model_dump()

    def test_structured_content_keeps_sparse_dump(self, tmp_path):
        """sources_used must remain absent when unset, matching _BaseResponse rules."""
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(_minimal_pdf_bytes())
        response = RenderResponse(
            pdf_path=str(pdf_path),
            document_name="Doc",
            pages_rendered=1,
            pages_failed=[],
            page_indices=[0],
        )

        with patch(
            "remarkable_mcp_redux.tools._artifacts.rasterize_pdf_pages",
            return_value=[_png_payload()],
        ):
            result = render_response_to_tool_result(response)

        assert "sources_used" not in result.structured_content
        assert result.structured_content["pdf_path"] == str(pdf_path)


def _mock_rendering():
    """Patch rmc + cairosvg so render_pages produces a valid PDF on disk.

    Mirrors the helper in tests/test_render.py but kept local so this test
    file doesn't import from another test module.
    """
    minimal_pdf = _minimal_pdf_bytes()
    minimal_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
    )

    def fake_rmc(args, **kwargs):
        if "-o" in args:
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(minimal_svg)
        return MagicMock(returncode=0)

    def fake_svg2pdf(**kwargs):
        return minimal_pdf

    return patch.multiple(
        "remarkable_mcp_redux.core.render",
        _run_rmc=fake_rmc,
        _svg_to_pdf_bytes=fake_svg2pdf,
    )


@pytest.mark.integration
class TestRenderToolDispatch:
    """End-to-end: registered FastMCP tool returns the artifact via ToolResult.

    Goes through the full FastMCP dispatch path (input validation, function
    invocation via TypeAdapter, ToolResult passthrough) so any regression in
    how the tool layer wires the artifact helper into the wire response is
    caught here, not just at the helper unit level.
    """

    @pytest.mark.asyncio
    async def test_render_pages_default_returns_image_blocks(
        self, fake_cache, render_dir
    ):
        app = FastMCP("test-render-artifacts")
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        register_tools(app, client)

        tool = app._tool_manager._tools["remarkable_render_pages"]
        with _mock_rendering():
            result = await tool.run(
                {"doc_id": "aaaa-1111-2222-3333", "first_n": 2}
            )

        assert isinstance(result, ToolResult)
        assert result.structured_content is not None
        assert result.structured_content["pages_rendered"] == 2
        assert result.structured_content["page_indices"] == [0, 1]

        images = [b for b in result.content if isinstance(b, ImageContent)]
        assert len(images) == 2, (
            "default render_pages tool must surface one ImageContent per page"
        )
        for img in images:
            assert img.mimeType == "image/png"
            assert base64.b64decode(img.data).startswith(b"\x89PNG\r\n\x1a\n")

        embedded = [b for b in result.content if isinstance(b, EmbeddedResource)]
        assert embedded == [], (
            "PDF EmbeddedResource must be off by default for Claude Desktop"
        )

    @pytest.mark.asyncio
    async def test_render_pages_with_pdf_resource_opt_in(
        self, fake_cache, render_dir
    ):
        app = FastMCP("test-render-artifacts")
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        register_tools(app, client)

        tool = app._tool_manager._tools["remarkable_render_pages"]
        with _mock_rendering():
            result = await tool.run(
                {
                    "doc_id": "aaaa-1111-2222-3333",
                    "first_n": 1,
                    "attach_pdf_resource": True,
                }
            )

        embedded = [b for b in result.content if isinstance(b, EmbeddedResource)]
        assert len(embedded) == 1, (
            "attach_pdf_resource=True should surface exactly one PDF artifact"
        )
        assert embedded[0].resource.mimeType == "application/pdf"
        assert base64.b64decode(embedded[0].resource.blob).startswith(b"%PDF-")

        images = [b for b in result.content if isinstance(b, ImageContent)]
        assert len(images) == 1, "images stay on by default with the opt-in"

    @pytest.mark.asyncio
    async def test_render_pages_attach_images_false(self, fake_cache, render_dir):
        app = FastMCP("test-render-artifacts")
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        register_tools(app, client)

        tool = app._tool_manager._tools["remarkable_render_pages"]
        with _mock_rendering():
            result = await tool.run(
                {
                    "doc_id": "aaaa-1111-2222-3333",
                    "first_n": 2,
                    "attach_images": False,
                }
            )

        images = [b for b in result.content if isinstance(b, ImageContent)]
        embedded = [b for b in result.content if isinstance(b, EmbeddedResource)]
        assert images == []
        assert embedded == []
        assert result.structured_content["pages_rendered"] == 2

    @pytest.mark.asyncio
    async def test_render_document_default_returns_image_blocks(
        self, fake_cache, render_dir
    ):
        app = FastMCP("test-render-artifacts")
        client = RemarkableClient(base_path=fake_cache, render_dir=render_dir)
        register_tools(app, client)

        tool = app._tool_manager._tools["remarkable_render_document"]
        with _mock_rendering():
            result = await tool.run({"doc_id": "aaaa-1111-2222-3333"})

        images = [b for b in result.content if isinstance(b, ImageContent)]
        assert len(images) >= 1
        assert all(img.mimeType == "image/png" for img in images)
        assert all(b.type != "resource" for b in result.content)
