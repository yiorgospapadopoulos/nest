"""Serve the built iPhone web app at `/`, falling back to `index.html` for app routes.

The app shell holds no data, so it needs no device token. `/api` routes are registered
first and keep priority; an unknown `/api` path is a JSON 404, never the app shell.
"""

from pathlib import Path, PurePosixPath

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

INDEX = "index.html"
ASSETS_PREFIX = "assets/"
NO_CACHE = "no-cache"
# Vite names everything under assets/ by content hash, so it never changes.
IMMUTABLE = "public, max-age=31536000, immutable"
_MEDIA_TYPES = {".webmanifest": "application/manifest+json", ".js": "text/javascript"}


def install_static(app: FastAPI, root: Path) -> None:
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def static_file(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        return serve(root, path)


def serve(root: Path, path: str) -> Response:
    if path == "api" or path.startswith("api/"):
        return _not_found()
    base = root.resolve()
    target = (base / path).resolve()
    if target.is_relative_to(base) and target.is_file():
        return _file(target, path)
    index = base / INDEX
    # A missing file (a name with an extension) is a 404; anything else is an app route.
    if "." in PurePosixPath(path).name or not index.is_file():
        return _not_found()
    return _file(index, INDEX)


def _file(target: Path, path: str) -> FileResponse:
    cache = IMMUTABLE if path.startswith(ASSETS_PREFIX) else NO_CACHE
    return FileResponse(
        target, media_type=_MEDIA_TYPES.get(target.suffix), headers={"Cache-Control": cache}
    )


def _not_found() -> JSONResponse:
    return JSONResponse({"detail": "Not Found"}, status_code=404)
