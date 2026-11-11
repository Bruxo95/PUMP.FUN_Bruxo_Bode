"""Robinhood Chain: conferência do token antes de copiar uma compra (0.32.279). Fictícia e REAL só compram com o token aprovado.

Pedido do dono em 10/11/2026 ("faz 1 a 4", item 2: checagem de token golpe). A GoPlus não confirmou se cobre a Robinhood Chain
(chain id 4663): quando ela não tiver dados, quem decide é a própria rede, com três conferências por eth_call (nada é enviado):
1. pool: a chave do pool (Initialize do PoolManager) tem que dar o id do pool e pagar em ETH (currency0 = 0);
2. ida e volta: o Quoter oficial da V4 cota comprar 0,01 ETH do token e vender de volta o que veio. Perda acima de
   ROUNDTRIP_MAX barra (taxa escondida no hook, pool vazio, venda travada);
3. transferência: simula o token saindo da carteira do próprio trader que acabou de comprar para o PoolManager. Se a
   transferência é recusada, é honeypot (só o criador consegue vender).
Token com casas decimais diferentes de 18 fica de fora nesta etapa (o preço da leitura conta 18 casas).
Falha na conferência nunca compra: o token fica sem veredito e a próxima compra confere de novo depois de ERR_S.
"""
from __future__ import annotations

import time

from . import evm
from .dormant_buy import v4_quote_data

QUOTER = "0x8dc178efb8111bb0973dd9d722ebeff267c98f94"   # V4 Quoter da Robinhood (lista oficial da Uniswap, conferido em 07/11)
PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
ZERO = "0x" + "0" * 40
GOPLUS = "https://api.gopluslabs.io/api/v1/token_security/4663?contract_addresses="
PROBE_WEI = 10 ** 16                 # 0,01 ETH na ida e volta
ROUNDTRIP_MAX = 12.0                 # % perdidos na ida e volta além disso barra (taxa dos dois lados + folga)
TAX_MAX = 5.0                        # taxa de compra ou venda do token (GoPlus) acima disso barra
OK_S, BAD_S, ERR_S = 600, 6 * 3600, 60
SEL_DEC = evm.selector("decimals()")
SEL_TRANSFER = evm.selector("transfer(address,uint256)")
GP_BLOQ = {"is_honeypot": "honeypot: não deixa vender", "cannot_sell_all": "não deixa vender tudo",
           "cannot_buy": "não deixa comprar", "selfdestruct": "o contrato pode se autodestruir",
           "owner_change_balance": "o dono pode mudar o saldo das carteiras", "transfer_pausable": "o dono pode pausar as transferências"}


def _hook(key: list) -> str:
    return " (contrato extra do pool " + key[4][:10] + "…)" if len(key) > 4 and key[4] != ZERO else ""


class Safety:
    def __init__(self, call, http):
        self.call = call            # async (to, data, from|None) → hex (levanta erro se a rede recusar)
        self.http = http
        self.cache: dict[str, dict] = {}
        self.stat = {"aprovados": 0, "barrados": 0, "erros": 0, "goplus_com_dados": 0, "goplus_sem_dados": 0}
        self.recent: list[dict] = []

    def cached(self, token: str, now: float | None = None) -> dict | None:
        v = self.cache.get(token)
        if not v:
            return None
        ttl = ERR_S if v.get("erro") else OK_S if v["ok"] else BAD_S
        return v if (now or time.time()) - v["t"] < ttl else None

    def mark(self, token: str, ok: bool, why: str = "", erro: bool = False, **extra) -> dict:
        v = {"ok": ok, "why": why, "t": time.time(), "erro": erro, "token": token, **extra}
        self.cache[token] = v
        self.stat["erros" if erro else "aprovados" if ok else "barrados"] += 1
        self.recent.insert(0, {k: v.get(k) for k in ("token", "ok", "why", "t", "erro", "ida_volta_pct", "goplus")})
        del self.recent[60:]
        if len(self.cache) > 3000:
            for k in sorted(self.cache, key=lambda x: self.cache[x]["t"])[:1000]:
                self.cache.pop(k, None)
        return v

    async def goplus(self, token: str) -> dict | None:
        """Dados da GoPlus para o token, {} sem dados, None se a consulta falhou."""
        try:
            js = (await self.http.get(GOPLUS + token, timeout=8)).json()
            res = (js or {}).get("result") or {}
            return res.get(token) or res.get(token.lower()) or {}
        except Exception:
            return None

    async def check(self, token: str, key: list, trader: str | None, trader_raw: int = 0, fee: float = 0.0) -> dict:
        if len(key) != 5 or key[0] != ZERO or key[1] != token:
            return self.mark(token, False, "pool não pago em ETH (a cópia só compra em pool de ETH da Uniswap V4)")
        try:
            dec = evm.words(await self.call(token, SEL_DEC, None))
        except Exception:
            dec = []
        if not dec:
            return self.mark(token, False, "o token não respondeu as casas decimais", erro=True)
        if dec[0] != 18:
            return self.mark(token, False, f"token com {dec[0]} casas decimais (só 18 nesta etapa)")
        gp = await self.goplus(token)
        gp_info = "consulta falhou" if gp is None else "sem dados" if not gp else "com dados"
        self.stat["goplus_com_dados" if gp else "goplus_sem_dados"] += 1
        if gp:
            bad = [v for k, v in GP_BLOQ.items() if str(gp.get(k, "")).strip() == "1"]
            for k, nome in (("buy_tax", "compra"), ("sell_tax", "venda")):
                try:
                    tx = float(gp.get(k)) * 100
                except (TypeError, ValueError):
                    continue
                if tx > TAX_MAX:
                    bad.append(f"taxa de {nome} do token {tx:.0f}% (máx. {TAX_MAX:g}%)")
            if bad:
                return self.mark(token, False, "GoPlus: " + "; ".join(bad), goplus=gp_info)
        # ida e volta pelo Quoter oficial
        # 0.32.290 (dono, 11/11): compra e venda separadas, com o motivo em palavras. Medido em 11/11: em pools com certos contratos extras
        # (hooks), a compra cota e QUALQUER venda pelo caminho oficial é recusada; quem negocia neles é um contrato-robô que vende por
        # dentro. A cópia compraria e não conseguiria sair.
        try:
            got = evm.words(await self.call(QUOTER, v4_quote_data(key, PROBE_WEI, True), None))
        except Exception as e:
            return self.mark(token, False, "o pool recusou até a compra de teste" + _hook(key) + " (" + str(e)[-60:] + ")", goplus=gp_info)
        if not got or not got[0]:
            return self.mark(token, False, "o pool não cotou a compra de teste", goplus=gp_info)
        try:
            back = evm.words(await self.call(QUOTER, v4_quote_data(key, got[0], False), None))
        except Exception:
            return self.mark(token, False, "a VENDA é recusada pelo pool" + _hook(key) + ": a compra passa, mas não daria para vender depois",
                             goplus=gp_info, venda_travada=True)
        if not back:
            return self.mark(token, False, "o pool não cotou a venda de teste", goplus=gp_info)
        loss = 100 * (1 - back[0] / PROBE_WEI)
        if fee > 0.05:                                    # taxa do pool acima de 5% em cada lado: barra mesmo se a ida e volta passar
            return self.mark(token, False, f"taxa do pool {fee * 100:.1f}% em cada lado", goplus=gp_info, ida_volta_pct=round(loss, 2))
        if loss > ROUNDTRIP_MAX:
            return self.mark(token, False, f"ida e volta perde {loss:.1f}% (máx. {ROUNDTRIP_MAX:g}%): taxa escondida ou pool vazio",
                             goplus=gp_info, ida_volta_pct=round(loss, 2))
        # o token sai da carteira de quem comprou?
        if trader and trader_raw > 100:
            try:
                await self.call(token, SEL_TRANSFER + evm.w_addr(PM) + evm.w_int(trader_raw // 100), trader)
            except Exception as e:
                msg = str(e).lower()
                if "insufficient" not in msg and "exceeds balance" not in msg:     # o trader já vendeu: não dá para medir
                    return self.mark(token, False, "o token não deixa transferir: honeypot", goplus=gp_info, ida_volta_pct=round(loss, 2))
        return self.mark(token, True, "", goplus=gp_info, ida_volta_pct=round(loss, 2))

    def summary(self, now: float | None = None) -> dict:
        return {"regras": {"ida_volta_max_pct": ROUNDTRIP_MAX, "taxa_max_pct": TAX_MAX, "barrado_h": BAD_S / 3600, "aprovado_min": OK_S / 60},
                "stat": self.stat, "recentes": self.recent[:30]}
