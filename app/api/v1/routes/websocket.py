"""WebSocket endpoint for real-time audit status updates."""

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.v1.deps import get_job_store
from app.services.jobs import JobStore
from app.services.websocket import websocket_manager

router = APIRouter()


@router.websocket("/audit/{job_id}")
async def audit_websocket(
    websocket: WebSocket,
    job_id: str,
    job_store: JobStore = Depends(get_job_store),  # noqa: B008
):
    """WebSocket endpoint for real-time audit status updates."""
    # Validate job exists
    job = job_store.get_job(job_id)
    if not job:
        await websocket.close(code=1008)  # Policy violation
        return

    # Accept connection
    await websocket.accept()

    # Add to manager
    await websocket_manager.connect(job_id, websocket)

    try:
        # Keep connection alive, but since we broadcast, no need to listen
        # Clients can send messages if needed in future
        while True:
            await websocket.receive_text()
            # For now, ignore incoming messages
            pass
    except WebSocketDisconnect:
        pass
    finally:
        # Remove from manager
        websocket_manager.disconnect(job_id, websocket)
