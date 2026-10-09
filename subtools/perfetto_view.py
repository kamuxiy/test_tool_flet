# -*- coding: utf-8 -*-
"""流畅性分析面板（Perfetto 抓取 + 解析）"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import webbrowser
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import flet as ft

from core.paths import app_root
from ui import styles as st

# 工具根目录
PERF_DIR = app_root() / "perf_all_in_one"
PERF_CFG = PERF_DIR / "config" / "long_perfetto_cfg.pbtx"
PARSER_DIR = PERF_DIR / "解析"
PARSER_PY = PARSER_DIR / "systrace_FrameTimeline_Analysis_20260330.py"
PARSER_EXE = PARSER_DIR / "trace_processor_shell.exe"
def _find_worker_exe():
    """打包后调用 perfetto_worker.exe；开发模式返回 None（用 sys.executable）。"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # 同目录：perfetto_worker.exe
        cand = exe_dir / "perfetto_worker.exe"
        if cand.is_file():
            return cand
        # 子目录：perfetto_worker/perfetto_worker.exe（分发时 worker 目录在主程序旁）
        cand2 = exe_dir / "perfetto_worker" / "perfetto_worker.exe"
        if cand2.is_file():
            return cand2
        # 上级目录：../perfetto_worker/perfetto_worker.exe
        cand3 = exe_dir.parent / "perfetto_worker" / "perfetto_worker.exe"
        if cand3.is_file():
            return cand3
    return None


def _capture_cmd(duration_ms: int) -> list:
    worker = _find_worker_exe()
    if worker:
        return [str(worker), "--profile_type=long_perfetto",
                f"--duration_ms={duration_ms}"]
    return [sys.executable, "main.py", "--profile_type=long_perfetto"]


def _update_cfg_duration(duration_ms: int) -> None:
    """修改 perfetto 配置文件中的 duration_ms"""
    if not PERF_CFG.is_file():
        raise FileNotFoundError(f"找不到配置文件: {PERF_CFG}")
    text = PERF_CFG.read_text(encoding="utf-8")
    text = re.sub(r"duration_ms:\s*\d+", f"duration_ms: {duration_ms}", text)
    PERF_CFG.write_text(text, encoding="utf-8")


_PERFETTO_DEFAULT = Path(r"D:\Users\Desktop\perfetto_output")


def _perfetto_output_root() -> Path:
    try:
        from core.user_prefs import get_output_dir

        return get_output_dir("perfetto")
    except Exception:
        return _PERFETTO_DEFAULT


def _ensure_output_dir() -> Path:
    """确保 Perfetto 输出根目录存在"""
    d = _perfetto_output_root()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _list_timestamp_dirs() -> list:
    """列出 Perfetto 输出根目录下所有时间戳文件夹（按修改时间倒序）"""
    d = _ensure_output_dir()
    return [p.name for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True) if p.is_dir()]


def _timestamp_dir() -> Path:
    """以时间戳命名的子文件夹"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    d = _ensure_output_dir() / ts
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_perfetto_trace(output_dir: Path) -> Optional[Path]:
    """在输出目录中找 .perfetto-trace 文件"""
    if not output_dir.is_dir():
        return None
    files = list(output_dir.glob("*.perfetto-trace"))
    if files:
        return files[0]
    return None


def _run_perfetto_capture(
    duration_ms: int,
    on_prompt: Callable[[str], None],
    on_done: Callable[[Callable[[], Path], Optional[str]], None],
) -> None:
    """在后台线程运行 perfetto 抓取，结果直接输出到桌面时间戳目录"""
    target_dir = _timestamp_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        worker = _find_worker_exe()
        if not worker:
            # 开发模式：直接修改本地配置
            _update_cfg_duration(duration_ms)
        env = os.environ.copy()
        env["PERFETTO_OUTPUT_DIR"] = str(target_dir)
        cmd = _capture_cmd(duration_ms)
        # 打包模式 cwd 用 worker 所在目录，避免依赖本地 perf_all_in_one
        cwd = str(Path(worker).resolve().parent) if worker else str(PERF_DIR)
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=env,
        )
        completed = False
        ttl_seen = False
        for line in proc.stdout:  # type: ignore
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            on_prompt(line)
            # perfetto 客户端输出 "TTL: Xs" 表示已开始倒计时
            if (not ttl_seen) and ("TTL:" in line):
                ttl_seen = True
                on_prompt("【提示】Perfetto 已开始抓取，请在手机上进行操作…")
            # 一轮抓取完成：继续读完后续输出，不要 break 丢掉收尾日志
            if (not completed) and ("Completed" in line) and ("iterations" in line):
                completed = True
                on_prompt("【提示】抓取轮次已完成，正在收尾输出…")
        try:
            proc.wait(timeout=duration_ms / 1000 + 30)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            on_done(lambda: target_dir, "抓取超时")
            return
        if completed:
            on_prompt("【提示】抓取完成，结果目录已就绪")
        on_done(lambda: target_dir, None)
    except Exception as e:
        on_done(lambda: target_dir, str(e))



def _find_generated_xlsx(output_dir: Path) -> Optional[Path]:
    """解析脚本把 xlsx 写在 trace 同目录，文件名形如 *.perfetto-trace_*解析.xlsx。"""
    if not output_dir.is_dir():
        return None
    cands = list(output_dir.rglob("*.xlsx"))
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def _run_parser(
    output_dir: Path,
    is_scrolling: str,
    scroll_scene: str,
    on_done: Callable[[Optional[str], Optional[Path]], None],
) -> None:
    """运行解析脚本"""
    try:
        traces = list(Path(output_dir).rglob("*.perfetto-trace"))
        if not traces:
            on_done(f"目录中未找到 .perfetto-trace：{output_dir}", None)
            return
        too_small = [t for t in traces if t.stat().st_size < 100 * 1024]
        if len(too_small) == len(traces):
            sizes = ", ".join(f"{t.name}={t.stat().st_size}B" for t in traces[:3])
            on_done(f"trace 过小无法解析（需≥100KB）：{sizes}", None)
            return

        worker = _find_worker_exe()
        if not worker and (not PARSER_PY.is_file() or not PARSER_EXE.is_file()):
            on_done("找不到解析脚本或 trace_processor_shell.exe", None)
            return
        before = {p.resolve() for p in Path(output_dir).rglob("*.xlsx")}
        if worker:
            # 打包模式：调用 perfetto_worker.exe，无 input 交互
            proc = subprocess.run(
                [str(worker), "--parse", str(output_dir),
                 f"--scroll_type={(is_scrolling or '').strip()}",
                 f"--scroll_keyword={scroll_scene or ''}"],
                cwd=str(output_dir),
                text=True,
                encoding="utf-8",
                errors="ignore",
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=600,
            )
        else:
            # 开发模式：直接运行解析脚本，模拟 input 交互
            fs = (is_scrolling or "").strip()
            input_lines = [str(output_dir), fs if fs in ("1", "0") else ""]
            if fs in ("1", "0"):
                input_lines.append(scroll_scene or "")
            input_text = "\n".join(input_lines) + "\n"
            proc = subprocess.run(
                [sys.executable, str(PARSER_PY)],
                cwd=str(PARSER_DIR),
                input=input_text,
                text=True,
                encoding="utf-8",
                errors="ignore",
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=600,
            )
        if proc.returncode != 0:
            tail = (proc.stdout or "")[-800:] or (proc.stderr or "")[-800:]
            on_done(f"解析失败: {tail}", None)
            return
        # 优先取本次新生成的 xlsx（文件可能稍晚落盘，短等再扫）
        xlsx = None
        for _ in range(6):
            after = list(Path(output_dir).rglob("*.xlsx"))
            new_files = [p for p in after if p.resolve() not in before]
            if new_files:
                new_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                xlsx = new_files[0]
                break
            cand = _find_generated_xlsx(Path(output_dir))
            if cand is not None:
                try:
                    recent = cand.stat().st_mtime >= (time.time() - 180)
                except OSError:
                    recent = False
                if cand.resolve() not in before or recent:
                    xlsx = cand
                    break
            time.sleep(0.4)
        if xlsx is None:
            tip = (proc.stdout or "")[-500:].strip() or (proc.stderr or "")[-500:].strip()
            on_done(
                "解析结束但未生成 Excel（请确认抓取时长足够、trace≥100KB）"
                + (f"：{tip}" if tip else ""),
                None,
            )
            return
        on_done(None, xlsx)
    except subprocess.TimeoutExpired:
        on_done("解析超时（>10分钟）", None)
    except Exception as e:
        on_done(str(e), None)


def build_perfetto_panel(
    page: ft.Page,
    snack: Callable[[str], None],
    append_lines: Callable[..., None],
) -> ft.Control:
    """构建流畅性分析面板"""

    # 单选：是否属于滑动
    slide_radio = ft.RadioGroup(
        value="",
        content=ft.Row(
            [
                ft.Radio(value="1", label="滑动"),
                ft.Radio(value="0", label="点击"),
                ft.Radio(value="", label="都不是"),
            ],
            spacing=16,
        ),
    )

    # 输入框1：场景（仅滑动时有效）
    scene_input = st.themed_text_field(page, label="滑动场景（如：列表滑动）", expand=True)

    # 输入框2：抓取时长
    duration_input = st.themed_text_field(page, label="抓取时长（ms）", value="10000", width=200)

    async def _append_async(msg: str) -> None:
        """必须在 UI 线程执行，才会触发右侧结果区自动滚到底。"""
        append_lines([msg])

    def _append(msg: str) -> None:
        """后台线程安全：经 page.run_task 回到 UI 事件循环。"""
        try:
            page.run_task(_append_async, msg)
        except Exception:
            try:
                append_lines([msg])
            except Exception:
                pass

    async def _snack_async(msg: str) -> None:
        snack(msg)

    def _ui_snack(msg: str) -> None:
        try:
            page.run_task(_snack_async, msg)
        except Exception:
            try:
                snack(msg)
            except Exception:
                pass

    # ---- 手动解析控件 ----
    ts_dd = ft.Dropdown(label="选择时间戳文件夹", expand=True, options=[])

    def _on_refresh_timestamps(_=None):
        try:
            dirs = _list_timestamp_dirs()
            if not dirs:
                ts_dd.options = []
                ts_dd.value = None
                page.update()
                _append("未检测到结果文件夹")
                return
            ts_dd.options = [ft.dropdown.Option(d) for d in dirs]
            if ts_dd.value not in dirs:
                ts_dd.value = dirs[0]
            page.update()
        except Exception as e:
            snack(f"刷新失败: {e}")

    def _on_parse_manual(_=None):
        val = ts_dd.value
        if not val:
            snack("请先选择一个时间戳文件夹")
            return
        target = _ensure_output_dir() / val
        if not target.is_dir():
            snack(f"文件夹不存在: {target}")
            return
        trace = _find_perfetto_trace(target)
        if not trace:
            snack("未找到 perfetto trace 文件")
            return
        _append(f"开始手动解析: {target}")
        snack("正在解析...")
        threading.Thread(
            target=_run_parser,
            args=(target, slide_radio.value or "", scene_input.value or "", _on_parser_done),
            daemon=True,
        ).start()

    # 抓取完成后的目标目录访问器，由回调提供
    _target_dir_getter = None

    def _on_capture_done(get_target_dir: Callable[[], Path], err: Optional[str]) -> None:
        """抓取完成后回到 UI 线程询问是否解析"""
        nonlocal _target_dir_getter
        _target_dir_getter = get_target_dir

        async def _ui() -> None:
            if err:
                snack(f"抓取失败: {err}")
                append_lines([f"抓取失败: {err}"])
                return
            append_lines(["抓取完成"])
            await _ask_parse_async()

        try:
            page.run_task(_ui)
        except Exception:
            if err:
                _append(f"抓取失败: {err}")
            else:
                _append("抓取完成")

    async def _ask_parse_async() -> None:
        nonlocal _target_dir_getter
        try:
            output_dir = _target_dir_getter() if _target_dir_getter else None
        except Exception:
            output_dir = None
        if not output_dir or not output_dir.is_dir():
            snack("未找到抓取结果目录")
            append_lines(["未找到抓取结果目录"])
            return
        trace = _find_perfetto_trace(output_dir)
        if not trace:
            snack("未找到 perfetto trace 文件")
            append_lines([f"未找到 perfetto trace 文件（目录：{output_dir}）"])
            return
        append_lines([f"结果文件：{trace}"])

        def on_confirm(e=None):
            page.pop_dialog()
            append_lines([f"开始解析: {output_dir}"])
            snack("正在解析...")
            threading.Thread(
                target=_run_parser,
                args=(output_dir, slide_radio.value or "", scene_input.value or "", _on_parser_done),
                daemon=True,
            ).start()

        def on_cancel(e=None):
            page.pop_dialog()
            append_lines(["已跳过解析"])

        confirm_dlg = ft.AlertDialog(
            title=ft.Text("解析结果"),
            content=ft.Text(f"抓取结果已保存到：\n{output_dir}\n\n是否解析生成 Excel 报告？"),
            actions=[
                ft.TextButton("取消", on_click=on_cancel),
                ft.FilledButton("解析", on_click=on_confirm),
            ],
        )
        page.show_dialog(confirm_dlg)

    def _on_parser_done(err: Optional[str], xlsx: Optional[Path]) -> None:
        async def _ui() -> None:
            if err:
                snack(err)
                append_lines([err])
                return
            if xlsx:
                snack(f"报告已生成: {xlsx}")
                append_lines([f"报告已生成: {xlsx}"])
            else:
                snack("解析结束但未生成 Excel 文件")
                append_lines(["解析结束但未生成 Excel 文件"])

        try:
            page.run_task(_ui)
        except Exception:
            if err:
                _append(err)
            elif xlsx:
                _append(f"报告已生成: {xlsx}")
            else:
                _append("解析结束但未生成 Excel 文件")

    def _on_start_click(_):
        # 校验时长
        try:
            duration = int(duration_input.value or "10000")
        except ValueError:
            snack("抓取时长必须是整数（ms）")
            return
        # 清空右侧输出区，并强制滚到底（新一轮抓取）
        try:
            append_lines([], clear=True)
        except Exception:
            pass
        _append("检查 ADB 设备...")
        threading.Thread(
            target=_check_device_then_capture,
            args=(duration,),
            daemon=True,
        ).start()

    def _check_device_then_capture(duration: int) -> None:
        try:
            r = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if "device" not in r.stdout:
                _ui_snack("未检测到 ADB 设备")
                return
        except Exception as e:
            _ui_snack(f"adb 检查异常: {e}")
            return
        _append("ADB 已连接，开始抓取...")
        _run_perfetto_capture(duration, _append, _on_capture_done)

    start_btn = st.btn_primary("开始抓取", icon=ft.Icons.PLAY_ARROW, on_click=_on_start_click)

    return st.themed_panel(
        page,
        padding=10,
        content=ft.Column(
            [
                st.themed_text(page, "流畅性分析", weight=ft.FontWeight.W_500, size=15),
                ft.Row(
                    [
                        st.themed_text(page, "是否属于滑动", size=11, muted=True),
                        slide_radio,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(content=scene_input, padding=ft.Padding.only(top=2)),
                ft.Row([duration_input, start_btn], spacing=8, wrap=True),
                ft.Divider(height=1),
                st.themed_text(page, "手动解析", weight=ft.FontWeight.W_500, size=13),
                ft.Row(
                    [
                        ts_dd,
                        st.btn_info_outline("刷新", icon=ft.Icons.REFRESH, on_click=_on_refresh_timestamps),
                    ],
                    spacing=4,
                ),
                st.btn_primary("解析选中文件夹", icon=ft.Icons.ANALYTICS_OUTLINED, on_click=_on_parse_manual),
                ft.Divider(height=1),
                st.themed_text(page, "开始测试前请：", size=11, muted=True),
                st.themed_text(page, "1. 关闭测试机日志抓取", size=11, muted=True),
                st.themed_text(page, "2. 设置好测试机测试环境", size=11, muted=True),
                st.themed_text(page, "3. 按照用例操作完成前提条件所需内容", size=11, muted=True),
                ft.Text(
                    spans=[
                        ft.TextSpan("4. 滑动场景查询：", style=ft.TextStyle(size=11, color=ft.Colors.ON_SURFACE_VARIANT)),
                        ft.TextSpan(
                            "https://odocs.myoas.com/docs/5rk9dz2yWQS77gqx",
                            on_click=lambda _: webbrowser.open("https://odocs.myoas.com/docs/5rk9dz2yWQS77gqx"),
                            style=ft.TextStyle(size=11, decoration=ft.TextDecoration.UNDERLINE, color=ft.Colors.BLUE),
                        ),
                    ],
                ),
            ],
            scroll=ft.ScrollMode.HIDDEN,
            spacing=4,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    )