"""Runs the API with uvicorn, bound to localhost only (D014)."""

import uvicorn
from fastapi import FastAPI

HOST = "127.0.0.1"


async def run_uvicorn(app: FastAPI, port: int) -> None:
    config = uvicorn.Config(app, host=HOST, port=port, lifespan="on", log_config=None)
    await uvicorn.Server(config).serve()
