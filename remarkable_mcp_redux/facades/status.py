"""StatusFacade — system diagnostics: cache existence, document count, rmc/cairo availability.

Cross-cutting health check; not tied to a single domain so it lives on its own facade.
"""

from pathlib import Path

from ..core.cache import RemarkableCache
from ..core.render import check_cairo_available, check_rmc_available
from ..responses import StatusResponse


class StatusFacade:
    """Diagnostics on the cache and rendering toolchain."""

    def __init__(self, base_path: Path, cache: RemarkableCache):
        self._base_path = base_path
        self._cache = cache

    def check(self) -> StatusResponse:
        """Report cache existence, document count, and render-toolchain availability.

        ``document_count`` counts only DocumentType records (folders excluded).
        ``rmc_available`` and ``cairo_available`` are static probes that report
        whether the optional render-pipeline dependencies are importable in
        the current environment.
        """
        cache_exists = self._cache.exists()
        return StatusResponse(
            cache_path=str(self._base_path),
            cache_exists=cache_exists,
            document_count=self._cache.count_documents() if cache_exists else 0,
            rmc_available=check_rmc_available(),
            cairo_available=check_cairo_available(),
        )
