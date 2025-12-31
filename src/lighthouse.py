"""Lighthouse runner - runs mobile and desktop audits."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from src.errors import AuditError
from src.models import (
    CategoryScores,
    CoreWebVitals,
    LighthouseMetrics,
    LighthouseReport,
    Opportunity,
)


def _get_audit_value(
    audits: Dict[str, Any], audit_id: str, key: str = "numericValue"
) -> Optional[float]:
    """Extract a value from Lighthouse audits."""
    audit = audits.get(audit_id)
    if not audit:
        return None
    return cast(Optional[float], audit.get(key))


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
                title=cast(str, audit.get("title", "")),
                description=cast(str, audit.get("description", "")),
                estimated_savings_ms=cast(
                    Optional[float], details.get("overallSavingsMs")
                ),
            )
        )

    return LighthouseMetrics(
        categories=scores,
        vitals=vitals,
        opportunities=opportunities,
    )


def _run_single_lighthouse(
    url: str, preset: str, output_path: Path, timeout: float
) -> None:
    """Run a single Lighthouse audit."""
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
    """
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
        except Exception as e:
            mobile_error = str(e)

        # Run desktop audit
        try:
            _run_single_lighthouse(url, "desktop", desktop_path, single_audit_timeout)
            with open(desktop_path) as f:
                desktop_json = json.load(f)
            desktop_metrics = _extract_metrics(desktop_json)
        except Exception as e:
            desktop_error = str(e)

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
