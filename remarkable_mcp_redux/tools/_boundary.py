"""tool_error_boundary decorator that catches RemarkableError raised by facades and
serializes a ToolError envelope so MCP clients keep the legacy {"error": True, ...} shape.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from ..exceptions import RemarkableError
from ..responses import ToolError

F = TypeVar("F", bound=Callable[..., Any])


def tool_error_boundary(fn: F) -> F:
    """Translate facade-level ``RemarkableError`` exceptions into a wire envelope.

    Apply *inside* ``@mcp.tool(...)`` so FastMCP introspects the wrapped
    function's real signature via ``functools.wraps``::

        @mcp.tool(title=..., annotations=..., output_schema=...)
        @tool_error_boundary
        def remarkable_get_document_info(doc_id: str): ...

    Generic ``Exception`` subclasses are not caught — those represent
    programming bugs or environmental faults that should surface as MCP
    server-level failures rather than tool-shaped error envelopes.

    The returned dict is the sparse ``model_dump`` of ``ToolError`` and
    therefore omits the optional ``code`` field when the raised exception
    didn't set one (the base ``RemarkableError`` and any custom subclass
    override do, so this only happens for exotic future cases).
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except RemarkableError as exc:
            return ToolError(
                error=True,
                detail=exc.detail,
                code=exc.code,
            ).model_dump()

    return wrapper  # type: ignore[return-value]


__all__ = ["tool_error_boundary"]
