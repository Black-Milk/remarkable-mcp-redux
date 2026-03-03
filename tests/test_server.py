# ABOUTME: Integration tests for the MCP server tool registration and response shapes.
# ABOUTME: Verifies all 6 tools are registered and return expected dict structures.

import pytest

from server import mcp, client


EXPECTED_TOOLS = [
    "remarkable_list_documents",
    "remarkable_get_document_info",
    "remarkable_render_pages",
    "remarkable_render_document",
    "remarkable_check_status",
    "remarkable_cleanup_renders",
]


class TestToolRegistration:
    @pytest.mark.integration
    def test_server_has_all_tools(self):
        """All 6 tools should be registered on the MCP server."""
        tools = mcp._tool_manager._tools
        tool_names = set(tools.keys())
        for name in EXPECTED_TOOLS:
            assert name in tool_names, f"Missing tool: {name}"

    @pytest.mark.integration
    def test_tool_count(self):
        """Server should have exactly 6 tools."""
        tools = mcp._tool_manager._tools
        assert len(tools) == 6


class TestToolResponseShapes:
    @pytest.mark.integration
    def test_check_status_shape(self):
        """remarkable_check_status should return status dict."""
        result = client.check_status()
        assert "cache_path" in result
        assert "cache_exists" in result
        assert "document_count" in result
        assert "rmc_available" in result
        assert "cairo_available" in result

    @pytest.mark.integration
    def test_list_documents_shape(self):
        """remarkable_list_documents should return documents list and count."""
        result = client.list_documents()
        assert "documents" in result
        assert "count" in result
        assert isinstance(result["documents"], list)

    @pytest.mark.integration
    def test_get_document_info_missing(self):
        """remarkable_get_document_info with bad ID returns error dict."""
        result = client.get_document_info("nonexistent-id")
        assert result["error"] is True
        assert "detail" in result

    @pytest.mark.integration
    def test_cleanup_renders_shape(self):
        """remarkable_cleanup_renders should return files_removed and bytes_freed."""
        result = client.cleanup_renders()
        assert "files_removed" in result
        assert "bytes_freed" in result
