"""Lighthouse runner - runs mobile and desktop audits with browser pooling and parallel execution."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.errors.exceptions import AuditError, LighthouseNotFoundError
from app.schemas.audit import (
    CategoryScores,
    CoreWebVitals,
    LighthouseMetrics,
    LighthouseReport,
    Opportunity,
)
from app.services.browser_pool import BrowserPool

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    """Safely convert value to float or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _get_audit_value(
    audits: dict[str, Any], audit_id: str, key: str = "numericValue"
) -> float | None:
    """Extract a numeric value from Lighthouse audits."""
    audit = audits.get(audit_id)
    if not audit:
        return None
    return _safe_float(audit.get(key))


def _extract_metrics(lh_json: dict[str, Any]) -> LighthouseMetrics:
    """Extract important metrics from raw Lighthouse JSON."""
    categories = lh_json["categories"]
    audits = lh_json["audits"]

    scores = CategoryScores(
        performance=categories["performance"]["score"],
        accessibility=categories["accessibility"]["score"],
        best_practices=categories["best-practices"]["score"],
        seo=categories["seo"]["score"],
    )

    vitals = CoreWebVitals(
        lcp_ms=_get_audit_value(audits, "largest-contentful-paint"),
        cls=_get_audit_value(audits, "cumulative-layout-shift"),
        inp_ms=_get_audit_value(audits, "interaction-to-next-paint"),
        tbt_ms=_get_audit_value(audits, "total-blocking-time"),
    )

    opportunities: list[Opportunity] = []
    for audit_id, audit in audits.items():
        details = audit.get("details")
        if not details or details.get("type") != "opportunity":
            continue

        opportunities.append(
            Opportunity(
                id=audit_id,
                title=str(audit.get("title", "")),
                description=str(audit.get("description", "")),
                estimated_savings_ms=_safe_float(details.get("overallSavingsMs")),
            )
        )

    return LighthouseMetrics(
        categories=scores,
        vitals=vitals,
        opportunities=opportunities,
    )


def _check_lighthouse_available() -> None:
    """
    Check if Lighthouse CLI is available in PATH.

    Raises:
        LighthouseNotFoundError: If lighthouse is not installed or not in PATH.
    """
    if shutil.which("lighthouse") is None:
        raise LighthouseNotFoundError(
            "Lighthouse CLI not found in PATH. Install it with: npm install -g lighthouse"
        )


def _build_lighthouse_command(
    url: str,
    preset: str,
    output_path: Path,
    cdp_port: int | None = None,
) -> list[str]:
    """Build the Lighthouse CLI command."""
    if preset == "mobile":
        command = [
            "lighthouse",
            url,
            "--form-factor=mobile",
            "--output=json",
            f"--output-path={output_path}",
            "--quiet",
        ]
    else:  # desktop
        command = [
            "lighthouse",
            url,
            "--preset=desktop",
            "--output=json",
            f"--output-path={output_path}",
            "--quiet",
        ]

    # If CDP port provided, connect to existing browser instead of launching new one
    if cdp_port:
        command.append(f"--port={cdp_port}")
    else:
        command.append("--chrome-flags=--headless")

    return command


def _run_single_lighthouse_sync(
    url: str,
    preset: str,
    output_path: Path,
    timeout: float,
    cdp_port: int | None = None,
) -> None:
    """
    Run a single Lighthouse audit synchronously.

    Raises:
        subprocess.TimeoutExpired: If the audit times out.
        RuntimeError: If lighthouse returns a non-zero exit code.
    """
    command = _build_lighthouse_command(url, preset, output_path, cdp_port)

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Lighthouse failed ({preset}):\n{result.stderr}")


async def _run_single_lighthouse_async(
    url: str,
    preset: str,
    output_path: Path,
    timeout: float,
    cdp_port: int | None = None,
) -> LighthouseMetrics:
    """
    Run a single Lighthouse audit asynchronously.

    Returns extracted metrics for the specified strategy.
    """
    # Run subprocess in thread pool
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                _run_single_lighthouse_sync,
                url,
                preset,
                output_path,
                timeout,
                cdp_port,
            ),
            timeout=timeout + 5,  # Extra buffer for thread overhead
        )

        # Parse output
        with open(output_path) as f:
            lh_json = json.load(f)

        return _extract_metrics(lh_json)

    except TimeoutError:
        raise AuditError(f"{preset.capitalize()} audit timed out after {timeout}s")
    except subprocess.TimeoutExpired as e:
        raise AuditError(f"{preset.capitalize()} audit timed out after {e.timeout}s")
    except RuntimeError as e:
        raise AuditError(f"Lighthouse process failed ({preset}): {e}")
    except json.JSONDecodeError as e:
        raise AuditError(f"Failed to parse Lighthouse output ({preset}): {e}")
    except FileNotFoundError:
        raise AuditError(f"Lighthouse output file not found ({preset})")
    except KeyError as e:
        raise AuditError(f"Missing expected key in Lighthouse output ({preset}): {e}")
    except OSError as e:
        raise AuditError(f"OS error running Lighthouse ({preset}): {e}")


async def run_lighthouse_parallel(
    url: str,
    browser_pool: BrowserPool,
    timeout: float = 600.0,
    on_mobile_start: Callable[[], None] | None = None,
    on_mobile_complete: Callable[[], None] | None = None,
    on_desktop_start: Callable[[], None] | None = None,
    on_desktop_complete: Callable[[], None] | None = None,
) -> LighthouseReport:
    """
    Run Lighthouse audits for mobile and desktop in parallel using browser pooling.

    This is the primary entry point for parallel Lighthouse audits.

    Args:
        url: The URL to audit
        browser_pool: The browser pool to acquire browsers from
        timeout: Total timeout for both audits in seconds (default: 600)
        on_mobile_start: Callback when mobile audit starts
        on_mobile_complete: Callback when mobile audit completes
        on_desktop_start: Callback when desktop audit starts
        on_desktop_complete: Callback when desktop audit completes

    Returns:
        LighthouseReport with mobile and/or desktop metrics

    Raises:
        LighthouseNotFoundError: If lighthouse CLI is not installed
        AuditError: If both mobile and desktop audits fail
    """
    _check_lighthouse_available()

    # Allocate timeout between mobile and desktop (running in parallel, but use same timeout)
    single_audit_timeout = timeout / 2.0

    mobile_metrics: LighthouseMetrics | None = None
    desktop_metrics: LighthouseMetrics | None = None
    mobile_error: str | None = None
    desktop_error: str | None = None

    async def run_mobile(
        tmpdir: Path, cdp_port: int
    ) -> tuple[LighthouseMetrics | None, str | None]:
        """Run mobile audit and return (metrics, error)."""
        output_path = tmpdir / "lighthouse-mobile.json"
        try:
            if on_mobile_start:
                on_mobile_start()
            metrics = await _run_single_lighthouse_async(
                url, "mobile", output_path, single_audit_timeout, cdp_port
            )
            if on_mobile_complete:
                on_mobile_complete()
            return metrics, None
        except AuditError as e:
            return None, str(e)
        except (TimeoutError, subprocess.TimeoutExpired) as e:
            return None, f"Mobile audit timed out: {e}"
        except (
            RuntimeError,
            json.JSONDecodeError,
            FileNotFoundError,
            KeyError,
            OSError,
        ) as e:
            return None, f"Mobile audit failed: {e}"

    async def run_desktop(
        tmpdir: Path, cdp_port: int
    ) -> tuple[LighthouseMetrics | None, str | None]:
        """Run desktop audit and return (metrics, error)."""
        output_path = tmpdir / "lighthouse-desktop.json"
        try:
            if on_desktop_start:
                on_desktop_start()
            metrics = await _run_single_lighthouse_async(
                url, "desktop", output_path, single_audit_timeout, cdp_port
            )
            if on_desktop_complete:
                on_desktop_complete()
            return metrics, None
        except AuditError as e:
            return None, str(e)
        except (TimeoutError, subprocess.TimeoutExpired) as e:
            return None, f"Desktop audit timed out: {e}"
        except (
            RuntimeError,
            json.JSONDecodeError,
            FileNotFoundError,
            KeyError,
            OSError,
        ) as e:
            return None, f"Desktop audit failed: {e}"

    # Create temp directories for each audit
    with (
        tempfile.TemporaryDirectory() as mobile_tmpdir,
        tempfile.TemporaryDirectory() as desktop_tmpdir,
    ):
        mobile_path = Path(mobile_tmpdir)
        desktop_path = Path(desktop_tmpdir)

        # Acquire browsers and run audits in parallel
        async with (
            browser_pool.acquire() as mobile_browser,
            browser_pool.acquire() as desktop_browser,
        ):
            # Run both audits concurrently
            results = await asyncio.gather(
                run_mobile(mobile_path, mobile_browser.cdp_port),
                run_desktop(desktop_path, desktop_browser.cdp_port),
                return_exceptions=True,
            )

            # Process results - each result is either an Exception or (metrics, error) tuple
            mobile_result: tuple[LighthouseMetrics | None, str | None] | BaseException = results[0]
            desktop_result: tuple[LighthouseMetrics | None, str | None] | BaseException = results[1]

            if isinstance(mobile_result, BaseException):
                mobile_error = str(mobile_result)
            else:
                mobile_metrics, mobile_error = mobile_result

            if isinstance(desktop_result, BaseException):
                desktop_error = str(desktop_result)
            else:
                desktop_metrics, desktop_error = desktop_result

    # If both failed, raise an error
    if mobile_metrics is None and desktop_metrics is None:
        errors: list[str] = []
        if mobile_error:
            errors.append(f"Mobile: {mobile_error}")
        if desktop_error:
            errors.append(f"Desktop: {desktop_error}")
        error_msg = "Lighthouse audits failed for both mobile and desktop: " + "; ".join(errors)
        raise AuditError(error_msg)

    return LighthouseReport(mobile=mobile_metrics, desktop=desktop_metrics)


# Legacy synchronous functions for backward compatibility


def run_lighthouse_single(url: str, strategy: str, timeout: float = 300.0) -> LighthouseMetrics:
    """
    Run Lighthouse for a single strategy (mobile or desktop).

    This is the legacy synchronous API - prefer run_lighthouse_parallel for new code.

    Returns extracted metrics for the specified strategy.
    Raises AuditError if the audit fails.

    Args:
        url: The URL to audit
        strategy: "mobile" or "desktop"
        timeout: Timeout for this single audit in seconds (default: 300)

    Raises:
        LighthouseNotFoundError: If lighthouse CLI is not installed.
        AuditError: If the audit fails.
    """
    # Check lighthouse is available before starting
    _check_lighthouse_available()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        output_path = tmpdir_path / f"lighthouse-{strategy}.json"

        # Run the audit
        try:
            _run_single_lighthouse_sync(url, strategy, output_path, timeout)
            with open(output_path) as f:
                lh_json = json.load(f)
            return _extract_metrics(lh_json)
        except subprocess.TimeoutExpired as e:
            raise AuditError(f"{strategy.capitalize()} audit timed out after {e.timeout}s")
        except subprocess.CalledProcessError as e:
            raise AuditError(f"Lighthouse process failed ({strategy}): {e}")
        except json.JSONDecodeError as e:
            raise AuditError(f"Failed to parse Lighthouse output ({strategy}): {e}")
        except FileNotFoundError:
            raise AuditError(f"Lighthouse output file not found ({strategy})")
        except KeyError as e:
            raise AuditError(f"Missing expected key in Lighthouse output ({strategy}): {e}")
        except OSError as e:
            raise AuditError(f"OS error running Lighthouse ({strategy}): {e}")


def run_lighthouse(url: str, timeout: float = 600.0) -> LighthouseReport:
    """
    Run Lighthouse for mobile and desktop sequentially.

    This is the legacy synchronous API - prefer run_lighthouse_parallel for new code.

    Returns extracted metrics (not full raw JSON).
    Raises AuditError if both mobile and desktop audits fail.

    Args:
        url: The URL to audit
        timeout: Total timeout for both audits in seconds (default: 600)

    Raises:
        LighthouseNotFoundError: If lighthouse CLI is not installed.
        AuditError: If both mobile and desktop audits fail.
    """
    # Check lighthouse is available before starting
    _check_lighthouse_available()

    mobile_metrics: LighthouseMetrics | None = None
    desktop_metrics: LighthouseMetrics | None = None
    mobile_error: str | None = None
    desktop_error: str | None = None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        mobile_path = tmpdir_path / "lighthouse-mobile.json"
        desktop_path = tmpdir_path / "lighthouse-desktop.json"

        # Allocate timeout between mobile and desktop audits
        single_audit_timeout = timeout / 2.0

        # Run mobile audit
        try:
            _run_single_lighthouse_sync(url, "mobile", mobile_path, single_audit_timeout)
            with open(mobile_path) as f:
                mobile_json = json.load(f)
            mobile_metrics = _extract_metrics(mobile_json)
        except subprocess.TimeoutExpired as e:
            mobile_error = f"Mobile audit timed out after {e.timeout}s"
        except subprocess.CalledProcessError as e:
            mobile_error = f"Lighthouse process failed: {e}"
        except json.JSONDecodeError as e:
            mobile_error = f"Failed to parse Lighthouse output: {e}"
        except FileNotFoundError:
            mobile_error = "Lighthouse output file not found"
        except KeyError as e:
            mobile_error = f"Missing expected key in Lighthouse output: {e}"
        except OSError as e:
            mobile_error = f"OS error running Lighthouse: {e}"

        # Run desktop audit
        try:
            _run_single_lighthouse_sync(url, "desktop", desktop_path, single_audit_timeout)
            with open(desktop_path) as f:
                desktop_json = json.load(f)
            desktop_metrics = _extract_metrics(desktop_json)
        except subprocess.TimeoutExpired as e:
            desktop_error = f"Desktop audit timed out after {e.timeout}s"
        except subprocess.CalledProcessError as e:
            desktop_error = f"Lighthouse process failed: {e}"
        except json.JSONDecodeError as e:
            desktop_error = f"Failed to parse Lighthouse output: {e}"
        except FileNotFoundError:
            desktop_error = "Lighthouse output file not found"
        except KeyError as e:
            desktop_error = f"Missing expected key in Lighthouse output: {e}"
        except OSError as e:
            desktop_error = f"OS error running Lighthouse: {e}"

    # If both failed, raise an error
    if mobile_metrics is None and desktop_metrics is None:
        errors: list[str] = []
        if mobile_error:
            errors.append(f"Mobile: {mobile_error}")
        if desktop_error:
            errors.append(f"Desktop: {desktop_error}")
        error_msg = "Lighthouse audits failed for both mobile and desktop: " + "; ".join(errors)
        raise AuditError(error_msg)

    return LighthouseReport(mobile=mobile_metrics, desktop=desktop_metrics)
