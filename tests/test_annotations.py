# ABOUTME: Integration tests asserting the per-tool ToolAnnotations matrix on the FastMCP server.
# ABOUTME: Drives every assertion off the live registry so changes happen in annotations.py only.

import pytest

from remarkable_mcp_redux.annotations import ANNOTATIONS, TITLES
from remarkable_mcp_redux.config import WRITE_TOOLS_ENV_VAR
from remarkable_mcp_redux.server import build_server

EXPECTED_TOOL_COUNT = 15


@pytest.fixture(scope="module")
def all_tools():
    """FastMCP app with read + write tools registered, mapped by tool name."""
    import os

    prior = os.environ.get(WRITE_TOOLS_ENV_VAR)
    os.environ[WRITE_TOOLS_ENV_VAR] = "true"
    try:
        app, _ = build_server()
        return app._tool_manager._tools
    finally:
        if prior is None:
            os.environ.pop(WRITE_TOOLS_ENV_VAR, None)
        else:
            os.environ[WRITE_TOOLS_ENV_VAR] = prior


class TestRegistryConsistency:
    """Sanity checks on the registry itself; run before the FastMCP plumbing."""

    @pytest.mark.unit
    def test_titles_and_annotations_cover_same_tools(self):
        """Every tool name in TITLES must have a matching ANNOTATIONS entry."""
        assert set(TITLES.keys()) == set(ANNOTATIONS.keys())

    @pytest.mark.unit
    def test_registry_has_expected_tool_count(self):
        """Pin the tool count so accidental adds/removes are noticed in review."""
        assert len(ANNOTATIONS) == EXPECTED_TOOL_COUNT

    @pytest.mark.unit
    @pytest.mark.parametrize("tool_name", sorted(ANNOTATIONS.keys()))
    def test_destructive_only_when_not_read_only(self, tool_name):
        """Spec rule: ``destructiveHint`` is only meaningful when ``readOnlyHint`` is False."""
        ann = ANNOTATIONS[tool_name]
        if ann.readOnlyHint:
            assert not ann.destructiveHint, (
                f"{tool_name}: readOnly tools must not set destructiveHint=True"
            )


class TestServerExposesAnnotations:
    """Each registered FastMCP tool carries the registry's metadata verbatim."""

    @pytest.mark.integration
    @pytest.mark.parametrize("tool_name", sorted(ANNOTATIONS.keys()))
    def test_tool_carries_annotations(self, all_tools, tool_name):
        assert tool_name in all_tools, f"Missing tool: {tool_name}"
        actual = all_tools[tool_name].annotations
        expected = ANNOTATIONS[tool_name]
        assert actual is not None, f"{tool_name} has no annotations attached"
        assert actual.readOnlyHint == expected.readOnlyHint
        assert actual.destructiveHint == expected.destructiveHint
        assert actual.idempotentHint == expected.idempotentHint
        assert actual.openWorldHint == expected.openWorldHint

    @pytest.mark.integration
    @pytest.mark.parametrize("tool_name", sorted(TITLES.keys()))
    def test_tool_carries_title(self, all_tools, tool_name):
        assert tool_name in all_tools, f"Missing tool: {tool_name}"
        assert all_tools[tool_name].title == TITLES[tool_name]
