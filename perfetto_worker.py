# -*- coding: utf-8 -*-
"""Perfetto worker"""
from __future__ import annotations
import os, sys
from pathlib import Path

# 显式依赖（PyInstaller 静态收集；解析脚本运行时需要）
import openpyxl  # noqa: F401
import sqlalchemy  # noqa: F401
import perfetto.trace_processor  # noqa: F401

def _find_perf_dir():
    if getattr(sys, "frozen", False):
        m = getattr(sys, "_MEIPASS", None)
        if m:
            c = Path(m) / "perf_all_in_one"
            if c.is_dir(): return c
        c = Path(sys.executable).resolve().parent / "perf_all_in_one"
        if c.is_dir(): return c
    c = Path(__file__).resolve().parent / "perf_all_in_one"
    if c.is_dir(): return c
    raise FileNotFoundError("perf_all_in_one not found")

import re

def _update_cfg_duration(pd, duration_ms):
    """修改 long_perfetto_cfg.pbtx 的 duration_ms"""
    cfg = pd / "config" / "long_perfetto_cfg.pbtx"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        text = re.sub(r"duration_ms:\s*\d+", f"duration_ms: {duration_ms}", text)
        cfg.write_text(text, encoding="utf-8")

def run_capture(pd):
    os.chdir(pd); sys.path.insert(0, str(pd))
    args = sys.argv[1:]
    # 过滤内部参数，只把 perf_all_in_one 认识的参数传下去
    passthrough = []
    for a in args:
        if a.startswith("--duration_ms="):
            try:
                _update_cfg_duration(pd, int(a.split("=", 1)[1]))
            except Exception as e:
                print(f"[worker] update cfg failed: {e}")
        else:
            passthrough.append(a)
    sys.argv = ["main.py"] + passthrough
    import main as pm
    pm.main()

def run_parse(pd, td, st, sk):
    pdir = pd / "解析"
    os.chdir(pdir); sys.path.insert(0, str(pdir)); sys.path.insert(0, str(pd))
    import systrace_FrameTimeline_Analysis_20260330 as pm
    pm.filter_scroll = (st or "").strip()
    pm.scroll_track_name = sk.split(",") if pm.filter_scroll in ("0","1") and sk else [""]
    pm.main_logic(td)

def main():
    args = sys.argv[1:]
    pd = _find_perf_dir()
    if "--parse" in args:
        td=""; st=""; sk=""; i=0
        while i < len(args):
            if args[i]=="--parse" and i+1<len(args): td=args[i+1]; i+=2; continue
            if args[i].startswith("--scroll_type="): st=args[i].split("=",1)[1]
            if args[i].startswith("--scroll_keyword="): sk=args[i].split("=",1)[1]
            i+=1
        run_parse(pd, td, st, sk)
    else:
        run_capture(pd)

if __name__ == "__main__":
    main()