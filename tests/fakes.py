"""Banco falso em memória com a mesma interface do SupaREST (para testar sem internet).

Imita o que o PostgREST faz com a service key: NÃO aplica RLS — por isso o código do servidor tem que filtrar
por user_id sempre, e é isso que os testes de isolamento conferem.
"""
from __future__ import annotations

import copy
import itertools
from datetime import datetime, timezone

PKS = {"profiles": ("user_id",), "user_settings": ("user_id",), "user_secrets": ("user_id", "nome"),
       "pump_positions": ("id",), "pump_trades": ("id",), "pump_lists": ("user_id", "tipo", "wallet"),
       "pump_feed": ("id",), "audit_log": ("id",), "app_secrets": ("nome",),
       "learning_daily": ("user_id", "dia"), "study_wallets": ("user_id", "wallet"),
       "wallet_trades": ("signature",), "study_positions": ("wallet", "token"), "ghost_stats": ("user_id",),
       "blacklist": ("endereco",), "token_life": ("mint",), "market_hourly": ("hora",),
       "creator_stats": ("creator",), "lab_state": ("id",), "auto_trades": ("id",),
       "elite_signals": ("id",), "daily_report": ("user_id", "dia"), "study_auto_log": ("id",),
       "auto_tune_log": ("id",), "config_offers": ("id",), "config_compare_reports": ("id",),
       "base_snapshots": ("id",), "base_log": ("id",), "base_shadows": ("mint",), "api_usage": ("mes", "api", "chave"), "base_evolutions": ("numero",), "token_xray": ("mint",)}
AUTO_ID = {"pump_feed", "audit_log", "study_auto_log", "auto_tune_log", "config_offers", "config_compare_reports",
           "base_snapshots", "base_log"}
DEFAULT_TS = {"config_compare_reports": "criado_em", "config_offers": "criado_em", "study_wallets": "criado_em", "pump_trades": "fechada_em", "pump_positions": "aberta_em", "audit_log": "at", "pump_feed": "at",
              "profiles": "criado_em", "user_secrets": "criado_em",
              "app_secrets": "atualizado_em"}


class FakeREST:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {t: [] for t in PKS}
        self.calls: list = []
        self._seq = itertools.count(1)
        self.fail = False

    def _check(self):
        if self.fail:
            raise RuntimeError("banco fora do ar (simulado)")

    @staticmethod
    def _match(row, filters):
        return all(row.get(k) == v for k, v in (filters or {}).items())

    async def select(self, table, filters=None, order=None, limit=None, columns="*", *, gte=None,
                     lte=None, is_null=(), offset=0):
        self._check()
        self.calls.append(("select", table, dict(filters or {})))
        rows = [copy.deepcopy(r) for r in self.tables[table] if self._match(r, filters)]
        from app.auto_trades import ts
        def comparable(value):
            parsed = ts(value)
            return parsed if parsed is not None else value
        rows = [row for row in rows if all(row.get(k) is not None and comparable(row[k]) >= comparable(v)
                                           for k, v in (gte or {}).items())
                and all(row.get(k) is not None and comparable(row[k]) <= comparable(v)
                        for k, v in (lte or {}).items()) and all(row.get(k) is None for k in is_null)]
        if order:
            col, _, d = order.partition(".")
            rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=(d == "desc"))
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]
        if columns != "*":
            cols = [c.strip() for c in columns.split(",")]
            rows = [{c: r.get(c) for c in cols} for r in rows]
        return rows

    async def insert(self, table, rows, upsert=False, on_conflict=None):
        self._check()
        rows = rows if isinstance(rows, list) else [rows]
        self.calls.append(("insert", table, len(rows)))
        pk = PKS[table]
        for r in rows:
            r = copy.deepcopy(r)
            if table in AUTO_ID and "id" not in r:
                r["id"] = next(self._seq)
            ts = DEFAULT_TS.get(table)
            if ts and ts not in r:
                r[ts] = datetime.now(timezone.utc).isoformat()
            key = tuple(r.get(k) for k in pk)
            old = [x for x in self.tables[table] if tuple(x.get(k) for k in pk) == key]
            if old:
                if not upsert:
                    raise RuntimeError(f"duplicate key {table} {key}")
                old[0].update(r)
            else:
                self.tables[table].append(r)

    async def update(self, table, filters, values):
        self._check()
        assert filters
        for r in self.tables[table]:
            if self._match(r, filters):
                r.update(copy.deepcopy(values))

    async def delete(self, table, filters):
        self._check()
        assert filters
        self.calls.append(("delete", table, dict(filters)))
        self.tables[table] = [r for r in self.tables[table] if not self._match(r, filters)]

    async def rpc(self, fn, args):
        self._check()
        if fn == "trim_pump_feed":
            mine = sorted([r for r in self.tables["pump_feed"] if r["user_id"] == args["p_user"]],
                          key=lambda r: r["id"], reverse=True)
            drop = {r["id"] for r in mine[args["p_keep"]:]}
            self.tables["pump_feed"] = [r for r in self.tables["pump_feed"] if r["id"] not in drop]
        return None

    # ajudante: cria um usuário como o gatilho do Supabase faria (1º = admin)
    def set_role(self, uid, role):
        for p in self.tables["profiles"]:
            if p["user_id"] == uid:
                p["role"] = role

    def add_user(self, uid, email, nome=None):
        role = "admin" if not self.tables["profiles"] else "user"
        self.tables["profiles"].append({"user_id": uid, "email": email, "nome": nome, "avatar_url": None,
                                        "role": role, "criado_em": datetime.now(timezone.utc).isoformat(),
                                        "bloqueado": False, "ultimo_acesso": None})
        self.tables["user_settings"].append({"user_id": uid, "settings": {}, "compartilhar_chave_st": False})
