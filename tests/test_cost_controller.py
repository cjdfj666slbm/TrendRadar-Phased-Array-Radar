"""费用控制模块的测试：不联网部分。"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import cost_controller as cc  # noqa: E402


class CostControllerTests(unittest.TestCase):
    def test_estimate_scales_with_news_count(self):
        small = cc.estimate_run_cost(100)
        large = cc.estimate_run_cost(400)
        self.assertGreater(large["cost"], small["cost"])
        self.assertGreater(large["tokens_out"], small["tokens_out"])
        # 输出 token 与条数严格成正比
        self.assertAlmostEqual(large["tokens_out"], small["tokens_out"] * 4, places=2)
        # 输入的固定开销使总成本略低于 4 倍
        self.assertLess(large["cost"], small["cost"] * 4)

    def test_zero_news_costs_nothing(self):
        self.assertEqual(cc.estimate_run_cost(0)["cost"], 0.0)
        self.assertEqual(cc.estimate_run_cost(-5)["cost"], 0.0)

    def test_daily_cost_respects_interval(self):
        # 周期越长，每天次数越少，花费越低
        hourly = cc.estimate_daily_cost(200, 60)
        six_hourly = cc.estimate_daily_cost(200, 360)
        self.assertAlmostEqual(hourly, six_hourly * 6, places=6)
        self.assertEqual(cc.estimate_daily_cost(200, 0), 0.0)

    def test_count_ai_processed_news_reads_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            news = root / "output" / "news"
            news.mkdir(parents=True)
            db = news / "2026-10-29.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE ai_filter_analyzed_news (id INTEGER)")
            conn.executemany("INSERT INTO ai_filter_analyzed_news VALUES (?)", [(i,) for i in range(7)])
            conn.commit()
            conn.close()
            self.assertEqual(cc.count_ai_processed_news(root), 7)

    def test_count_returns_zero_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cc.count_ai_processed_news(Path(tmp)), 0)

    def test_fetch_balance_rejects_empty_key(self):
        with self.assertRaises(cc.BalanceError):
            cc.fetch_balance("")

    def test_format_money(self):
        self.assertEqual(cc.format_money(8.6), "8.60 元")


if __name__ == "__main__":
    unittest.main()
