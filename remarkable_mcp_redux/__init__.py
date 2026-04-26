# ABOUTME: Package root for the remarkable-mcp redux server.
# ABOUTME: Re-exports the public RemarkableClient facade for convenience.

from .client import RemarkableClient
from .config import DEFAULT_BASE_PATH, DEFAULT_RENDER_DIR

__all__ = [
    "DEFAULT_BASE_PATH",
    "DEFAULT_RENDER_DIR",
    "RemarkableClient",
]
