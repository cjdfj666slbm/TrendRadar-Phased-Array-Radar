# coding=utf-8
"""
AI 客户端模块

基于 LiteLLM 的统一 AI 模型接口
支持 100+ AI 提供商（OpenAI、DeepSeek、Gemini、Claude、国内模型等）
"""

import os
from typing import Any, Dict, List

from litellm import completion

# DeepSeek 官方价格（元 / 百万 tokens），仅用于运行时成本估算提示
_PRICE_INPUT_PER_M = 2.0
_PRICE_CACHED_PER_M = 0.1
_PRICE_OUTPUT_PER_M = 8.0


class AIClient:
    """统一的 AI 客户端（基于 LiteLLM）"""

    # 类级累计统计：analyzer / filter / translator 的实例共享同一份，
    # 保证一次运行的总用量可以汇总（否则三个模块各算各的）
    usage_totals: Dict[str, int] = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
    }

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 AI 客户端

        Args:
            config: AI 配置字典
                - MODEL: 模型标识（格式: provider/model_name）
                - API_KEY: API 密钥
                - API_BASE: API 基础 URL（可选）
                - TEMPERATURE: 采样温度
                - MAX_TOKENS: 最大生成 token 数
                - TIMEOUT: 请求超时时间（秒）
                - NUM_RETRIES: 重试次数（可选）
                - FALLBACK_MODELS: 备用模型列表（可选）
                - EXTRA_PARAMS: 透传给 LiteLLM 的额外参数（可选），如
                  extra_headers、top_p、presence_penalty、stop 等
        """
        self.model = config.get("MODEL", "deepseek/deepseek-chat")
        self.api_key = config.get("API_KEY") or os.environ.get("AI_API_KEY", "")
        self.api_base = config.get("API_BASE", "")
        self.temperature = config.get("TEMPERATURE", 1.0)
        self.max_tokens = config.get("MAX_TOKENS", 5000)
        self.timeout = config.get("TIMEOUT", 120)
        self.num_retries = config.get("NUM_RETRIES", 2)
        self.fallback_models = config.get("FALLBACK_MODELS", [])
        # config.yaml 中 ai.extra_params 的透传参数（如自定义请求头）
        self.extra_params = config.get("EXTRA_PARAMS") or {}
        if not isinstance(self.extra_params, dict):
            print(
                f"[AI] 配置错误: ai.extra_params 应为字典，"
                f"当前为 {type(self.extra_params).__name__}，已忽略"
            )
            self.extra_params = {}

    def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> str:
        """
        调用 AI 模型进行对话

        Args:
            messages: 消息列表，格式: [{"role": "system/user/assistant", "content": "..."}]
            **kwargs: 额外参数，会覆盖默认配置

        Returns:
            str: AI 响应内容

        Raises:
            Exception: API 调用失败时抛出异常
        """
        # 构建请求参数
        params = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "timeout": kwargs.get("timeout", self.timeout),
            "num_retries": kwargs.get("num_retries", self.num_retries),
        }

        # 添加 API Key
        if self.api_key:
            params["api_key"] = self.api_key

        # 添加 API Base（如果配置了）
        if self.api_base:
            params["api_base"] = self.api_base

        # 添加 max_tokens（如果配置了且不为 0）
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = max_tokens

        # 添加 fallback 模型（如果配置了）
        if self.fallback_models:
            params["fallbacks"] = self.fallback_models

        # 合并配置文件中的 extra_params（如自定义请求头 extra_headers），
        # 再用调用方 kwargs 覆盖；两者均不覆盖上方已确定的核心参数，
        # 因此未配置 extra_params 时行为与原先完全一致
        for key, value in {**self.extra_params, **kwargs}.items():
            if key not in params:
                params[key] = value

        # 调用 LiteLLM
        response = completion(**params)

        # 记录 token 用量与估算成本（运行时在日志里可见）
        self._record_usage(response)

        # 提取响应内容
        # 某些模型/提供商返回 list（内容块）而非 str，统一转为 str
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", str(item)) if isinstance(item, dict) else str(item)
                for item in content
            )
        return content or ""

    @staticmethod
    def _estimate_cost(prompt: int, completion: int, cached: int) -> float:
        """按 DeepSeek 官方价格估算费用（元）。"""
        uncached = max(0, prompt - cached)
        return (
            uncached / 1_000_000 * _PRICE_INPUT_PER_M
            + cached / 1_000_000 * _PRICE_CACHED_PER_M
            + completion / 1_000_000 * _PRICE_OUTPUT_PER_M
        )

    def _record_usage(self, response: Any) -> None:
        """读取本次调用的 token 用量，累计并打印到日志。

        TrendRadar 默认丢弃了 API 返回的 usage 字段，导致运行时看不到
        token 消耗；这里补上，便于在管理器日志/终端里核对实际花费。
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = int(getattr(details, "cached_tokens", 0) or 0)

        totals = AIClient.usage_totals
        totals["calls"] += 1
        totals["prompt_tokens"] += prompt
        totals["completion_tokens"] += completion
        totals["cached_tokens"] += cached
        totals["total_tokens"] += total

        call_cost = self._estimate_cost(prompt, completion, cached)
        total_cost = self._estimate_cost(
            totals["prompt_tokens"], totals["completion_tokens"], totals["cached_tokens"]
        )
        print(
            f"[AI 用量] 本次：输入 {prompt} + 输出 {completion} = {total} tokens"
            f"（缓存命中 {cached}）≈ ¥{call_cost:.4f}｜"
            f"累计：{totals['calls']} 次调用 {totals['total_tokens']} tokens ≈ ¥{total_cost:.4f}"
        )

    @classmethod
    def usage_summary(cls) -> str:
        """返回本次进程的总用量摘要（供运行结束时打印）。"""
        totals = cls.usage_totals
        if totals["calls"] == 0:
            return "本次运行没有调用 AI（可能未启用 AI 功能）"
        cost = cls._estimate_cost(
            totals["prompt_tokens"], totals["completion_tokens"], totals["cached_tokens"]
        )
        return (
            f"本次运行共 {totals['calls']} 次 AI 调用："
            f"输入 {totals['prompt_tokens']} / 输出 {totals['completion_tokens']} tokens"
            f"（缓存命中 {totals['cached_tokens']}），估算花费 ¥{cost:.4f}"
        )

    def validate_config(self) -> tuple[bool, str]:
        """
        验证配置是否有效

        Returns:
            tuple: (是否有效, 错误信息)
        """
        if not self.model:
            return False, "未配置 AI 模型（model）"

        if not self.api_key:
            return False, "未配置 AI API Key，请在 config.yaml 或环境变量 AI_API_KEY 中设置"

        # 验证模型格式（应该包含 provider/model）
        if "/" not in self.model:
            return False, f"模型格式错误: {self.model}，应为 'provider/model' 格式（如 'deepseek/deepseek-chat'）"

        return True, ""
