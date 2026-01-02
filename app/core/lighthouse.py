"""Lighthouse runner - runs mobile and desktop audits."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.errors.exceptions import AuditError, LighthouseNotFoundError
from app.schemas.audit import (
    CategoryScores,
    CoreWebVitals,
    LighthouseMetrics,
    LighthouseReport,
    Opportunity,
)


def _safe_float(value: Any) -> Optional[float]:
    """Safely convert value to float or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _get_audit_value(
    audits: Dict[str, Any], audit_id: str, key: str = "numericValue"
) -> Optional[float]:
    """Extract a numeric value from Lighthouse audits."""
    audit = audits.get(audit_id)
    if not audit:
        return None
    return _safe_float(audit.get(key))


def _extract_metrics(lh_json: Dict[str, Any]) -> LighthouseMetrics:
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
            "Lighthouse CLI not found in PATH. "
            "Install it with: npm install -g lighthouse"
        )


def _run_single_lighthouse(
    url: str, preset: str, output_path: Path, timeout: float
) -> None:
    """
    Run a single Lighthouse audit.

    Raises:
        subprocess.TimeoutExpired: If the audit times out.
        RuntimeError: If lighthouse returns a non-zero exit code.
    """
    if preset == "mobile":
        command = [
            "lighthouse",
            url,
            "--form-factor=mobile",
            "--output=json",
            f"--output-path={output_path}",
            "--quiet",
            "--chrome-flags=--headless",
        ]
    else:  # desktop
        command = [
            "lighthouse",
            url,
            "--preset=desktop",
            "--output=json",
            f"--output-path={output_path}",
            "--quiet",
            "--chrome-flags=--headless",
        ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Lighthouse failed ({preset}):\n{result.stderr}")


def run_lighthouse(url: str, timeout: float = 600.0) -> LighthouseReport:
    """
    Run Lighthouse for mobile and desktop.

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

    mobile_metrics: Optional[LighthouseMetrics] = None
    desktop_metrics: Optional[LighthouseMetrics] = None
    mobile_error: Optional[str] = None
    desktop_error: Optional[str] = None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        mobile_path = tmpdir_path / "lighthouse-mobile.json"
        desktop_path = tmpdir_path / "lighthouse-desktop.json"

        # Allocate timeout between mobile and desktop audits
        single_audit_timeout = timeout / 2.0

        # Run mobile audit
        try:
            _run_single_lighthouse(url, "mobile", mobile_path, single_audit_timeout)
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
            _run_single_lighthouse(url, "desktop", desktop_path, single_audit_timeout)
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
        errors: List[str] = []
        if mobile_error:
            errors.append(f"Mobile: {mobile_error}")
        if desktop_error:
            errors.append(f"Desktop: {desktop_error}")
        error_msg = (
            "Lighthouse audits failed for both mobile and desktop: " + "; ".join(errors)
        )
        raise AuditError(error_msg)

    return LighthouseReport(mobile=mobile_metrics, desktop=desktop_metrics)
