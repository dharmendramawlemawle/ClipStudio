from fastapi import Request, status
from fastapi.responses import JSONResponse
from app.core.logging import logger


class ClipStudioException(Exception):
    """Base exception for ClipStudio application."""

    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class EntityNotFoundException(ClipStudioException):
    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(
            message=f"{entity_name} with id '{entity_id}' was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class JobExecutionException(ClipStudioException):
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Centralized fallback exception handler."""
    logger.error(f"Unhandled exception at {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred in ClipStudio.",
            "detail": str(exc),
        },
    )


async def clipstudio_exception_handler(request: Request, exc: ClipStudioException) -> JSONResponse:
    """Handler for domain-specific ClipStudio exceptions."""
    logger.warning(f"Domain error at {request.method} {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
        },
    )
