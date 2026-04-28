"""FastMCP server entry point for the remarkable-mcp redux package.

Builds the FastMCP app, registers tools, and runs over stdio.
"""

import logging
import sys

from fastmcp import FastMCP

from .client import RemarkableClient
from .config import ensure_cairo_library_path
from .tools import register_tools

ensure_cairo_library_path()

logging.basicConfig(stream=sys.stderr, level=logging.INFO)


def build_server() -> tuple[FastMCP, RemarkableClient]:
    """Construct the FastMCP app and shared RemarkableClient."""
    app = FastMCP("remarkable")
    rm_client = RemarkableClient()
    register_tools(app, rm_client)
    return app, rm_client


mcp, client = build_server()


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
