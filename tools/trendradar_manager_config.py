"""Comment-preserving configuration helpers for the TrendRadar Windows GUI."""

from __future__ import annotations

import os
import re
import io
import tempfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


_BEGIN = "# BEGIN TREND RADAR MANAGER KEYWORDS"
_END = "# END TREND RADAR MANAGER KEYWORDS"

# AI 能力开关：表单标签 -> (config.yaml 中的定位路径, 默认值)
# 这些开关决定"从 newsnow 抓到的热点"到底经过哪些 AI 加工环节。
AI_FEATURE_FIELDS = {
    "AI 分析（推送附洞察报告）": (("ai_analysis", "enabled"), True),
    "AI 智能筛选（自然语言兴趣，替代关键词）": (("filter", "method"), "keyword"),
    "AI 翻译（推送标题译为目标语言）": (("ai_translation", "enabled"), True),
}

# newsnow 数据源默认地址（与 trendradar/crawler/fetcher.py 的 DEFAULT_API_URL 保持一致）
NEWSNOW_DEFAULT_API_URL = "https://newsnow.busiyi.world/api/s"

CHANNEL_FIELDS = {
    "Feishu": ("feishu", "webhook_url"),
    "DingTalk": ("dingtalk", "webhook_url"),
    "WeCom": ("wework", "webhook_url"),
    "Telegram bot token": ("telegram", "bot_token"),
    "Telegram chat ID": ("telegram", "chat_id"),
    "Email password": ("email", "password"),
    "ntfy topic": ("ntfy", "topic"),
    "ntfy token": ("ntfy", "token"),
    "Bark": ("bark", "url"),
    "Slack": ("slack", "webhook_url"),
    "Generic webhook": ("generic_webhook", "webhook_url"),
}

# 只需填一个 Webhook 地址即可使用的渠道（可同时启用多个）
# 界面标签 -> (config 中的 section, 子键, 获取地址的说明)
WEBHOOK_CHANNELS = {
    "飞书": ("feishu", "webhook_url", "飞书群 → 设置 → 群机器人 → 添加机器人 → 自定义机器人 → 复制 Webhook 地址"),
    "钉钉": ("dingtalk", "webhook_url", "钉钉群 → 群设置 → 智能群助手 → 添加机器人 → 自定义 → 复制 Webhook 地址"),
    "企业微信": ("wework", "webhook_url", "企微群 → 群设置 → 群机器人 → 添加 → 复制 Webhook 地址"),
    "Slack": ("slack", "webhook_url", "Slack → Apps → Incoming Webhooks → 复制 Webhook URL"),
}

# 钉钉机器人若启用"加签"安全设置，需要额外填加签密钥（SEC 开头）与关键词
DINGTALK_SECRET_KEY = "dingtalk_secret"
DINGTALK_KEYWORD_KEY = "dingtalk_keyword"
DEFAULT_DINGTALK_KEYWORD = "TrendRadar"


def load_dingtalk_security(config: dict[str, Any]) -> tuple[str, str]:
    """读取钉钉加签密钥与自定义关键词（未配置时关键词回退默认值）。"""
    notification = config.get("notification")
    if not isinstance(notification, dict):
        return "", DEFAULT_DINGTALK_KEYWORD
    secret = str(notification.get(DINGTALK_SECRET_KEY) or "")
    keyword = str(notification.get(DINGTALK_KEYWORD_KEY) or "") or DEFAULT_DINGTALK_KEYWORD
    return secret, keyword


def save_dingtalk_security(path: Path, secret: str, keyword: str) -> None:
    """保存钉钉加签密钥与自定义关键词。"""
    with open(path, "r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    config = _yaml().load(original)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")
    notification = config.get("notification")
    if not isinstance(notification, dict):
        notification = {}
        config["notification"] = notification
    notification[DINGTALK_SECRET_KEY] = (secret or "").strip()
    notification[DINGTALK_KEYWORD_KEY] = (keyword or "").strip()
    output = io.StringIO()
    _yaml().dump(config, output)
    _write_preserving_style(path, original, output.getvalue())


# Cloudflare Pages 发布配置在 config.yaml 中的位置
CLOUDFLARE_SECTION = "cloudflare_pages"


def load_cloudflare_pages(config: dict[str, Any]) -> tuple[str, str, str]:
    """读取 Cloudflare Pages 配置：(account_id, api_token, project_name)。"""
    section = config.get(CLOUDFLARE_SECTION)
    if not isinstance(section, dict):
        return "", "", ""
    return (
        str(section.get("account_id") or ""),
        str(section.get("api_token") or ""),
        str(section.get("project_name") or ""),
    )


def save_cloudflare_pages(path: Path, account_id: str, api_token: str, project_name: str) -> None:
    """保存 Cloudflare Pages 配置，保留配置文件其余内容与注释。"""
    with open(path, "r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    config = _yaml().load(original)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")

    account_id = (account_id or "").strip()
    api_token = (api_token or "").strip()
    project_name = (project_name or "").strip()
    if not (account_id or api_token or project_name):
        config.pop(CLOUDFLARE_SECTION, None)
    else:
        section = config.get(CLOUDFLARE_SECTION)
        if not isinstance(section, dict):
            section = {}
            config[CLOUDFLARE_SECTION] = section
        section["account_id"] = account_id
        section["api_token"] = api_token
        section["project_name"] = project_name

    output = io.StringIO()
    _yaml().dump(config, output)
    _write_preserving_style(path, original, output.getvalue())


def sign_dingtalk_url(webhook_url: str, secret: str) -> str:
    """为钉钉 Webhook 追加 timestamp 与 sign 参数（加签模式必需）。

    算法：sign = Base64(HMAC-SHA256(key=secret, data="{timestamp}\n{secret}"))，
    然后对 sign 做 URL 编码追加到 webhook 地址后。
    """
    if not secret or not secret.strip():
        return webhook_url
    import base64
    import hashlib
    import hmac
    import time
    import urllib.parse

    secret = secret.strip()
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    separator = "&" if "?" in webhook_url else "?"
    return f"{webhook_url}{separator}timestamp={timestamp}&sign={sign}"


def inject_dingtalk_keyword(text: str, keyword: str) -> str:
    """确保消息含钉钉自定义关键词（不含则在开头补上）。"""
    keyword = (keyword or "").strip()
    if not keyword or keyword in text:
        return text
    return f"{keyword}\n\n{text}"


def load_webhook_channels(config: dict[str, Any]) -> dict[str, str]:
    """读取各 Webhook 渠道已配置的地址（未配置的返回空字符串）。"""
    notification = config.get("notification")
    channels = notification.get("channels") if isinstance(notification, dict) else None
    if not isinstance(channels, dict):
        channels = {}
    values: dict[str, str] = {}
    for label, (section, key, _hint) in WEBHOOK_CHANNELS.items():
        section_config = channels.get(section)
        values[label] = (
            str(section_config.get(key) or "")
            if isinstance(section_config, dict)
            else ""
        )
    return values


def save_webhook_channels(path: Path, values: dict[str, str]) -> None:
    """保存多个 Webhook 渠道地址；填了任意一个就开启通知总开关。"""
    with open(path, "r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    config = _yaml().load(original)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")

    notification = config.get("notification")
    if not isinstance(notification, dict):
        notification = {}
        config["notification"] = notification
    channels = notification.get("channels")
    if not isinstance(channels, dict):
        channels = {}
        notification["channels"] = channels

    any_filled = False
    for label, (section, key, _hint) in WEBHOOK_CHANNELS.items():
        if label not in values:
            continue
        address = (values[label] or "").strip()
        if address and not address.startswith("http"):
            raise ValueError(f"{label} 的 Webhook 地址应以 http:// 或 https:// 开头")
        section_config = channels.get(section)
        if not isinstance(section_config, dict):
            section_config = {}
            channels[section] = section_config
        section_config[key] = address
        if address:
            any_filled = True

    notification["enabled"] = any_filled
    output = io.StringIO()
    _yaml().dump(config, output)
    _write_preserving_style(path, original, output.getvalue())

AI_PROVIDERS = {
    "火山方舟（豆包）": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": (
            "doubao-lite-4k",
            "doubao-lite-32k",
            "doubao-pro-4k",
            "doubao-pro-32k",
            "doubao-pro-128k",
            "doubao-1-5-lite-32k",
            "doubao-1-5-pro-32k",
            "doubao-1-5-pro-256k",
            "doubao-seed-1.6-flash",
            "doubao-seed-1.6-thinking",
            "doubao-seed-2.0-mini",
            "doubao-seed-2.0-lite",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.1-turbo",
            "doubao-seed-2.1-lite",
            "doubao-seed-2.1-pro",
            "doubao-seed-evolving",
            "deepseek-v3",
            "deepseek-v4-flash",
            "deepseek-v4.1-flash",
            "deepseek-v4-pro",
            "deepseek-r1",
            "deepseek-r1-distill-qwen-32b",
            "deepseek-r1-distill-qwen-37b",
            "qwen2-7b-instruct",
            "qwen2-14b-instruct",
            "qwen2-72b-instruct",
            "qwen3-7b-instruct",
            "qwen3-14b-instruct",
            "qwen3-72b-instruct",
            "glm-4-flash",
            "glm-4",
            "glm-4-plus",
            "glm-5",
            "glm-5-2",
            "glm-5-3-flash",
            "kimi-k2.6",
            "kimi-k2.7",
            "kimi-k2.8",
            "kimi-k3",
            "minimax-m2.5",
            "minimax-m2.7",
            "minimax-m3",
            "minimax-m3.1-flash",
            "mistral-7b-instruct",
            "mistral-nemo",
            "mistral-large",
        ),
    },
    "阿里云百炼": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": (
            "qwen-turbo",
            "qwen-plus",
            "qwen-max",
            "qwen3-7b-instruct",
            "qwen3-14b-instruct",
            "qwen3-72b-instruct",
        ),
    },
    "智谱 GLM": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ("glm-4-flash", "glm-4", "glm-4-plus", "glm-5"),
    },
    "Kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ("kimi-k2.6", "kimi-k2.7", "kimi-k2.8", "kimi-k3"),
    },
    "腾讯混元": {
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "models": ("hunyuan-lite", "hunyuan-standard", "hunyuan-pro"),
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ("deepseek-chat", "deepseek-lite", "deepseek-v3", "deepseek-r1"),
    },
    "MiniMax": {
        "base_url": "https://api.minimax.chat/v1",
        "models": ("minimax-m2.5", "minimax-m2.7", "minimax-m3", "minimax-m3.1-flash"),
    },
    "科大讯飞星火": {
        "base_url": "https://spark-api.xf-yun.com/v4.0",
        "models": ("spark-lite", "spark-pro", "spark-max"),
    },
    "自定义兼容接口": {
        "base_url": "",
        "models": (),
    },
}


def _yaml() -> YAML:
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    return parser


def load_config(path: Path) -> Any:
    with open(path, "r", encoding="utf-8", newline="") as stream:
        config = _yaml().load(stream)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")
    return config


def get_form_values(
    config: dict[str, Any],
    channel_label: str,
) -> tuple[str, str, str, str]:
    ai = config.get("ai", {})
    notifications = config.get("notification", {})
    channels = notifications.get("channels", {}) if isinstance(notifications, dict) else {}
    section, key = CHANNEL_FIELDS[channel_label]
    channel_config = channels.get(section, {}) if isinstance(channels, dict) else {}
    model = str(ai.get("model", "") or "")
    api_base = str(ai.get("base_url", "") or ai.get("api_base", "") or "")
    configured_provider = str(ai.get("service_provider", "") or "")
    provider = infer_ai_provider(ai, model, api_base)
    if model.startswith("openai/"):
        model = model[len("openai/"):]
    elif "/" in model and model.split("/", 1)[0] in ("deepseek", "ollama"):
        model = model.split("/", 1)[1]
    api_key = str(ai.get("api_key", "") or "")
    if configured_provider in ("Ollama", "Ollama（本地模型）") and api_key == "ollama":
        api_key = ""
    models = AI_PROVIDERS[provider]["models"]
    if provider != "自定义兼容接口" and model not in models:
        model = models[0]
    return (
        provider,
        api_base or AI_PROVIDERS[provider]["base_url"],
        api_key,
        model,
        str(channel_config.get(key, "") or "") if isinstance(channel_config, dict) else "",
    )


def infer_ai_provider(ai: dict[str, Any], model: str, api_base: str) -> str:
    provider = str(ai.get("service_provider", "") or "")
    if provider == "Ollama（本地模型）" or provider == "Ollama":
        provider = "自定义兼容接口"
    if provider in AI_PROVIDERS:
        return provider

    lowered_model = model.lower()
    lowered_base = api_base.lower()
    if lowered_model.startswith("deepseek/") or "deepseek.com" in lowered_base:
        return "DeepSeek"
    if "ark.cn-beijing.volces.com" in lowered_base:
        return "火山方舟（豆包）"
    if "dashscope.aliyuncs.com" in lowered_base:
        return "阿里云百炼"
    if "open.bigmodel.cn" in lowered_base:
        return "智谱 GLM"
    if "moonshot.cn" in lowered_base:
        return "Kimi"
    if "hunyuan.cloud.tencent.com" in lowered_base:
        return "腾讯混元"
    if "minimax.chat" in lowered_base:
        return "MiniMax"
    if "xf-yun.com" in lowered_base:
        return "科大讯飞星火"
    if api_base:
        return "自定义兼容接口"
    return "火山方舟（豆包）"


def provider_models(provider: str) -> tuple[str, ...]:
    return AI_PROVIDERS[provider]["models"]


def _get_nested(config: dict[str, Any], path: tuple[str, ...], default: Any) -> Any:
    """按路径读取嵌套配置，任一层不是 mapping 时回退默认值。"""
    current: Any = config
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _set_nested(config: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """按路径写入嵌套配置，缺失层自动创建。"""
    current: dict[str, Any] = config
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def load_ai_features(config: dict[str, Any]) -> dict[str, Any]:
    """读取 AI 能力开关现状，返回 {表单标签: 当前值}。"""
    features: dict[str, Any] = {}
    for label, (path, default) in AI_FEATURE_FIELDS.items():
        value = _get_nested(config, path, None)
        if value is None:
            value = default
        # 筛选方式对表单呈现为布尔值：method == "ai" 即开启
        if path == ("filter", "method"):
            value = str(value).strip().lower() == "ai"
        features[label] = bool(value)
    return features


def save_ai_features(path: Path, features: dict[str, bool]) -> None:
    """保存 AI 能力开关，只改动相关三段，不影响其他配置与注释。"""
    with open(path, "r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    config = _yaml().load(original)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")

    for label, (feature_path, default) in AI_FEATURE_FIELDS.items():
        if label not in features:
            continue
        enabled = bool(features[label])
        if feature_path == ("filter", "method"):
            _set_nested(config, feature_path, "ai" if enabled else "keyword")
        else:
            _set_nested(config, feature_path, enabled)

    output = io.StringIO()
    _yaml().dump(config, output)
    _write_preserving_style(path, original, output.getvalue())


def load_source_api_url(config: dict[str, Any]) -> str:
    """读取 newsnow 数据源地址；留空表示使用内置默认地址。"""
    return str(_get_nested(config, ("platforms", "api_url"), "") or "")


def save_source_api_url(path: Path, api_url: str) -> None:
    """保存 newsnow 数据源地址（留空则回退内置默认地址）。"""
    with open(path, "r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    config = _yaml().load(original)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")

    cleaned = api_url.strip()
    if cleaned and not re.match(r"^https?://", cleaned, re.IGNORECASE):
        raise ValueError("数据源地址必须以 http:// 或 https:// 开头")

    platforms = config.get("platforms")
    if not isinstance(platforms, dict):
        platforms = {}
        config["platforms"] = platforms
    platforms["api_url"] = cleaned

    output = io.StringIO()
    _yaml().dump(config, output)
    _write_preserving_style(path, original, output.getvalue())


# 官方兴趣文件里的引导语，不参与编辑正文
_INTERESTS_LEAD = "下面是我要关注的内容"

# 面向普通用户的关注方向模板：勾选后自动填入"AI 兴趣描述"
# 每项是 (模板名称, 一句话说明, 兴趣条目列表)
INTEREST_PRESETS = (
    (
        "科技与 AI",
        "国产大模型、芯片、算力、智能汽车、机器人",
        (
            "国产大模型与 AI 产品发布：DeepSeek、通义、豆包、Kimi、智谱等的能力演进与开源竞争",
            "AI 芯片与算力：英伟达、昇腾、CUDA、算力供给与推理成本变化",
            "半导体制造：光刻机、先进封装、国产替代与供应链安全",
            "智能汽车与自动驾驶：比亚迪、特斯拉、智驾方案、销量与出海",
            "机器人与具身智能：人形机器人、四足机器人、量产与场景落地",
        ),
    ),
    (
        "财经与市场",
        "股市、汇率、利率、宏观政策",
        (
            "股市与资本市场：A 股、港股、美股重大波动与监管政策",
            "货币政策：美联储与央行利率决议、降准降息、流动性变化",
            "汇率与大宗商品：人民币汇率、原油、黄金价格异动",
            "宏观经济数据：CPI、PMI、就业、GDP 等重要指标",
            "行业龙头财报：业绩暴雷或超预期、重大并购重组",
        ),
    ),
    (
        "游戏与数码",
        "新游戏、新硬件、发布会",
        (
            "新游戏发售与评测：黑神话悟空、影之刃等国产 3A 与热门新游",
            "游戏公司动态：腾讯、米哈游、网易的产品与运营动作",
            "数码硬件发布：手机、显卡、CPU、掌机新品与价格",
            "光刻机与芯片代工进展对消费电子价格的影响",
        ),
    ),
    (
        "社会与民生",
        "政策、教育、医疗、消费",
        (
            "教育政策：中高考改革、双减、培训机构监管",
            "医疗与健康：医保政策、药品集采、公共卫生事件",
            "消费与零售：胖东来等零售标杆、消费趋势与补贴政策",
            "房地产与住房政策：限购松绑、房贷利率、保交楼",
            "就业与社保：就业形势、劳动保障、社保调整",
        ),
    ),
    (
        "国际与地缘",
        "中美欧关系、关税、冲突",
        (
            "中美关系与关税：贸易谈判、出口管制、产业脱钩",
            "地缘冲突：俄乌、中东及周边地区重大局势变化",
            "国际组织与外交：联合国、G7、金砖等重大会议与决议",
            "其他国家科技产业政策：欧盟、日本、印度的产业补贴与监管",
        ),
    ),
    (
        "能源与汽车",
        "光伏、核电、新能源车",
        (
            "新能源与光伏：光伏产能、储能、风光大基地项目",
            "核电与电力系统：核电机组核准、电网建设、电价改革",
            "新能源汽车：销量排行、价格战、电池技术与充电基础设施",
        ),
    ),
)



def _split_interests_layout(lines: list[str]) -> tuple[int, int]:
    """返回 (head_end, tail_start)：头部注释区结束位置与尾部说明段起始位置。

    官方兴趣文件的结构是「注释头 + 正文 + 尾部说明（可能含无 # 的列表项）」。
    头部：文件开头连续的注释行与空行。
    尾部：从末尾往回找到的最后一段注释块，该块到文件末尾都视为尾部说明。
    """
    head_end = 0
    for index, line in enumerate(lines):
        if line.strip() and not line.strip().startswith("#"):
            break
        head_end = index + 1

    tail_start = len(lines)
    for index in range(len(lines) - 1, head_end - 1, -1):
        if lines[index].strip().startswith("#"):
            tail_start = index
            while tail_start - 1 >= head_end and lines[tail_start - 1].strip().startswith("#"):
                tail_start -= 1
            break
    return head_end, tail_start


def load_ai_interests(path: Path) -> str:
    """读取 AI 兴趣描述正文（跳过注释头、官方引导语与尾部说明，便于直接编辑）。"""
    if not path.is_file():
        return ""
    content = path.read_bytes().decode("utf-8-sig")
    lines = content.splitlines()

    # 有锚点时只取锚点之间（本工具维护的正文）
    if content.count(_INTERESTS_BEGIN) == 1 and content.count(_INTERESTS_END) == 1:
        start = content.index(_INTERESTS_BEGIN) + len(_INTERESTS_BEGIN)
        end = content.index(_INTERESTS_END)
        lines = content[start:end].splitlines()
        body = [line.rstrip() for line in lines if line.strip()]
        return "\n".join(body)

    head_end, tail_start = _split_interests_layout(lines)
    body = [
        line.rstrip()
        for line in lines[head_end:tail_start]
        if line.strip() and not line.strip().startswith("#") and not line.strip().startswith(_INTERESTS_LEAD)
    ]
    return "\n".join(body)


# 兴趣正文的分界锚点：正文写在两个锚点之间，锚点之外的注释头与尾部原样保留
_INTERESTS_BEGIN = "# >>> TrendRadar GUI 兴趣描述（以下由管理器维护，可直接编辑）"
_INTERESTS_END = "# <<< TrendRadar GUI 兴趣描述结束"


def save_ai_interests(path: Path, text: str) -> None:
    """保存兴趣描述，保留原文件注释头与尾部说明。

    正文写入一对锚点注释之间；重复保存只替换锚点内内容，不会重复累积。
    """
    raw = path.read_bytes() if path.is_file() else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    original = raw.decode("utf-8-sig") if raw else ""
    newline = "\r\n" if "\r\n" in original else "\n"
    body = newline.join(line.rstrip() for line in text.splitlines() if line.strip())
    block = f"{_INTERESTS_BEGIN}{newline}{body}{newline}{_INTERESTS_END}"

    if original.count(_INTERESTS_BEGIN) == 1 and original.count(_INTERESTS_END) == 1:
        start = original.index(_INTERESTS_BEGIN)
        end = original.index(_INTERESTS_END) + len(_INTERESTS_END)
        content = original[:start] + block + original[end:]
    elif original.strip():
        # 首次接管：保留开头注释头 + 尾部注释段（如"标题质量要求"），只替换中间正文
        lines = original.splitlines()
        head_end, tail_start = _split_interests_layout(lines)

        head = [line for line in lines[:head_end]]
        while head and not head[-1].strip():
            head.pop()
        # 尾部保留原始行（含列表项），只去掉尾部多余空行
        tail = [line.rstrip() for line in lines[tail_start:]]
        while tail and not tail[0].strip():
            tail.pop(0)
        while tail and not tail[-1].strip():
            tail.pop()

        parts = [newline.join(head), "", block]
        if tail:
            parts += ["", newline.join(tail)]
        content = newline.join(parts) + newline
    else:
        content = block + newline

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    if bom:
        encoded = b"\xef\xbb\xbf" + encoded
    _atomic_write(path, encoded)


def _write_preserving_style(path: Path, original: str, serialized: str) -> None:
    """统一处理换行符与 BOM 后原子写入。"""
    newline = "\r\n" if "\r\n" in original else "\n"
    serialized = serialized.replace("\r\n", "\n").replace("\n", newline)
    if original.startswith("\ufeff"):
        serialized = "\ufeff" + serialized
    _atomic_write(path, serialized.encode("utf-8"))


def detect_env_key_conflict(configured_key: str, environ: dict[str, str] | None = None) -> str | None:
    """检测系统环境变量 AI_API_KEY 是否会覆盖 GUI 里配置的 Key。

    TrendRadar 的 loader 中环境变量优先级高于 config.yaml，若二者不一致，
    实际运行使用的是环境变量里的旧 Key，用户会误以为界面保存失败。
    返回冲突说明文本；无冲突返回 None。
    """
    source = os.environ if environ is None else environ
    env_key = (source.get("AI_API_KEY") or "").strip()
    if not env_key:
        return None
    configured = (configured_key or "").strip()
    if env_key == configured:
        return None
    if not configured:
        return "检测到环境变量 AI_API_KEY 已设置，将覆盖界面中留空的 Key。"
    return (
        "检测到环境变量 AI_API_KEY 与界面中填写的 Key 不一致，"
        "实际运行时会优先使用环境变量中的 Key。"
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def save_config(
    path: Path,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    channel_label: str,
    channel_value: str,
    clear_api_key: bool = False,
) -> None:
    with open(path, "r", encoding="utf-8", newline="") as stream:
        original = stream.read()
    config = _yaml().load(original)
    if not isinstance(config, dict):
        raise ValueError("config.yaml must contain a YAML mapping")
    if provider not in AI_PROVIDERS:
        raise ValueError(f"Unknown AI provider: {provider}")
    if provider == "自定义兼容接口":
        if not base_url.strip():
            raise ValueError("Custom AI Base URL must not be empty")
        if not model.strip():
            raise ValueError("Custom AI model must not be empty")
    elif model not in AI_PROVIDERS[provider]["models"]:
        raise ValueError(f"Model {model!r} is not available for {provider}")

    ai = config.setdefault("ai", {})
    if not isinstance(ai, dict):
        raise ValueError("config.yaml ai section must be a mapping")
    ai["service_provider"] = provider
    ai["provider"] = "openai_compatible"
    selected_base_url = base_url.strip() if provider == "自定义兼容接口" else AI_PROVIDERS[provider]["base_url"]
    selected_model = model.strip()
    ai["base_url"] = selected_base_url
    ai["api_base"] = selected_base_url
    ai["model"] = selected_model if selected_model.startswith("openai/") else f"openai/{selected_model}"
    if api_key:
        ai["api_key"] = api_key
    elif clear_api_key:
        ai["api_key"] = ""

    section, key = CHANNEL_FIELDS[channel_label]
    notification = config.setdefault("notification", {})
    if not isinstance(notification, dict):
        raise ValueError("config.yaml notification section must be a mapping")
    channels = notification.setdefault("channels", {})
    if not isinstance(channels, dict):
        raise ValueError("config.yaml notification.channels section must be a mapping")
    channel = channels.setdefault(section, {})
    if not isinstance(channel, dict):
        raise ValueError(f"config.yaml notification.channels.{section} must be a mapping")
    if channel_value:
        channel[key] = channel_value
        notification["enabled"] = True

    output = io.StringIO()
    _yaml().dump(config, output)
    _write_preserving_style(path, original, output.getvalue())


def load_managed_keywords(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    block = _find_keyword_block(content)
    if block is None:
        return []
    start, end = block
    lines = content[start:end].splitlines()
    keywords = []
    for line in lines[1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not (stripped.startswith("[") and stripped.endswith("]")):
            keywords.append(stripped)
    return keywords


def _find_keyword_block(content: str) -> tuple[int, int] | None:
    begin_count = content.count(_BEGIN)
    end_count = content.count(_END)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise ValueError("frequency_words.txt has invalid GUI keyword markers")
    start = content.index(_BEGIN)
    end_marker = content.index(_END)
    if end_marker < start:
        raise ValueError("frequency_words.txt keyword markers are out of order")
    end = content.find("\n", end_marker)
    if end == -1:
        end = len(content)
    else:
        end += 1
    return start, end


def save_managed_keywords(path: Path, keywords: list[str]) -> None:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    content = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in content else "\n"
    block = _find_keyword_block(content)
    cleaned = [word.strip() for word in keywords if word.strip()]
    if any("\n" in word or "\r" in word for word in cleaned):
        raise ValueError("Each keyword must be on a single line")

    replacement = ""
    if cleaned:
        if "[WORD_GROUPS]" not in content:
            raise ValueError("frequency_words.txt is missing [WORD_GROUPS]")
        replacement = newline.join([_BEGIN, "[TrendRadar GUI]", *cleaned, _END]) + newline

    if block is not None:
        start, end = block
        content = content[:start] + replacement + content[end:]
    elif replacement:
        content = content.rstrip("\r\n") + newline * 2 + replacement

    encoded = content.encode("utf-8")
    if bom:
        encoded = b"\xef\xbb\xbf" + encoded
    _atomic_write(path, encoded)


def read_collection_interval(settings_path: Path, default: int = 60) -> int:
    try:
        import json

        data = json.loads(settings_path.read_text(encoding="utf-8"))
        value = int(data.get("collection_interval_minutes", default))
        return value if 1 <= value <= 1440 else default
    except (OSError, ValueError, TypeError, AttributeError):
        return default


def save_collection_interval(settings_path: Path, interval: int) -> None:
    import json

    if not 1 <= interval <= 1440:
        raise ValueError("Collection interval must be between 1 and 1440 minutes")
    content = json.dumps(
        {"collection_interval_minutes": interval},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    _atomic_write(settings_path, content)


def redact_secrets(text: str, secrets: list[str]) -> str:
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)
