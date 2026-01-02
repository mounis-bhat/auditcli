"""URL validation utilities."""

import re
from urllib.parse import urlparse

from app.errors.exceptions import ValidationError


def validate_url(url: str) -> str:
    """
    Validate and normalize URL.
    Returns normalized URL or raises ValidationError.
    """
    if not url:
        raise ValidationError("URL is required and must be a non-empty string")

    # Remove leading/trailing whitespace
    url = url.strip()

    # Add protocol if missing (only if no protocol at all)
    if "://" not in url:
        url = f"https://{url}"

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValidationError(f"Invalid URL format: {str(e)}")

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("URL must use http or https protocol")

    # Validate netloc (domain)
    if not parsed.netloc:
        raise ValidationError("URL must include a valid domain")

    # Basic domain validation (must have at least one dot, no spaces)
    if "." not in parsed.netloc or " " in parsed.netloc:
        raise ValidationError("URL domain appears to be invalid")

    # Extract hostname without port for validation
    hostname = parsed.netloc.split(":")[0] if ":" in parsed.netloc else parsed.netloc

    # Validate port if present
    if ":" in parsed.netloc:
        port_str = parsed.netloc.split(":")[-1]
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValidationError(f"Port {port} is out of valid range (1-65535)")
        except ValueError:
            raise ValidationError(f"Invalid port: {port_str}")

    # Check for localhost/IP addresses (basic validation)
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
        # Allow localhost for development
        pass
    else:
        # Basic check that it looks like a domain (not just IP without validation)
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", hostname):
            # It's an IP address, basic validation
            pass
        elif not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", hostname):
            raise ValidationError("URL domain format appears invalid")

    return url
