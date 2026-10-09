# -*- coding: utf-8 -*-
"""用户偏好（输出目录等），持久化到本地 JSON。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from core.paths import app_root

# 与历史默认路径一致
DEFAULT_LOG_EXPORT = r"E:\log"
DEFAULT_PERFETTO = r"D:\Users\Desktop\perfetto_output"
DEFAULT_SCRCPY_RECORDS = str((app_root() / "scrcpy_records").resolve())
DEFAULT_SCREENSHOT_EXPORT = r"D:\Users\Desktop\screenshots_export"

# key -> (界面标题, 默认路径)
OUTPUT_DIR_SPECS: tuple[tuple[str, str, str], ...] = (
    ("log_export", "LOG 导出", DEFAULT_LOG_EXPORT),
    ("perfetto", "流畅性分析 (Perfetto)", DEFAULT_PERFETTO),
    ("scrcpy_records", "投屏录像", DEFAULT_SCRCPY_RECORDS),
    ("screenshot_export", "截图导出", DEFAULT_SCREENSHOT_EXPORT),
)

_cache: dict[str, Any] | None = None


def prefs_file() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    else:
        base = Path.home() / ".config"
    d = base / "TestToolFlet"
    d.mkdir(parents=True, exist_ok=True)
    return d / "user_settings.json"


def _defaults() -> dict[str, Any]:
    return {
        "output_dirs": {k: default for k, _title, default in OUTPUT_DIR_SPECS},
    }


def load_prefs(*, force: bool = False) -> dict[str, Any]:
    global _cache
    if _cache is not None and not force:
        return _cache
    data = _defaults()
    path = prefs_file()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                dirs = raw.get("output_dirs")
                if isinstance(dirs, dict):
                    for k, _t, default in OUTPUT_DIR_SPECS:
                        v = dirs.get(k)
                        if isinstance(v, str) and v.strip():
                            data["output_dirs"][k] = v.strip()
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    _cache = data
    return data


def save_prefs(data: dict[str, Any] | None = None) -> None:
    global _cache
    if data is None:
        data = load_prefs()
    path = prefs_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _cache = data


def get_output_dir(key: str) -> Path:
    prefs = load_prefs()
    dirs = prefs.get("output_dirs") or {}
    default = next((d for k, _t, d in OUTPUT_DIR_SPECS if k == key), "")
    raw = str(dirs.get(key) or default).strip() or default
    return Path(raw)


def set_output_dirs(mapping: dict[str, str], *, persist: bool = True) -> dict[str, Any]:
    prefs = load_prefs()
    dirs = dict(prefs.get("output_dirs") or {})
    for k, _t, default in OUTPUT_DIR_SPECS:
        if k in mapping:
            v = (mapping[k] or "").strip() or default
            dirs[k] = v
    prefs["output_dirs"] = dirs
    if persist:
        save_prefs(prefs)
    else:
        global _cache
        _cache = prefs
    return prefs


def normalize_path_str(s: str) -> str:
    s = (s or "").strip().strip('"')
    if not s:
        return ""
    try:
        return str(Path(s).expanduser())
    except (OSError, ValueError):
        return s
