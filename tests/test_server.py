# ABOUTME: Integration tests for the MCP server tool registration and response shapes.
# ABOUTME: Verifies tools are registered (with the write-tool opt-in) and return expected shapes.

import pytest

from remarkable_mcp_redux.config import WRITE_TOOLS_ENV_VAR
from remarkable_mcp_redux.exceptions import BackupMissingError, NotFoundError
from remarkable_mcp_redux.server import build_server, client, mcp

EXPECTED_READ_TOOLS = [
    "remarkable_list_documents",
    "remarkable_list_folders",
    "remarkable_get_document_info",
    "remarkable_render_pages",
    "remarkable_render_document",
    "remarkable_check_status",
    "remarkable_cleanup_renders",
]

EXPECTED_WRITE_TOOLS = [
    "remarkable_rename_document",
    "remarkable_rename_folder",
    "remarkable_move_document",
    "remarkable_move_folder",
    "remarkable_create_folder",
    "remarkable_pin_document",
    "remarkable_restore_metadata",
    "remarkable_cleanup_metadata_backups",
]

EXPECTED_TOOLS = EXPECTED_READ_TOOLS


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
        result = client.status.check()
        assert "cache_path" in result
        assert "cache_exists" in result
        assert "document_count" in result
        assert "rmc_available" in result
        assert "cairo_available" in result

    @pytest.mark.integration
    def test_list_documents_shape(self):
        """remarkable_list_documents should return documents list, count, and pagination metadata."""
        result = client.documents.list()
        assert "documents" in result
        assert "count" in result
        assert "total_count" in result
        assert "limit" in result
        assert "offset" in result
        assert "has_more" in result
        assert isinstance(result["documents"], list)
        assert isinstance(result["has_more"], bool)

    @pytest.mark.integration
    def test_get_document_info_missing_raises(self):
        """remarkable_get_document_info with bad ID raises NotFoundError at the facade.

        The MCP tool boundary turns this into a ToolError envelope on the wire
        (covered by test_boundary_translates_remarkable_error in test_exceptions).
        """
        with pytest.raises(NotFoundError, match="not found"):
            client.documents.get_info("nonexistent-id")

    @pytest.mark.integration
    def test_cleanup_renders_shape(self):
        """remarkable_cleanup_renders should return files_removed and bytes_freed."""
        result = client.render.cleanup_renders()
        assert "files_removed" in result
        assert "bytes_freed" in result

    @pytest.mark.integration
    def test_list_folders_shape(self):
        """remarkable_list_folders should return folders list, count, and pagination metadata."""
        result = client.folders.list()
        assert "folders" in result
        assert "count" in result
        assert "total_count" in result
        assert "limit" in result
        assert "offset" in result
        assert "has_more" in result
        assert isinstance(result["folders"], list)
        assert isinstance(result["has_more"], bool)


class TestWriteToolGating:
    @pytest.mark.integration
    def test_write_tools_disabled_by_default(self, monkeypatch):
        """Without REMARKABLE_ENABLE_WRITE_TOOLS, no write tools register."""
        monkeypatch.delenv(WRITE_TOOLS_ENV_VAR, raising=False)
        app, _ = build_server()
        tool_names = set(app._tool_manager._tools.keys())
        for name in EXPECTED_WRITE_TOOLS:
            assert name not in tool_names
        assert len(tool_names) == len(EXPECTED_READ_TOOLS)

    @pytest.mark.integration
    def test_write_tools_register_when_enabled(self, monkeypatch):
        """When the env flag is truthy, all eight write tools must register."""
        monkeypatch.setenv(WRITE_TOOLS_ENV_VAR, "true")
        app, _ = build_server()
        tool_names = set(app._tool_manager._tools.keys())
        for name in EXPECTED_WRITE_TOOLS:
            assert name in tool_names, f"Missing write tool: {name}"
        assert len(tool_names) == len(EXPECTED_READ_TOOLS) + len(EXPECTED_WRITE_TOOLS)

    @pytest.mark.integration
    def test_falsy_env_keeps_write_tools_disabled(self, monkeypatch):
        """A non-truthy value should still leave write tools off."""
        monkeypatch.setenv(WRITE_TOOLS_ENV_VAR, "no")
        app, _ = build_server()
        tool_names = set(app._tool_manager._tools.keys())
        for name in EXPECTED_WRITE_TOOLS:
            assert name not in tool_names


class TestWriteToolResponseShapes:
    """Per-method shape checks for the new write surface using a synthetic cache."""

    @pytest.mark.integration
    def test_pin_document_shape(self, fake_cache):
        from remarkable_mcp_redux.client import RemarkableClient

        c = RemarkableClient(base_path=fake_cache)
        result = c.writes.pin_document("aaaa-1111-2222-3333", True, dry_run=True)
        assert "doc_id" in result
        assert "old_pinned" in result
        assert "new_pinned" in result
        assert result["dry_run"] is True

    @pytest.mark.integration
    def test_create_folder_shape(self, fake_cache):
        from remarkable_mcp_redux.client import RemarkableClient

        c = RemarkableClient(base_path=fake_cache)
        result = c.writes.create_folder("Shape Check", dry_run=True)
        assert result["dry_run"] is True
        assert result["name"] == "Shape Check"
        assert result["parent"] == ""

    @pytest.mark.integration
    def test_cleanup_metadata_backups_shape(self, fake_cache):
        from remarkable_mcp_redux.client import RemarkableClient

        c = RemarkableClient(base_path=fake_cache)
        result = c.writes.cleanup_metadata_backups(older_than_days=0, dry_run=True)
        assert "files_removed" in result
        assert "bytes_freed" in result
        assert "scanned_docs" in result
        assert "backups_remaining" in result

    @pytest.mark.integration
    def test_restore_metadata_no_backup_raises(self, fake_cache):
        from remarkable_mcp_redux.client import RemarkableClient

        c = RemarkableClient(base_path=fake_cache)
        with pytest.raises(BackupMissingError, match="(?i)backup"):
            c.writes.restore_metadata("aaaa-1111-2222-3333")
