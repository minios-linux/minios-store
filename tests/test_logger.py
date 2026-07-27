"""Tests for minios_store.logger.setup_logging."""

import logging

from minios_store import logger as logger_module


def _reset_app_logger():
    lg = logging.getLogger("minios_store")
    for handler in list(lg.handlers):
        lg.removeHandler(handler)
    return lg


def test_setup_logging_info_level():
    _reset_app_logger()
    lg = logger_module.setup_logging(verbose=False)
    assert lg.level == logging.INFO
    assert any(isinstance(h, logging.StreamHandler) for h in lg.handlers)


def test_setup_logging_verbose_level():
    _reset_app_logger()
    lg = logger_module.setup_logging(verbose=True)
    assert lg.level == logging.DEBUG
    assert logging.getLogger("websockets").level == logging.DEBUG


def test_setup_logging_quiets_websockets_when_not_verbose():
    _reset_app_logger()
    logger_module.setup_logging(verbose=False)
    assert logging.getLogger("websockets").level == logging.WARNING
