"""0.32.47: relatório da carteira em estudo + prompt para o ChatGPT (só texto, nada muda no robô)."""
from app.study_ai import PROMPT, ai_text, wallet_block

W = "Est1".ljust(44, "1")


def test_report_has_wallet_numbers_links_and_prompt():
    prof = {"main": {"source": "Solana Tracker", "closed": 12, "win_rate": 0.58, "hold_med_s": 420, "pnl_24h": 1.2, "pnl_7d": 5.5,
                     "per_day_7d": 0.8, "unit": "SOL"},
            "digest": {"unit": "SOL", "score": 71, "n_acertos": 7, "n_erros": 5, "ganho": 6.0, "perda": 0.5, "pump_pct": 90,
                       "acertos": [{"mint": "Tok1".ljust(40, "1") + "pump", "symbol": "TK1", "realized": 2.5}], "erros": []},
            "recent": [{"at": "2026-10-29T08:00:00+00:00", "side": "buy", "sol": 1.5, "mint": "Tok1".ljust(40, "1") + "pump",
                        "mcap_sol": 45, "signature": "SIG1"}], "trades_seen": 30}
    b = wallet_block(W, "baleia", prof, {"age_days": 40, "txs": 900, "usd": 12000, "criados": 0}, {"trades": 3, "pnl_sol": 0.02})
    assert W in b and "solscan.io/account/" + W in b and "baleia" in b and "TK1" in b and "SIG1" in b and "58%" in b
    txt = ai_text([b])
    assert PROMPT in txt and "NÃO CONFIRMADO" in txt and txt.index(PROMPT) < txt.index(W)
