"""Shared logging configuration for the Scouting App."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIRECTORY = os.getenv("LOG_DIRECTORY", "logs")
LOG_FILE_NAME = os.getenv("LOG_FILE_NAME", "server.log")
ERROR_LOG_FILE_NAME = os.getenv("ERROR_LOG_FILE_NAME", "error.log")


def configure_logging() -> None:
    """Configure application logging for both the API and worker scripts."""

    root_logger = logging.getLogger()
    already_configured = any(
        getattr(handler, "_scouting_app_logging", False)
        for handler in root_logger.handlers
    )
    if already_configured:
        return

    os.makedirs(LOG_DIRECTORY, exist_ok=True)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    root_logger.setLevel(LOG_LEVEL)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler._scouting_app_logging = True  # type: ignore[attr-defined]
    root_logger.addHandler(stream_handler)

    log_path = os.path.join(LOG_DIRECTORY, LOG_FILE_NAME)
    file_handler = RotatingFileHandler(log_path, maxBytes=10**6, backupCount=5)
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(formatter)
    file_handler._scouting_app_logging = True  # type: ignore[attr-defined]
    root_logger.addHandler(file_handler)

    error_log_path = os.path.join(LOG_DIRECTORY, ERROR_LOG_FILE_NAME)
    error_handler = RotatingFileHandler(
        error_log_path, maxBytes=10**6, backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler._scouting_app_logging = True  # type: ignore[attr-defined]
    root_logger.addHandler(error_handler)


__all__ = ["configure_logging"]
