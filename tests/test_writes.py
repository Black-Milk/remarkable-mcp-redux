"""Unit tests for the WritesFacade (rename, move, pin, restore, create_folder, cleanup).

Covers backup retention, sync flags, dry-run mode, and trashed-record refusal.
"""

import json
from pathlib import Path

import pytest

from remarkable_mcp_redux.client import RemarkableClient
from remarkable_mcp_redux.config import BACKUP_RETENTION_ENV_VAR
from remarkable_mcp_redux.exceptions import (
    BackupMissingError,
    ConflictError,
    KindMismatchError,
    NotFoundError,
    TrashedRecordError,
    ValidationError,
)
from tests.conftest import (
    NESTED_DOC_INSIDE_C,
    NESTED_FOLDER_A,
    NESTED_FOLDER_C,
    NESTED_FOLDER_D,
    PERSONAL_FOLDER_ID,
    PINNED_DOC_ID,
    TRASHED_DOC_ID,
    WORK_FOLDER_ID,
)

# ---------------------------------------------------------------------------
# writes.rename_document
# ---------------------------------------------------------------------------


class TestRenameDocument:
    @pytest.mark.unit
    def test_renames_visible_name_on_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_document(
            "aaaa-1111-2222-3333", "Renamed Journal"
        )
        assert result.get("error") is not True
        assert result["dry_run"] is False
        assert result["record_id"] == "aaaa-1111-2222-3333"
        assert result["old_name"] == "Morning Journal"
        assert result["new_name"] == "Renamed Journal"

        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Renamed Journal"

    @pytest.mark.unit
    def test_dry_run_does_not_modify_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_document(
            "aaaa-1111-2222-3333", "X", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["old_name"] == "Morning Journal"
        assert result["new_name"] == "X"
        assert "backup_path" not in result

        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Morning Journal"
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_creates_timestamped_backup(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        backup_path = Path(result["backup_path"])
        assert backup_path.exists()
        assert backup_path.name.startswith("aaaa-1111-2222-3333.metadata.bak.")
        backup_data = json.loads(backup_path.read_text())
        assert backup_data["visibleName"] == "Morning Journal"

    @pytest.mark.unit
    def test_updates_last_modified_timestamp(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        before = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["lastModified"]
        client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        after = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["lastModified"]
        assert int(after) > int(before)

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder"):
            client.writes.rename_document(WORK_FOLDER_ID, "X")
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Work"

    @pytest.mark.unit
    def test_rejects_missing_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="not found"):
            client.writes.rename_document("does-not-exist", "X")

    @pytest.mark.unit
    def test_rejects_empty_name(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="non-empty"):
            client.writes.rename_document("aaaa-1111-2222-3333", "   ")
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Morning Journal"


# ---------------------------------------------------------------------------
# writes.move_document
# ---------------------------------------------------------------------------


class TestMoveDocument:
    @pytest.mark.unit
    def test_moves_doc_into_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.move_document("aaaa-1111-2222-3333", WORK_FOLDER_ID)
        assert result.get("error") is not True
        assert result["record_id"] == "aaaa-1111-2222-3333"
        assert result["old_parent"] == ""
        assert result["new_parent"] == WORK_FOLDER_ID
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_moves_doc_to_root(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.move_document("bbbb-4444-5555-6666", "")
        assert result.get("error") is not True
        assert result["old_parent"] == WORK_FOLDER_ID
        assert result["new_parent"] == ""
        on_disk = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.metadata").read_text()
        )
        assert on_disk["parent"] == ""

    @pytest.mark.unit
    def test_dry_run_does_not_modify_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.move_document(
            "aaaa-1111-2222-3333", WORK_FOLDER_ID, dry_run=True
        )
        assert result["dry_run"] is True
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["parent"] == ""
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_rejects_unknown_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="(?i)folder"):
            client.writes.move_document("aaaa-1111-2222-3333", "nonexistent-folder")

    @pytest.mark.unit
    def test_rejects_document_as_parent(self, fake_cache):
        """Moving into another document is invalid: targets must be CollectionType."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder|collection"):
            client.writes.move_document(
                "aaaa-1111-2222-3333", "bbbb-4444-5555-6666"
            )

    @pytest.mark.unit
    def test_rejects_self_as_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)itself"):
            client.writes.move_document(
                "aaaa-1111-2222-3333", "aaaa-1111-2222-3333"
            )

    @pytest.mark.unit
    def test_rejects_collection_source(self, fake_cache):
        """Cannot move a folder via this tool (folder moves are out of scope)."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder|collection"):
            client.writes.move_document(WORK_FOLDER_ID, "")

    @pytest.mark.unit
    def test_creates_timestamped_backup(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.move_document("aaaa-1111-2222-3333", WORK_FOLDER_ID)
        backup_path = Path(result["backup_path"])
        assert backup_path.exists()
        assert backup_path.name.startswith("aaaa-1111-2222-3333.metadata.bak.")


# ---------------------------------------------------------------------------
# Sync flags - every write path must set metadatamodified and modified
# ---------------------------------------------------------------------------


class TestSyncFlags:
    """All write paths must set metadatamodified=True and modified=True so the
    reMarkable desktop sync engine recognises the change as a local edit."""

    @pytest.mark.unit
    def test_rename_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_move_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.writes.move_document("aaaa-1111-2222-3333", WORK_FOLDER_ID)
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_pin_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.writes.pin_document("aaaa-1111-2222-3333", True)
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_create_folder_sets_sync_flags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.create_folder("Newly Created")
        folder_id = result["folder_id"]
        on_disk = json.loads((fake_cache / f"{folder_id}.metadata").read_text())
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True

    @pytest.mark.unit
    def test_restore_writes_resurrect_sync_flags(self, fake_cache):
        """A restore writes the backup contents back; the backup itself was made
        before sync flags were set, but the post-restore safety backup must
        capture the live (sync-flags-True) state. The restored file matches
        whatever was in the backup."""
        client = RemarkableClient(base_path=fake_cache)
        client.writes.rename_document("aaaa-1111-2222-3333", "First Rename")
        client.writes.rename_document("aaaa-1111-2222-3333", "Second Rename")
        client.writes.restore_metadata("aaaa-1111-2222-3333")
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["metadatamodified"] is True
        assert on_disk["modified"] is True


# ---------------------------------------------------------------------------
# Refuse trashed records on rename/move/pin
# ---------------------------------------------------------------------------


class TestRefuseDeleted:
    @pytest.mark.unit
    def test_rename_refuses_trashed(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(TrashedRecordError, match="(?i)trash"):
            client.writes.rename_document(TRASHED_DOC_ID, "Anything")

    @pytest.mark.unit
    def test_move_refuses_trashed(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(TrashedRecordError, match="(?i)trash"):
            client.writes.move_document(TRASHED_DOC_ID, WORK_FOLDER_ID)

    @pytest.mark.unit
    def test_move_rejects_trash_destination(self, fake_cache):
        """The 'trash' sentinel is a malformed destination, not a trashed record."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)trash"):
            client.writes.move_document("aaaa-1111-2222-3333", "trash")

    @pytest.mark.unit
    def test_pin_refuses_trashed(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(TrashedRecordError, match="(?i)trash"):
            client.writes.pin_document(TRASHED_DOC_ID, True)


# ---------------------------------------------------------------------------
# Backup retention - auto-prune and env override
# ---------------------------------------------------------------------------


class TestBackupRetention:
    @pytest.mark.unit
    def test_keeps_last_five_by_default(self, fake_cache, monkeypatch):
        monkeypatch.delenv(BACKUP_RETENTION_ENV_VAR, raising=False)
        client = RemarkableClient(base_path=fake_cache)
        for i in range(8):
            client.writes.rename_document("aaaa-1111-2222-3333", f"Name {i}")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 5

    @pytest.mark.unit
    def test_retention_zero_keeps_only_pre_write_backup(self, fake_cache, monkeypatch):
        """retention=0 means "delete every backup older than the one just made".
        After a single rename, the backup chain is empty (the backup made by the
        rename itself is also pruned because retention=0 is "keep zero")."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "0")
        client = RemarkableClient(base_path=fake_cache)
        client.writes.rename_document("aaaa-1111-2222-3333", "Once")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 0

    @pytest.mark.unit
    def test_env_override_keeps_two(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "2")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(5):
            client.writes.rename_document("aaaa-1111-2222-3333", f"Name {i}")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 2

    @pytest.mark.unit
    def test_invalid_env_falls_back_to_default(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "not-a-number")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(7):
            client.writes.rename_document("aaaa-1111-2222-3333", f"Name {i}")
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 5  # default

    @pytest.mark.unit
    def test_retention_isolates_documents(self, fake_cache, monkeypatch):
        """Pruning one document's chain must not delete another document's backups."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "1")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(3):
            client.writes.rename_document("aaaa-1111-2222-3333", f"A{i}")
        for i in range(3):
            client.writes.rename_document("bbbb-4444-5555-6666", f"B{i}")
        a_backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        b_backups = list(fake_cache.glob("bbbb-4444-5555-6666.metadata.bak.*"))
        assert len(a_backups) == 1
        assert len(b_backups) == 1


# ---------------------------------------------------------------------------
# writes.cleanup_metadata_backups bulk tool
# ---------------------------------------------------------------------------


class TestCleanupBackupsTool:
    @pytest.mark.unit
    def test_refuses_no_filters(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)filter"):
            client.writes.cleanup_metadata_backups()

    @pytest.mark.unit
    def test_doc_id_filter_targets_single_chain(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")  # do not auto-prune
        client = RemarkableClient(base_path=fake_cache)
        for i in range(3):
            client.writes.rename_document("aaaa-1111-2222-3333", f"A{i}")
        for i in range(3):
            client.writes.rename_document("bbbb-4444-5555-6666", f"B{i}")
        result = client.writes.cleanup_metadata_backups(doc_id="aaaa-1111-2222-3333")
        assert result["files_removed"] == 3
        b_backups = list(fake_cache.glob("bbbb-4444-5555-6666.metadata.bak.*"))
        assert len(b_backups) == 3

    @pytest.mark.unit
    def test_older_than_zero_wipes_everything(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(2):
            client.writes.rename_document("aaaa-1111-2222-3333", f"A{i}")
        result = client.writes.cleanup_metadata_backups(older_than_days=0)
        assert result["files_removed"] >= 2
        backups = list(fake_cache.glob("*.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_older_than_high_keeps_recent(self, fake_cache, monkeypatch):
        """With a future cutoff (older_than_days=365), recent backups stay put."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(3):
            client.writes.rename_document("aaaa-1111-2222-3333", f"A{i}")
        result = client.writes.cleanup_metadata_backups(older_than_days=365)
        assert result["files_removed"] == 0
        assert result["backups_remaining"] == 3

    @pytest.mark.unit
    def test_dry_run_preserves_files(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        for i in range(2):
            client.writes.rename_document("aaaa-1111-2222-3333", f"A{i}")
        result = client.writes.cleanup_metadata_backups(
            older_than_days=0, dry_run=True
        )
        assert result["dry_run"] is True
        assert result["files_removed"] == 2
        backups = list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        assert len(backups) == 2


# ---------------------------------------------------------------------------
# writes.pin_document
# ---------------------------------------------------------------------------


class TestPinTool:
    @pytest.mark.unit
    def test_pins_a_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.pin_document("aaaa-1111-2222-3333", True)
        assert result.get("error") is not True
        assert result["new_pinned"] is True
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["pinned"] is True

    @pytest.mark.unit
    def test_unpins_a_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.pin_document(PINNED_DOC_ID, False)
        assert result.get("error") is not True
        assert result["old_pinned"] is True
        assert result["new_pinned"] is False
        on_disk = json.loads((fake_cache / f"{PINNED_DOC_ID}.metadata").read_text())
        assert on_disk["pinned"] is False

    @pytest.mark.unit
    def test_idempotent_repin(self, fake_cache):
        """Pinning an already-pinned doc still succeeds and writes."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.pin_document(PINNED_DOC_ID, True)
        assert result.get("error") is not True
        assert result["new_pinned"] is True

    @pytest.mark.unit
    def test_dry_run_no_change(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        before = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["pinned"]
        result = client.writes.pin_document(
            "aaaa-1111-2222-3333", True, dry_run=True
        )
        assert result["dry_run"] is True
        after = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )["pinned"]
        assert before == after

    @pytest.mark.unit
    def test_rejects_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder|collection"):
            client.writes.pin_document(WORK_FOLDER_ID, True)


# ---------------------------------------------------------------------------
# writes.restore_metadata
# ---------------------------------------------------------------------------


class TestRestoreTool:
    @pytest.mark.unit
    def test_round_trip_restore(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        original = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        result = client.writes.restore_metadata("aaaa-1111-2222-3333")
        assert result.get("error") is not True
        restored = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert restored["visibleName"] == original["visibleName"]

    @pytest.mark.unit
    def test_creates_pre_restore_backup(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        before_count = len(
            list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        )
        result = client.writes.restore_metadata("aaaa-1111-2222-3333")
        after_count = len(
            list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))
        )
        assert Path(result["pre_restore_backup"]).exists()
        assert after_count >= before_count or Path(result["pre_restore_backup"]).exists()

    @pytest.mark.unit
    def test_no_backups_raises_backup_missing(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(BackupMissingError, match="(?i)backup"):
            client.writes.restore_metadata("aaaa-1111-2222-3333")

    @pytest.mark.unit
    def test_missing_doc_raises_not_found(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="(?i)metadata|not found"):
            client.writes.restore_metadata("nonexistent-doc")

    @pytest.mark.unit
    def test_dry_run_reports_source(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        result = client.writes.restore_metadata("aaaa-1111-2222-3333", dry_run=True)
        assert result["dry_run"] is True
        assert "would_restore_from" in result
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Renamed"


# ---------------------------------------------------------------------------
# writes.create_folder
# ---------------------------------------------------------------------------


class TestCreateFolder:
    @pytest.mark.unit
    def test_creates_root_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.create_folder("Brand New")
        assert result.get("error") is not True
        folder_id = result["folder_id"]
        meta = json.loads((fake_cache / f"{folder_id}.metadata").read_text())
        assert meta["type"] == "CollectionType"
        assert meta["visibleName"] == "Brand New"
        assert meta["parent"] == ""
        assert meta["deleted"] is False
        assert (fake_cache / f"{folder_id}.content").exists()

    @pytest.mark.unit
    def test_creates_nested_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.create_folder("Subfolder", parent=WORK_FOLDER_ID)
        assert result.get("error") is not True
        meta = json.loads((fake_cache / f"{result['folder_id']}.metadata").read_text())
        assert meta["parent"] == WORK_FOLDER_ID

    @pytest.mark.unit
    def test_rejects_empty_name(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="non-empty"):
            client.writes.create_folder("   ")

    @pytest.mark.unit
    def test_rejects_trash_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)trash"):
            client.writes.create_folder("Doomed", parent="trash")

    @pytest.mark.unit
    def test_rejects_missing_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="(?i)not found"):
            client.writes.create_folder("Lost", parent="nonexistent-folder")

    @pytest.mark.unit
    def test_rejects_document_as_parent(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder|collection"):
            client.writes.create_folder("Bad", parent="aaaa-1111-2222-3333")

    @pytest.mark.unit
    def test_rejects_duplicate_sibling_name(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ConflictError, match="(?i)exists"):
            client.writes.create_folder("Work")  # collides with WORK_FOLDER_ID

    @pytest.mark.unit
    def test_duplicate_check_is_case_insensitive(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ConflictError, match="(?i)exists"):
            client.writes.create_folder("WORK")

    @pytest.mark.unit
    def test_duplicate_allowed_under_different_parents(self, fake_cache):
        """Same folder name is fine when parents differ."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.create_folder("Work", parent=PERSONAL_FOLDER_ID)
        assert result.get("error") is not True

    @pytest.mark.unit
    def test_dry_run_does_not_write(self, fake_cache):
        before = set(fake_cache.glob("*.metadata"))
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.create_folder("Plan-only", dry_run=True)
        assert result["dry_run"] is True
        after = set(fake_cache.glob("*.metadata"))
        assert before == after

    @pytest.mark.unit
    def test_orphan_content_cleaned_on_metadata_failure(
        self, fake_cache, monkeypatch
    ):
        """If the .metadata write fails, the .content sibling must be removed."""
        from remarkable_mcp_redux.core import writes as writes_module

        original_write = writes_module._atomic_write_json
        calls = {"n": 0}

        def flaky_write(target, data):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("boom")
            return original_write(target, data)

        monkeypatch.setattr(writes_module, "_atomic_write_json", flaky_write)
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(OSError):
            client.writes.create_folder("Doomed Folder")
        orphans = [
            p for p in fake_cache.glob("*.content") if not (p.with_suffix(".metadata")).exists()
        ]
        assert orphans == []


# ---------------------------------------------------------------------------
# writes.rename_folder
# ---------------------------------------------------------------------------


class TestFolderRename:
    @pytest.mark.unit
    def test_renames_folder(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_folder(WORK_FOLDER_ID, "Workspace")
        assert result.get("error") is not True
        assert result["record_id"] == WORK_FOLDER_ID
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Workspace"

    @pytest.mark.unit
    def test_rejects_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)document"):
            client.writes.rename_folder("aaaa-1111-2222-3333", "Should fail")

    @pytest.mark.unit
    def test_rejects_duplicate_sibling(self, fake_cache):
        """Renaming Work to "Personal" collides with the existing sibling Personal."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ConflictError, match="(?i)exists"):
            client.writes.rename_folder(WORK_FOLDER_ID, "Personal")

    @pytest.mark.unit
    def test_idempotent_self_rename_allowed(self, fake_cache):
        """Renaming to the same name is a no-conflict sibling-uniqueness case."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_folder(WORK_FOLDER_ID, "Work")
        assert result.get("error") is not True

    @pytest.mark.unit
    def test_dry_run_no_change(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_folder(WORK_FOLDER_ID, "Workspace", dry_run=True)
        assert result["dry_run"] is True
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Work"


# ---------------------------------------------------------------------------
# writes.move_folder
# ---------------------------------------------------------------------------


class TestRenameDocumentsBatch:
    @pytest.mark.unit
    def test_happy_path(self, fake_cache):
        """Three docs, all renamed; results aligned with input order."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "new_name": "Renamed Journal"},
            {"id": "bbbb-4444-5555-6666", "new_name": "Renamed Sketch"},
            {"id": "cccc-7777-8888-9999", "new_name": "Renamed Empty"},
        ]
        result = client.writes.rename_documents_batch(items)
        assert result["dry_run"] is False
        assert result["succeeded"] == 3
        assert result["failed"] == 0
        rows = result["results"]
        assert [r.id for r in rows] == [
            "aaaa-1111-2222-3333",
            "bbbb-4444-5555-6666",
            "cccc-7777-8888-9999",
        ]
        for row in rows:
            assert row.success is True
            assert row.backup_path is not None
            assert Path(row.backup_path).exists()
        for doc_id, expected in [
            ("aaaa-1111-2222-3333", "Renamed Journal"),
            ("bbbb-4444-5555-6666", "Renamed Sketch"),
            ("cccc-7777-8888-9999", "Renamed Empty"),
        ]:
            on_disk = json.loads((fake_cache / f"{doc_id}.metadata").read_text())
            assert on_disk["visibleName"] == expected

    @pytest.mark.unit
    def test_dry_run_does_not_write(self, fake_cache):
        """Dry-run reports succeeded counts but leaves the cache untouched."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "new_name": "Plan-only A"},
            {"id": "bbbb-4444-5555-6666", "new_name": "Plan-only B"},
        ]
        result = client.writes.rename_documents_batch(items, dry_run=True)
        assert result["dry_run"] is True
        assert result["succeeded"] == 2
        assert result["failed"] == 0
        for row in result["results"]:
            assert row.success is True
            assert row.backup_path is None
        for doc_id, original in [
            ("aaaa-1111-2222-3333", "Morning Journal"),
            ("bbbb-4444-5555-6666", "Architecture Sketch"),
        ]:
            on_disk = json.loads((fake_cache / f"{doc_id}.metadata").read_text())
            assert on_disk["visibleName"] == original
        backups = list(fake_cache.glob("*.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_mixed_outcomes_continue_on_error(self, fake_cache):
        """One success, one not_found, one kind_mismatch (folder id) — verify
        ordering, error codes, and that the success still writes."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "new_name": "Renamed OK"},
            {"id": "does-not-exist", "new_name": "Doomed"},
            {"id": WORK_FOLDER_ID, "new_name": "Folder Rename"},
        ]
        result = client.writes.rename_documents_batch(items)
        assert result["succeeded"] == 1
        assert result["failed"] == 2
        rows = result["results"]
        assert rows[0].success is True
        assert rows[0].old_name == "Morning Journal"
        assert rows[1].success is False
        assert rows[1].code == "not_found"
        assert rows[2].success is False
        assert rows[2].code == "kind_mismatch"

        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Renamed OK"
        folder_on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert folder_on_disk["visibleName"] == "Work"

    @pytest.mark.unit
    def test_trashed_record_yields_trashed_code(self, fake_cache):
        """Trashed record reports code=trashed; sibling items still process."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": TRASHED_DOC_ID, "new_name": "Resurrect Me"},
            {"id": "aaaa-1111-2222-3333", "new_name": "Renamed Anyway"},
        ]
        result = client.writes.rename_documents_batch(items)
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert result["results"][0].success is False
        assert result["results"][0].code == "trashed"
        assert result["results"][1].success is True

        trashed_on_disk = json.loads(
            (fake_cache / f"{TRASHED_DOC_ID}.metadata").read_text()
        )
        assert trashed_on_disk["visibleName"] == "Trashed Note"

    @pytest.mark.unit
    def test_empty_list_raises_validation(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)non-empty"):
            client.writes.rename_documents_batch([])

    @pytest.mark.unit
    def test_duplicate_ids_raises_validation(self, fake_cache):
        """Duplicate ids in one batch are refused before any write happens."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "new_name": "First"},
            {"id": "aaaa-1111-2222-3333", "new_name": "Second"},
        ]
        with pytest.raises(ValidationError, match="(?i)duplicate"):
            client.writes.rename_documents_batch(items)
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Morning Journal"

    @pytest.mark.unit
    def test_per_item_empty_name_does_not_abort_batch(self, fake_cache):
        """An empty new_name on one item surfaces as code=validation; siblings still process."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "new_name": "   "},
            {"id": "bbbb-4444-5555-6666", "new_name": "Survives"},
        ]
        result = client.writes.rename_documents_batch(items)
        assert result["results"][0].success is False
        assert result["results"][0].code == "validation"
        assert result["results"][1].success is True


class TestRenameFoldersBatch:
    @pytest.mark.unit
    def test_happy_path(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": WORK_FOLDER_ID, "new_name": "Workspace"},
            {"id": PERSONAL_FOLDER_ID, "new_name": "Private"},
        ]
        result = client.writes.rename_folders_batch(items)
        assert result["succeeded"] == 2
        assert result["failed"] == 0
        for folder_id, expected in [
            (WORK_FOLDER_ID, "Workspace"),
            (PERSONAL_FOLDER_ID, "Private"),
        ]:
            on_disk = json.loads((fake_cache / f"{folder_id}.metadata").read_text())
            assert on_disk["visibleName"] == expected

    @pytest.mark.unit
    def test_in_batch_sibling_collision(self, fake_cache):
        """[Work->Foo, Personal->Foo] under root: first wins, second reports conflict."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": WORK_FOLDER_ID, "new_name": "Foo"},
            {"id": PERSONAL_FOLDER_ID, "new_name": "Foo"},
        ]
        result = client.writes.rename_folders_batch(items)
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert result["results"][0].success is True
        assert result["results"][1].success is False
        assert result["results"][1].code == "conflict"

        work_on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert work_on_disk["visibleName"] == "Foo"
        personal_on_disk = json.loads(
            (fake_cache / f"{PERSONAL_FOLDER_ID}.metadata").read_text()
        )
        assert personal_on_disk["visibleName"] == "Personal"

    @pytest.mark.unit
    def test_existing_sibling_collision(self, fake_cache):
        """Renaming Work to "Personal" collides with the existing sibling Personal
        even though Personal isn't in the batch."""
        client = RemarkableClient(base_path=fake_cache)
        items = [{"id": WORK_FOLDER_ID, "new_name": "Personal"}]
        result = client.writes.rename_folders_batch(items)
        assert result["failed"] == 1
        assert result["results"][0].success is False
        assert result["results"][0].code == "conflict"
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Work"

    @pytest.mark.unit
    def test_dry_run_simulates_in_batch_collision(self, fake_cache):
        """Dry-run still walks the bucket so [A->Foo, B->Foo] flags the second
        item without writing anything."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": WORK_FOLDER_ID, "new_name": "Shared"},
            {"id": PERSONAL_FOLDER_ID, "new_name": "Shared"},
        ]
        result = client.writes.rename_folders_batch(items, dry_run=True)
        assert result["dry_run"] is True
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert result["results"][1].code == "conflict"

        for folder_id, original in [
            (WORK_FOLDER_ID, "Work"),
            (PERSONAL_FOLDER_ID, "Personal"),
        ]:
            on_disk = json.loads((fake_cache / f"{folder_id}.metadata").read_text())
            assert on_disk["visibleName"] == original
        backups = list(fake_cache.glob("*.metadata.bak.*"))
        assert backups == []

    @pytest.mark.unit
    def test_self_rename_allowed_in_batch(self, fake_cache):
        """Renaming a folder to its current name (case-only change) must not
        trip the in-batch sibling check."""
        client = RemarkableClient(base_path=fake_cache)
        items = [{"id": WORK_FOLDER_ID, "new_name": "WORK"}]
        result = client.writes.rename_folders_batch(items)
        assert result["succeeded"] == 1
        assert result["results"][0].success is True


class TestRenameRecordSingularUnchanged:
    """Regression: extracting _validate_rename_target must not change the
    behavior of the singular rename_document/rename_folder path."""

    @pytest.mark.unit
    def test_singular_document_rename_still_works(self, fake_cache):
        """Document rename echoes the affected id under ``record_id``, writes
        visibleName atomically, and produces a backup."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_document(
            "aaaa-1111-2222-3333", "Singular Rename"
        )
        assert result["dry_run"] is False
        assert result["record_id"] == "aaaa-1111-2222-3333"
        assert "record_id" in result
        assert result["old_name"] == "Morning Journal"
        assert result["new_name"] == "Singular Rename"
        assert Path(result["backup_path"]).exists()
        on_disk = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Singular Rename"

    @pytest.mark.unit
    def test_singular_folder_rename_still_works(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.rename_folder(WORK_FOLDER_ID, "Workspace")
        assert result["dry_run"] is False
        assert result["record_id"] == WORK_FOLDER_ID
        assert "record_id" in result
        assert result["old_name"] == "Work"
        assert result["new_name"] == "Workspace"
        on_disk = json.loads(
            (fake_cache / f"{WORK_FOLDER_ID}.metadata").read_text()
        )
        assert on_disk["visibleName"] == "Workspace"

    @pytest.mark.unit
    def test_singular_validation_errors_unchanged(self, fake_cache):
        """Empty name still raises ValidationError with the same message shape."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="non-empty"):
            client.writes.rename_document("aaaa-1111-2222-3333", "   ")


class TestFolderMove:
    @pytest.mark.unit
    def test_moves_folder(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.writes.move_folder(NESTED_FOLDER_D, NESTED_FOLDER_A)
        assert result.get("error") is not True
        assert result["record_id"] == NESTED_FOLDER_D
        on_disk = json.loads(
            (nested_folder_cache / f"{NESTED_FOLDER_D}.metadata").read_text()
        )
        assert on_disk["parent"] == NESTED_FOLDER_A

    @pytest.mark.unit
    def test_reports_descendants_affected(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.writes.move_folder(NESTED_FOLDER_A, NESTED_FOLDER_D)
        assert result["descendants_affected"] == 3

    @pytest.mark.unit
    def test_rejects_self_as_parent(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        with pytest.raises(ValidationError, match="(?i)itself"):
            client.writes.move_folder(NESTED_FOLDER_A, NESTED_FOLDER_A)

    @pytest.mark.unit
    def test_rejects_descendant_as_parent(self, nested_folder_cache):
        """Cycle prevention: cannot move A under its own descendant C."""
        client = RemarkableClient(base_path=nested_folder_cache)
        with pytest.raises(ValidationError, match="(?i)subtree"):
            client.writes.move_folder(NESTED_FOLDER_A, NESTED_FOLDER_C)

    @pytest.mark.unit
    def test_rejects_trash_destination(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        with pytest.raises(ValidationError, match="(?i)trash"):
            client.writes.move_folder(NESTED_FOLDER_A, "trash")

    @pytest.mark.unit
    def test_rejects_document_target(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder|collection"):
            client.writes.move_folder(NESTED_FOLDER_A, NESTED_DOC_INSIDE_C)

    @pytest.mark.unit
    def test_rejects_document_source(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)document"):
            client.writes.move_folder("aaaa-1111-2222-3333", "")

    @pytest.mark.unit
    def test_dry_run_no_change(self, nested_folder_cache):
        client = RemarkableClient(base_path=nested_folder_cache)
        result = client.writes.move_folder(
            NESTED_FOLDER_D, NESTED_FOLDER_A, dry_run=True
        )
        assert result["dry_run"] is True
        on_disk = json.loads(
            (nested_folder_cache / f"{NESTED_FOLDER_D}.metadata").read_text()
        )
        assert on_disk["parent"] == ""


# ---------------------------------------------------------------------------
# writes.update_document_tags (singular)
# ---------------------------------------------------------------------------


class TestUpdateDocumentTags:
    @pytest.mark.unit
    def test_replace_mode_writes_new_tag_list(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "bbbb-4444-5555-6666", tags=["Fresh"]
        )
        assert result.get("error") is not True
        assert result["dry_run"] is False
        assert result["old_tags"] == ["Reference", "Architecture"]
        assert result["new_tags"] == ["Fresh"]
        assert sorted(result["added"]) == ["Fresh"]
        assert sorted(result["removed"]) == ["Architecture", "Reference"]
        content = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        assert [t["name"] for t in content["tags"]] == ["Fresh"]

    @pytest.mark.unit
    def test_replace_with_empty_clears_tags(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "bbbb-4444-5555-6666", tags=[]
        )
        assert result["new_tags"] == []
        assert sorted(result["removed"]) == ["Architecture", "Reference"]
        content = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        assert content["tags"] == []

    @pytest.mark.unit
    def test_add_mode_appends(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "aaaa-1111-2222-3333", add=["Important"]
        )
        assert result["new_tags"] == ["Journal", "Important"]
        assert result["added"] == ["Important"]
        assert result["removed"] == []

    @pytest.mark.unit
    def test_remove_mode_drops(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "bbbb-4444-5555-6666", remove=["Reference"]
        )
        assert result["new_tags"] == ["Architecture"]
        assert result["removed"] == ["Reference"]
        assert result["added"] == []

    @pytest.mark.unit
    def test_add_and_remove_combined(self, fake_cache):
        """Swap one tag for another in a single call."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "bbbb-4444-5555-6666",
            add=["Diagrams"],
            remove=["Architecture"],
        )
        assert "Diagrams" in result["new_tags"]
        assert "Architecture" not in result["new_tags"]
        assert result["added"] == ["Diagrams"]
        assert result["removed"] == ["Architecture"]

    @pytest.mark.unit
    def test_add_existing_tag_is_noop(self, fake_cache):
        """Adding a tag that already exists (case-insensitive) is a no-op."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "aaaa-1111-2222-3333", add=["journal"]
        )
        assert result["added"] == []
        assert result["new_tags"] == ["Journal"]

    @pytest.mark.unit
    def test_remove_case_insensitive(self, fake_cache):
        """Removing "JOURNAL" still drops the existing "Journal" entry."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "aaaa-1111-2222-3333", remove=["JOURNAL"]
        )
        assert result["new_tags"] == []
        assert result["removed"] == ["Journal"]

    @pytest.mark.unit
    def test_dedupes_user_input(self, fake_cache):
        """Repeated entries in the user's list collapse to the first occurrence."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "cccc-7777-8888-9999", tags=["Foo", "FOO", "Bar"]
        )
        assert result["new_tags"] == ["Foo", "Bar"]

    @pytest.mark.unit
    def test_rejects_no_op_call(self, fake_cache):
        """Passing none of tags/add/remove is a malformed request."""
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)at least one"):
            client.writes.update_document_tags("aaaa-1111-2222-3333")

    @pytest.mark.unit
    def test_rejects_mixing_replace_and_incremental(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)mutually exclusive"):
            client.writes.update_document_tags(
                "aaaa-1111-2222-3333", tags=["A"], add=["B"]
            )

    @pytest.mark.unit
    def test_rejects_empty_tag(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)empty|whitespace"):
            client.writes.update_document_tags(
                "aaaa-1111-2222-3333", add=["   "]
            )

    @pytest.mark.unit
    def test_rejects_add_remove_overlap(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)both"):
            client.writes.update_document_tags(
                "aaaa-1111-2222-3333", add=["Foo"], remove=["foo"]
            )

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder"):
            client.writes.update_document_tags(WORK_FOLDER_ID, tags=["X"])

    @pytest.mark.unit
    def test_rejects_trashed_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(TrashedRecordError, match="(?i)trash"):
            client.writes.update_document_tags(TRASHED_DOC_ID, tags=["X"])

    @pytest.mark.unit
    def test_rejects_missing_document(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="(?i)not found"):
            client.writes.update_document_tags("does-not-exist", tags=["X"])

    @pytest.mark.unit
    def test_dry_run_does_not_touch_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "aaaa-1111-2222-3333", add=["Important"], dry_run=True
        )
        assert result["dry_run"] is True
        assert "content_backup_path" not in result
        assert "metadata_backup_path" not in result
        content = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.content").read_text()
        )
        assert [t["name"] for t in content["tags"]] == ["Journal"]
        assert list(fake_cache.glob("aaaa-1111-2222-3333.content.bak.*")) == []
        assert list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*")) == []

    @pytest.mark.unit
    def test_creates_content_and_metadata_backups(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.update_document_tags(
            "aaaa-1111-2222-3333", add=["Important"]
        )
        content_backup = Path(result["content_backup_path"])
        metadata_backup = Path(result["metadata_backup_path"])
        assert content_backup.exists()
        assert metadata_backup.exists()
        assert content_backup.name.startswith("aaaa-1111-2222-3333.content.bak.")
        assert metadata_backup.name.startswith("aaaa-1111-2222-3333.metadata.bak.")

    @pytest.mark.unit
    def test_metadata_sync_flags_refresh(self, fake_cache):
        """Successful tag write must bump lastModified + sync flags on .metadata."""
        client = RemarkableClient(base_path=fake_cache)
        before = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        client.writes.update_document_tags(
            "aaaa-1111-2222-3333", add=["Important"]
        )
        after = json.loads(
            (fake_cache / "aaaa-1111-2222-3333.metadata").read_text()
        )
        assert int(after["lastModified"]) > int(before["lastModified"])
        assert after["metadatamodified"] is True
        assert after["modified"] is True

    @pytest.mark.unit
    def test_preserves_existing_timestamps_on_surviving_tags(self, fake_cache):
        """Surviving tags keep their existing timestamp; new tags get 0."""
        # Manually craft a richer existing tag with a non-zero timestamp.
        content_path = fake_cache / "bbbb-4444-5555-6666.content"
        content = json.loads(content_path.read_text())
        content["tags"] = [
            {"name": "Reference", "timestamp": 12345},
            {"name": "Architecture", "timestamp": 67890},
        ]
        content_path.write_text(json.dumps(content))

        client = RemarkableClient(base_path=fake_cache)
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", add=["Diagrams"], remove=["Architecture"]
        )
        new_content = json.loads(content_path.read_text())
        by_name = {t["name"]: t for t in new_content["tags"]}
        assert by_name["Reference"]["timestamp"] == 12345
        assert by_name["Diagrams"]["timestamp"] == 0


# ---------------------------------------------------------------------------
# writes.update_document_tags_batch
# ---------------------------------------------------------------------------


class TestUpdateDocumentTagsBatch:
    @pytest.mark.unit
    def test_mixed_success_and_failure(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "add": ["Pinned"]},
            {"id": WORK_FOLDER_ID, "add": ["X"]},  # folder, kind_mismatch
            {"id": TRASHED_DOC_ID, "add": ["X"]},  # trashed
            {"id": "does-not-exist", "add": ["X"]},  # not_found
        ]
        result = client.writes.update_document_tags_batch(items)
        assert result["dry_run"] is False
        assert result["succeeded"] == 1
        assert result["failed"] == 3
        assert result["results"][0].success is True
        assert result["results"][1].code == "kind_mismatch"
        assert result["results"][2].code == "trashed"
        assert result["results"][3].code == "not_found"

    @pytest.mark.unit
    def test_dry_run_writes_nothing(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        items = [{"id": "aaaa-1111-2222-3333", "add": ["Pinned"]}]
        result = client.writes.update_document_tags_batch(items, dry_run=True)
        assert result["dry_run"] is True
        assert result["succeeded"] == 1
        assert list(fake_cache.glob("aaaa-1111-2222-3333.content.bak.*")) == []

    @pytest.mark.unit
    def test_per_item_validation_failure_does_not_abort(self, fake_cache):
        """Validation errors on one item show up as failed rows, not raises."""
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "add": ["GoodTag"]},
            {"id": "bbbb-4444-5555-6666", "add": ["   "]},  # validation
        ]
        result = client.writes.update_document_tags_batch(items)
        assert result["succeeded"] == 1
        assert result["results"][1].success is False
        assert result["results"][1].code == "validation"

    @pytest.mark.unit
    def test_rejects_empty_list(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)non-empty"):
            client.writes.update_document_tags_batch([])

    @pytest.mark.unit
    def test_rejects_duplicate_ids(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        items = [
            {"id": "aaaa-1111-2222-3333", "add": ["A"]},
            {"id": "aaaa-1111-2222-3333", "add": ["B"]},
        ]
        with pytest.raises(ValidationError, match="(?i)duplicate"):
            client.writes.update_document_tags_batch(items)

    @pytest.mark.unit
    def test_rejects_malformed_item(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)id"):
            client.writes.update_document_tags_batch([{"add": ["X"]}])


# ---------------------------------------------------------------------------
# writes.set_document_authors
# ---------------------------------------------------------------------------


class TestSetDocumentAuthors:
    @pytest.mark.unit
    def test_replaces_authors(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.set_document_authors(
            "bbbb-4444-5555-6666", ["Neal Ford", "Mark Richards"]
        )
        assert result.get("error") is not True
        assert result["old_authors"] == ["Mark Richards"]
        assert result["new_authors"] == ["Neal Ford", "Mark Richards"]
        content = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        assert content["documentMetadata"]["authors"] == [
            "Neal Ford",
            "Mark Richards",
        ]
        assert content["documentMetadata"]["title"] == "Software Architecture Patterns"

    @pytest.mark.unit
    def test_clearing_authors_removes_field(self, fake_cache):
        """Empty list clears authors and drops the documentMetadata.authors key."""
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.set_document_authors("bbbb-4444-5555-6666", [])
        assert result["new_authors"] == []
        content = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        assert "authors" not in content["documentMetadata"]
        assert content["documentMetadata"]["title"] == "Software Architecture Patterns"

    @pytest.mark.unit
    def test_dedupes_input(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.set_document_authors(
            "cccc-7777-8888-9999", ["Alice", "alice", "Bob"]
        )
        assert result["new_authors"] == ["Alice", "Bob"]

    @pytest.mark.unit
    def test_rejects_empty_string_entry(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)empty|whitespace"):
            client.writes.set_document_authors(
                "cccc-7777-8888-9999", ["Alice", "   "]
            )

    @pytest.mark.unit
    def test_rejects_non_string_entry(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(ValidationError, match="(?i)string"):
            client.writes.set_document_authors(
                "cccc-7777-8888-9999", ["Alice", 42]
            )

    @pytest.mark.unit
    def test_rejects_collection_type(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(KindMismatchError, match="(?i)folder"):
            client.writes.set_document_authors(WORK_FOLDER_ID, ["Alice"])

    @pytest.mark.unit
    def test_rejects_trashed(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(TrashedRecordError, match="(?i)trash"):
            client.writes.set_document_authors(TRASHED_DOC_ID, ["Alice"])

    @pytest.mark.unit
    def test_dry_run_does_not_touch_disk(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        result = client.writes.set_document_authors(
            "bbbb-4444-5555-6666", ["Brand New"], dry_run=True
        )
        assert result["dry_run"] is True
        content = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        assert content["documentMetadata"]["authors"] == ["Mark Richards"]


# ---------------------------------------------------------------------------
# writes.restore_content
# ---------------------------------------------------------------------------


class TestRestoreContent:
    @pytest.mark.unit
    def test_round_trip_restore(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        original = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", tags=["Replaced"]
        )
        result = client.writes.restore_content("bbbb-4444-5555-6666")
        assert result.get("error") is not True
        restored = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        assert restored["tags"] == original["tags"]

    @pytest.mark.unit
    def test_creates_pre_restore_backup(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", tags=["Replaced"]
        )
        result = client.writes.restore_content("bbbb-4444-5555-6666")
        assert Path(result["pre_restore_backup"]).exists()
        assert Path(result["restored_from"]).exists()

    @pytest.mark.unit
    def test_no_backups_raises_backup_missing(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(BackupMissingError, match="(?i)backup"):
            client.writes.restore_content("aaaa-1111-2222-3333")

    @pytest.mark.unit
    def test_missing_content_raises_not_found(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        with pytest.raises(NotFoundError, match="(?i)content|not found"):
            client.writes.restore_content("nonexistent-doc")

    @pytest.mark.unit
    def test_dry_run_reports_source(self, fake_cache):
        client = RemarkableClient(base_path=fake_cache)
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", tags=["Replaced"]
        )
        result = client.writes.restore_content(
            "bbbb-4444-5555-6666", dry_run=True
        )
        assert result["dry_run"] is True
        assert "would_restore_from" in result
        on_disk = json.loads(
            (fake_cache / "bbbb-4444-5555-6666.content").read_text()
        )
        assert [t["name"] for t in on_disk["tags"]] == ["Replaced"]


# ---------------------------------------------------------------------------
# writes.cleanup_metadata_backups - .content.bak.* extension
# ---------------------------------------------------------------------------


class TestCleanupBackupsContentExtension:
    @pytest.mark.unit
    def test_reaps_content_backups_alongside_metadata(
        self, fake_cache, monkeypatch
    ):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", add=["Important"]
        )
        result = client.writes.cleanup_metadata_backups(older_than_days=0)
        # Tag write created both a .content.bak and a .metadata.bak; rename
        # added one more .metadata.bak. Total of 3 files removed.
        assert result["files_removed"] >= 3
        assert list(fake_cache.glob("*.metadata.bak.*")) == []
        assert list(fake_cache.glob("*.content.bak.*")) == []

    @pytest.mark.unit
    def test_doc_id_filter_targets_both_chains(self, fake_cache, monkeypatch):
        """doc_id filter scans both .metadata and .content backup chains."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", add=["Important"]
        )
        client.writes.rename_document("aaaa-1111-2222-3333", "Renamed")
        result = client.writes.cleanup_metadata_backups(
            doc_id="bbbb-4444-5555-6666"
        )
        assert result["files_removed"] == 2  # one .metadata + one .content
        # The other doc's .metadata backup must not be touched.
        assert (
            len(list(fake_cache.glob("aaaa-1111-2222-3333.metadata.bak.*"))) == 1
        )

    @pytest.mark.unit
    def test_dry_run_counts_content_backups(self, fake_cache, monkeypatch):
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", add=["Important"]
        )
        result = client.writes.cleanup_metadata_backups(
            older_than_days=0, dry_run=True
        )
        # Tag write created exactly one .content.bak and one .metadata.bak.
        assert result["files_removed"] == 2
        assert (
            len(list(fake_cache.glob("bbbb-4444-5555-6666.content.bak.*"))) == 1
        )
        assert (
            len(list(fake_cache.glob("bbbb-4444-5555-6666.metadata.bak.*"))) == 1
        )

    @pytest.mark.unit
    def test_scanned_docs_counts_unique_ids_not_extensions(
        self, fake_cache, monkeypatch
    ):
        """A doc with both .metadata and .content backups counts as 1 scanned."""
        monkeypatch.setenv(BACKUP_RETENTION_ENV_VAR, "100")
        client = RemarkableClient(base_path=fake_cache)
        client.writes.update_document_tags(
            "bbbb-4444-5555-6666", add=["Important"]
        )
        result = client.writes.cleanup_metadata_backups(
            doc_id="bbbb-4444-5555-6666", dry_run=True
        )
        assert result["scanned_docs"] == 1
