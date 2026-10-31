"""DeepSeek 账户余额查询与 AI 使用量估算。

只依赖标准库，便于随 GUI 一起打包。
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BALANCE_URL = "https://api.deepseek.com/user/balance"

# DeepSeek 官方价格（元 / 百万 tokens），用于本地估算
PRICE_INPUT_PER_M = 2.0
PRICE_OUTPUT_PER_M = 8.0

# 单条新闻经 AI 筛选时的 token 估算参数
TOKENS_PER_TITLE = 40
TOKENS_PROMPT_OVERHEAD = 600
TOKENS_OUTPUT_PER_NEWS = 25


class BalanceError(RuntimeError):
    """查询余额失败。"""


def fetch_balance(api_key: str, timeout: int = 15) -> dict[str, Any]:
    """查询 DeepSeek 账户余额，返回 {currency, total, granted, topped_up, available}。"""
    key = (api_key or "").strip()
    if not key:
        raise BalanceError("未配置 API Key")
    request = urllib.request.Request(
        BALANCE_URL, headers={"Authorization": f"Bearer {key}"}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise BalanceError("API Key 无效或已过期") from error
        raise BalanceError(f"查询失败 HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise BalanceError(f"网络错误: {error.reason}") from error
    except OSError as error:
        raise BalanceError(f"网络错误: {error}") from error

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise BalanceError("返回内容格式异常") from error

    infos = data.get("balance_infos") or []
    if not isinstance(infos, list) or not infos:
        raise BalanceError("未返回余额信息")
    info = infos[0] if isinstance(infos[0], dict) else {}
    return {
        "available": bool(data.get("is_available")),
        "currency": info.get("currency", "CNY"),
        "total": float(info.get("total_balance", 0) or 0),
        "granted": float(info.get("granted_balance", 0) or 0),
        "topped_up": float(info.get("topped_up_balance", 0) or 0),
    }


def count_ai_processed_news(project_root: Path, day: str | None = None) -> int:
    """统计当天已被 AI 筛选处理过的新闻条数（用于估算消耗）。"""
    news_dir = Path(project_root) / "output" / "news"
    if not news_dir.is_dir():
        return 0
    if day:
        candidates = [news_dir / f"{day}.db"]
    else:
        candidates = sorted(news_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[:1]
    total = 0
    for db_path in candidates:
        if not db_path.is_file():
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM ai_filter_analyzed_news")
                total += int(cur.fetchone()[0])
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            continue
    return total


def estimate_run_cost(news_count: int) -> dict[str, float]:
    """按新闻条数估算单次 AI 筛选的 token 与费用。"""
    if news_count <= 0:
        return {"tokens_in": 0.0, "tokens_out": 0.0, "cost": 0.0}
    tokens_in = news_count * (TOKENS_PER_TITLE + 20) + TOKENS_PROMPT_OVERHEAD * 4
    tokens_out = news_count * TOKENS_OUTPUT_PER_NEWS
    cost = tokens_in / 1_000_000 * PRICE_INPUT_PER_M + tokens_out / 1_000_000 * PRICE_OUTPUT_PER_M
    return {"tokens_in": tokens_in, "tokens_out": tokens_out, "cost": cost}


def estimate_daily_cost(news_count: int, interval_minutes: int, runs_per_day: int | None = None) -> float:
    """估算每天费用。newline: 按采集周期算出每天运行次数。"""
    single = estimate_run_cost(news_count)["cost"]
    if runs_per_day is not None:
        runs = max(0, runs_per_day)
    else:
        runs = 1440 / interval_minutes if interval_minutes > 0 else 0
    return single * runs


def format_money(value: float) -> str:
    return f"{value:.2f} 元"
