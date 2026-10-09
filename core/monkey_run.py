# -*- coding: utf-8 -*-
"""AOSP Monkey 命令构建与启动（对齐原版 aosp_monkey_tools）"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .adb import _popen_kwargs


@dataclass
class MonkeyParams:
    sn: str
    package_name: str = ""
    package_mode: int = 1  # 1 单包名 2 白名单文件
    seed: str = ""
    times: str = "300000"
    delay: str = "500"
    nav: str = "0"
    main_nav: str = "2"
    touch: str = "50"
    motion: str = "15"
    trackball: str = "0"
    pinchzoom: str = "5"
    system_key: str = "5"
    flip: str = "1"
    crashes_yes: bool = True
    timeouts_yes: bool = True
    log_level: str = "-v -v"
    save_error_log: bool = True
    logcat_extra: bool = True
    whitelist_local_path: str = ""


def validate_sn(sn: str) -> Optional[str]:
    if sn in ("没有设备", "有多个设备，请选择一个"):
        return "请选择有效设备 SN"
    if not sn or not str(sn).strip():
        return "请输入或自动获取 SN"
    return None


def build_monkey_cmd(p: MonkeyParams) -> Tuple[Optional[str], Optional[str]]:
    err = validate_sn(p.sn)
    if err:
        return None, err
    if p.package_mode == 1 and not (p.package_name or "").strip():
        return None, "请输入包名"
    if p.package_mode == 2 and not (p.whitelist_local_path or "").strip():
        return None, "请填写白名单文件路径"

    seed = f"-s {p.seed}" if (p.seed or "").strip() else ""
    delay = p.delay or "500"
    nav = p.nav or "0"
    main_nav = p.main_nav or "2"
    touch = p.touch or "50"
    motion = p.motion or "15"
    trackball = p.trackball or "0"
    pinchzoom = p.pinchzoom or "5"
    system_key = p.system_key or "5"
    flip = p.flip or "1"
    crashes = "--ignore-crashes" if p.crashes_yes else ""
    timeouts = "--ignore-timeouts" if p.timeouts_yes else ""
    time = p.times or "300000"
    log = p.log_level or "-v -v"

    if p.package_mode == 1:
        cmd = (
            f"adb -s {p.sn} shell monkey -p {p.package_name} --throttle {delay} "
            f"--pct-nav {nav} --pct-majornav {main_nav} --pct-touch {touch} "
            f"--pct-motion {motion} --pct-trackball {trackball} --pct-pinchzoom {pinchzoom} "
            f"--pct-syskeys {system_key} --pct-flip {flip} {crashes} {timeouts} {log} {seed} {time}"
        )
    else:
        cmd = (
            f"adb -s {p.sn} shell monkey --pkg-whitelist-file sdcard/Download/monkeywhitelist.txt "
            f"--throttle {delay} --pct-nav {nav} --pct-majornav {main_nav} --pct-touch {touch} "
            f"--pct-motion {motion} --pct-trackball {trackball} --pct-pinchzoom {pinchzoom} "
            f"--pct-syskeys {system_key} --pct-flip {flip} {crashes} {timeouts} {log} {seed} {time}"
        )
    return " ".join(cmd.split()), None


def _ensure_error_dir() -> str:
    base = "D:\\error\\"
    if not os.path.exists(base):
        os.mkdir(base)
    l_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    folder = os.path.join(base, l_time)
    os.mkdir(folder)
    return l_time


def _save_error_log(cmd: str, l_time: str) -> None:
    err_file = os.path.join("D:\\error", l_time, "MonkeyError.log")
    os.makedirs(os.path.dirname(err_file), exist_ok=True)
    full = f'{cmd} 2> "{err_file}"'
    subprocess.Popen(
        full,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_popen_kwargs(),
    )


def _dont_save_error_log(cmd: str, _l_time: str) -> None:
    subprocess.Popen(
        cmd,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **_popen_kwargs(),
    )


def _logcat_workers(sn: str, l_time: str) -> List[threading.Thread]:
    def make(_title: str, pat: str, fname: str):
        def run():
            out_path = os.path.join("D:\\error", l_time, fname)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            if sys.platform == "win32":
                pipeline = (
                    f'adb -s {sn} shell logcat | findstr {pat} > "{out_path}"'
                )
            else:
                pipeline = (
                    f'adb -s {sn} shell logcat 2>/dev/null | grep -E {pat} > "{out_path}"'
                )
            subprocess.Popen(
                pipeline,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_popen_kwargs(),
            )

        return run

    return [
        threading.Thread(target=make("LogcatError", "error", "error.log")),
        threading.Thread(target=make("LogcatFatal", "fatal", "fatal.log")),
        threading.Thread(target=make("LogcatException", "exception", "exception.log")),
        threading.Thread(target=make("LogcatANR", "anr", "anr.log")),
        threading.Thread(target=make("LogcatCrash", "crash", "crash.log")),
    ]


def run_monkey(
    p: MonkeyParams,
    on_log: Callable[[str], None],
) -> None:
    cmd, err = build_monkey_cmd(p)
    if err:
        on_log("错误: " + err)
        return
    assert cmd
    l_time = _ensure_error_dir()
    on_log(f"Monkey 命令:\n{cmd}\n日志目录: D:\\error\\{l_time}\\")

    if p.save_error_log:
        t = threading.Thread(target=_save_error_log, args=(cmd, l_time))
    else:
        t = threading.Thread(target=_dont_save_error_log, args=(cmd, l_time))
    t.start()
    t.join()

    if p.logcat_extra:
        for th in _logcat_workers(p.sn, l_time):
            th.start()
            th.join()

    on_log(
        "Monkey 已在后台运行（无独立 CMD 窗口）；请勿重复点击开始。\n请定期清理 D:\\error 文件夹。"
    )


def push_whitelist(sn: str, file_path: str, on_log: Callable[[str], None]) -> None:
    err = validate_sn(sn)
    if err:
        on_log("错误: " + err)
        return
    if not (file_path or "").strip():
        on_log("错误: 请填写白名单文件路径")
        return
    cmd = f"adb -s {sn} push {file_path} sdcard/Download/monkeywhitelist.txt"
    on_log("上传白名单:\n" + cmd)
    r = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        **_popen_kwargs(),
    )
    if r.stdout:
        on_log(r.stdout.strip())
    if r.stderr:
        on_log(r.stderr.strip())
    if r.returncode != 0:
        on_log(f"退出码: {r.returncode}")
