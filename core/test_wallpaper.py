# -*- coding: utf-8 -*-
"""生成测试机标识壁纸（1080×2352，底色 #56585D）并 adb push 到 DCIM。"""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import tempfile
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .adb import _popen_kwargs, adb_devices_serials, validate_sn

W_IMG, H_IMG = 1080, 2352
# 壁纸配色：底色 #56585D，文字 #FFFFFF
WALLPAPER_BG = (0x56, 0x58, 0x5D)
WALLPAPER_FG = (0xFF, 0xFF, 0xFF)
FONT_START = 48
LINE_GAP = 18


def _ensure_device_online(sn: str) -> Optional[str]:
    err = validate_sn(sn)
    if err:
        return err
    serials = adb_devices_serials()
    if not serials:
        return "未检测到已通过 adb 连接的设备，请先连接测试机并开启 USB 调试。"
    if sn.strip() not in serials:
        return f"当前 SN 未在设备列表中。已连接：{', '.join(serials)}"
    return None


def _run_adb_shell(
    sn: str, argv_after_shell: List[str], timeout: int = 45
) -> subprocess.CompletedProcess:
    cmd = ["adb", "-s", sn, "shell", *argv_after_shell]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        **_popen_kwargs(),
    )


def _get_prop_single_line(sn: str, prop_key: str, label_zh: str) -> Tuple[bool, str]:
    r = _run_adb_shell(sn, ["getprop", prop_key])
    if r.returncode != 0:
        hint = (r.stderr or "") + (r.stdout or "")
        return False, (
            f"获取{label_zh}失败({prop_key}) code={r.returncode}: {hint.strip()}"
        )
    raw = (r.stdout or "").strip()
    row0 = raw.splitlines()[0] if raw.splitlines() else ""
    return True, row0 or "(空)"


def get_ota_version(sn: str) -> Tuple[bool, str]:
    return _get_prop_single_line(sn, "ro.build.version.ota", "OTA")


def parse_imei1_from_engineer(sn: str) -> Tuple[bool, str]:
    r = _run_adb_shell(sn, ["dumpsys", "engineer", "--query_indicate_info"], timeout=60)
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    if r.returncode != 0:
        return False, f"dumpsys engineer 失败(code={r.returncode}): {out[:500]}"
    patterns = [
        r"(?i)(?:slot\s*1|IMEI\s*1|IMEI1)\s*[:=]\s*([0-9]{8,22})",
        r"(?i)IMEI1\s*[：:]\s*([0-9]{8,22})",
        r"(?i)imei\[?0\]?\s*[:=]\s*([0-9]{8,22})",
    ]
    for pat in patterns:
        m = re.search(pat, out)
        if m:
            return True, m.group(1).strip()
    m = re.search(r"(?i)IMEI[12]?\D{0,6}([0-9]{14,17})", out)
    if m:
        return True, m.group(1).strip()
    short = "\n".join(out.splitlines()[:30])
    return False, (
        "输出中未找到 IMEI1，请确认机型支持 dumpsys engineer。\n预览:\n" + short
    )


def _pick_font(size: int) -> ImageFont.ImageFont:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts = [
        os.path.join(windir, "Fonts", "msyh.ttc"),
        os.path.join(windir, "Fonts", "msyhbd.ttf"),
        os.path.join(windir, "Fonts", "simhei.ttf"),
        os.path.join(windir, "Fonts", "arial.ttf"),
    ]
    for p in fonts:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    if not (text or "").strip():
        return []
    rows: List[str] = []
    for segment in text.replace("\r\n", "\n").split("\n"):
        if not segment:
            continue
        line = ""
        for ch in segment:
            trial = line + ch
            try:
                bb = draw.textbbox((0, 0), trial, font=font)
                w = bb[2] - bb[0]
            except Exception:
                w = len(trial) * 10
            if w <= max_width or not line:
                line = trial
            else:
                rows.append(line)
                line = ch
        if line:
            rows.append(line)
    return rows


def _layout_and_draw_png(
    dst_path: str,
    rows: List[str],
) -> None:
    inner_w = W_IMG - 160
    font_size = FONT_START

    while font_size >= 24:
        font = _pick_font(font_size)
        img = Image.new("RGB", (W_IMG, H_IMG), WALLPAPER_BG)
        draw = ImageDraw.Draw(img)

        wrapped: List[str] = []
        for r in rows:
            wrapped.extend(_wrap_to_width(draw, r, font, inner_w))

        block_h = 0
        heights: List[int] = []
        for ln in wrapped:
            try:
                bb = draw.textbbox((0, 0), ln, font=font)
                h = bb[3] - bb[1]
            except Exception:
                h = font_size + 4
            heights.append(max(h, font_size))
            block_h += h + LINE_GAP
        block_h -= LINE_GAP

        if block_h > H_IMG - 100:
            font_size -= 4
            continue

        cy = H_IMG // 2
        y = cy - block_h // 2
        for ln, hi in zip(wrapped, heights):
            try:
                bb = draw.textbbox((0, 0), ln, font=font)
                tw = bb[2] - bb[0]
            except Exception:
                tw = len(ln) * font_size // 2
            x = (W_IMG - tw) // 2
            draw.text((x, y), ln, fill=WALLPAPER_FG, font=font)
            y += hi + LINE_GAP

        img.save(dst_path, format="PNG", optimize=True)
        return

    raise OSError("无法在给定画布内排版文字")


def generate_test_wallpaper_and_push(sn: str, third_line: str) -> Tuple[str, List[str]]:
    """返回（状态摘要 成功|失败，输出行列表）。"""
    chk = _ensure_device_online(sn)
    if chk:
        return "失败", [chk]

    ok_o, ota = get_ota_version(sn.strip())
    if not ok_o:
        return "失败", [ota]

    ok_i, imei_or_err = parse_imei1_from_engineer(sn.strip())
    if not ok_i:
        pre = [f"OTA(getprop): {ota}", imei_or_err]
        return "失败", pre

    ok_pn, product_name = _get_prop_single_line(sn.strip(), "ro.product.name", "机型信息")
    if not ok_pn:
        return "失败", [f"OTA(getprop): {ota}", f"IMEI1: {imei_or_err}", product_name]

    ok_rm, region_mark = _get_prop_single_line(
        sn.strip(), "ro.oppo.regionmark", "标志位"
    )
    if not ok_rm:
        return (
            "失败",
            [
                f"OTA(getprop): {ota}",
                f"IMEI1: {imei_or_err}",
                f"机型信息(ro.product.name): {product_name}",
                region_mark,
            ],
        )

    lines_out: List[str] = [
        f"OTA(getprop): {ota}",
        f"IMEI1: {imei_or_err}",
        f"机型信息(ro.product.name): {product_name}",
        f"标志位(ro.oppo.regionmark): {region_mark}",
    ]

    t3 = (third_line or "").strip()
    if t3:
        lines_out.append(f"附加: {t3}")

    rows_for_image = [ota, imei_or_err, product_name, region_mark]
    if t3:
        rows_for_image.append(t3)

    local_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            local_path = tf.name
        _layout_and_draw_png(local_path, rows_for_image)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        remote_name = f"test_wallpaper_{ts}.png"
        remote = f"/sdcard/DCIM/{remote_name}"
        pcmd = subprocess.run(
            ["adb", "-s", sn.strip(), "push", local_path, remote],
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        push_lines = list(lines_out)
        push_lines.append(f"$ adb push … → {remote}")
        if pcmd.stdout and pcmd.stdout.strip():
            push_lines.append(pcmd.stdout.strip())
        if pcmd.stderr and pcmd.stderr.strip():
            push_lines.append(pcmd.stderr.strip())
        if pcmd.returncode != 0:
            return "失败", push_lines
        push_lines.append(f"已上传到: {remote}")
        return "成功", push_lines
    finally:
        if local_path:
            try:
                if os.path.isfile(local_path):
                    os.unlink(local_path)
            except OSError:
                pass
