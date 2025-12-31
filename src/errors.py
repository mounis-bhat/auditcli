"""Custom exception classes for audit CLI."""


class AuditError(Exception):
    """Base exception for audit failures."""

    pass


class APIError(AuditError):
    """Exception for external API failures (Gemini, PSI)."""

    pass


class ValidationError(AuditError):
    """Exception for input validation failures."""

    pass
