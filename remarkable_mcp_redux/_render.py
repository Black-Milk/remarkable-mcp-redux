# ABOUTME: Rendering pipeline for reMarkable .rm pages: rmc -> SVG -> cairosvg -> PDF.
# ABOUTME: Per-page rendering plus multi-page merge into a single PDF via pypdf.

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .config import ensure_cairo_library_path

ensure_cairo_library_path()


class RemarkableRenderer:
    """Render reMarkable .rm pages to PDF via rmc -> SVG -> cairosvg -> PDF."""

    def __init__(self, render_dir: Path):
        self.render_dir = Path(render_dir)

    def render_document_pages(
        self,
        doc_id: str,
        document_name: str,
        page_ids: list[str],
        page_dir: Path,
        selected_indices: list[int],
    ) -> dict:
        """Render selected pages and merge them into a single PDF on disk."""
        self.render_dir.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        pages_rendered = 0
        pages_failed: list[dict] = []

        for idx in selected_indices:
            if idx < 0 or idx >= len(page_ids):
                pages_failed.append({"index": idx, "reason": "out of bounds"})
                continue

            page_id = page_ids[idx]
            rm_path = page_dir / f"{page_id}.rm"

            if not rm_path.exists():
                pages_failed.append({"index": idx, "reason": "no .rm file"})
                continue

            try:
                pdf_bytes = render_single_page(rm_path)
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)
                pages_rendered += 1
            except Exception as exc:
                pages_failed.append({"index": idx, "reason": str(exc)})

        if pages_rendered == 0:
            return {
                "pdf_path": None,
                "document_name": document_name,
                "pages_rendered": 0,
                "pages_failed": pages_failed,
                "page_indices": selected_indices,
            }

        pdf_path = self.render_dir / f"{doc_id}.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        return {
            "pdf_path": str(pdf_path),
            "document_name": document_name,
            "pages_rendered": pages_rendered,
            "pages_failed": pages_failed,
            "page_indices": selected_indices,
        }

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


def render_single_page(rm_path: Path) -> bytes:
    """Render a single .rm file to PDF bytes via rmc -> SVG -> cairosvg."""
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
            raise RuntimeError(f"rmc failed (exit {returncode}) for {rm_path}{detail}")
        if not Path(svg_path).exists() or Path(svg_path).stat().st_size == 0:
            raise RuntimeError(f"rmc produced no output for {rm_path}")
        return _svg_to_pdf_bytes(url=svg_path)
    finally:
        if Path(svg_path).exists():
            Path(svg_path).unlink()


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
