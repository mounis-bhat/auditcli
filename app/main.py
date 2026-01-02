"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.v1 import router as v1_router

app = FastAPI(
    title="Web Audit API",
    description="API for running comprehensive web performance audits using Lighthouse, CrUX, and AI analysis",
    version="0.1.0",
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
