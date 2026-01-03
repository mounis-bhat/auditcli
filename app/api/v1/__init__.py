"""API v1 package."""

from fastapi import APIRouter

from app.api.v1.routes import audits, cache, health, websocket

router = APIRouter(prefix="/v1")
router.include_router(health.router, tags=["health"])
router.include_router(audits.router, tags=["audits"])
router.include_router(cache.router, tags=["cache"])
router.include_router(websocket.router, tags=["websocket"])
