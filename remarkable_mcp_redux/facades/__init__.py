# ABOUTME: Facades subpackage — per-domain orchestration on top of cache + render mechanisms.
# ABOUTME: Re-exports the five facade classes for ergonomic imports from the composition root.

from .documents import DocumentsFacade
from .folders import FoldersFacade
from .render import RenderFacade
from .status import StatusFacade
from .writes import WritesFacade

__all__ = [
    "DocumentsFacade",
    "FoldersFacade",
    "RenderFacade",
    "StatusFacade",
    "WritesFacade",
]
