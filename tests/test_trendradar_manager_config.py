import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
FREQUENCY_MODULE = TOOLS.parent / "trendradar" / "core" / "frequency.py"
FREQUENCY_SPEC = importlib.util.spec_from_file_location("trendradar_frequency", FREQUENCY_MODULE)
frequency_module = importlib.util.module_from_spec(FREQUENCY_SPEC)
FREQUENCY_SPEC.loader.exec_module(frequency_module)

load_frequency_words = frequency_module.load_frequency_words
from trendradar_manager_config import (  # noqa: E402
    AI_FEATURE_FIELDS,
    AI_PROVIDERS,
    INTEREST_PRESETS,
    NEWSNOW_DEFAULT_API_URL,
    WEBHOOK_CHANNELS,
    detect_env_key_conflict,
    get_form_values,
    infer_ai_provider,
    inject_dingtalk_keyword,
    load_ai_features,
    load_ai_interests,
    load_config,
    load_dingtalk_security,
    load_managed_keywords,
    load_source_api_url,
    load_webhook_channels,
    provider_models,
    read_collection_interval,
    redact_secrets,
    save_ai_features,
    save_ai_interests,
    save_collection_interval,
    save_config,
    save_dingtalk_security,
    save_managed_keywords,
    save_source_api_url,
    save_webhook_channels,
    sign_dingtalk_url,
)


class TrendRadarManagerConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.config_path = self.root / "config.yaml"
        self.config_path.write_text(
            "# keep this comment\n"
            "app:\n"
            "  timezone: Asia/Shanghai\n"
            "ai:\n"
            "  model: deepseek/deepseek-v4-flash\n"
            "  api_key: old-secret # do not expose\n"
            "notification:\n"
            "  enabled: false\n"
            "  channels:\n"
            "    feishu:\n"
            "      webhook_url: old-webhook\n"
            "    slack:\n"
            "      webhook_url: keep-this-channel\n",
            encoding="utf-8",
        )
        self.keywords_path = self.root / "frequency_words.txt"
        self.keywords_path.write_text(
            "[GLOBAL_FILTER]\nspam\n\n[WORD_GROUPS]\n\nexisting keyword\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_saves_only_selected_config_and_preserves_comments_and_values(self):
        save_config(
            self.config_path,
            "DeepSeek",
            "https://api.deepseek.com/v1",
            "new-secret",
            "deepseek-chat",
            "Feishu",
            "new-webhook",
        )

        config = load_config(self.config_path)
        self.assertIn("# keep this comment", self.config_path.read_text(encoding="utf-8"))
        self.assertIn("# do not expose", self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["app"]["timezone"], "Asia/Shanghai")
        self.assertEqual(config["ai"]["api_key"], "new-secret")
        self.assertEqual(config["ai"]["provider"], "openai_compatible")
        self.assertEqual(config["ai"]["service_provider"], "DeepSeek")
        self.assertEqual(config["ai"]["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(config["ai"]["api_base"], "https://api.deepseek.com/v1")
        self.assertEqual(config["ai"]["model"], "openai/deepseek-chat")
        self.assertEqual(config["notification"]["channels"]["feishu"]["webhook_url"], "new-webhook")
        self.assertEqual(config["notification"]["channels"]["slack"]["webhook_url"], "keep-this-channel")
        self.assertTrue(config["notification"]["enabled"])
        values = get_form_values(config, "Feishu")
        self.assertEqual(
            values,
            ("DeepSeek", "https://api.deepseek.com/v1", "new-secret", "deepseek-chat", "new-webhook"),
        )

    def test_empty_key_keeps_existing_unless_explicitly_cleared(self):
        save_config(self.config_path, "DeepSeek", "https://api.deepseek.com/v1", "", "deepseek-chat", "Feishu", "")
        self.assertEqual(load_config(self.config_path)["ai"]["api_key"], "old-secret")
        save_config(
            self.config_path,
            "DeepSeek",
            "https://api.deepseek.com/v1",
            "replacement-key",
            "deepseek-chat",
            "Feishu",
            "",
            clear_api_key=True,
        )
        self.assertEqual(load_config(self.config_path)["ai"]["api_key"], "replacement-key")
        save_config(
            self.config_path,
            "DeepSeek",
            "https://api.deepseek.com/v1",
            "",
            "deepseek-chat",
            "Feishu",
            "",
            clear_api_key=True,
        )
        self.assertEqual(load_config(self.config_path)["ai"]["api_key"], "")

    def test_all_ai_providers_save_openai_compatible_settings(self):
        for provider, settings in AI_PROVIDERS.items():
            with self.subTest(provider=provider):
                save_config(
                    self.config_path,
                    provider,
                    settings["base_url"] or "https://custom.example/v1",
                    "platform-key" if provider != "自定义兼容接口" else "",
                    settings["models"][0] if settings["models"] else "custom-model",
                    "Feishu",
                    "",
                    clear_api_key=True,
                )
                config = load_config(self.config_path)["ai"]
                self.assertEqual(config["service_provider"], provider)
                self.assertEqual(config["provider"], "openai_compatible")
                model = settings["models"][0] if settings["models"] else "custom-model"
                base_url = settings["base_url"] or "https://custom.example/v1"
                self.assertEqual(config["model"], f"openai/{model}")
                self.assertEqual(config["api_base"], base_url)
                self.assertEqual(config["base_url"], config["api_base"])
                self.assertEqual(
                    config["api_key"],
                    "platform-key" if provider != "自定义兼容接口" else "",
                )
                values = get_form_values(load_config(self.config_path), "Feishu")
                self.assertEqual(values[0], provider)
                self.assertEqual(values[1], base_url)
                self.assertEqual(values[3], model)

    def test_provider_inference_and_legacy_label_compatibility(self):
        self.assertEqual(
            infer_ai_provider({}, "openai/qwen-turbo", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "阿里云百炼",
        )
        self.assertEqual(infer_ai_provider({"service_provider": "Ollama（本地模型）"}, "", ""), "自定义兼容接口")

    def test_exact_provider_and_model_dropdown_options(self):
        self.assertEqual(
            list(AI_PROVIDERS),
            [
                "火山方舟（豆包）",
                "阿里云百炼",
                "智谱 GLM",
                "Kimi",
                "腾讯混元",
                "DeepSeek",
                "MiniMax",
                "科大讯飞星火",
                "自定义兼容接口",
            ],
        )
        self.assertEqual(len(provider_models("火山方舟（豆包）")), 47)
        self.assertEqual(provider_models("阿里云百炼"), ("qwen-turbo", "qwen-plus", "qwen-max", "qwen3-7b-instruct", "qwen3-14b-instruct", "qwen3-72b-instruct"))
        self.assertEqual(provider_models("智谱 GLM"), ("glm-4-flash", "glm-4", "glm-4-plus", "glm-5"))
        self.assertEqual(provider_models("Kimi"), ("kimi-k2.6", "kimi-k2.7", "kimi-k2.8", "kimi-k3"))
        self.assertEqual(provider_models("腾讯混元"), ("hunyuan-lite", "hunyuan-standard", "hunyuan-pro"))
        self.assertEqual(provider_models("DeepSeek"), ("deepseek-chat", "deepseek-lite", "deepseek-v3", "deepseek-r1"))
        self.assertEqual(provider_models("MiniMax"), ("minimax-m2.5", "minimax-m2.7", "minimax-m3", "minimax-m3.1-flash"))
        self.assertEqual(provider_models("科大讯飞星火"), ("spark-lite", "spark-pro", "spark-max"))
        self.assertEqual(provider_models("自定义兼容接口"), ())
        self.assertEqual(
            {provider: settings["base_url"] for provider, settings in AI_PROVIDERS.items()},
            {
                "火山方舟（豆包）": "https://ark.cn-beijing.volces.com/api/v3",
                "阿里云百炼": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "智谱 GLM": "https://open.bigmodel.cn/api/paas/v4",
                "Kimi": "https://api.moonshot.cn/v1",
                "腾讯混元": "https://api.hunyuan.cloud.tencent.com/v1",
                "DeepSeek": "https://api.deepseek.com/v1",
                "MiniMax": "https://api.minimax.chat/v1",
                "科大讯飞星火": "https://spark-api.xf-yun.com/v4.0",
                "自定义兼容接口": "",
            },
        )

    def test_model_must_belong_to_selected_provider(self):
        with self.assertRaisesRegex(ValueError, "not available"):
            save_config(
                self.config_path,
                "DeepSeek",
                "https://api.deepseek.com/v1",
                "",
                "qwen-plus",
                "Feishu",
                "",
            )

    def test_custom_compatibility_allows_manual_endpoint_and_model(self):
        save_config(
            self.config_path,
            "自定义兼容接口",
            "https://custom.example/v1",
            "custom-key",
            "vendor/custom-model",
            "Feishu",
            "",
        )
        ai = load_config(self.config_path)["ai"]
        self.assertEqual(ai["provider"], "openai_compatible")
        self.assertEqual(ai["base_url"], "https://custom.example/v1")
        self.assertEqual(ai["api_base"], "https://custom.example/v1")
        self.assertEqual(ai["model"], "openai/vendor/custom-model")
        self.assertEqual(
            get_form_values(load_config(self.config_path), "Feishu")[:4],
            ("自定义兼容接口", "https://custom.example/v1", "custom-key", "vendor/custom-model"),
        )

    def test_keyword_updates_replace_only_managed_block(self):
        save_managed_keywords(self.keywords_path, ["first", "second"])
        save_managed_keywords(self.keywords_path, ["replacement"])

        content = self.keywords_path.read_text(encoding="utf-8")
        self.assertIn("[GLOBAL_FILTER]\nspam", content)
        self.assertIn("existing keyword", content)
        self.assertNotIn("\nfirst\n", content)
        self.assertEqual(load_managed_keywords(self.keywords_path), ["replacement"])
        groups, _, global_filters = load_frequency_words(str(self.keywords_path))
        gui_groups = [group for group in groups if group["display_name"] == "TrendRadar GUI"]
        self.assertEqual(len(gui_groups), 1)
        self.assertEqual(gui_groups[0]["group_key"], "replacement")
        self.assertEqual(global_filters[0]["word"], "spam")

    def test_keyword_clear_removes_managed_block(self):
        save_managed_keywords(self.keywords_path, ["tracked"])
        save_managed_keywords(self.keywords_path, [])

        content = self.keywords_path.read_text(encoding="utf-8")
        self.assertNotIn("BEGIN TREND RADAR MANAGER KEYWORDS", content)
        self.assertIn("existing keyword", content)

    def test_interval_storage_and_secret_redaction(self):
        settings = self.root / "manager.json"
        self.assertEqual(read_collection_interval(settings), 60)
        save_collection_interval(settings, 25)
        self.assertEqual(read_collection_interval(settings), 25)
        self.assertEqual(
            redact_secrets("request failed for old-secret and sk-abcdefghijklmnop", ["old-secret"]),
            "request failed for [REDACTED] and [REDACTED]",
        )


    def test_ai_feature_toggles_round_trip_and_preserve_comments(self):
        # 按真实 config.yaml 的结构造一份，含三个 AI 开关所在段
        self.config_path.write_text(
            "# top comment\n"
            "ai:\n"
            "  model: deepseek/deepseek-v4-flash\n"
            "filter:\n"
            "  method: keyword # keep me\n"
            "ai_analysis:\n"
            "  enabled: true\n"
            "ai_translation:\n"
            "  enabled: true\n"
            "platforms:\n"
            "  enabled: true\n"
            "  api_url: ''\n",
            encoding="utf-8",
        )
        config = load_config(self.config_path)
        features = load_ai_features(config)
        self.assertEqual(set(features), set(AI_FEATURE_FIELDS))
        self.assertFalse(features["AI 智能筛选（自然语言兴趣，替代关键词）"])
        self.assertTrue(features["AI 分析（推送附洞察报告）"])

        save_ai_features(
            self.config_path,
            {
                "AI 分析（推送附洞察报告）": False,
                "AI 智能筛选（自然语言兴趣，替代关键词）": True,
                "AI 翻译（推送标题译为目标语言）": False,
            },
        )

        text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("# top comment", text)
        self.assertIn("# keep me", text)
        reloaded = load_config(self.config_path)
        self.assertEqual(reloaded["filter"]["method"], "ai")
        self.assertFalse(reloaded["ai_analysis"]["enabled"])
        self.assertFalse(reloaded["ai_translation"]["enabled"])
        # 未涉及的段保持原样
        self.assertEqual(reloaded["ai"]["model"], "deepseek/deepseek-v4-flash")
        self.assertTrue(reloaded["platforms"]["enabled"])

        # 反向切换回关键词
        save_ai_features(self.config_path, {"AI 智能筛选（自然语言兴趣，替代关键词）": False})
        self.assertEqual(load_config(self.config_path)["filter"]["method"], "keyword")

    def test_ai_feature_toggle_creates_missing_sections(self):
        self.config_path.write_text("ai:\n  model: deepseek/deepseek-v4-flash\n", encoding="utf-8")
        self.assertTrue(load_ai_features(load_config(self.config_path))["AI 分析（推送附洞察报告）"])
        save_ai_features(self.config_path, {"AI 分析（推送附洞察报告）": False})
        config = load_config(self.config_path)
        self.assertFalse(config["ai_analysis"]["enabled"])
        self.assertEqual(config["ai"]["model"], "deepseek/deepseek-v4-flash")

    def test_source_api_url_round_trip_and_validation(self):
        self.config_path.write_text(
            "# comment\nplatforms:\n  enabled: true\n  api_url: ''\n  sources:\n    - id: toutiao\n",
            encoding="utf-8",
        )
        self.assertEqual(load_source_api_url(load_config(self.config_path)), "")
        save_source_api_url(self.config_path, "  https://newsnow.example.com/api/s  ")
        self.assertEqual(
            load_source_api_url(load_config(self.config_path)),
            "https://newsnow.example.com/api/s",
        )
        text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("# comment", text)
        self.assertEqual(load_config(self.config_path)["platforms"]["sources"][0]["id"], "toutiao")

        with self.assertRaisesRegex(ValueError, "http"):
            save_source_api_url(self.config_path, "ftp://bad")
        with self.assertRaisesRegex(ValueError, "http"):
            save_source_api_url(self.config_path, "not-a-url")

        # 留空表示回退内置默认地址
        save_source_api_url(self.config_path, "")
        self.assertEqual(load_source_api_url(load_config(self.config_path)), "")
        self.assertTrue(NEWSNOW_DEFAULT_API_URL.startswith("https://"))

    def test_env_key_conflict_detection(self):
        # 无环境变量时无冲突
        self.assertIsNone(detect_env_key_conflict("sk-config", {}))
        # 环境变量与配置一致时无冲突
        self.assertIsNone(detect_env_key_conflict("sk-same", {"AI_API_KEY": " sk-same "}))
        # 环境变量存在但配置留空 -> 提示覆盖
        message = detect_env_key_conflict("", {"AI_API_KEY": "sk-env"})
        self.assertIsNotNone(message)
        self.assertIn("覆盖", message)
        # 二者不一致 -> 提示以环境变量优先
        message = detect_env_key_conflict("sk-config", {"AI_API_KEY": "sk-env"})
        self.assertIsNotNone(message)
        self.assertIn("环境变量", message)
        # 空白环境变量视为未设置
        self.assertIsNone(detect_env_key_conflict("sk-config", {"AI_API_KEY": "   "}))

    def test_new_writers_keep_crlf_and_bom(self):
        self.config_path.write_bytes(
            "\ufeffplatforms:\r\n  api_url: ''\r\nai_analysis:\r\n  enabled: true\r\n".encode("utf-8")
        )
        save_source_api_url(self.config_path, "https://example.com/api/s")
        save_ai_features(self.config_path, {"AI 分析（推送附洞察报告）": False})
        raw = self.config_path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        decoded = raw.decode("utf-8-sig")
        self.assertNotIn("\n", decoded.replace("\r\n", ""))
        self.assertEqual(load_source_api_url(load_config(self.config_path)), "https://example.com/api/s")
        self.assertFalse(load_config(self.config_path)["ai_analysis"]["enabled"])


    def test_ai_interests_round_trip_preserves_head_and_tail(self):
        interests = self.root / "ai_interests.txt"
        interests.write_text(
            "# header comment\n"
            "# Version: 1.1.0\n"
            "\n"
            "下面是我要关注的内容：\n"
            "1. 旧兴趣内容\n"
            "2. 另一条旧兴趣\n"
            "\n"
            "\n"
            "# 标题质量要求\n"
            "# 可自由增删改\n"
            "- 不要标题党\n"
            "- 不要营销软文\n",
            encoding="utf-8",
        )
        loaded = load_ai_interests(interests)
        self.assertEqual(loaded, "1. 旧兴趣内容\n2. 另一条旧兴趣")
        self.assertNotIn("下面是我要关注", loaded)

        save_ai_interests(interests, "1. AI 芯片\n2. 新能源汽车")
        text = interests.read_text(encoding="utf-8")
        self.assertIn("# Version: 1.1.0", text)
        self.assertIn("# 标题质量要求", text)
        self.assertIn("- 不要标题党", text)
        self.assertIn("- 不要营销软文", text)
        self.assertIn("1. AI 芯片", text)
        self.assertNotIn("旧兴趣内容", text)
        self.assertEqual(load_ai_interests(interests), "1. AI 芯片\n2. 新能源汽车")

        # 反复保存不累积锚点
        save_ai_interests(interests, "3. 第三版")
        save_ai_interests(interests, "4. 第四版")
        final = interests.read_text(encoding="utf-8")
        self.assertEqual(final.count(">>> TrendRadar GUI 兴趣描述"), 1)
        self.assertEqual(final.count("<<< TrendRadar GUI 兴趣描述结束"), 1)
        self.assertIn("4. 第四版", final)
        self.assertNotIn("第三版", final)
        self.assertIn("- 不要营销软文", final)

    def test_ai_interests_creates_missing_file_and_keeps_crlf(self):
        interests = self.root / "nested" / "ai_interests.txt"
        save_ai_interests(interests, "全新兴趣")
        self.assertEqual(load_ai_interests(interests), "全新兴趣")

        crlf = self.root / "crlf.txt"
        crlf.write_bytes("# head\r\n旧内容\r\n".encode("utf-8"))
        save_ai_interests(crlf, "新内容")
        raw = crlf.read_bytes()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn("# head", raw.decode("utf-8"))


    def test_interest_presets_are_wellformed(self):
        self.assertGreaterEqual(len(INTEREST_PRESETS), 4)
        names = [name for name, _desc, _words in INTEREST_PRESETS]
        self.assertEqual(len(names), len(set(names)), "模板名称不能重复")
        all_words: list[str] = []
        for name, desc, words in INTEREST_PRESETS:
            self.assertTrue(name.strip())
            self.assertTrue(desc.strip())
            self.assertGreaterEqual(len(words), 3, f"{name} 条目太少")
            for word in words:
                self.assertTrue(word.strip())
                self.assertNotIn("\n", word)
                self.assertFalse(word.strip().startswith("#"))
            all_words.extend(words)
        # 各模板之间不能有重复条目，否则勾选/取消会互相干扰
        self.assertEqual(len(all_words), len(set(all_words)), "模板之间存在重复条目")

    def test_presets_round_trip_through_interests_file(self):
        interests = self.root / "ai_interests.txt"
        interests.write_bytes(
            "# 注释头\n".encode("utf-8") + b"\n" + b"old body\n"
        )
        picked = []
        for name, _desc, words in INTEREST_PRESETS[:2]:
            picked.append(name)
            picked.extend(words)
        body = "\n".join(picked[1:])
        save_ai_interests(interests, body)
        self.assertEqual(load_ai_interests(interests), body)
        self.assertIn("# 注释头", interests.read_text(encoding="utf-8"))


    def test_webhook_channels_save_multiple_together(self):
        self.config_path.write_text(
            "# keep\nnotification:\n  enabled: false\n  channels:\n    feishu:\n      webhook_url: ''\n    dingtalk:\n      webhook_url: ''\n    slack:\n      webhook_url: keep-slack\n",
            encoding="utf-8",
        )
        config = load_config(self.config_path)
        self.assertEqual(load_webhook_channels(config)["飞书"], "")
        self.assertEqual(load_webhook_channels(config)["Slack"], "keep-slack")

        save_webhook_channels(
            self.config_path,
            {"飞书": "https://open.feishu.cn/hook/A", "钉钉": "https://oapi.dingtalk.com/B"},
        )
        reloaded = load_config(self.config_path)
        self.assertTrue(reloaded["notification"]["enabled"])
        self.assertEqual(reloaded["notification"]["channels"]["feishu"]["webhook_url"], "https://open.feishu.cn/hook/A")
        self.assertEqual(reloaded["notification"]["channels"]["dingtalk"]["webhook_url"], "https://oapi.dingtalk.com/B")
        self.assertEqual(reloaded["notification"]["channels"]["slack"]["webhook_url"], "keep-slack")
        self.assertIn("# keep", self.config_path.read_text(encoding="utf-8"))

        # 全部清空后应关闭通知总开关
        save_webhook_channels(self.config_path, {"飞书": "", "钉钉": ""})
        reloaded = load_config(self.config_path)
        self.assertFalse(reloaded["notification"]["enabled"])
        self.assertEqual(reloaded["notification"]["channels"]["feishu"]["webhook_url"], "")

        with self.assertRaisesRegex(ValueError, "http"):
            save_webhook_channels(self.config_path, {"飞书": "not-a-url"})

    def test_webhook_channel_hints_present(self):
        self.assertIn("飞书", WEBHOOK_CHANNELS)
        self.assertIn("钉钉", WEBHOOK_CHANNELS)
        for label, (section, key, hint) in WEBHOOK_CHANNELS.items():
            self.assertTrue(section)
            self.assertEqual(key, "webhook_url")
            self.assertGreater(len(hint), 20, f"{label} 获取指引过短")


    def test_dingtalk_sign_url_and_keyword_injection(self):
        url = "https://oapi.dingtalk.com/robot/send?access_token=abc"
        # 无密钥时原样返回
        self.assertEqual(sign_dingtalk_url(url, ""), url)
        self.assertEqual(sign_dingtalk_url(url, "   "), url)

        signed = sign_dingtalk_url(url, "SECtest-secret")
        import urllib.parse

        parsed = urllib.parse.urlparse(signed)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["access_token"], ["abc"])
        self.assertIn("timestamp", query)
        self.assertIn("sign", query)
        self.assertTrue(query["timestamp"][0].isdigit())
        self.assertGreater(len(query["sign"][0]), 20)
        # 签名结果依赖时间戳与密钥：换密钥必须得到不同的 sign
        other = sign_dingtalk_url(url, "SECother-secret")
        other_query = urllib.parse.parse_qs(urllib.parse.urlparse(other).query)
        self.assertNotEqual(query["sign"][0], other_query["sign"][0])

        # 关键词注入
        self.assertEqual(inject_dingtalk_keyword("正文", "大闪闪"), "大闪闪\n\n正文")
        self.assertEqual(inject_dingtalk_keyword("大闪闪 正文", "大闪闪"), "大闪闪 正文")
        self.assertEqual(inject_dingtalk_keyword("正文", ""), "正文")

    def test_dingtalk_security_round_trip(self):
        self.config_path.write_text(
            "notification:\n  enabled: true\n  channels:\n    dingtalk:\n      webhook_url: x\n",
            encoding="utf-8",
        )
        secret, keyword = load_dingtalk_security(load_config(self.config_path))
        self.assertEqual(secret, "")
        self.assertEqual(keyword, "TrendRadar")  # 未配置时回退默认关键词

        save_dingtalk_security(self.config_path, "SECabc", "大闪闪")
        secret, keyword = load_dingtalk_security(load_config(self.config_path))
        self.assertEqual(secret, "SECabc")
        self.assertEqual(keyword, "大闪闪")
        # 未影响既有渠道
        self.assertEqual(
            load_config(self.config_path)["notification"]["channels"]["dingtalk"]["webhook_url"], "x"
        )


if __name__ == "__main__":
    unittest.main()
