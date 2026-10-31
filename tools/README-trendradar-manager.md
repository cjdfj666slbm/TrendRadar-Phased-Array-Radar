# TrendRadar Windows Manager

The Tkinter client in `tools\trendradar_manager.py` manages the existing TrendRadar installation. It launches each collection round with `.venv312\Scripts\python.exe -u -m trendradar`, shows live output, and waits the selected number of minutes after each round. **Start saves the form first.** Stop terminates the current TrendRadar process.

## 三步向导（面向普通用户）

界面按"选方向 → 填 Key → 选渠道"三步组织，高级项默认收起：

**① 我关心什么** — 6 个关注方向模板（科技与 AI / 财经与市场 / 游戏与数码 / 社会与民生 / 国际与地缘 / 能源与汽车），勾选后自动填入自然语言兴趣描述。首次勾选会替换上游自带的示例兴趣，避免与用户选择混杂；可多选叠加，也可直接在下方文本框改写。

**② AI 服务** — 选服务商 + 填 API Key + 选模型。"测试 AI 连接"按钮会真实发一次最小请求并报告 401/403/404 等结果。Base URL / 数据源 / 采集周期 / 清除 Key 收在"显示高级设置"里。

**③ 推送到哪里** — 选渠道并填凭据；不填则只生成 HTML 报告。

保存时自动决定 `filter.method`：**兴趣框有内容 → `ai`（AI 智能筛选），留空 → `keyword`**。用户永远只面对一个"我关心什么"输入框，不需要理解关键词语法与 AI 兴趣的区别。`ai_analysis.enabled` 固定开启，`ai_translation.enabled` 固定关闭（普通场景用不上，需要时用高级设置）。

The form edits `config\config.yaml` using comment-preserving YAML round-tripping and updates only the selected AI/channel values. AI providers are 火山方舟（豆包）, 阿里云百炼, 智谱 GLM, Kimi, 腾讯混元, DeepSeek, MiniMax, 科大讯飞星火, and 自定义兼容接口. Selecting a preset provider refreshes its read-only model dropdown and locks its Base URL. The custom provider unlocks both Base URL and model; API Key is the only manually entered credential. The GUI stores `provider: openai_compatible`, the selected provider label, `base_url`, `api_base` (the field consumed by TrendRadar), the API key, and a LiteLLM `openai/<model>` model name. This uses TrendRadar's existing OpenAI-compatible LiteLLM path; no backend code is changed.

Keywords are stored in a marked `[TrendRadar GUI]` block in `config\frequency_words.txt`; other keyword groups and global filters are left alone. The cycle interval is stored in `%LOCALAPPDATA%\TrendRadar\manager.json`, not in TrendRadar's application config.

## AI 加工链路

The GUI is the single place to wire the newsnow-sourced hotlist to AI processing. Three toggles under **AI 加工环节** map to the switches TrendRadar actually reads:

| 界面开关 | 写入 `config.yaml` | 作用 |
| --- | --- | --- |
| AI 分析 | `ai_analysis.enabled` | 推送正文后附 AI 洞察报告 |
| AI 智能筛选 | `filter.method: ai` / `keyword` | natural-language interests replace keyword matching |
| AI 翻译 | `ai_translation.enabled` | translate pushed titles to the target language |

**newsnow 数据源** edits `platforms.api_url`. Leave it empty to use the built-in default (`https://newsnow.busiyi.world/api/s`). Only `http://` / `https://` URLs are accepted.

**AI 兴趣描述** edits `config\ai_interests.txt` — the natural-language interests consumed when **AI 智能筛选** is enabled. The editor only rewrites the body between the `# >>> TrendRadar GUI 兴趣描述` / `# <<< …结束` anchors, so the official comment header (`Version: 1.1.0`) and the trailing 标题质量要求 block are preserved, and repeated saves never accumulate duplicate blocks. The reader strips the official `下面是我要关注的内容：` lead-in so only real interest lines appear.

**测试 AI 连接** sends one minimal `chat/completions` request with the current Base URL / Key / model and reports the result inline (including a 401/403/404 hint), so a bad key is caught before a full collection round is wasted.

## Token 用量可见性

DSH 客户端只统计**它自己**的对话 token，TrendRadar 作为独立进程调用 API 的消耗它看不到。为此在 `trendradar/ai/client.py` 补了用量追踪（TrendRadar 原生会丢弃 API 返回的 `usage` 字段）：

- 每次 AI 调用打印一行：`[AI 用量] 本次：输入 N + 输出 M = T tokens（缓存命中 C）≈ ¥X.XXXX｜累计：K 次调用 …`
- 每次运行结束打印汇总：`[AI 成本] 本次运行共 K 次 AI 调用：输入 N / 输出 M tokens（缓存命中 C），估算花费 ¥X.XXXX`
- 统计是**类级共享**的，`analyzer` / `filter` / `translator` 三个模块的消耗会汇总到同一份计数

**在哪里看**：管理器窗口底部的「运行日志」区会实时显示这些行（它转发 TrendRadar 子进程的 stdout）。命令行运行则直接输出到终端。

价格参数按 DeepSeek 官方价写在 `client.py` 顶部（输入 2 元/百万、输出 8 元/百万、缓存 0.1 元/百万），换服务商需自行调整。

## 已知限制

- **环境变量优先级**：TrendRadar 的 `core/loader.py` 中 `AI_API_KEY` 环境变量优先于 `config.yaml`。若系统里残留旧 `AI_API_KEY`，界面填的 Key 会被静默覆盖。GUI 会检测到这种情况并在状态栏与运行日志中提示，但不会（也不应）擅自修改系统环境变量。
- **`service_provider` / `provider` / `base_url` 仅本工具使用**：TrendRadar 后端只读取 `model` / `api_key` / `api_base`。前三个键用于界面回显，改动它们不影响运行结果。
- **DeepSeek 的 `deepseek-chat` 是别名**：实测请求 `deepseek-chat` 时 API 返回 `model: deepseek-flash`，即服务端做了名称映射。当前该 Key 可用的模型只有 `deepseek-flash` 与 `deepseek-v4-pro`，因此 `config.yaml` 直接写 `openai/deepseek-flash`，避免依赖别名的未来变化。要判断实际用了哪个模型，看 API 响应里的 `model` 字段。
- **采集周期是"跑完再等"**：实际间隔 = 单轮采集耗时 + 设定分钟数，不是严格定时。
- **源码运行需 ruamel.yaml**：exe 已内置该依赖；若直接 `python tools\trendradar_manager.py`，需先 `uv add --dev ruamel.yaml`，否则 ImportError。

API keys and channel credentials are masked in the form and redacted from captured application logs. They remain plaintext in `config.yaml`, as expected by TrendRadar; protect that file and do not share it. Changing providers clears the previous provider's API key entry so a credential is not silently reused. The GUI does not configure every channel option (for example, Telegram's paired token and chat ID); use the project's regular config editor for advanced channel settings.

## Build and launch

From PowerShell in this project, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_trendradar_manager.ps1
```

The build uses `uv tool run` with temporary/cached PyInstaller and `ruamel.yaml` tooling; it does not install packages into or change `.venv312`. On successful packaging it writes a one-file, no-console GUI executable under `dist\TrendRadarManager*.exe`, updates a prior TrendRadar Manager Desktop shortcut created for this project's `dist` executable (or creates a new shortcut if none exists), and verifies that the shortcut target is the generated executable. The build needs `uv` and network access the first time.

The process-scoped `-ExecutionPolicy Bypass` only runs this build script for the current PowerShell process; it does not change the machine or user policy. The executable bundles the GUI runtime, but intentionally **reuses the existing TrendRadar project and its `.venv312`**. Keep the executable in `dist` under the project root (or another descendant) and keep `.venv312` and `config` in place. It is not a self-contained TrendRadar distribution: moving it to a different computer or away from this project will not work without that installation. No administrator/UAC elevation is required.

## Tests

The config and keyword preservation tests can run without changing `.venv312`:

```powershell
uv tool run --python 3.12 --with ruamel.yaml --with pytest pytest tests\test_trendradar_manager_config.py -q
```
