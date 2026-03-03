"""
Loguru-based structured logger factory.
Outputs JSON in production, human-readable text in development.
"""

import sys
from functools import cache

from loguru import logger as _loguru_logger

from ai_copilot_infra.core.config import settings


def _configure_logger() -> None:
    _loguru_logger.remove()

    if settings.log_format == "json":
        _loguru_logger.add(
            sys.stdout,
            level=settings.log_level,
            format="{message}",
            serialize=True,
            enqueue=True,
        )
    else:
        _loguru_logger.add(
            sys.stdout,
            level=settings.log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level>"
                " | <cyan>{name}</cyan> - {message}"
            ),
            colorize=True,
            enqueue=True,
        )


_configure_logger()


@cache
def get_logger(name: str):
    """Return a logger bound with the given module name."""
    return _loguru_logger.bind(module=name)
