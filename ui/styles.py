# -*- coding: utf-8 -*-
"""按钮强调色 + Darcula / IntelliJ Light 双套界面色板（输入框、侧栏、工作区）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import flet as ft

# —— 字体：全应用统一 UI 栈，避免系统默认/Roboto 与中文混排导致粗细不一 —— #
FONT_FAMILY_UI = "Microsoft YaHei UI, Segoe UI, system-ui, sans-serif"
FONT_FAMILY_MONO = (
    "'Cascadia Mono', 'Cascadia Code', Consolas, 'Microsoft YaHei UI', monospace"
)


def ui_label_style(p: ThemePalette, *, size: float = 13) -> ft.TextStyle:
    return ft.TextStyle(color=p.field_label, size=size, font_family=FONT_FAMILY_UI)


def ui_body_text_style(p: ThemePalette, *, size: float = 13) -> ft.TextStyle:
    return ft.TextStyle(color=p.field_text, size=size, font_family=FONT_FAMILY_UI)


def mono_text_style(p: ThemePalette, *, size: float = 13) -> ft.TextStyle:
    return ft.TextStyle(color=p.field_text, size=size, font_family=FONT_FAMILY_MONO)


# —— darkly 近似（按钮，明暗通用）—— #
PRIMARY = "#375a7f"
SUCCESS = "#00bc8c"
INFO = "#3498db"
WARNING = "#f39c12"
DANGER = "#e74c3c"
SECONDARY = "#444950"
LIGHT_OUTLINE_FG = "#ecf0f1"

# 兼容旧代码：默认指暗色（新代码请用 get_palette(page)）
IDEA_RAIL_BG = "#3c3f41"
IDEA_RAIL_DIVIDER = "#515151"
IDEA_RAIL_SELECT_BG = "#4a4e52"
IDEA_RAIL_ACCENT = "#589df6"
IDEA_RAIL_ICON = "#afb1b3"
IDEA_RAIL_ICON_ON = "#f3f3f3"
IDEA_TOOLBAR_BG = "#313335"
IDEA_EDITOR_BG = "#2b2b2b"
FIELD_SURFACE = "#45494a"
FIELD_SURFACE_FOCUS = "#4d5254"
FIELD_BORDER = "#6b6b6b"
FIELD_BORDER_FOCUS = IDEA_RAIL_ACCENT
FIELD_TEXT = "#e8e8e8"
FIELD_LABEL = "#c4c4c4"
OUTPUT_SURFACE = "#2f3233"
OUTPUT_BORDER = "#5a5d5e"
MENU_SURFACE = "#4a5052"


@dataclass(frozen=True)
class ThemePalette:
    editor_bg: str
    toolbar_bg: str
    rail_bg: str
    rail_divider: str
    rail_select_bg: str
    rail_accent: str
    rail_icon: str
    rail_icon_on: str
    field_surface: str
    field_surface_focus: str
    field_border: str
    field_border_focus: str
    field_text: str
    field_label: str
    output_surface: str
    output_border: str
    menu_surface: str


PALETTE_DARK = ThemePalette(
    editor_bg="#2b2b2b",
    toolbar_bg="#313335",
    rail_bg="#3c3f41",
    rail_divider="#515151",
    rail_select_bg="#4a4e52",
    rail_accent="#589df6",
    rail_icon="#afb1b3",
    rail_icon_on="#f3f3f3",
    field_surface="#45494a",
    field_surface_focus="#4d5254",
    field_border="#6b6b6b",
    field_border_focus="#589df6",
    field_text="#e8e8e8",
    field_label="#c4c4c4",
    output_surface="#2f3233",
    output_border="#5a5d5e",
    menu_surface="#4a5052",
)

# IntelliJ 新 UI 浅色工具条 / 编辑器近似
PALETTE_LIGHT = ThemePalette(
    editor_bg="#f2f2f2",
    toolbar_bg="#ebebeb",
    rail_bg="#e3e3e3",
    rail_divider="#c4c4c4",
    rail_select_bg="#d0d8e0",
    rail_accent="#247ce9",
    rail_icon="#5c5c5c",
    rail_icon_on="#1a1a1a",
    field_surface="#ffffff",
    field_surface_focus="#f7f7f7",
    field_border="#a8a8a8",
    field_border_focus="#247ce9",
    field_text="#1e1e1e",
    field_label="#4a4a4a",
    output_surface="#fafafa",
    output_border="#b8b8b8",
    menu_surface="#ffffff",
)


def is_dark(page: ft.Page) -> bool:
    return page.theme_mode != ft.ThemeMode.LIGHT


def get_palette(page: ft.Page) -> ThemePalette:
    return PALETTE_DARK if is_dark(page) else PALETTE_LIGHT


def iter_descendants(control: ft.Control) -> Iterator[ft.Control]:
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from iter_descendants(content)
    for ch in getattr(control, "controls", None) or []:
        yield from iter_descendants(ch)


def _meta(control: ft.Control) -> dict[str, Any] | None:
    d = getattr(control, "data", None)
    return d if isinstance(d, dict) else None


def _apply_text_field(p: ThemePalette, c: ft.TextField) -> None:
    c.fill_color = p.field_surface
    c.bgcolor = p.field_surface
    c.color = p.field_text
    c.border_color = p.field_border
    c.focused_border_color = p.field_border_focus
    c.focused_bgcolor = p.field_surface_focus
    c.cursor_color = p.field_border_focus
    c.selection_color = ft.Colors.with_opacity(0.35, p.field_border_focus)
    c.label_style = ui_label_style(p)
    ts = c.text_style
    c.text_style = ft.TextStyle(
        size=(ts.size if ts and ts.size is not None else 13),
        weight=ts.weight if ts else None,
        color=p.field_text,
        font_family=(ts.font_family if ts and ts.font_family else FONT_FAMILY_UI),
    )


def _apply_output_field(p: ThemePalette, c: ft.TextField) -> None:
    c.fill_color = p.output_surface
    c.bgcolor = p.output_surface
    c.color = p.field_text
    meta = c.data if isinstance(c.data, dict) else {}
    if meta.get("_flet_borderless"):
        c.border_color = ft.Colors.TRANSPARENT
        c.focused_border_color = ft.Colors.TRANSPARENT
        c.border_width = 0
        c.focused_border_width = 0
        c.border_radius = 0
    else:
        c.border_color = p.output_border
        c.focused_border_color = p.output_border
        c.border_radius = 8
    c.cursor_color = p.field_border_focus
    c.selection_color = ft.Colors.with_opacity(0.35, p.field_border_focus)
    c.label_style = ui_label_style(p)
    ts = c.text_style
    c.text_style = ft.TextStyle(
        size=(ts.size if ts and ts.size is not None else 13),
        weight=ts.weight if ts else None,
        color=p.field_text,
        font_family=(ts.font_family if ts and ts.font_family else FONT_FAMILY_MONO),
    )


def _apply_dropdown(p: ThemePalette, c: ft.Dropdown) -> None:
    c.fill_color = p.field_surface
    c.bgcolor = p.field_surface
    c.color = p.field_text
    c.border_color = p.field_border
    c.focused_border_color = p.field_border_focus
    c.label_style = ui_label_style(p)
    c.menu_style = ft.MenuStyle(bgcolor=p.menu_surface, elevation=6)


def refresh_tagged_in_trees(page: ft.Page, roots: list[ft.Control]) -> None:
    """切换明暗后刷新已挂载的输入框、文案等（遍历多个根，含未当前显示的子面板）。"""
    p = get_palette(page)
    for root in roots:
        for c in iter_descendants(root):
            meta = _meta(c)
            if not meta:
                continue
            kind = meta.get("_flet_theme")
            if kind == "text_field":
                _apply_text_field(p, c)
            elif kind == "output_field":
                _apply_output_field(p, c)
            elif kind == "dropdown":
                _apply_dropdown(p, c)
            elif kind == "text_body":
                assert isinstance(c, ft.Text)
                c.color = p.field_text
                if c.font_family is None:
                    c.font_family = FONT_FAMILY_UI
            elif kind == "text_muted":
                assert isinstance(c, ft.Text)
                c.color = p.field_label
                if c.font_family is None:
                    c.font_family = FONT_FAMILY_UI
            elif kind == "output_log_text":
                assert isinstance(c, ft.Text)
                c.color = p.field_text
                c.font_family = FONT_FAMILY_MONO
            elif kind == "panel_bg":
                assert isinstance(c, ft.Container)
                c.bgcolor = p.editor_bg
            elif kind == "toolbar_bg":
                assert isinstance(c, ft.Container)
                c.bgcolor = p.toolbar_bg
            elif kind == "hairline":
                assert isinstance(c, ft.Divider)
                c.color = p.rail_divider
            elif kind == "vdiv":
                assert isinstance(c, ft.VerticalDivider)
                c.color = p.rail_divider
            elif kind == "checkbox":
                if isinstance(c, ft.Checkbox):
                    c.fill_color = p.field_surface
                    c.check_color = p.field_border_focus
            elif kind == "radio":
                if isinstance(c, ft.Radio):
                    c.fill_color = p.field_surface
                    c.active_color = p.field_border_focus
            elif kind == "thin_border_box":
                if isinstance(c, ft.Container):
                    c.border = ft.Border.all(1, p.field_border)
                    if meta.get("_flet_fill_output"):
                        c.bgcolor = p.output_surface


def themed_text_field(page: ft.Page, **kwargs: Any) -> ft.TextField:
    p = get_palette(page)
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": "text_field"}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    defaults: dict[str, Any] = dict(
        dense=True,
        filled=True,
        fill_color=p.field_surface,
        bgcolor=p.field_surface,
        color=p.field_text,
        border_width=1,
        border_color=p.field_border,
        focused_border_width=2,
        focused_border_color=p.field_border_focus,
        focused_bgcolor=p.field_surface_focus,
        cursor_color=p.field_border_focus,
        selection_color=ft.Colors.with_opacity(0.35, p.field_border_focus),
        label_style=ui_label_style(p),
        text_style=ui_body_text_style(p),
        data=base_data,
    )
    defaults.update(kwargs)
    return ft.TextField(**defaults)


def themed_output_field(page: ft.Page, **kwargs: Any) -> ft.TextField:
    p = get_palette(page)
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": "output_field"}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    ts_override = kwargs.pop("text_style", None)
    base_mono = mono_text_style(p)
    merged_ts = base_mono
    if ts_override is not None:
        merged_ts = ft.TextStyle(
            size=ts_override.size if ts_override.size is not None else base_mono.size,
            weight=ts_override.weight if ts_override.weight is not None else base_mono.weight,
            color=ts_override.color if ts_override.color is not None else base_mono.color,
            font_family=ts_override.font_family or FONT_FAMILY_MONO,
        )
    defaults: dict[str, Any] = dict(
        dense=True,
        filled=True,
        fill_color=p.output_surface,
        bgcolor=p.output_surface,
        color=p.field_text,
        border_width=1,
        border_color=p.output_border,
        border_radius=8,
        focused_border_width=1,
        focused_border_color=p.output_border,
        cursor_color=p.field_border_focus,
        selection_color=ft.Colors.with_opacity(0.35, p.field_border_focus),
        label_style=ui_label_style(p),
        text_style=merged_ts,
        data=base_data,
    )
    defaults.update(kwargs)
    return ft.TextField(**defaults)


def themed_dropdown(page: ft.Page, **kwargs: Any) -> ft.Dropdown:
    p = get_palette(page)
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": "dropdown"}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    defaults: dict[str, Any] = dict(
        dense=True,
        filled=True,
        fill_color=p.field_surface,
        bgcolor=p.field_surface,
        color=p.field_text,
        border_width=1,
        border_color=p.field_border,
        focused_border_width=2,
        focused_border_color=p.field_border_focus,
        label_style=ui_label_style(p),
        menu_style=ft.MenuStyle(bgcolor=p.menu_surface, elevation=6),
        data=base_data,
    )
    defaults.update(kwargs)
    return ft.Dropdown(**defaults)


def themed_text(page: ft.Page, text: str, *, muted: bool = False, **kwargs: Any) -> ft.Text:
    p = get_palette(page)
    color = p.field_label if muted else p.field_text
    role = "text_muted" if muted else "text_body"
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": role}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    if kwargs.get("font_family") is None:
        kwargs["font_family"] = FONT_FAMILY_UI
    return ft.Text(text, color=color, data=base_data, **kwargs)


def themed_panel(page: ft.Page, **kwargs: Any) -> ft.Container:
    p = get_palette(page)
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": "panel_bg"}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    kw = dict(bgcolor=p.editor_bg, data=base_data, alignment=ft.Alignment.TOP_LEFT, **kwargs)
    return ft.Container(**kw)


def themed_toolbar(page: ft.Page, **kwargs: Any) -> ft.Container:
    p = get_palette(page)
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": "toolbar_bg"}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    kw = dict(bgcolor=p.toolbar_bg, data=base_data, alignment=ft.Alignment.TOP_LEFT, **kwargs)
    return ft.Container(**kw)


def themed_hairline(page: ft.Page) -> ft.Divider:
    p = get_palette(page)
    return ft.Divider(height=1, color=p.rail_divider, data={"_flet_theme": "hairline"})


def themed_vdiv(page: ft.Page) -> ft.VerticalDivider:
    p = get_palette(page)
    return ft.VerticalDivider(width=1, thickness=1, color=p.rail_divider, data={"_flet_theme": "vdiv"})


def themed_checkbox(page: ft.Page, **kwargs: Any) -> ft.Checkbox:
    p = get_palette(page)
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": "checkbox"}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    return ft.Checkbox(
        fill_color=p.field_surface,
        check_color=p.field_border_focus,
        data=base_data,
        **kwargs,
    )


def themed_radio(page: ft.Page, **kwargs: Any) -> ft.Radio:
    p = get_palette(page)
    udata = kwargs.pop("data", None)
    base_data: dict[str, Any] = {"_flet_theme": "radio"}
    if isinstance(udata, dict):
        base_data = {**udata, **base_data}
    return ft.Radio(
        fill_color=p.field_surface,
        active_color=p.field_border_focus,
        data=base_data,
        **kwargs,
    )


OUTPUT_STATUS_KINDS = frozenset({"neutral", "ok", "fail", "warn"})


def status_kind_from_title(title: str) -> str:
    """由 run_command_chain / set_status 的标题文案映射为输出框状态（对齐原版 fr_r bootstyle）。"""
    t = (title or "").strip()
    if t in ("成功", "压缩完成"):
        return "ok"
    if t == "失败":
        return "fail"
    if t == "警告":
        return "warn"
    if t in ("就绪", "传输中", "压缩中") or "取消" in t:
        return "neutral"
    if "失败" in t:
        return "fail"
    if "警告" in t:
        return "warn"
    if "成功" in t or "完成" in t:
        return "ok"
    return "neutral"


def apply_output_status_border(
    page: ft.Page, target: ft.TextField | ft.Container, kind: str
) -> None:
    """根据成功/失败/警告切换输出框边框颜色（主题切换后需再次调用以叠加 palette）。"""
    p = get_palette(page)
    k = kind if kind in OUTPUT_STATUS_KINDS else "neutral"
    if k == "ok":
        bc = SUCCESS
    elif k == "fail":
        bc = DANGER
    elif k == "warn":
        bc = WARNING
    else:
        bc = p.output_border
    if isinstance(target, ft.Container):
        target.border = ft.Border.all(1, bc)
        target.border_radius = 8
        return
    field = target
    field.border_color = bc
    field.focused_border_color = bc
    field.border_width = 1
    field.focused_border_width = 1
    field.border_radius = 8


# 旧名兼容（需传入 page）
dark_text_field = themed_text_field
dark_output_field = themed_output_field
dark_dropdown = themed_dropdown


def btn_primary(text: str, **kwargs: Any) -> ft.FilledButton:
    return ft.FilledButton(text, bgcolor=PRIMARY, color="#ffffff", **kwargs)


def btn_success(text: str, **kwargs: Any) -> ft.FilledButton:
    return ft.FilledButton(text, bgcolor=SUCCESS, color="#ffffff", **kwargs)


def btn_info_outline(text: str, **kwargs: Any) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        text,
        style=ft.ButtonStyle(color=INFO, bgcolor=ft.Colors.with_opacity(0.08, INFO)),
        **kwargs,
    )


def btn_warning_outline(text: str, **kwargs: Any) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        text,
        style=ft.ButtonStyle(color=WARNING, bgcolor=ft.Colors.with_opacity(0.08, WARNING)),
        **kwargs,
    )


def btn_danger_outline(text: str, **kwargs: Any) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        text,
        style=ft.ButtonStyle(color=DANGER, bgcolor=ft.Colors.with_opacity(0.08, DANGER)),
        **kwargs,
    )


def btn_secondary(text: str, **kwargs: Any) -> ft.FilledButton:
    return ft.FilledButton(text, bgcolor=SECONDARY, color="#ffffff", **kwargs)


def btn_tonal_neutral(text: str, **kwargs: Any) -> ft.FilledTonalButton:
    return ft.FilledTonalButton(text, **kwargs)
