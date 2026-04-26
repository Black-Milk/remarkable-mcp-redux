# ABOUTME: Integration tests for the MCP server tool registration and response shapes.
# ABOUTME: Verifies tools are registered (with the write-tool opt-in) and return expected shapes.

import pytest

from remarkable_mcp_redux.config import WRITE_TOOLS_ENV_VAR
from remarkable_mcp_redux.server import build_server, client, mcp

EXPECTED_TOOLS = [
    "remarkable_list_documents",
    "remarkable_list_folders",
    "remarkable_get_document_info",
    "remarkable_render_pages",
    "remarkable_render_document",
    "remarkable_check_status",
    "remarkable_cleanup_renders",
]


class TestToolRegistration:
    @pytest.mark.integration
    def test_server_has_all_tools(self):
        """All read-only tools should be registered on the MCP server."""
        tools = mcp._tool_manager._tools
        tool_names = set(tools.keys())
        for name in EXPECTED_TOOLS:
            assert name in tool_names, f"Missing tool: {name}"

    @pytest.mark.integration
    def test_tool_count(self):
        """Server should have exactly len(EXPECTED_TOOLS) read-only tools."""
        tools = mcp._tool_manager._tools
        assert len(tools) == len(EXPECTED_TOOLS)


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

    @pytest.mark.integration
    def test_list_folders_shape(self):
        """remarkable_list_folders should return folders list and count."""
        result = client.list_folders()
        assert "folders" in result
        assert "count" in result
        assert isinstance(result["folders"], list)


class TestWriteToolGating:
    @pytest.mark.integration
    def test_write_tools_disabled_by_default(self, monkeypatch):
        """Without REMARKABLE_ENABLE_WRITE_TOOLS, write tools must not register."""
        monkeypatch.delenv(WRITE_TOOLS_ENV_VAR, raising=False)
        app, _ = build_server()
        tool_names = set(app._tool_manager._tools.keys())
        assert "remarkable_rename_document" not in tool_names
        assert "remarkable_move_document" not in tool_names

    @pytest.mark.integration
    def test_write_tools_register_when_enabled(self, monkeypatch):
        """When the env flag is truthy, write tools must register."""
        monkeypatch.setenv(WRITE_TOOLS_ENV_VAR, "true")
        app, _ = build_server()
        tool_names = set(app._tool_manager._tools.keys())
        assert "remarkable_rename_document" in tool_names
        assert "remarkable_move_document" in tool_names

    @pytest.mark.integration
    def test_falsy_env_keeps_write_tools_disabled(self, monkeypatch):
        """A non-truthy value should still leave write tools off."""
        monkeypatch.setenv(WRITE_TOOLS_ENV_VAR, "no")
        app, _ = build_server()
        tool_names = set(app._tool_manager._tools.keys())
        assert "remarkable_rename_document" not in tool_names
