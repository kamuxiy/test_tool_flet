# -*- coding: utf-8 -*-
"""统一日志模块。"""
from __future__ import annotations
import logging, sys
from core.paths import app_root
_LOG_FILE = app_root() / 'test_tool.log'
def _setup():
    l = logging.getLogger('test_tool'); l.setLevel(logging.DEBUG)
    try:
        fh = logging.FileHandler(_LOG_FILE, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        l.addHandler(fh)
    except OSError:
        pass
    return l
logger = _setup()
