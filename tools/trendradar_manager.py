"""Small Windows GUI for managing a local TrendRadar installation."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from trendradar_manager_config import (
    AI_PROVIDERS,
    INTEREST_PRESETS,
    NEWSNOW_DEFAULT_API_URL,
    WEBHOOK_CHANNELS,
    detect_env_key_conflict,
    get_form_values,
    inject_dingtalk_keyword,
    load_ai_features,
    load_ai_interests,
    load_config,
    load_source_api_url,
    load_cloudflare_pages,
    load_dingtalk_security,
    load_webhook_channels,
    provider_models,
    read_collection_interval,
    redact_secrets,
    save_ai_features,
    save_ai_interests,
    save_collection_interval,
    save_config,
    save_cloudflare_pages,
    save_dingtalk_security,
    save_source_api_url,
    save_webhook_channels,
    sign_dingtalk_url,
)


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的 exe 中。"""
    return getattr(sys, "frozen", False)


def runtime_root() -> Path:
    """运行时数据根目录。

    - 源码模式：项目根（保持原有行为）
    - 打包模式：exe 同级 runtime/，不可写时回落 %APPDATA%\\TrendRadar
    """
    if not is_frozen():
        return Path(__file__).resolve().parents[1]
    base = Path(sys.executable).resolve().parent / "runtime"
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return base
    except OSError:
        fallback = Path(os.environ.get("APPDATA", Path.home())) / "TrendRadar"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def find_project_root() -> Path:
    """返回配置文件与输出目录所在位置。"""
    return runtime_root()


def settings_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "TrendRadar" / "manager.json"


class TrendRadarManager(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        try:
            self.project_root = find_project_root()
        except FileNotFoundError as error:
            self.withdraw()
            messagebox.showerror("TrendRadar 管理器", str(error))
            self.destroy()
            raise

        self.config_path = self.project_root / "config" / "config.yaml"
        self.keywords_path = self.project_root / "config" / "frequency_words.txt"
        self.interests_path = self.project_root / "config" / "ai_interests.txt"
        # 打包模式：用 exe 自身作为子进程入口；源码模式：用项目 .venv312
        if is_frozen():
            self.python_path = Path(sys.executable).resolve()
        else:
            self.python_path = self.project_root / ".venv312" / "Scripts" / "python.exe"
        self.settings_file = settings_path()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.process_lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None
        self.worker_active = False
        self.clear_environment_key = False
        self.cloud_status_ref = None

        self.title("TrendRadar 管理器")
        # 自适应屏幕高度：屏幕矮时窗口不超出，靠滚动查看下方内容
        screen_h = self.winfo_screenheight()
        target_h = min(1000, max(600, screen_h - 80))
        self.geometry(f"900x{target_h}")
        self.minsize(720, 520)
        self._build_ui()
        self._load_form()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._drain_events)

    def _build_ui(self) -> None:
        # 内容较长，放进可滚动容器，避免小屏幕上底部区域（费用/日志）被挤出窗口
        scroll_host = ttk.Frame(self)
        scroll_host.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(scroll_host, highlightthickness=0, borderwidth=0)
        vbar = ttk.Scrollbar(scroll_host, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        outer = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=outer, anchor=tk.NW)
        self._scroll_canvas = canvas

        def _on_configure(_event: object = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_resize(event: object) -> None:
            # 让内部内容始终与画布同宽，保证横向不出现滚动
            canvas.itemconfigure(window_id, width=event.width)  # type: ignore[attr-defined]

        outer.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event: object) -> None:
            delta = getattr(event, "delta", 0)
            canvas.yview_scroll(int(-delta / 120), "units")

        # Windows 鼠标滚轮：进入画布区域时绑定
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        ttk.Label(
            outer,
            text="TrendRadar 管理器",
            font=("", 13, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="三步配好：选关注方向 → 填 AI Key → 选推送渠道。填完点「保存并启动」。",
            foreground="#555555",
        ).pack(anchor=tk.W, pady=(0, 8))

        self.provider = tk.StringVar(value="DeepSeek")
        self.base_url = tk.StringVar()
        self.api_key = tk.StringVar()
        self.model = tk.StringVar()
        self.channel = tk.StringVar(value="Feishu")
        self.channel_value = tk.StringVar()
        self.interval = tk.StringVar(value="60")
        self.clear_key = tk.BooleanVar(value=False)
        self.key_status = tk.StringVar(value="")
        self.source_url = tk.StringVar(value="")
        self.test_status = tk.StringVar(value="")
        self._interests_touched = False
        self.preset_vars: dict[str, tk.BooleanVar] = {
            name: tk.BooleanVar(value=False) for name, _desc, _words in INTEREST_PRESETS
        }

        # ① 关注方向
        step1 = ttk.LabelFrame(outer, text="① 我关心什么", padding=10)
        step1.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(
            step1,
            text="勾选你关心的方向（可多选），下面会自动填入对应兴趣；也可以自己改写。",
            foreground="#555555",
        ).pack(anchor=tk.W, pady=(0, 6))
        preset_frame = ttk.Frame(step1)
        preset_frame.pack(fill=tk.X)
        for index, (name, desc, _words) in enumerate(INTEREST_PRESETS):
            cell = ttk.Frame(preset_frame)
            cell.grid(row=index // 3, column=index % 3, sticky=tk.W, padx=(0, 18), pady=2)
            ttk.Checkbutton(
                cell,
                text=name,
                variable=self.preset_vars[name],
                command=lambda n=name: self._apply_preset(n),
            ).pack(anchor=tk.W)
            ttk.Label(cell, text=desc, foreground="#888888", font=("", 8)).pack(anchor=tk.W)

        ttk.Label(step1, text="具体关注（每行一条，自然语言描述）").pack(anchor=tk.W, pady=(8, 2))
        self.interests_text = ScrolledText(step1, height=7, wrap=tk.WORD)
        self.interests_text.pack(fill=tk.X)

        # ② AI
        step2 = ttk.LabelFrame(outer, text="② AI 服务（用于自动筛选与解读新闻）", padding=10)
        step2.pack(fill=tk.X, pady=(0, 8))
        step2.columnconfigure(1, weight=1)

        ttk.Label(step2, text="服务商").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        provider_box = ttk.Combobox(
            step2, textvariable=self.provider, values=list(AI_PROVIDERS), state="readonly"
        )
        provider_box.grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=3)
        provider_box.bind("<<ComboboxSelected>>", self._provider_changed)

        ttk.Label(step2, text="API Key").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        ttk.Entry(step2, textvariable=self.api_key, show="•").grid(
            row=1, column=1, sticky=tk.EW, pady=3
        )
        ttk.Label(step2, textvariable=self.key_status).grid(row=1, column=2, sticky=tk.W, padx=8)

        ttk.Label(step2, text="模型").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        self.model_box = ttk.Combobox(step2, textvariable=self.model, state="readonly")
        self.model_box.grid(row=2, column=1, columnspan=2, sticky=tk.EW, pady=3)

        # 高级项默认收起，避免干扰新手
        self.advanced_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            step2,
            text="显示高级设置（Base URL / 数据源 / 采集周期 / 清除 Key）",
            variable=self.advanced_visible,
            command=self._toggle_advanced,
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))

        self.advanced_frame = ttk.Frame(step2)
        self.advanced_frame.grid(row=4, column=0, columnspan=3, sticky=tk.EW)
        self.advanced_frame.columnconfigure(1, weight=1)

        ttk.Label(self.advanced_frame, text="Base URL").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        self.base_url_entry = ttk.Entry(
            self.advanced_frame, textvariable=self.base_url, state="readonly"
        )
        self.base_url_entry.grid(row=0, column=1, sticky=tk.EW, pady=3)

        ttk.Label(self.advanced_frame, text="数据源").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        ttk.Entry(self.advanced_frame, textvariable=self.source_url).grid(
            row=1, column=1, sticky=tk.EW, pady=3
        )
        ttk.Label(
            self.advanced_frame,
            text=f"留空使用默认：{NEWSNOW_DEFAULT_API_URL}",
            foreground="#888888",
            font=("", 8),
        ).grid(row=2, column=1, sticky=tk.W)

        ttk.Label(self.advanced_frame, text="采集周期").grid(row=3, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        interval_cell = ttk.Frame(self.advanced_frame)
        interval_cell.grid(row=3, column=1, sticky=tk.W, pady=3)
        ttk.Spinbox(interval_cell, from_=1, to=1440, textvariable=self.interval, width=6).pack(side=tk.LEFT)
        ttk.Label(interval_cell, text=" 分钟（每轮跑完后再等这么久）", foreground="#888888").pack(side=tk.LEFT)

        ttk.Checkbutton(
            self.advanced_frame, text="清除已保存的 Key", variable=self.clear_key
        ).grid(row=4, column=1, sticky=tk.W, pady=3)
        self.advanced_frame.grid_remove()

        # ③ 推送
        step3 = ttk.LabelFrame(outer, text="③ 推送渠道（可选，都留空则只生成网页）", padding=10)
        step3.pack(fill=tk.X, pady=(0, 8))
        step3.columnconfigure(1, weight=1)
        self.webhook_vars: dict[str, tk.StringVar] = {}
        self.webhook_test_buttons: dict[str, ttk.Button] = {}
        for row_index, (label, (_section, _key, hint)) in enumerate(WEBHOOK_CHANNELS.items()):
            ttk.Label(step3, text=label).grid(
                row=row_index * 2, column=0, sticky=tk.W, padx=(0, 8), pady=3
            )
            value = tk.StringVar(value="")
            self.webhook_vars[label] = value
            ttk.Entry(step3, textvariable=value, show="•").grid(
                row=row_index * 2, column=1, sticky=tk.EW, pady=3
            )
            button = ttk.Button(
                step3,
                text=f"测试{label}",
                command=lambda name=label: self._test_webhook(name),
            )
            button.grid(row=row_index * 2, column=2, padx=(8, 0))
            self.webhook_test_buttons[label] = button
            ttk.Label(
                step3,
                text=hint,
                foreground="#777777",
                font=("", 8),
                wraplength=820,
                justify=tk.LEFT,
            ).grid(row=row_index * 2 + 1, column=1, columnspan=2, sticky=tk.W)

        # 钉钉专有：加签密钥与自定义关键词（安全设置要求时必须填）
        dingtalk_row = len(WEBHOOK_CHANNELS) * 2
        ttk.Separator(step3, orient=tk.HORIZONTAL).grid(
            row=dingtalk_row, column=0, columnspan=3, sticky=tk.EW, pady=6
        )
        self.dingtalk_secret = tk.StringVar(value="")
        self.dingtalk_keyword = tk.StringVar(value="")
        ttk.Label(step3, text="钉钉加签密钥").grid(
            row=dingtalk_row + 1, column=0, sticky=tk.W, padx=(0, 8), pady=3
        )
        ttk.Entry(step3, textvariable=self.dingtalk_secret, show="•").grid(
            row=dingtalk_row + 1, column=1, columnspan=2, sticky=tk.EW, pady=3
        )
        ttk.Label(
            step3,
            text="钉钉机器人安全设置里选了「加签」时填，SEC 开头；没选就留空",
            foreground="#777777",
            font=("", 8),
        ).grid(row=dingtalk_row + 2, column=1, columnspan=2, sticky=tk.W)
        ttk.Label(step3, text="钉钉关键词").grid(
            row=dingtalk_row + 3, column=0, sticky=tk.W, padx=(0, 8), pady=3
        )
        ttk.Entry(step3, textvariable=self.dingtalk_keyword).grid(
            row=dingtalk_row + 3, column=1, columnspan=2, sticky=tk.EW, pady=3
        )
        ttk.Label(
            step3,
            text="钉钉机器人安全设置里「自定义关键词」填了什么，这里就填同一个词；每条消息会自动带上它",
            foreground="#777777",
            font=("", 8),
        ).grid(row=dingtalk_row + 4, column=1, columnspan=2, sticky=tk.W)

        # 操作区
        buttons = ttk.Frame(outer)
        buttons.pack(fill=tk.X, pady=(0, 8))
        self.test_button = ttk.Button(buttons, text="测试 AI 连接", command=self._test_ai)
        self.test_button.pack(side=tk.LEFT)
        self.save_button = ttk.Button(buttons, text="保存配置", command=self._save_form)
        self.save_button.pack(side=tk.LEFT, padx=(8, 0))
        self.start_button = ttk.Button(buttons, text="保存并启动", command=self._start)
        self.start_button.pack(side=tk.LEFT, padx=(8, 0))
        self.stop_button = ttk.Button(buttons, text="停止", command=self._stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        self.status = tk.StringVar(value="已停止")
        ttk.Label(buttons, textvariable=self.status).pack(side=tk.RIGHT)

        # 查看报告：电脑用浏览器打开，手机走云端发布
        view = ttk.LabelFrame(outer, text="④ 查看完整报告（手机任何网络都能看）", padding=8)
        view.pack(fill=tk.X, pady=(0, 8))
        row = ttk.Frame(view)
        row.pack(fill=tk.X)
        ttk.Button(row, text="在电脑上查看", command=self._open_report).pack(side=tk.LEFT)
        self.cloud_button = ttk.Button(
            row, text="发布到手机（Cloudflare）", command=self._publish_cloud
        )
        self.cloud_button.pack(side=tk.LEFT, padx=(8, 0))
        self.cloud_status = tk.StringVar(value="")
        ttk.Label(view, textvariable=self.cloud_status, foreground="#2c7a2c", wraplength=820).pack(
            anchor=tk.W, pady=(6, 0)
        )

        cloud_form = ttk.Frame(view)
        cloud_form.pack(fill=tk.X, pady=(6, 0))
        cloud_form.columnconfigure(1, weight=1)
        self.cf_account = tk.StringVar(value="")
        self.cf_token = tk.StringVar(value="")
        self.cf_project = tk.StringVar(value="trendradar")
        ttk.Label(cloud_form, text="Account ID").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=2)
        ttk.Entry(cloud_form, textvariable=self.cf_account).grid(row=0, column=1, sticky=tk.EW, pady=2)
        ttk.Label(cloud_form, text="API Token").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=2)
        ttk.Entry(cloud_form, textvariable=self.cf_token, show="•").grid(row=1, column=1, sticky=tk.EW, pady=2)
        ttk.Label(cloud_form, text="项目名").grid(row=2, column=0, sticky=tk.W, padx=(0, 8), pady=2)
        ttk.Entry(cloud_form, textvariable=self.cf_project).grid(row=2, column=1, sticky=tk.EW, pady=2)
        ttk.Label(
            view,
            text="在 dash.cloudflare.com 创建 Pages 项目（Direct Upload）后，填入上表三项即可发布；发布后得到 public 网址，手机随时可看。",
            foreground="#888888",
            font=("", 8),
            wraplength=820,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

        ttk.Label(outer, textvariable=self.test_status, foreground="#c0392b").pack(anchor=tk.W)

        # 费用控制：显示余额、估算消耗、一键切换采集周期
        cost = ttk.LabelFrame(outer, text="费用控制（AI 按 token 计费）", padding=8)
        cost.pack(fill=tk.X, pady=(6, 8))
        cost_row = ttk.Frame(cost)
        cost_row.pack(fill=tk.X)
        ttk.Button(cost_row, text="查询余额", command=self._query_balance).pack(side=tk.LEFT)
        self.single_run = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            cost_row,
            text="只运行一次（跑完自动停止，不循环）",
            variable=self.single_run,
        ).pack(side=tk.LEFT, padx=(10, 0))
        cost_row2 = ttk.Frame(cost)
        cost_row2.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(cost_row2, text="循环周期（取消勾选上面才生效）：").pack(side=tk.LEFT)
        for text_label, minutes in (
            ("30分", 30),
            ("1小时", 60),
            ("3小时", 180),
            ("6小时", 360),
            ("12小时", 720),
        ):
            ttk.Button(
                cost_row2,
                text=text_label,
                width=6,
                command=lambda m=minutes: self._set_interval(m),
            ).pack(side=tk.LEFT, padx=1)
        self.cost_status = tk.StringVar(value="点击「查询余额」查看 AI 花费")
        ttk.Label(cost, textvariable=self.cost_status, foreground="#1f5fa8", wraplength=820).pack(
            anchor=tk.W, pady=(6, 0)
        )
        self.cost_detail = tk.StringVar(value="")
        ttk.Label(cost, textvariable=self.cost_detail, foreground="#666666", font=("", 8)).pack(
            anchor=tk.W
        )

        logs = ttk.LabelFrame(outer, text="运行日志", padding=6)
        logs.pack(fill=tk.BOTH, expand=True)
        self.log_view = ScrolledText(logs, state=tk.DISABLED, wrap=tk.WORD, height=10)
        self.log_view.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            outer,
            text="API Key 以明文保存在 config.yaml；本工具不会把 Key 写进日志。",
            foreground="#888888",
            font=("", 8),
        ).pack(anchor=tk.W, pady=(6, 0))

    def _toggle_advanced(self) -> None:
        if self.advanced_visible.get():
            self.advanced_frame.grid()
        else:
            self.advanced_frame.grid_remove()

    def _apply_preset(self, name: str) -> None:
        """勾选/取消关注方向模板：勾选时把该方向条目加入兴趣框，取消时移除。"""
        preset = next((p for p in INTEREST_PRESETS if p[0] == name), None)
        if preset is None:
            return
        _name, _desc, words = preset
        current = [
            line.strip()
            for line in self.interests_text.get("1.0", tk.END).splitlines()
            if line.strip()
        ]
        if self.preset_vars[name].get():
            # 首次勾选模板时，若内容仍是上游示例（含"1. "这类编号），先清空避免混杂
            if not self._interests_touched and current:
                looks_like_upstream = any(
                    line[:3].rstrip(".").isdigit() for line in current
                )
                if looks_like_upstream:
                    current = []
            for word in words:
                if word not in current:
                    current.append(word)
            self._interests_touched = True
        else:
            current = [line for line in current if line not in words]
            self._interests_touched = True
        self.interests_text.delete("1.0", tk.END)
        self.interests_text.insert("1.0", "\n".join(current))

    def _load_form(self) -> None:
        try:
            config = load_config(self.config_path)
            provider, base_url, key, model, channel_value = get_form_values(config, self.channel.get())
            self.provider.set(provider)
            custom = provider == "自定义兼容接口"
            self.base_url.set(base_url)
            self.base_url_entry.configure(state="normal" if custom else "readonly")
            self.api_key.set(key)
            models = provider_models(provider)
            self.model_box.configure(
                values=models,
                state="normal" if custom else "readonly",
            )
            self.model.set(model)
            self.channel_value.set(channel_value)
            self.key_status.set("已配置" if key or os.environ.get("AI_API_KEY") else "未配置")
            conflict = detect_env_key_conflict(key)
            if conflict:
                self.test_status.set(conflict)
            features = load_ai_features(config)
            self._sync_presets_from_interests(load_ai_interests(self.interests_path))
            self.source_url.set(load_source_api_url(config))
            channel_values = load_webhook_channels(config)
            for label, var in self.webhook_vars.items():
                var.set(channel_values.get(label, ""))
            secret, keyword = load_dingtalk_security(config)
            self.dingtalk_secret.set(secret)
            self.dingtalk_keyword.set(keyword)
            cf_account, cf_token, cf_project = load_cloudflare_pages(config)
            self.cf_account.set(cf_account)
            self.cf_token.set(cf_token)
            self.cf_project.set(cf_project or "trendradar")
            self.interests_text.delete("1.0", tk.END)
            self.interests_text.insert("1.0", load_ai_interests(self.interests_path))
            self._interests_touched = False
            self.interval.set(str(read_collection_interval(self.settings_file)))
        except Exception as error:
            self._show_safe_error("读取配置失败", error)

    def _sync_presets_from_interests(self, text: str) -> None:
        """根据现有兴趣内容，反推哪些模板应处于勾选状态。"""
        lines = {line.strip() for line in text.splitlines() if line.strip()}
        for name, _desc, words in INTEREST_PRESETS:
            self.preset_vars[name].set(all(word in lines for word in words))

    def _provider_changed(self, _event: object = None) -> None:
        provider = self.provider.get()
        if provider not in AI_PROVIDERS:
            return
        custom = provider == "自定义兼容接口"
        self.base_url.set("" if custom else AI_PROVIDERS[provider]["base_url"])
        self.base_url_entry.configure(state="normal" if custom else "readonly")
        models = provider_models(provider)
        self.model_box.configure(values=models, state="normal" if custom else "readonly")
        self.model.set(models[0] if models else "")
        self.api_key.set("")
        self.clear_key.set(True)
        self.key_status.set("请输入此平台的 Key")

    def _save_form(self) -> bool:
        try:
            interval = int(self.interval.get())
            if not 1 <= interval <= 1440:
                raise ValueError("周期必须在 1 到 1440 分钟之间")
            clearing_key = self.clear_key.get()
            save_config(
                self.config_path,
                self.provider.get(),
                self.base_url.get(),
                self.api_key.get(),
                self.model.get(),
                self.channel.get(),
                self.channel_value.get(),
                clear_api_key=self.clear_key.get(),
            )
            save_ai_interests(self.interests_path, self.interests_text.get("1.0", tk.END))
            # 普通用户界面只提供一个输入框：填了内容就用 AI 筛选，留空则按关键词全量推送。
            # AI 分析与翻译默认开启，让"AI 加工"开箱即用。
            has_interests = bool(self.interests_text.get("1.0", tk.END).strip())
            save_ai_features(
                self.config_path,
                {
                    "AI 分析（推送附洞察报告）": True,
                    "AI 智能筛选（自然语言兴趣，替代关键词）": has_interests,
                    "AI 翻译（推送标题译为目标语言）": False,
                },
            )
            save_source_api_url(self.config_path, self.source_url.get())
            save_webhook_channels(
                self.config_path,
                {label: var.get() for label, var in self.webhook_vars.items()},
            )
            save_dingtalk_security(
                self.config_path, self.dingtalk_secret.get(), self.dingtalk_keyword.get()
            )
            save_cloudflare_pages(
                self.config_path,
                self.cf_account.get(),
                self.cf_token.get(),
                self.cf_project.get(),
            )
            save_collection_interval(self.settings_file, interval)
            if clearing_key:
                self.clear_environment_key = True
            self.clear_key.set(False)
            self._load_form()
            self._append_log("配置已保存；运行中的进程将在下一轮使用新配置。")
            return True
        except Exception as error:
            self._show_safe_error("保存配置失败", error)
            return False

    def _test_webhook(self, label: str) -> None:
        """向指定渠道的群机器人发一条测试消息，验证地址是否可用。"""
        url = self.webhook_vars[label].get().strip()
        if not url:
            self.test_status.set(f"请先填写{label}的 Webhook 地址。")
            return
        if not url.startswith("http"):
            self.test_status.set(f"{label} 的地址应以 https:// 开头。")
            return
        self.test_status.set(f"正在向{label}发送测试消息…")
        self.webhook_test_buttons[label].configure(state=tk.DISABLED)
        text = f"**TrendRadar 测试消息**\n\n如果你在{label}里看到这条，说明推送配置成功了 🎉"
        # Tk 变量只能在主线程读取，必须先取出再进工作线程
        keyword = self.dingtalk_keyword.get().strip() if label == "钉钉" else ""
        secret = self.dingtalk_secret.get().strip() if label == "钉钉" else ""
        if label == "钉钉":
            text = inject_dingtalk_keyword(text, keyword)

        def worker() -> None:
            try:
                import json
                import urllib.error
                import urllib.request

                target = url
                if label == "钉钉":
                    target = sign_dingtalk_url(url, secret)
                    payload = {
                        "msgtype": "markdown",
                        "markdown": {"title": "TrendRadar 测试消息", "text": text},
                    }
                    success_code_key = "errcode"
                elif label == "飞书":
                    payload = {
                        "msg_type": "interactive",
                        "card": {
                            "schema": "2.0",
                            "body": {"elements": [{"tag": "markdown", "content": text}]},
                        },
                    }
                    success_code_key = "StatusCode"
                else:
                    payload = {"text": text}
                    success_code_key = None

                request = urllib.request.Request(
                    target,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = response.read().decode("utf-8", "replace")
                result = json.loads(body) if body.strip() else {}
                if success_code_key is None:
                    self.events.put(("test", f"{label} 请求已成功发出。"))
                    return
                code = result.get(success_code_key)
                if code == 0:
                    self.events.put(("test", f"{label} 发送成功！去群里看看。"))
                else:
                    message = result.get("errmsg") or result.get("msg") or ""
                    self.events.put(("test", f"{label} 拒绝了这条消息：{message}（code={code}）"))
            except urllib.error.HTTPError as error:
                detail = ""
                try:
                    detail = error.read(200).decode("utf-8", "replace")
                except Exception:
                    pass
                self.events.put(("test", f"{label} 发送失败 HTTP {error.code} {detail[:120]}".strip()))
            except Exception as error:
                self.events.put(("test", f"{label} 发送失败：{type(error).__name__}（检查地址或网络）"))
            finally:
                self.events.put(("test_btn", label))

        threading.Thread(target=worker, daemon=True).start()

    def _test_ai(self) -> None:
        """用当前表单里的 Key 直接向服务商发一次最小请求，验证 AI 接口是否连通。"""
        provider = self.provider.get()
        api_key = self.api_key.get().strip() or os.environ.get("AI_API_KEY", "").strip()
        model = self.model.get().strip()
        base_url = self.base_url.get().strip()
        if not api_key:
            self.test_status.set("请先填写 API Key。")
            return
        if not model:
            self.test_status.set("请先选择 AI 模型。")
            return
        if provider == "自定义兼容接口" and not base_url:
            self.test_status.set("自定义兼容接口需要填写 Base URL。")
            return
        self.test_status.set("正在测试…")
        self.test_button.configure(state=tk.DISABLED)

        def worker() -> None:
            try:
                import json
                import urllib.error
                import urllib.request

                endpoint = (base_url or AI_PROVIDERS[provider]["base_url"]).rstrip("/") + "/chat/completions"
                payload = json.dumps(
                    {
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    }
                ).encode("utf-8")
                request = urllib.request.Request(
                    endpoint,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=20) as response:
                    response.read(256)
                    self.events.put(("test", f"连接成功（HTTP {response.status}）"))
            except urllib.error.HTTPError as error:
                detail = ""
                try:
                    detail = error.read(200).decode("utf-8", "replace")
                except Exception:
                    pass
                hint = {401: "Key 无效或不被该服务商接受", 403: "Key 无权限或未开通该模型", 404: "模型名或 Base URL 不存在"}.get(error.code, "")
                self.events.put(("test", f"连接失败 HTTP {error.code} {hint} {detail[:120]}".strip()))
            except Exception as error:
                self.events.put(("test", f"连接失败：{type(error).__name__}（检查网络/Base URL）"))

        threading.Thread(target=worker, daemon=True).start()

    def _start(self) -> None:
        if self.worker_active:
            return
        try:
            interval = int(self.interval.get())
            if not 1 <= interval <= 1440:
                raise ValueError
            if not self.python_path.is_file():
                raise FileNotFoundError
        except (ValueError, FileNotFoundError):
            hint = (
                "请确认采集周期为 1–1440 分钟。"
                if is_frozen()
                else "请确认采集周期为 1–1440 分钟，且项目的 .venv312\\Scripts\\python.exe 已安装。"
            )
            messagebox.showerror("无法启动", hint)
            return

        if not self._save_form():
            return
        conflict = detect_env_key_conflict(self.api_key.get())
        if conflict:
            self._append_log(f"⚠ {conflict}")
        self.stop_event.clear()
        self.worker_active = True
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status.set("运行中")
        single_run = self.single_run.get()
        if single_run:
            self._append_log("TrendRadar 启动；本次只运行一轮，跑完自动停止。")
        else:
            self._append_log(f"TrendRadar 启动；每轮结束后等待 {interval} 分钟。")
        api_key = self.api_key.get()
        secrets = [api_key, os.environ.get("AI_API_KEY", "")]
        dingtalk_secret = self.dingtalk_secret.get().strip()
        dingtalk_keyword = self.dingtalk_keyword.get().strip()
        if dingtalk_secret:
            secrets.append(dingtalk_secret)
        self.worker = threading.Thread(
            target=self._run_cycles,
            args=(
                interval,
                secrets,
                api_key,
                self.provider.get(),
                self.clear_environment_key,
                dingtalk_secret,
                dingtalk_keyword,
                single_run,
            ),
            daemon=True,
        )
        self.worker.start()

    def _run_cycles(
        self,
        interval: int,
        secrets: list[str],
        api_key: str,
        provider: str,
        clear_environment_key: bool,
        dingtalk_secret: str = "",
        dingtalk_keyword: str = "",
        single_run: bool = False,
    ) -> None:
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        # 把钉钉加签密钥与关键词传给 TrendRadar 子进程，供发送时自动签名
        if dingtalk_secret:
            environment["DINGTALK_SECRET"] = dingtalk_secret
        else:
            environment.pop("DINGTALK_SECRET", None)
        if dingtalk_keyword:
            environment["DINGTALK_KEYWORD"] = dingtalk_keyword
        else:
            environment.pop("DINGTALK_KEYWORD", None)
        if api_key:
            environment["AI_API_KEY"] = api_key
        elif clear_environment_key:
            environment.pop("AI_API_KEY", None)
        cycle = 0
        try:
            while not self.stop_event.is_set():
                cycle += 1
                self.events.put(("log", f"--- 第 {cycle} 轮开始 ---"))
                if is_frozen():
                    command = [str(self.python_path), "--internal-run-trendradar"]
                else:
                    command = [str(self.python_path), "-u", "-m", "trendradar"]
                process = subprocess.Popen(
                    command,
                    cwd=str(self.project_root),
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                with self.process_lock:
                    self.process = process
                if process.stdout is not None:
                    for line in process.stdout:
                        self.events.put(("log", redact_secrets(line.rstrip("\r\n"), secrets)))
                return_code = process.wait()
                with self.process_lock:
                    self.process = None
                self.events.put(("log", f"--- 本轮结束（退出码 {return_code}）---"))
                if single_run:
                    # 只运行一次：本轮结束即退出循环，不进入等待
                    self.events.put(("log", "「只运行一次」已完成，停止。想看再点启动即可。"))
                    break
                if self.stop_event.wait(interval * 60):
                    break
        except Exception:
            self.events.put(("log", "启动或监控 TrendRadar 时出错；请检查网络与运行环境。"))
        finally:
            with self.process_lock:
                process = self.process
                self.process = None
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            self.events.put(("finished", None))

    def _report_file(self) -> Path:
        """返回最新的 HTML 报告位置（根目录 index.html 优先）。"""
        root_index = self.project_root / "index.html"
        output_index = self.project_root / "output" / "index.html"
        if root_index.is_file():
            return root_index
        return output_index

    def _open_report(self) -> None:
        """用系统默认浏览器打开本地 HTML 报告。"""
        report = self._report_file()
        if not report.is_file():
            self._append_log("还没有生成报告：请先点「保存并启动」跑一轮。")
            self.cloud_status.set("尚未生成报告，先运行一轮。")
            return
        try:
            import webbrowser

            webbrowser.open(report.resolve().as_uri())
            self._append_log(f"已在浏览器打开报告：{report}")
            self.cloud_status.set(f"已在浏览器打开：{report.name}")
        except Exception as error:
            self._show_safe_error("打开报告失败", error)

    def _publish_cloud(self) -> None:
        """把最新报告发布到 Cloudflare Pages，手机可用任何网络打开。"""
        report = self._report_file()
        if not report.is_file():
            self.cloud_status.set("尚未生成报告：请先运行一轮。")
            return
        account_id = self.cf_account.get().strip()
        token = self.cf_token.get().strip()
        project = self.cf_project.get().strip()
        if not (account_id and token and project):
            self.cloud_status.set("请先填写 Account ID、API Token 和项目名。")
            return
        self.cloud_status.set("正在发布到 Cloudflare…")
        self.cloud_button.configure(state=tk.DISABLED)

        def worker() -> None:
            try:
                tools_dir = str(Path(__file__).resolve().parent)
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                import cloudflare_pages

                button_url = cloudflare_pages.publish_html(account_id, token, project, report)
                self.events.put(("cloud", f"发布成功！手机打开：{button_url}"))
            except Exception as error:
                self.events.put(("cloud", f"发布失败：{error}"))
            finally:
                self.events.put(("cloud_btn", None))

        threading.Thread(target=worker, daemon=True).start()

    def _set_interval(self, minutes: int) -> None:
        """一键切换采集周期（直接影响 AI 花费）。"""
        self.interval.set(str(minutes))
        try:
            save_collection_interval(self.settings_file, minutes)
            self._save_form()
        except Exception as error:
            self._show_safe_error("设置周期失败", error)
            return
        self._append_log(f"采集周期已设为 {minutes} 分钟。")

    def _query_balance(self) -> None:
        """查询 DeepSeek 余额，并按当前周期估算每日花费与可用天数。"""
        api_key = self.api_key.get().strip() or os.environ.get("AI_API_KEY", "").strip()
        if not api_key:
            self.cost_status.set("请先在「② AI 服务」里填写 API Key。")
            return
        try:
            interval = int(self.interval.get())
        except ValueError:
            interval = 60
        self.cost_status.set("正在查询余额…")

        def worker() -> None:
            try:
                tools_dir = str(Path(__file__).resolve().parent)
                if tools_dir not in sys.path:
                    sys.path.insert(0, tools_dir)
                import cost_controller

                balance = cost_controller.fetch_balance(api_key)
                processed = cost_controller.count_ai_processed_news(self.project_root)
                sample = processed if processed > 0 else 250
                single = cost_controller.estimate_run_cost(sample)["cost"]
                daily = cost_controller.estimate_daily_cost(sample, interval)
                days = balance["total"] / daily if daily > 0 else 0
                self.events.put(("cost", (balance, single, daily, days, sample, interval)))
            except Exception as error:
                self.events.put(("cost_err", str(error)))
            finally:
                self.events.put(("cost_btn", None))

        threading.Thread(target=worker, daemon=True).start()

    def _stop(self) -> None:
        if not self.worker_active:
            return
        self.stop_event.set()
        with self.process_lock:
            process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        self.status.set("正在停止…")
        self.stop_button.configure(state=tk.DISABLED)

    def _drain_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self._append_log(str(value))
                elif event == "test":
                    self.test_status.set(str(value))
                    self.test_button.configure(state=tk.NORMAL)
                elif event == "test_btn":
                    self.webhook_test_buttons[str(value)].configure(state=tk.NORMAL)
                elif event == "cloud":
                    self.cloud_status.set(str(value))
                    self._append_log(str(value))
                elif event == "cloud_btn":
                    self.cloud_button.configure(state=tk.NORMAL)
                elif event == "cost":
                    balance, single, daily, days, sample, interval = value
                    self.cost_status.set(
                        f"余额 {balance['total']:.2f} 元｜每 {interval} 分钟一轮，"
                        f"约 {daily:.2f} 元/天，还能用 {days:.0f} 天"
                    )
                    self.cost_detail.set(
                        f"按 {sample} 条/轮估算：单次约 {single:.3f} 元；"
                        f"余额较充足时建议用 3-6 小时周期，可省 3-10 倍"
                    )
                elif event == "cost_err":
                    self.cost_status.set(f"查询失败：{value}")
                elif event == "cost_btn":
                    pass
                elif event == "finished":
                    self.worker_active = False
                    self.start_button.configure(state=tk.NORMAL)
                    self.stop_button.configure(state=tk.DISABLED)
                    self.status.set("已停止")
                    self._append_log("TrendRadar 管理进程已停止。")
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _append_log(self, text: str) -> None:
        self.log_view.configure(state=tk.NORMAL)
        self.log_view.insert(tk.END, text + "\n")
        self.log_view.see(tk.END)
        self.log_view.configure(state=tk.DISABLED)

    @staticmethod
    def _show_safe_error(title: str, error: Exception) -> None:
        messagebox.showerror(title, f"{type(error).__name__}。请检查文件格式、权限和路径。")

    def _close(self) -> None:
        if self.worker_active:
            self._stop()
        self.destroy()


if __name__ == "__main__":
    TrendRadarManager().mainloop()
