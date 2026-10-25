"""Regra "só copiar traders online": a cada 10 min quem ficou inativo sai e entra o melhor do top que estiver
online. Sem internet."""
import time
from collections import deque

from tests.test_pump import _pump


def _lb(n):
    return [{"wallet": f"T{i}".ljust(44, "1"), "eligible": True, "rank": i + 1, "winrate": 70.0, "trades": 2000}
            for i in range(n)]


def _online(pf, w, ago_s=0):
    pf.activity[w] = {"last": time.time() - ago_s, "n": deque(), "pn": deque(), "pump": 1, "other": 0}


def test_only_online_traders_are_copied_best_first(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_only_online=True, pump_online_min=10, pump_top_n=2)
    pf.leaderboard = _lb(5)
    pf.refresh_followed(force=True)
    assert pf.followed == []                                   # ninguém negociou: não copia ninguém
    L = [r["wallet"] for r in pf.leaderboard]
    _online(pf, L[3])
    _online(pf, L[1], ago_s=60)
    _online(pf, L[0], ago_s=3600)                              # o nº 1 está inativo há 1 h
    pf.refresh_followed(force=True)
    assert pf.followed == [L[1], L[3]]                         # melhores do top que estão online, na ordem


def test_inactive_leaves_and_best_online_enters(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_only_online=True, pump_online_min=10, pump_top_n=2, pump_rank_every_s=600)
    pf.leaderboard = _lb(4)
    L = [r["wallet"] for r in pf.leaderboard]
    for w in L:
        _online(pf, w)
    pf.refresh_followed(force=True)
    assert pf.followed == [L[0], L[1]]
    pf.activity[L[0]]["last"] = time.time() - 11 * 60          # o nº 1 parou há 11 min
    pf.refresh_followed()                                      # ainda dentro dos 10 min da última consulta
    assert pf.followed == [L[0], L[1]]
    pf._rank_at = time.time() - 601                            # passaram os 10 min
    pf.refresh_followed()
    assert pf.followed == [L[1], L[2]]
    msg = pf.events[-1]["msg"]
    assert "entrou" in msg and "saiu" in msg and "inativo" in msg


def test_manual_wallet_stays_even_if_inactive(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_only_online=True, pump_top_n=3)
    man = "Manuat".ljust(44, "1")
    pf.add_manual(man)
    pf.leaderboard = _lb(3)
    L = [r["wallet"] for r in pf.leaderboard]
    _online(pf, L[2])
    pf.refresh_followed(force=True)
    assert pf.followed == [man, L[2]]                          # manual fica mesmo sem atividade


def test_leaderboard_last_trade_counts_after_restart(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_only_online=True, pump_online_min=10, pump_top_n=5)
    pf.leaderboard = _lb(3)
    pf.leaderboard[0]["last_trade"] = int((time.time() - 120) * 1000)                       # ms, 2 min atrás
    pf.leaderboard[1]["last_trade"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 3600))
    pf.refresh_followed(force=True)
    assert pf.followed == [pf.leaderboard[0]["wallet"]]
    snap_lb = {r["wallet"]: r for r in pf.snapshot()["leaderboard"]}
    assert snap_lb[pf.leaderboard[0]["wallet"]]["online"] and not snap_lb[pf.leaderboard[1]["wallet"]]["online"]


def test_turning_rule_off_restores_original_behavior(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_only_online=False, pump_top_n=2)
    pf.leaderboard = _lb(4)
    pf.refresh_followed(force=True)
    assert pf.followed == [r["wallet"] for r in pf.leaderboard[:2]]
