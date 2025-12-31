"""Simple CLI entry point."""

import json
import sys

from src.audit import run_audit


def main() -> None:
    """Run web audit and output JSON to stdout."""
    if len(sys.argv) != 2:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "Usage: src <url>",
                }
            )
        )
        sys.exit(1)

    url = sys.argv[1]

    # Ensure URL has protocol
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    result = run_audit(url)
    print(result.model_dump_json(indent=2, exclude_none=True))


if __name__ == "__main__":
    main()
