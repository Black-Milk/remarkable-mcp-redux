"""Unit tests for the .rm header version probe in core.rm_format.

Covers v5/v6/short-file/missing-file/garbage cases.
"""

import pytest

from remarkable_mcp_redux.core.rm_format import parse_rm_version


def _v5_header() -> bytes:
    return b"reMarkable .lines file, version=5".ljust(43, b" ") + b"\x00" * 21


def _v6_header() -> bytes:
    return b"reMarkable .lines file, version=6".ljust(43, b" ") + b"\x00" * 21


@pytest.mark.unit
def test_v5_header_returns_5(tmp_path):
    rm_path = tmp_path / "v5.rm"
    rm_path.write_bytes(_v5_header())
    assert parse_rm_version(rm_path) == 5


@pytest.mark.unit
def test_v6_header_returns_6(tmp_path):
    rm_path = tmp_path / "v6.rm"
    rm_path.write_bytes(_v6_header())
    assert parse_rm_version(rm_path) == 6


@pytest.mark.unit
def test_missing_file_returns_none(tmp_path):
    """Probe must not raise when the path does not exist."""
    assert parse_rm_version(tmp_path / "does-not-exist.rm") is None


@pytest.mark.unit
def test_short_file_returns_none(tmp_path):
    """A file shorter than the header length must not crash and must return None."""
    rm_path = tmp_path / "short.rm"
    rm_path.write_bytes(b"reMarkable .lines")
    assert parse_rm_version(rm_path) is None


@pytest.mark.unit
def test_garbage_bytes_returns_none(tmp_path):
    """Random bytes that don't include a known version banner return None.

    Importantly, this means existing test fixtures that write 64 zero bytes
    won't be misidentified as v5 or v6.
    """
    rm_path = tmp_path / "garbage.rm"
    rm_path.write_bytes(b"\x00" * 64)
    assert parse_rm_version(rm_path) is None


@pytest.mark.unit
def test_unknown_version_returns_none(tmp_path):
    """An otherwise-valid banner with an unsupported version returns None."""
    rm_path = tmp_path / "v9.rm"
    payload = b"reMarkable .lines file, version=9".ljust(43, b" ") + b"\x00" * 21
    rm_path.write_bytes(payload)
    assert parse_rm_version(rm_path) is None


@pytest.mark.unit
def test_directory_path_returns_none(tmp_path):
    """A directory at the path must not crash and must return None."""
    assert parse_rm_version(tmp_path) is None
