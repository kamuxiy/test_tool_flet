# 测试工具箱（test_tool_flet）

面向 Android 手机系统测试的 **Windows 桌面工具箱**，基于 [Flet](https://flet.dev) `0.85.3`。

仓库：[kamuxiy/test_tool_flet](https://github.com/kamuxiy/test_tool_flet)  
当前版本以 `core/config.py` 中的 `__version__` 为准；正式安装包见 [Releases](https://github.com/kamuxiy/test_tool_flet/releases)。

## 功能

| 入口 | 说明 |
|------|------|
| **主页 · LOG 导出** | 拉取 / 打包设备日志 |
| **主页 · Install/Push** | 安装 APK、推送文件（实时进度） |
| **主页 · Pull** | 从设备拉取文件（实时进度） |
| **主页 · 流畅性分析** | Perfetto 抓取与解析（内置 `perfetto_worker`） |
| **主页 · 卡顿检测** | 丢帧 / 卡顿相关检测开关与辅助 |
| **主页 · 测试壁纸** | 写入测试机壁纸信息 |
| **主页 · 埋点 / 充电** | 埋点与充电相关工具 |
| **侧栏 · 查看截图** | 浏览 `Pictures/Screenshots` 缩略图并导出 |
| **侧栏 · 投屏** | 内置 scrcpy，窗口宽度按设备分辨率自适应 |
| **侧栏 · 设置** | 主题与**输出目录**（LOG / Perfetto / 录像 / 截图导出） |

输出目录默认值与界面标题定义在 `core/user_prefs.py`，用户修改后保存在 `%LOCALAPPDATA%\TestToolFlet\user_settings.json`。

## 环境要求

- Windows 10/11
- Python **3.10+**（推荐 3.12；依赖已锁定 `flet==0.85.3`）
- 设备侧已开启 USB 调试；本仓库自带 `scrcpy-win64-v2.7/` 与 `adb`

## 本地运行

```bat
git clone https://github.com/kamuxiy/test_tool_flet.git
cd test_tool_flet
py -m pip install -r requirements.txt
py main.py
```

## 本地打包

与 CI 使用同一套逻辑：

```bat
打包为exe.bat
```

或：

```powershell
.\scripts\package.ps1
```

产物只有一个文件夹：`dist\test_tool_flet\`（含 `test_tool_flet.exe` 与 `perfetto_worker\`）。分发时整夹拷贝即可。

## 自动发版

每次合并到 `main` 时，GitHub Actions（`.github/workflows/release.yml`）会：

1. **递增版本号**（默认 patch：`0.4.0` → `0.4.1`），写回 `core/config.py` 并提交（提交信息带 `[skip ci]`，避免循环）
2. 在 `windows-latest` 上执行 `scripts/package.ps1` 打包
3. 打 tag（如 `v0.4.1`）并创建 [GitHub Release](https://github.com/kamuxiy/test_tool_flet/releases)，附件为 `test_tool_flet-vX.Y.Z-windows.zip`

也可在 Actions 页手动触发 **Release**，并选择递增 `patch` / `minor` / `major`。

本地预览下一版本号：

```bat
py scripts\bump_version.py --dry-run
py scripts\bump_version.py minor --dry-run
```

## 目录结构

```
test_tool_flet/
├── main.py                 # 主程序
├── launcher.py             # 启动器源码
├── perfetto_worker.py      # 流畅性解析子进程入口
├── requirements.txt        # 依赖（含 flet==0.85.3）
├── 打包为exe.bat            # 调用 scripts/package.ps1
├── scripts/
│   ├── bump_version.py     # 版本递增
│   └── package.ps1         # Windows 打包
├── .github/workflows/
│   └── release.yml         # 自动 bump + 构建 Release
├── core/                   # ADB、配置、用户偏好、Monkey 等
├── subtools/               # 各功能页（投屏、截图、设置、Perfetto…）
├── ui/                     # 主题与样式
├── assets/                 # 多语言等资源
├── scrcpy-win64-v2.7/      # 内置投屏
└── perf_all_in_one/        # Perfetto / systrace 工具链
```

## 配置一览

| 项 | 位置 |
|----|------|
| 应用版本 `__version__` | `core/config.py` |
| 输出目录默认值 | `core/user_prefs.py` |
| 用户持久化设置 | `%LOCALAPPDATA%\TestToolFlet\user_settings.json` |

## 开发说明

- **以 GitHub / 云端为准**，功能改动请提 PR 到 `main`；合并后由 CI 发版。
- 本工具依赖 Windows API、scrcpy 与 exe 打包，云端适合改代码与语法检查；真机调试与本地验证仍在 Windows 上进行。
- 调试时可设环境变量 `TEST_TOOL_FLET_DEBUG=1`，让 ADB 定时刷新异常打印到控制台。
