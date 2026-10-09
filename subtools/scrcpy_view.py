# -*- coding: utf-8 -*-
"""投屏工具独立窗口：原生 scrcpy 叠层显示，并同步宿主窗口拖拽/缩放/最小化。"""
from __future__ import annotations

import asyncio
import ctypes
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import flet as ft

from core import adb
from ui import styles as st

_DEFAULT_RECORD_DIR = Path(__file__).resolve().parent.parent / "scrcpy_records"
WINDOW_TITLE = "测试工具箱 · 投屏工具"
SCRCPY_TITLE = "TestToolOverlayScrcpy"
SIDEBAR_W = 280
TITLE_BAR_H = 40
VIDEO_PAD = 0  # 右侧显示区贴合设备比例，避免额外黑边
SYNC_INTERVAL = 0.016  # 拖拽时需足够密，才能跟手
WM_CLOSE = 0x0010
SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_BORDER = 0x00800000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000

user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _format_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def open_directory(path_str: str) -> None:
    p = os.path.normpath(path_str)
    os.makedirs(p, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def get_work_area() -> tuple[int, int, int, int]:
    """返回工作区 (left, top, width, height)。"""
    if sys.platform != "win32":
        return 0, 0, 1600, 900
    r = RECT()
    SPI_GETWORKAREA = 0x0030
    if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
        return 0, 0, 1600, 900
    return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)


def query_device_wm_size(sn: str = "") -> Optional[tuple[int, int]]:
    """读取设备显示分辨率 (width, height)。优先 Override size。"""
    cmd = ["adb"]
    s = (sn or "").strip()
    if s and s not in ("没有设备", "有多个设备，请选择一个"):
        cmd.extend(["-s", s])
    cmd.extend(["shell", "wm", "size"])
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=8,
            **adb._popen_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    override = None
    physical = None
    for line in text.splitlines():
        m = re.search(r"(Override|Physical)\s+size:\s*(\d+)\s*x\s*(\d+)", line, re.I)
        if not m:
            continue
        wh = (int(m.group(2)), int(m.group(3)))
        if m.group(1).lower().startswith("override"):
            override = wh
        else:
            physical = wh
    return override or physical


def fit_video_content_size(
    dev_w: int,
    dev_h: int,
    *,
    max_w: int,
    max_h: int,
    min_w: int = 180,
    min_h: int = 180,
) -> tuple[int, int]:
    """按设备宽高比，在最大可用区域内等比缩放内容区尺寸。"""
    dw = max(1, int(dev_w))
    dh = max(1, int(dev_h))
    mw = max(min_w, int(max_w))
    mh = max(min_h, int(max_h))
    ar = dw / dh
    if mw / ar <= mh:
        w = mw
        h = int(round(w / ar))
    else:
        h = mh
        w = int(round(h * ar))
    return max(min_w, w), max(min_h, h)


def resolve_scrcpy_exe(app_root: Path) -> Optional[str]:
    bundled = app_root / "scrcpy-win64-v2.7" / "scrcpy.exe"
    if bundled.is_file():
        return str(bundled.resolve())
    for name in ("scrcpy.exe", "scrcpy"):
        p = shutil.which(name)
        if p:
            return p
    beside = Path(sys.executable).resolve().parent / "scrcpy.exe"
    if beside.is_file():
        return str(beside)
    return None


def find_hwnd_by_title(title: str) -> int:
    if sys.platform != "win32":
        return 0
    return int(user32.FindWindowW(None, title) or 0)


def get_window_screen_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    if not hwnd:
        return None
    r = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)


def _strip_chrome(hwnd: int) -> None:
    if not hwnd:
        return
    style = int(user32.GetWindowLongW(hwnd, GWL_STYLE))
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)


def place_overlay(
    hwnd: int,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    host_hwnd: int = 0,
    show: bool = True,
) -> None:
    """定位叠层，并保证其 Z 序在投屏工具窗之上（避免最小化后被挡住）。"""
    if not hwnd or w <= 0 or h <= 0:
        return
    if not show:
        user32.ShowWindow(hwnd, SW_HIDE)
        return
    # 先放到最前并定位
    user32.SetWindowPos(
        hwnd,
        HWND_TOP,
        int(x),
        int(y),
        int(w),
        int(h),
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    user32.ShowWindow(hwnd, SW_SHOW)
    # 再把宿主窗插到叠层正下方，避免恢复后宿主盖住 scrcpy
    if host_hwnd and user32.IsWindow(host_hwnd):
        user32.SetWindowPos(
            host_hwnd,
            hwnd,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )


def raise_overlay_above_host(hwnd: int, host_hwnd: int) -> None:
    if not hwnd or not user32.IsWindow(hwnd):
        return
    user32.SetWindowPos(
        hwnd,
        HWND_TOP,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    if host_hwnd and user32.IsWindow(host_hwnd):
        user32.SetWindowPos(
            host_hwnd,
            hwnd,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )


def set_overlay_visible(hwnd: int, visible: bool) -> None:
    if not hwnd:
        return
    user32.ShowWindow(hwnd, SW_SHOW if visible else SW_HIDE)


def launch_scrcpy_tool_process(*, sn: str = "", app_root: Optional[Path] = None) -> Optional[str]:
    """从主程序拉起独立投屏窗口。"""
    root = app_root or Path(__file__).resolve().parent.parent
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--scrcpy-tool"]
    else:
        cmd = [sys.executable, str(root / "main.py"), "--scrcpy-tool"]
    sn = (sn or "").strip()
    if sn and sn not in ("没有设备", "有多个设备，请选择一个"):
        cmd.extend(["--sn", sn])
    try:
        subprocess.Popen(cmd, cwd=str(root))
    except OSError as e:
        return f"启动投屏窗口失败: {e}"
    return None


def run_scrcpy_tool_window(sn: str = "") -> None:
    async def main(page: ft.Page):
        await _build_scrcpy_tool_page(page, sn=sn)

    ft.run(main)


async def _build_scrcpy_tool_page(page: ft.Page, *, sn: str = "") -> None:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        app_root = Path(meipass) if meipass else Path(sys.executable).resolve().parent
    else:
        app_root = Path(__file__).resolve().parent.parent

    pal0 = st.get_palette(page)
    page.title = WINDOW_TITLE
    page.padding = 0
    page.spacing = 0
    page.bgcolor = pal0.editor_bg
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    # 先给一个占位尺寸，随后按设备分辨率自适应
    page.window.width = SIDEBAR_W + 420
    page.window.height = TITLE_BAR_H + 720
    page.window.min_width = SIDEBAR_W + 220
    page.window.min_height = TITLE_BAR_H + 320
    page.window.frameless = True
    page.window.shadow = False
    page.window.bgcolor = pal0.editor_bg

    out_dir = _DEFAULT_RECORD_DIR
    try:
        from core.user_prefs import get_output_dir

        out_dir = get_output_dir("scrcpy_records")
    except Exception:
        pass
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        out_dir = Path.home() / "scrcpy_records"
        out_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "sn": (sn or "").strip(),
        "alive": True,
        "mode": "idle",  # idle | mirroring | recording
        "scrcpy_proc": None,
        "scrcpy_hwnd": 0,
        "record_path": None,
        "record_file": None,
        "elapsed": 0.0,
        "tick_started": None,
        "timer_task": None,
        "sync_task": None,
        "view_w": 0.0,
        "view_h": 0.0,
        "content_w": 0.0,
        "content_h": 0.0,
        "dev_w": 1080,
        "dev_h": 1920,
        "lock_h": 0,
        "layout_lock": False,
        "host_hwnd": 0,
        "host_hidden": False,
        "chrome_stripped": False,
    }

    def snack(msg: str) -> None:
        page.snack_bar = ft.SnackBar(ft.Text(msg))
        page.snack_bar.open = True
        page.update()

    def _serial_args() -> list[str]:
        s = state["sn"]
        if s and s not in ("没有设备", "有多个设备，请选择一个"):
            return ["-s", s]
        return []

    def _adb_prefix() -> list[str]:
        return ["adb", *_serial_args()]

    def _current_record_dir() -> Path:
        raw = (dir_field.value or "").strip()
        p = Path(raw) if raw else out_dir
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            return out_dir
        return p

    def _new_local_record_path() -> Path:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return _current_record_dir() / f"record_{stamp}.mp4"

    def _kill_scrcpy(*, wait_s: float = 8.0, finalize_record: bool = False) -> None:
        hwnd = int(state["scrcpy_hwnd"] or 0)
        proc = state["scrcpy_proc"]
        state["scrcpy_hwnd"] = 0
        state["chrome_stripped"] = False
        state["scrcpy_proc"] = None
        if not proc and not hwnd:
            return
        # 录屏时必须先 WM_CLOSE 让 scrcpy 写完 moov；Hide+terminate 会得到无法播放的坏文件
        if hwnd and user32.IsWindow(hwnd):
            try:
                if finalize_record:
                    user32.ShowWindow(hwnd, SW_SHOW)
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if proc:
            try:
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=wait_s)
                    except subprocess.TimeoutExpired:
                        try:
                            if hwnd and user32.IsWindow(hwnd):
                                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                            proc.wait(timeout=2)
                        except Exception:
                            pass
                        if proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                try:
                                    proc.wait(timeout=2)
                                except subprocess.TimeoutExpired:
                                    pass
            except OSError:
                pass
        if finalize_record:
            time.sleep(0.5)

    def _mp4_looks_playable(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size < 1024:
                return False
            data = path.read_bytes()
            # 无 moov 的 mp4 多数播放器打不开
            return b"ftyp" in data[:64] and b"moov" in data
        except OSError:
            return False

    def _start_recording_segment() -> tuple[Optional[str], Optional[Path]]:
        """用 scrcpy --record 直接写到本地（同 Scrcpy-GUI；OPPO 上 adb screenrecord 无写权限）。"""
        local = _new_local_record_path()
        err = _launch_overlay_scrcpy(record_path=local)
        if err:
            state["record_path"] = None
            return err, None
        state["record_path"] = local
        return None, local

    def _stop_recording_segment(*, resume_mirror: bool = True) -> Optional[Path]:
        local = state.get("record_path")
        state["record_path"] = None
        _kill_scrcpy(wait_s=10.0, finalize_record=True)
        if resume_mirror:
            _launch_overlay_scrcpy(record_path=None)
        if local and _mp4_looks_playable(Path(local)):
            return Path(local)
        return None

    def _ensure_host_hwnd() -> int:
        hwnd = int(state.get("host_hwnd") or 0)
        if hwnd and user32.IsWindow(hwnd):
            return hwnd
        hwnd = find_hwnd_by_title(WINDOW_TITLE)
        state["host_hwnd"] = hwnd
        return hwnd

    def _refresh_device_size() -> tuple[int, int]:
        # 重新对齐时可能已换机：单设备则切到当前机；多设备则尽量沿用原 SN
        try:
            serials = adb.adb_devices_serials()
        except Exception:
            serials = []
        cur = (state.get("sn") or "").strip()
        if len(serials) == 1:
            state["sn"] = serials[0]
        elif cur and cur in serials:
            state["sn"] = cur
        elif serials:
            state["sn"] = serials[0]
        wh = query_device_wm_size(state.get("sn") or "")
        if wh and wh[0] > 0 and wh[1] > 0:
            state["dev_w"], state["dev_h"] = int(wh[0]), int(wh[1])
        return int(state["dev_w"]), int(state["dev_h"])

    def _force_host_client_size(win_w: int, win_h: int) -> None:
        """Flet 改 width/height 有时不即时，用 Win32 再钉一次外框尺寸。"""
        hwnd = _ensure_host_hwnd()
        if not hwnd:
            return
        rect = get_window_screen_rect(hwnd)
        if not rect:
            return
        left, top, _ow, _oh = rect
        user32.SetWindowPos(
            hwnd,
            HWND_TOP,
            int(left),
            int(top),
            int(win_w),
            int(win_h),
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

    def _apply_layout_for_device(*, update_ui: bool = True) -> tuple[int, int]:
        """窗口高度锁定，仅按设备宽高比改宽度；去掉左右黑边。"""
        dw, dh = _refresh_device_size()
        _wa_l, _wa_t, wa_w, wa_h = get_work_area()

        # 高度：首次记下，之后「重新对齐」只改宽度
        if not state.get("lock_h"):
            prefer = int(page.window.height or (TITLE_BAR_H + 720))
            state["lock_h"] = min(max(prefer, TITLE_BAR_H + 320), max(TITLE_BAR_H + 320, wa_h - 16))
        lock_h = int(state["lock_h"])

        view_h = max(200, lock_h - TITLE_BAR_H)
        content_h = max(160, view_h - VIDEO_PAD * 2)
        # 宽度由高度 × 设备宽高比决定
        content_w = int(round(content_h * (dw / float(dh))))
        max_content_w = max(160, wa_w - SIDEBAR_W - 24 - VIDEO_PAD * 2)
        if content_w > max_content_w:
            # 超宽屏工作区不够时，仍保比例：缩宽度并相应降低内容高度（窗口高度仍锁定，上下可留白）
            content_w = max_content_w
            content_h = max(160, int(round(content_w * (dh / float(dw)))))

        view_w = content_w + VIDEO_PAD * 2
        # 右侧显示区高度仍铺满锁定窗口高度，内容按比例居中叠层
        view_h = max(200, lock_h - TITLE_BAR_H)
        win_w = SIDEBAR_W + view_w
        win_h = lock_h
        win_w = min(win_w, max(SIDEBAR_W + 200, wa_w - 8))

        state["view_w"] = float(view_w)
        state["view_h"] = float(view_h)
        state["content_w"] = float(content_w)
        state["content_h"] = float(content_h)
        state["layout_lock"] = True

        page.window.width = win_w
        page.window.height = win_h
        page.window.min_width = min(win_w, SIDEBAR_W + 200)
        page.window.min_height = win_h
        page.window.max_height = win_h
        try:
            video_host.width = view_w
            video_host.height = view_h
            video_host.expand = False
            sidebar.width = SIDEBAR_W
            sidebar.height = view_h
        except NameError:
            pass
        if update_ui:
            try:
                page.update()
            except Exception:
                pass
        _force_host_client_size(win_w, win_h)
        # 再读一次实际窗口，校正 view（防止 Flet/DPI 偏差）
        host = _ensure_host_hwnd()
        actual = get_window_screen_rect(host) if host else None
        if actual:
            _l, _t, aw, ah = actual
            # 仅当实际宽度明显偏大时强制再钉
            if aw > win_w + 8:
                _force_host_client_size(win_w, win_h)
        return view_w, view_h

    def _video_screen_rect() -> tuple[int, int, int, int]:
        # 优先用 Win32 GetWindowRect；叠层按「内容区」比例居中，避免宽容器左右黑边
        host = _ensure_host_hwnd()
        rect = get_window_screen_rect(host) if host else None
        if rect:
            left, top, win_w, win_h = rect
        else:
            left = float(page.window.left or 0)
            top = float(page.window.top or 0)
            win_w = float(page.window.width or SIDEBAR_W + 420)
            win_h = float(page.window.height or TITLE_BAR_H + 720)

        panel_x = left + SIDEBAR_W
        panel_y = top + TITLE_BAR_H
        panel_w = state["view_w"] if state["view_w"] > 1 else max(1.0, win_w - SIDEBAR_W)
        panel_h = state["view_h"] if state["view_h"] > 1 else max(1.0, win_h - TITLE_BAR_H)

        cw = float(state.get("content_w") or max(1.0, panel_w - VIDEO_PAD * 2))
        ch = float(state.get("content_h") or max(1.0, panel_h - VIDEO_PAD * 2))
        # 在右侧面板内水平居中、垂直居中放置内容区（通常 content 宽=面板内宽，无左右缝）
        x = int(panel_x + max(0.0, (panel_w - cw) / 2.0))
        y = int(panel_y + max(0.0, (panel_h - ch) / 2.0))
        w = int(max(1.0, cw))
        h = int(max(1.0, ch))
        return x, y, w, h

    def _wait_scrcpy_hwnd(timeout: float = 10.0) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hwnd = find_hwnd_by_title(SCRCPY_TITLE)
            if hwnd:
                return hwnd
            proc = state["scrcpy_proc"]
            if proc and proc.poll() is not None:
                return 0
            time.sleep(0.08)
        return 0

    def _reposition_overlay(*, force_show: Optional[bool] = None) -> None:
        hwnd = state["scrcpy_hwnd"]
        if not hwnd:
            return
        if not user32.IsWindow(hwnd):
            state["scrcpy_hwnd"] = 0
            return
        host = _ensure_host_hwnd()
        if host and user32.IsIconic(host):
            state["host_hidden"] = True
        show = (not state["host_hidden"]) if force_show is None else force_show
        if not show:
            set_overlay_visible(hwnd, False)
            return
        x, y, w, h = _video_screen_rect()
        if not state["chrome_stripped"]:
            _strip_chrome(hwnd)
            state["chrome_stripped"] = True
        place_overlay(hwnd, x, y, w, h, host_hwnd=host, show=True)

    def _launch_overlay_scrcpy(*, record_path: Optional[Path] = None) -> Optional[str]:
        exe = resolve_scrcpy_exe(app_root)
        if not exe:
            return "未找到 scrcpy.exe"
        # 切换录制时需要重启同一路 scrcpy（设备通常只能挂一路）
        _kill_scrcpy(
            wait_s=10.0 if state.get("record_path") else 3.0,
            finalize_record=bool(state.get("record_path")),
        )
        x, y, w, h = _video_screen_rect()
        max_edge = max(int(state["dev_w"]), int(state["dev_h"]), w, h)
        max_edge = min(max(720, max_edge), 2560)
        cmd = [
            exe,
            *_serial_args(),
            "--window-title",
            SCRCPY_TITLE,
            "--window-borderless",
            "--window-x",
            str(max(0, x)),
            "--window-y",
            str(max(0, y)),
            "--window-width",
            str(max(160, w)),
            "--window-height",
            str(max(160, h)),
            "--max-size",
            str(max_edge),
        ]
        if record_path is not None:
            try:
                record_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return f"无法创建录像目录: {e}"
            # 显式 mp4，避免扩展名/收尾异常
            cmd.extend(["--record", str(record_path), "--record-format", "mp4"])
        try:
            state["scrcpy_proc"] = subprocess.Popen(
                cmd,
                cwd=str(Path(exe).parent),
                **adb._popen_kwargs(),
            )
        except OSError as e:
            state["scrcpy_proc"] = None
            return f"启动 scrcpy 失败: {e}"
        hwnd = _wait_scrcpy_hwnd()
        if not hwnd:
            _kill_scrcpy()
            return "未找到 scrcpy 窗口，请检查设备连接"
        state["scrcpy_hwnd"] = hwnd
        _reposition_overlay(force_show=True)
        return None

    def _set_status(text: str) -> None:
        status_label.value = text
        try:
            page.update()
        except Exception:
            pass

    def _refresh_duration() -> None:
        elapsed = state["elapsed"]
        if state["mode"] == "recording" and state["tick_started"] is not None:
            elapsed += time.monotonic() - state["tick_started"]
        duration_label.value = _format_duration(elapsed)
        try:
            page.update()
        except Exception:
            pass

    def _sync_buttons() -> None:
        mode = state["mode"]
        btn_start.visible = mode != "recording"
        btn_stop.visible = mode == "recording"
        try:
            page.update()
        except Exception:
            pass

    async def _timer_loop() -> None:
        try:
            while state["mode"] == "recording" and state["alive"]:
                _refresh_duration()
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            pass

    def _stop_timer(*, accumulate: bool) -> None:
        task = state["timer_task"]
        state["timer_task"] = None
        if task and not task.done():
            task.cancel()
        if accumulate and state["tick_started"] is not None:
            state["elapsed"] += time.monotonic() - state["tick_started"]
        state["tick_started"] = None
        _refresh_duration()

    def _start_timer(*, reset: bool) -> None:
        if reset:
            state["elapsed"] = 0.0
        state["tick_started"] = time.monotonic()
        old = state["timer_task"]
        if old and not old.done():
            old.cancel()
        state["timer_task"] = page.run_task(_timer_loop)

    async def _sync_overlay_loop() -> None:
        last_rect = None
        z_ticks = 0
        try:
            while state["alive"]:
                hwnd = state["scrcpy_hwnd"]
                proc = state["scrcpy_proc"]
                if proc and proc.poll() is not None:
                    state["scrcpy_hwnd"] = 0
                    state["scrcpy_proc"] = None
                    if state["mode"] == "mirroring":
                        state["mode"] = "idle"
                        video_hint.value = "scrcpy 已退出，可点「重新对齐投屏」"
                        video_hint.visible = True
                        _set_status("状态：投屏已结束")
                        _sync_buttons()
                elif hwnd:
                    host = _ensure_host_hwnd()
                    if host and user32.IsIconic(host):
                        if not state["host_hidden"]:
                            state["host_hidden"] = True
                            set_overlay_visible(hwnd, False)
                            last_rect = None
                    else:
                        if state["host_hidden"]:
                            state["host_hidden"] = False
                            _reposition_overlay(force_show=True)
                            last_rect = _video_screen_rect()
                            z_ticks = 0
                        else:
                            rect = _video_screen_rect()
                            if rect != last_rect:
                                _reposition_overlay(force_show=True)
                                last_rect = rect
                                z_ticks = 0
                            else:
                                z_ticks += 1
                                # ~每 160ms 纠正一次层级，防止最小化恢复后被挡住
                                if z_ticks >= 10:
                                    raise_overlay_above_host(hwnd, host)
                                    z_ticks = 0
                await asyncio.sleep(SYNC_INTERVAL)
        except asyncio.CancelledError:
            pass

    duration_label = st.themed_text(page, "00:00:00", size=26, weight=ft.FontWeight.W_600)
    status_label = st.themed_text(page, "状态：初始化…", muted=True, size=12)
    dir_field = st.themed_text_field(
        page, label="录像存放目录", value=str(out_dir), expand=True, read_only=True
    )
    btn_start = st.btn_success("开始", icon=ft.Icons.FIBER_MANUAL_RECORD, width=104)
    btn_stop = st.btn_danger_outline("停止", icon=ft.Icons.STOP, width=104)
    btn_open_dir = st.btn_info_outline("打开目录", icon=ft.Icons.FOLDER_OPEN, width=120)
    btn_realign = st.btn_primary("重新对齐投屏", icon=ft.Icons.CAST, width=180)
    btn_stop.visible = False
    record_action_row = ft.Row([btn_start, btn_stop], spacing=6)

    video_hint = st.themed_text(
        page,
        "正在启动原生 scrcpy 叠层…",
        muted=True,
        size=13,
        text_align=ft.TextAlign.CENTER,
    )

    async def on_realign(_=None):
        if state["mode"] == "recording":
            snack("录制中请先停止，再重新对齐")
            return
        video_hint.value = "正在按设备分辨率调整窗口…"
        video_hint.visible = True
        page.update()
        _apply_layout_for_device()
        await asyncio.sleep(0.08)
        err = await asyncio.to_thread(_launch_overlay_scrcpy, record_path=None)
        if err:
            snack(err)
            video_hint.value = err
            _set_status(f"状态：{err}")
            return
        video_hint.visible = False
        if state["mode"] != "recording":
            state["mode"] = "mirroring"
        _set_status(
            f"状态：投屏中 · 设备 {state['dev_w']}×{state['dev_h']} · "
            f"窗口宽 {int(SIDEBAR_W + state['view_w'])} · "
            f"画面 {int(state['content_w'])}×{int(state['content_h'])}"
        )
        if not state["sync_task"]:
            state["sync_task"] = page.run_task(_sync_overlay_loop)
        _sync_buttons()
        snack("投屏已对齐")

    async def on_start(_=None):
        if state["mode"] == "recording":
            return
        _apply_layout_for_device()
        await asyncio.sleep(0.05)
        err, local = await asyncio.to_thread(_start_recording_segment)
        if err:
            snack(err)
            return
        if not state["sync_task"]:
            state["sync_task"] = page.run_task(_sync_overlay_loop)
        state["mode"] = "recording"
        state["record_file"] = local
        _start_timer(reset=True)
        _set_status(f"状态：录制中 → {local.name if local else ''}")
        _sync_buttons()
        snack("开始录制")

    async def on_stop(_=None):
        if state["mode"] != "recording":
            return
        _stop_timer(accumulate=True)
        local = await asyncio.to_thread(_stop_recording_segment, resume_mirror=True)
        state["mode"] = "mirroring" if state["scrcpy_hwnd"] else "idle"
        state["record_file"] = local
        state["elapsed"] = 0.0
        _refresh_duration()
        if local:
            _set_status(f"状态：投屏中（未录制）；已保存 {local.name}")
            snack(f"录制已停止：{local}")
        else:
            _set_status("状态：投屏中（未录制）；保存失败")
            snack("录制已停止，但视频保存失败，请重试")
        _sync_buttons()

    def on_open_dir(_=None):
        try:
            open_directory(str(_current_record_dir()))
        except OSError as e:
            snack(f"打开目录失败: {e}")

    btn_start.on_click = on_start
    btn_stop.on_click = on_stop
    btn_open_dir.on_click = on_open_dir
    btn_realign.on_click = on_realign

    sidebar = ft.Container(
        width=SIDEBAR_W,
        bgcolor=pal0.rail_bg,
        border=ft.Border.only(right=ft.BorderSide(1, pal0.rail_divider)),
        padding=ft.Padding.only(top=10, bottom=12, left=8, right=8),
        content=ft.Column(
            [
                st.themed_text(page, "投屏工具", size=13, weight=ft.FontWeight.W_500),
                st.themed_hairline(page),
                st.themed_text(
                    page,
                    "叠层用原生 scrcpy；录屏走 scrcpy --record 写到本机目录"
                    "（同 Scrcpy-GUI）。停止时用正常关窗收尾，保证可播放。",
                    muted=True,
                    size=11,
                ),
                btn_realign,
                st.themed_hairline(page),
                st.themed_text(page, "录屏", size=16, weight=ft.FontWeight.W_500),
                record_action_row,
                ft.Container(height=4),
                st.themed_text(page, "录制时长", muted=True, size=11),
                duration_label,
                status_label,
                ft.Container(height=4),
                dir_field,
                btn_open_dir,
            ],
            spacing=8,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )

    def on_view_size(e):
        # 尺寸由 _apply_layout_for_device 驱动，避免布局回写把宽度撑开
        if state.get("layout_lock"):
            if state["scrcpy_hwnd"]:
                _reposition_overlay()
            return
        try:
            w = float(e.width or 0)
            h = float(e.height or 0)
            if w > 1:
                state["view_w"] = w
            if h > 1:
                state["view_h"] = h
        except Exception:
            pass
        if state["scrcpy_hwnd"]:
            _reposition_overlay()

    video_host = ft.Container(
        width=360,
        height=720,
        bgcolor="#1a1a1a",
        padding=0,
        alignment=ft.Alignment.CENTER,
        content=video_hint,
        data={"_flet_theme": "panel_bg"},
        on_size_change=on_view_size,
    )

    async def on_close_window(_=None):
        state["alive"] = False
        _stop_timer(accumulate=False)
        task = state["sync_task"]
        if task and not task.done():
            task.cancel()
        if state.get("record_path"):
            await asyncio.to_thread(_stop_recording_segment, resume_mirror=False)
        else:
            await asyncio.to_thread(_kill_scrcpy)
        await page.window.close()

    async def on_minimize(_=None):
        state["host_hidden"] = True
        if state["scrcpy_hwnd"]:
            set_overlay_visible(state["scrcpy_hwnd"], False)
        page.window.minimized = True
        page.update()

    def on_window_event(e: ft.WindowEvent):
        et = e.type
        if et in (ft.WindowEventType.MINIMIZE, ft.WindowEventType.HIDE):
            state["host_hidden"] = True
            if state["scrcpy_hwnd"]:
                set_overlay_visible(state["scrcpy_hwnd"], False)
        elif et in (
            ft.WindowEventType.RESTORE,
            ft.WindowEventType.SHOW,
            ft.WindowEventType.MAXIMIZE,
            ft.WindowEventType.UNMAXIMIZE,
        ):
            state["host_hidden"] = False
            if state["scrcpy_hwnd"]:
                _reposition_overlay(force_show=True)
        elif et in (
            ft.WindowEventType.MOVE,
            ft.WindowEventType.MOVED,
            ft.WindowEventType.RESIZE,
            ft.WindowEventType.RESIZED,
        ):
            if state["scrcpy_hwnd"] and not state["host_hidden"]:
                _reposition_overlay()
        elif et == ft.WindowEventType.FOCUS:
            if state["scrcpy_hwnd"] and not state["host_hidden"]:
                _reposition_overlay(force_show=True)

    page.window.on_event = on_window_event

    title_btn_min = ft.IconButton(
        icon=ft.Icons.MINIMIZE, icon_size=18, icon_color=pal0.field_text, on_click=on_minimize
    )
    title_btn_close = ft.IconButton(
        icon=ft.Icons.CLOSE, icon_size=18, icon_color=pal0.field_text, on_click=on_close_window
    )
    title_bar = ft.Container(
        height=TITLE_BAR_H,
        bgcolor=pal0.toolbar_bg,
        border=ft.Border.only(bottom=ft.BorderSide(1, pal0.rail_divider)),
        padding=ft.Padding.symmetric(horizontal=8),
        content=ft.Row(
            [
                ft.WindowDragArea(
                    content=ft.Container(
                        content=st.themed_text(
                            page, WINDOW_TITLE, size=13, weight=ft.FontWeight.W_500
                        ),
                        padding=ft.Padding.only(left=8),
                        alignment=ft.Alignment.CENTER_LEFT,
                        expand=True,
                    ),
                    expand=True,
                ),
                title_btn_min,
                title_btn_close,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    shell = ft.Container(
        expand=True,
        bgcolor=pal0.editor_bg,
        border_radius=10,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        content=ft.Column(
            [
                title_bar,
                ft.Row(
                    [sidebar, video_host],
                    spacing=0,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ],
            spacing=0,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.START,
        ),
    )
    page.add(shell)
    _sync_buttons()
    _set_status("状态：正在按设备分辨率调整窗口…")
    _apply_layout_for_device()
    # 等窗口坐标与视频区尺寸就绪后再叠层
    for _ in range(40):
        if page.window.left is not None and state["view_w"] > 1:
            break
        await asyncio.sleep(0.05)
    await on_realign()
