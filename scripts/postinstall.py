#!/usr/bin/env python3
"""Post-installation script to set up Playwright browsers."""

import subprocess
import sys


def main() -> int:
    """Install Playwright browsers (Chromium) after package installation."""
    print("Installing Playwright browsers...")
    print("This may take a few minutes on first run.")

    try:
        # Install all Playwright browsers to ensure compatibility
        _result = subprocess.run(
            [sys.executable, "-m", "playwright", "install"],
            check=True,
            capture_output=False,
        )
        print("Playwright Chromium installed successfully!")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Failed to install Playwright browsers: {e}", file=sys.stderr)
        print(
            "You can manually install by running: playwright install chromium",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError:
        print(
            "Playwright not found. Make sure you've installed the package dependencies.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
