"""Structured logging configuration."""

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    log_dir: str = "logs"
) -> logging.Logger:
    """Configure structured logging with optional file output.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file name. If None, uses timestamp.
        log_dir: Directory for log files.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger("internship_scanner")
    logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    logger.handlers.clear()

    # Console handler with concise format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler with detailed format
    if log_file or log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(exist_ok=True)

        if log_file is None:
            log_file = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        file_handler = logging.FileHandler(log_path / log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """Get the application logger."""
    return logging.getLogger("internship_scanner")
