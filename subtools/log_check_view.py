# -*- coding: utf-8 -*-
"""日志核查工具（上行录入场景表格，对齐 log_check_tool 演示数据与着色逻辑）"""
from __future__ import annotations

from typing import Any, Callable, List

import flet as ft

from ui import styles as st

# 与 log_check_tool/init_treeview_data 一致，可扩展
_INITIAL_ROWS: List[List[Any]] = [
    ["AUDIO_SOURCE_DEFAULT", "AUDIO_SOURCE_DEFAULT", "0", "0"],
    ["mic录音", "AUDIO_SOURCE_MIC", "2", "1"],
    ["通话只有上行", "AUDIO_SOURCE_VOICE_COMMUNICATION", "N/A", "2"],
]


def build_log_check_panel(page: ft.Page, snack: Callable[[str], None]) -> ft.Control:
    rows_data: List[dict[str, str]] = []
    for r in _INITIAL_ROWS:
        rows_data.append(
            {
                "comment": str(r[0]),
                "name": str(r[1]),
                "value": str(r[2]),
                "normal": str(r[3]),
            }
        )

    param_in = st.themed_text_field(page, label="录入参数（如 实际值 或 参数名=值）", expand=True)
    table_holder = ft.Column(spacing=0, tight=True)

    def row_color(val: str, norm: str) -> str | None:
        if val == "N/A":
            return "#665c00"
        if val == norm:
            return "#14532d"
        return "#7f1d1d"

    def rebuild_table():
        table_holder.controls.clear()
        for r in rows_data:
            bg = row_color(r["value"], r["normal"])
            tc = st.get_palette(page).field_text
            table_holder.controls.append(
                ft.Container(
                    padding=8,
                    bgcolor=bg,
                    border_radius=4,
                    margin=ft.Margin.only(bottom=4),
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                expand=2,
                                content=ft.Text(
                                    r["comment"],
                                    size=12,
                                    color=tc,
                                    font_family=st.FONT_FAMILY_UI,
                                ),
                            ),
                            ft.Container(
                                expand=2,
                                content=ft.Text(
                                    r["name"],
                                    size=12,
                                    weight=ft.FontWeight.W_500,
                                    color=tc,
                                    font_family=st.FONT_FAMILY_UI,
                                ),
                            ),
                            ft.Container(
                                expand=1,
                                content=ft.Text(
                                    r["value"],
                                    size=12,
                                    color=tc,
                                    font_family=st.FONT_FAMILY_UI,
                                ),
                            ),
                            ft.Container(
                                expand=1,
                                content=ft.Text(
                                    r["normal"],
                                    size=12,
                                    color=tc,
                                    font_family=st.FONT_FAMILY_UI,
                                ),
                            ),
                        ],
                    ),
                )
            )
        page.update()

    def on_record(_):
        raw = (param_in.value or "").strip()
        if not raw:
            snack("请输入参数")
            return
        if "=" in raw:
            k, _, v = raw.partition("=")
            k, v = k.strip(), v.strip()
            for r in rows_data:
                if r["name"] == k:
                    r["value"] = v
                    snack(f"已更新 {k} = {v}")
                    rebuild_table()
                    return
            snack("未找到匹配参数名")
            return
        for r in rows_data:
            if r["value"] != "N/A":
                r["value"] = raw
                snack("已写入首条可编辑行的实际值")
                rebuild_table()
                return
        snack("无匹配行")

    def on_clear(_):
        param_in.value = ""
        for i, r in enumerate(rows_data):
            r["value"] = str(_INITIAL_ROWS[i][2])
        rebuild_table()
        snack("已重置为初始值")

    def on_test(_):
        rebuild_table()
        snack("已按 实际值 vs 预期值 着色（绿=一致，红=不一致，黄=N/A）")

    rebuild_table()

    return st.themed_panel(
        page,
        padding=16,
        content=ft.Column(
            controls=[
                st.themed_text(page, "Log 核查工具（音频场景示例）", size=18, weight=ft.FontWeight.W_500),
                st.themed_text(
                    page,
                    "与原版相同示例数据；绿/红/黄 表示 pass/fail/na。",
                    size=12,
                    muted=True,
                ),
                ft.Row(
                    controls=[
                        param_in,
                        st.btn_info_outline("录入参数", on_click=on_record),
                        st.btn_danger_outline("清空参数", on_click=on_clear),
                        st.btn_success("开始测试", on_click=on_test),
                    ],
                    wrap=True,
                    spacing=8,
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            expand=2,
                            content=st.themed_text(page, "注释", weight=ft.FontWeight.W_500),
                        ),
                        ft.Container(
                            expand=2,
                            content=st.themed_text(page, "参数名", weight=ft.FontWeight.W_500),
                        ),
                        ft.Container(
                            expand=1,
                            content=st.themed_text(page, "实际值", weight=ft.FontWeight.W_500),
                        ),
                        ft.Container(
                            expand=1,
                            content=st.themed_text(page, "预期", weight=ft.FontWeight.W_500),
                        ),
                    ]
                ),
                ft.Container(
                    content=ft.Column(controls=[table_holder], scroll=ft.ScrollMode.AUTO),
                    expand=True,
                    height=400,
                ),
            ],
            expand=True,
            spacing=10,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        expand=True,
    )
