"""Simple CLI entry point."""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv
from src.audit import run_audit
from src.errors import AuditError, APIError, ValidationError


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

    # Check for localhost/IP addresses (basic validation)
    if parsed.netloc in ("localhost", "127.0.0.1", "0.0.0.0"):
        # Allow localhost for development
        pass
    else:
        # Basic check that it looks like a domain (not just IP without validation)
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", parsed.netloc):
            # It's an IP address, basic validation
            pass
        elif not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", parsed.netloc):
            raise ValidationError("URL domain format appears invalid")

    return url


def validate_api_keys() -> None:
    """
    Validate required API keys on startup.
    Raises ValidationError if keys are missing or malformed.
    """
    # Check PSI API key
    psi_key = os.getenv("PSI_API_KEY")
    if not psi_key or not psi_key.strip():
        raise ValidationError(
            "PSI_API_KEY environment variable is required and must be non-empty"
        )

    # Basic format validation (should be reasonably long API key)
    if len(psi_key.strip()) < 10:
        raise ValidationError("PSI_API_KEY appears to be too short or malformed")

    # Check Google API key
    google_key = os.getenv("GOOGLE_API_KEY")
    if not google_key or not google_key.strip():
        raise ValidationError(
            "GOOGLE_API_KEY environment variable is required and must be non-empty"
        )

    # Basic format validation (should be reasonably long API key)
    if len(google_key.strip()) < 10:
        raise ValidationError("GOOGLE_API_KEY appears to be too short or malformed")


def main() -> None:
    """Run web audit and output JSON to stdout."""
    parser = argparse.ArgumentParser(description="Web audit CLI tool")
    parser.add_argument("url", nargs="?", help="URL to audit")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate inputs without running audit",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Audit timeout in seconds (default: 600 = 10 minutes)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip cache check and don't store results",
    )

    args = parser.parse_args()

    try:
        # Load environment variables from .env file
        load_dotenv()

        # Validate API keys on startup
        validate_api_keys()

        if args.validate_only:
            # Pre-flight validation only
            if not args.url:
                raise ValidationError("URL is required when using --validate-only")
            validated_url = validate_url(args.url)
            print(
                json.dumps(
                    {
                        "status": "success",
                        "message": "Validation successful",
                        "validated_url": validated_url,
                    }
                )
            )
            return

        # Normal audit mode
        if not args.url:
            raise ValidationError("URL is required")

        url = validate_url(args.url)

        result = run_audit(url, timeout=args.timeout, no_cache=args.no_cache)
        print(result.model_dump_json(indent=2, exclude_none=True))

    except ValidationError as e:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": f"Validation error: {str(e)}",
                }
            )
        )
        sys.exit(1)
    except (AuditError, APIError) as e:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(e),
                }
            )
        )
        sys.exit(1)
    except Exception as e:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": f"Unexpected error: {str(e)}",
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
