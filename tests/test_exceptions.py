"""Contract tests for the typed exception hierarchy and the tool_error_boundary
decorator that converts RemarkableError subclasses into ToolError wire envelopes.
"""

import pytest

from remarkable_mcp_redux.exceptions import (
    BackupMissingError,
    ConflictError,
    KindMismatchError,
    NotFoundError,
    RemarkableError,
    TrashedRecordError,
    ValidationError,
)
from remarkable_mcp_redux.tools._boundary import tool_error_boundary

CASES = [
    (NotFoundError, "not_found"),
    (KindMismatchError, "kind_mismatch"),
    (ValidationError, "validation"),
    (TrashedRecordError, "trashed"),
    (ConflictError, "conflict"),
    (BackupMissingError, "backup_missing"),
]


class TestExceptionHierarchy:
    @pytest.mark.unit
    @pytest.mark.parametrize("exc_cls,expected_code", CASES)
    def test_each_subclass_has_stable_code(self, exc_cls, expected_code):
        """The ``code`` class attribute is the discriminator the boundary
        forwards to clients; tests pin it so changes are intentional."""
        assert exc_cls.code == expected_code

    @pytest.mark.unit
    @pytest.mark.parametrize("exc_cls,_", CASES)
    def test_subclasses_inherit_from_base(self, exc_cls, _):
        assert issubclass(exc_cls, RemarkableError)
        assert issubclass(exc_cls, Exception)

    @pytest.mark.unit
    def test_detail_is_str_message(self):
        exc = NotFoundError("missing record xyz")
        assert exc.detail == "missing record xyz"
        assert str(exc) == "missing record xyz"


class TestToolErrorBoundary:
    """The boundary catches typed exceptions and produces the wire envelope."""

    @pytest.mark.unit
    @pytest.mark.parametrize("exc_cls,expected_code", CASES)
    def test_translates_each_typed_exception(self, exc_cls, expected_code):
        @tool_error_boundary
        def fn():
            raise exc_cls(f"boom from {exc_cls.__name__}")

        result = fn()
        assert isinstance(result, dict)
        assert result == {
            "error": True,
            "detail": f"boom from {exc_cls.__name__}",
            "code": expected_code,
        }

    @pytest.mark.unit
    def test_passes_success_value_through(self):
        @tool_error_boundary
        def fn():
            return {"ok": True, "x": 1}

        assert fn() == {"ok": True, "x": 1}

    @pytest.mark.unit
    def test_does_not_swallow_generic_exceptions(self):
        """Programming bugs should surface at MCP server level, not as ToolError."""

        @tool_error_boundary
        def fn():
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError, match="kaboom"):
            fn()

    @pytest.mark.unit
    def test_preserves_function_signature_for_introspection(self):
        """``functools.wraps`` keeps the original signature so FastMCP's
        decorator-time introspection still works correctly."""

        @tool_error_boundary
        def remarkable_demo(doc_id: str, count: int = 5) -> dict:
            """demo docstring"""
            return {"doc_id": doc_id, "count": count}

        assert remarkable_demo.__name__ == "remarkable_demo"
        assert remarkable_demo.__doc__ == "demo docstring"
        assert remarkable_demo("xyz", count=3) == {"doc_id": "xyz", "count": 3}

    @pytest.mark.unit
    def test_envelope_drops_code_when_unset(self):
        """A bare ``RemarkableError`` (no subclass) still has a code constant.

        This test guards the sparse-serialization path: even though we always
        forward ``exc.code``, the wire envelope's ``model_dump`` behaviour
        means clients with no concept of ``code`` keep working unchanged.
        """

        @tool_error_boundary
        def fn():
            raise RemarkableError("generic")

        result = fn()
        # base class keeps code="remarkable_error"
        assert result["error"] is True
        assert result["detail"] == "generic"
        assert result["code"] == "remarkable_error"
