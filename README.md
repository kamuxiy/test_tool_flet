<div align="center">

# 测试工具箱 | test_tool_flet

[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flet](https://img.shields.io/badge/GUI-Flet%200.85.3-0a66c2?style=flat-square)](https://flet.dev/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078d7?style=flat-square&logo=windows&logoColor=white)](#)
[![Release](https://img.shields.io/github/v/release/kamuxiy/test_tool_flet?style=flat-square&label=Release)](https://github.com/kamuxiy/test_tool_flet/releases)

---

面向 Android 手机系统测试的 **Windows 桌面工具箱**。

设备连接、日志导出、安装推送、流畅性（Perfetto）分析、卡顿检测、投屏录屏、截图导出等集于一处；绿色目录版分发，解压即可运行。

</div>

---

## 功能概览

| 功能 | 说明 |
| :--- | :--- |
| 多设备 SN 选择 | 刷新已连接设备，顶部统一选择测试机 |
| LOG 导出 | 拉取 / 打包设备日志到可配置目录 |
| Install / Push | 安装 APK、推送文件，支持实时进度 |
| Pull | 从设备拉取文件，支持实时进度 |
| 流畅性分析 | Perfetto 抓取与解析（内置 `perfetto_worker`） |
| 卡顿检测 | 丢帧 / 卡顿相关检测开关与辅助 |
| 测试壁纸 | 写入测试机壁纸信息 |
| 埋点 / 充电 | 埋点与充电相关工具页 |
| 查看截图 | 浏览 `Pictures/Screenshots` 缩略图，多选导出 |
| 投屏工具 | 内置 scrcpy；窗口高度固定，宽度随设备分辨率自适应 |
| 目录设置 | LOG / Perfetto / 录像 / 截图导出路径可改，本地持久化 |
| 绿色版打包 | Flet pack + PyInstaller onedir，免安装 Python |

---

## 快速开始

### 方式一：下载 Release（推荐）

1. 前往 [Releases](https://github.com/kamuxiy/test_tool_flet/releases) 下载最新 `test_tool_flet-v*-windows.zip`
2. 解压后双击 `test_tool_flet.exe` 启动
3. 用 USB 连接测试机并开启调试，在程序内刷新 / 选择 SN

> 首次如被 SmartScreen 拦截，选择「仍要运行」（开源自建包常见提示）。

### 方式二：源码运行

```bash
git clone https://github.com/kamuxiy/test_tool_flet.git
cd test_tool_flet

pip install -r requirements.txt
python main.py
```

Windows 上也可使用 `py main.py`。

### 方式三：本地打包 Windows 目录版

在 Windows 上：

```bat
打包为exe.bat
```

或：

```powershell
.\scripts\package.ps1
```

产物输出到 `dist\test_tool_flet\`（整夹分发即可）：

| 路径 | 说明 |
| :--- | :--- |
| `test_tool_flet.exe` | 主程序 |
| `perfetto_worker\` | 流畅性解析子进程（勿单独删） |
| `scrcpy-win64-v2.7\` | 内置投屏 |

也可在仓库 Actions 中手动触发 **Build Windows Client**，或推送 `v*` 标签自动构建并发布 Release。

---

## 环境依赖

| 项目 | 要求 | 说明 |
| :--- | :--- | :--- |
| 操作系统 | Windows 10 / 11（64 位） | 正式客户端目标平台 |
| 运行方式 | 下载 Release 解压 | 已内置运行时，无需预装 Python |
| Python | 3.10+（推荐 3.12） | **仅**源码运行或自行打包时需要 |
| USB 调试 | 设备已开启 | 本仓库自带 `adb`（随 scrcpy 目录） |

### 主要依赖（源码）

| 库 | 作用 |
| :--- | :--- |
| [Flet](https://flet.dev/) `0.85.3` | 桌面 GUI（已锁定版本） |
| [Pillow](https://python-pillow.org/) | 截图缩略图等 |
| [psutil](https://pypi.org/project/psutil/) | 进程辅助 |
| [pyperclip](https://pypi.org/project/pyperclip/) | 剪贴板 |
| [PyGetWindow](https://pypi.org/project/PyGetWindow/) | 投屏窗口几何 |
| [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | 部分辅助 UI |
| PyInstaller / flet-cli | **仅**打包时需要 |

---

## 项目结构

```
test_tool_flet/
├── main.py                      # 主程序入口
├── launcher.py                  # 启动器源码
├── perfetto_worker.py           # 流畅性解析子进程入口
├── requirements.txt             # 依赖（含 flet==0.85.3）
├── 打包为exe.bat                 # 调用 scripts/package.ps1
├── scripts/
│   ├── bump_version.py          # 升版本（patch / minor / major）
│   └── package.ps1              # Windows 目录版打包
├── .github/workflows/
│   └── build-windows.yml        # 自动打包 Windows 并发布 Release
├── core/
│   ├── adb.py                   # ADB 封装与进度
│   ├── config.py                # 版本号等配置（唯一版本源）
│   ├── user_prefs.py            # 输出目录默认值与本地持久化
│   ├── paths.py / logger.py
│   ├── monkey_run.py
│   └── test_wallpaper.py
├── subtools/                    # 功能页
│   ├── perfetto_view.py
│   ├── scrcpy_view.py
│   ├── screenshots_view.py
│   ├── settings_view.py
│   └── ...
├── ui/styles.py                 # 主题色板
├── assets/                      # 多语言等资源
├── scrcpy-win64-v2.7/           # 内置投屏
└── perf_all_in_one/             # Perfetto / systrace 工具链
```

> 新增功能并推送到 GitHub 时，请同步更新本 README（功能表、结构与使用说明）。  
> **每次更新 GitHub 仓库文件前**，先执行 `python scripts/bump_version.py`（或 `minor` / `major`）升版本；`core/config.py` 的 `__version__` 是唯一版本源，界面页脚与 Release 标签共用。

---

## 使用说明

### 输出目录

在侧栏 **设置 → 目录设置** 中修改；未改时使用下列默认值（见 `core/user_prefs.py`）：

| 功能 | 默认路径 |
| :--- | :--- |
| LOG 导出 | `E:\log` |
| 流畅性分析 (Perfetto) | `D:\Users\Desktop\perfetto_output` |
| 投屏录像 | `<程序目录>\scrcpy_records` |
| 截图导出 | `D:\Users\Desktop\screenshots_export` |

用户设置保存在 `%LOCALAPPDATA%\TestToolFlet\user_settings.json`。

### 调试

设置环境变量 `TEST_TOOL_FLET_DEBUG=1` 后，ADB 定时刷新异常会打印到控制台（源码运行或带控制台的 exe）。

### 发版

| 方式 | 说明 |
| :--- | :--- |
| Actions 手动 | Actions → **Build Windows Client** → 选择 bump（默认 patch）→ 运行；完成后发布 Release |
| 推送标签 | 本地升版本并提交后：`git tag vX.Y.Z && git push origin vX.Y.Z` |

产物：`test_tool_flet-vX.Y.Z-windows.zip`。

---

## 反馈

- Bug / 建议：[Issues](https://github.com/kamuxiy/test_tool_flet/issues)
- 更新说明：[Releases](https://github.com/kamuxiy/test_tool_flet/releases)

---

<div align="center">

Made by kamuXiY

</div>
