"""Unit tests for the render-artifact helper that wraps RenderResponse for MCP tools.

Covers successful renders (PDF attached as an embedded resource), failure-only
renders (no artifact, structured content only), and stale-path renders (file
gone since the facade returned, artifact silently omitted).
"""

import base64

import pytest
from fastmcp.tools.tool import ToolResult
from mcp.types import EmbeddedResource

from remarkable_mcp_redux.responses import PageFailure, RenderResponse
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


@pytest.mark.unit
class TestRenderResponseToToolResult:
    def test_success_attaches_pdf_artifact_and_structured_content(self, tmp_path):
        """Successful render: ToolResult carries one PDF EmbeddedResource and
        structured content equal to the response's sparse model_dump."""
        pdf_bytes = _minimal_pdf_bytes()
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(pdf_bytes)

        response = RenderResponse(
            pdf_path=str(pdf_path),
            document_name="Doc",
            pages_rendered=2,
            pages_failed=[],
            page_indices=[0, 1],
            sources_used={"rm_v6": 2},
        )

        result = render_response_to_tool_result(response)

        assert isinstance(result, ToolResult)
        assert result.structured_content == response.model_dump()
        assert len(result.content) == 1

        block = result.content[0]
        assert isinstance(block, EmbeddedResource)
        assert block.resource.mimeType == "application/pdf"
        decoded = base64.b64decode(block.resource.blob)
        assert decoded == pdf_bytes

    def test_failure_only_omits_artifact(self):
        """No pages rendered: ToolResult has only structured content, no PDF."""
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
        for block in result.content:
            assert not isinstance(block, EmbeddedResource), (
                "Failure-only render must not surface a PDF artifact"
            )

    def test_stale_pdf_path_does_not_crash(self, tmp_path):
        """If the renderer reported a path that no longer exists on disk,
        the helper preserves the structured metadata and skips the artifact
        instead of raising — protecting against races with cleanup_renders."""
        missing_path = tmp_path / "stale.pdf"
        assert not missing_path.exists()

        response = RenderResponse(
            pdf_path=str(missing_path),
            document_name="Doc",
            pages_rendered=1,
            pages_failed=[],
            page_indices=[0],
            sources_used={"rm_v6": 1},
        )

        result = render_response_to_tool_result(response)

        assert isinstance(result, ToolResult)
        assert result.structured_content == response.model_dump()
        for block in result.content:
            assert not isinstance(block, EmbeddedResource), (
                "Stale pdf_path must not produce an EmbeddedResource"
            )

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

        result = render_response_to_tool_result(response)

        assert "sources_used" not in result.structured_content
        assert result.structured_content["pdf_path"] == str(pdf_path)
