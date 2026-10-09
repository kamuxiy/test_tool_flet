# -*- coding: utf-8 -*-
"""
测试工具箱 — Flet 版主程序
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Optional


def _app_root() -> Path:
    """开发：main.py 所在目录；PyInstaller 单文件：解压目录 _MEIPASS。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


_ROOT = _app_root()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 开发：多语言数据在上级 test_tool/assets（与 subtools.language_view 一致）
if not getattr(sys, "frozen", False):
    _dev_repo = Path(__file__).resolve().parent.parent
    if (_dev_repo / "assets" / "languages.py").is_file() and str(_dev_repo) not in sys.path:
        sys.path.insert(0, str(_dev_repo))
else:
    # 打包：--add-data 解压的 .py 未必能被 import 识别为包；在此注册 assets / assets.languages
    _bundle_assets = _ROOT / "assets"
    _lang_file = _bundle_assets / "languages.py"
    if not _lang_file.is_file():
        raise RuntimeError(
            f"打包不完整：未找到 {_lang_file}。"
            "请用 test_tool_flet\\打包为exe.bat 打包，且上级目录须有 test_tool\\assets。"
        )
    if "assets.languages" not in sys.modules:
        import importlib.util
        import types

        if "assets" not in sys.modules:
            _pkg = types.ModuleType("assets")
            _pkg.__path__ = [str(_bundle_assets)]  # type: ignore[attr-defined]
            sys.modules["assets"] = _pkg
        _spec = importlib.util.spec_from_file_location("assets.languages", _lang_file)
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules["assets.languages"] = _mod
            _spec.loader.exec_module(_mod)

import flet as ft
import pyperclip

from core import adb, test_wallpaper
from core.config import __version__
from core.user_prefs import get_output_dir

from ui import styles as st
from subtools.log_check_view import build_log_check_panel
from subtools.language_view import build_language_panel
from subtools.monkey_view import build_monkey_panel
from subtools.perfetto_view import build_perfetto_panel
from subtools.scrcpy_view import launch_scrcpy_tool_process, run_scrcpy_tool_window
from subtools.screenshots_view import build_screenshots_panel
from subtools.settings_view import build_settings_panel


_HOME_TAB_META = (
    ("LOG 导出", ft.Icons.FOLDER_ZIP),
    ("Install/Push", ft.Icons.UPLOAD_FILE),
    ("Pull", ft.Icons.DOWNLOAD),
    ("流畅性分析", ft.Icons.SPEED_OUTLINED),
    ("卡顿检测", ft.Icons.MONITOR_HEART_OUTLINED),
    ("添加测试机测试壁纸", ft.Icons.IMAGE_OUTLINED),
    ("埋点", ft.Icons.ANALYTICS_OUTLINED),
    ("充电", ft.Icons.BATTERY_CHARGING_FULL),
)


def _dropdown_option(text: str):
    try:
        return ft.dropdown.Option(text)
    except AttributeError:
        return ft.DropdownOption(key=text, text=text)


def _snack(page: ft.Page, msg: str):
    page.snack_bar = ft.SnackBar(ft.Text(msg), open=True)
    page.update()


def _open_log_dir():
    log_dir = str(get_output_dir("log_export"))
    os.makedirs(log_dir, exist_ok=True)
    p = os.path.normpath(log_dir)
    if sys.platform == "win32":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


# 与仓库内目录 test_tool_flet/scrcpy-win64-v2.7 一致；打包时用 --add-data 一并解压到 _MEIPASS
SCRCPY_BUNDLE_DIR = "scrcpy-win64-v2.7"


def _bundled_scrcpy_exe() -> Path:
    return _ROOT / SCRCPY_BUNDLE_DIR / "scrcpy.exe"


def _resolve_scrcpy_exe() -> Optional[str]:
    bundled = _bundled_scrcpy_exe()
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


def _launch_scrcpy(serial: Optional[str] = None) -> Optional[str]:
    """启动内置/ PATH 中的 scrcpy 投屏；失败返回提示文案，成功返回 None。"""
    exe = _resolve_scrcpy_exe()
    if not exe:
        return (
            f"未找到投屏程序。请将 {SCRCPY_BUNDLE_DIR} 放在本工具目录下，"
            "或将 scrcpy 加入系统 PATH。"
        )
    cmd = [exe]
    s = (serial or "").strip()
    if s and s not in ("没有设备", "有多个设备，请选择一个"):
        cmd.extend(["-s", s])
    try:
        # 工作目录设为 scrcpy 目录，确保同目录 DLL / 资源可被加载
        # Win32：CREATE_NO_WINDOW，避免打包 exe 拉起投屏时额外弹出 conhost 黑框
        subprocess.Popen(
            cmd,
            cwd=str(Path(exe).parent),
            **adb._popen_kwargs(),
        )
    except OSError as e:
        return f"启动投屏失败: {e}"
    return None


def _win32_tk_pick_files(multiple: bool = True) -> list[str]:
    """Windows：用 tkinter 原生文件对话框，规避 Flet FilePicker pick_files 偶发 10s 超时。"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    try:
        if multiple:
            sel = filedialog.askopenfilenames(parent=root, title="选择要安装/上传的文件")
            return list(sel) if sel else []
        one = filedialog.askopenfilename(parent=root, title="选择文件")
        return [one] if one else []
    finally:
        root.destroy()


def _win32_tk_pick_directory() -> Optional[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    try:
        d = filedialog.askdirectory(parent=root, title="选择本机保存目录")
        return d if d else None
    finally:
        root.destroy()


async def main(page: ft.Page):
    page.title = f"测试工具箱 (Flet) v{__version__}"
    page.theme_mode = ft.ThemeMode.DARK
    # Flet View 默认 padding=10，会在窗体四周留出空隙，像一圈黑边；贴边需清零
    page.padding = 0
    page.spacing = 0
    page.bgcolor = st.get_palette(page).editor_bg
    _app_theme = ft.Theme(font_family=st.FONT_FAMILY_UI, use_material3=True)
    page.theme = _app_theme
    page.dark_theme = _app_theme
    page.window.width = 1280
    page.window.height = 780
    page.window.min_width = 1024
    page.window.min_height = 640
    page.window.frameless = True
    page.window.shadow = False
    page.window.bgcolor = st.get_palette(page).editor_bg

    ui_hooks: dict = {"apply_chrome": lambda: None}
    view_state: dict[str, str] = {"key": "home"}
    theme_roots: list[ft.Control] = []
    window_shell: ft.Container | None = None

    def theme_toggle(_=None):
        page.theme_mode = (
            ft.ThemeMode.LIGHT if page.theme_mode == ft.ThemeMode.DARK else ft.ThemeMode.DARK
        )
        ui_hooks["apply_chrome"]()

    install_paths: list[str] = []
    state_save_sn: dict[str, str] = {"sn": ""}
    sn_dd = SimpleNamespace(value=None, options=[])
    _device_cache: dict[str, dict[str, str]] = {}
    _device_menu_open = {"v": False}
    _device_rows: dict[str, ft.Control] = {}

    def _device_icon(kind: str):
        if kind == "watch":
            return ft.Icons.WATCH_OUTLINED
        if kind == "tablet":
            return ft.Icons.TABLET_MAC_OUTLINED
        return ft.Icons.SMARTPHONE_OUTLINED

    def _device_kind_label(kind: str) -> str:
        return {"watch": "手表", "tablet": "平板", "phone": "手机"}.get(kind, "手机")

    def _adb_status_kind(summary: str) -> str:
        if summary in ("设备连接正常", "多个设备连接"):
            return "ok"
        if summary in ("无设备连接", "设备连接异常"):
            return "warn"
        if summary == "无ADB环境":
            return "fail"
        return "warn"

    def _adb_status_color(summary: str) -> str:
        k = _adb_status_kind(summary)
        if k == "ok":
            return st.SUCCESS
        if k == "fail":
            return st.DANGER
        return st.WARNING

    def _glow_dot(color: str) -> ft.Container:
        return ft.Container(
            width=10,
            height=10,
            border_radius=999,
            bgcolor=color,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=10,
                color=ft.Colors.with_opacity(0.55, color),
                offset=ft.Offset(0, 0),
            ),
        )

    adb_summary_state = {"summary": "…"}
    adb_led = _glow_dot(st.WARNING)
    adb_label = st.themed_text(page, "ADB: …", size=13, muted=True)
    selected_device_icon = ft.Icon(
        ft.Icons.DEVICES_OTHER_OUTLINED, size=18, color=st.get_palette(page).field_label
    )
    selected_device_title = st.themed_text(page, "未选择设备", size=13, weight=ft.FontWeight.W_500)
    selected_device_sn = st.themed_text(page, "SN：—", size=11, muted=True)
    selected_device_ota = st.themed_text(page, "OTA：—", size=11, muted=True)
    device_dropdown_chevron = ft.Icon(
        ft.Icons.ARROW_DROP_DOWN, size=20, color=st.get_palette(page).field_label
    )
    device_menu_col = ft.Column(spacing=6, tight=True)
    # 浮层必须用不透明底色；若挂在普通 Column 里会被下方按钮盖住，看起来像半透明。
    device_menu_box = ft.Container(
        visible=False,
        width=420,
        bgcolor=st.get_palette(page).editor_bg,
        border=ft.Border.all(1, st.get_palette(page).field_border),
        border_radius=10,
        padding=ft.Padding.all(8),
        opacity=1,
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=18,
            color=ft.Colors.with_opacity(0.35, "#000000"),
            offset=ft.Offset(0, 6),
        ),
        content=device_menu_col,
    )

    def _selected_detail() -> dict[str, str]:
        sn = (sn_dd.value or "").strip()
        if sn and sn in _device_cache:
            return _device_cache[sn]
        return {"sn": "", "ota": "", "kind": "unknown", "model": "", "project_code": ""}

    def _sync_selected_device_card() -> None:
        info = _selected_detail()
        pal = st.get_palette(page)
        if info.get("sn"):
            selected_device_card.bgcolor = pal.rail_select_bg
            selected_device_card.border = ft.Border.all(1, pal.field_border_focus)
            selected_device_icon.name = _device_icon(info.get("kind", "phone"))
            selected_device_icon.color = pal.field_border_focus
            title = f"{info.get('project_code') or '-----'} · {info.get('model') or info.get('product') or info['sn']}"
            selected_device_title.value = title
            selected_device_sn.value = f"SN：{info['sn']}"
            selected_device_ota.value = f"OTA：{info.get('ota') or '—'}"
        else:
            selected_device_card.bgcolor = pal.field_surface
            selected_device_card.border = ft.Border.all(1, pal.field_border)
            selected_device_icon.name = ft.Icons.DEVICES_OTHER_OUTLINED
            selected_device_icon.color = pal.field_label
            selected_device_title.value = "未选择设备"
            selected_device_sn.value = "SN：—"
            selected_device_ota.value = "OTA：—"

    def _close_device_menu() -> None:
        _device_menu_open["v"] = False
        device_dropdown_chevron.name = ft.Icons.ARROW_DROP_DOWN
        device_menu_box.visible = False

    def _render_device_menu() -> None:
        device_menu_col.controls.clear()
        opts = list(sn_dd.options or [])
        if not opts:
            device_menu_col.controls.append(
                st.themed_text(page, "当前未检测到设备", size=12, muted=True)
            )
        else:
            for sn in opts:
                info = _device_cache.get(
                    sn,
                    {"sn": sn, "ota": "", "kind": "phone", "model": "", "project_code": ""},
                )
                is_sel = sn == (sn_dd.value or "")
                pal = st.get_palette(page)
                title = f"{info.get('project_code') or '-----'} · {info.get('model') or info.get('product') or sn}"
                row = ft.Container(
                    border_radius=8,
                    bgcolor=pal.rail_select_bg if is_sel else pal.field_surface,
                    border=ft.Border.all(1, pal.field_border_focus if is_sel else pal.field_border),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                    ink=True,
                    on_click=lambda e, s=sn: _pick_device(s),
                    content=ft.Row(
                        [
                            ft.Icon(
                                _device_icon(info.get("kind", "phone")),
                                size=20,
                                color=pal.field_border_focus if is_sel else pal.field_label,
                            ),
                            ft.Column(
                                [
                                    st.themed_text(page, title, size=13, weight=ft.FontWeight.W_500),
                                    st.themed_text(
                                        page,
                                        f"SN：{info.get('sn', sn)}",
                                        size=11,
                                        muted=True,
                                    ),
                                    st.themed_text(
                                        page,
                                        f"OTA：{info.get('ota') or '—'}",
                                        size=11,
                                        muted=True,
                                    ),
                                ],
                                spacing=2,
                                expand=True,
                                tight=True,
                            ),
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE if is_sel else ft.Icons.RADIO_BUTTON_UNCHECKED,
                                size=18,
                                color=st.SUCCESS if is_sel else pal.field_label,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
                _device_rows[sn] = row
                device_menu_col.controls.append(row)
        device_menu_box.visible = _device_menu_open["v"]

    def _toggle_device_menu(_=None) -> None:
        _device_menu_open["v"] = not _device_menu_open["v"]
        device_dropdown_chevron.name = (
            ft.Icons.ARROW_DROP_UP if _device_menu_open["v"] else ft.Icons.ARROW_DROP_DOWN
        )
        _render_device_menu()
        page.update()

    def _pick_device(sn: str) -> None:
        sn_dd.value = sn
        _sync_selected_device_card()
        _close_device_menu()
        _render_device_menu()
        page.update()

    selected_device_card = ft.Container(
        width=420,
        border_radius=10,
        bgcolor=st.get_palette(page).field_surface,
        border=ft.Border.all(1, st.get_palette(page).field_border),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        ink=True,
        on_click=_toggle_device_menu,
        content=ft.Row(
            [
                selected_device_icon,
                ft.Column(
                    [selected_device_title, selected_device_sn, selected_device_ota],
                    spacing=1,
                    expand=True,
                    tight=True,
                ),
                device_dropdown_chevron,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )
    status_badge = st.themed_text(page, "运行结果 · 就绪", size=13, weight=ft.FontWeight.W_500)
    # 「End：」时间行不写入结果框，显示在运行结果右侧（见 append_lines）
    end_time_banner = st.themed_text(page, "", size=12, muted=True, opacity=0.92)

    # ListView + Text：内容增高会触发 auto_scroll；TextField 改 value 时外层 Column 往往不贴底
    _opal0 = st.get_palette(page)
    _output_text = ft.Text(
        value="",
        selectable=True,
        size=13,
        color=_opal0.field_text,
        font_family=st.FONT_FAMILY_MONO,
        data={"_flet_theme": "output_log_text"},
    )

    class _OutputProxy:
        @property
        def value(self) -> str:
            return _output_text.value or ""

        @value.setter
        def value(self, v: str | None) -> None:
            _output_text.value = v or ""

    output = _OutputProxy()

    # follow=True：新日志自动滚到最新；用户上翻后变 False；再滚回底部恢复 True
    _output_tail = {"follow": True, "pinning": False}
    _BOTTOM_EPS = 48.0

    def _sync_output_autoscroll() -> None:
        output_scroller.auto_scroll = bool(_output_tail["follow"])

    def _on_output_scroll(e: ft.OnScrollEvent):
        if _output_tail["pinning"]:
            return
        try:
            max_ext = float(e.max_scroll_extent or 0)
            pixels = float(e.pixels or 0)
        except (TypeError, ValueError):
            return
        at_bottom = max_ext <= 0 or pixels >= (max_ext - _BOTTOM_EPS)
        if at_bottom:
            _output_tail["follow"] = True
            _sync_output_autoscroll()
            return
        # 仅在明确上翻时取消跟随；忽略布局阶段 pixels=0 的噪声
        delta = getattr(e, "scroll_delta", None)
        if delta is not None and delta < 0:
            _output_tail["follow"] = False
            _sync_output_autoscroll()

    output_scroller = ft.ListView(
        [_output_text],
        expand=True,
        spacing=0,
        padding=0,
        auto_scroll=True,
        on_scroll=_on_output_scroll,
        scroll_interval=50,
    )

    _opal = st.get_palette(page)
    output_frame = ft.Container(
        expand=True,
        bgcolor=_opal.output_surface,
        border=ft.Border.all(1, _opal.output_border),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=output_scroller,
        data={"_flet_theme": "panel_bg", "_flet_fill_output": True},
    )

    output_status_state: dict[str, str] = {"k": "neutral"}

    def set_status(title: str):
        status_badge.value = f"运行结果 · {title}"
        output_status_state["k"] = st.status_kind_from_title(title)
        st.apply_output_status_border(page, output_frame, output_status_state["k"])

    st.apply_output_status_border(page, output_frame, "neutral")

    async def _pin_output_to_latest_async(*, force: bool = False):
        """用户在底部（或强制）时滚到最新行；上翻查看历史时不抢滚动。"""
        if not force and not _output_tail["follow"]:
            return
        _output_tail["pinning"] = True
        try:
            _output_tail["follow"] = True
            _sync_output_autoscroll()
            page.update()
            await asyncio.sleep(0.05)
            try:
                await output_scroller.scroll_to(offset=-1, duration=0)
            except Exception:
                pass
            page.update()
        finally:
            _output_tail["pinning"] = False
            _output_tail["follow"] = True
            _sync_output_autoscroll()

    def _pin_output_to_latest_sync(*, force: bool = False):
        if not force and not _output_tail["follow"]:
            return
        _output_tail["pinning"] = True
        try:
            _output_tail["follow"] = True
            _sync_output_autoscroll()
            page.update()

            async def _scroll() -> None:
                try:
                    await output_scroller.scroll_to(offset=-1, duration=0)
                except Exception:
                    pass

            try:
                page.run_task(_scroll)
            except Exception:
                pass
        finally:
            _output_tail["pinning"] = False
            _output_tail["follow"] = True
            _sync_output_autoscroll()

    def _schedule_pin_output_to_latest(*, force: bool = False):
        if not force and not _output_tail["follow"]:
            return
        _sync_output_autoscroll()
        try:
            asyncio.get_running_loop().create_task(_pin_output_to_latest_async(force=force))
        except RuntimeError:
            _pin_output_to_latest_sync(force=force)

    _END_LINE_PREFIX = "End："

    def _split_end_banner_lines(raw: list[str]) -> tuple[list[str], str | None]:
        body: list[str] = []
        banner: str | None = None
        for ln in raw:
            if ln.strip().startswith(_END_LINE_PREFIX):
                banner = ln.strip()
            else:
                body.append(ln)
        return body, banner

    def append_lines(lines: list[str], clear: bool = False, *, skip_async_scroll: bool = False):
        body, end_banner = _split_end_banner_lines(lines)
        text = "\n".join(body)
        if clear or not output.value:
            output.value = text
            end_time_banner.value = end_banner or ""
            # 新一轮输出：默认跟随最新行
            if clear:
                _output_tail["follow"] = True
                _sync_output_autoscroll()
        else:
            if text:
                output.value = (output.value.rstrip() + "\n" + text).strip()
            if end_banner is not None:
                end_time_banner.value = end_banner
        page.update()
        if not skip_async_scroll:
            _schedule_pin_output_to_latest(force=bool(clear) or bool(_output_tail["follow"]))

    _adb_ui_snap: tuple[tuple[str, ...], str, str | None, str] | None = None

    async def refresh_sn(_=None, *, force: bool = False):
        nonlocal _adb_ui_snap
        cur = sn_dd.value or ""
        opts, _show, summary = await asyncio.to_thread(adb.refresh_sn_state, cur)
        if len(opts) == 1:
            new_val: str | None = opts[0]
        elif not opts:
            new_val = None
        else:
            # 多设备时保留用户已选 SN（原版逻辑）；勿在每次刷新时清空下拉
            new_val = cur if cur in opts else None
        new_label = f"ADB: {summary}"
        snap = (tuple(opts), summary, new_val, new_label)
        if not force and snap == _adb_ui_snap:
            return
        _adb_ui_snap = snap
        sn_dd.options = list(opts)
        sn_dd.value = new_val
        adb_summary_state["summary"] = summary
        adb_led.bgcolor = _adb_status_color(summary)
        adb_led.shadow = ft.BoxShadow(
            spread_radius=1,
            blur_radius=10,
            color=ft.Colors.with_opacity(0.55, _adb_status_color(summary)),
            offset=ft.Offset(0, 0),
        )
        adb_label.value = new_label
        old_keys = set(_device_cache.keys())
        new_keys = set(opts)
        for gone in old_keys - new_keys:
            _device_cache.pop(gone, None)
        for sn in opts:
            if force or sn not in _device_cache:
                _device_cache[sn] = await asyncio.to_thread(adb.get_device_brief, sn)
        _sync_selected_device_card()
        _render_device_menu()
        page.update()

    async def refresh_sn_manual(_):
        """工具栏「自动获取」：即使状态未变也刷新界面，避免误以为无响应。"""
        await refresh_sn(force=True)

    # —— Install / Push —— #
    install_list_col = ft.Column(spacing=4, tight=True)

    def rebuild_install_list():
        install_list_col.controls.clear()
        if not install_paths:
            install_list_col.controls.append(
                st.themed_text(
                    page,
                    "点击下方「添加文件」选择 APK/文件，或粘贴路径后添加。",
                    size=12,
                    muted=True,
                )
            )
        else:
            for path in list(install_paths):

                def rm(p=path):
                    if p in install_paths:
                        install_paths.remove(p)
                    rebuild_install_list()
                    page.update()

                install_list_col.controls.append(
                    ft.Row(
                        [
                            st.themed_text(page, path, expand=True, selectable=True, size=12),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                tooltip="移除",
                                on_click=lambda e, f=rm: f(),
                            ),
                        ],
                        tight=True,
                    )
                )

    manual_path = st.themed_text_field(page, label="手动路径", expand=True)

    def add_manual_path(_):
        p = (manual_path.value or "").strip().strip('"')
        if not p:
            _snack(page, "请输入路径")
            return
        if p not in install_paths:
            install_paths.append(p)
        manual_path.value = ""
        rebuild_install_list()
        page.update()

    async def _run_adb_ops_with_live_progress(
        ops: list[tuple[str, list[str]]], *, busy_title: str = "传输中"
    ):
        """执行 adb argv 列表并在右侧结果框实时刷新进度。"""
        set_status(busy_title)
        append_lines(["准备开始…"], clear=True)
        page.update()
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        stop = object()

        async def _pump():
            while True:
                item = await q.get()
                if item is stop:
                    break
                msg = item[1] if isinstance(item, tuple) else str(item)
                output.value = msg
                page.update()
                _schedule_pin_output_to_latest(force=True)

        def _on_prog(msg: str):
            asyncio.run_coroutine_threadsafe(q.put(("prog", msg)), loop)

        def work():
            return adb.run_adb_argv_chain_with_progress(ops, on_progress=_on_prog)

        pump = asyncio.create_task(_pump())
        try:
            title, lines = await asyncio.to_thread(work)
        finally:
            await q.put(stop)
            await pump
        set_status(title)
        append_lines(lines, clear=True)
        page.update()

    async def run_install(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        if not install_paths:
            _snack(page, "请先添加要安装的文件")
            return
        ops = [
            (f"安装 {Path(f).name}", ["adb", "-s", sn, "install", "-r", "-t", "-d", f])
            for f in install_paths
        ]
        await _run_adb_ops_with_live_progress(ops, busy_title="安装中")

    async def run_push(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        if not install_paths:
            _snack(page, "请先添加要上传的文件")
            return
        ops = [
            (
                f"上传 {Path(f).name}",
                ["adb", "-s", sn, "push", f, "sdcard/Download/"],
            )
            for f in install_paths
        ]
        await _run_adb_ops_with_live_progress(ops, busy_title="上传中")

    fp_files: Optional[ft.FilePicker] = None
    if sys.platform != "win32":
        fp_files = ft.FilePicker()
        page.overlay.append(fp_files)

    async def pick_install_files(_):
        if sys.platform == "win32":
            paths = await asyncio.to_thread(_win32_tk_pick_files, True)
            for p in paths:
                if p and p not in install_paths:
                    install_paths.append(p)
        else:
            assert fp_files is not None
            files = await fp_files.pick_files(allow_multiple=True)
            if files:
                for f in files:
                    p = f.path or f.name
                    if p and p not in install_paths:
                        install_paths.append(p)
        rebuild_install_list()
        page.update()

    rebuild_install_list()

    # —— Pull —— #
    pull_local = st.themed_text_field(page, label="本机目录", expand=True)
    pull_remote = st.themed_text_field(page, label="设备路径", expand=True)

    fp_pull_dir: Optional[ft.FilePicker] = None
    if sys.platform != "win32":
        fp_pull_dir = ft.FilePicker()
        page.overlay.append(fp_pull_dir)

    async def pick_pull_dir_handler(_):
        if sys.platform == "win32":
            path = await asyncio.to_thread(_win32_tk_pick_directory)
        else:
            assert fp_pull_dir is not None
            path = await fp_pull_dir.get_directory_path()
        if path:
            pull_local.value = path
            page.update()

    async def run_pull(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        loc = (pull_local.value or "").strip()
        rem = (pull_remote.value or "").strip()
        if not loc or not rem:
            _snack(page, "请填写本机目录与设备路径")
            return
        ops = [
            (
                f"下载 {Path(rem).name or rem}",
                ["adb", "-s", sn, "pull", rem, loc],
            )
        ]
        await _run_adb_ops_with_live_progress(ops, busy_title="下载中")

    # —— LOG —— #
    log_pick = st.themed_dropdown(page, label="选择 LOG 目录（先查询 LOG）", width=400, options=[])

    async def run_search_log(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        state_save_sn["sn"] = sn
        os.makedirs(str(get_output_dir("log_export")), exist_ok=True)

        def work():
            return adb.run_command_chain(adb.search_log_command(sn))

        title, lines = await asyncio.to_thread(work)
        set_status(title)
        append_lines(lines, clear=True)
        names = []
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith("$ ") or s.startswith("End："):
                continue
            names.append(s)
        log_pick.options = [_dropdown_option(n) for n in names]
        if names:
            log_pick.value = names[0]
        page.update()

    async def run_pull_log(zip_after: bool):
        name = log_pick.value
        if not name:
            _snack(page, "请先查询 LOG 并选择目录")
            return
        if str(name).startswith("(") or str(name).startswith("End"):
            _snack(page, "请选择有效的 LOG 目录")
            return
        save_sn = state_save_sn.get("sn") or ""
        if not save_sn:
            _snack(page, "请先点击查询 LOG")
            return
        local_base = str(get_output_dir("log_export"))
        if os.path.exists(os.path.join(local_base, str(name))):
            set_status("失败")
            append_lines(["文件已存在"], clear=False)
            page.update()
            return
        phone_log_path = f"sdcard/android/data/com.oplus.logkit/files/log/{name}"
        total = await asyncio.to_thread(adb.get_remote_folder_size, save_sn, phone_log_path)

        set_status("传输中")

        loop = asyncio.get_running_loop()
        dl_q: asyncio.Queue = asyncio.Queue()
        dl_stop = object()

        async def _pump_download_progress():
            while True:
                item = await dl_q.get()
                if item is dl_stop:
                    break
                received, total_b = item
                if total_b and total_b > 0:
                    pct = str(received / total_b * 100)
                else:
                    pct = "0"
                output.value = f"当前传输进度：{pct}%\n{received}\n{total_b}"
                page.update()
                _schedule_pin_output_to_latest(force=True)

        def _put_dl(received: int, total_b: int):
            asyncio.run_coroutine_threadsafe(dl_q.put((received, total_b)), loop)

        def run_dl():
            return adb.download_log_with_progress(
                save_sn, phone_log_path, str(name), total, _put_dl
            )

        dl_pump = asyncio.create_task(_pump_download_progress())
        try:
            ok, lines = await asyncio.to_thread(run_dl)
        finally:
            await dl_q.put(dl_stop)
            await dl_pump

        set_status("成功" if ok else "失败")
        append_lines(lines, clear=True)
        if ok and zip_after:
            set_status("压缩中")
            folder = os.path.join(local_base, str(name))
            download_snap = output.value or ""

            zip_q: asyncio.Queue = asyncio.Queue()
            zip_stop = object()

            async def _pump_zip_progress():
                while True:
                    item = await zip_q.get()
                    if item is zip_stop:
                        break
                    kind = item[0]
                    if kind == "msg":
                        output.value = (output.value or "").rstrip() + "\n" + item[1]
                    elif kind == "zc":
                        _, i, n = item
                        pct = str(i / n * 100) if n else "0"
                        output.value = (
                            download_snap.rstrip()
                            + "\n开始压缩...\n"
                            + f"当前压缩进度：{pct}%\n{i}\n{n}"
                        )
                    page.update()
                    _schedule_pin_output_to_latest(force=True)

            def _put_zip_msg(m: str):
                asyncio.run_coroutine_threadsafe(zip_q.put(("msg", m)), loop)

            def _put_zc(i: int, n: int):
                asyncio.run_coroutine_threadsafe(zip_q.put(("zc", i, n)), loop)

            def run_compress():
                return adb.compress_folder_to_zip(
                    folder, _put_zip_msg, on_zip_tick=_put_zc
                )

            zip_pump = asyncio.create_task(_pump_zip_progress())
            try:
                extra = await asyncio.to_thread(run_compress)
            finally:
                await zip_q.put(zip_stop)
                await zip_pump

            if extra == ["无文件可压缩"]:
                append_lines(extra, clear=False)
            elif len(extra) >= 2:
                append_lines(extra[-2:], clear=False)
            set_status("压缩完成")
        page.update()

    async def pull_log_plain(_):
        await run_pull_log(False)

    async def pull_log_zip(_):
        await run_pull_log(True)

    async def add_wallpaper_clicked(_):
        sn = sn_dd.value or ""
        third = wallpaper_third_line.value or ""
        set_status("处理中")
        page.update()
        title, lines = await asyncio.to_thread(
            test_wallpaper.generate_test_wallpaper_and_push, sn, third
        )
        set_status(title)
        append_lines(lines, clear=True)
        page.update()

    async def clear_current_app_data_clicked(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return

        def peek():
            return adb.get_foreground_package_activity(sn)

        pkg, activity, dbg = await asyncio.to_thread(peek)
        if not pkg:
            _snack(page, "无法获取当前前台包名，请进入目标应用界面后重试。")
            return

        async def on_confirm(e):
            page.pop_dialog()
            page.update()
            set_status("运行中")
            page.update()

            def work():
                return adb.pm_clear_package_data(sn, pkg)

            title, out_lines = await asyncio.to_thread(work)
            head = [
                "【清除当前应用数据】",
                *dbg,
                f"目标包名: {pkg}",
                f"解析页面(Activity): {activity or '—'}",
            ]
            set_status(title)
            append_lines(head + out_lines, clear=True)
            page.update()

        async def on_cancel(e):
            page.pop_dialog()
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("确认清除应用数据"),
            content=ft.Text(
                f"将执行 adb shell pm clear，清除包「{pkg}」的全部应用数据（不可撤销）。\n"
                f"当前解析页面: {activity or '—'}\n\n是否继续？"
            ),
            actions=[
                ft.TextButton("取消", on_click=on_cancel),
                ft.FilledButton("清除", on_click=on_confirm),
            ],
        )
        page.show_dialog(dlg)
        page.update()

    # —— 埋点 Tab 控件 —— #
    env_dd = st.themed_dropdown(
        page,
        label="环境类别",
        options=[_dropdown_option("测试环境"), _dropdown_option("正式环境")],
        value="测试环境",
        width=200,
    )
    region_dd = st.themed_dropdown(
        page,
        label="区域",
        options=[
            _dropdown_option("国内上报"),
            _dropdown_option("海外上报"),
            _dropdown_option("印度上报"),
        ],
        value="国内上报",
        width=200,
    )

    async def run_chain_ui(make_cmds):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        cmds = make_cmds(sn)
        if not cmds:
            _snack(page, "无可用命令")
            return

        def work():
            return adb.run_command_chain(cmds)

        title, lines = await asyncio.to_thread(work)
        set_status(title)
        append_lines(lines, clear=True)
        page.update()

    def acmd(make_cmds):
        async def _handler(_):
            await run_chain_ui(make_cmds)

        return _handler

    async def dcs_change_clicked(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        cmds = adb.build_dcs_change_env(sn, env_dd.value or "", region_dd.value or "")

        def work():
            return adb.run_command_chain(cmds)

        title, lines = await asyncio.to_thread(work)
        set_status(title)
        append_lines(lines, clear=True)
        page.update()

    async def dcs_auto_clicked(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return

        def p1():
            return adb.dcs_auto_test_phase1(sn)

        ok, st, lines = await asyncio.to_thread(p1)
        set_status(st)
        append_lines(lines, clear=True, skip_async_scroll=True)
        await _pin_output_to_latest_async(force=True)
        if not ok:
            return

        async def on_confirm(e):
            page.pop_dialog()
            page.update()

            def p2():
                return adb.dcs_auto_test_phase2(sn)

            ok2, st2, lines2 = await asyncio.to_thread(p2)
            set_status(st2)
            append_lines(lines2, clear=False, skip_async_scroll=True)
            await _pin_output_to_latest_async(force=True)

        async def on_cancel(e):
            page.pop_dialog()
            append_lines(["用户取消操作"], clear=False, skip_async_scroll=True)
            await _pin_output_to_latest_async(force=True)

        # Flet 0.8x：须用 show_dialog / pop_dialog，勿再用已移除的 page.dialog
        wait_dlg = ft.AlertDialog(
            title=ft.Text("提示"),
            content=ft.Text("请现在在测试机上进行操作，完成后点击确定。"),
            actions=[
                ft.TextButton("取消", on_click=on_cancel),
                ft.FilledButton("确定", on_click=on_confirm),
            ],
        )
        page.show_dialog(wait_dlg)
        page.update()

    # —— 充电 —— #
    charge_dd = st.themed_dropdown(
        page,
        label="充电状态",
        options=[_dropdown_option(x) for x in adb.CHARGE_ITEMS],
        width=420,
    )

    async def charge_run(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        item = charge_dd.value
        if not item:
            _snack(page, "请选择充电状态")
            return
        cmds = adb.build_charge_commands(sn, str(item))
        if not cmds:
            _snack(page, "类型不能为空")
            return

        def work():
            return adb.run_command_chain(cmds)

        title, lines = await asyncio.to_thread(work)
        set_status(title)
        append_lines(lines, clear=True)
        page.update()

    # —— 基本操作 —— #
    fill_mb = st.themed_text_field(page, label="填充 MB", value="10", width=88, height=32)

    async def device_info(_):
        sn = sn_dd.value or ""

        def work():
            return adb.get_device_info_lines(sn)

        title, lines = await asyncio.to_thread(work)
        set_status(title)
        append_lines(lines, clear=True)
        page.update()

    async def fill_storage_run(_):
        sn = sn_dd.value or ""
        err = adb.validate_sn(sn)
        if err:
            _snack(page, err)
            return
        n = (fill_mb.value or "10").strip()
        cmds = [
            f"adb -s {sn} shell dd if=/dev/zero of=sdcard/fill_storage_{n}MB bs=1m count={n}"
        ]

        def work():
            return adb.run_command_chain(cmds)

        title, lines = await asyncio.to_thread(work)
        set_status(title)
        append_lines(lines, clear=True)
        page.update()

    def copy_output(_):
        body = (output.value or "").rstrip()
        end_b = (end_time_banner.value or "").strip()
        if body and end_b:
            pyperclip.copy(body + "\n" + end_b)
        elif body:
            pyperclip.copy(body)
        else:
            pyperclip.copy(end_b)
        _snack(page, "输出已复制到剪贴板")

    def clear_output(_):
        output.value = ""
        end_time_banner.value = ""
        _output_tail["follow"] = True
        set_status("就绪")
        page.update()
        _schedule_pin_output_to_latest(force=True)

    async def on_title_min(_):
        page.window.minimized = True
        page.update()

    async def on_title_close(_):
        await page.window.close()

    title_label = st.themed_text(
        page,
        f"测试工具箱 (Flet) v{__version__}",
        size=14,
        weight=ft.FontWeight.W_500,
    )
    _tpal = st.get_palette(page)
    title_bar_btn_min = ft.IconButton(
        icon=ft.Icons.MINIMIZE,
        tooltip="最小化",
        icon_size=20,
        icon_color=_tpal.field_text,
        style=ft.ButtonStyle(bgcolor=ft.Colors.TRANSPARENT),
        on_click=on_title_min,
    )
    title_bar_btn_close = ft.IconButton(
        icon=ft.Icons.CLOSE,
        tooltip="关闭",
        icon_size=20,
        icon_color=st.DANGER,
        style=ft.ButtonStyle(bgcolor=ft.Colors.TRANSPARENT),
        on_click=on_title_close,
    )
    wallpaper_third_line = st.themed_text_field(
        page,
        label="附加文案（可选，显示在 OTA/IMEI/机型/标志位之后）",
        expand=True,
    )

    custom_title_bar = ft.Container(
        bgcolor=_tpal.toolbar_bg,
        border=ft.Border.only(bottom=ft.BorderSide(1, _tpal.rail_divider)),
        padding=ft.Padding.only(right=2),
        content=ft.Row(
            [
                ft.WindowDragArea(
                    expand=True,
                    maximizable=True,
                    content=ft.Container(
                        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                        content=title_label,
                    ),
                ),
                title_bar_btn_min,
                title_bar_btn_close,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    # Flet 0.8x：Tabs = TabBar（标签） + TabBarView（内容），Tab 使用 label 而非 text
    perfetto_panel = build_perfetto_panel(page, snack=lambda m: _snack(page, m), append_lines=append_lines)

    # —— 卡顿检测 —— #
    def _jank_on_cmds(sn: str):
        return [
            f"adb -s {sn} wait-for-device",
            f"adb -s {sn} remount",
            f"adb -s {sn} shell setprop persist.oplus.qualityprotect.jankalertenabled true",
            f"adb -s {sn} reboot",
            f"adb -s {sn} wait-for-device",
            f"adb -s {sn} shell getprop persist.oplus.qualityprotect.jankalertenabled",
            f'adb -s {sn} shell logcat -d | findstr "JankAlertManager"',
        ]

    def _jank_check_cmds(sn: str):
        return [
            f"adb -s {sn} reboot",
            f"adb -s {sn} wait-for-device",
            f"adb -s {sn} shell ps -ef | findstr com.oplus.midas",
            f'adb -s {sn} shell logcat -d | findstr "JankAlertManager"',
        ]

    def _jank_off_cmds(sn: str):
        return [
            f"adb -s {sn} wait-for-device",
            f"adb -s {sn} remount",
            f"adb -s {sn} shell setprop persist.oplus.qualityprotect.jankalertenabled false",
            f"adb -s {sn} reboot",
            f"adb -s {sn} wait-for-device",
            f"adb -s {sn} shell getprop persist.oplus.qualityprotect.jankalertenabled",
            f'adb -s {sn} shell logcat -d | findstr "JankAlertManager"',
        ]

    jank_panel = st.themed_panel(
        page,
        padding=16,
        content=ft.Column(
            [
                st.themed_text(page, "卡顿检测", size=18, weight=ft.FontWeight.W_500),
                st.themed_text(
                    page,
                    "基于 persist.oplus.qualityprotect.jankalertenabled 属性开关丢帧检测，"
                    "命令与项目目录下同名 bat 文件一致。执行会重启手机，请确保设备已连接。",
                    size=12,
                    muted=True,
                ),
                st.btn_success("开启卡顿检测开关", icon=ft.Icons.POWER_SETTINGS_NEW, on_click=acmd(_jank_on_cmds)),
                st.btn_info_outline("重启手机并查看丢帧检测是否Ready", icon=ft.Icons.REFRESH, on_click=acmd(_jank_check_cmds)),
                st.btn_danger_outline("关闭卡顿检测开关", icon=ft.Icons.POWER_OFF, on_click=acmd(_jank_off_cmds)),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=12,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )

    dcs_panel = st.themed_panel(
            page,
            padding=16,
            content=ft.Column(
                [
                    st.btn_success(
                        "一键埋点测试（推荐）",
                        icon=ft.Icons.AUTO_AWESOME,
                        on_click=dcs_auto_clicked,
                    ),
                    st.themed_text(page, "手动埋点", weight=ft.FontWeight.W_500),
                    ft.Row(
                        [
                            st.btn_info_outline(
                                "快速确认环境",
                                on_click=acmd(
                                    lambda s: [
                                        f"adb -s {s} shell dumpsys activity provider DcsContentProvider env"
                                    ]
                                ),
                            ),
                            st.btn_info_outline(
                                "打开 debug 日志",
                                on_click=acmd(
                                    lambda s: [
                                        f"adb -s {s} shell dumpsys activity provider DcsContentProvider debug 1"
                                    ]
                                ),
                            ),
                            st.btn_info_outline(
                                "手动更新配置",
                                on_click=acmd(
                                    lambda s: [
                                        f"adb -s {s} shell dumpsys activity provider DcsContentProvider update config"
                                    ]
                                ),
                            ),
                            st.btn_info_outline(
                                "保存到数据库",
                                on_click=acmd(
                                    lambda s: [
                                        f"adb -s {s} shell dumpsys activity provider DcsContentProvider record data"
                                    ]
                                ),
                            ),
                            st.btn_info_outline(
                                "触发埋点上报",
                                on_click=acmd(
                                    lambda s: [
                                        f"adb -s {s} shell dumpsys activity provider DcsContentProvider upload StatisticData"
                                    ]
                                ),
                            ),
                        ],
                        spacing=8,
                        run_spacing=8,
                        wrap=True,
                    ),
                    st.themed_text(page, "切换测试环境", weight=ft.FontWeight.W_500),
                    ft.Row(
                        [env_dd, region_dd, st.btn_primary("切换", on_click=dcs_change_clicked)],
                        wrap=True,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
    charge_panel = st.themed_panel(
            page,
            padding=16,
            content=ft.Column(
                [
                    st.themed_text(
                        page,
                        "执行顺序建议：允许充电 → 禁止充电 → 按需改电量/类型。"
                        " 禁止充电后可断充、改充电类型等。",
                        size=12,
                        muted=True,
                    ),
                    ft.Row([charge_dd, st.btn_primary("执行", on_click=charge_run)], wrap=True),
                ],
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
    install_panel = st.themed_panel(
            page,
            padding=16,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            st.btn_info_outline(
                                "添加文件",
                                icon=ft.Icons.FILE_OPEN,
                                on_click=pick_install_files,
                            ),
                            st.btn_warning_outline(
                                "清空列表",
                                on_click=lambda _: (
                                    install_paths.clear(),
                                    rebuild_install_list(),
                                    page.update(),
                                ),
                            ),
                        ]
                    ),
                    ft.Container(
                        content=ft.Column([install_list_col], scroll=ft.ScrollMode.AUTO),
                        height=180,
                        border=ft.Border.all(1, st.get_palette(page).field_border),
                        border_radius=8,
                        padding=8,
                        data={"_flet_theme": "thin_border_box"},
                    ),
                    ft.Row([manual_path, st.btn_primary("加入列表", on_click=add_manual_path)]),
                    ft.Row(
                        [
                            st.btn_success("安装 install", on_click=run_install),
                            st.btn_info_outline("上传 push", on_click=run_push),
                        ]
                    ),
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
    pull_panel = st.themed_panel(
            page,
            padding=16,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            pull_local,
                            ft.IconButton(
                                icon=ft.Icons.FOLDER_OPEN,
                                tooltip="选择目录",
                                on_click=pick_pull_dir_handler,
                            ),
                        ],
                        expand=True,
                    ),
                    pull_remote,
                    st.btn_primary("下载 pull", on_click=run_pull),
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
    log_panel_home = st.themed_panel(
            page,
            padding=16,
            content=ft.Column(
                [
                    st.btn_primary("查询 LOG", on_click=run_search_log),
                    log_pick,
                    ft.Row(
                        [
                            st.btn_success("导出选中 LOG", on_click=pull_log_plain),
                            st.btn_info_outline("导出并压缩", on_click=pull_log_zip),
                        ]
                    ),
                    st.btn_info_outline(
                        "打开本机 LOG 目录",
                        icon=ft.Icons.FOLDER_OPEN,
                        on_click=lambda _: _open_log_dir(),
                    ),
                ],
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
    wallpaper_panel = st.themed_panel(
            page,
            padding=16,
            content=ft.Column(
                [
                    st.themed_text(
                        page,
                        "使用顶部下拉框所选 SN。将生成 1080×2352 壁纸（底色 #56585D、文字白色）："
                        "第 1 行为 OTA，第 2 行为 IMEI1，"
                        "第 3 行为机型 ro.product.name，"
                        "第 4 行为标志位 ro.oppo.regionmark，"
                        "第 5 行为下方输入框（可空）；完成后 adb push 到 /sdcard/DCIM。",
                        size=12,
                        muted=True,
                    ),
                    wallpaper_third_line,
                    ft.Row(
                        [
                            st.btn_primary(
                                "添加到手机",
                                icon=ft.Icons.IMAGE_OUTLINED,
                                on_click=add_wallpaper_clicked,
                            ),
                        ],
                        wrap=True,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                alignment=ft.MainAxisAlignment.START,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
    _tab_bodies = [
        log_panel_home,
        install_panel,
        pull_panel,
        perfetto_panel,
        jank_panel,
        wallpaper_panel,
        dcs_panel,
        charge_panel,
    ]
    assert len(_tab_bodies) == len(_HOME_TAB_META), "主页选项卡数量须与 _HOME_TAB_META 一致"

    # 使用原生 TabBar（原始高度）；scrollable 支持拖动与滚轮横向滚动标签
    home_tab_bar = ft.TabBar(
        scrollable=True,
        tabs=[ft.Tab(label=lab, icon=ico) for lab, ico in _HOME_TAB_META],
    )

    tabs = ft.Tabs(
        length=len(_HOME_TAB_META),
        expand=True,
        content=ft.Column(
            controls=[
                home_tab_bar,
                ft.TabBarView(expand=True, controls=_tab_bodies),
            ],
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )

    async def on_launch_scrcpy(_):
        """打开投屏工具窗口（原生 scrcpy 叠层 + 录屏）。"""
        err = await asyncio.to_thread(
            launch_scrcpy_tool_process,
            sn=sn_dd.value or "",
            app_root=_ROOT,
        )
        if err:
            _snack(page, err)

    # 标题行 + 工具栏 padding + 已选卡片高度；浮层 top 必须完全在卡片下方，避免重叠。
    _device_menu_top = {"v": 100}

    device_header_body = ft.Column(
        [
            ft.Row(
                [
                    st.themed_text(page, "设备与连接", weight=ft.FontWeight.W_500, size=16),
                    ft.Row(
                        [adb_led, adb_label],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        tight=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Row(
                [
                    selected_device_card,
                    st.btn_primary(
                        "自动获取",
                        icon=ft.Icons.REFRESH,
                        on_click=refresh_sn_manual,
                        height=36,
                    ),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ],
        spacing=6,
        alignment=ft.MainAxisAlignment.START,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    basic_ops_body = ft.Column(
        [
            st.themed_text(page, "基本操作", weight=ft.FontWeight.W_500, size=13),
            ft.Row(
                [
                    st.btn_success("获取设备信息", on_click=device_info, height=32),
                    st.btn_warning_outline(
                        "取消新机保护",
                        height=32,
                        on_click=acmd(
                            lambda s: [
                                f"adb -s {s} shell settings put system disable_device_protect true",
                                f"adb -s {s} shell settings put system protect_limit_time 1",
                            ]
                        ),
                    ),
                    st.btn_info_outline(
                        "解除系统 app 安装限制",
                        height=32,
                        on_click=acmd(
                            lambda s: [
                                f"adb -s {s} shell setprop debug.allow.persist.update true"
                            ]
                        ),
                    ),
                    st.btn_info_outline(
                        "获取包名",
                        height=32,
                        on_click=acmd(lambda s: [adb.get_package_cmd(s)]),
                    ),
                    st.btn_info_outline(
                        "启动投屏",
                        icon=ft.Icons.SCREEN_SHARE_OUTLINED,
                        height=32,
                        on_click=on_launch_scrcpy,
                        tooltip="打开投屏窗口（原生 scrcpy 叠层）",
                    ),
                ],
                spacing=6,
                run_spacing=4,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Row(
                [
                    st.btn_danger_outline(
                        "清除当前应用数据",
                        height=32,
                        on_click=clear_current_app_data_clicked,
                    ),
                    st.btn_danger_outline(
                        "刷机 (reboot edl)",
                        height=32,
                        on_click=acmd(lambda s: [f"adb -s {s} reboot edl"]),
                    ),
                    fill_mb,
                    st.btn_warning_outline(
                        "开始填充存储",
                        height=32,
                        on_click=fill_storage_run,
                    ),
                ],
                spacing=6,
                run_spacing=4,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ],
        spacing=4,
        tight=True,
        visible=True,
    )

    top_bar_body = ft.Column(
        [device_header_body, basic_ops_body],
        spacing=6,
        alignment=ft.MainAxisAlignment.START,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    # 工具栏上下 padding=8；浮层挂到整页 Stack，避免截图页隐藏「基本操作」后
    # 工具栏变矮、下拉被下方内容裁切/盖住。
    _TOOLBAR_PAD_Y = 8.0
    device_menu_layer = ft.Container(
        content=device_menu_box,
        left=16,
        top=_device_menu_top["v"],
    )

    def _layout_device_menu_layer(e=None) -> None:
        # toolbar pad + 标题行 ≈26 + spacing 6 + 卡片高度 + 4px 间隙
        card_h = float(getattr(e, "height", None) or 0)
        if card_h <= 0:
            card_h = 54.0
        top = _TOOLBAR_PAD_Y + 26.0 + 6.0 + card_h + 4.0
        if abs(top - _device_menu_top["v"]) > 0.5:
            _device_menu_top["v"] = top
            device_menu_layer.top = top
            if _device_menu_open["v"]:
                page.update()

    selected_device_card.on_size_change = _layout_device_menu_layer

    top_bar = st.themed_toolbar(
        page,
        padding=ft.Padding.symmetric(horizontal=16, vertical=8),
        content=top_bar_body,
    )

    workspace_content_slot = ft.Container(expand=True, content=tabs)

    home_col_body = ft.Column(
        [top_bar, st.themed_hairline(page), workspace_content_slot],
        expand=True,
        spacing=0,
        alignment=ft.MainAxisAlignment.START,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    # 设备下拉浮层盖住下方工作区（主页基本操作 / 截图页内容均可）
    home_col = ft.Stack(
        [home_col_body, device_menu_layer],
        expand=True,
        clip_behavior=ft.ClipBehavior.NONE,
    )

    _snack_fn = lambda m: _snack(page, m)
    monkey_panel = build_monkey_panel(
        page,
        get_sn=lambda: sn_dd.value or "",
        append_lines=append_lines,
        snack=_snack_fn,
    )
    def _language_end_banner(text: str):
        end_time_banner.value = text
        page.update()

    language_panel = build_language_panel(
        page,
        append_lines=append_lines,
        snack=_snack_fn,
        end_banner_callback=_language_end_banner,
    )
    log_panel = build_log_check_panel(page, snack=_snack_fn)
    screenshots_panel = build_screenshots_panel(
        page,
        get_sn=lambda: sn_dd.value or "",
        snack=_snack_fn,
    )
    settings_panel, settings_theme_dd = build_settings_panel(
        page,
        snack=_snack_fn,
        on_palette_change=lambda: ui_hooks["apply_chrome"](),
        on_theme_toggle=theme_toggle,
        on_dirs_applied=lambda: ui_hooks.get("on_dirs_applied", lambda: None)(),
    )

    workspace_body = ft.Container(
        expand=True,
        padding=0,
        alignment=ft.Alignment.TOP_LEFT,
        bgcolor=st.get_palette(page).editor_bg,
        content=home_col,
        data={"_flet_theme": "panel_bg"},
    )

    rail_items: dict[str, tuple[ft.Container, ft.IconButton]] = {}

    def select_view(key: str):
        view_state["key"] = key
        pal = st.get_palette(page)
        for k, (slot, btn) in rail_items.items():
            sel = k == key
            slot.bgcolor = pal.rail_select_bg if sel else None
            slot.border = (
                ft.Border.only(left=ft.BorderSide(3, pal.rail_accent)) if sel else None
            )
            btn.icon_color = pal.rail_icon_on if sel else pal.rail_icon

        show_log = key not in ("screenshots",)
        output_card.visible = show_log
        vdiv_mid.visible = show_log
        # 切页时收起 SN 下拉，避免错位
        if _device_menu_open["v"]:
            _close_device_menu()

        if key == "home":
            basic_ops_body.visible = True
            workspace_content_slot.content = tabs
            workspace_body.content = home_col
        elif key == "screenshots":
            basic_ops_body.visible = False
            workspace_content_slot.content = screenshots_panel
            workspace_body.content = home_col
        elif key == "monkey":
            workspace_body.content = monkey_panel
        elif key == "language":
            workspace_body.content = language_panel
        elif key == "settings":
            workspace_body.content = settings_panel
        page.update()

    rail_controls: list[ft.Control] = []
    for key, icon, tip in (
        ("home", ft.Icons.HOME_OUTLINED, "主页 · 设备与 ADB"),
        ("screenshots", ft.Icons.PHOTO_LIBRARY_OUTLINED, "查看截图"),
        ("monkey", ft.Icons.BUG_REPORT_OUTLINED, "AOSP Monkey"),
        ("language", ft.Icons.TRANSLATE, "多语言辅助"),
        ("settings", ft.Icons.SETTINGS_OUTLINED, "设置"),
    ):

        def on_click(e, k=key):
            select_view(k)

        btn = ft.IconButton(
            icon=icon,
            tooltip=tip,
            icon_size=20,
            icon_color=st.get_palette(page).rail_icon,
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.TRANSPARENT,
                overlay_color=ft.Colors.with_opacity(0.14, "#ffffff"),
            ),
            on_click=on_click,
        )
        slot = ft.Container(
            width=52,
            height=46,
            alignment=ft.Alignment.CENTER,
            content=btn,
        )
        rail_items[key] = (slot, btn)
        rail_controls.append(slot)

    _pal0 = st.get_palette(page)
    icon_rail = ft.Container(
        width=52,
        padding=ft.Padding.only(top=8, bottom=8),
        bgcolor=_pal0.rail_bg,
        border=ft.Border.only(right=ft.BorderSide(1, _pal0.rail_divider)),
        content=ft.Column(
            rail_controls,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
            spacing=2,
        ),
    )

    def _refresh_version_footer() -> None:
        version_footer.value = (
            f"Flet 版 v{__version__} · LOG 目录: {get_output_dir('log_export')}"
        )

    version_footer = st.themed_text(
        page,
        f"Flet 版 v{__version__} · LOG 目录: {get_output_dir('log_export')}",
        size=11,
        muted=True,
        opacity=0.9,
    )

    def _on_dirs_applied() -> None:
        _refresh_version_footer()
        page.update()

    ui_hooks["on_dirs_applied"] = _on_dirs_applied
    support_footer = st.themed_text(
        page,
        "有使用问题找W8076967",
        size=11,
        muted=True,
        opacity=0.85,
    )

    output_card = ft.Container(
        expand=True,
        bgcolor=_pal0.editor_bg,
        padding=ft.Padding.only(left=8, right=16, bottom=16),
        data={"_flet_theme": "panel_bg"},
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Row(
                            [status_badge, end_time_banner],
                            spacing=10,
                            wrap=True,
                            tight=True,
                        ),
                        ft.Row(
                            [
                                ft.TextButton("复制输出", on_click=copy_output),
                                ft.TextButton("清空", on_click=clear_output),
                            ],
                            tight=True,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(expand=True, content=output_frame),
                ft.Row(
                    [
                        version_footer,
                        support_footer,
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                ),
            ],
            expand=True,
            spacing=8,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )

    vdiv_outer = st.themed_vdiv(page)
    vdiv_mid = st.themed_vdiv(page)

    theme_roots.extend(
        [
            home_col,
            monkey_panel,
            language_panel,
            log_panel,
            screenshots_panel,
            settings_panel,
            output_card,
            vdiv_outer,
            vdiv_mid,
            title_label,
            end_time_banner,
            version_footer,
            support_footer,
        ]
    )

    def apply_chrome_theme():
        pal = st.get_palette(page)
        page.padding = 0
        page.spacing = 0
        page.bgcolor = pal.editor_bg
        page.window.bgcolor = pal.editor_bg
        if window_shell:
            window_shell.bgcolor = pal.editor_bg
        workspace_body.bgcolor = pal.editor_bg
        icon_rail.bgcolor = pal.rail_bg
        icon_rail.border = ft.Border.only(right=ft.BorderSide(1, pal.rail_divider))
        custom_title_bar.bgcolor = pal.toolbar_bg
        custom_title_bar.border = ft.Border.only(bottom=ft.BorderSide(1, pal.rail_divider))
        title_bar_btn_min.icon_color = pal.field_text
        v = "dark" if st.is_dark(page) else "light"
        if settings_theme_dd.value != v:
            settings_theme_dd.value = v
        selected_device_card.bgcolor = pal.field_surface
        selected_device_card.border = ft.Border.all(1, pal.field_border)
        device_menu_box.bgcolor = pal.editor_bg
        device_menu_box.opacity = 1
        device_menu_box.border = ft.Border.all(1, pal.field_border)
        device_dropdown_chevron.color = pal.field_label
        _sync_selected_device_card()
        _render_device_menu()
        st.refresh_tagged_in_trees(page, theme_roots)
        st.apply_output_status_border(page, output_frame, output_status_state["k"])
        output_frame.bgcolor = pal.output_surface
        select_view(view_state["key"])

    ui_hooks["apply_chrome"] = apply_chrome_theme

    _main_row = ft.Row(
        [
            icon_rail,
            vdiv_outer,
            ft.Row(
                [
                    workspace_body,
                    vdiv_mid,
                    output_card,
                ],
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        ],
        expand=True,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    window_shell = ft.Container(
        expand=True,
        bgcolor=st.get_palette(page).editor_bg,
        border_radius=12,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        content=ft.Column(
            [
                custom_title_bar,
                _main_row,
            ],
            expand=True,
            spacing=0,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )
    page.add(window_shell)

    select_view("home")
    await refresh_sn()

    # 设置环境变量 TEST_TOOL_FLET_DEBUG=1（或 true/yes/on）时，ADB 轮询里 refresh_sn 的异常会打印到控制台
    _debug_adb_poll = (os.environ.get("TEST_TOOL_FLET_DEBUG") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    async def _adb_status_poll():
        """定时刷新 ADB 连接摘要与设备列表（仅变化时 refresh_sn 内会 page.update）。"""
        while True:
            await asyncio.sleep(2.5)
            try:
                await refresh_sn()
            except Exception:
                if _debug_adb_poll:
                    traceback.print_exc()

    asyncio.create_task(_adb_status_poll())


if __name__ == "__main__":
    if "--scrcpy-tool" in sys.argv:
        _sn = ""
        if "--sn" in sys.argv:
            _i = sys.argv.index("--sn")
            if _i + 1 < len(sys.argv):
                _sn = sys.argv[_i + 1]
        run_scrcpy_tool_window(_sn)
    else:
        ft.run(main)