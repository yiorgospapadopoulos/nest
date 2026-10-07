"""Map domain errors to JSON responses with their HTTP status."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from harness.errors import HarnessError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HarnessError)
    async def harness_error(_request: Request, error: HarnessError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(error.payload(), status_code=error.status_code, headers=error.headers())
