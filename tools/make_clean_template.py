"""生成用于打包的干净配置模板：保留注释与结构，清空全部凭据。"""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"E:\TrendRadar-master")
SRC = ROOT / "config"
DST = ROOT / "templates" / "config"

from ruamel.yaml import YAML  # noqa: E402


def clean_config_yaml(text: str) -> str:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    data = yaml.load(text)
    if not isinstance(data, dict):
        raise ValueError("config.yaml 不是映射结构")

    # AI 凭据
    ai = data.get("ai")
    if isinstance(ai, dict):
        ai["api_key"] = ""
        ai["api_base"] = ""
        for key in ("service_provider", "provider", "base_url"):
            ai.pop(key, None)

    # 推送渠道：清空所有凭据
    notification = data.get("notification")
    if isinstance(notification, dict):
        channels = notification.get("channels")
        if isinstance(channels, dict):
            for section in channels.values():
                if not isinstance(section, dict):
                    continue
                for key in list(section.keys()):
                    if key == "msg_type":
                        continue
                    if isinstance(section[key], str):
                        section[key] = ""
        notification["enabled"] = False
        for key in ("dingtalk_secret", "dingtalk_keyword"):
            notification.pop(key, None)

    # 移除可能存在的云存储 / Cloudflare 凭据
    for key in ("cloudflare_pages",):
        data.pop(key, None)
    storage = data.get("storage")
    if isinstance(storage, dict):
        remote = storage.get("remote")
        if isinstance(remote, dict):
            for key in ("bucket", "access_key", "secret_key", "endpoint"):
                if key in remote:
                    remote[key] = ""

    # 默认用关键词筛选，用户自行决定是否开 AI
    filter_section = data.get("filter")
    if isinstance(filter_section, dict) and "method" in filter_section:
        filter_section["method"] = "keyword"

    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()


def main() -> int:
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    for item in SRC.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(SRC)
        target = DST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel.name == "config.yaml":
            text = item.read_text(encoding="utf-8")
            target.write_text(clean_config_yaml(text), encoding="utf-8")
            print(f"  净化: {rel}")
        else:
            shutil.copy2(item, target)
            print(f"  复制: {rel}")

    print()
    print(f"模板目录: {DST}")
    total = sum(1 for _ in DST.rglob("*") if _.is_file())
    print(f"文件数: {total}")

    # 校验：确认无凭据残留
    check = (DST / "config.yaml").read_text(encoding="utf-8")
    bad = [k for k in ("sk-", "oapi.dingtalk.com/robot", "open.feishu.cn/open-apis/bot/v2/hook/", "SEC") if k in check]
    print("残留凭据检查:", "❌ " + ", ".join(bad) if bad else "✅ 无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
