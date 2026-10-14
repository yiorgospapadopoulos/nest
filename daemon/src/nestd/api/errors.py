"""Map domain errors to JSON responses with their HTTP status."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nestd.errors import NestError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NestError)
    async def nest_error(_request: Request, error: NestError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(error.payload(), status_code=error.status_code, headers=error.headers())
