"""Custom exception classes for audit application."""


class AuditError(Exception):
    """Base exception for audit failures."""

    pass


class APIError(AuditError):
    """Exception for external API failures (Gemini, PSI)."""

    pass


class ValidationError(AuditError):
    """Exception for input validation failures."""

    pass


class LighthouseNotFoundError(AuditError):
    """Raised when Lighthouse CLI is not found in PATH."""

    pass


class PlaywrightBrowsersNotInstalledError(AuditError):
    """Raised when Playwright browser binaries are not installed."""

    pass
