from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.router import api_v1_router
from app.api.websockets.connection import ws_manager
from app.config import settings
from app.core.exceptions import (
    ClipStudioException,
    clipstudio_exception_handler,
    global_exception_handler,
)
from app.core.logging import logger
from app.database import close_database
from app.services.job_queue import job_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup reconciliation and graceful teardown."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}...")
    # Reconcile any interrupted or orphan jobs from previous execution
    await job_queue.reconcile_interrupted_jobs()
    logger.info(f"{settings.APP_NAME} backend initialized successfully.")

    yield

    logger.info(f"Shutting down {settings.APP_NAME}...")
    await close_database()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """FastAPI Application Factory."""
    app = FastAPI(
        title="ClipStudio Backend API",
        version=settings.APP_VERSION,
        description="Independent, local-first AI video clipping and creator workspace API.",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception Handlers
    app.add_exception_handler(ClipStudioException, clipstudio_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    # Routers
    app.include_router(api_v1_router)

    # WebSocket Real-Time Endpoint
    @app.websocket("/ws/events")
    async def websocket_events_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            while True:
                # Keep connection alive & handle incoming pings
                data = await websocket.receive_text()
                # Optional client ping/pong response
                if data == "ping":
                    await websocket.send_text('{"event_type": "pong"}')
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception as exc:
            logger.warning(f"WebSocket client error: {exc}")
            ws_manager.disconnect(websocket)

    # Root route
    @app.get("/", tags=["Root"])
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "online",
            "docs_url": "/docs",
            "api_v1": "/api/v1",
            "ws_url": "/ws/events",
        }

    return app


app = create_app()
