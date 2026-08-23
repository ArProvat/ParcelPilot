"""Exceptions for workbook and document ingestion."""


class IngestionError(Exception):
    """Base exception for all ingestion errors."""
    pass


class WorkbookStructureError(IngestionError):
    """Raised when an Excel workbook has missing sheets, malformed headers, or missing metadata."""
    pass


class RelationalIntegrityError(IngestionError):
    """Raised when referential integrity between entities (e.g. account_id) is violated."""
    pass


class BusinessInvariantError(IngestionError):
    """Raised when domain business invariants (e.g. negative fees, invalid time windows) are violated."""
    pass
