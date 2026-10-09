# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple

import flet as ft

from core import user_prefs
from ui import styles as st

try:
    import psutil
except ImportError:
    psutil = None


def _pick_directory_sync() -> Optional[str]:
    if sys.platform == "win32":
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            d = filedialog.askdirectory(parent=root, title="选择输出目录")
            return d if d else None
        finally:
            root.destroy()
    return None


def build_settings_panel(
    page: ft.Page,
    snack: Callable[[str], None],
    on_palette_change: Optional[Callable[[], None]] = None,
    on_theme_toggle: Optional[Callable[..., None]] = None,
    on_dirs_applied: Optional[Callable[[], None]] = None,
) -> Tuple[ft.Control, ft.Dropdown]:
    theme_dd = st.themed_dropdown(
        page,
        label="主题（部分控件随系统主题）",
        width=280,
        options=[ft.dropdown.Option("dark"), ft.dropdown.Option("light")],
        value="dark" if page.theme_mode == ft.ThemeMode.DARK else "light",
    )
    mem_proc = st.themed_text(page, "进程内存: …", size=13)
    mem_sys = st.themed_text(page, "系统内存占用: …", size=13)

    async def on_theme(e):
        v = theme_dd.value or "dark"
        page.theme_mode = ft.ThemeMode.DARK if v == "dark" else ft.ThemeMode.LIGHT
        if on_palette_change:
            on_palette_change()
        else:
            page.update()

    theme_dd.on_change = on_theme

    async def refresh_mem(_=None):
        if not psutil:
            mem_proc.value = "进程内存: 请 pip install psutil"
            mem_sys.value = ""
            page.update()
            return

        def read():
            p = psutil.Process(os.getpid())
            uss = int(p.memory_full_info().uss / 1024 / 1024)
            pct = psutil.virtual_memory().percent
            return uss, pct

        uss, pct = await asyncio.to_thread(read)
        mem_proc.value = f"本工具进程: ~{uss} MB (USS)"
        mem_sys.value = f"系统内存使用率: {pct:.1f}%"
        page.update()

    refresh_btn = st.btn_primary("刷新内存信息", on_click=refresh_mem)

    theme_toggle_btn = (
        st.btn_secondary("主题切换", on_click=on_theme_toggle)
        if on_theme_toggle
        else None
    )

    # —— 目录设置 —— #
    prefs = user_prefs.load_prefs()
    saved_dirs: dict[str, str] = dict(prefs.get("output_dirs") or {})
    applied: dict[str, str] = {
        k: user_prefs.normalize_path_str(saved_dirs.get(k) or default)
        for k, _title, default in user_prefs.OUTPUT_DIR_SPECS
    }
    fields: dict[str, ft.TextField] = {}
    fp_dir: Optional[ft.FilePicker] = None
    if sys.platform != "win32":
        fp_dir = ft.FilePicker()
        page.overlay.append(fp_dir)

    apply_btn = st.btn_primary("应用")
    apply_btn.style = ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: st.PRIMARY,
            ft.ControlState.DISABLED: ft.Colors.with_opacity(0.28, st.PRIMARY),
        },
        color={
            ft.ControlState.DEFAULT: "#ffffff",
            ft.ControlState.DISABLED: ft.Colors.with_opacity(0.45, "#ffffff"),
        },
        overlay_color={
            ft.ControlState.DISABLED: ft.Colors.TRANSPARENT,
        },
        mouse_cursor={
            ft.ControlState.DEFAULT: ft.MouseCursor.CLICK,
            ft.ControlState.DISABLED: ft.MouseCursor.BASIC,
        },
    )
    apply_btn.disabled = True
    apply_btn.opacity = 0.55

    def _draft_dirs() -> dict[str, str]:
        out: dict[str, str] = {}
        for k, _title, default in user_prefs.OUTPUT_DIR_SPECS:
            raw = (fields[k].value or "").strip()
            out[k] = user_prefs.normalize_path_str(raw) or default
        return out

    def _set_apply_enabled(enabled: bool) -> None:
        apply_btn.disabled = not enabled
        apply_btn.opacity = 1.0 if enabled else 0.55
        # 直接属性在部分 Flet 版本会盖住 style 的 DISABLED；同步刷一遍
        if enabled:
            apply_btn.bgcolor = st.PRIMARY
            apply_btn.color = "#ffffff"
        else:
            apply_btn.bgcolor = ft.Colors.with_opacity(0.28, st.PRIMARY)
            apply_btn.color = ft.Colors.with_opacity(0.45, "#ffffff")

    def _sync_apply_enabled() -> None:
        dirty = _draft_dirs() != applied
        _set_apply_enabled(dirty)
        page.update()

    def _on_path_change(_e=None) -> None:
        _sync_apply_enabled()

    async def _browse(key: str) -> None:
        if sys.platform == "win32":
            path = await asyncio.to_thread(_pick_directory_sync)
        else:
            assert fp_dir is not None
            path = await fp_dir.get_directory_path(dialog_title="选择输出目录")
        if path:
            fields[key].value = path
            _sync_apply_enabled()

    async def _on_apply(_e=None) -> None:
        draft = _draft_dirs()
        if draft == applied:
            return
        for k, title, _d in user_prefs.OUTPUT_DIR_SPECS:
            p = draft[k]
            if not p:
                snack(f"「{title}」路径不能为空")
                return
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                snack(f"无法创建「{title}」目录: {exc}")
                return
        user_prefs.set_output_dirs(draft, persist=True)
        applied.clear()
        applied.update(draft)
        _set_apply_enabled(False)
        snack("目录设置已保存")
        if on_dirs_applied:
            on_dirs_applied()
        page.update()

    apply_btn.on_click = _on_apply
    _set_apply_enabled(False)

    dir_rows: list[ft.Control] = [
        st.themed_text(page, "目录设置", size=16, weight=ft.FontWeight.W_500),
        st.themed_text(
            page,
            "以下功能会把产物写到对应文件夹；修改后点「应用」生效，并会记住下次打开。",
            size=12,
            muted=True,
        ),
    ]
    for key, title, default in user_prefs.OUTPUT_DIR_SPECS:
        initial = applied.get(key) or default
        tf = st.themed_text_field(
            page,
            label=title,
            value=initial,
            expand=True,
            on_change=_on_path_change,
        )
        fields[key] = tf

        async def _browse_click(_e=None, k=key):
            await _browse(k)

        browse = st.btn_info_outline(
            "选择文件夹",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=_browse_click,
        )
        dir_rows.append(
            ft.Row(
                [tf, browse],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
    dir_rows.append(ft.Row([apply_btn], alignment=ft.MainAxisAlignment.START))
    dir_rows.append(
        st.themed_text(
            page,
            f"配置文件: {user_prefs.prefs_file()}",
            size=11,
            muted=True,
        )
    )

    settings_controls: list[ft.Control] = [
        st.themed_text(page, "设置", size=18, weight=ft.FontWeight.W_500),
        st.themed_hairline(page),
        theme_dd,
    ]
    if theme_toggle_btn is not None:
        settings_controls.append(theme_toggle_btn)
    settings_controls.extend(
        [
            st.themed_hairline(page),
            *dir_rows,
            st.themed_hairline(page),
            mem_proc,
            mem_sys,
            refresh_btn,
            st.themed_text(
                page,
                "说明：Flet 主题与原版 ttkbootstrap 主题名不同，此处仅切换明暗。",
                size=12,
                muted=True,
            ),
        ]
    )

    panel = st.themed_panel(
        page,
        padding=16,
        content=ft.Column(
            controls=settings_controls,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        expand=True,
    )
    return panel, theme_dd
