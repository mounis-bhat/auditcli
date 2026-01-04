"""Health check endpoints with database connectivity verification."""

from typing import Any, Dict

from fastapi import APIRouter

from app.services.cache import check_database_connection, get_cache_stats
from app.services.circuit_breaker import get_all_circuit_breaker_stats

router = APIRouter()


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Basic health check endpoint.

    Returns overall health status based on critical component checks.
    """
    # Check database connectivity
    db_status = check_database_connection()

    # Determine overall health
    is_healthy = db_status["connected"]

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "database": {
            "connected": db_status["connected"],
            "error": db_status["error"],
        },
    }


@router.get("/health/detailed")
async def detailed_health_check() -> Dict[str, Any]:
    """
    Detailed health check with all component statuses.

    Includes database connectivity, cache stats, and circuit breaker states.
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

    # Determine overall health
    is_healthy = db_status["connected"]

    # Check if any circuit breakers are open
    circuits_open = any(
        stats.state.value == "open" for stats in circuit_breakers.values()
    )

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "degraded": circuits_open,  # True if any circuit is open
        "components": {
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
        },
    }


@router.get("/ready")
async def readiness_check() -> Dict[str, Any]:
    """
    Kubernetes-style readiness probe.

    Returns 200 if the service is ready to accept traffic.
    Checks that the database is connected and accessible.
    """
    db_status = check_database_connection()

    if not db_status["connected"]:
        # Return 503 Service Unavailable via exception
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "reason": f"Database not connected: {db_status['error']}",
            },
        )

    return {"ready": True}


@router.get("/live")
async def liveness_check() -> Dict[str, bool]:
    """
    Kubernetes-style liveness probe.

    Always returns 200 if the service is running.
    This is a simple ping that doesn't check dependencies.
    """
    return {"alive": True}
