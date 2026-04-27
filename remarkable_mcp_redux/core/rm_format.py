# ABOUTME: Best-effort version probe for reMarkable .rm (.lines) files.
# ABOUTME: Returns the format version (5 or 6) from the 43-byte header, or None.

from pathlib import Path

# reMarkable .rm files start with a fixed-length banner. The exact bytes are:
#   b"reMarkable .lines file, version=N" + b" " * (43 - len(banner))
# Any non-banner bytes mean we don't know the version (treat as unknown rather
# than guess - the dispatcher will fall back to the v6/rmc path for safety).
_HEADER_LEN = 43
_KNOWN_VERSIONS: tuple[int, ...] = (5, 6)


def parse_rm_version(rm_path: Path) -> int | None:
    """Return the .rm format version (5 or 6) by reading the file header.

    Returns ``None`` for missing files, files shorter than the header,
    unreadable bytes, or banners with an unrecognised version digit. The
    function never raises - callers should treat ``None`` as "unknown,
    proceed with the default (rmc/v6) path".
    """
    try:
        with open(rm_path, "rb") as f:
            header = f.read(_HEADER_LEN)
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return None

    if len(header) < _HEADER_LEN:
        return None

    for version in _KNOWN_VERSIONS:
        marker = f"version={version}".encode()
        if marker in header:
            return version
    return None
