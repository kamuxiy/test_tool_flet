# -*- coding: utf-8 -*-
"""ADB 与埋点/充电等业务命令（从原版 main_gui 抽离，供 Flet 与其它 UI 复用）"""

from __future__ import annotations

import datetime
import os
import queue
import re
import subprocess
import sys
import threading
import time
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

from .user_prefs import get_output_dir

CREATE_NO_WINDOW = 0x08000000


def _popen_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def validate_sn(sn: str) -> Optional[str]:
    if sn == "有多个设备，请选择一个":
        return "请选择一个设备"
    if sn == "没有设备":
        return "没有设备"
    if not sn or not str(sn).strip():
        return "请输入设备 SN 或点击自动获取"
    return None


def adb_devices_serials() -> List[str]:
    try:
        r = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=15,
            **_popen_kwargs(),
        )
        lines = r.stdout.splitlines()
        return [line.split("\t")[0].strip() for line in lines if line.strip().endswith("device")]
    except (subprocess.TimeoutExpired, OSError):
        return []


def adb_devices_probe() -> Tuple[List[str], str]:
    """
    返回 (设备序列号列表, 状态码)
    状态码:
      ok      -> adb 可用
      no_adb  -> adb 不存在/不可执行
      error   -> 其他异常
    """
    try:
        r = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=15,
            **_popen_kwargs(),
        )
        lines = r.stdout.splitlines()
        serials = [line.split("\t")[0].strip() for line in lines if line.strip().endswith("device")]
        return serials, "ok"
    except FileNotFoundError:
        return [], "no_adb"
    except OSError:
        return [], "no_adb"
    except subprocess.TimeoutExpired:
        return [], "error"


def refresh_sn_state(current: str) -> Tuple[List[str], str, str]:
    """
    返回 (下拉选项列表, 当前显示文本, adb状态摘要)
    adb状态摘要: 设备连接正常 | 多个设备连接 | 无设备连接 | 设备连接异常
    """
    res, health = adb_devices_probe()
    if len(res) == 1:
        return res, res[0], "设备连接正常"
    if len(res) > 1:
        return res, "有多个设备，请选择一个", "多个设备连接"
    if health == "no_adb":
        return [], "没有设备", "无ADB环境"
    if health == "error":
        return [], "没有设备", "设备连接异常"
    return [], "没有设备", "无设备连接"


def get_device_brief(sn: str) -> Dict[str, str]:
    """
    读取设备简要信息供 UI 展示:
    - sn
    - ota
    - kind: phone/tablet/watch/unknown
    """
    props = {
        "ota": "ro.build.version.ota",
        "characteristics": "ro.build.characteristics",
        "product": "ro.product.name",
        "model": "ro.product.model",
    }
    result: Dict[str, str] = {
        "sn": sn,
        "ota": "",
        "kind": "unknown",
        "product": "",
        "model": "",
        "pcba": "",
        "project_code": "",
    }
    for key, prop in props.items():
        try:
            r = subprocess.run(
                ["adb", "-s", sn, "shell", "getprop", prop],
                capture_output=True,
                text=True,
                timeout=8,
                **_popen_kwargs(),
            )
            val = (r.stdout or "").strip()
        except (subprocess.TimeoutExpired, OSError):
            val = ""
        result[key] = val

    low = " ".join(
        x.lower()
        for x in (
            result.get("characteristics", ""),
            result.get("product", ""),
            result.get("ota", ""),
        )
        if x
    )
    if "watch" in low:
        result["kind"] = "watch"
    elif "tablet" in low or "pad" in low:
        result["kind"] = "tablet"
    else:
        result["kind"] = "phone"

    try:
        r = subprocess.run(
            ["adb", "-s", sn, "shell", "dumpsys", "engineer", "--query_indicate_info"],
            capture_output=True,
            text=True,
            timeout=8,
            **_popen_kwargs(),
        )
        pcba_raw = r.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        pcba_raw = ""
    pcba, project_code = parse_pcba_from_indicate(pcba_raw)
    result["pcba"] = pcba
    result["project_code"] = project_code
    return result


def parse_pcba_from_indicate(text: str) -> tuple[str, str]:
    """
    从 dumpsys engineer --query_indicate_info 输出解析 PCBA 与项目代号。
    代号规则与「获取设备信息」一致：PCBA 去掉空白后第 3～7 位（共 5 位数字）。
    """
    pcba = ""
    for ln in (text or "").splitlines():
        s = ln.strip()
        m = re.match(r"(?i)^PCBA\s*:\s*(.+)$", s)
        if m:
            pcba = m.group(1).strip()
            break
    if not pcba:
        return "", ""
    clean = re.sub(r"\s+", "", pcba)
    code = ""
    if len(clean) >= 7:
        chunk = clean[2:7]
        if chunk.isdigit():
            code = chunk
    if not code:
        m = re.search(r"(\d{5})", clean)
        if m:
            code = m.group(1)
    return pcba, code


def classify_output_lines(lines: List[str]) -> str:
    """成功 | 警告 | 失败"""
    for ln in lines:
        low = ln.lower()
        if "warning" in low:
            return "警告"
        if "error" in low:
            return "失败"
    return "成功"


def run_shell(cmd: str) -> Tuple[int, List[str], List[str]]:
    r = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, **_popen_kwargs()
    )
    out = r.stdout.splitlines() if r.stdout else []
    err = r.stderr.splitlines() if r.stderr else []
    return r.returncode, out, err


def run_command_chain(cmds: List[str]) -> Tuple[str, List[str]]:
    """
    顺序执行多条 shell 命令，行为对齐原版 init_assets_box。
    返回 (结果标题: 成功/警告/失败, 汇总输出行)
    """
    all_lines: List[str] = []
    for cmd in cmds:
        print(cmd)
        all_lines.append(f"$ {cmd}")
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, **_popen_kwargs()
        )
        if r.returncode != 0:
            if r.stderr:
                all_lines.extend(r.stderr.splitlines())
            return "失败", all_lines
        cmd_lines = r.stdout.splitlines() if r.stdout else []
        for i, line in enumerate(cmd_lines):
            low = line.lower()
            if "warning" in low:
                all_lines.extend(cmd_lines)
                return "警告", all_lines
            if "error" in low:
                all_lines.extend(cmd_lines[: i + 1])
                return "失败", all_lines
        all_lines.extend(cmd_lines)
    all_lines.append("End：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return "成功", all_lines


_ADB_PCT_RE = re.compile(r"\[\s*(\d{1,3})\s*%\]|(\d{1,3})\s*%")


def _parse_adb_percent(text: str) -> Optional[int]:
    m = _ADB_PCT_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        pct = int(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= pct <= 100:
        return pct
    return None


def _split_adb_progress_chunks(buf: str) -> Tuple[List[str], str]:
    """按 \\r / \\n 切开 adb 进度刷新，返回 (完整片段, 残余缓冲)。"""
    parts: List[str] = []
    while True:
        i_n = buf.find("\n")
        i_r = buf.find("\r")
        if i_n < 0 and i_r < 0:
            break
        if i_n < 0:
            i = i_r
        elif i_r < 0:
            i = i_n
        else:
            i = min(i_n, i_r)
        piece = buf[:i].strip("\r\n")
        buf = buf[i + 1 :]
        if piece:
            parts.append(piece)
    return parts, buf


def run_adb_argv_chain_with_progress(
    ops: List[Tuple[str, List[str]]],
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[str]]:
    """按 argv 列表顺序执行 adb（push/pull/install），实时回调进度。

    adb 常用 \\r 刷新百分比；若按行 readline 会一直堵在「启动中」。
    这里按字节块读取，并在无输出时发心跳。
    ops: [(显示名, argv), ...]
    """
    all_lines: List[str] = []
    n = len(ops)

    def _emit(msg: str) -> None:
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    for idx, (label, argv) in enumerate(ops, start=1):
        cmd_show = " ".join(argv)
        print(cmd_show)
        all_lines.append(f"$ {cmd_show}")
        head = f"[{idx}/{n}] {label}"
        _emit(f"{head}\n当前进度：启动中…")
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            **_popen_kwargs(),
        )
        assert proc.stdout is not None
        cmd_out: List[str] = []
        last_pct = -1
        last_detail = ""
        text_buf = ""
        t0 = time.monotonic()
        last_beat = t0

        q: queue.Queue = queue.Queue()

        def _reader() -> None:
            try:
                while True:
                    chunk = proc.stdout.read(256)
                    if not chunk:
                        break
                    if isinstance(chunk, bytes):
                        q.put(chunk.decode("utf-8", errors="replace"))
                    else:
                        q.put(str(chunk))
            finally:
                q.put(None)

        th = threading.Thread(target=_reader, daemon=True)
        th.start()

        eof = False
        while not eof:
            try:
                item = q.get(timeout=0.25)
            except queue.Empty:
                item = ()
            if item is None:
                eof = True
            elif isinstance(item, str):
                text_buf += item
                pieces, text_buf = _split_adb_progress_chunks(text_buf)
                for text in pieces:
                    cmd_out.append(text)
                    last_detail = text
                    pct = _parse_adb_percent(text)
                    if pct is not None:
                        last_pct = pct
                        _emit(f"{head}\n当前进度：{pct}%\n{text}")
                    else:
                        shown = f"{last_pct}%" if last_pct >= 0 else "进行中…"
                        _emit(f"{head}\n当前进度：{shown}\n{text}")
                    last_beat = time.monotonic()

            now = time.monotonic()
            if proc.poll() is not None and eof:
                break
            if now - last_beat >= 0.8 and proc.poll() is None:
                elapsed = int(now - t0)
                shown = f"{last_pct}%" if last_pct >= 0 else "进行中…"
                extra = f"\n{last_detail}" if last_detail else ""
                _emit(f"{head}\n当前进度：{shown}（已用时 {elapsed}s）{extra}")
                last_beat = now

        # 残余缓冲
        rem = text_buf.strip("\r\n")
        if rem:
            cmd_out.append(rem)
            pct = _parse_adb_percent(rem)
            if pct is not None:
                last_pct = pct
            _emit(f"{head}\n当前进度：{last_pct if last_pct >= 0 else 100}%\n{rem}")

        rc = proc.wait()
        th.join(timeout=2)
        if rc != 0:
            all_lines.extend(cmd_out)
            tip = cmd_out[-1] if cmd_out else f"exit={rc}"
            _emit(f"{head}\n失败：{tip}")
            return "失败", all_lines
        for i, line in enumerate(cmd_out):
            low = line.lower()
            if "warning" in low:
                all_lines.extend(cmd_out)
                return "警告", all_lines
            if "error" in low and "no error" not in low:
                all_lines.extend(cmd_out[: i + 1])
                return "失败", all_lines
        all_lines.extend(cmd_out)
        _emit(f"{head}\n当前进度：100%\n本项完成")
    all_lines.append("End：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    _emit("\n".join(all_lines[-12:]) if all_lines else "完成")
    return "成功", all_lines


def run_command_chain_with_progress(
    cmds: List[str],
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[str, List[str]]:
    """兼容旧接口：shell 命令字符串。推送/拉取请优先用 run_adb_argv_chain_with_progress。"""
    ops = [(c, ["cmd", "/c", c] if sys.platform == "win32" else ["bash", "-lc", c]) for c in cmds]
    # Windows 上用 cmd /c 仍可能缓冲；尽量让调用方改用 argv 版
    return run_adb_argv_chain_with_progress(ops, on_progress=on_progress)


def get_package_cmd(sn: str) -> str:
    if sys.platform == "win32":
        return f"adb -s {sn} shell dumpsys window | findstr w="
    return f"adb -s {sn} shell dumpsys window | grep -E 'mCurrentFocus|w=' || true"


def build_dcs_change_env(sn: str, env: str, region: str) -> List[str]:
    in_url = "https://obus-dct-in.heytapmobile.com"
    cn_url = "https://obus-dct-cn.heytapmobi.com"
    sg_url = "https://obus-dct-sg.heytapmobile.com"
    if env == "测试环境":
        if region == "国内上报":
            return [
                f"adb -s {sn} shell dumpsys activity provider DcsContentProvider setServer pre {cn_url}"
            ]
        if region == "海外上报":
            return [
                f"adb -s {sn} shell dumpsys activity provider DcsContentProvider setServer pre {sg_url}"
            ]
        if region == "印度上报":
            return [
                f"adb -s {sn} shell dumpsys activity provider DcsContentProvider setServer pre {in_url}"
            ]
    if env == "正式环境":
        return [
            f"adb -s {sn} shell dumpsys activity provider DcsContentProvider setServer release"
        ]
    return []


CHARGE_ITEMS = [
    "允许充电",
    "禁止充电",
    "电量",
    "低电",
    "电量40",
    "断充",
    "连续断充",
    "进入充电保护",
    "退出充电保护",
    "预期满电",
    "预期满电拔电",
    "非预期满电",
    "普充",
    "快速充电",
    "快速充电 - 带瓦数",
    "闪充",
    "超级闪充不带瓦数",
    "超级闪充带瓦数65w",
    "超级闪充带瓦数100w",
    "无线普电 - 不带瓦数",
    "无线普电 - 带瓦数",
    "无线闪充 - 不带瓦数",
    "无线闪充 - 带瓦数",
    "进入极寒模式",
    "退出极寒模式",
    "无线反充",
]


def build_charge_commands(sn: str, item: str) -> Optional[List[str]]:
    if item == "允许充电":
        return [f"adb -s {sn} shell dumpsys battery set usb 1"]
    if item == "禁止充电":
        return [f"adb -s {sn} shell dumpsys battery set usb 0"]
    if item == "电量":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.BATTERY_CHANGED --ei level %1 --ei scale 100"
        ]
    if item == "低电":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 100 --ei chargewattage 100 --ei status 4 --ei scale 100 --ei chargeplugged 0",
            f"adb -s {sn} shell am broadcast -a android.intent.action.BATTERY_CHANGED --ei level 10 --ei scale 100",
        ]
    if item == "电量40":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.BATTERY_CHANGED --ei level 40 --ei scale 100"
        ]
    if item == "断充":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei ui_charge_wattage 100 --ei status 4 --ei chargeplugged 0"
        ]
    if item == "连续断充":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargeplugged 0 --ei status 2 --ei scale 100 ",
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargeplugged 0  --ei level 100 --ei status 4 --ei scale 100",
        ]
    if item == "进入充电保护":
        return [f"adb -s {sn} shell settings put system charge_protection_current_state 1"]
    if item == "退出充电保护":
        return [f"adb -s {sn} shell settings put system charge_protection_current_state 0"]
    if item == "预期满电":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 100 --ei chargewattage 100 --ei status 5 --ei chargeplugged 1"
        ]
    if item == "预期满电拔电":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei chargewattage 100 --ei status 4 --ei plugged 0"
        ]
    if item == "非预期满电":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 100 --ei chargewattage 100 --ei status 5 --ei chargeplugged 0"
        ]
    if item == "普充":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 0 --ei cpa_charge_wattage 0 --ei chargewattage 0 --ei status 2 --ei chargeplugged 1"
        ]
    if item == "快速充电":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 1 --ei cpa_charge_wattage 18 --ei chargewattage 0 --ei status 2 --ei chargeplugged 1"
        ]
    if item == "快速充电 - 带瓦数":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 1 --ei cpa_charge_wattage 18 --ei chargewattage 18 --ei status 2 --ei chargeplugged 1"
        ]
    if item == "闪充":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 2 --ei ui_charge_wattage 0 --ei status 2 --ei chargeplugged 1"
        ]
    if item == "超级闪充不带瓦数":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 0 --ei chargewattage 0 --ei status 2 --ei chargeplugged 1"
        ]
    if item == "超级闪充带瓦数65w":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 65 --ei chargewattage 65 --ei status 2 --ei chargeplugged 1"
        ]
    if item == "超级闪充带瓦数100w":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 100 --ei chargewattage 100 --ei status 2 --ei chargeplugged 1"
        ]
    if item == "无线普电 - 不带瓦数":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 0 --ei cpa_charge_wattage 0 --ei chargewattage 0 --ei status 2 --ei chargeplugged 4"
        ]
    if item == "无线普电 - 带瓦数":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 0 --ei cpa_charge_wattage 10 --ei chargewattage 10 --ei status 2 --ei chargeplugged 4"
        ]
    if item == "无线闪充 - 不带瓦数":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 0 --ei chargewattage 0 --ei status 2 --ei chargeplugged 4"
        ]
    if item == "无线闪充 - 带瓦数":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 100 --ei chargewattage 100 --ei status 2 --ei chargeplugged 4"
        ]
    if item == "进入极寒模式":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 100 --ei chargewattage 100 --ei status 2 --ei chargeplugged 1 --ei bms_heating_status 1 "
        ]
    if item == "退出极寒模式":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ei chargertechnology 3 --ei cpa_charge_wattage 100 --ei chargewattage 100 --ei status 2 --ei chargeplugged 1 --ei bms_heating_status 0"
        ]
    if item == "无线反充":
        return [
            f"adb -s {sn} shell am broadcast -a android.intent.action.ADDITIONAL_BATTERY_CHANGED --ez wirelessChargingReverse true --ei chargertechnology 0 --ei chargewattage 100 --ei status 4 --ei chargeplugged 1  --ei wireless_reverse_chg_type 1"
        ]
    return None


def get_device_info_lines(sn: str) -> Tuple[str, List[str]]:
    """获取设备信息（多段 adb），返回 (结果标题, 行列表)。"""
    err = validate_sn(sn)
    if err:
        return "失败", [err]

    cmds = {
        "product": f"adb -s {sn} shell getprop ro.product.name",
        "region": f"adb -s {sn} shell getprop ro.oppo.regionmark",
        "coloros": f"adb -s {sn} shell getprop ro.build.version.opporom",
        "android": f"adb -s {sn} shell getprop ro.build.version.release",
        "ota": f"adb -s {sn} shell getprop ro.build.version.ota",
        "locked": f"adb -s {sn} shell getprop ro.boot.flash.locked",
        "engineer": f"adb -s {sn} shell dumpsys engineer --query_indicate_info",
    }
    lines: List[str] = []
    worst = "成功"

    def run_one(cmd: str, prefix: Optional[str] = None):
        nonlocal worst
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, **_popen_kwargs()
        )
        if r.returncode != 0:
            worst = "失败"
            return
        out = r.stdout.splitlines() if r.stdout else []
        for ln in out:
            low = ln.lower()
            if "error" in low:
                worst = "失败"
            elif "warning" in low and worst == "成功":
                worst = "警告"
        if prefix and out:
            lines.append(prefix + out[0])
            lines.extend(out[1:])
        elif out:
            lines.extend(out)

    run_one(cmds["product"], "机型：")
    run_one(cmds["region"])
    run_one(cmds["coloros"])
    run_one(cmds["android"], "Android版本：")
    run_one(cmds["ota"], "OTA版本：")
    run_one(cmds["engineer"])
    r = subprocess.run(
        cmds["locked"],
        shell=True,
        capture_output=True,
        text=True,
        **_popen_kwargs(),
    )
    if r.returncode == 0 and r.stdout:
        lo = r.stdout.splitlines()[0]
        lines.append(
            "设备锁状态："
            + lo
            + "（1未解锁，可测试）-（0解锁，无法测试，检测不到增量包）"
        )
    lines.append("End：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return worst, lines


def dcs_run_step(sn: str, shell_cmd: str) -> Tuple[bool, str, List[str]]:
    """单步埋点 shell，成功且输出无 warning/error 行则 ok。"""
    code, out, err = run_shell(shell_cmd)
    lines = list(out)
    if code != 0:
        lines.extend(err)
        return False, "失败", lines
    st = classify_output_lines(lines)
    if st == "失败":
        return False, "失败", lines
    if st == "警告":
        return False, "警告", lines
    return True, "成功", lines


def dcs_auto_test_phase1(sn: str) -> Tuple[bool, str, List[str]]:
    """一键埋点：步骤 1～3，不含用户确认对话框。"""
    err = validate_sn(sn)
    if err:
        return False, "失败", [err]
    acc: List[str] = []
    steps = [
        ("操作步骤_1:开启日志：", f"adb -s {sn} shell dumpsys activity provider DcsContentProvider debug 1"),
        ("操作步骤_2:检查环境：", f"adb -s {sn} shell dumpsys activity provider DcsContentProvider env"),
        (
            "操作步骤_3:设置测试环境：",
            f"adb -s {sn} shell dumpsys activity provider DcsContentProvider setServer pre https://obus-dct-cn.heytapmobi.com",
        ),
    ]
    for title, cmd in steps:
        acc.append(title)
        ok, st, lines = dcs_run_step(sn, cmd)
        acc.extend(lines)
        if not ok:
            return False, st, acc
    acc.append("默认设置为国内上报")
    acc.append("等待用户操作中...")
    return True, "成功", acc


def dcs_auto_test_phase2(sn: str) -> Tuple[bool, str, List[str]]:
    """一键埋点：步骤 4～5（用户确认后）。"""
    acc: List[str] = []
    acc.append("操作步骤_4:保存到数据库：")
    record_cmd = f"adb -s {sn} shell dumpsys activity provider DcsContentProvider record data"
    last = None
    for _ in range(3):
        last = subprocess.run(
            record_cmd,
            shell=True,
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )
    if not last or last.returncode != 0:
        return False, "失败", acc
    lines = last.stdout.splitlines() if last.stdout else []
    st = classify_output_lines(lines)
    acc.extend(lines)
    if st != "成功":
        return False, st, acc

    acc.append("操作步骤_5:再次触发一次埋点上传：")
    upload_cmd = f"adb -s {sn} shell dumpsys activity provider DcsContentProvider upload StatisticData"
    last2 = None
    for _ in range(3):
        last2 = subprocess.run(
            upload_cmd,
            shell=True,
            capture_output=True,
            text=True,
            **_popen_kwargs(),
        )
    if not last2 or last2.returncode != 0:
        return False, "失败", acc
    lines2 = last2.stdout.splitlines() if last2.stdout else []
    st2 = classify_output_lines(lines2)
    acc.extend(lines2)
    if st2 != "成功":
        return False, st2, acc
    acc.append("埋点上报完成，现在可以去Obus平台查询埋点记录")
    acc.append("End：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return True, "成功", acc


def search_log_command(sn: str) -> List[str]:
    return [f"adb -s {sn} shell ls sdcard/android/data/com.oplus.logkit/files/log"]


def get_remote_folder_size(device_serial: str, remote_path: str) -> int:
    cmd = ["adb", "-s", device_serial, "shell", f"du -sk '{remote_path}'"]
    try:
        output = subprocess.check_output(cmd, **_popen_kwargs()).decode().split()[0]
        return int(output) * 1024
    except Exception:
        return 0


def get_local_folder_size(local_path: str) -> int:
    total_size = 0
    if not os.path.exists(local_path):
        return 0
    if os.path.isfile(local_path):
        return os.path.getsize(local_path)
    for dirpath, _, filenames in os.walk(local_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size


def download_log_with_progress(
    save_sn: str,
    phone_log_path: str,
    phone_log_name: str,
    total_bytes: int,
    on_progress: Callable[[int, int], None],
) -> Tuple[bool, List[str]]:
    log_dir = str(get_output_dir("log_export"))
    os.makedirs(log_dir, exist_ok=True)
    lines: List[str] = []
    proc = subprocess.Popen(
        ["adb", "-s", save_sn, "pull", phone_log_path, log_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        **_popen_kwargs(),
    )
    while proc.poll() is None:
        local_path = os.path.join(log_dir, phone_log_name)
        if os.path.exists(local_path) and total_bytes > 0:
            received = get_local_folder_size(local_path)
            on_progress(received, total_bytes)
        time.sleep(0.5)
    ok = proc.returncode == 0
    if ok:
        lines.append("当前传输进度：100%")
        lines.append(str(total_bytes))
        lines.append("当前传输完成")
    else:
        err = proc.stderr.read() if proc.stderr else ""
        lines.append("pull 失败: " + (err or "unknown"))
    return ok, lines


def compress_folder_to_zip(
    folder_path: str,
    on_line: Callable[[str], None],
    *,
    on_zip_tick: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    zip_file_name = f"{folder_path.rstrip(os.sep)}.zip"
    files_to_zip: List[str] = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            files_to_zip.append(os.path.join(root, f))
    total_files = len(files_to_zip)
    if total_files == 0:
        on_line("无文件可压缩")
        return ["无文件可压缩"]
    lines: List[str] = ["开始压缩..."]
    if not on_zip_tick:
        on_line("开始压缩...")
    with zipfile.ZipFile(zip_file_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, file_path in enumerate(files_to_zip, 1):
            arcname = os.path.relpath(file_path, folder_path)
            zf.write(file_path, arcname)
            msg = f"当前压缩进度：{str(i / total_files * 100)}%"
            lines.append(msg)
            if on_zip_tick:
                on_zip_tick(i, total_files)
            else:
                on_line(msg)
    lines.append("压缩完成，压缩包路径：")
    lines.append(zip_file_name)
    return lines


def _parse_foreground_pkg_activity(dumpsys_text: str) -> Tuple[Optional[str], Optional[str]]:
    """从 dumpsys activity 合并文本中解析前台 package 与 activity（回退用）。"""
    if not dumpsys_text:
        return None, None
    patterns = [
        r"ACTIVITY\s+([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)/([a-zA-Z0-9_.]+)\s",
        r"mResumedActivity[^\n]*\s([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)/([a-zA-Z0-9_.]+)",
        r"mCurrentFocus[^\n]*\s([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)/([a-zA-Z0-9_.]+)",
        r"topResumedActivity[^\n]*\s([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)/([a-zA-Z0-9_.]+)",
    ]
    for pat in patterns:
        m = re.search(pat, dumpsys_text)
        if m:
            return m.group(1), m.group(2)
    return None, None


def _parse_pkg_act_from_window_brace(inner: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析 Window{ ... } 内部 token，形如：「5d2f3ab u0 com.pkg/.Main」或「u0 com.pkg/com.pkg.Main」。
    从右向左找第一个含「包名/组件」的 token。
    """
    inner = (inner or "").strip()
    if not inner:
        return None, None
    pkg_re = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+$")
    act_re = re.compile(r"^[.a-zA-Z0-9_]+$")
    for token in reversed(inner.split()):
        if "/" not in token:
            continue
        parts = token.split("/", 1)
        if len(parts) != 2:
            continue
        left, right = parts[0], parts[1]
        if not pkg_re.match(left) or not act_re.match(right):
            continue
        return left, right
    return None, None


def _parse_pkg_act_from_dumpsys_window(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    从 dumpsys window 输出解析包名/Activity。
    优先 mFocusedWindow=Window{ ... }，其次 mCurrentFocus=Window{ ... }。
    返回 (package, activity, 命中的原始行片段，供诊断)。
    """
    if not text:
        return None, None, None
    for key in ("mFocusedWindow=Window{", "mCurrentFocus=Window{"):
        idx = 0
        while True:
            pos = text.find(key, idx)
            if pos < 0:
                break
            line_end = text.find("\n", pos)
            snippet = text[pos : line_end if line_end >= 0 else len(text)]
            brace_start = pos + len(key) - 1  # 指向 '{'
            depth = 0
            end_j = -1
            for j in range(brace_start, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        end_j = j
                        break
            if end_j < 0:
                idx = pos + 1
                continue
            inner = text[brace_start + 1 : end_j]
            pkg, act = _parse_pkg_act_from_window_brace(inner)
            if pkg:
                return pkg, act, snippet.strip()[:240]
            idx = end_j + 1
    return None, None, None


def get_foreground_package_activity(sn: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    读取当前前台包名与 Activity（页面组件名）。
    优先：adb shell dumpsys window，解析 mFocusedWindow=Window{ ... }（与手动「dumpsys window | findstr w=」后查看该行一致）。
    若全文未解析到，再仅用含「w=」的行拼接后重试（等价 findstr w=）。
    最后回退：dumpsys activity top / activities。
    返回 (package, activity, 简要诊断行)。
    """
    meta: List[str] = []

    try:
        r = subprocess.run(
            ["adb", "-s", sn, "shell", "dumpsys", "window"],
            capture_output=True,
            text=True,
            timeout=25,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        wout = r.stdout or ""
        meta.append(f"dumpsys window exit={r.returncode}")

        pkg, act, snippet = _parse_pkg_act_from_dumpsys_window(wout)
        if snippet:
            meta.append(f"mFocused 命中: {snippet}")
        if pkg:
            meta.append("来源: dumpsys window (mFocusedWindow / mCurrentFocus)")
            return pkg, act, meta

        w_lines = "\n".join(
            ln
            for ln in wout.splitlines()
            if "w=" in ln or "mFocusedWindow" in ln or "mCurrentFocus" in ln
        )
        if w_lines and w_lines != wout:
            meta.append("重试: 含 w= 或焦点窗口行（对齐 findstr w= + 焦点行）")
            pkg, act, snippet = _parse_pkg_act_from_dumpsys_window(w_lines)
            if snippet:
                meta.append(f"mFocused 命中: {snippet}")
            if pkg:
                meta.append("来源: dumpsys window + w= 过滤")
                return pkg, act, meta
    except (subprocess.TimeoutExpired, OSError) as e:
        meta.append(f"dumpsys window 失败: {e}")

    chunks: List[str] = []
    for label, args in (
        ("activity top", ["shell", "dumpsys", "activity", "top"]),
        ("activity activities", ["shell", "dumpsys", "activity", "activities"]),
    ):
        try:
            r = subprocess.run(
                ["adb", "-s", sn, *args],
                capture_output=True,
                text=True,
                timeout=25,
                encoding="utf-8",
                errors="replace",
                **_popen_kwargs(),
            )
            chunks.append(r.stdout or "")
            meta.append(f"dumpsys {label} exit={r.returncode}")
        except (subprocess.TimeoutExpired, OSError) as e:
            meta.append(f"dumpsys {label} 失败: {e}")
    text = "\n".join(chunks)[:120000]
    pkg, act = _parse_foreground_pkg_activity(text)
    if pkg:
        meta.append("来源: dumpsys activity（回退）")
    return pkg, act, meta


def run_quick_traverse_monkey_error_log(sn: str) -> Tuple[str, List[str]]:
    """
    快捷遍历：对当前前台包名执行约 30s Monkey，同时仅采集 logcat Error 及以上（*:E）。
    返回 (用于状态角标: 成功/失败/警告, 输出行列表)。
    """
    err = validate_sn(sn)
    if err:
        return "失败", [err]

    pkg, activity, dbg = get_foreground_package_activity(sn)
    lines: List[str] = [
        "【快捷遍历】读取前台应用",
        *dbg,
        f"包名: {pkg or '—'}",
        f"页面(Activity): {activity or '—'}",
    ]
    if not pkg:
        lines.append("无法解析前台包名，请保持目标界面在前台、亮屏后重试。")
        return "失败", lines

    # 约 30s：60 事件 × 500ms throttle
    throttle_ms = "500"
    event_count = "60"
    monkey_cmd = [
        "adb",
        "-s",
        sn,
        "shell",
        "monkey",
        "-p",
        pkg,
        "--throttle",
        throttle_ms,
        "--pct-touch",
        "45",
        "--pct-motion",
        "20",
        "--pct-nav",
        "10",
        "--pct-majornav",
        "10",
        "--pct-syskeys",
        "10",
        "--pct-trackball",
        "0",
        "--pct-pinchzoom",
        "0",
        "--pct-flip",
        "5",
        "--ignore-crashes",
        "--ignore-timeouts",
        "-v",
        "-v",
        event_count,
    ]
    lines.append("$ " + " ".join(monkey_cmd))
    lines.append("并行: adb shell logcat -v time *:E（仅 Error 及以上）")
    lines.append("---")

    log_lines: List[str] = []
    log_holder: dict = {}

    def _read_logcat() -> None:
        try:
            proc = subprocess.Popen(
                ["adb", "-s", sn, "shell", "logcat", "-v", "time", "*:E"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_popen_kwargs(),
            )
        except OSError as e:
            log_lines.append(f"logcat 启动失败: {e}")
            return
        log_holder["p"] = proc
        out = proc.stdout
        if not out:
            return
        while True:
            line = out.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            log_lines.append(line.rstrip())

    th = threading.Thread(target=_read_logcat, daemon=True)
    th.start()
    time.sleep(0.35)

    monkey_result = None
    try:
        monkey_result = subprocess.run(
            monkey_cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        lines.append(f"Monkey 退出码: {monkey_result.returncode}")
        if monkey_result.stdout:
            lines.append("--- monkey 输出 ---")
            lines.extend((monkey_result.stdout or "").strip().splitlines()[:100])
        if monkey_result.stderr:
            lines.extend((monkey_result.stderr or "").strip().splitlines()[:40])
    except subprocess.TimeoutExpired:
        lines.append("Monkey 执行超时。")
    except OSError as e:
        lines.append(f"Monkey 执行失败: {e}")
    finally:
        p = log_holder.get("p")
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            try:
                p.wait(timeout=4)
            except Exception:
                pass
        th.join(timeout=3)

    lines.append("--- logcat（*:E 仅错误级）---")
    if log_lines:
        tail = log_lines[-600:] if len(log_lines) > 600 else log_lines
        lines.extend(tail)
    else:
        lines.append("（本时段内无 Error 级别 logcat 行）")

    if monkey_result is None:
        return "失败", lines
    if monkey_result.returncode != 0:
        return "失败", lines
    st = classify_output_lines(log_lines) if log_lines else "成功"
    if st == "失败":
        return "失败", lines
    if st == "警告":
        return "警告", lines
    return "成功", lines


def pm_clear_package_data(sn: str, package: str) -> Tuple[str, List[str]]:
    """
    执行 adb shell pm clear <package>，清除该包应用数据。
    返回 (成功|失败, 输出行)。
    """
    err = validate_sn(sn)
    if err:
        return "失败", [err]
    pkg = (package or "").strip()
    if not pkg:
        return "失败", ["包名为空"]
    cmd = ["adb", "-s", sn, "shell", "pm", "clear", pkg]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return "失败", [f"$ {' '.join(cmd)}", str(e)]
    lines: List[str] = ["$ " + " ".join(cmd)]
    if r.stdout and r.stdout.strip():
        lines.append(r.stdout.strip())
    if r.stderr and r.stderr.strip():
        lines.append(r.stderr.strip())
    if r.returncode != 0:
        return "失败", lines
    return "成功", lines
