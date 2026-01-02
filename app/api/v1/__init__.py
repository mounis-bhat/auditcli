"""API v1 package."""

from fastapi import APIRouter

from app.api.v1.routes import audits, health

router = APIRouter(prefix="/v1")
router.include_router(health.router, tags=["health"])
router.include_router(audits.router, tags=["audits"])
