"""FastAPI application entrypoint with lifecycle management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.services.browser_pool import BrowserPool
from app.services.concurrency import ConcurrencyManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def cleanup_idle_browsers_task(browser_pool: BrowserPool) -> None:
    """Background task to periodically clean up idle browsers."""
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            closed = await browser_pool.cleanup_idle()
            if closed > 0:
                logger.info(f"Cleaned up {closed} idle browser(s)")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in browser cleanup task: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan manager.

    Handles startup and shutdown of browser pool and concurrency manager.
    """
    logger.info("Starting up Web Audit API...")

    # Initialize concurrency manager (this also initializes the queue)
    concurrency_manager = ConcurrencyManager.get_instance()

    # Recover any jobs that were processing when we crashed
    requeued = concurrency_manager.recover_from_crash()
    if requeued > 0:
        logger.info(f"Recovered {requeued} job(s) from previous run")

    # Initialize browser pool (lazy - doesn't launch browsers yet)
    browser_pool = BrowserPool.get_instance()
    await browser_pool.initialize()

    # Start background cleanup task
    cleanup_task = asyncio.create_task(cleanup_idle_browsers_task(browser_pool))

    logger.info("Web Audit API started successfully")
    logger.info(
        f"Concurrency: max {concurrency_manager.max_concurrent} audits, "
        f"queue max {concurrency_manager.queue.max_size}"
    )

    try:
        yield
    finally:
        logger.info("Shutting down Web Audit API...")

        # Cancel cleanup task
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        # Shutdown browser pool
        await browser_pool.shutdown()

        logger.info("Web Audit API shutdown complete")


app = FastAPI(
    title="Web Audit API",
    description="API for running comprehensive web performance audits using Lighthouse, CrUX, and AI analysis",
    version="0.1.0",
    lifespan=lifespan,
)

# Include API v1 routes
app.include_router(v1_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "name": "Web Audit API",
        "version": "0.1.0",
        "docs": "/docs",
    }
