# ABOUTME: Rendering pipeline dispatcher for reMarkable pages (typed PageSource union).
# ABOUTME: Mechanism-only: facades/render.py owns per-page source policy; this module just executes.

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from ..config import ensure_cairo_library_path
from .page_sources import (
    MissingSource,
    PageSource,
    PdfPassthroughSource,
    RmV5Source,
    RmV6Source,
    source_label,
)
from .pdf_passthrough import extract_pdf_page

ensure_cairo_library_path()


# ------------------------------------------------------------------
# Typed exceptions
# ------------------------------------------------------------------


class RenderError(Exception):
    """Base class for renderer failures. Carries a stable ``code`` string."""

    code: str = "render_error"


class LegacyV5Error(RenderError):
    """Raised when a page is in the pre-firmware-v3 v5 .rm format."""

    code = "v5_unsupported"


class NoSourceError(RenderError):
    """Raised when there is no usable source for a page (no .rm, no source PDF)."""

    code = "no_source"


class RmcFailedError(RenderError):
    """Raised when the rmc subprocess returns non-zero or produces no SVG."""

    code = "rmc_failed"


class CairoSvgFailedError(RenderError):
    """Raised when cairosvg cannot render the SVG produced by rmc."""

    code = "cairosvg_failed"


class PdfExtractError(RenderError):
    """Raised when pypdf fails to extract a page from the source PDF."""

    code = "pdf_extract_failed"


# ------------------------------------------------------------------
# Public dispatch surface
# ------------------------------------------------------------------


def render_page_source(src: PageSource) -> bytes:
    """Render a single ``PageSource`` to PDF bytes.

    Pure dispatch by variant. Each branch raises a typed ``RenderError``
    subclass on failure; callers map ``exc.code`` into ``pages_failed``.
    """
    match src:
        case RmV6Source(rm_path=rm_path):
            return _render_rm_v6(rm_path)
        case PdfPassthroughSource(source_pdf=src_pdf, pdf_page_index=idx):
            return _render_pdf_passthrough(src_pdf, idx)
        case RmV5Source(rm_path=rm_path):
            raise LegacyV5Error(
                f"{rm_path.name} is a legacy v5 .rm file (pre-firmware-v3). "
                "rmc/rmscene only support v6; re-open the notebook on the "
                "device or in the desktop app to migrate it to v6."
            )
        case MissingSource():
            raise NoSourceError(
                "no .rm file and no source PDF page available for this page"
            )
    raise RenderError(f"Unhandled PageSource variant: {type(src).__name__}")


class RemarkableRenderer:
    """Render a sequence of ``PageSource`` plans into a single merged PDF on disk."""

    def __init__(self, render_dir: Path):
        self.render_dir = Path(render_dir)

    def render_document_pages(
        self,
        doc_id: str,
        document_name: str,
        plan: list[PageSource | None],
        selected_indices: list[int],
    ) -> dict:
        """Render each ``PageSource`` in ``plan`` and merge into a single PDF.

        ``plan`` is parallel to ``selected_indices``: ``plan[i]`` is the source
        for ``selected_indices[i]``, or ``None`` for an out-of-bounds index.
        """
        self.render_dir.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        pages_rendered = 0
        pages_failed: list[dict] = []
        sources_used: dict[str, int] = {}

        for plan_pos, idx in enumerate(selected_indices):
            src = plan[plan_pos] if plan_pos < len(plan) else None
            if src is None:
                pages_failed.append(
                    {
                        "index": idx,
                        "code": "out_of_bounds",
                        "reason": "out of bounds",
                    }
                )
                continue

            try:
                pdf_bytes = render_page_source(src)
            except RenderError as exc:
                pages_failed.append(
                    {"index": idx, "code": exc.code, "reason": str(exc)}
                )
                continue
            except Exception as exc:
                pages_failed.append(
                    {"index": idx, "code": "render_error", "reason": str(exc)}
                )
                continue

            try:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)
            except Exception as exc:
                pages_failed.append(
                    {"index": idx, "code": "render_error", "reason": str(exc)}
                )
                continue

            pages_rendered += 1
            label = source_label(src)
            sources_used[label] = sources_used.get(label, 0) + 1

        if pages_rendered == 0:
            response: dict = {
                "pdf_path": None,
                "document_name": document_name,
                "pages_rendered": 0,
                "pages_failed": pages_failed,
                "page_indices": selected_indices,
            }
            return response

        pdf_path = self.render_dir / f"{doc_id}.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        response = {
            "pdf_path": str(pdf_path),
            "document_name": document_name,
            "pages_rendered": pages_rendered,
            "pages_failed": pages_failed,
            "page_indices": selected_indices,
        }
        if sources_used:
            response["sources_used"] = sources_used
        return response

    def cleanup(self) -> dict:
        """Remove all files from the render directory."""
        if not self.render_dir.exists():
            return {"files_removed": 0, "bytes_freed": 0}

        files_removed = 0
        bytes_freed = 0
        for f in self.render_dir.iterdir():
            if f.is_file():
                bytes_freed += f.stat().st_size
                f.unlink()
                files_removed += 1

        return {"files_removed": files_removed, "bytes_freed": bytes_freed}


# ------------------------------------------------------------------
# Per-variant backends
# ------------------------------------------------------------------


def _render_rm_v6(rm_path: Path) -> bytes:
    """Render a v6 .rm via rmc -> SVG -> cairosvg -> PDF bytes."""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        svg_path = tmp.name

    try:
        proc = _run_rmc(
            ["rmc", str(rm_path), "-o", svg_path], capture_output=True, text=True
        )
        returncode = getattr(proc, "returncode", 0)
        if returncode != 0:
            stderr = (getattr(proc, "stderr", "") or "").strip()
            detail = f": {stderr}" if stderr else ""
            raise RmcFailedError(
                f"rmc failed (exit {returncode}) for {rm_path}{detail}"
            )
        if not Path(svg_path).exists() or Path(svg_path).stat().st_size == 0:
            raise RmcFailedError(f"rmc produced no output for {rm_path}")
        try:
            return _svg_to_pdf_bytes(url=svg_path)
        except Exception as exc:
            raise CairoSvgFailedError(
                f"cairosvg failed to convert SVG for {rm_path}: {exc}"
            ) from exc
    finally:
        if Path(svg_path).exists():
            Path(svg_path).unlink()


def _render_pdf_passthrough(source_pdf: Path, page_index: int) -> bytes:
    """Wrap pypdf extraction errors in a typed renderer exception."""
    try:
        return extract_pdf_page(source_pdf, page_index)
    except (FileNotFoundError, IndexError) as exc:
        raise PdfExtractError(str(exc)) from exc
    except Exception as exc:
        raise PdfExtractError(
            f"failed to extract PDF page {page_index} from {source_pdf}: {exc}"
        ) from exc


def check_rmc_available() -> bool:
    """Whether the rmc binary is on PATH."""
    return shutil.which("rmc") is not None


def check_cairo_available() -> bool:
    """Whether cairosvg can render a minimal SVG end-to-end."""
    try:
        import cairosvg

        cairosvg.svg2pdf(
            bytestring=b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>'
        )
        return True
    except Exception:
        return False


# ------------------------------------------------------------------
# Module-level functions (patchable in tests)
# ------------------------------------------------------------------


def _run_rmc(args, **kwargs):
    """Run the rmc subprocess. Extracted for test patching."""
    return subprocess.run(args, **kwargs)


def _svg_to_pdf_bytes(**kwargs) -> bytes:
    """Convert SVG to PDF bytes via cairosvg. Extracted for test patching."""
    import cairosvg

    return cairosvg.svg2pdf(**kwargs)
