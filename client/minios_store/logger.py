"""Logging setup for MiniOS Store daemon."""

import logging
import sys


def setup_logging(verbose=False):
    """Configure logging for the daemon.

    Args:
        verbose: If True, set level to DEBUG; otherwise INFO.

    Returns:
        The root logger for the application.
    """
    level = logging.DEBUG if verbose else logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger = logging.getLogger("minios_store")
    logger.setLevel(level)
    logger.addHandler(handler)

    # Suppress noisy websockets logs unless verbose
    ws_logger = logging.getLogger("websockets")
    ws_logger.setLevel(logging.DEBUG if verbose else logging.WARNING)

    return logger
