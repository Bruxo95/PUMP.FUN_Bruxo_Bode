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

    def seed_wave(self, radar, mint, entries, sol=1.0):
        for wallet, age in entries:
            self.assertTrue(radar.record(wallet, trade(f"{mint}:{wallet}:{age}", mint=mint,
                                                      at=NOW - age, sol=sol), now=NOW))

    def test_hot_callout_explains_recent_distinct_entries_in_the_existing_wave(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 90), (W2, 20)])
        snap = self.snap(radar)
        self.assertEqual(snap["callout_policy"], {
            "entry_window_s": 120, "last_buy_max_age_s": 60, "stale_after_s": 180,
            "min_buy_pressure_pct": 80, "min_wallets": 2, "entry_memory_s": 1800,
            "order": ["hot", "selling", "watch", "stale", "incomplete"]})
        self.assertEqual(len(snap["waves"]), 1)
        wave = snap["waves"][0]
        callout = wave["callout"]
        self.assertEqual(wave["mint"], M1)
        self.assertEqual(callout["state"], "hot")
        self.assertEqual(callout["label"], "HOT")
        self.assertEqual(callout["recent_wallets"], 2)
        self.assertEqual(callout["last_buy_age_s"], 20)
        self.assertEqual(callout["convergence_span_s"], 70)
        self.assertEqual(callout["rank"], 1)
        self.assertTrue(all(isinstance(reason, str) and reason for reason in callout["reasons"]))
        self.assertTrue(any("120" in reason for reason in callout["reasons"]))

    def test_callout_time_boundaries_use_exact_entry_and_last_buy_times(self):
        cases = [(120, 60, "hot"), (120.001, 60, "watch"),
                 (120, 60.001, "watch"), (200, 180, "watch"), (200, 180.001, "stale")]
        for first_age, second_age, expected in cases:
            with self.subTest(first_age=first_age, second_age=second_age):
                radar = self.make_buffer()
                self.seed_wave(radar, M1, [(W1, first_age), (W2, second_age)])
                self.assertEqual(self.snap(radar)["waves"][0]["callout"]["state"], expected)

    def test_repeat_buy_cannot_reheat_an_old_group_or_count_as_a_new_wallet(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 150), (W2, 140)])
        radar.record(W1, trade("repeat-now", at=NOW - 1), now=NOW)
        radar.record(W1, trade("repeat-again", at=NOW), now=NOW)
        wave = self.snap(radar)["waves"][0]
        self.assertEqual(wave["buy_count"], 4)
        self.assertEqual(wave["wallet_count"], 2)
        self.assertEqual(wave["callout"]["recent_wallets"], 0)
        self.assertEqual(wave["callout"]["last_buy_age_s"], 0)
        self.assertEqual(wave["callout"]["state"], "watch")

    def test_repeats_do_not_become_new_entries_when_initial_buys_leave_the_visible_window(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 302), (W2, 301)])
        radar.record(W1, trade("repeat-outside-window-a", at=NOW - 10), now=NOW)
        radar.record(W2, trade("repeat-outside-window-b", at=NOW - 5), now=NOW)
        snap = self.snap(radar)
        wave = snap["waves"][0]
        self.assertFalse(snap["truncated"])
        self.assertEqual(snap["event_count"], 2)
        # Números da onda continuam restritos aos cinco minutos selecionados.
        self.assertEqual(wave["buy_count"], 2)
        self.assertEqual(wave["first_buy"], NOW - 10)
        self.assertEqual(wave["callout"]["convergence_span_s"], 5)
        # O destaque lembra as primeiras entradas retidas, anteriores à janela.
        self.assertEqual(wave["callout"]["recent_wallets"], 0)
        self.assertEqual(wave["callout"]["state"], "watch")

    def test_losing_entry_anchors_before_the_visible_window_marks_the_callout_incomplete(self):
        radar = self.make_buffer(max_events=2)
        self.seed_wave(radar, M1, [(W1, 302), (W2, 301)])
        radar.record(W1, trade("anchor-evicted-a", at=NOW - 10), now=NOW)
        radar.record(W2, trade("anchor-evicted-b", at=NOW - 5), now=NOW)
        snap = self.snap(radar)
        self.assertEqual(snap["event_count"], 2)
        self.assertTrue(snap["truncated"])
        self.assertEqual(snap["waves"][0]["callout"]["state"], "incomplete")
        self.assertTrue(any("limite" in reason.lower() for reason in snap["waves"][0]["callout"]["reasons"]))

    def test_anchor_expiration_uses_trade_time_even_when_the_old_events_arrived_recently(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 1790), (W2, 1780)])
        later = NOW + 40
        # As operações antigas chegaram há 40 s, mas ocorreram há mais de 30 min.
        radar.record(W1, trade("after-memory-a", at=later - 5), now=later)
        radar.record(W2, trade("after-memory-b", at=later), now=later)
        snap = radar.snapshot((W1, W2), now=later)
        self.assertEqual(snap["event_count"], 2)
        self.assertFalse(snap["truncated"])
        self.assertEqual(snap["waves"][0]["callout"]["recent_wallets"], 2)
        self.assertEqual(snap["waves"][0]["callout"]["state"], "hot")

    def test_participant_sale_prevents_hot_even_with_overwhelming_buy_volume(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 30), (W2, 20)], sol=100)
        radar.record(W1, trade("small-sale", side="sell", sol=0.01, at=NOW - 1), now=NOW)
        wave = self.snap(radar)["waves"][0]
        self.assertGreater(wave["buy_pressure"], 99)
        self.assertEqual(wave["callout"]["state"], "selling")
        self.assertTrue(any("vender" in reason for reason in wave["callout"]["reasons"]))
        incomplete = self.snap(radar, connected=False)["waves"][0]["callout"]
        self.assertEqual(incomplete["state"], "incomplete")
        self.assertTrue(any("desconectado" in reason for reason in incomplete["reasons"]))
        self.assertTrue(any("vender" in reason for reason in incomplete["reasons"]))

    def test_missing_volume_is_observation_without_a_hot_badge(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 30), (W2, 20)], sol=0)
        wave = self.snap(radar)["waves"][0]
        self.assertIsNone(wave["buy_pressure"])
        self.assertEqual(wave["callout"]["state"], "watch")
        self.assertTrue(any("sem volume" in reason for reason in wave["callout"]["reasons"]))

    def test_incomplete_buffer_never_promotes_remaining_events_to_hot(self):
        radar = self.make_buffer(max_events=2)
        self.seed_wave(radar, M1, [(W1, 30), (W2, 20)])
        radar.record(W1, trade("overflow", at=NOW - 1), now=NOW)
        snap = self.snap(radar)
        self.assertTrue(snap["truncated"])
        self.assertEqual(snap["waves"][0]["callout"]["recent_wallets"], 2)
        self.assertEqual(snap["waves"][0]["callout"]["state"], "incomplete")
        self.assertTrue(any("limite" in reason.lower() for reason in snap["waves"][0]["callout"]["reasons"]))

    def test_other_users_dropped_event_does_not_mark_this_users_callout_incomplete(self):
        radar = self.make_buffer(max_events=3)
        radar.record(W3, trade("other-account", mint=M2), now=NOW)
        self.seed_wave(radar, M1, [(W1, 30), (W2, 20)])
        radar.record(W1, trade("fresh", at=NOW - 1), now=NOW)
        snap = self.snap(radar, wallets=(W1, W2))
        self.assertFalse(snap["truncated"])
        self.assertEqual(snap["waves"][0]["callout"]["state"], "hot")

    def test_hot_requires_the_configured_number_of_recent_wallets_after_user_filtering(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 200), (W2, 20), (W3, 10)])
        strict = self.snap(radar, min_wallets=3)
        self.assertEqual(strict["callout_policy"]["min_wallets"], 3)
        self.assertEqual(strict["waves"][0]["wallet_count"], 3)
        self.assertEqual(strict["waves"][0]["callout"]["recent_wallets"], 2)
        self.assertEqual(strict["waves"][0]["callout"]["state"], "watch")
        self.assertEqual(self.snap(radar)["waves"][0]["callout"]["state"], "hot")
        mine = self.snap(radar, wallets=(W1, W2))
        self.assertEqual(mine["waves"][0]["callout"]["recent_wallets"], 1)
        self.assertEqual(mine["waves"][0]["callout"]["state"], "watch")

    def test_callout_ranking_prioritizes_state_and_distinct_entries_over_the_latest_repeat(self):
        radar = self.make_buffer()
        strong, sale, watch, stale = (c * 40 + "pump" for c in "FGHJ")
        self.seed_wave(radar, strong, [(W1, 50), (W2, 45), (W3, 40)])
        self.seed_wave(radar, M1, [(W1, 10), (W2, 5)])
        self.seed_wave(radar, sale, [(W1, 30), (W2, 20)])
        radar.record(W1, trade("rank-sale", mint=sale, side="sell", at=NOW - 1), now=NOW)
        self.seed_wave(radar, watch, [(W1, 150), (W2, 140)])
        radar.record(W1, trade("newest-repeat", mint=watch, at=NOW), now=NOW)
        self.seed_wave(radar, stale, [(W1, 250), (W2, 200)])
        waves = self.snap(radar)["waves"]
        self.assertEqual([wave["mint"] for wave in waves], [strong, M1, sale, watch, stale])
        self.assertEqual([wave["callout"]["state"] for wave in waves], ["hot", "hot", "selling", "watch", "stale"])
        self.assertEqual([wave["callout"]["rank"] for wave in waves], [1, 2, 3, 4, 5])

    def test_wave_limit_is_applied_after_ordering_all_calculated_callouts(self):
        radar = self.make_buffer()
        for i in range(100):
            mint = f"Other{i:03d}".ljust(40, "1") + "pump"
            self.seed_wave(radar, mint, [(W1, 250), (W2, 240)])
            radar.record(W1, trade(f"repeat-{i}", mint=mint, at=NOW - 1), now=NOW)
        self.seed_wave(radar, M1, [(W1, 50), (W2, 40), (W3, 30)])
        snap = self.snap(radar)
        self.assertTrue(snap["truncated"])
        self.assertEqual(len(snap["waves"]), 100)
        self.assertEqual(snap["waves"][0]["mint"], M1)
        self.assertEqual([wave["callout"]["rank"] for wave in snap["waves"]], list(range(1, 101)))
        self.assertTrue(all(wave["callout"]["state"] == "incomplete" for wave in snap["waves"]))

    def test_getting_a_later_snapshot_cools_the_callout_without_requiring_another_trade(self):
        radar = self.make_buffer()
        self.seed_wave(radar, M1, [(W1, 5), (W2, 0)])
        hot = self.snap(radar)
        warm = radar.snapshot((W1, W2), now=NOW + 61)
        stale = radar.snapshot((W1, W2), now=NOW + 181)
        self.assertEqual([result["waves"][0]["callout"]["state"] for result in (hot, warm, stale)],
                         ["hot", "watch", "stale"])
        self.assertEqual([result["event_count"] for result in (hot, warm, stale)], [2, 2, 2])


if __name__ == "__main__":
    unittest.main()
