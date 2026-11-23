"""Serve compiled assets without applying compression to streaming APIs."""
from pathlib import Path

from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware


def frontend_assets(directory: Path) -> GZipMiddleware:
    return GZipMiddleware(StaticFiles(directory=directory), minimum_size=1024, compresslevel=5)
