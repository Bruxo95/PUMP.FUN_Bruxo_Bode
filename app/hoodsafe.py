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
ROUNDTRIP_MAX = 8.0                  # 0.32.322: era 12 (o trade já nascia devendo até 12%). % perdidos na ida e volta além disso barra (taxa dos dois lados + folga)
TAX_MAX = 5.0                        # taxa de compra ou venda do token (GoPlus) acima disso barra
# 0.32.312 (caso HOLD, 11/11: a venda passou na conferência e travou minutos depois): aprovado vale só 90 s (antes 10 min), então
# cada compra confere de novo se o pool ainda aceita a venda; e o código do contrato é lido no explorador (Blockscout).
OK_S, BAD_S, ERR_S = 90, 6 * 3600, 60
EXPLORER = "https://robinhoodchain.blockscout.com/api/v2/smart-contracts/"
SCAN_S = 24 * 3600
# nomes de função que só existem para travar ou taxar a venda de quem comprou (honeypot clássico): o dono liga a trava depois
DANGER = {"blacklist": "lista negra de carteiras", "blocklist": "lista negra de carteiras", "addbot": "marcar carteiras como robô",
          "setbot": "marcar carteiras como robô", "isbot": "lista de robôs", "pause": "pausar o token", "settrading": "ligar/desligar negociação",
          "disabletrading": "desligar negociação", "settradingenabled": "ligar/desligar negociação", "setmaxtx": "limite por transação",
          "setmaxsell": "limite de venda", "setsellfee": "taxa de venda", "setselltax": "taxa de venda", "settax": "mudar a taxa",
          "setfee": "mudar a taxa", "updatefee": "mudar a taxa", "setcooldown": "espera entre vendas", "setlimit": "limites de carteira",
          "setmaxwallet": "limite por carteira", "excludefromfee": "isentar carteiras de taxa", "setpair": "trocar o par de venda",
          "setswapenabled": "ligar/desligar venda", "lockseller": "travar quem vende", "freeze": "congelar carteiras"}
SEL_DEC = evm.selector("decimals()")
# 0.32.316 (pedido do dono, depois dos casos TEXEL e mihao de 11/11: o criador tirou toda a liquidez minutos depois da compra). Medido
# na rede em 11/11: dos 151 pools novos pagos em ETH em 2 h, em 120 a liquidez era de uma carteira comum (NFT do PositionManager da
# Uniswap V4 com dono sem código) e 90 desses já tinham sido retirados. Liquidez queimada ou presa num contrato não sai assim.
POSM = "0x58daec3116aae6d93017baaea7749052e8a04fa7"     # PositionManager oficial da V4 na Robinhood (name() = Uniswap v4 Positions NFT)
T_ML = "0x" + evm.keccak256(b"ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32)").hex()
SEL_OWNER = evm.selector("ownerOf(uint256)")
LP_S = 300                           # dono da liquidez de cada pool guardado 5 min
LP_SPANS = (2_000_000, 9_000_000)    # blocos para trás (~2,3 dias, depois ~10 dias) atrás das entradas de liquidez
LP_LIVRE_PCT = 50.0                  # carteira comum com essa parte da liquidez ou mais = pode tirar a qualquer hora
SEL_TRANSFER = evm.selector("transfer(address,uint256)")
GP_BLOQ = {"is_honeypot": "honeypot: não deixa vender", "cannot_sell_all": "não deixa vender tudo",
           "cannot_buy": "não deixa comprar", "selfdestruct": "o contrato pode se autodestruir",
           "owner_change_balance": "o dono pode mudar o saldo das carteiras", "transfer_pausable": "o dono pode pausar as transferências"}


def _delta(lg: dict) -> int:
    w = evm.words(lg.get("data") or "0x")
    return (w[2] - (1 << 256) if w[2] >> 255 else w[2]) if len(w) > 3 else 0


def _hook(key: list) -> str:
    return " (contrato extra do pool " + key[4][:10] + "…)" if len(key) > 4 and key[4] != ZERO else ""


class Safety:
    def __init__(self, call, http):
        self.call = call            # async (to, data, from|None) → hex (levanta erro se a rede recusar)
        self.http = http
        self.cache: dict[str, dict] = {}
        self.stat = {"aprovados": 0, "barrados": 0, "erros": 0, "goplus_com_dados": 0, "goplus_sem_dados": 0}
        self.recent: list[dict] = []
        self.scans: dict[str, dict] = {}
        self.rpc = None              # async (método, params) → resultado; posto pela cópia (eth_getLogs e eth_getCode)
        self.lp_cache: dict[str, dict] = {}

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
        self.recent.insert(0, {k: v.get(k) for k in ("token", "ok", "why", "t", "erro", "ida_volta_pct", "goplus", "lp_livre")})
        del self.recent[60:]
        if len(self.cache) > 3000:
            for k in sorted(self.cache, key=lambda x: self.cache[x]["t"])[:1000]:
                self.cache.pop(k, None)
        return v

    async def scan(self, token: str) -> dict:
        """Código do contrato no Blockscout (cache 24 h): {"verificado": True/False/None, "perigo": [nomes]}. None = não deu para ler."""
        c = self.scans.get(token)
        if c and time.time() - c["t"] < SCAN_S:
            return c
        out = {"verificado": None, "perigo": [], "t": time.time()}
        try:
            r = await self.http.get(EXPLORER + token, timeout=6)
            js = r.json() if getattr(r, "status_code", 200) == 200 else {}
            if isinstance(js, dict) and js:
                out["verificado"] = bool(js.get("is_verified") or js.get("is_fully_verified"))
                names = {str(f.get("name") or "").lower() for f in (js.get("abi") or []) if isinstance(f, dict) and f.get("type") == "function"}
                out["perigo"] = sorted({DANGER[k] for n in names for k in DANGER if k in n})
            elif getattr(r, "status_code", 200) == 404:
                out["verificado"] = False
        except Exception:
            pass
        self.scans[token] = out
        if len(self.scans) > 5000:
            for k in list(self.scans)[:1000]:
                self.scans.pop(k, None)
        return out

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
        sc = await self.scan(token)
        if sc["perigo"]:
            return self.mark(token, False, "o contrato tem funções que o dono usa para travar ou taxar a venda: " + ", ".join(sc["perigo"][:4]),
                             verificado=sc["verificado"], venda_travada=True)
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
                    return self.mark(token, False, "o token não deixa transferir (nem o trader que comprou consegue mandar para o pool): honeypot", goplus=gp_info,
                                     ida_volta_pct=round(loss, 2), venda_travada=True)
        lp = await self.lp_control(key)
        return self.mark(token, True, "", goplus=gp_info, ida_volta_pct=round(loss, 2), verificado=sc["verificado"],
                         lp_carteira_pct=lp.get("pct_carteira") if lp else None, lp_livre=lp.get("livre") if lp else None)

    async def lp_control(self, key: list) -> dict | None:
        """Quem pode tirar a liquidez do pool. Soma as entradas e saídas de liquidez (ModifyLiquidity) por dono de posição; a que ainda
        está no pool e pertence a uma carteira comum (NFT do PositionManager com dono sem código, ou com delegação EIP-7702) pode ser
        retirada a qualquer hora. Devolve {"pct_carteira", "livre" (texto ou None), "donos"}; None se não deu para ler (não barra)."""
        if self.rpc is None:
            return None
        from .dormant_buy import v4_pool_id
        pid = v4_pool_id(key)
        c = self.lp_cache.get(pid)
        if c and time.time() - c["t"] < LP_S:
            return c
        try:
            head = int(await self.rpc("eth_blockNumber", []) or "0x0", 16)
            logs, b = [], head
            for span in LP_SPANS:
                a = max(0, b - span)
                logs = (await self.rpc("eth_getLogs", [{"address": PM, "topics": [T_ML, pid], "fromBlock": hex(a), "toBlock": hex(b)}]) or []) + logs
                if any(_delta(lg) > 0 for lg in logs) or a == 0:
                    break
                b = a - 1
            net: dict[tuple, int] = {}
            for lg in logs:
                k = ("0x" + lg["topics"][2][-40:], evm.words(lg.get("data") or "0x")[3])
                net[k] = net.get(k, 0) + _delta(lg)
            live = {k: v for k, v in net.items() if v > 0}
            total = sum(live.values())
            livre, donos = 0, []
            for (snd, salt), v in live.items():
                if snd != POSM:
                    continue                                  # liquidez posta por outro contrato (lançadora): não é carteira comum
                w = evm.words(await self.call(POSM, SEL_OWNER + evm.w_int(salt), None))
                dono = "0x" + hex(w[0])[2:].rjust(40, "0") if w else None
                if not dono or int(dono, 16) == 0 or dono.endswith("dead"):
                    continue
                code = await self.rpc("eth_getCode", [dono, "latest"]) or "0x"
                if code in ("0x", "0x0") or code.startswith("0xef0100"):
                    livre += v
                    donos.append(dono)
        except Exception:
            return None
        pct = round(100 * livre / total, 1) if total else None
        out = {"t": time.time(), "pct_carteira": pct, "donos": donos[:3],
               "livre": (f"{pct:.0f}% da liquidez do pool é de uma carteira comum ({donos[0][:6]}…{donos[0][-4:]}): ela pode tirar tudo a qualquer hora"
                         if pct is not None and pct >= LP_LIVRE_PCT and donos else None)}
        self.lp_cache[pid] = out
        if len(self.lp_cache) > 3000:
            for k in list(self.lp_cache)[:1000]:
                self.lp_cache.pop(k, None)
        return out

    def summary(self, now: float | None = None) -> dict:
        return {"regras": {"ida_volta_max_pct": ROUNDTRIP_MAX, "taxa_max_pct": TAX_MAX, "barrado_h": BAD_S / 3600, "aprovado_min": OK_S / 60},
                "stat": self.stat, "recentes": self.recent[:30]}
