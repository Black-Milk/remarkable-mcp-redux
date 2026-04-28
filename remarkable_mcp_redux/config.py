"""Default paths and environment configuration for the remarkable-mcp server.

Centralizes cache location, render dir, and macOS Cairo library path setup.
"""

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
BACKUP_RETENTION_ENV_VAR = "REMARKABLE_BACKUP_RETENTION_COUNT"
DEFAULT_BACKUP_RETENTION = 5

RENDER_DIR_ENV_VAR = "REMARKABLE_RENDER_DIR"


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


def render_dir() -> Path:
    """Resolve the render output directory.

    Reads ``REMARKABLE_RENDER_DIR``; ``~`` is expanded and the path is made
    absolute. Falls back to ``DEFAULT_RENDER_DIR`` when unset or empty so
    existing deployments keep writing to ``/tmp/remarkable-renders``.

    Pointing this at a directory that an MCP client mounts into its
    workspace (e.g. ``~/Documents/Claude/Projects/<name>/renders``) lets
    the client read the merged PDFs directly via its native filesystem
    tools, sidestepping the cross-client wire bug where ``ImageContent``
    blocks are dropped from ``CallToolResult`` whenever
    ``structuredContent`` is also set.
    """
    raw = os.environ.get(RENDER_DIR_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_RENDER_DIR
    return Path(os.path.expanduser(raw)).resolve()


def backup_retention_count() -> int:
    """How many .metadata.bak.* siblings to retain per document. Default 5.

    Negative or non-integer env values fall back to the default. A value of 0
    means "delete every backup older than the one just created" - the live
    write still creates a backup before the atomic replace, so this never
    blocks the rollback-on-write path; it only prunes prior generations.
    """
    raw = os.environ.get(BACKUP_RETENTION_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_BACKUP_RETENTION
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_BACKUP_RETENTION
    return n if n >= 0 else DEFAULT_BACKUP_RETENTION
