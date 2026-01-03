"""Cache management routes."""

from fastapi import APIRouter
from typing import Dict, Any

from app.services.cache import clear_cache, cleanup_expired, get_cache_stats

router: APIRouter = APIRouter()


@router.get("/cache/stats")
async def get_cache_stats_endpoint() -> Dict[str, Any]:
    """Get cache statistics."""
    return get_cache_stats()


@router.post("/cache/cleanup")
async def cleanup_expired_cache_endpoint() -> Dict[str, Any]:
    """Remove expired entries from cache."""
    removed_count = cleanup_expired()
    return {
        "message": "Expired cache entries cleaned up successfully",
        "removed_count": removed_count,
    }


@router.delete("/cache")
async def clear_cache_endpoint() -> Dict[str, str]:
    """Clear all cache entries."""
    clear_cache()
    return {"message": "Cache cleared successfully"}
