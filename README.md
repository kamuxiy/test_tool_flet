# 测试工具箱 (test_tool_dev)

手机系统测试辅助工具箱 — Flet 桌面版。

## 目录结构

```
test_tool_dev/
+-- main.py                    # 主程序入口
+-- launcher.py                # 快捷启动器源码
+-- test_tool_flet.exe         # 快捷启动 exe（双击启动）
+-- requirements.txt           # 依赖清单
+-- launch.spec                # 启动器打包配置
+-- 启动Flet.bat                # 批处理启动（备用）
+-- 打包为exe.bat               # 完整打包脚本
+-- core/
|   +-- adb.py                 # ADB 命令封装
|   +-- config.py              # 配置（LOG 路径、版本号）
|   +-- paths.py               # 统一路径解析
|   +-- logger.py              # 日志模块
|   +-- monkey_run.py          # Monkey 测试引擎
|   +-- test_wallpaper.py      # 测试壁纸生成
+-- subtools/
|   +-- monkey_view.py         # Monkey 面板
|   +-- language_view.py       # 多语言工具面板
|   +-- log_check_view.py      # Log 检查面板
|   +-- settings_view.py       # 设置面板
+-- ui/
|   +-- styles.py              # 主题色板与 UI 辅助
+-- assets/
|   +-- languages.py           # 多语言数据
+-- scrcpy-win64-v2.7/         # 投屏工具（可选）
+-- .cursor/rules/global/       # AI 辅助领域规则
```

## 运行

```bat
# 方式 1：双击 test_tool_flet.exe

# 方式 2：命令行
cd test_tool_dev
py main.py

# 方式 3：批处理
启动Flet.bat
```

## 首次安装依赖

```bat
py -m pip install -r requirements.txt
```

## 打包为独立 exe

```bat
打包为exe.bat
```

完成后只分发 **一个文件夹**：`dist\test_tool_flet\`（内含主程序与流畅性分析所需的 `perfetto_worker` 子目录）。不再单独产出 `dist\perfetto_worker\`。

## 配置

| 配置项 | 位置 | 说明 |
|--------|------|------|
| LOG / Perfetto / 录像目录 | 设置页「目录设置」 | 默认见 `core/user_prefs.py`，持久化到 `%LOCALAPPDATA%\TestToolFlet\user_settings.json` |
| LOG 历史默认 | `core/config.py` | `E:\log` |
| 版本号 | `core/config.py` | `__version__` |

## 版本历史

- **0.4.0** — 目录设置可持久化；日志跟随最新行；流畅性解析与投屏录像等修复
- **0.3.0** — 移除 Tk 版，扁平化目录结构，统一路径解析，增加日志
- **0.2.0** — Flet 重写版
- **0.1.x** — Tk 原版（已移除）