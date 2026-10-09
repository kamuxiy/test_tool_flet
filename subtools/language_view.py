# -*- coding: utf-8 -*-
from __future__ import annotations
import sys

import datetime
from pathlib import Path
from typing import Callable, Optional

import flet as ft

from ui import styles as st

def _repo_with_assets() -> Path:
    """开发：仓库根（含 assets/）；打包：与 main 相同，资源在 _MEIPASS/assets。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


_REPO = _repo_with_assets()
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from assets.languages import Language  # noqa: E402


def build_language_panel(
    page: ft.Page,
    append_lines: Callable[..., None],
    snack: Callable[[str], None],
    end_banner_callback: Optional[Callable[[str], None]] = None,
) -> ft.Control:
    lang = Language()
    type_dd = st.themed_dropdown(
        page,
        label="语言类型",
        width=320,
        options=[
            ft.dropdown.Option(x)
            for x in [
                "内销",
                "外销",
                "内销RTL",
                "内销LTR",
                "外销RTL",
                "外销LTR",
                "内外销LTR",
                "内外销RTL",
                "内外销",
                "自定义",
            ]
        ],
        value="自定义",
    )
    uy = st.themed_checkbox(page, label="强制加上维吾尔语", value=False)
    custom_col = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=280)
    custom_wrap = ft.Container(
        content=custom_col,
        border=ft.Border.all(1, st.get_palette(page).field_border),
        border_radius=8,
        bgcolor=st.get_palette(page).output_surface,
        padding=8,
        data={"_flet_theme": "thin_border_box", "_flet_fill_output": True},
    )
    checks: dict[str, ft.Checkbox] = {}

    def rebuild_custom_options():
        custom_col.controls.clear()
        checks.clear()
        sel = type_dd.value or "自定义"
        if sel == "自定义":
            opts = lang.get_language("内外销") or []
        else:
            opts = lang.get_language(sel) or []
        for item in opts:
            cb = st.themed_checkbox(
                page,
                label=item[:60] + ("…" if len(item) > 60 else ""),
                data=item,
            )
            checks[item] = cb
            custom_col.controls.append(cb)
        page.update()

    def on_type_change(e):
        sel = type_dd.value or ""
        if sel == "自定义":
            uy.disabled = True
            uy.value = False
            custom_wrap.visible = True
        else:
            uy.disabled = False
            custom_wrap.visible = False
        rebuild_custom_options()

    type_dd.on_change = on_type_change

    result = st.themed_output_field(
        page,
        label="生成结果",
        multiline=True,
        min_lines=8,
        max_lines=16,
        read_only=True,
        expand=True,
        text_style=ft.TextStyle(size=12),
    )

    def create_txt() -> tuple[bool, str]:
        path = _repo_root() / "language-custom.txt"
        if type_dd.value == "自定义":
            chosen = [k for k, cb in checks.items() if cb.value]
            language_list = chosen
        else:
            language_list = list(lang.get_language(lang=type_dd.value) or [])
            if uy.value and "维吾尔语（中国）=ug-CN" not in language_list:
                language_list.append("维吾尔语（中国）=ug-CN")
        try:
            with open(path, "w", encoding="utf-8") as f:
                for item in language_list:
                    f.write(item + "\n")
        except OSError as ex:
            return False, str(ex)
        return True, str(path)

    async def on_gen(_):
        result.value = ""
        result.value += f"单选: {type_dd.value}\n维吾尔语: {uy.value}\n"
        if type_dd.value == "自定义":
            picked = [k for k, cb in checks.items() if cb.value]
            result.value += f"勾选数: {len(picked)}\n\n"
        try:
            ok, msg = create_txt()
            if ok:
                result.value += Language.notes + "\n\n生成成功！\n" + msg
                snack("已写入 language-custom.txt")
            else:
                result.value += "生成失败: " + msg
                snack("写入失败")
        except Exception as ex:
            result.value += f"错误: {ex}"
            snack("出错")
        end_line = "End：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if end_banner_callback:
            end_banner_callback(end_line)
        else:
            result.value += "\n\n" + end_line
        page.update()

    rebuild_custom_options()
    custom_wrap.visible = True
    uy.disabled = True

    return st.themed_panel(
        page,
        padding=16,
        content=ft.Column(
            controls=[
                st.themed_text(page, "多语言截图辅助", size=18, weight=ft.FontWeight.W_500),
                st.themed_text(page, "步骤 1：选择类型；自定义时可勾选语言。", size=12, muted=True),
                ft.Row([type_dd, uy], wrap=True, spacing=12),
                st.themed_text(page, "步骤 2：自定义时勾选语言", weight=ft.FontWeight.W_500),
                custom_wrap,
                st.btn_success("生成 language-custom.txt", on_click=on_gen),
                st.themed_text(page, "结果", weight=ft.FontWeight.W_500),
                result,
            ],
            expand=True,
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        expand=True,
    )
