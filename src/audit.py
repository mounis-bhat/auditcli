"""Main audit orchestration."""

from src.ai import generate_ai_report
from src.lighthouse import run_lighthouse
from src.models import AuditResponse, Insights, LighthouseReport, Status
from src.psi import fetch_crux


def run_audit(url: str) -> AuditResponse:
    """
    Run a complete web audit for the given URL.

    Always attempts:
    - Lighthouse (mobile + desktop)
    - CrUX field data
    - AI analysis

    Returns structured response with status indicating success/partial/failed.
    """
    # Run Lighthouse
    lighthouse: LighthouseReport = run_lighthouse(url)

    # Check if Lighthouse completely failed
    lighthouse_failed = lighthouse.mobile is None and lighthouse.desktop is None

    if lighthouse_failed:
        return AuditResponse(
            status=Status.FAILED,
            url=url,
            lighthouse=lighthouse,
            crux=None,
            insights=Insights(metrics=lighthouse, ai_report=None),
            error="Lighthouse failed to run for both mobile and desktop",
        )

    # Fetch CrUX data
    crux = fetch_crux(url)

    # Generate AI report
    ai_report = generate_ai_report(url, lighthouse, crux)

    # Determine status
    # - SUCCESS: Everything worked
    # - PARTIAL: Lighthouse worked but CrUX or AI failed
    all_succeeded = (
        lighthouse.mobile is not None
        and lighthouse.desktop is not None
        and crux is not None
        and ai_report is not None
    )

    status = Status.SUCCESS if all_succeeded else Status.PARTIAL

    return AuditResponse(
        status=status,
        url=url,
        lighthouse=lighthouse,
        crux=crux,
        insights=Insights(metrics=lighthouse, ai_report=ai_report),
    )
