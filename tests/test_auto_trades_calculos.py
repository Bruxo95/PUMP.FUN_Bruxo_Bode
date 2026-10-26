"""Cálculos do registro automático: sem rede e executáveis com Python padrão."""
import copy
import json
import unittest
from datetime import datetime, timezone

from app.auto_trades import api_item, observe_after, operation_row, readiness, summary


NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc).timestamp()


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def closed_row(index=0, pnl=0.01, real=False):
    at = NOW - (index % 7) * 86400 - 1800
    return {"id": str(index), "mint": "Token", "origem": "explorar", "real": real,
            "entrada_em": stamp(at), "saida_em": stamp(at + 900), "pnl_sol": pnl,
            "pnl_pct": pnl * 2000 if pnl is not None else None, "sol_in": 0.05,
            "info": {"exit_t": at + 900, "exit_price": 2.0},
            "depois": {}}


class AutomaticRecordsTests(unittest.TestCase):
    def test_entry_and_exit_share_id_and_preserve_existing_followup(self):
        position = {"id": 7, "mint": "Token", "symbol": "TOK", "origem": "explorar", "auto": True,
                    "open_t": NOW - 100, "sol_in": 0.0505, "price_in": 1.0, "tokens_left": 0.02,
                    "proceeds": 0.0, "auto_info": {"veredito": "chance alta", "chance": None, "pressure": 65}}
        opened = operation_row(position)
        self.assertEqual(opened["id"], "7")
        self.assertEqual(opened["entrada_em"], stamp(NOW - 100))
        self.assertIsNone(opened["chance"])
        self.assertIsNone(opened["saida_em"])
        opened["depois"] = {"15m": 20.0}
        trade = {**position, "closed_t": NOW, "price_out": 2.0, "pnl_sol": 0.02,
                 "pnl_pct": 40, "reason": "alvo", "best_pct": 42, "worst_pct": -8}
        finished = operation_row(trade, previous=opened, closed=True)
        self.assertEqual(finished["id"], opened["id"])
        self.assertEqual(finished["saida_em"], stamp(NOW))
        self.assertEqual(finished["depois"], {"15m": 20.0})
        self.assertEqual(finished["info"]["exit_price"], 2.0)
        self.assertEqual(finished["pnl_sol"], 0.02)
        self.assertNotIn("user_id", finished)
        unsafe = operation_row({**position, "auto_info": {"boost": {"amount": float("nan")}}})
        self.assertIsNone(unsafe["info"]["boost"]["amount"])
        json.dumps(unsafe, allow_nan=False)

    def test_summary_uses_only_completed_numeric_results(self):
        rows = [closed_row(1, 0.03), closed_row(2, -0.02), closed_row(3, 0.01),
                {**closed_row(4, 100), "saida_em": None}, closed_row(5, None)]
        stats = summary(rows)
        self.assertEqual(stats["closed"], 3)
        self.assertAlmostEqual(stats["pnl_sol"], 0.02)
        self.assertAlmostEqual(stats["profit_factor"], 2.0)
        self.assertAlmostEqual(stats["win_rate"], 2 / 3)
        self.assertFalse(stats["profit_factor_unbounded"])

    def test_no_losses_is_distinct_from_no_operations(self):
        empty = summary([])
        wins = summary([closed_row(1)])
        self.assertIsNone(empty["profit_factor"])
        self.assertFalse(empty["profit_factor_unbounded"])
        self.assertIsNone(wins["profit_factor"])
        self.assertTrue(wins["profit_factor_unbounded"])

    def test_real_readiness_requires_all_thresholds_and_only_simulated_results(self):
        rows = [closed_row(i, 0.02 if i < 45 else -0.01) for i in range(100)]
        # Acerto de 45% e fator de lucro > 1,3, em sete dias de operações.
        result = readiness(rows)
        self.assertTrue(result["recommended"])
        self.assertEqual(result["closed_sim"], 100)
        self.assertEqual(result["days_sim"], 7)
        self.assertFalse(readiness(rows[:99])["recommended"])
        one_day = [{**r, "entrada_em": stamp(NOW - 1800)} for r in rows]
        self.assertFalse(readiness(one_day)["recommended"])
        low_pf = [closed_row(i, 0.005 if i < 45 else -0.01) for i in range(100)]
        self.assertFalse(readiness(low_pf)["recommended"])
        real = [closed_row(i, 1000, real=True) for i in range(120)]
        self.assertFalse(readiness(real)["recommended"])
        invalid = [{**closed_row(i, 1), "pnl_sol": None} for i in range(7)]
        self.assertEqual(readiness(invalid)["days_sim"], 0)

    def test_followups_need_fresh_prices_at_each_deadline(self):
        row = closed_row()
        row["saida_em"] = stamp(NOW)
        row["info"] = {"exit_t": NOW, "exit_price": 2.0}
        rows = {"0": row}
        self.assertEqual(observe_after(rows, {"Token": {"price": 3.0, "last_t": NOW + 899}}, NOW + 900), set())
        self.assertNotIn("15m", row["depois"])
        self.assertEqual(observe_after(rows, {"Token": {"price": 3.0, "last_t": NOW + 901}}, NOW + 901), {"0"})
        self.assertEqual(row["depois"]["15m"], 50.0)
        observe_after(rows, {"Token": {"price": 1.0, "last_t": NOW + 3600}}, NOW + 3600)
        self.assertEqual(row["depois"]["60m"], -50.0)

    def test_missed_fifteen_minute_photo_is_not_reconstructed_at_sixty_minutes(self):
        row = closed_row()
        row["saida_em"] = stamp(NOW)
        row["info"] = {"exit_t": NOW, "exit_price": 2.0}
        rows = {"0": row}
        observe_after(rows, {"Token": {"price": 3.0, "last_t": NOW + 3600}}, NOW + 3600)
        self.assertIsNone(row["depois"]["15m"])
        self.assertEqual(row["depois"]["60m"], 50.0)

    def test_api_item_does_not_expose_user_id_or_modify_stored_record(self):
        row = {**closed_row(), "user_id": "private-account"}
        before = copy.deepcopy(row)
        item = api_item(row, NOW)
        self.assertNotIn("user_id", item)
        self.assertFalse(item["open"])
        self.assertEqual(item["duration_s"], 900)
        self.assertEqual(row, before)


if __name__ == "__main__":
    unittest.main()
