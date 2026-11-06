"""Dormant: abastecer de gás uma carteira a partir de outra rede (0.32.244, pedido do dono em 06/11/2026). Isolado em /dormant.

Ponte: Relay. Em 06/11/2026 foi a mais barata das que deram cotação (cerca de 1% ou menos em US$ 5 nas rotas para Base, Arbitrum, BNB,
Polygon, Avalanche e Solana; mais caro para Ethereum) e cobre as 7 redes. A API do Gas.zip e a da Across não devolveram cotação utilizável
nos testes daquele dia. O dono sempre vê a taxa antes, e a taxa é calculada aqui com o preço da CoinGecko, não com o número da Relay.

O que protege, porque a transação é montada pela API deles:
- origem só nas redes onde a API usa o depósito que os documentos da Relay descrevem: depositNative(depositor, id), endereço fixo aqui.
  Polygon e Avalanche usam outro contrato, que não consegui validar: recebem gás, mas não servem de origem;
- destino SÓ uma carteira cadastrada desta conta: o navegador manda o nome da rede, nunca um endereço;
- o contrato, o seletor, o valor, a rede e o depositante da transação são conferidos antes de assinar, e nunca há approve;
- teto por abastecimento e limite do dia (o mesmo das compras).
O que NÃO dá para conferir na rede: o "id" do depósito é opaco, então quem garante que o gás vai para o recebedor pedido é a Relay. Por isso o
teto é baixo. Se a Relay não entregar, ela devolve (segundo a documentação, o solver reembolsa). Solana só recebe: sair da Solana exigiria
liberar o programa deles na conferência de transações, e isso não dá para validar sem enviar.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid

from . import evm
from .dormant_buy import CHAINS, EVM_CHAINS, BuyError, _iso, _ts

RELAY = "https://api.relay.link"
DEPOSITORY = "0x4cd00e387622c35bddb9b4c962c136462338bc31"     # 06/11/2026: é o que api.relay.link/chains lista como depository, e o que as cotações das 4 origens usam
SEL_DEPOSIT = evm.selector("depositNative(address,bytes32)")
ORIGENS = ("ethereum", "binance-smart-chain", "base", "arbitrum-one")
RELAY_ID = {"solana": 792703809, **{k: CHAINS[k]["id"] for k in EVM_CHAINS}}
SOL_NATIVE = "11111111111111111111111111111111"
ZERO = "0x" + "0" * 40
GAS_MAX_USD = 25.0                # teto por abastecimento: é só para gás, e o destino não é verificável na rede
TAXA_AVISO, TAXA_BLOQ = 3.0, 15.0
GAS_OP = 400000                   # gás de uma compra ou venda (com a autorização), perto do que as simulações mediram
SOL_OP = 0.003                    # taxa + aluguel da conta de um token novo
OPS_POUCO, OPS_ALVO = 3, 5
MIN_SUGESTAO = 1.0
ENTREGA_S = 60
ENTREGA_PASSO = 3
REQ_ID = re.compile(r"^0x[0-9a-fA-F]{64}$")


def check_quote(js: dict, origem: str, addr: str, recebedor: str, value: int) -> dict:
    """Só passa a transação que é exatamente um depósito da moeda da rede, no contrato fixo, da própria carteira. Falha fechada."""
    steps = js.get("steps") if isinstance(js, dict) else None
    if not isinstance(steps, list) or len(steps) != 1:
        raise BuyError("a Relay pediu mais de um passo: recusado")
    st = steps[0]
    items = st.get("items") or []
    if st.get("id") != "deposit" or st.get("kind") != "transaction" or len(items) != 1:
        raise BuyError("a Relay pediu outra operação além do depósito: recusado")
    d = items[0].get("data") or {}
    if str(d.get("to") or "").lower() != DEPOSITORY:
        raise BuyError("a Relay mandou depositar em outro contrato: recusado")
    if int(d.get("chainId") or 0) != CHAINS[origem]["id"]:
        raise BuyError("a Relay mandou uma transação de outra rede: recusado")
    if str(d.get("value") or "") != str(value):
        raise BuyError("o valor da transação não bate com o pedido: recusado")
    if str(d.get("from") or "").lower() != addr:
        raise BuyError("a transação não é da sua carteira: recusado")
    data = str(d.get("data") or "").lower()
    if len(data) != 138 or not data.startswith(SEL_DEPOSIT) or "0x" + data[34:74] != addr:
        raise BuyError("a transação não é o depósito esperado: recusado")
    det = js.get("details") or {}
    if str(det.get("recipient") or "") != recebedor or str(det.get("sender") or "").lower() != addr:
        raise BuyError("a cotação não é para a sua carteira de destino: recusado")
    rid = st.get("requestId") or js.get("requestId")
    if not isinstance(rid, str) or not REQ_ID.match(rid):
        raise BuyError("a Relay não devolveu um identificador válido: recusado")
    try:
        saida = float((det.get("currencyOut") or {})["amountFormatted"])
    except (KeyError, TypeError, ValueError):
        raise BuyError("a Relay não disse quanto entrega: recusado") from None
    if saida <= 0:
        raise BuyError("a Relay não entrega nada nesta cotação: recusado")
    return {"data": data, "saida": saida, "request_id": rid, "tempo_s": det.get("timeEstimate")}


class GasFiller:
    def __init__(self, buyer):
        self.b = buyer

    async def status(self, uid: str) -> dict:
        """Saldo de cada carteira e para quantas operações o gás dá."""
        b = self.b
        rows = await b.db.select("dormant_wallets", {"user_id": uid}, columns="rede,endereco") or []

        async def one(r):
            k = r["rede"]
            c = CHAINS.get(k)
            if not c:
                return k, None
            try:
                if c["tipo"] == "solana":
                    saldo = (await b.rpc(b.sol_rpc(), "getBalance", [r["endereco"]]))["value"] / 1e9
                    op = SOL_OP
                else:
                    saldo = int(await b.rpc(c["rpc"], "eth_getBalance", [r["endereco"], "latest"]) or "0x0", 16) / 1e18
                    op = int(await b.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16) * GAS_OP / 1e18
            except (BuyError, KeyError, TypeError, ValueError):
                return k, {"saldo": None, "moeda": c["moeda"], "estado": "nao_lido"}
            usd = await b.native_usd(k)
            ops = saldo / op if op else None
            alvo = max(MIN_SUGESTAO, op * OPS_ALVO * usd) if usd else MIN_SUGESTAO
            return k, {"saldo": saldo, "moeda": c["moeda"], "usd": saldo * usd if usd else None, "ops": ops,
                       "estado": "sem" if ops is not None and ops < 1 else "pouco" if ops is not None and ops < OPS_POUCO else "ok",
                       "sugestao_usd": round(min(GAS_MAX_USD, alvo), 2), "pode_origem": k in ORIGENS and bool(usd) and saldo * usd >= MIN_SUGESTAO}
        return {"redes": {k: v for k, v in await asyncio.gather(*[one(r) for r in rows])}, "teto_usd": GAS_MAX_USD}

    async def _relay_quote(self, origem: str, destino: str, addr: str, recebedor: str, value: int) -> dict:
        moeda_out = SOL_NATIVE if CHAINS[destino]["tipo"] == "solana" else ZERO
        try:
            r = await self.b.http.post(RELAY + "/quote/v2", json={"user": addr, "recipient": recebedor, "originChainId": RELAY_ID[origem], "destinationChainId": RELAY_ID[destino],
                                                                   "originCurrency": ZERO, "destinationCurrency": moeda_out, "amount": str(value), "tradeType": "EXACT_INPUT"},
                                       headers={"User-Agent": "pump-fun-copy/1.0"}, timeout=20)
            js = r.json()
        except Exception as e:
            raise BuyError(f"a Relay não respondeu ({type(e).__name__})") from None
        if not isinstance(js, dict) or "steps" not in js:
            raise BuyError("a Relay não cotou esta rota: " + str((js or {}).get("message") if isinstance(js, dict) else "")[:120])
        return check_quote(js, origem, addr, recebedor, value)

    async def _wallets(self, uid: str, origem: str, destino: str) -> tuple[dict, dict]:
        if origem not in ORIGENS:
            raise BuyError("esta rede não serve de origem: use Ethereum, BNB Chain, Base ou Arbitrum")
        if destino not in CHAINS or destino == origem:
            raise BuyError("escolha outra rede de destino")
        o, d = await self.b.wallet_row(uid, origem), await self.b.wallet_row(uid, destino)
        if not o or not d:
            raise BuyError("as duas redes precisam ter carteira cadastrada: o gás só vai para uma carteira sua")
        return o, d

    async def preview(self, uid: str, destino: str, origem: str, usd) -> dict:
        b = self.b
        o, d = await self._wallets(uid, origem, destino)
        try:
            usd = float(usd)
        except (TypeError, ValueError):
            raise BuyError("valor inválido") from None
        if not 0 < usd < 1e9:
            raise BuyError("valor inválido")
        c, cd = CHAINS[origem], CHAINS[destino]
        cfg = await b.cfg(uid)
        bloq: list[str] = []
        avisos: list[str] = []
        if not b.allowed():
            bloq.append("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
        if not cfg["on"]:
            bloq.append("as compras estão desligadas: ligue em Compras, nesta tela")
        if usd > GAS_MAX_USD:
            bloq.append(f"o teto por abastecimento é US$ {GAS_MAX_USD:g}: isto é só para gás")
        if usd > cfg["max_usd"]:
            bloq.append(f"passa do seu limite por compra (US$ {cfg['max_usd']:g})")
        gasto = await b.spent_today(uid)
        if gasto + usd > cfg["dia_usd"]:
            bloq.append(f"passa do seu limite por dia (US$ {cfg['dia_usd']:g}; já foram US$ {gasto:.2f} hoje)")
        if await b.pending_on(uid, origem):
            bloq.append("há uma operação sem confirmação nesta rede: espere ela terminar")
        un, ud = await b.native_usd(origem), await b.native_usd(destino)
        if not un or not ud:
            raise BuyError("sem a cotação em dólar das duas moedas agora: tente de novo em instantes")
        value = int(usd / un * 1e18)
        addr, rec = o["endereco"], d["endereco"]
        q = await self._relay_quote(origem, destino, addr, rec, value)
        usd_out = q["saida"] * ud
        taxa = (1 - usd_out / usd) * 100
        if taxa > TAXA_BLOQ:
            bloq.append(f"a taxa ficaria em {taxa:.1f}%: cara demais (máx. {TAXA_BLOQ:g}%)")
        elif taxa > TAXA_AVISO:
            avisos.append(f"a taxa está em {taxa:.1f}%: valores pequenos e destino Ethereum custam mais")
        gp = int(await b.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        bal = int(await b.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        gas = 60000
        if bal < value:
            bloq.append(f"saldo insuficiente na origem: {bal / 1e18:.6f} {c['moeda']}")
        else:
            try:
                gas = int(await b.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": DEPOSITORY, "data": q["data"], "value": hex(value)}]), 16)
            except BuyError as e:
                bloq.append("a rede recusou na simulação: " + str(e))
            if bal < value + int(gas * 1.3) * gp:
                bloq.append(f"falta {c['moeda']} para pagar o gás da própria transação na origem")
        out = {"origem": origem, "origem_nome": c["nome"], "destino": destino, "destino_nome": cd["nome"], "moeda_origem": c["moeda"], "moeda_destino": cd["moeda"], "carteira": addr, "recebedor": rec,
               "paga": value / 1e18, "usd": usd, "recebe": q["saida"], "usd_recebe": round(usd_out, 4), "taxa_pct": round(taxa, 2), "gas_usd": round(gas * gp / 1e18 * un, 4), "tempo_s": q["tempo_s"],
               "ponte": "Relay", "bloqueia": bloq, "avisos": avisos}
        if not bloq:
            b._prune()
            qid = uuid.uuid4().hex
            b.quotes[qid] = {"lado": "gas", "uid": uid, "t": time.time(), "origem": origem, "destino": destino, "end": addr, "rec": rec, "value": value, "usd": usd, "usd_n": un, "ud": ud, "saida": q["saida"], "gp": gp}
            out.update(quote_id=qid, validade_s=60)
        return out

    async def fill(self, uid: str, quote_id: str, senha: str, confirmar: str) -> dict:
        b = self.b
        if confirmar != "ABASTECER":
            raise BuyError("digite ABASTECER para confirmar")
        async with b.lock(uid):
            b._prune()
            q = b.quotes.get(str(quote_id or ""))
            if not q or q["uid"] != uid or q.get("lado") != "gas":
                raise BuyError("esta cotação venceu: peça outra")
            cfg = await b.cfg(uid)
            if not b.allowed():
                raise BuyError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            if not cfg["on"]:
                raise BuyError("as compras estão desligadas")
            o, d = await self._wallets(uid, q["origem"], q["destino"])
            if o["endereco"] != q["end"] or d["endereco"] != q["rec"]:
                raise BuyError("uma das carteiras mudou: peça outra cotação")
            secret = await b._open(uid, o, senha)
            b.quotes.pop(quote_id, None)
            gasto = await b.spent_today(uid)
            if q["usd"] > min(GAS_MAX_USD, cfg["max_usd"]) or gasto + q["usd"] > cfg["dia_usd"]:
                raise BuyError("passa dos seus limites em dólar")
            if await b.pending_on(uid, q["origem"]):
                raise BuyError("há uma operação sem confirmação nesta rede: espere ela terminar")
            c = CHAINS[q["origem"]]
            if int(await b.rpc(c["rpc"], "eth_chainId", []) or "0x0", 16) != c["id"]:
                raise BuyError("o RPC respondeu de outra rede: nada foi enviado")
            addr = o["endereco"]
            key = evm.parse_key(secret)
            if evm.address_of(key) != addr:
                raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
            nova = await self._relay_quote(q["origem"], q["destino"], addr, q["rec"], q["value"])    # o depósito tem que ser de uma cotação nova
            if nova["saida"] < q["saida"] * 0.97:
                raise BuyError("a cotação piorou: nada foi enviado, peça outra")
            est = int(await b.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": DEPOSITORY, "data": nova["data"], "value": hex(q["value"])}]), 16)
            gp = int(await b.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
            if q.get("gp") and gp > q["gp"] * 2:
                raise BuyError("o gás mais que dobrou desde a cotação: nada foi enviado, peça outra")
            gp = int(gp * 1.1)
            gas = int(est * 1.3) + 10000
            if int(await b.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16) < q["value"] + gas * gp:
                raise BuyError(f"falta {c['moeda']} para pagar o valor e o gás: nada foi enviado")
            nonce = int(await b.rpc(c["rpc"], "eth_getTransactionCount", [addr, "pending"]), 16)
            raw, h = evm.sign_tx(key, nonce, gp, gas, DEPOSITORY, q["value"], nova["data"], c["id"])
            row = {"id": uuid.uuid4().hex, "user_id": uid, "em": _iso(time.time()), "rede": q["origem"], "destino": q["destino"], "endereco": addr, "recebedor": q["rec"], "nativo": q["value"] / 1e18,
                   "nativo_usd": q["usd_n"], "usd_in": q["usd"], "saida": nova["saida"], "saida_usd": q["ud"], "request_id": nova["request_id"], "tx": h, "status": "enviando"}
            await b.db.insert("dormant_gas", row)      # grava ANTES de enviar, como na compra
            try:
                await b.rpc(c["rpc"], "eth_sendRawTransaction", [raw])
            except BuyError as e:
                if "known" not in str(e).lower() and "already" not in str(e).lower():
                    await self._finish(row, status="falhou", motivo="envio recusado: " + str(e)[:160])
                    raise
            from .dormant_buy import RECIBO_S
            t0, rc = time.monotonic(), None
            while time.monotonic() - t0 < RECIBO_S and not rc:
                await asyncio.sleep(ENTREGA_PASSO)
                try:
                    rc = await b.rpc(c["rpc"], "eth_getTransactionReceipt", [h])
                except BuyError:
                    rc = None
            if not rc:
                await self._finish(row, status="pendente", motivo="depósito sem confirmação em 90 s")
                return self._public(row)
            g = int(rc.get("gasUsed") or "0x0", 16) * int(rc.get("effectiveGasPrice") or hex(gp), 16) / 1e18
            if int(rc.get("status") or "0x0", 16) != 1:
                await self._finish(row, status="falhou", motivo="o depósito falhou na rede (só o gás foi gasto)", gas_usd=round(g * q["usd_n"], 4))
                return self._public(row)
            await self._finish(row, status="pendente", motivo="depositado: esperando a entrega", gas_usd=round(g * q["usd_n"], 4))
            t0 = time.monotonic()
            while time.monotonic() - t0 < ENTREGA_S:
                await asyncio.sleep(ENTREGA_PASSO)
                if await self._check_delivery(row):
                    break
            return self._public(row)

    async def _check_delivery(self, row: dict) -> bool:
        """Pergunta à Relay como está. True quando acabou (entregue, devolvido ou falhou)."""
        try:
            r = await self.b.http.get(RELAY + "/intents/status/v3", params={"requestId": row["request_id"]}, timeout=15)
            st = str((r.json() or {}).get("status") or "")
        except Exception:
            return False
        if st == "success":
            await self._finish(row, status="confirmada", motivo=None)
        elif st == "refund":
            await self._finish(row, status="devolvida", motivo="a Relay devolveu o valor para a carteira de origem")
        elif st == "failure":
            await self._finish(row, status="falhou", motivo="a Relay disse que a entrega falhou: confira o saldo; se não voltar, procure o suporte dela com a transação")
        else:
            return False
        return True

    async def _finish(self, row: dict, **v) -> None:
        row.update(v)
        await self.b.db.update("dormant_gas", {"id": row["id"], "user_id": row["user_id"]}, v)

    async def history(self, uid: str) -> list[dict]:
        rows = await self.b.db.select("dormant_gas", {"user_id": uid}, order="em.desc", limit=100) or []
        for r in rows:
            if r.get("status") in ("enviando", "pendente") and time.time() - _ts(r.get("em")) > 20 and r.get("request_id"):
                await self._check_delivery(r)
        return [self._public(r) for r in rows]

    @staticmethod
    def _public(r: dict) -> dict:
        co, cd = CHAINS.get(r.get("rede")) or {}, CHAINS.get(r.get("destino")) or {}
        return {"id": r.get("id"), "t": _ts(r.get("em")), "origem_nome": co.get("nome"), "destino_nome": cd.get("nome"), "moeda_origem": co.get("moeda"), "moeda_destino": cd.get("moeda"), "paga": r.get("nativo"),
                "usd": r.get("usd_in"), "recebe": r.get("saida"), "gas_usd": r.get("gas_usd"), "status": r.get("status"), "motivo": r.get("motivo"), "tx": r.get("tx"), "expl": co.get("expl")}
