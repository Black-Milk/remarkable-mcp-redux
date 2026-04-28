"""Unit tests for the env-var helpers in :mod:`remarkable_mcp_redux.config`.

Covers ``render_dir`` resolution across unset / empty / literal-path /
``~``-expanded cases. The other helpers (``is_write_tools_enabled``,
``backup_retention_count``) already have integration coverage via
``tests/test_server.py`` and the write-tool tests.
"""

from pathlib import Path

import pytest

from remarkable_mcp_redux.config import (
    DEFAULT_RENDER_DIR,
    RENDER_DIR_ENV_VAR,
    render_dir,
)


@pytest.mark.unit
class TestRenderDirEnvResolution:
    def test_unset_falls_back_to_default(self, monkeypatch):
        """No env var → default scratch path."""
        monkeypatch.delenv(RENDER_DIR_ENV_VAR, raising=False)
        assert render_dir() == DEFAULT_RENDER_DIR

    def test_empty_string_falls_back_to_default(self, monkeypatch):
        """Explicitly empty value is treated as unset (defensive against shells
        that export ``FOO=``)."""
        monkeypatch.setenv(RENDER_DIR_ENV_VAR, "")
        assert render_dir() == DEFAULT_RENDER_DIR

    def test_whitespace_only_falls_back_to_default(self, monkeypatch):
        """Whitespace-only values (e.g. accidentally quoted spaces) fall back."""
        monkeypatch.setenv(RENDER_DIR_ENV_VAR, "   ")
        assert render_dir() == DEFAULT_RENDER_DIR

    def test_literal_absolute_path_is_returned_resolved(
        self, monkeypatch, tmp_path
    ):
        """An absolute path is honored and returned as a resolved Path."""
        target = tmp_path / "renders"
        monkeypatch.setenv(RENDER_DIR_ENV_VAR, str(target))
        result = render_dir()
        assert result == target.resolve()
        assert result.is_absolute()

    def test_relative_path_is_resolved_to_absolute(self, monkeypatch, tmp_path):
        """A relative path is resolved against CWD; the helper guarantees absolute."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(RENDER_DIR_ENV_VAR, "renders")
        result = render_dir()
        assert result.is_absolute()
        assert result == (tmp_path / "renders").resolve()

    def test_tilde_is_expanded(self, monkeypatch):
        """``~`` is expanded to the user's home before resolution."""
        monkeypatch.setenv(RENDER_DIR_ENV_VAR, "~/remarkable-renders-test")
        result = render_dir()
        assert "~" not in str(result)
        assert result == (Path.home() / "remarkable-renders-test").resolve()

    def test_surrounding_whitespace_is_stripped(self, monkeypatch, tmp_path):
        """Leading/trailing whitespace around the path is trimmed."""
        target = tmp_path / "renders"
        monkeypatch.setenv(RENDER_DIR_ENV_VAR, f"  {target}  ")
        assert render_dir() == target.resolve()
