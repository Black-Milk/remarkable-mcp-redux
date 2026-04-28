"""Typed PageSource union describing where a single page's bytes come from.

Sits between facades/render.py (policy) and core/render.py (mechanism); add new variants here.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RmV6Source:
    """A v6 ``.rm`` file. Rendered via the rmc -> SVG -> cairosvg -> PDF pipeline."""

    rm_path: Path


@dataclass(frozen=True)
class RmV5Source:
    """A legacy v5 ``.rm`` file (pre-firmware-v3).

    Today the renderer raises ``LegacyV5Error`` for this variant. When/if a v5
    backend (e.g. ``lines-are-rusty``) ships, this is the single dispatch arm
    that needs to learn to call it - the surface around it is already in place.
    """

    rm_path: Path


@dataclass(frozen=True)
class PdfPassthroughSource:
    """An unannotated PDF page extracted directly from the source PDF via pypdf."""

    source_pdf: Path
    pdf_page_index: int


@dataclass(frozen=True)
class MissingSource:
    """No bytes available for this page (no .rm file, no source PDF page).

    Examples: an unannotated EPUB page, or a notebook with a stray page id but
    no on-disk ``.rm`` file. Surfaced to callers as ``code: "no_source"``.
    """


PageSource = RmV6Source | RmV5Source | PdfPassthroughSource | MissingSource


# Stable, machine-readable identifiers used both for the `sources_used` summary
# and for `pages_failed[].code` when a variant fails. Kept in one place so the
# mapping stays tight and the strings don't drift.
SOURCE_LABEL: dict[type, str] = {
    RmV6Source: "rm_v6",
    RmV5Source: "rm_v5",
    PdfPassthroughSource: "pdf_passthrough",
    MissingSource: "missing",
}


def source_label(src: PageSource) -> str:
    """Return the stable string label for a PageSource variant."""
    return SOURCE_LABEL[type(src)]
