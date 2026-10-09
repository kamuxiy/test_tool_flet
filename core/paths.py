# -*- coding: utf-8 -*-
"""统一路径解析：开发模式 vs PyInstaller 打包模式。"""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """返回应用根目录。

    开发：core/paths.py 的父目录。
    打包：PyInstaller 解压目录 _MEIPASS。
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    # core/paths.py -> core/ -> test_tool_dev/
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    """返回仓库根目录（含 assets/）。

    开发：app_root()。
    打包：同 app_root()。
    """
    return app_root()