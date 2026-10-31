# TrendRadar 开箱即用版 · 管理器

> 一键把全网热榜接上 AI，只推你关心的新闻。下载即用，无需安装 Python。

---

## 这是什么

这是 [TrendRadar](https://github.com/sansan0/TrendRadar) 的**图形化管理器 + 独立打包版**。

原版 TrendRadar 需要 `git clone`、安装 Python、手改 YAML 配置，对普通用户门槛较高。
本工具把这一切收进一个窗口：**选关注方向 → 填 AI Key → 选推送渠道 → 点启动**。

| 对比 | 原版 TrendRadar | 本工具 |
| --- | --- | --- |
| 安装 | clone + uv sync | **下载 exe 双击** |
| 配置 | 手动编辑 YAML | 图形界面 |
| AI 接入 | 改配置文件 | 选服务商 + 粘贴 Key |
| 关键词语法 | 需学习 | 勾选兴趣模板即可 |
| 报告查看 | 命令行路径 | 内置按钮打开 |

---

## 快速开始（3 步）

### 1. 下载并运行

下载 `TrendRadar.exe`，放到任意可写目录，双击运行。

> 首次运行会在 exe 同级创建 `runtime/` 目录存放配置与数据。
> 若该目录不可写，自动回落到 `%APPDATA%\TrendRadar`。

### 2. 配置 AI

- **AI 服务商**：下拉选择（DeepSeek / 火山方舟 / 阿里云百炼 / 智谱 / Kimi / 腾讯混元 / MiniMax / 讯飞星火 / 自定义兼容接口）
- **API Key**：粘贴你的 Key
- 点 **测试 AI 连接** 确认可用

> 推荐 DeepSeek：`deepseek-flash` 每轮筛选约 ¥0.1–0.2，适合日常使用。

### 3. 选兴趣并启动

- 勾选关注方向（科技与 AI / 财经 / 游戏 / 民生 / 国际 / 能源）
- 点 **保存并启动**
- 跑完后点 **在电脑上查看** 打开报告

**不配置任何推送渠道也能用**——报告会生成为本地 HTML 网页。

---

## 功能

### AI 加工链路

| 界面开关 | 作用 |
| --- | --- |
| AI 智能筛选 | 用自然语言描述兴趣，AI 逐条判断相关度（替代关键词匹配） |
| AI 分析 | 推送末尾附洞察报告 |
| AI 翻译 | 标题翻译为目标语言 |

### 推送渠道

飞书 / 钉钉 / 企业微信 / Slack 群机器人（填 Webhook 地址即可，可同时启用多个）。

**钉钉用户注意**：若机器人启用了「加签」或「自定义关键词」，需在界面填写对应字段，程序会自动签名并在消息中注入关键词。

### 费用控制

- 查询 DeepSeek 余额
- 估算每日花费与可用天数
- 一键切换采集周期
- **只运行一次**模式：跑完即停，不循环

### Token 用量可见

每次 AI 调用打印实际用量，运行结束打印汇总：

```
[AI 用量] 本次：输入 1200 + 输出 300 = 1500 tokens（缓存命中 0）≈ ¥0.0048
[AI 成本] 本次运行共 12 次 AI 调用：输入 15200 / 输出 3100 tokens，估算花费 ¥0.055
```

---

## 数据存放位置

```
TrendRadar.exe
runtime/
  ├── config/          # 配置文件（首次运行自动生成）
  │   ├── config.yaml
  │   ├── frequency_words.txt
  │   ├── ai_interests.txt
  │   └── ...
  └── output/          # 报告与数据库
      ├── index.html   # 最新报告
      ├── news/        # 每日数据库
      └── html/        # 历史报告快照
```

---

## 常见问题

**Q: 需要安装 Python 吗？**
不需要。Python 运行时已打包进 exe。

**Q: 会花多少钱？**
取决于 AI 用量。DeepSeek `deepseek-flash` 下，530 条新闻全量筛选约 ¥0.2；之后只处理新增，通常每轮 ¥0.05 以内。
可用界面的 **查询余额** 实时查看。

**Q: 不配推送渠道能用吗？**
能。报告会生成本地 HTML，点「在电脑上查看」即可。

**Q: 钉钉提示「关键词不匹配」？**
机器人安全设置里填了自定义关键词。在管理器「③ 推送渠道」的「钉钉关键词」填入同一个词即可。

**Q: 数据会上传到哪里？**
仅在你配置的 AI 服务商（用于筛选/分析）与你配置的推送渠道。其余数据全在本地。

---

## 许可证

本项目基于 [TrendRadar](https://github.com/sansan0/TrendRadar)（作者 [@sansan0](https://github.com/sansan0)），遵循 **GPL-3.0** 协议分发。

- 本仓库代码同样以 GPL-3.0 开源
- 保留原项目协议文件与署名
- 详细条款见 [LICENSE](LICENSE)

---

## 致谢

- [TrendRadar](https://github.com/sansan0/TrendRadar) — 核心抓取、分析、推送能力
- [newsnow](https://github.com/ourongxing/newsnow) — 多平台热榜数据源
- [LiteLLM](https://github.com/BerriAI/litellm) — 统一 AI 模型接口
