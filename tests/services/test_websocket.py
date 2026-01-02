"""Tests for WebSocket functionality."""

import pytest
from unittest.mock import AsyncMock

from app.services.websocket import WebSocketManager


class TestWebSocketManager:
    def test_singleton(self):
        manager1 = WebSocketManager.get_instance()
        manager2 = WebSocketManager.get_instance()
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        manager = WebSocketManager()
        mock_ws = AsyncMock()
        job_id = "test-job"

        await manager.connect(job_id, mock_ws)
        assert job_id in manager.connections
        assert mock_ws in manager.connections[job_id]

        manager.disconnect(job_id, mock_ws)
        assert job_id not in manager.connections

    @pytest.mark.asyncio
    async def test_broadcast(self):
        manager = WebSocketManager()
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        job_id = "test-job"

        await manager.connect(job_id, mock_ws1)
        await manager.connect(job_id, mock_ws2)

        await manager.broadcast(job_id, "lighthouse_mobile", 25, "running")

        mock_ws1.send_json.assert_called_once()
        mock_ws2.send_json.assert_called_once()

        call_args = mock_ws1.send_json.call_args[0][0]
        assert call_args["stage"] == "lighthouse_mobile"
        assert call_args["progress"] == 25
        assert call_args["status"] == "running"
        assert "timestamp" in call_args

    @pytest.mark.asyncio
    async def test_broadcast_disconnect_failed(self):
        manager = WebSocketManager()
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws2.send_json.side_effect = Exception("Disconnected")
        job_id = "test-job"

        await manager.connect(job_id, mock_ws1)
        await manager.connect(job_id, mock_ws2)

        await manager.broadcast(job_id, "stage", 50, "status")

        mock_ws1.send_json.assert_called_once()
        # mock_ws2 should be removed
        assert mock_ws2 not in manager.connections[job_id]
        assert len(manager.connections[job_id]) == 1
