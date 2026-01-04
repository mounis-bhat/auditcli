"""Cache management routes."""

from typing import Any

from fastapi import APIRouter

from app.services.cache import cleanup_expired, clear_cache, get_cache_stats

router: APIRouter = APIRouter()


@router.get("/cache/stats")
async def get_cache_stats_endpoint() -> dict[str, Any]:
    """Get cache statistics."""
    return get_cache_stats()


@router.post("/cache/cleanup")
async def cleanup_expired_cache_endpoint() -> dict[str, Any]:
    """Remove expired entries from cache."""
    removed_count = cleanup_expired()
    return {
        "message": "Expired cache entries cleaned up successfully",
        "removed_count": removed_count,
    }


@router.delete("/cache")
async def clear_cache_endpoint() -> dict[str, str]:
    """Clear all cache entries."""
    clear_cache()
    return {"message": "Cache cleared successfully"}
