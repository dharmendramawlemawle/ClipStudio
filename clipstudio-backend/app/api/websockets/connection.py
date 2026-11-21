import json
from datetime import datetime, timezone
from fastapi import WebSocket
from app.core.logging import logger
from app.schemas.job import JobProgressEvent


class ConnectionManager:
    """Manages active WebSocket client connections and broadcasts job progress events."""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total active: {len(self.active_connections)}")

    async def broadcast(self, data: dict):
        """Broadcasts arbitrary JSON payload to all active connections."""
        if not self.active_connections:
            return

        dead_connections: set[WebSocket] = set()
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(data))
            except Exception as exc:
                logger.warning(f"Failed to send to client; marking dead: {exc}")
                dead_connections.add(connection)

        for dead in dead_connections:
            self.disconnect(dead)

    async def broadcast_job_progress(
        self,
        job_id: str,
        status: str,
        progress_percent: float,
        current_step: str,
        message: str,
    ):
        """Constructs and broadcasts a standardized JobProgressEvent."""
        event = JobProgressEvent(
            job_id=job_id,
            status=status,
            progress_percent=progress_percent,
            current_step=current_step,
            message=message,
            timestamp=datetime.now(timezone.utc),
        )
        await self.broadcast(event.model_dump(mode="json"))


ws_manager = ConnectionManager()
