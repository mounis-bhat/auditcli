"""Lighthouse runner - runs mobile and desktop audits."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, cast

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


def _run_single_lighthouse(url: str, preset: str, output_path: Path) -> None:
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
    )

    if result.returncode != 0:
        raise RuntimeError(f"Lighthouse failed ({preset}):\n{result.stderr}")


def run_lighthouse(url: str) -> LighthouseReport:
    """
    Run Lighthouse for mobile and desktop.
    Returns extracted metrics (not full raw JSON).
    """
    mobile_metrics: Optional[LighthouseMetrics] = None
    desktop_metrics: Optional[LighthouseMetrics] = None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        mobile_path = tmpdir_path / "lighthouse-mobile.json"
        desktop_path = tmpdir_path / "lighthouse-desktop.json"

        # Run mobile audit
        try:
            _run_single_lighthouse(url, "mobile", mobile_path)
            with open(mobile_path) as f:
                mobile_json = json.load(f)
            mobile_metrics = _extract_metrics(mobile_json)
        except Exception:
            pass  # mobile_metrics stays None

        # Run desktop audit
        try:
            _run_single_lighthouse(url, "desktop", desktop_path)
            with open(desktop_path) as f:
                desktop_json = json.load(f)
            desktop_metrics = _extract_metrics(desktop_json)
        except Exception:
            pass  # desktop_metrics stays None

    return LighthouseReport(mobile=mobile_metrics, desktop=desktop_metrics)
