"""TrendRadar 独立版入口：把 TrendRadar 打包成单文件 exe 时使用。

职责：
  1. 确定运行时数据目录（exe 同级的 runtime/，或 %APPDATA%\\TrendRadar）
  2. 首次运行时从内置资源复制 config 模板
  3. 切换工作目录后调用 TrendRadar 原有主流程

设计原则：不改动 TrendRadar 业务代码，只处理"资源在哪、数据写哪"。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的 exe 中。"""
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """PyInstaller 解包目录（含内置资源）；源码运行时退回项目根。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def app_dir() -> Path:
    """exe 所在目录（用户可见的位置）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def runtime_dir() -> Path:
    """运行时数据目录：优先 exe 同级 runtime/，不可写时回落 %APPDATA%。"""
    candidate = app_dir() / "runtime"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        fallback = Path(os.environ.get("APPDATA", Path.home())) / "TrendRadar"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


# 首次运行需要落地的配置模板（相对 config 目录）
CONFIG_TEMPLATES = (
    "config.yaml",
    "timeline.yaml",
    "frequency_words.txt",
    "ai_interests.txt",
    "ai_analysis_prompt.txt",
    "ai_translation_prompt.txt",
)

CONFIG_SUBDIR_TEMPLATES = (
    ("ai_filter", ("prompt.txt", "extract_prompt.txt", "update_tags_prompt.txt")),
    ("custom/ai", (".gitkeep",)),
    ("custom/keyword", (".gitkeep",)),
)


def ensure_runtime(runtime: Path) -> list[str]:
    """确保 runtime 下的配置文件齐全，返回本次新建的文件列表。"""
    created: list[str] = []
    config_dir = runtime / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    source_config = bundle_dir() / "config"
    for name in CONFIG_TEMPLATES:
        target = config_dir / name
        if target.is_file():
            continue
        source = source_config / name
        if source.is_file():
            shutil.copy2(source, target)
            created.append(f"config/{name}")

    for subdir, names in CONFIG_SUBDIR_TEMPLATES:
        target_dir = config_dir / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = target_dir / name
            if target.is_file():
                continue
            source = source_config / subdir / name
            if source.is_file():
                shutil.copy2(source, target)
                created.append(f"config/{subdir}/{name}")

    # TrendRadar 依赖这两个目录存在
    for sub in ("output", "output/news", "output/rss", "output/html"):
        (runtime / sub).mkdir(parents=True, exist_ok=True)

    return created


def _force_utf8_stdio() -> None:
    """强制标准输出/错误为 UTF-8。

    Windows 控制台默认 GBK，而 TrendRadar 会输出 emoji（如 ❌），
    不处理会抛 UnicodeEncodeError 直接崩溃。
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _hide_console() -> None:
    """GUI 模式下隐藏控制台窗口。

    单文件 exe 若用 windowed 模式打包，子进程拿不到 stdout（管理器就读不到日志）；
    因此仍以 console 模式打包，启动 GUI 时再把控制台窗口隐藏掉。
    """
    if not is_frozen():
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def main() -> int:
    _force_utf8_stdio()

    # 打包后由管理器自调用时，走纯命令行 TrendRadar 流程（不弹 GUI）
    if "--internal-run-trendradar" in sys.argv:
        sys.argv = [arg for arg in sys.argv if arg != "--internal-run-trendradar"]
        runtime = runtime_dir()
        ensure_runtime(runtime)
        os.chdir(runtime)
        from trendradar.__main__ import main as trendradar_main

        trendradar_main()
        return 0

    runtime = runtime_dir()
    created = ensure_runtime(runtime)
    if is_frozen() and created:
        print(f"[独立版] 首次运行，已初始化 {len(created)} 个配置文件 → {runtime}")

    _hide_console()

    # 其余情况启动图形管理器
    from trendradar_manager import TrendRadarManager

    app = TrendRadarManager()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
