"""Unit tests for RemarkableCache ancestry/descendant helpers using synthetic fixtures.

Constructs RemarkableCache directly without instantiating RemarkableClient.
"""

import json

import pytest

from remarkable_mcp_redux.core.cache import RemarkableCache
from tests.conftest import (
    NESTED_FOLDER_A,
    NESTED_FOLDER_B,
    NESTED_FOLDER_C,
    NESTED_FOLDER_D,
)

# ---------------------------------------------------------------------------
# RemarkableCache.is_descendant_of / count_descendants
# ---------------------------------------------------------------------------


class TestIsDescendantOf:
    @pytest.mark.unit
    def test_direct_child(self, nested_folder_cache):
        cache = RemarkableCache(nested_folder_cache)
        assert cache.is_descendant_of(NESTED_FOLDER_B, NESTED_FOLDER_A) is True

    @pytest.mark.unit
    def test_transitive_descendant(self, nested_folder_cache):
        cache = RemarkableCache(nested_folder_cache)
        assert cache.is_descendant_of(NESTED_FOLDER_C, NESTED_FOLDER_A) is True

    @pytest.mark.unit
    def test_self_is_descendant_of_self(self, nested_folder_cache):
        cache = RemarkableCache(nested_folder_cache)
        assert cache.is_descendant_of(NESTED_FOLDER_A, NESTED_FOLDER_A) is True

    @pytest.mark.unit
    def test_sibling_is_not_descendant(self, nested_folder_cache):
        cache = RemarkableCache(nested_folder_cache)
        assert cache.is_descendant_of(NESTED_FOLDER_D, NESTED_FOLDER_A) is False

    @pytest.mark.unit
    def test_unknown_id_returns_false(self, nested_folder_cache):
        cache = RemarkableCache(nested_folder_cache)
        assert cache.is_descendant_of("nope", NESTED_FOLDER_A) is False

    @pytest.mark.unit
    def test_handles_malformed_cycle(self, tmp_path):
        """If two folders illegally refer to each other as parents, the helper
        must terminate via its visited-set rather than loop forever."""
        cycle_a = "cycle-a"
        cycle_b = "cycle-b"
        (tmp_path / f"{cycle_a}.metadata").write_text(
            json.dumps(
                {
                    "type": "CollectionType",
                    "visibleName": "A",
                    "parent": cycle_b,
                    "lastModified": "1",
                }
            )
        )
        (tmp_path / f"{cycle_b}.metadata").write_text(
            json.dumps(
                {
                    "type": "CollectionType",
                    "visibleName": "B",
                    "parent": cycle_a,
                    "lastModified": "1",
                }
            )
        )
        cache = RemarkableCache(tmp_path)
        # Asking whether a cycle node is a descendant of an outsider must just
        # return False without hanging.
        assert cache.is_descendant_of(cycle_a, "outsider") is False

    @pytest.mark.unit
    def test_count_descendants_includes_transitive(self, nested_folder_cache):
        cache = RemarkableCache(nested_folder_cache)
        # A's subtree contains B, C, and the doc inside C: 3 descendants.
        assert cache.count_descendants(NESTED_FOLDER_A) == 3

    @pytest.mark.unit
    def test_count_descendants_leaf_folder(self, nested_folder_cache):
        cache = RemarkableCache(nested_folder_cache)
        # D has no descendants.
        assert cache.count_descendants(NESTED_FOLDER_D) == 0
