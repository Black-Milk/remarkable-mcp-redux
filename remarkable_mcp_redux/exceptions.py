# ABOUTME: Typed exception hierarchy raised by facades; converted to ToolError envelopes at the
# ABOUTME: tools/ boundary so MCP clients keep seeing the {"error": True, "detail": ...} wire shape.

from __future__ import annotations


class RemarkableError(Exception):
    """Base for every typed failure raised by the facade layer.

    Phase 4 replaced the legacy ``return {"error": True, ...}`` envelope
    pattern with raise-and-catch: facades raise these classes, the
    ``@tool_error_boundary`` decorator in ``tools/_boundary.py`` catches them
    and serializes a ``ToolError`` envelope. The envelope still carries
    ``error: True`` and ``detail: <message>`` for backward compatibility, plus
    the new optional ``code`` field driven by the per-class ``code`` constant
    below — clients can branch on a stable identifier instead of grepping the
    detail string.

    Subclasses set the ``code`` class attribute. Callers that only need a
    human-readable message keep using ``str(exc)`` (it returns ``detail``).
    """

    code: str = "remarkable_error"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class NotFoundError(RemarkableError):
    """A targeted record, metadata file, or backup file does not exist on disk."""

    code = "not_found"


class KindMismatchError(RemarkableError):
    """Operation invoked against the wrong record type.

    Raised when a document tool receives a CollectionType id (or vice versa).
    The detail message steers callers to the correct dedicated tool.
    """

    code = "kind_mismatch"


class ValidationError(RemarkableError):
    """Caller supplied invalid arguments.

    Covers empty/whitespace names, non-positive limits, negative offsets,
    empty ``page_indices`` lists, missing required filters, and
    structurally-invalid moves (e.g. into 'trash', into self).
    """

    code = "validation"


class TrashedRecordError(RemarkableError):
    """The targeted record exists but is currently in the trash (deleted=True).

    Distinct from ``NotFoundError`` because the record can be revived from the
    reMarkable app — the failure is recoverable, just not via these tools.
    """

    code = "trashed"


class ConflictError(RemarkableError):
    """A precondition collides with existing state.

    Today: sibling-name uniqueness on rename/create_folder. Future use cases
    (concurrent backup writes, lock contention) plug in here.
    """

    code = "conflict"


class BackupMissingError(RemarkableError):
    """``restore_metadata`` was asked to roll back a record with no backup chain."""

    code = "backup_missing"


__all__ = [
    "BackupMissingError",
    "ConflictError",
    "KindMismatchError",
    "NotFoundError",
    "RemarkableError",
    "TrashedRecordError",
    "ValidationError",
]
