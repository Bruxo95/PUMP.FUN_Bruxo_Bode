"""Radar: agregação e limites sem rede nem dependências externas.

Também pode rodar com Python padrão: python -B -m unittest tests.test_radar -v.
"""
import math
import unittest

from app.radar import RadarBuffer


NOW = 2_000_000_000.0
W1, W2, W3 = ("A" * 44, "B" * 44, "C" * 44)
M1, M2 = "D" * 40 + "pump", "E" * 40 + "pump"


def trade(signature, mint=M1, side="buy", sol=1.0, at=NOW - 10):
    return {"signature": signature, "mint": mint, "txType": side,
            "solAmount": sol, "tokenAmount": 100.0, "blockTime": at}


class RadarTests(unittest.TestCase):
    def make_buffer(self, **kwargs):
        return RadarBuffer(now=NOW - 100, **kwargs)

    def snap(self, radar, wallets=(W1, W2, W3), **kwargs):
        return radar.snapshot(wallets, now=NOW, **kwargs)

    def test_distinct_wallets_same_token_and_duplicate_delivery(self):
        radar = self.make_buffer()
        self.assertTrue(radar.record(W1, trade("a"), now=NOW))
        self.assertFalse(radar.record(W1, trade("a"), now=NOW))
        radar.record(W1, trade("b"), now=NOW)
        self.assertEqual(self.snap(radar)["waves"], [])
        radar.record(W2, trade("a", sol=2.0), now=NOW)
        wave = self.snap(radar)["waves"][0]
        self.assertEqual(wave["mint"], M1)
        self.assertEqual(wave["wallet_count"], 2)
        self.assertEqual(wave["buy_count"], 3)
        self.assertAlmostEqual(wave["buy_sol"], 4.0)
        self.assertEqual(wave["status"], "accumulating")
        self.assertEqual(wave["buy_pressure"], 100.0)

    def test_separate_tokens_threshold_and_user_wallet_filter(self):
        radar = self.make_buffer()
        radar.record(W1, trade("a"), now=NOW)
        radar.record(W2, trade("b", mint=M2), now=NOW)
        self.assertEqual(self.snap(radar)["waves"], [])
        radar.record(W2, trade("c"), now=NOW)
        self.assertEqual(len(self.snap(radar)["waves"]), 1)
        self.assertEqual(self.snap(radar, min_wallets=3)["waves"], [])
        private = self.snap(radar, wallets=(W1, W3))
        self.assertEqual(private["waves"], [])
        self.assertEqual(private["event_count"], 1)

    def test_expiration_uses_trade_time_not_received_time(self):
        radar = self.make_buffer()
        radar.record(W1, trade("old", at=NOW - 301), now=NOW)
        radar.record(W2, trade("fresh"), now=NOW)
        self.assertEqual(self.snap(radar, window_min=5)["waves"], [])
        self.assertEqual(len(self.snap(radar, window_min=6)["waves"]), 1)
        self.assertEqual(radar.snapshot((W1, W2), now=NOW + 400, window_min=5)["waves"], [])

    def test_participant_sale_after_buy_warns_but_unrelated_sale_does_not(self):
        radar = self.make_buffer()
        radar.record(W1, trade("old-sell", side="sell", at=NOW - 30), now=NOW)
        radar.record(W1, trade("a", at=NOW - 20), now=NOW)
        radar.record(W2, trade("b", at=NOW - 19), now=NOW)
        radar.record(W3, trade("unrelated", side="sell", at=NOW - 5), now=NOW)
        wave = self.snap(radar)["waves"][0]
        self.assertEqual(wave["status"], "accumulating")
        self.assertEqual(wave["seller_count"], 0)
        radar.record(W1, trade("sale", side="sell", sol=0.5, at=NOW - 1), now=NOW)
        wave = self.snap(radar)["waves"][0]
        self.assertEqual(wave["status"], "selling")
        self.assertEqual(wave["seller_count"], 1)
        self.assertEqual(wave["sell_count"], 1)
        self.assertAlmostEqual(wave["sell_sol"], 0.5)
        self.assertAlmostEqual(wave["net_sol"], 1.5)
        self.assertAlmostEqual(wave["buy_pressure"], 80.0)

    def test_bad_events_do_not_create_waves_or_poison_numeric_output(self):
        radar = self.make_buffer()
        invalid = [trade("future", at=NOW + 600), trade("nan", at=math.nan),
                   trade("inf", sol=math.inf), trade("negative", sol=-1),
                   trade("side", side="create"), {**trade("mint"), "mint": ""},
                   {**trade("signature"), "signature": ""}]
        for event in invalid:
            with self.subTest(event=event["signature"]):
                self.assertFalse(radar.record(W1, event, now=NOW))
        self.assertEqual(self.snap(radar)["event_count"], 0)
        self.assertEqual(self.snap(radar)["waves"], [])

    def test_sale_observed_before_buy_in_same_block_second_is_not_an_exit(self):
        radar = self.make_buffer()
        radar.record(W1, trade("sale-before", side="sell"), now=NOW)
        radar.record(W1, trade("buy-a"), now=NOW)
        radar.record(W2, trade("buy-b"), now=NOW)
        wave = self.snap(radar)["waves"][0]
        self.assertEqual(wave["seller_count"], 0)
        self.assertEqual(wave["status"], "accumulating")

    def test_removing_wallet_immediately_removes_its_participation(self):
        radar = self.make_buffer()
        radar.record(W1, trade("a"), now=NOW)
        radar.record(W2, trade("b"), now=NOW)
        self.assertEqual(len(self.snap(radar)["waves"]), 1)
        removed = self.snap(radar, wallets=(W1,))
        self.assertEqual(removed["waves"], [])
        self.assertEqual(removed["event_count"], 1)

    def test_memory_overflow_is_disclosed(self):
        radar = self.make_buffer(max_events=3)
        for i in range(8):
            radar.record(W1 if i % 2 else W2, trade(str(i), at=NOW - 8 + i), now=NOW)
        snap = self.snap(radar)
        self.assertLessEqual(snap["event_count"], 3)
        self.assertTrue(snap["truncated"])


if __name__ == "__main__":
    unittest.main()
