# -*- coding: utf-8 -*-
"""查看 / 导出设备截图（Pictures/Screenshots）。"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

import flet as ft

from core.user_prefs import get_output_dir
from ui import styles as st

_REMOTE_DIR = "/sdcard/Pictures/Screenshots"
_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _cache_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    else:
        base = Path.home() / ".cache"
    d = base / "TestToolFlet" / "screenshot_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _adb_prefix(sn: str) -> list[str]:
    return ["adb", "-s", sn] if sn else ["adb"]


def _run_adb(args: list[str], *, timeout: float = 60) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def list_remote_screenshots(sn: str) -> tuple[Optional[list[str]], Optional[str]]:
    """返回设备截图文件名列表（仅文件名），失败返回 (None, err)。"""
    if not sn:
        return None, "请先选择设备"
    # 优先 ls；部分机型无 toybox find
    rc, out, err = _run_adb(
        [*_adb_prefix(sn), "shell", "ls", "-1", _REMOTE_DIR],
        timeout=30,
    )
    names: list[str] = []
    if rc == 0 and out.strip():
        for line in out.splitlines():
            name = line.strip().split("/")[-1]
            if not name or name.endswith(":"):
                continue
            if name.lower() in ("no", "such", "file", "directory", "ls:"):
                continue
            if Path(name).suffix.lower() in _IMG_EXT:
                names.append(name)
    else:
        rc2, out2, err2 = _run_adb(
            [
                *_adb_prefix(sn),
                "shell",
                f"find {_REMOTE_DIR} -maxdepth 1 -type f 2>/dev/null",
            ],
            timeout=30,
        )
        if rc2 != 0:
            tip = (err or err2 or out or out2 or "无法读取截图目录").strip()
            if "No such file" in tip or "No such file" in (out + out2):
                return [], None
            return None, tip
        for line in out2.splitlines():
            name = line.strip().split("/")[-1]
            if name and Path(name).suffix.lower() in _IMG_EXT:
                names.append(name)
    # 新截图通常文件名含时间戳，倒序更贴近「最新在前」
    names = sorted(set(names), reverse=True)
    return names, None


def pull_screenshot(sn: str, name: str, local_path: Path) -> Optional[str]:
    remote = f"{_REMOTE_DIR}/{name}"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    rc, _out, err = _run_adb(
        [*_adb_prefix(sn), "pull", remote, str(local_path)],
        timeout=120,
    )
    if rc != 0 or not local_path.is_file():
        return (err or "pull 失败").strip() or "pull 失败"
    return None


def open_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    p = str(path.resolve())
    if sys.platform == "win32":
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def build_screenshots_panel(
    page: ft.Page,
    *,
    get_sn: Callable[[], str],
    snack: Callable[[str], None],
) -> ft.Control:
    selected: set[str] = set()
    items: list[dict] = []  # {name, local, card}
    status = st.themed_text(page, "点击「显示截图」加载设备相册截图", size=12, muted=True)
    grid = ft.GridView(
        expand=True,
        runs_count=4,
        max_extent=160,
        child_aspect_ratio=0.78,
        spacing=10,
        run_spacing=10,
        padding=8,
    )

    def _export_dir() -> Path:
        return get_output_dir("screenshot_export")

    def _sync_card_style(card: ft.Container, name: str) -> None:
        pal = st.get_palette(page)
        on = name in selected
        card.border = ft.Border.all(
            2, pal.field_border_focus if on else pal.field_border
        )
        card.bgcolor = (
            ft.Colors.with_opacity(0.18, pal.field_border_focus)
            if on
            else pal.field_surface
        )

    def _toggle(name: str) -> None:
        if name in selected:
            selected.discard(name)
        else:
            selected.add(name)
        for it in items:
            if it["name"] == name:
                _sync_card_style(it["card"], name)
                break
        _refresh_sel_label()
        page.update()

    sel_label = st.themed_text(page, "已选 0 张", size=12, muted=True)

    def _refresh_sel_label() -> None:
        sel_label.value = f"已选 {len(selected)} 张"

    def _make_card(name: str, local: Path) -> ft.Container:
        pal = st.get_palette(page)
        img = ft.Image(
            src=str(local) if local.is_file() else None,
            width=140,
            height=120,
            fit=ft.BoxFit.COVER,
            border_radius=6,
            error_content=ft.Container(
                width=140,
                height=120,
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=pal.field_label),
            ),
        )
        title = ft.Text(
            name,
            size=11,
            color=pal.field_text,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
            text_align=ft.TextAlign.CENTER,
        )
        card = ft.Container(
            width=148,
            padding=6,
            border_radius=8,
            border=ft.Border.all(2, pal.field_border),
            bgcolor=pal.field_surface,
            ink=True,
            on_click=lambda e, n=name: _toggle(n),
            content=ft.Column(
                [img, title],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            data={"_flet_theme": "thin_border_box"},
        )
        _sync_card_style(card, name)
        return card

    async def _on_show(_e=None) -> None:
        sn = (get_sn() or "").strip()
        if not sn:
            snack("请先选择设备")
            return
        status.value = "正在读取设备截图列表…"
        grid.controls.clear()
        items.clear()
        selected.clear()
        _refresh_sel_label()
        page.update()

        names, err = await asyncio.to_thread(list_remote_screenshots, sn)
        if err:
            status.value = f"读取失败：{err}"
            snack(err)
            page.update()
            return
        if not names:
            status.value = f"目录为空或不存在：{_REMOTE_DIR}"
            page.update()
            return

        cache_dir = _cache_root() / re.sub(r"[^\w\-]+", "_", sn)
        cache_dir.mkdir(parents=True, exist_ok=True)
        status.value = f"正在拉取缩略图 0/{len(names)}…"
        page.update()

        ok_n = 0
        for i, name in enumerate(names, 1):
            local = cache_dir / name
            if not local.is_file() or local.stat().st_size <= 0:
                pull_err = await asyncio.to_thread(pull_screenshot, sn, name, local)
                if pull_err:
                    continue
            card = _make_card(name, local)
            items.append({"name": name, "local": local, "card": card})
            grid.controls.append(card)
            ok_n += 1
            if i % 4 == 0 or i == len(names):
                status.value = f"正在拉取缩略图 {i}/{len(names)}…"
                page.update()
                await asyncio.sleep(0)

        status.value = f"共 {ok_n} 张（设备目录 {_REMOTE_DIR}）"
        _refresh_sel_label()
        page.update()

    async def _on_export(_e=None) -> None:
        sn = (get_sn() or "").strip()
        if not sn:
            snack("请先选择设备")
            return
        if not selected:
            snack("请先选择要导出的截图")
            return
        out = _export_dir()
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            snack(f"无法创建导出目录: {e}")
            return
        status.value = f"正在导出 {len(selected)} 张…"
        page.update()
        done = 0
        fail = 0
        for name in list(selected):
            dest = out / name
            # 优先用已缓存文件复制，否则再 pull
            cached = next((it["local"] for it in items if it["name"] == name), None)
            if cached and Path(cached).is_file():
                try:
                    await asyncio.to_thread(shutil.copy2, str(cached), str(dest))
                    done += 1
                    continue
                except OSError:
                    pass
            err = await asyncio.to_thread(pull_screenshot, sn, name, dest)
            if err:
                fail += 1
            else:
                done += 1
        status.value = f"导出完成：成功 {done}，失败 {fail} → {out}"
        snack(f"已导出 {done} 张到 {out}")
        page.update()

    def _on_open_dir(_e=None) -> None:
        try:
            open_directory(_export_dir())
        except Exception as e:
            snack(f"打开目录失败: {e}")

    btn_show = st.btn_primary("显示截图", icon=ft.Icons.IMAGE_OUTLINED, on_click=_on_show)
    btn_export = st.btn_success("导出", icon=ft.Icons.DOWNLOAD, on_click=_on_export)
    btn_open = st.btn_info_outline(
        "打开导出目录", icon=ft.Icons.FOLDER_OPEN, on_click=_on_open_dir
    )

    list_frame = ft.Container(
        expand=True,
        border=ft.Border.all(1, st.get_palette(page).field_border),
        border_radius=8,
        bgcolor=st.get_palette(page).output_surface,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=grid,
        data={"_flet_theme": "thin_border_box", "_flet_fill_output": True},
    )

    return st.themed_panel(
        page,
        padding=12,
        expand=True,
        content=ft.Column(
            [
                ft.Row(
                    [
                        btn_show,
                        status,
                        ft.Container(expand=True),
                        sel_label,
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                st.themed_text(
                    page,
                    f"设备路径：{_REMOTE_DIR}（单击缩略图单选/多选切换）",
                    size=11,
                    muted=True,
                ),
                list_frame,
                ft.Row(
                    [btn_export, btn_open],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            expand=True,
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )
