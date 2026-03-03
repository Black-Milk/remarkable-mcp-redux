# ABOUTME: Client for reading and rendering reMarkable tablet documents from local cache.
# ABOUTME: Wraps rmc (SVG rendering) + cairosvg (PDF conversion) + pypdf (merging) pipeline.

import io
import json
import os
import shutil
import subprocess
import sys
import logging
from pathlib import Path

from pypdf import PdfWriter, PdfReader

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("remarkable-mcp")

DEFAULT_BASE_PATH = Path(
    os.path.expanduser(
        "~/Library/Containers/com.remarkable.desktop/"
        "Data/Library/Application Support/remarkable/desktop"
    )
)
DEFAULT_RENDER_DIR = Path("/tmp/remarkable-renders")


class RemarkableClient:
    """Reads and renders reMarkable documents from the local desktop app cache."""

    def __init__(
        self,
        base_path: Path = DEFAULT_BASE_PATH,
        render_dir: Path = DEFAULT_RENDER_DIR,
    ):
        self.base_path = Path(base_path)
        self.render_dir = Path(render_dir)
        # Ensure cairosvg can find Homebrew's cairo on macOS
        if "DYLD_LIBRARY_PATH" not in os.environ:
            os.environ["DYLD_LIBRARY_PATH"] = "/opt/homebrew/lib"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_status(self) -> dict:
        """Diagnostics: cache exists, tool availability, document count."""
        cache_exists = self.base_path.exists() and self.base_path.is_dir()
        doc_count = 0
        if cache_exists:
            doc_count = sum(
                1 for f in self.base_path.iterdir() if f.suffix == ".metadata"
            )
        return {
            "cache_path": str(self.base_path),
            "cache_exists": cache_exists,
            "document_count": doc_count,
            "rmc_available": shutil.which("rmc") is not None,
            "cairo_available": self._check_cairo(),
        }

    def list_documents(self, search: str | None = None) -> dict:
        """List documents in the cache, with optional case-insensitive search."""
        if not self.base_path.exists():
            return {"documents": [], "count": 0}

        documents = []
        for meta_path in sorted(self.base_path.glob("*.metadata")):
            doc_id = meta_path.stem
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            name = meta.get("visibleName", doc_id)
            if search and search.lower() not in name.lower():
                continue

            page_ids = self._get_page_ids(doc_id)
            documents.append({
                "doc_id": doc_id,
                "name": name,
                "page_count": len(page_ids),
                "last_modified": meta.get("lastModified", ""),
            })

        return {"documents": documents, "count": len(documents)}

    def get_document_info(self, doc_id: str) -> dict:
        """Detailed metadata for a single document."""
        meta_path = self.base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            return {"error": True, "detail": f"Document not found: {doc_id}"}

        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            return {"error": True, "detail": f"Failed to read metadata: {exc}"}

        page_ids = self._get_page_ids(doc_id)
        content_format = self._detect_content_format(doc_id)

        return {
            "doc_id": doc_id,
            "name": meta.get("visibleName", doc_id),
            "page_count": len(page_ids),
            "page_ids": page_ids,
            "content_format": content_format,
        }

    def render_pages(
        self,
        doc_id: str,
        page_indices: list[int] | None = None,
        last_n: int | None = None,
        first_n: int | None = None,
    ) -> dict:
        """Render selected pages of a document to a single PDF.

        Priority: page_indices > last_n > first_n > all pages.
        """
        meta_path = self.base_path / f"{doc_id}.metadata"
        if not meta_path.exists():
            return {"error": True, "detail": f"Document not found: {doc_id}"}

        all_page_ids = self._get_page_ids(doc_id)
        if not all_page_ids:
            return {"error": True, "detail": "No pages found in document"}

        doc_name = self._get_document_name(doc_id)

        # Determine which indices to render
        selected_indices = self._resolve_page_selection(
            total=len(all_page_ids),
            page_indices=page_indices,
            last_n=last_n,
            first_n=first_n,
        )

        # Render selected pages
        self.render_dir.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        pages_rendered = 0
        pages_failed = []

        for idx in selected_indices:
            if idx < 0 or idx >= len(all_page_ids):
                pages_failed.append({"index": idx, "reason": "out of bounds"})
                continue

            page_id = all_page_ids[idx]
            rm_path = self.base_path / doc_id / f"{page_id}.rm"

            if not rm_path.exists():
                pages_failed.append({"index": idx, "reason": "no .rm file"})
                continue

            try:
                pdf_bytes = self._render_single_page(rm_path)
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)
                pages_rendered += 1
            except Exception as exc:
                pages_failed.append({"index": idx, "reason": str(exc)})

        if pages_rendered == 0:
            return {
                "pdf_path": None,
                "document_name": doc_name,
                "pages_rendered": 0,
                "pages_failed": pages_failed,
                "page_indices": selected_indices,
            }

        pdf_path = self.render_dir / f"{doc_id}.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        return {
            "pdf_path": str(pdf_path),
            "document_name": doc_name,
            "pages_rendered": pages_rendered,
            "pages_failed": pages_failed,
            "page_indices": selected_indices,
        }

    def cleanup_renders(self) -> dict:
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
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_page_ids(self, doc_id: str) -> list[str]:
        """Extract page IDs from a document, supporting v1 and v2 content formats."""
        content_path = self.base_path / f"{doc_id}.content"
        if not content_path.exists():
            return []

        try:
            with open(content_path) as f:
                content = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        # v1 format: flat list of UUID strings
        if "pages" in content and content["pages"]:
            return content["pages"]

        # v2 format: cPages.pages[].id
        cpages = content.get("cPages", {})
        return [p["id"] for p in cpages.get("pages", [])]

    def _detect_content_format(self, doc_id: str) -> str:
        """Detect whether a document uses v1 or v2 content format."""
        content_path = self.base_path / f"{doc_id}.content"
        if not content_path.exists():
            return "unknown"

        try:
            with open(content_path) as f:
                content = json.load(f)
        except (json.JSONDecodeError, OSError):
            return "unknown"

        if "pages" in content and content["pages"]:
            return "v1"
        if "cPages" in content:
            return "v2"
        return "unknown"

    def _get_document_name(self, doc_id: str) -> str:
        """Get the visible name of a document from its metadata."""
        meta_path = self.base_path / f"{doc_id}.metadata"
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    return json.load(f).get("visibleName", doc_id)
            except (json.JSONDecodeError, OSError):
                pass
        return doc_id

    def _resolve_page_selection(
        self,
        total: int,
        page_indices: list[int] | None,
        last_n: int | None,
        first_n: int | None,
    ) -> list[int]:
        """Resolve page selection args to a list of page indices."""
        if page_indices is not None:
            return page_indices
        if last_n is not None:
            start = max(0, total - last_n)
            return list(range(start, total))
        if first_n is not None:
            return list(range(min(first_n, total)))
        return list(range(total))

    def _render_single_page(self, rm_path: Path) -> bytes:
        """Render a single .rm file to PDF bytes via rmc → SVG → cairosvg."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
            svg_path = tmp.name

        try:
            _run_rmc(["rmc", str(rm_path), "-o", svg_path], capture_output=True, text=True)
            if not Path(svg_path).exists() or Path(svg_path).stat().st_size == 0:
                raise RuntimeError(f"rmc produced no output for {rm_path}")
            return _svg_to_pdf_bytes(url=svg_path)
        finally:
            if Path(svg_path).exists():
                Path(svg_path).unlink()

    def _check_cairo(self) -> bool:
        """Check if cairosvg can function."""
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
