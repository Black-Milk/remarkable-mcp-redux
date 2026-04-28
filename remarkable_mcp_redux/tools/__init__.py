"""MCP tool subpackage entry point.

Dispatches read, render, and (opt-in) write tool registrations to per-domain modules.
"""

from fastmcp import FastMCP

from ..client import RemarkableClient
from ..config import is_write_tools_enabled
from .read import register_read_tools
from .render import register_render_tools
from .write import register_write_tools


def register_tools(mcp: FastMCP, client: RemarkableClient) -> None:
    """Register MCP tools on the given FastMCP app.

    Read-only and render tools are always registered. Write-back tools are
    only registered when REMARKABLE_ENABLE_WRITE_TOOLS is set to a truthy
    value (controlled via ``is_write_tools_enabled``).
    """
    register_read_tools(
        mcp,
        documents=client.documents,
        folders=client.folders,
        status=client.status,
    )
    register_render_tools(mcp, render=client.render)
    if is_write_tools_enabled():
        register_write_tools(mcp, writes=client.writes)


__all__ = ["register_tools"]
