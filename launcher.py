"""
test_tool_flet 快捷启动器
双击此 exe 即可启动 Flet 版测试工具箱，无需手动开终端。
"""

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path


def msgbox(title: str, text: str) -> None:
    """在 windowed exe 中弹出消息框（无控制台时替代 input）。"""
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x30)


def _get_python_exe() -> str:
    """获取系统 Python 解释器路径。
    
    开发模式返回当前运行的 Python；
    PyInstaller 打包模式（frozen）下 sys.executable 是 exe 自身，
    需要从 PATH 查找真实 Python。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    # frozen: 搜索系统 Python
    for name in ("python", "python3", "py"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    
    # 最后尝试 base_prefix（PyInstaller 环境中可能可用）
    base = sys.base_prefix if hasattr(sys, "base_prefix") else ""
    if base:
        candidate = os.path.join(base, "python.exe")
        if os.path.isfile(candidate):
            return candidate

    return "python"  # fallback，让 subprocess 报清晰的 FileNotFoundError


def find_main_py() -> Path | None:
    """查找 main.py，优先同目录，其次子目录 test_tool_flet/。"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parent

    for p in [exe_dir / "main.py", exe_dir / "test_tool_flet" / "main.py"]:
        if p.is_file():
            return p
    return None


def main():
    main_py = find_main_py()
    if main_py is None:
        msgbox(
            "test_tool_flet - 错误",
            "找不到 main.py\n\n"
            "请将 test_tool_flet.exe 放在 test_tool_flet 目录内。",
        )
        sys.exit(1)

    python_exe = _get_python_exe()
    try:
        subprocess.run(
            [python_exe, str(main_py)],
            cwd=str(main_py.parent),
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        msgbox(
            "test_tool_flet - 错误",
            "找不到 Python 解释器\n\n请安装 Python 3.10+",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()