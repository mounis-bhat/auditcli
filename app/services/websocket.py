"""WebSocket connection manager for real-time audit status updates."""

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from fastapi import WebSocket


class WebSocketManager:
    """Manages WebSocket connections for real-time audit updates."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.connections: Dict[str, List[WebSocket]] = {}
        self.broadcast_queue: asyncio.Queue[Tuple[str, str, int, str]] = asyncio.Queue()
        self._broadcast_task: asyncio.Task[None] | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get_instance(cls) -> "WebSocketManager":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        """Add WebSocket connection for a job."""
        with self._lock:
            if job_id not in self.connections:
                self.connections[job_id] = []
            self.connections[job_id].append(websocket)
            if self.loop is None:
                self.loop = asyncio.get_running_loop()

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        """Remove WebSocket connection for a job."""
        with self._lock:
            if job_id in self.connections:
                try:
                    self.connections[job_id].remove(websocket)
                except ValueError:
                    pass  # Already removed
                if not self.connections[job_id]:
                    del self.connections[job_id]

    def enqueue_broadcast(
        self, job_id: str, stage: str, progress: int, status: str
    ) -> None:
        """Enqueue a broadcast message to be sent asynchronously."""
        if self.loop and self.loop.is_running():
            # Schedule in the main event loop from any context
            asyncio.run_coroutine_threadsafe(
                self._enqueue_async(job_id, stage, progress, status), self.loop
            )
        else:
            # Fallback: try create_task if we're in an async context
            try:
                asyncio.create_task(
                    self._enqueue_async(job_id, stage, progress, status)
                )
            except RuntimeError:
                # No event loop, discard (shouldn't happen if loop is set)
                pass

    async def _enqueue_async(
        self, job_id: str, stage: str, progress: int, status: str
    ) -> None:
        """Async helper to enqueue broadcast."""
        await self.broadcast_queue.put((job_id, stage, progress, status))
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._process_broadcasts())

    async def _process_broadcasts(self) -> None:
        """Process queued broadcasts."""
        while True:
            try:
                job_id, stage, progress, status = await asyncio.wait_for(
                    self.broadcast_queue.get(), timeout=1.0
                )
                await self.broadcast(job_id, stage, progress, status)
            except asyncio.TimeoutError:
                # No more items, check if we should stop
                if self.broadcast_queue.empty():
                    break
            except Exception:
                # Log error but continue
                continue

    async def broadcast(
        self, job_id: str, stage: str, progress: int, status: str
    ) -> None:
        """Broadcast status update to all connected clients for a job."""
        message: Dict[str, Any] = {
            "stage": stage,
            "progress": progress,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            if job_id in self.connections:
                disconnected: List[WebSocket] = []
                for websocket in self.connections[job_id]:
                    try:
                        await websocket.send_json(message)
                    except Exception:
                        # Mark for removal if send fails
                        disconnected.append(websocket)
                # Remove disconnected websockets
                for ws in disconnected:
                    try:
                        self.connections[job_id].remove(ws)
                    except ValueError:
                        pass
                if not self.connections[job_id]:
                    del self.connections[job_id]


# Global instance
websocket_manager = WebSocketManager.get_instance()
