"""Audit endpoints."""

from fastapi import APIRouter, HTTPException

from app.core.audit import run_audit
from app.errors.exceptions import AuditError, LighthouseNotFoundError, ValidationError
from app.schemas.audit import AuditRequest, AuditResponse
from app.services.validators import validate_url

router = APIRouter()


@router.post("/audit", response_model=AuditResponse)
async def create_audit(request: AuditRequest) -> AuditResponse:
    """
    Run a web performance audit for the given URL.

    Returns comprehensive audit data including:
    - Lighthouse metrics (mobile + desktop)
    - CrUX field data (if available)
    - AI-generated insights and recommendations
    """
    try:
        # Validate and normalize URL
        validated_url = validate_url(request.url)

        # Run the audit
        result = run_audit(
            url=validated_url,
            timeout=float(request.timeout or 600),
            no_cache=request.no_cache or False,
        )

        return result

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LighthouseNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=str(e),
        )
    except AuditError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
