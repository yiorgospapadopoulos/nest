import sys

from nestd.platform.base import Platform, PlatformName, UnsupportedPlatformError
from nestd.platform.linux import LINUX
from nestd.platform.macos import MACOS

__all__ = [
    "LINUX",
    "MACOS",
    "Platform",
    "PlatformName",
    "UnsupportedPlatformError",
    "current_platform",
]


def current_platform(system: str = sys.platform) -> Platform:
    if system == "darwin":
        return MACOS
    if system.startswith("linux"):
        return LINUX
    msg = f"Nest does not run on {system} yet"
    raise UnsupportedPlatformError(msg)
