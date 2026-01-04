"""Health check endpoints with database connectivity verification."""

from typing import Any, Dict

from fastapi import APIRouter

from app.services.cache import check_database_connection, get_cache_stats
from app.services.circuit_breaker import get_all_circuit_breaker_stats

router = APIRouter()


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Comprehensive health check endpoint.

    Returns overall health status including database connectivity, cache stats,
    circuit breaker states, readiness, and liveness information.
    """
    # Check database connectivity
    db_status = check_database_connection()

    # Get cache statistics
    cache_stats = get_cache_stats()

    # Get circuit breaker states
    circuit_breakers = get_all_circuit_breaker_stats()

    # Format circuit breaker info
    cb_info = {}
    for name, stats in circuit_breakers.items():
        cb_info[name] = {
            "state": stats.state.value,
            "consecutive_failures": stats.consecutive_failures,
            "total_calls": stats.total_calls,
            "total_failures": stats.total_failures,
            "total_successes": stats.total_successes,
            "time_in_current_state_seconds": round(stats.time_in_current_state, 2),
        }

    # Determine overall health and readiness
    is_healthy = db_status["connected"]
    is_ready = db_status["connected"]

    # Check if any circuit breakers are open (degraded state)
    circuits_open = any(
        stats.state.value == "open" for stats in circuit_breakers.values()
    )

    # If database is not connected, raise 503 (maintaining readiness probe behavior)
    if not is_ready:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "ready": False,
                "alive": True,
                "degraded": circuits_open,
                "database": {
                    "status": "unhealthy",
                    "connected": db_status["connected"],
                    "path": db_status["path"],
                    "integrity": db_status["integrity"],
                    "journal_mode": db_status["journal_mode"],
                    "error": db_status["error"],
                },
                "reason": f"Database not connected: {db_status['error']}",
            },
        )

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "ready": is_ready,
        "alive": True,
        "degraded": circuits_open,  # True if any circuit is open
        "database": {
            "status": "healthy" if db_status["connected"] else "unhealthy",
            "connected": db_status["connected"],
            "path": db_status["path"],
            "integrity": db_status["integrity"],
            "journal_mode": db_status["journal_mode"],
            "error": db_status["error"],
        },
        "cache": {
            "status": "healthy",
            "total_entries": cache_stats["total_entries"],
            "valid_entries": cache_stats["valid_entries"],
            "hit_rate_percent": cache_stats["metrics"]["hit_rate_percent"],
            "active_url_locks": cache_stats["url_locking"]["active_locks"],
        },
        "circuit_breakers": cb_info,
    }
