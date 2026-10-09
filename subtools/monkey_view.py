# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Callable

import flet as ft

from core.monkey_run import MonkeyParams, push_whitelist, run_monkey
from ui import styles as st


def build_monkey_panel(
    page: ft.Page,
    get_sn: Callable[[], str],
    append_lines: Callable[..., None],
    snack: Callable[[str], None],
) -> ft.Control:
    sn_ov = st.themed_text_field(page, label="SN（留空则用顶部工具栏）", width=400)
    pkg = st.themed_text_field(page, label="测试范围：包名或白名单本地路径", expand=True)
    mode = ft.RadioGroup(
        content=ft.Row(
            [
                st.themed_radio(page, value="1", label="单应用包名"),
                st.themed_radio(page, value="2", label="多应用白名单文件"),
            ]
        ),
        value="1",
    )
    wl_push = st.btn_info_outline("push 白名单", width=168)

    seed = st.themed_text_field(page, label="种子（可选）", width=200)
    times = st.themed_text_field(page, label="测试次数", value="300000", width=200)
    delay = st.themed_text_field(page, label="延迟 ms", value="500", width=120)
    nav = st.themed_text_field(page, label="pct-nav", value="0", width=80)
    main_nav = st.themed_text_field(page, label="pct-majornav", value="2", width=80)
    touch = st.themed_text_field(page, label="pct-touch", value="50", width=80)
    motion = st.themed_text_field(page, label="pct-motion", value="15", width=80)
    trackball = st.themed_text_field(page, label="pct-trackball", value="0", width=80)
    pinch = st.themed_text_field(page, label="pct-pinchzoom", value="5", width=80)
    sysk = st.themed_text_field(page, label="pct-syskeys", value="5", width=80)
    flip = st.themed_text_field(page, label="pct-flip", value="1", width=80)

    crashes = st.themed_dropdown(
        page,
        label="忽略崩溃",
        options=[ft.dropdown.Option("是"), ft.dropdown.Option("否")],
        value="是",
        width=140,
    )
    timeouts = st.themed_dropdown(
        page,
        label="忽略超时",
        options=[ft.dropdown.Option("是"), ft.dropdown.Option("否")],
        value="是",
        width=140,
    )
    loglvl = st.themed_dropdown(
        page,
        label="日志等级",
        options=[ft.dropdown.Option("-v -v -v"), ft.dropdown.Option("-v -v"), ft.dropdown.Option("-v")],
        value="-v -v",
        width=140,
    )
    save_err = st.themed_dropdown(
        page,
        label="只保存 monkey 错误日志",
        options=[ft.dropdown.Option("是"), ft.dropdown.Option("否")],
        value="是",
        width=200,
    )
    logcat = st.themed_dropdown(
        page,
        label="额外 logcat",
        options=[ft.dropdown.Option("是"), ft.dropdown.Option("否")],
        value="是",
        width=140,
    )

    info_t = st.themed_text(page, "", size=12, selectable=True)

    def _sn():
        s = (sn_ov.value or "").strip()
        return s if s else (get_sn() or "")

    def _params() -> MonkeyParams:
        return MonkeyParams(
            sn=_sn(),
            package_name=pkg.value or "",
            package_mode=1 if mode.value == "1" else 2,
            seed=seed.value or "",
            times=times.value or "300000",
            delay=delay.value or "500",
            nav=nav.value or "0",
            main_nav=main_nav.value or "2",
            touch=touch.value or "50",
            motion=motion.value or "15",
            trackball=trackball.value or "0",
            pinchzoom=pinch.value or "5",
            system_key=sysk.value or "5",
            flip=flip.value or "1",
            crashes_yes=(crashes.value == "是"),
            timeouts_yes=(timeouts.value == "是"),
            log_level=loglvl.value or "-v -v",
            save_error_log=(save_err.value == "是"),
            logcat_extra=(logcat.value == "是"),
            whitelist_local_path=pkg.value or "",
        )

    async def on_push(_):
        acc: list[str] = []

        def coll(s: str):
            acc.append(s)

        await asyncio.to_thread(push_whitelist, _sn(), pkg.value or "", coll)
        if acc:
            append_lines(acc, clear=False)
            page.update()

    async def on_start(_):
        acc: list[str] = []

        def coll(s: str):
            acc.append(s)

        await asyncio.to_thread(run_monkey, _params(), coll)
        if acc:
            append_lines(acc, clear=False)
        info_t.value = "若已弹出 CMD，请勿重复点击开始。"
        page.update()

    wl_push.on_click = on_push

    start_b = st.btn_primary("开始 Monkey", width=200, on_click=on_start)

    return st.themed_panel(
        page,
        padding=16,
        content=ft.Column(
            controls=[
                st.themed_text(page, "AOSP Monkey 工具", size=18, weight=ft.FontWeight.W_500),
                st.themed_text(
                    page,
                    "与原版一致：在 Windows 上拉起 CMD 执行 adb / logcat。",
                    size=12,
                    muted=True,
                ),
                st.themed_hairline(page),
                sn_ov,
                pkg,
                ft.Row(
                    [mode, wl_push],
                    spacing=12,
                    wrap=False,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                st.themed_text(page, "参数（事件占比）", weight=ft.FontWeight.W_500),
                ft.Row(
                    controls=[seed, times, delay],
                    wrap=True,
                    spacing=8,
                ),
                ft.Row(
                    controls=[nav, main_nav, touch, motion, trackball, pinch, sysk, flip],
                    wrap=True,
                    spacing=8,
                ),
                st.themed_text(page, "日志设置", weight=ft.FontWeight.W_500),
                ft.Row(
                    controls=[crashes, timeouts, loglvl, save_err, logcat],
                    wrap=True,
                    spacing=8,
                ),
                st.themed_hairline(page),
                start_b,
                info_t,
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        expand=True,
    )
