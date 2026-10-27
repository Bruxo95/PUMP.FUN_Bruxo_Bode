"""Confere a transação montada por terceiros (PumpPortal / Jupiter) ANTES de assinar com a carteira do usuário.

Motivo (auditoria de 2026-10-25, SEC-01): o servidor assinava qualquer mensagem que o provedor devolvesse. No
teste offline, um pedido de compra de 0,05 SOL virou a assinatura de uma transferência de 9 SOL. Agora a mensagem
só é assinada se:
- a carteira do usuário for a ÚNICA assinante e a pagadora da taxa;
- todo programa chamado estiver na lista abaixo (desconhecido = recusa);
- não houver transferência de token, aprovação (approve) nem troca de autoridade;
- fechar conta de token só devolvendo o saldo para a própria carteira;
- o SOL gasto pelos programas de troca (máximo da compra / valor de entrada da Jupiter) caber no pedido;
- transferências de SOL para terceiros (taxa da PumpPortal) e a taxa de prioridade ficarem dentro de tetos.
Falha fechada: qualquer coisa que não dê para conferir é recusada. Não substitui carteira dedicada com pouco saldo.
"""
from __future__ import annotations

import asyncio
import hashlib
import time

SYSTEM = "11111111111111111111111111111111"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"     # conferido na doc da Solana Tracker em 2026-10-25
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
WSOL = "So11111111111111111111111111111111111111112"
# 0.31.48: programa intermediário que a PumpPortal passou a pôr na transação do trade-local (visto em 27/10/2026: recusou
# as compras reais de R1R2L1R2 e Windle). Na blockchain ele chama Buy/Sell do programa oficial 6EF8… e o de taxas pfee….
# Os dados dele não dizem quanto gasta, então a transação com ele só é assinada depois de SIMULADA (PumpReal._sim_guard):
# a simulação mostra quanto SOL sai da carteira e se algum outro token seria mexido.
PUMPPORTAL_ROUTER = "FAdo9NCw1ssek6Z6yeWzWjhLVsr8uiCwcWNUnKgzTnHe"

MAX_PRIORITY_LAMPORTS = 10_000_000          # 0,01 SOL de taxa de prioridade por transação
MAX_RENT_LAMPORTS = 10_000_000              # contas novas (aluguel) por transação
MAX_ATA_CREATES = 4


def anchor(name: str) -> bytes:
    """Discriminador Anchor da instrução (8 primeiros bytes de sha256("global:<nome>"))."""
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


PUMP_BUY, PUMP_SELL, PUMP_BUY_SOL_IN = anchor("buy"), anchor("sell"), anchor("buy_exact_sol_in")
# só rotas "ExactIn" v1, cujo final dos dados é: in_amount u64, quoted_out u64, slippage_bps u16, platform_fee_bps u8
JUP_ROUTES = {anchor("route"), anchor("shared_accounts_route")}


class TxRejected(ValueError):
    """A mensagem não bate com o pedido: não assinar."""


def _u64(data: bytes, at: int) -> int:
    if len(data) < at + 8:
        raise TxRejected("dados da instrução curtos demais")
    return int.from_bytes(data[at:at + 8], "little")


def wsol_ata(owner: str) -> str:
    from solders.pubkey import Pubkey
    addr, _ = Pubkey.find_program_address([bytes(Pubkey.from_string(owner)), bytes(Pubkey.from_string(TOKEN)),
                                           bytes(Pubkey.from_string(WSOL))], Pubkey.from_string(ATA))
    return str(addr)


def check(message, owner: str, *, max_spend_lamports: int, max_fee_lamports: int, mint: str | None = None,
          jupiter: dict | None = None, owner_wsol: str | None = None,
          max_priority_lamports: int = MAX_PRIORITY_LAMPORTS) -> dict:
    """Levanta TxRejected se a mensagem fizer algo além do pedido. Devolve um resumo (para log/teste).

    max_spend_lamports: SOL que os programas de troca podem gastar (máximo da compra na pump.fun / PumpSwap).
    max_fee_lamports: soma das transferências de SOL para terceiros (ex.: taxa da PumpPortal).
    mint: o token pedido; precisa aparecer nas instruções da pump.fun/PumpSwap.
    jupiter: {"amount": entrada máxima, "slip_bps": slippage máximo} — exige uma rota Jupiter conferida.
    """
    keys = [str(k) for k in message.account_keys]
    if message.header.num_required_signatures != 1 or not keys or keys[0] != owner:
        raise TxRejected("a carteira do usuário não é a única assinante/pagadora")
    owner_wsol = owner_wsol or wsol_ata(owner)

    def key(i: int) -> str | None:
        return keys[i] if i < len(keys) else None            # índice além das chaves fixas = conta de lookup table

    spend = external = wrapped = rent = 0
    cu_limit, cu_price, ata_creates, jup_routes, routed = 1_400_000, 0, 0, 0, 0
    for ix in message.instructions:
        prog = key(ix.program_id_index)
        accs = [key(i) for i in bytes(ix.accounts)]
        data = bytes(ix.data)
        if prog == COMPUTE_BUDGET:
            if data[:1] == b"\x02":
                cu_limit = int.from_bytes(data[1:5], "little")
            elif data[:1] == b"\x03":
                cu_price = _u64(data, 1)
            elif data[:1] not in (b"\x01", b"\x04"):
                raise TxRejected("instrução de orçamento de computação desconhecida")
        elif prog == SYSTEM:
            kind = int.from_bytes(data[:4], "little") if len(data) >= 4 else -1
            if kind == 2:                                     # Transfer
                if not accs or accs[0] != owner:
                    raise TxRejected("transferência de SOL de conta inesperada")
                lamports = _u64(data, 4)
                if len(accs) > 1 and accs[1] == owner_wsol:
                    wrapped += lamports                       # SOL embrulhado continua na conta do próprio usuário
                else:
                    external += lamports
            elif kind == 0:                                   # CreateAccount: só aluguel de conta nova
                rent += _u64(data, 4)
            else:
                raise TxRejected(f"instrução do System Program não permitida ({kind})")
        elif prog == ATA:
            if data[:1] not in (b"", b"\x00", b"\x01"):
                raise TxRejected("instrução de conta associada não permitida")
            ata_creates += 1
        elif prog in (TOKEN, TOKEN_2022):
            tag = data[:1]
            if tag == b"\x09":                                # CloseAccount: saldo volta para a própria carteira
                if len(accs) < 2 or accs[1] != owner:
                    raise TxRejected("fechamento de conta de token mandando o saldo para terceiros")
            elif tag not in (b"\x01", b"\x10", b"\x11", b"\x12"):   # Initialize*, SyncNative
                raise TxRejected(f"instrução de token não permitida ({data[:1].hex() or 'vazia'})")
        elif prog in (PUMP, PUMP_AMM):
            disc = data[:8]
            if mint and mint not in accs:
                raise TxRejected("a instrução da pump.fun não é do token pedido")
            if disc == PUMP_BUY:
                spend += _u64(data, 16)                       # max_sol_cost / max_quote_amount_in
            elif disc == PUMP_BUY_SOL_IN and prog == PUMP:
                spend += _u64(data, 8)                        # spendable_sol_in
            elif disc != PUMP_SELL:
                raise TxRejected("instrução da pump.fun desconhecida")
        elif prog == PUMPPORTAL_ROUTER:
            if mint and mint not in accs:
                raise TxRejected("a instrução da PumpPortal não é do token pedido")
            if PUMP not in accs and PUMP_AMM not in accs:
                raise TxRejected("a instrução da PumpPortal não chama a pump.fun")
            routed += 1
        elif prog == JUPITER:
            if jupiter is None or data[:8] not in JUP_ROUTES or len(data) < 27:
                raise TxRejected("instrução da Jupiter desconhecida")
            tail = data[-19:]
            in_amount, slip, fee = _u64(tail, 0), int.from_bytes(tail[16:18], "little"), tail[18]
            if in_amount > int(jupiter["amount"]):
                raise TxRejected("a rota da Jupiter usa mais do que o valor pedido")
            if slip > int(jupiter["slip_bps"]) or fee != 0:
                raise TxRejected("a rota da Jupiter tem slippage/taxa acima do pedido")
            jup_routes += 1
        else:
            raise TxRejected(f"programa não permitido: {prog or 'conta de lookup table'}")
    priority = cu_price * cu_limit // 1_000_000
    if jupiter is not None and jup_routes != 1:
        raise TxRejected("a transação da Jupiter precisa ter exatamente uma rota")
    if spend > max_spend_lamports:
        raise TxRejected(f"gasto máximo {spend / 1e9:.4f} SOL acima do pedido ({max_spend_lamports / 1e9:.4f} SOL)")
    if external > max_fee_lamports:
        raise TxRejected(f"envia {external / 1e9:.4f} SOL para terceiros (teto {max_fee_lamports / 1e9:.4f} SOL)")
    if priority > max_priority_lamports or rent > MAX_RENT_LAMPORTS or ata_creates > MAX_ATA_CREATES:
        raise TxRejected("taxa de prioridade, aluguel ou contas novas acima do teto")
    if routed and jupiter is not None:
        raise TxRejected("rota da PumpPortal misturada com a Jupiter")
    return {"spend": spend, "external": external, "wrapped": wrapped, "rent": rent, "priority": priority,
            "needs_simulation": routed > 0}


# ---------------------------------------------------------------------------- SEC-04: transação sem confirmação
async def signature_status(rpc, sig: str) -> tuple[str | None, str | None]:
    """("confirmada" | "falhou" | None, erro). Procura também no histórico (a transação pode ter entrado tarde)."""
    st = (await rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}]))["value"][0]
    if st and st.get("err"):
        return "falhou", str(st["err"])[:120]
    if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
        return "confirmada", None
    return None, None


async def reconcile(rpc, sig: str, blockhash: str, timeout: float = 90.0, step: float = 2.0) -> tuple[str, str | None]:
    """Depois de "pendente": espera a assinatura confirmar/falhar ou o blockhash vencer (aí ela não entra mais).
    Motivo (auditoria 2026-10-25, SEC-04): montar outra venda antes disso podia vender duas vezes."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            st, err = await signature_status(rpc, sig)
        except Exception:
            st, err = None, None
        if st:
            return st, err
        try:
            valid = bool((await rpc("isBlockhashValid", [blockhash, {"commitment": "processed"}]))["value"])
        except Exception:
            valid = True                                      # sem resposta: não dá para afirmar que venceu
        if not valid:
            try:
                st, err = await signature_status(rpc, sig)    # última conferência: pode ter entrado no limite
            except Exception:
                return "pendente", "sem confirmação; não reenviar até conferir a assinatura"
            return (st, err) if st else ("expirada", "a transação venceu sem entrar na blockchain")
        if time.monotonic() >= deadline:
            return "pendente", "sem confirmação; não reenviar até conferir a assinatura"
        await asyncio.sleep(step)
