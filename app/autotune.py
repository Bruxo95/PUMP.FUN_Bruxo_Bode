"""Ajuste automático (0.31.14, pedido do dono em 2026-10-26: "a IA ver e rever os relatórios, já corrigir e melhorar;
ir ganhando mais e ficando mais inteligente").

A cada 6 h, para cada admin com `pump_tune_on` e SÓ com a execução real desligada (as opções valem para as duas
carteiras; com o real ligado o ajuste para e avisa):
1. Saída: as Estratégias fantasma testam, com as mesmas entradas, várias regras de saída. Se uma regra rende mais por
   trade que as suas regras atuais (base mínima de MIN_TRADES fechados e MIN_DAYS dias de fantasmas), ela é aplicada nas
   suas opções. A regra fica "em teste" por EVAL_S e EVAL_TRADES trades: se o resultado por trade piorar em relação
   ao que era antes, volta sozinha às opções anteriores e a regra fica de fora por REJECT_S.
2. Traders: quem deu prejuízo com MIN_COPIES+ cópias e acerto abaixo de 30% nos últimos 7 dias é pausado por 48 h.
3. Explorar e Carteiras em estudo já aprendem sozinhos (app/autolearn.py, app/autostudy.py).
Tudo fica em `auto_tune_log` e aparece em Relatórios → Ajuste automático.
"""
from __future__ import annotations

from .ghosts import params

MIN_TRADES = 30
MIN_DAYS = 2.0
MARGIN_SOL = 0.001               # a regra nova precisa render pelo menos isso a mais por trade
EVAL_S = 48 * 3600
EVAL_TRADES = 15
REJECT_S = 7 * 86400
MIN_COPIES = 5
PAUSE_H = 48
KEYS = ("pump_stop_pct", "pump_trail_enabled", "pump_trail_start_pct", "pump_trail_dist_pct", "pump_tp1_on",
        "pump_tp1_pct", "pump_tp1_frac_pct", "pump_tp_pct", "pump_max_hold_h", "pump_exit_dev_sell",
        "pump_exit_migrate", "pump_exit_stale_on", "pump_exit_stale_min")


def variant_settings(vid: str) -> dict | None:
    """Opções que reproduzem a regra do fantasma. None quando a regra não existe nas opções (ignorar a venda do trader)."""
    p = params(vid)
    if not p.get("follow", True):
        return None
    out = {"pump_stop_pct": p["stop"], "pump_trail_enabled": bool(p["trail"]), "pump_tp1_on": bool(p["tp1"]),
           "pump_tp_pct": p["tp"] or 0.0, "pump_max_hold_h": round(p["max_s"] / 3600, 3),
           "pump_exit_dev_sell": bool(p["dev"]), "pump_exit_migrate": bool(p["migrate"]),
           "pump_exit_stale_on": bool(p["stale"])}
    if p["trail"]:
        out["pump_trail_start_pct"], out["pump_trail_dist_pct"] = p["trail"]
    if p["tp1"]:
        out["pump_tp1_pct"], out["pump_tp1_frac_pct"] = p["tp1"]
    if p["stale"]:
        out["pump_exit_stale_min"] = p["stale"]
    return out


AUTO_KEYS = ("pump_ar_stop_pct", "pump_ar_trail_start", "pump_ar_trail_dist", "pump_ar_tp1_pct", "pump_ar_tp1_frac",
             "pump_ar_tp_pct", "pump_ar_max_hold_min", "pump_ar_press_min", "pump_ar_exit_grad")
AUTO_MIN_TRADES = 20             # automáticas do Explorar: base menor (entram menos que as cópias)


def auto_variant_settings(vid: str) -> dict | None:
    """Opções das automáticas (pump_ar_*) que reproduzem um fantasma das automáticas (0.31.21)."""
    from .ghosts import AUTO_BASE, AUTO_VARIANTS
    if vid not in {v for v, _, _ in AUTO_VARIANTS}:
        return None
    p = params(vid, AUTO_VARIANTS, AUTO_BASE)
    if not p["trail"]:
        return None                               # as automáticas sempre usam stop móvel
    out = {"pump_ar_stop_pct": p["stop"], "pump_ar_trail_start": p["trail"][0], "pump_ar_trail_dist": p["trail"][1],
           "pump_ar_tp1_pct": p["tp1"][0] if p["tp1"] else 0.0, "pump_ar_tp_pct": p["tp"] or 0.0,
           "pump_ar_max_hold_min": round(p["max_s"] / 60, 2), "pump_ar_press_min": p["press"] or 0.0,
           "pump_ar_exit_grad": bool(p["migrate"])}
    if p["tp1"]:
        out["pump_ar_tp1_frac"] = p["tp1"][1]
    return out


def per_trade(rows: list[dict]) -> float | None:
    return sum(r.get("pnl_sol") or 0 for r in rows) / len(rows) if rows else None


def pick_exit(snap: dict, ghosts_days: float, rejected: set, mapper=None, min_trades: int = MIN_TRADES) -> dict | None:
    """A regra de saída que mais rende por trade, se passar a sua com folga e tiver base."""
    mapper = mapper or variant_settings
    yours = snap.get("yours") or {}
    if ghosts_days < MIN_DAYS or (yours.get("trades") or 0) < min_trades:
        return None
    mine = (yours.get("pnl_sol") or 0) / yours["trades"]
    best = None
    for v in snap.get("variants") or []:
        if v["trades"] < min_trades or v["id"] in rejected or mapper(v["id"]) is None:
            continue
        avg = v["pnl_sol"] / v["trades"]
        if avg > 0 and avg >= mine + MARGIN_SOL and (best is None or avg > best["avg"]):
            best = {"id": v["id"], "nome": v["nome"], "avg": round(avg, 6), "trades": v["trades"], "mine_avg": round(mine, 6)}
    return best


def evaluate(change: dict, trades: list[dict], now: float, ts, sel=None) -> tuple[str, str] | None:
    """('manteve' | 'desfez', motivo) quando a regra em teste já tem base; None enquanto ainda testa."""
    t0 = ts(change.get("em")) or now
    sim = [t for t in trades if not t.get("real") and (sel is None or sel(t))]
    after = [t for t in sim if (ts(t.get("closed_at")) or 0) >= t0]
    if now - t0 < EVAL_S or len(after) < EVAL_TRADES:
        return None
    span = now - t0
    before = [t for t in sim if t0 - span <= (ts(t.get("closed_at")) or 0) < t0]
    a, b = per_trade(after), per_trade(before)
    txt = f"depois {a:+.5f} SOL/trade em {len(after)} trades × antes " + ("–" if b is None else f"{b:+.5f} SOL/trade em {len(before)}")
    if b is not None and a < b:
        return "desfez", "piorou: " + txt
    return "manteve", "melhorou ou igual: " + txt


def bad_traders(autopsy: dict, paused: set) -> list[dict]:
    return [x for x in autopsy.get("traders") or [] if x["wallet"] not in paused and x["wallet"] != "?"
            and x["trades"] >= MIN_COPIES and x["acerto"] < 0.30 and x["pnl_sol"] < 0]

