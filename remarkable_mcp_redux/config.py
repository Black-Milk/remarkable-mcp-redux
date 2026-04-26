# ABOUTME: Default paths and environment configuration for the remarkable-mcp server.
# ABOUTME: Centralizes cache location, render dir, and macOS Cairo library path setup.

import os
from pathlib import Path

DEFAULT_BASE_PATH = Path(
    os.path.expanduser(
        "~/Library/Containers/com.remarkable.desktop/"
        "Data/Library/Application Support/remarkable/desktop"
    )
)

DEFAULT_RENDER_DIR = Path("/tmp/remarkable-renders")


WRITE_TOOLS_ENV_VAR = "REMARKABLE_ENABLE_WRITE_TOOLS"


def ensure_cairo_library_path() -> None:
    """Make sure cairosvg can locate Homebrew's cairo on macOS.

    Sets DYLD_LIBRARY_PATH to /opt/homebrew/lib if not already configured.
    Idempotent and safe to call from multiple modules.
    """
    if "DYLD_LIBRARY_PATH" not in os.environ:
        os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib"


def is_write_tools_enabled() -> bool:
    """Whether the opt-in write-back MCP tools are enabled.

    Controlled by the REMARKABLE_ENABLE_WRITE_TOOLS env var. Truthy values are
    "1", "true", "yes", "on" (case-insensitive). Default: disabled.
    """
    val = os.environ.get(WRITE_TOOLS_ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes", "on")
