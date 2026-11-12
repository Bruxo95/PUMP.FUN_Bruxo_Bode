"""Dormant: comprar e vender uma moeda da lista na DEX, à mão (0.32.242 e 0.32.243, pedidos do dono em 06/11/2026). Isolado do resto:
nada aqui fala com o motor da Solana, da BNB ou da Robinhood. Nunca compra nem vende sozinho.

Só entram as redes onde dá para comprar pelo caminho mais seguro:
- Redes EVM: só o roteador oficial da DEX, com endereço FIXO aqui (conferido na rede em 06/11/2026: eth_call de factory() e
  WETH() batem com as fábricas oficiais). A transação é montada aqui, não por um agregador. Comprar com a moeda da rede não
  precisa de approve, então nenhum contrato fica autorizado a mexer nos tokens da carteira. O recebedor é sempre a própria carteira.
- Solana: Jupiter, com a conferência de txguard (programas, valor, slippage, assinante) + o token tem que cair na conta da carteira.
Rede que não está aqui (TRON, Cardano, Stellar…) não mostra o botão.

Antes de assinar, sempre: chave geral ligada (começa desligada), trava PUMP_REAL_ALLOWED, senha de compra, limites por compra e
por dia em dólar, cotação com validade de 60 s e uso único, cotação refeita na hora, simulação da rede, conferência do token na
GoPlus e comparação com o preço da CoinGecko. Falha fechada: o que não dá para conferir não compra. O endereço do token vem da lista
do servidor (CoinGecko), nunca do navegador. A chave em texto só existe durante a assinatura; nunca vai para log, banco ou tela.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone

from . import cardano
from . import osmosis
from . import dormant_vault as vault
from . import evm
from .crypto import CryptoError

log = logging.getLogger("pump.dormant.compra")

ZERO = "0x" + "0" * 40
T_TRANSFER = "0x" + evm.keccak256(b"Transfer(address,address,uint256)").hex()
SEL_AMOUNTS = evm.selector("getAmountsOut(uint256,address[])")
SEL_SWAP_ETH = evm.selector("swapExactETHForTokensSupportingFeeOnTransferTokens(uint256,address[],address,uint256)")
SEL_SWAP_AVAX = evm.selector("swapExactAVAXForTokensSupportingFeeOnTransferTokens(uint256,address[],address,uint256)")
SEL_V3_QUOTE = evm.selector("quoteExactInputSingle((address,address,uint256,uint24,uint160))")
SEL_V3_SWAP = evm.selector("exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))")
SEL_DECIMALS = evm.selector("decimals()")
V3_ROUTER = "0xe592427a0aece92de3edee1f18e0157c05861564"     # Uniswap V3 (mesmo endereço nas 3 redes; fábrica 0x1f98… conferida)
V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"
V3_FEES = (500, 3000, 10000)
WSOL = "So11111111111111111111111111111111111111112"
T_WITHDRAW = "0x" + evm.keccak256(b"Withdrawal(address,uint256)").hex()
SEL_APPROVE = evm.selector("approve(address,uint256)")
SEL_ALLOW = evm.selector("allowance(address,address)")
SEL_BALANCE = evm.selector("balanceOf(address)")
SEL_SELL_ETH = evm.selector("swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)")
SEL_SELL_AVAX = evm.selector("swapExactTokensForAVAXSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)")
SEL_MULTI = evm.selector("multicall(bytes[])")
SEL_UNWRAP = evm.selector("unwrapWETH9(uint256,address)")
SEL_V4_QUOTE = evm.selector("quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))")
SEL_UR_EXEC = evm.selector("execute(bytes,bytes[],uint256)")
T_V4_INIT = "0x" + evm.keccak256(b"Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)").hex()
# 0.32.257 (pedido do dono, 07/11/2026: "faz a V4"): na Robinhood quase todo memecoin está na Uniswap V4 (a Pons é um pool V4 com contrato
# extra, o hook). Endereços da lista oficial (developers.uniswap.org/docs/protocols/v4/deployments, Robinhood Chain 4663), conferidos na rede
# em 07/11: o Universal Router é o mesmo que a compra real de GLC usou. Só pools que pagam com ETH (currency0 = 0); a chave do pool vem do
# evento Initialize do PoolManager e só vale se o keccak dela der o id do pool. Só compra: a venda pela V4 (Permit2) não foi feita.
V4 = {"robinhood": {"pm": "0x8366a39cc670b4001a1121b8f6a443a643e40951", "quoter": "0x8dc178efb8111bb0973dd9d722ebeff267c98f94",
                    "ur": "0x8876789976decbfcbbbe364623c63652db8c0904", "gt": "robinhood"}}
# 0.32.258 (pedido do dono, 07/11/2026: "faz a venda"): na V4 o Universal Router puxa o token pelo Permit2 (mesmo endereço em todas as redes,
# da lista oficial da Uniswap; código conferido na Robinhood em 07/11). Antes da venda: o token autoriza o Permit2 e o Permit2 autoriza o
# roteador, os dois só no valor exato da venda, o do Permit2 vencendo em 30 min. O roteador só puxa de quem chama: sobra não tem o que roubar.
PERMIT2 = "0x000000000022d473030f116ddee9f6b43ac78ba3"
SEL_P2_APPROVE = evm.selector("approve(address,address,uint160,uint48)")
SEL_P2_ALLOW = evm.selector("allowance(address,address,address)")
T_V4_SWAP = "0x" + evm.keccak256(b"Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)").hex()
P2_VALIDADE_S = 30 * 60
GT_API = "https://api.geckoterminal.com/api/v2"
V4_DEX = {"pons-v2-dex": "Pons (Uniswap V4)", "uniswap-v4-robinhood": "Uniswap V4"}
V4_POOLS_MAX, V4_TTL_S, V4_LOG_SPAN = 4, 600, 400_000

# chave = id da rede na CoinGecko. Tudo conferido em 06/11/2026 (chain id, código do contrato, fábrica, moeda embrulhada, ponte).
CHAINS = {
    "solana": {"nome": "Solana", "tipo": "solana", "moeda": "SOL", "cg": "solana", "dec": 9, "dex": "Jupiter", "expl": "https://solscan.io/tx/",
               "reserva": 0.005},
    "ethereum": {"nome": "Ethereum", "tipo": "evm", "id": 1, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://etherscan.io/tx/",
                 "rpc": "https://ethereum-rpc.publicnode.com", "router": "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
                 "wrapped": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "ponte": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "v3": True,
                 # sem isto o robô de sandwich leva quase toda a folga de preço. 0.32.247: o modo padrão tenta por até 25 blocos (a compra do dono em
                 # 06/11 passou de 90 s); o rápido manda para todos os construtores. Se não entrar em PUBLICO_APOS_S, _evm_send repete na fila pública
                 "envio": "https://rpc.flashbots.net/fast", "gas_mult": 1.25},
    "binance-smart-chain": {"nome": "BNB Chain", "tipo": "evm", "id": 56, "moeda": "BNB", "cg": "binancecoin", "dec": 18, "dex": "PancakeSwap", "expl": "https://bscscan.com/tx/",
                            "rpc": "https://bsc-rpc.publicnode.com", "router": "0x10ed43c718714eb63d5aa57b78b54704e256024e",
                            "wrapped": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "ponte": "0x55d398326f99059ff775485246999027b3197955"},
    "base": {"nome": "Base", "tipo": "evm", "id": 8453, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://basescan.org/tx/",
             "rpc": "https://base-rpc.publicnode.com", "router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
             "wrapped": "0x4200000000000000000000000000000000000006", "ponte": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
    "polygon-pos": {"nome": "Polygon", "tipo": "evm", "id": 137, "moeda": "POL", "cg": "polygon-ecosystem-token", "dec": 18, "dex": "QuickSwap e Uniswap", "expl": "https://polygonscan.com/tx/",
                    "rpc": "https://polygon-bor-rpc.publicnode.com", "router": "0xa5e0829caced8ffdd4de3c43696c57f7d7a678ff",
                    "wrapped": "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270", "ponte": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "v3": True},
    "avalanche": {"nome": "Avalanche", "tipo": "evm", "id": 43114, "moeda": "AVAX", "cg": "avalanche-2", "dec": 18, "dex": "Trader Joe", "expl": "https://snowtrace.io/tx/",
                  "rpc": "https://avalanche-c-chain-rpc.publicnode.com", "router": "0x60ae616a2155ee3d9a68541ba4544862310933d4",
                  "wrapped": "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7", "ponte": "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e", "swap_sel": SEL_SWAP_AVAX, "sell_sel": SEL_SELL_AVAX},
    "arbitrum-one": {"nome": "Arbitrum", "tipo": "evm", "id": 42161, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://arbiscan.io/tx/",
                     "rpc": "https://arbitrum-one-rpc.publicnode.com", "router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
                     "wrapped": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", "ponte": "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "v3": True},
    # 0.32.256 (pedido do dono, 07/11/2026: "adiciona a Robinhood e as top 12 L2 da Ethereum"). Lista da L2BEAT de 07/11 (layer2 por valor guardado):
    # Base, Arbitrum, Polygon PoS, Robinhood, OP Mainnet, Mantle, Lighter, Whitechain, Ink, Starknet, Linea, World Chain, Celo, Gnosis, ZKsync Era.
    # Entram só as que têm roteador V2 OFICIAL publicado pela própria DEX: Uniswap (developers.uniswap.org, v2 deployments) e PancakeSwap
    # (developer.pancakeswap.finance, v2 addresses), mais o Honeyswap no Gnosis. Em 07/11, na rede: código no endereço, factory() = a fábrica publicada,
    # WETH() = moeda embrulhada, par moeda embrulhada/dólar existente, getAmountsOut cotando e a compra simulada por eth_call passando.
    # Ficaram de fora: Mantle e Ink (sem roteador V2 oficial publicado: o principal do Mantle tem outra interface), Celo (a moeda da rede já é um token,
    # não há WETH()), Lighter e Starknet (não são EVM com DEX), Whitechain (sem DEX conferida). Uniswap V3 só onde está o mesmo SwapRouter das outras.
    "robinhood": {"nome": "Robinhood Chain", "tipo": "evm", "id": 4663, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://robinhoodchain.blockscout.com/tx/",
                  "rpc": "https://rpc.mainnet.chain.robinhood.com", "router": "0x89e5db8b5aa49aa85ac63f691524311aeb649eba",
                  "wrapped": "0x0bd7d308f8e1639fab988df18a8011f41eacad73", "ponte": "0x5fc5360d0400a0fd4f2af552add042d716f1d168"},
    "optimistic-ethereum": {"nome": "Optimism", "tipo": "evm", "id": 10, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://optimistic.etherscan.io/tx/",
                            "rpc": "https://optimism-rpc.publicnode.com", "router": "0x4a7b5da61326a6379179b40d00f57e5bbdc962c2",
                            "wrapped": "0x4200000000000000000000000000000000000006", "ponte": "0x0b2c639c533813f4aa9d7837caf62653d097ff85", "v3": True},
    "linea": {"nome": "Linea", "tipo": "evm", "id": 59144, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "PancakeSwap", "expl": "https://lineascan.build/tx/",
              "rpc": "https://linea-rpc.publicnode.com", "router": "0x8cfe327cec66d1c090dd72bd0ff11d690c33a2eb",
              "wrapped": "0xe5d7c2a44ffddf6b295a15c148167daaaf5cf34f", "ponte": "0x176211869ca2b568f2a7d4ee941e073a821ee1ff"},
    "world-chain": {"nome": "World Chain", "tipo": "evm", "id": 480, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://worldscan.org/tx/",
                    "rpc": "https://worldchain-mainnet.g.alchemy.com/public", "router": "0x541ab7c31a119441ef3575f6973277de0ef460bd",
                    "wrapped": "0x4200000000000000000000000000000000000006", "ponte": "0x79a02482a880bce3f13e09da970dc34db4cd24d1"},
    "xdai": {"nome": "Gnosis", "tipo": "evm", "id": 100, "moeda": "xDAI", "cg": "xdai", "dec": 18, "dex": "Honeyswap", "expl": "https://gnosisscan.io/tx/",
             "rpc": "https://gnosis-rpc.publicnode.com", "router": "0x1c232f01118cb8b424793ae03f870aa7d0ac7f77",
             "wrapped": "0xe91d153e0b41518a2ce8dd3d7944fa863463a97d", "ponte": "0xddafbb505ad214d7b80b1f830fccc89b60fb7a83"},
    "zksync": {"nome": "zkSync", "tipo": "evm", "id": 324, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "PancakeSwap", "expl": "https://explorer.zksync.io/tx/",
               "rpc": "https://mainnet.era.zksync.io", "router": "0x5aeaf2883fbf30f3d62471154eda3c0c1b05942d",
               "wrapped": "0x5aea5775959fbc2557cc8789bc1bf90a239d9a91", "ponte": "0x1d17cbcf0d6d143135ae902365d2e5e2a16538d4"},
    # 0.32.273 (pedido do dono, 09/11/2026): Cardano pela Minswap. A transação é montada pelo agregador oficial deles (agg-api.minswap.org,
    # sem chave), conferida aqui (app/cardano.check_tx) e só então assinada. A ordem vai para o contrato da DEX e o token chega numa segunda
    # transação, quando o executor da Minswap roda a ordem (segundos a minutos). Ordem fora da folga fica parada até ser cancelada.
    "cardano": {"nome": "Cardano", "tipo": "cardano", "moeda": "ADA", "cg": "cardano", "dec": 6, "dex": "Minswap", "expl": "https://cardanoscan.io/transaction/",
                "reserva": 3.0},
    # 0.32.274 (pedido do dono, 09/11/2026): Osmosis, a DEX da Cosmos, paga em OSMO. A transação é montada AQUI (app/osmosis.py: uma mensagem só,
    # remetente = a própria carteira, mínimo a receber); o roteador oficial da Osmosis (SQS) só sugere as pools. Conferido em 09/11 na rede:
    # nó osmosis-1 v32, simulação aceitando a mensagem de troca, chave pública derivada = a guardada na rede para a frase de teste pública.
    "osmosis": {"nome": "Osmosis", "tipo": "cosmos", "moeda": "OSMO", "cg": "osmosis", "dec": 6, "dex": "Osmosis", "expl": "https://www.mintscan.io/osmosis/tx/",
                "reserva": 0.3, "lcd": ["https://lcd.osmosis.zone", "https://osmosis-rest.publicnode.com"], "sqs": "https://sqs.osmosis.zone"},
    "unichain": {"nome": "Unichain", "tipo": "evm", "id": 130, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://uniscan.xyz/tx/",
                 "rpc": "https://mainnet.unichain.org", "router": "0x284f11109359a7e1306c3e447ef14d38400063ff",
                 "wrapped": "0x4200000000000000000000000000000000000006", "ponte": "0x078d782b760474a361dda0af3839290b0ef57ad6"},
}
EVM_CHAINS = [k for k, c in CHAINS.items() if c["tipo"] == "evm"]

# 0.32.246 (dono, 06/11/2026: abasteceu US$ 7 de gás e ficou sem poder comprar): gás tem limite próprio e não conta no das compras
# 0.32.329 (pedido do dono, 12/11): alertas do Dormant no Telegram, por conta (tg_on começa desligado)
TG_TIPOS = ("acordando", "pump", "dump", "acordou_chain")
CFG_DEFAULT = {"on": False, "max_usd": 50.0, "dia_usd": 200.0, "slip_pct": 3.0, "gas_max_usd": 10.0, "gas_dia_usd": 50.0, "cex_max_usd": 25.0, "cex_dia_usd": 100.0,
               "tg_on": False, "tg_tipos": list(TG_TIPOS)}
CFG_LIMITS = {"max_usd": (1.0, 10000.0), "dia_usd": (1.0, 50000.0), "slip_pct": (0.1, 15.0), "gas_max_usd": (1.0, 25.0), "gas_dia_usd": (1.0, 200.0), "cex_max_usd": (1.0, 5000.0), "cex_dia_usd": (1.0, 20000.0)}
CEX_NOMES = {"binance": "Binance", "bybit": "Bybit", "okx": "OKX", "kucoin": "KuCoin", "mexc": "MEXC", "nonkyc": "NonKYC"}
QUOTE_TTL_S = 60                  # depois disso a cotação vale nada e o botão pede outra
MAX_TRIES, LOCK_S = 5, 15 * 60    # 5 senhas erradas seguidas: compra e chaves travadas por 15 min (sobrevive ao reinício)
PENDENTE_S = 15 * 60              # compra sem confirmação segura outra na mesma rede por 15 min (nonce, compra dobrada)
EXPIRA_S = 6 * 3600               # sem nada depois disso: marca como não confirmada
RECIBO_S = 90
RECIBO_PASSO = 3
RESPOSTA_S = 8                    # 0.32.248: a tela recebe "enviada" depois disto; a confirmação segue por trás e a tela acompanha (o dono achou que tinha falhado)
PUBLICO_APOS_S = 30               # a MESMA transação assinada: mesmo hash, não compra duas vezes, e a folga de preço continua valendo
PRECO_AVISO, PRECO_BLOQ = 10.0, 25.0     # % pagando acima da CoinGecko
IMPACTO_AVISO, IMPACTO_BLOQ = 10.0, 25.0  # % que a própria compra move o preço (pool pequeno)
TAXA_TOKEN_MAX = 10.0
VENDA_BLOQ = 50.0                 # % abaixo da CoinGecko que barra a venda (dormente tem pool ruim: até aqui é só aviso)
# campo da GoPlus → motivo. Bloqueia = não deixa vender ou o dono mexe no saldo. Aviso = aparece, a decisão é do dono.
GP_BLOQ = {"is_honeypot": "honeypot: não deixa vender", "cannot_sell_all": "não deixa vender tudo", "cannot_buy": "não deixa comprar",
           "selfdestruct": "o contrato pode se autodestruir"}
# 0.32.263 (pedido do dono, caso BEAM 08/11/2026): "o dono pode mudar o saldo" deixou de barrar e virou aviso em qualquer moeda. No BEAM
# o poder é um burn(carteira, valor) nas mãos de um cofre 5 de 9 (Gnosis Safe), token da Binance e da Coinbase. O aviso aparece sempre e a
# compra só sai com a confirmação extra (risco=True), conferida também no servidor.
SALDO_TXT = "o dono pode mudar o saldo das carteiras: quem controla o contrato consegue apagar moedas da sua carteira"
GP_RISCO = {"owner_change_balance": SALDO_TXT}
SOL_RISCO = {"balance_mutable_authority": SALDO_TXT}
GP_AVISO = {"transfer_pausable": "o dono pode pausar as transferências", "is_blacklisted": "tem lista negra de carteiras",
            "hidden_owner": "dono escondido", "slippage_modifiable": "o dono pode mudar a taxa de venda",
            "trading_cooldown": "espera obrigatória entre compra e venda", "is_mintable": "o dono pode criar mais moedas",
            "is_proxy": "o contrato pode ser trocado pelo dono", "can_take_back_ownership": "o dono pode voltar a mandar no contrato"}
SOL_BLOQ = {"closable": "o dono pode fechar o token",
            "non_transferable": "o token não pode ser transferido"}
SOL_AVISO = {"freezable": "o dono pode congelar carteiras", "mintable": "o dono pode criar mais moedas",
             "metadata_mutable": "o dono pode mudar os dados do token", "transfer_hook": "o token roda um programa a cada transferência"}
ADDR_EVM = re.compile(r"^0x[0-9a-f]{40}$")
OSMO_DENOM = re.compile(r"^(ibc/[0-9A-F]{64}|factory/osmo1[02-9ac-hj-np-z]{38,58}/[A-Za-z0-9._-]{1,64}|u[a-z]{2,12})$")
ADA_UNIT = re.compile(r"^[0-9a-f]{56}(?:[0-9a-f]{2}){0,32}$")
MINSWAP = "https://agg-api.minswap.org/aggregator"
KOIOS = "https://api.koios.rest/api/v1"
ADA_ORDEM_PARADA_S = 10 * 60          # ordem ainda na DEX depois disso: o preço saiu da folga, a tela oferece cancelar
ADDR_SOL = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class BuyError(Exception):
    """Motivo já em linguagem de usuário. Nunca leva chave nem senha."""


def clean_cfg(raw: dict | None, base: dict | None = None) -> dict:
    out = {**CFG_DEFAULT, **{k: v for k, v in (base or {}).items() if k in CFG_DEFAULT}}
    for k, (lo, hi) in CFG_LIMITS.items():
        if k not in (raw or {}):
            continue
        try:
            v = float(raw[k])
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out[k] = round(min(hi, max(lo, v)), 4)
    return out


def buyable(watch, cid: str | None) -> list[str]:
    """Redes onde esta moeda pode ser comprada aqui. A principal vem primeiro."""
    if not cid:
        return []
    adr = watch.addr.get(cid) or {}
    first = watch.chain_of(cid)
    return sorted([k for k, v in adr.items() if k in CHAINS and valid_token(k, v)], key=lambda k: k != first)


def valid_token(chain: str, adr: str) -> bool:
    c = CHAINS.get(chain)
    if not c or not isinstance(adr, str):
        return False
    if c["tipo"] == "cardano":                      # policy (28 bytes) + nome (até 32 bytes), em hex, como a CoinGecko e a Minswap usam
        return bool(ADA_UNIT.match(adr.lower()))
    if c["tipo"] == "cosmos":                       # denominação da Osmosis: ibc/<hash>, factory/<criador>/<nome> ou nativa (u…)
        return bool(OSMO_DENOM.match(adr)) and adr != osmosis.NATIVE
    return bool(ADDR_SOL.match(adr)) if c["tipo"] == "solana" else bool(ADDR_EVM.match(adr.lower())) and adr.lower() != ZERO


def key_address(chain: str, text: str) -> str:
    """Endereço público da chave colada. ValueError com texto para a tela, sem o valor da chave."""
    if CHAINS[chain]["tipo"] == "solana":
        from .solana_wallet import parse_keypair
        return str(parse_keypair(text).pubkey())
    if CHAINS[chain]["tipo"] == "cardano":
        return cardano.address_of(text)
    if CHAINS[chain]["tipo"] == "cosmos":
        return osmosis.address_of(text)
    return evm.address_of(evm.parse_key(text))


def v2_data(c: dict, min_out: int, path: list, addr: str, deadline: int) -> str:
    return evm.call_data(c.get("swap_sel") or SEL_SWAP_ETH, min_out, path, addr, deadline)


def v3_data(tok_in: str, tok_out: str, fee: int, addr: str, deadline: int, amount: int, min_out: int) -> str:
    return (SEL_V3_SWAP + evm.w_addr(tok_in) + evm.w_addr(tok_out) + evm.w_int(fee) + evm.w_addr(addr) +
            evm.w_int(deadline) + evm.w_int(amount) + evm.w_int(min_out) + evm.w_int(0))


def v3_sell_data(tok_in: str, wrapped: str, fee: int, addr: str, deadline: int, amount: int, min_out: int) -> str:
    """Uniswap V3 entrega a moeda embrulhada: troca para o próprio roteador e ele desembrulha e paga a carteira, na mesma transação."""
    a = v3_data(tok_in, wrapped, fee, V3_ROUTER, deadline, amount, min_out)[2:]
    b = (SEL_UNWRAP + evm.w_int(min_out) + evm.w_addr(addr))[2:]
    def enc(h):
        return evm.w_int(len(h) // 2) + h + "0" * ((64 - len(h) % 64) % 64)
    ea, eb = enc(a), enc(b)
    return SEL_MULTI + evm.w_int(32) + evm.w_int(2) + evm.w_int(64) + evm.w_int(64 + len(ea) // 2) + ea + eb


def _i24(v: int) -> str:
    return (int(v) % (1 << 256)).to_bytes(32, "big").hex()


def _bytes_enc(h: str) -> str:
    return evm.w_int(len(h) // 2) + h + "0" * ((64 - len(h) % 64) % 64)


def _arr_bytes(items: list[str]) -> str:
    heads, tails, off = [], [], 32 * len(items)
    for h in items:
        t = _bytes_enc(h)
        heads.append(evm.w_int(off))
        tails.append(t)
        off += len(t) // 2
    return evm.w_int(len(items)) + "".join(heads) + "".join(tails)


def v4_key_enc(key: list) -> str:
    """PoolKey (currency0, currency1, fee, tickSpacing, hooks) em 5 palavras."""
    c0, c1, fee, ts, hooks = key
    return evm.w_addr(c0) + evm.w_addr(c1) + evm.w_int(fee) + _i24(ts) + evm.w_addr(hooks)


def v4_pool_id(key: list) -> str:
    return "0x" + evm.keccak256(bytes.fromhex(v4_key_enc(key))).hex()


def v4_quote_data(key: list, amount: int, zero_for_one: bool = True) -> str:
    return SEL_V4_QUOTE + evm.w_int(32) + v4_key_enc(key) + evm.w_int(1 if zero_for_one else 0) + evm.w_int(amount) + evm.w_int(32 * 8) + evm.w_int(0)


def v4_data(key: list, amount: int, min_out: int, deadline: int, sell: bool = False) -> str:
    """Universal Router execute(0x10 = V4_SWAP, [SWAP_EXACT_IN_SINGLE, SETTLE_ALL, TAKE_ALL]). Compra: paga ETH (currency0 = 0) e recebe o
    token. Venda (0.32.258): paga o token (o roteador puxa pelo Permit2) e recebe ETH. Mesmo formato da compra e da venda de GLC na Pons de
    07/11/2026 (tx 0x7d5bf818… e 0x93c2bfdb…, decodificadas e reproduzidas byte a byte no teste). O que sai cai em quem chamou (TAKE_ALL paga
    o msg.sender = a própria carteira); menos que min_out e a transação é recusada."""
    p0 = (evm.w_int(32) + v4_key_enc(key) + evm.w_int(0 if sell else 1) + evm.w_int(amount) + evm.w_int(min_out) + evm.w_int(0)
          + evm.w_int(32 * 10) + evm.w_int(0))
    paga, recebe = (key[1], key[0]) if sell else (key[0], key[1])
    p1 = evm.w_addr(paga) + evm.w_int(amount)
    p2 = evm.w_addr(recebe) + evm.w_int(min_out)
    acts = _bytes_enc("060c0f")
    inp = evm.w_int(64) + evm.w_int(64 + len(acts) // 2) + acts + _arr_bytes([p0, p1, p2])
    cmds = _bytes_enc("10")
    return SEL_UR_EXEC + evm.w_int(96) + evm.w_int(96 + len(cmds) // 2) + evm.w_int(deadline) + cmds + _arr_bytes([inp])


def v4_swap_eth(logs: list, pm: str) -> int:
    """ETH que a venda tirou do pool, pelo evento Swap do PoolManager (amount0 em int128; na venda os dois lados têm sinais opostos)."""
    def s(w: int) -> int:
        return w - (1 << 256) if w >> 255 else w
    for lg in logs:
        tp = lg.get("topics") or []
        if (lg.get("address") or "").lower() == pm and tp and tp[0] == T_V4_SWAP:
            w = evm.words(lg.get("data") or "0x")
            if len(w) >= 2:
                a0, a1 = s(w[0]), s(w[1])
                if a0 and a1 and (a0 > 0) != (a1 > 0):
                    return abs(a0)
    return 0


def v4_key_from_log(log: dict) -> list | None:
    """Evento Initialize do PoolManager → PoolKey. None se o formato não bater."""
    try:
        t, d = log["topics"], bytes.fromhex(log["data"][2:])
        ts = int.from_bytes(d[32:64], "big")
        return ["0x" + t[2][-40:].lower(), "0x" + t[3][-40:].lower(), int.from_bytes(d[0:32], "big"),
                ts - (1 << 256) if ts >> 255 else ts, "0x" + d[76:96].hex()]
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def judge_goplus(chain: str, d: dict | None) -> tuple[list[str], list[str]]:
    """(bloqueia, avisos) da resposta da GoPlus."""
    if d is None:
        return [], ["não deu para consultar a segurança do token na GoPlus agora"]
    if not d:
        return [], ["a GoPlus não tem dados de segurança deste token"]
    if CHAINS[chain]["tipo"] == "solana":
        st = lambda k: str((d.get(k) or {}).get("status") if isinstance(d.get(k), dict) else d.get(k) or "").strip()  # noqa: E731
        return [v for k, v in SOL_BLOQ.items() if st(k) == "1"], [v for k, v in {**SOL_RISCO, **SOL_AVISO}.items() if st(k) == "1"]
    bloq = [v for k, v in GP_BLOQ.items() if str(d.get(k, "")).strip() == "1"]
    avis = [v for k, v in {**GP_RISCO, **GP_AVISO}.items() if str(d.get(k, "")).strip() == "1"]
    for k, nome in (("buy_tax", "compra"), ("sell_tax", "venda")):
        try:
            v = float(d.get(k)) * 100
        except (TypeError, ValueError):
            continue
        if v > TAXA_TOKEN_MAX:
            bloq.append(f"taxa de {nome} do token {v:.0f}% (máx. {TAXA_TOKEN_MAX:g}%)")
        elif v > 0.5:
            avis.append(f"o token cobra {v:.1f}% de taxa na {nome}")
    return bloq, avis


def window_pct(px_now: float | None, spark: list | None, h: int, buy_t: float, px_in: float | None, now: float) -> tuple[float | None, float | None]:
    """(variação %, preço de referência) da janela. Comprou dentro dela: conta só desde a compra, pelo preço pago."""
    if not px_now:
        return None, None
    ref = None
    if buy_t >= now - h * 3600:
        ref = px_in
    elif spark and len(spark) >= h * 0.95:           # sparkline da CoinGecko: um ponto por hora, o último é o mais recente
        ref = spark[max(0, len(spark) - 1 - h)]
    if not ref:
        return None, None
    return round((px_now / ref - 1) * 100, 2), ref


def holdings(rows: list[dict], watch, now: float, janelas=(1, 12, 24, 168), sells: list[dict] | None = None) -> dict:
    """Linhas do histórico e a carteira somada, nas janelas de 1 h, 12 h, 24 h, 7 dias e no total. As vendas confirmadas abatem as
    compras mais antigas do mesmo token: o que sobrou vale o preço de agora, o que foi vendido vale o que entrou de verdade."""
    itens, soma_agora, soma_custo, soma_rec = [], 0.0, 0.0, 0.0
    soma_ref: dict[int, list[float]] = {h: [0.0, 0.0] for h in janelas}
    baixa: dict[str, tuple[float, float]] = {}
    pool: dict[tuple, list] = {}
    for x in sorted([s for s in sells or [] if s.get("status") == "confirmada" and s.get("qty")], key=lambda s: _ts(s.get("em"))):
        pool.setdefault((x.get("rede"), x.get("token")), []).append([float(x["qty"]), float(x["usd_out"] or 0) - float(x.get("gas_usd") or 0), float(x["qty"])])
    for r in sorted([r for r in rows if r.get("status") == "confirmada" and r.get("qty")], key=lambda r: _ts(r.get("em"))):
        falta, vend, rec = float(r["qty"]), 0.0, 0.0
        for v in pool.get((r.get("rede"), r.get("token"))) or []:
            n = min(falta, v[0])
            if n > 0:
                vend += n
                rec += v[1] * n / v[2]
                v[0] -= n
                falta -= n
        baixa[r.get("id")] = (vend, rec)
    for r in rows:
        d = dict(r)
        d["t"] = _ts(r.get("em"))
        c = CHAINS.get(r.get("rede")) or {}
        d["rede_nome"], d["moeda"], d["expl"] = c.get("nome"), c.get("moeda"), c.get("expl")
        if str(r.get("rede") or "").startswith("cex:"):      # 0.32.247: compra em exchange (não dá para vender daqui ainda)
            d["rede_nome"], d["moeda"], d["cex"] = CEX_NOMES.get(r["rede"][4:], r["rede"][4:]), "USDT", True
        if r.get("status") == "confirmada" and r.get("qty"):
            row = watch.rows.get(r.get("cg")) or {}
            px = row.get("current_price")
            spk = [float(x) for x in ((row.get("sparkline_in_7d") or {}).get("price") or []) if x]
            custo = float(r.get("usd_in") or 0) + float(r.get("gas_usd") or 0)
            vend, rec = baixa.get(r.get("id"), (0.0, 0.0))
            resto = max(0.0, float(r["qty"]) - vend)
            if resto < float(r["qty"]) * 1e-9:     # sobra de arredondamento não é saldo
                resto = 0.0
            d["custo"], d["px_agora"], d["img"], d["vendido"], d["recebido"], d["resto"] = round(custo, 4), px, row.get("image"), vend, round(rec, 4), resto
            for h in janelas:
                pct, ref = window_pct(px, spk, h, d["t"], r.get("px_in"), now) if resto else (None, None)
                d[f"h{h}"] = pct
                if pct is not None:
                    soma_ref[h][0] += resto * px
                    soma_ref[h][1] += resto * ref
            if px or not resto:
                v = resto * (px or 0)
                d["valor"], d["ganho"], d["total"] = round(v, 4), round(v + rec - custo, 4), round(((v + rec) / custo - 1) * 100, 2) if custo else None
                soma_agora += v
                soma_custo += custo
                soma_rec += rec
        itens.append(d)
    res = {"investido": round(soma_custo, 2), "valor": round(soma_agora, 2), "recebido": round(soma_rec, 2), "ganho": round(soma_agora + soma_rec - soma_custo, 2),
           "total": round(((soma_agora + soma_rec) / soma_custo - 1) * 100, 2) if soma_custo else None}
    for h in janelas:
        a, b = soma_ref[h]
        res[f"h{h}"] = round((a / b - 1) * 100, 2) if b else None
    return {"itens": itens, "resumo": res, "leitura_t": watch.stat.get("leitura_t")}


def _ts(v) -> float:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class Buyer:
    """Uma instância por servidor. db = SupaREST; box = SecretBox; watch = DormantWatch."""

    def __init__(self, http, db, box, watch, allowed=None, sys_key=None):
        self.http, self.db, self.box, self.watch = http, db, box, watch
        self.allowed = allowed or (lambda: False)
        self.sys_key = sys_key or (lambda name: "")
        self.quotes: dict[str, dict] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._gp: dict[tuple, tuple] = {}
        self._px: dict[str, tuple] = {}
        self._jq = None
        self._v4keys: dict[str, list | None] = {}           # id do pool → PoolKey conferida (não muda nunca)
        self._v4tok: dict[tuple, tuple] = {}                # (rede, token) → (quando, pools com ETH da GeckoTerminal)

    def lock(self, uid: str) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    async def _early(self, coro):
        """Devolve o resultado se ficar pronto em RESPOSTA_S; senão None, e o trabalho continua até terminar (a linha no banco é atualizada)."""
        task = asyncio.ensure_future(coro)
        bg = self.__dict__.setdefault("_bg", set())
        bg.add(task)

        def done(t):
            bg.discard(t)
            if not t.cancelled() and t.exception() is not None and not isinstance(t.exception(), BuyError):
                log.error("Dormant: acompanhamento da transação parou: %s", type(t.exception()).__name__)
        task.add_done_callback(done)
        try:
            return await asyncio.wait_for(asyncio.shield(task), RESPOSTA_S)
        except asyncio.TimeoutError:
            return None

    # ------------------------------------------------------------------ rede
    async def rpc(self, url: str, method: str, params: list):
        try:
            r = await self.http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                     headers={"User-Agent": "pump-fun-copy/1.0"}, timeout=20)
            js = r.json()
        except Exception as e:                     # só o tipo: o endereço do RPC pode levar chave de API
            raise BuyError(f"a rede não respondeu ({type(e).__name__})") from None
        if not isinstance(js, dict):
            raise BuyError("a rede respondeu sem dados")
        if js.get("error"):
            e = js["error"]
            raise BuyError(str(e.get("message") if isinstance(e, dict) else e)[:160])
        return js.get("result")

    async def native_usd(self, chain: str) -> float | None:
        cg = CHAINS[chain]["cg"]
        hit = self._px.get(cg)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        v = None
        try:
            d = await self.watch.get("/simple/price", {"ids": cg, "vs_currencies": "usd"})
            v = float(((d or {}).get(cg) or {}).get("usd") or 0) or None
        except Exception:
            v = None
        if not v:                                  # CoinGecko pediu para esperar: serve a leitura da lista, se recente
            row = self.watch.rows.get(cg) or {}
            lido = self.watch.stat.get("leitura_t") or 0
            v = row.get("current_price") if time.time() - lido < 3600 else None
        if v:
            self._px[cg] = (time.time(), float(v))
        return float(v) if v else None

    async def goplus(self, chain: str, token: str) -> dict | None:
        k = (chain, token)
        hit = self._gp.get(k)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        c = CHAINS[chain]
        if c["tipo"] in ("cardano", "cosmos"):     # a GoPlus não cobre Cardano nem Osmosis: aparece o aviso "sem dados de segurança"
            return {}
        url = ("https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses=" + token if c["tipo"] == "solana"
               else f"https://api.gopluslabs.io/api/v1/token_security/{c['id']}?contract_addresses={token}")
        try:
            js = (await self.http.get(url, timeout=10)).json()
            res = (js or {}).get("result") or {}
            d = res.get(token) or res.get(token.lower()) or {}
        except Exception:
            return None
        self._gp[k] = (time.time(), d)
        if len(self._gp) > 500:
            self._gp.clear()
        return d

    # ------------------------------------------------------------------ 0.32.245: saldo e máximo de compra, antes de digitar o valor
    async def limit_info(self, uid: str, chain: str) -> dict:
        c = CHAINS.get(chain)
        if not c:
            raise BuyError("rede inválida")
        cfg = await self.cfg(uid)
        wal = await self.wallet_row(uid, chain)
        usd_n = await self.native_usd(chain)
        gasto = await self.spent_today(uid)
        resta = max(0.0, cfg["dia_usd"] - gasto)
        saldo, reserva = None, 0.0
        if wal:
            try:
                if c["tipo"] == "solana":
                    saldo, reserva = (await self.rpc(self.sol_rpc(), "getBalance", [wal["endereco"]]))["value"] / 1e9, c["reserva"]
                elif c["tipo"] == "cardano":
                    saldo, reserva = (await self._ada_wallet(wal["endereco"]))[0] / 1e6, c["reserva"] + 4.0   # depósito e taxas da DEX
                elif c["tipo"] == "cosmos":
                    saldo, reserva = await self._osmo_bal(wal["endereco"], osmosis.NATIVE) / 1e6, c["reserva"]
                else:
                    saldo = int(await self.rpc(c["rpc"], "eth_getBalance", [wal["endereco"], "latest"]) or "0x0", 16) / 1e18
                    reserva = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16) * c.get("gas_mult", 1.1) * 300000 * 1.3 / 1e18   # o gás da própria compra
            except (BuyError, KeyError, TypeError, ValueError):
                saldo = None
        out = {"moeda": c["moeda"], "usd_n": usd_n, "tem_carteira": bool(wal), "saldo": saldo, "saldo_usd": saldo * usd_n if saldo is not None and usd_n else None, "reserva_gas": reserva,
               "limite_compra_usd": cfg["max_usd"], "limite_dia_usd": cfg["dia_usd"], "gasto_dia_usd": gasto, "resta_dia_usd": round(resta, 2), "ligado": cfg["on"], "max_nativo": None, "max_usd": None, "limitado_por": None}
        if usd_n:
            caps = [(cfg["max_usd"], "seu limite por compra"), (resta, "o que sobra do seu limite de 24 h")]
            if saldo is not None:
                caps.append((max(0.0, saldo - reserva) * usd_n, "o saldo da carteira (fica o gás da compra)"))
            m, por = min(caps, key=lambda x: x[0])
            out.update(max_nativo=math.floor(m / usd_n * 1e8) / 1e8, max_usd=round(m, 2), limitado_por=por)
        return out

    # ------------------------------------------------------------------ cotação EVM
    async def _call(self, c: dict, to: str, data: str) -> str | None:
        try:
            return await self.rpc(c["rpc"], "eth_call", [{"to": to, "data": data}, "latest"])
        except BuyError:
            return None                            # rota sem pool responde erro: é só "não há esta rota"

    async def _v2_out(self, c: dict, value: int, path: list) -> int:
        w = evm.words(await self._call(c, c["router"], evm.call_data(SEL_AMOUNTS, value, path)) or "0x")
        return w[-1] if len(w) >= 2 + len(path) else 0

    async def _v3_out(self, c: dict, value: int, token: str, fee: int) -> int:
        data = SEL_V3_QUOTE + evm.w_addr(c["wrapped"]) + evm.w_addr(token) + evm.w_int(value) + evm.w_int(fee) + evm.w_int(0)
        w = evm.words(await self._call(c, V3_QUOTER, data) or "0x")
        return w[0] if w else 0

    async def _v4_out(self, c: dict, value: int, key: list, chain: str, zero_for_one: bool = True) -> int:
        w = evm.words(await self._call(c, V4[chain]["quoter"], v4_quote_data(key, value, zero_for_one)) or "0x")
        return w[0] if w else 0

    async def _route_out(self, c: dict, rt: dict, value: int, token: str) -> int:
        if rt["tipo"] == "v4":
            return await self._v4_out(c, value, rt["key"], rt["rede"])
        return await (self._v3_out(c, value, token, rt["fee"]) if rt["tipo"] == "v3" else self._v2_out(c, value, rt["path"]))

    async def _v4_block_at(self, c: dict, ts: float) -> int:
        """Bloco perto de uma hora (busca binária, ~25 leituras). A rede só aceita eth_getLogs em trechos de até 10 milhões de blocos."""
        lo, hi = 0, int(await self.rpc(c["rpc"], "eth_blockNumber", []) or "0x0", 16)
        while hi - lo > 2000:
            mid = (lo + hi) // 2
            b = await self.rpc(c["rpc"], "eth_getBlockByNumber", [hex(mid), False]) or {}
            lo, hi = (mid, hi) if int(b.get("timestamp") or "0x0", 16) < ts else (lo, mid)
        return lo

    async def _v4_key(self, chain: str, pid: str, created: str | None, token: str) -> list | None:
        if pid in self._v4keys:
            return self._v4keys[pid]
        c, key = CHAINS[chain], None
        try:
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp()
            b = await self._v4_block_at(c, ts)
            logs = await self.rpc(c["rpc"], "eth_getLogs", [{"address": V4[chain]["pm"], "topics": [T_V4_INIT, pid],
                                                             "fromBlock": hex(max(0, b - V4_LOG_SPAN)), "toBlock": hex(b + V4_LOG_SPAN)}]) or []
            for lg in logs:
                k = v4_key_from_log(lg)
                if k and v4_pool_id(k) == pid and k[0] == ZERO and k[1] == token:
                    key = k
                    break
        except (BuyError, ValueError, TypeError):
            return None                              # falha de leitura: tenta de novo na próxima cotação
        self._v4keys[pid] = key
        return key

    async def _v4_pools(self, chain: str, token: str) -> list[dict]:
        """Pools V4 do token que pagam com ETH, os de mais dinheiro primeiro (GeckoTerminal só aponta; tudo é conferido na rede)."""
        now = time.time()
        hit = self._v4tok.get((chain, token))
        if hit and now - hit[0] < V4_TTL_S:
            pools = hit[1]
        else:
            pools = []
            try:
                r = await self.http.get(f"{GT_API}/networks/{V4[chain]['gt']}/tokens/{token}/pools", headers={"accept": "application/json"}, timeout=15)
                for p in (r.json() or {}).get("data") or []:
                    a, rel = p.get("attributes") or {}, p.get("relationships") or {}
                    pid = str(a.get("address") or "").lower()
                    lados = {str(((rel.get(x) or {}).get("data") or {}).get("id") or "").split("_")[-1].lower() for x in ("base_token", "quote_token")}
                    if re.fullmatch(r"0x[0-9a-f]{64}", pid) and lados == {ZERO, token}:
                        pools.append({"pid": pid, "criado": a.get("pool_created_at"), "usd": float(a.get("reserve_in_usd") or 0),
                                      "dex": ((rel.get("dex") or {}).get("data") or {}).get("id") or ""})
            except Exception:                        # GeckoTerminal fora: fica sem V4 nesta cotação
                pools = []
            pools = sorted(pools, key=lambda x: -x["usd"])[:V4_POOLS_MAX]
            self._v4tok[(chain, token)] = (now, pools)
        out = []
        for p in pools:
            key = await self._v4_key(chain, p["pid"], p["criado"], token)
            if key:
                out.append({"tipo": "v4", "rede": chain, "key": key, "dex": V4_DEX.get(p["dex"], "Uniswap V4"),
                            "rota": "pool V4" + (" com contrato extra (hook)" if key[4] != ZERO else ""), "hook": key[4] != ZERO})
        return out

    async def evm_best(self, chain: str, token: str, value: int) -> dict | None:
        c = CHAINS[chain]
        cands = [{"tipo": "v2", "path": [c["wrapped"], token], "dex": c["dex"].split(" e ")[0], "rota": "direta"}]
        if c.get("ponte") and token != c["ponte"]:
            cands.append({"tipo": "v2", "path": [c["wrapped"], c["ponte"], token], "dex": c["dex"].split(" e ")[0], "rota": "passando por dólar"})
        if c.get("v3"):
            cands += [{"tipo": "v3", "fee": f, "dex": "Uniswap V3", "rota": f"pool de {f / 10000:g}%"} for f in V3_FEES]
        if chain in V4:
            cands += await self._v4_pools(chain, token)
        outs = await asyncio.gather(*[self._route_out(c, rt, value, token) for rt in cands])
        best, out = None, 0
        for rt, o in zip(cands, outs):
            if o > out:
                best, out = rt, o
        return {**best, "out": out} if best else None

    # ------------------------------------------------------------------ cotação
    async def preview(self, uid: str, key: str, chain: str, amount) -> dict:
        """Mostra tudo antes da compra. Só devolve quote_id se nada bloquear; quem compra não manda preço nenhum."""
        w = self.watch
        m = next((x for x in w.todas() if x["cmc"] == key), None)
        if m is None:
            raise BuyError("esta moeda não está na lista")
        it = w.item(m)
        cid = it.get("cg")
        if chain not in buyable(w, cid):
            raise BuyError("esta moeda não pode ser comprada nesta rede por aqui")
        c = CHAINS[chain]
        await self.resolve_pending(uid)            # 0.32.247: a compra pode já ter confirmado; sem isto ficava bloqueado até abrir Minhas compras
        token = w.addr[cid][chain]
        token = token if c["tipo"] in ("solana", "cosmos") else token.lower()      # denominação da Osmosis diferencia maiúsculas
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            raise BuyError("valor inválido") from None
        if not math.isfinite(amt) or amt <= 0:
            raise BuyError("valor inválido")
        value = int(amt * 10 ** c["dec"])
        if value <= 0:
            raise BuyError("valor pequeno demais")
        cfg = await self.cfg(uid)
        wal = await self.wallet_row(uid, chain)
        bloq: list[str] = []
        avisos: list[str] = []
        if not self.allowed():
            bloq.append("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
        if not cfg["on"]:
            bloq.append("as compras estão desligadas em Carteiras e compra")
        if not wal:
            bloq.append(f"cadastre a carteira da rede {c['nome']} em Carteiras e compra")
        usd_n = await self.native_usd(chain)
        usd_in = amt * usd_n if usd_n else None
        if usd_in is None:
            bloq.append(f"sem a cotação de {c['moeda']} em dólar: sem ela os limites não valem")
        else:
            if usd_in > cfg["max_usd"]:
                bloq.append(f"passa do seu limite por compra (${cfg['max_usd']:g})")
            gasto = await self.spent_today(uid)
            if gasto + usd_in > cfg["dia_usd"]:
                bloq.append(f"passa do seu limite por dia (${cfg['dia_usd']:g}; já foram ${gasto:.2f} nas últimas 24 h)")
        if await self.pending_on(uid, chain):
            bloq.append("há uma compra sem confirmação nesta rede: espere ela terminar (veja Minhas compras)")
        gb, ga = judge_goplus(chain, await self.goplus(chain, token))
        bloq += gb
        avisos += ga
        q = {"uid": uid, "key": key, "cg": cid, "rede": chain, "token": token, "value": value, "amt": amt, "usd_n": usd_n, "usd_in": usd_in,
             "nome": it.get("nome"), "simbolo": it.get("simbolo"), "t": time.time(), "slip": cfg["slip_pct"], "end": (wal or {}).get("endereco"),
             "risco": SALDO_TXT in ga}
        if c["tipo"] == "solana":
            det = await self._preview_sol(q, wal, bloq, avisos)
        elif c["tipo"] == "cardano":
            det = await self._preview_ada(q, wal, bloq, avisos)
        elif c["tipo"] == "cosmos":
            det = await self._preview_osmo(q, wal, bloq, avisos)
        else:
            det = await self._preview_evm(q, wal, bloq, avisos)
        px_cg = it.get("preco")
        if usd_in and det.get("qty") and px_cg:
            pago = usd_in / det["qty"]
            dif = (pago / px_cg - 1) * 100
            det["px_pago"], det["px_cg"], det["dif_cg"] = pago, px_cg, round(dif, 2)
            if dif > PRECO_BLOQ:
                bloq.append(f"o preço na DEX está {dif:.0f}% acima da CoinGecko: pool errado, manipulado ou sem dinheiro")
            elif dif > PRECO_AVISO:
                avisos.append(f"o preço na DEX está {dif:.0f}% acima da CoinGecko (lida a cada 20 min)")
        elif det.get("qty"):
            avisos.append("sem preço da CoinGecko para comparar")
        imp = det.get("impacto")
        if imp is not None:
            if imp > IMPACTO_BLOQ:
                bloq.append(f"esta compra moveria o preço em {imp:.0f}%: pool pequeno para este valor")
            elif imp > IMPACTO_AVISO:
                avisos.append(f"esta compra move o preço em {imp:.0f}%: pool pequeno para este valor")
        out = {"moeda": {"nome": q["nome"], "simbolo": q["simbolo"], "img": it.get("img")}, "rede": chain, "rede_nome": c["nome"], "token": token,
               "moeda_rede": c["moeda"], "valor": amt, "usd": usd_in, "carteira": q["end"], "slip": cfg["slip_pct"], "bloqueia": bloq, "avisos": avisos, "risco": q["risco"], **det}
        if not bloq:
            self._prune()
            qid = uuid.uuid4().hex
            self.quotes[qid] = q
            out.update(quote_id=qid, validade_s=QUOTE_TTL_S)
        return out

    async def _preview_evm(self, q: dict, wal: dict | None, bloq: list, avisos: list) -> dict:
        c = CHAINS[q["rede"]]
        rt = await self.evm_best(q["rede"], q["token"], q["value"])
        if not rt:
            bloq.append(f"nenhum pool com a moeda da rede em {c['dex']} para este token")
            return {"dex": c["dex"]}
        w = evm.words(await self._call(c, q["token"], SEL_DECIMALS) or "0x")
        dec = w[0] if w else None
        if dec is None or dec > 36:
            bloq.append("o contrato do token não informa as casas decimais")
            return {"dex": rt["dex"], "rota": rt["rota"]}
        min_out = rt["out"] * (10000 - int(q["slip"] * 100)) // 10000
        q.update(route={k: v for k, v in rt.items() if k != "out"}, min_out=min_out, dec=dec)
        if rt.get("hook"):
            avisos.append(f"o pool tem um contrato extra (hook {rt['key'][4][:8]}…) que roda em cada troca: o valor mostrado vem da simulação "
                          "dele, e a compra é recusada pela rede se receber menos que o mínimo.")
        small = await self._route_out(c, rt, max(q["value"] // 50, 1), q["token"])
        impacto = round(max(0.0, (1 - rt["out"] / (small * 50)) * 100), 2) if small else None
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        q["gp"] = gp
        gas, gas_nat = 300000, None
        if wal:
            bal = int(await self.rpc(c["rpc"], "eth_getBalance", [wal["endereco"], "latest"]) or "0x0", 16)
            if bal < q["value"]:
                bloq.append(f"saldo insuficiente: a carteira tem {bal / 1e18:.6f} {c['moeda']}")
            else:
                try:
                    to, data = self._evm_tx(q, min_out, wal["endereco"])
                    gas = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": wal["endereco"], "to": to, "data": data, "value": hex(q["value"])}]), 16)
                except BuyError as e:
                    bloq.append("a rede recusou na simulação: " + str(e))
            gas_nat = gas * gp / 1e18
            if bal < q["value"] + int(gas * 1.3) * gp and bal >= q["value"]:
                bloq.append(f"falta {c['moeda']} para pagar o gás: use Abastecer em Carteiras e compra")
        gas_usd = (gas_nat if gas_nat is not None else gas * gp / 1e18) * (q["usd_n"] or 0)
        if q["usd_in"] and gas_usd > q["usd_in"] * 0.25:
            avisos.append(f"o gás (${gas_usd:.2f}) passa de 25% do valor da compra")
        return {"dex": rt["dex"], "rota": rt["rota"], "recebe": rt["out"] / 10 ** dec, "qty": rt["out"] / 10 ** dec, "minimo": min_out / 10 ** dec,
                "impacto": impacto, "gas_usd": round(gas_usd, 4)}

    def _evm_tx(self, q: dict, min_out: int, addr: str) -> tuple[str, str]:
        """Destino e dados: sempre o roteador fixo daqui, recebedor sempre a própria carteira."""
        c, rt = CHAINS[q["rede"]], q["route"]
        dl = int(time.time()) + 300
        if rt["tipo"] == "v3":
            return V3_ROUTER, v3_data(c["wrapped"], q["token"], rt["fee"], addr, dl, q["value"], min_out)
        if rt["tipo"] == "v4":                       # o recebedor é quem assina (TAKE_ALL paga o msg.sender): nada a passar
            return self._v4_checked(q), v4_data(rt["key"], q["value"], min_out, dl)
        return c["router"], v2_data(c, min_out, rt["path"], addr, dl)

    # ------------------------------------------------------------------ cotação Solana
    def jup(self):
        from .jupiter import JupiterQuoter
        if self._jq is None or self._jq[0] != self.sys_key("jupiter_api_key"):
            k = self.sys_key("jupiter_api_key")
            self._jq = (k, JupiterQuoter(self.http, k))
        return self._jq[1]

    def sol_rpc(self) -> str:
        from .solana_wallet import PUBLIC_RPC, check_rpc_url
        u = self.sys_key("rpc_url")
        if u:
            try:
                return check_rpc_url(u)
            except ValueError:
                pass
        return PUBLIC_RPC

    async def _jup_quote(self, q: dict, inp: str = WSOL, out: str | None = None, amount: int | None = None) -> dict | None:
        jq = self.jup()
        await jq._jup_wait()
        try:
            r = await self.http.get(f"{jq.jup_base}/swap/v1/quote", headers=jq.jup_headers, timeout=10,
                                    params={"inputMint": inp, "outputMint": out or q["token"], "amount": str(amount if amount is not None else q["value"]),
                                            "slippageBps": int(q["slip"] * 100), "restrictIntermediateTokens": "true"})
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def _sol_decimals(self, mint: str) -> int | None:
        try:
            return int((await self.rpc(self.sol_rpc(), "getTokenSupply", [mint]))["value"]["decimals"])
        except Exception:
            return None

    async def _preview_sol(self, q: dict, wal: dict | None, bloq: list, avisos: list) -> dict:
        jq = await self._jup_quote(q)
        if not jq or not int(jq.get("outAmount") or 0):
            bloq.append("a Jupiter não achou rota para este token")
            return {"dex": "Jupiter"}
        dec = await self._sol_decimals(q["token"])
        if dec is None:
            bloq.append("não consegui ler as casas decimais do token")
            return {"dex": "Jupiter"}
        out, thr = int(jq["outAmount"]), int(jq.get("otherAmountThreshold") or 0)
        q.update(min_out=thr, dec=dec)
        if wal:
            try:
                bal = (await self.rpc(self.sol_rpc(), "getBalance", [wal["endereco"]]))["value"]
                if bal < q["value"] + int(CHAINS["solana"]["reserva"] * 1e9):
                    bloq.append(f"saldo insuficiente: a carteira tem {bal / 1e9:.4f} SOL (fica {CHAINS['solana']['reserva']:g} SOL para as taxas); use Abastecer em Carteiras e compra")
            except (BuyError, KeyError, TypeError):
                bloq.append("não consegui ler o saldo da carteira")
        labels = [((r.get("swapInfo") or {}).get("label") or "?") for r in (jq.get("routePlan") or [])]
        try:
            imp = round(float(jq.get("priceImpactPct") or 0) * 100, 2)
        except (TypeError, ValueError):
            imp = None
        usd = (q["usd_n"] or 0) * 0.0025
        return {"dex": "Jupiter", "rota": " → ".join(labels[:4]), "recebe": out / 10 ** dec, "qty": out / 10 ** dec, "minimo": thr / 10 ** dec,
                "impacto": imp, "gas_usd": round(usd, 4)}

    # ------------------------------------------------------------------ compra
    def _prune(self) -> None:
        now = time.time()
        for k in [k for k, v in self.quotes.items() if now - v["t"] > QUOTE_TTL_S]:
            del self.quotes[k]

    async def buy(self, uid: str, quote_id: str, senha: str, confirmar: str, risco: bool = False) -> dict:
        if confirmar != "COMPRAR":
            raise BuyError("digite COMPRAR para confirmar")
        rq = self.quotes.get(str(quote_id or ""))
        if rq and rq.get("risco") and risco is not True:
            raise BuyError("o dono deste token pode mudar o saldo das carteiras: marque que você entende o risco")
        async with self.lock(uid):                 # uma compra por vez por conta: sem compra dobrada nem nonce repetido
            self._prune()
            q = self.quotes.get(str(quote_id or ""))
            if not q or q["uid"] != uid or q.get("lado"):
                raise BuyError("esta cotação venceu: peça outra")
            cfg = await self.cfg(uid)
            if not self.allowed():
                raise BuyError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            if not cfg["on"]:
                raise BuyError("as compras estão desligadas em Carteiras e compra")
            wal = await self.wallet_row(uid, q["rede"])
            if not wal or wal["endereco"] != q["end"]:
                raise BuyError("a carteira desta rede mudou: peça outra cotação")
            secret = await self._open(uid, wal, senha)       # senha errada não gasta a cotação, mas conta tentativa
            self.quotes.pop(quote_id, None)                  # daqui em diante a cotação é de uso único
            gasto = await self.spent_today(uid)
            if q["usd_in"] > cfg["max_usd"] or gasto + q["usd_in"] > cfg["dia_usd"]:
                raise BuyError("passa dos seus limites em dólar")
            if await self.pending_on(uid, q["rede"]):
                raise BuyError("há uma compra sem confirmação nesta rede: espere ela terminar")
            if CHAINS[q["rede"]]["tipo"] == "solana":
                return await self._buy_sol(q, wal, secret)
            if CHAINS[q["rede"]]["tipo"] == "cardano":
                return await self._buy_ada(q, wal, secret)
            if CHAINS[q["rede"]]["tipo"] == "cosmos":
                return await self._buy_osmo(q, wal, secret)
            return await self._buy_evm(q, wal, secret)

    def _row(self, q: dict, wal: dict, tx: str | None, dex: str | None, rota: str | None) -> dict:
        return {"id": uuid.uuid4().hex, "user_id": q["uid"], "em": _iso(time.time()), "rede": q["rede"], "cmc": q["key"], "cg": q["cg"], "nome": q["nome"], "simbolo": q["simbolo"],
                "token": q["token"], "endereco": wal["endereco"], "dex": dex, "rota": rota, "nativo": q["amt"], "nativo_usd": q["usd_n"], "usd_in": q["usd_in"],
                "casas": q.get("dec"), "tx": tx, "status": "enviando"}

    async def _finish(self, row: dict, **v) -> dict:
        row.update(v)
        await self.db.update("dormant_buys", {"id": row["id"], "user_id": row["user_id"]}, v)
        return row

    async def _buy_evm(self, q: dict, wal: dict, secret: str) -> dict:
        c = CHAINS[q["rede"]]
        cid = int(await self.rpc(c["rpc"], "eth_chainId", []) or "0x0", 16)
        if cid != c["id"]:
            raise BuyError("o RPC respondeu de outra rede: nada foi enviado")
        addr = wal["endereco"]
        key = evm.parse_key(secret)
        if evm.address_of(key) != addr:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        out = await self._route_out(c, q["route"], q["value"], q["token"])
        if out < q["min_out"]:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        to, data = self._evm_tx(q, q["min_out"], addr)
        est = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": hex(q["value"])}]), 16)
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        if q.get("gp") and gp > q["gp"] * 2:
            raise BuyError("o gás mais que dobrou desde a cotação: nada foi enviado, peça outra cotação")
        gp = int(gp * c.get("gas_mult", 1.1))
        gas = int(est * 1.3) + 20000
        bal = int(await self.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        if bal < q["value"] + gas * gp:
            raise BuyError(f"falta {c['moeda']} para pagar a compra e o gás: nada foi enviado")
        nonce = int(await self.rpc(c["rpc"], "eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, gas, to, q["value"], data, c["id"])
        rt = q["route"]
        # grava ANTES de enviar: se o servidor cair aqui, a compra aparece e o limite do dia conta
        row = self._row(q, wal, h, rt["dex"], rt["rota"])
        await self.db.insert("dormant_buys", row)
        self.watch.held.add(q["cg"])
        async def rest():
            try:
                rc = await self._evm_send(c, raw, h)
            except BuyError as e:
                await self._finish(row, status="falhou", motivo=str(e)[:160])
                raise
            if rc:
                return self._public(await self._apply_evm(row, rc, gp))
            await self._finish(row, status="pendente", motivo="sem confirmação em 90 s: confira em Minhas compras")
            return self._public(row)
        return await self._early(rest()) or self._public(row)

    async def _evm_send(self, c: dict, raw: str, h: str) -> dict | None:
        """Envia e espera o recibo. Primeiro pelo caminho protegido, se a rede tiver; sem entrar a tempo, a mesma transação vai para a fila pública."""
        priv = c.get("envio")
        sent, why = False, ""
        for url in dict.fromkeys([priv or c["rpc"], c["rpc"]]):
            try:
                await self.rpc(url, "eth_sendRawTransaction", [raw])
                sent = True
                priv = priv if url == priv else None
                break
            except BuyError as e:
                why = str(e)
                if "known" in why.lower() or "already" in why.lower():
                    sent, priv = True, priv if url == priv else None
                    break
        if not sent:
            raise BuyError("a rede recusou o envio: " + why[:160])
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECIBO_S:
            await asyncio.sleep(RECIBO_PASSO)
            try:
                rc = await self.rpc(c["rpc"], "eth_getTransactionReceipt", [h])
            except BuyError:
                rc = None
            if rc:
                return rc
            if priv and time.monotonic() - t0 >= PUBLICO_APOS_S:
                priv = None
                try:
                    await self.rpc(c["rpc"], "eth_sendRawTransaction", [raw])
                except BuyError:
                    pass                           # "já conhecida" ou já entrou: o recibo é quem decide
        return None

    async def _apply_evm(self, row: dict, rc: dict, gp: int | None = None) -> dict:
        c = CHAINS[row["rede"]]
        gas = int(rc.get("gasUsed") or "0x0", 16) * int(rc.get("effectiveGasPrice") or hex(gp or 0), 16) / 1e18
        gas_usd = round(gas * float(row.get("nativo_usd") or 0), 4)
        if int(rc.get("status") or "0x0", 16) != 1:
            return await self._finish(row, status="falhou", motivo="a transação falhou na rede (só o gás foi gasto)", gas_usd=gas_usd)
        got = 0
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if (lg.get("address") or "").lower() == row["token"] and len(tp) >= 3 and tp[0] == T_TRANSFER and tp[2][-40:].lower() == row["endereco"][2:]:
                got += int(lg.get("data") or "0x0", 16)
        if got <= 0:
            return await self._finish(row, status="confira", motivo=f"confirmada, mas o token não apareceu no recibo: confira em {c['nome']}", gas_usd=gas_usd)
        qty = got / 10 ** int(row.get("casas") or 18)
        return await self._finish(row, status="confirmada", motivo=None, qty=qty, px_in=float(row["usd_in"]) / qty, gas_usd=gas_usd)

    async def _buy_sol(self, q: dict, wal: dict, secret: str) -> dict:
        from .jupiter import JupiterWallet
        from .solana_wallet import UserWallet
        from . import txguard
        jq = await self._jup_quote(q)
        if not jq or not int(jq.get("outAmount") or 0):
            raise BuyError("a Jupiter não achou rota agora: nada foi enviado")
        if int(jq.get("otherAmountThreshold") or 0) < q["min_out"] * 0.99:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        try:
            uw = UserWallet(secret, public_rpc=self.sol_rpc(), jupiter_api_key=self.sys_key("jupiter_api_key"))
        except ValueError:
            raise BuyError("a chave guardada não abriu") from None
        if uw.address != wal["endereco"]:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        jw = JupiterWallet(self.http, uw, self.jup(), priority_sol=0.0001)
        try:
            raw, blockhash = await jw._swap_tx(jq, prio="high", amount=q["value"], out_mint=q["token"])
        except txguard.TxRejected as e:
            raise BuyError("a transação não passou na conferência: " + str(e)[:160] + ": nada foi enviado") from None
        except Exception as e:
            raise BuyError(f"não consegui montar a transação ({type(e).__name__}): nada foi enviado") from None
        from solders.transaction import VersionedTransaction
        sig = str(VersionedTransaction.from_bytes(base64.b64decode(raw)).signatures[0])
        labels = [((r.get("swapInfo") or {}).get("label") or "?") for r in (jq.get("routePlan") or [])]
        row = self._row(q, wal, sig, "Jupiter", " → ".join(labels[:4]))
        await self.db.insert("dormant_buys", row)
        self.watch.held.add(q["cg"])
        async def rest():
            s, st, err = await jw._send_and_confirm(raw)
            if st == "pendente":
                st, err = await txguard.reconcile(jw._rpc, s or sig, blockhash)
            if st == "confirmada":
                return self._public(await self._apply_sol(row))
            if st == "pendente":
                await self._finish(row, status="pendente", motivo=(err or "")[:160])
                return self._public(row)
            await self._finish(row, status="falhou", motivo=(err or st)[:160])
            raise BuyError("a compra não entrou: " + (err or st)[:160])
        return await self._early(rest()) or self._public(row)

    async def _apply_sol(self, row: dict) -> dict:
        tx = None
        for _ in range(5):
            try:
                tx = await self.rpc(self.sol_rpc(), "getTransaction", [row["tx"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
            except BuyError:
                tx = None
            if tx:
                break
            await asyncio.sleep(2)
        if not tx or not tx.get("meta"):
            return await self._finish(row, status="confira", motivo="confirmada, mas não consegui ler a quantidade: confira no Solscan")
        meta = tx["meta"]
        if meta.get("err"):
            return await self._finish(row, status="falhou", motivo=str(meta["err"])[:160])

        def soma(lst):
            return sum(float((b.get("uiTokenAmount") or {}).get("uiAmountString") or 0) for b in lst or []
                       if b.get("mint") == row["token"] and b.get("owner") == row["endereco"])
        qty = soma(meta.get("postTokenBalances")) - soma(meta.get("preTokenBalances"))
        fee = float(meta.get("fee") or 0) / 1e9
        gas_usd = round(fee * float(row.get("nativo_usd") or 0), 4)
        if qty <= 0:
            return await self._finish(row, status="confira", motivo="confirmada, mas o token não apareceu na carteira: confira no Solscan", gas_usd=gas_usd)
        return await self._finish(row, status="confirmada", motivo=None, qty=qty, px_in=float(row["usd_in"]) / qty, gas_usd=gas_usd)

    @staticmethod
    def _public(r: dict) -> dict:
        c = CHAINS.get(r.get("rede")) or {}
        return {k: r.get(k) for k in ("id", "status", "motivo", "tx", "qty", "px_in", "usd_in", "gas_usd", "nome", "simbolo", "dex", "rota")} | {"expl": c.get("expl")}

    # ------------------------------------------------------------------ venda (0.32.243, pedido do dono em 06/11/2026)
    # Vender é sair: funciona com as compras desligadas e não conta nos limites em dólar, mas pede senha e VENDER como a compra.
    # A trava geral PUMP_REAL_ALLOWED continua valendo: com ela fechada o servidor não assina nada.
    async def _erc20_word(self, c: dict, token: str, data: str) -> int:
        w = evm.words(await self.rpc(c["rpc"], "eth_call", [{"to": token, "data": data}, "latest"]) or "0x")
        return w[0] if w else 0

    async def evm_sell_best(self, chain: str, token: str, amount: int) -> dict | None:
        c = CHAINS[chain]
        cands = [{"tipo": "v2", "path": [token, c["wrapped"]], "dex": c["dex"].split(" e ")[0], "rota": "direta"}]
        if c.get("ponte") and token != c["ponte"]:
            cands.append({"tipo": "v2", "path": [token, c["ponte"], c["wrapped"]], "dex": c["dex"].split(" e ")[0], "rota": "passando por dólar"})
        if c.get("v3"):
            cands += [{"tipo": "v3", "fee": f, "dex": "Uniswap V3", "rota": f"pool de {f / 10000:g}%"} for f in V3_FEES]
        if chain in V4:
            cands += await self._v4_pools(chain, token)
        outs = await asyncio.gather(*[self._sell_out(c, rt, amount, token) for rt in cands])
        best, out = None, 0
        for rt, o in zip(cands, outs):
            if o > out:
                best, out = rt, o
        return {**best, "out": out} if best else None

    async def _sell_out(self, c: dict, rt: dict, amount: int, token: str) -> int:
        if rt["tipo"] == "v4":
            return await self._v4_out(c, amount, rt["key"], rt["rede"], zero_for_one=False)
        if rt["tipo"] == "v2":
            return await self._v2_out(c, amount, rt["path"])
        data = SEL_V3_QUOTE + evm.w_addr(token) + evm.w_addr(c["wrapped"]) + evm.w_int(amount) + evm.w_int(rt["fee"]) + evm.w_int(0)
        w = evm.words(await self._call(c, V3_QUOTER, data) or "0x")
        return w[0] if w else 0

    def _sell_tx(self, q: dict, min_out: int, addr: str) -> tuple[str, str]:
        """Sempre o roteador fixo daqui; o dinheiro sempre para a própria carteira."""
        c, rt = CHAINS[q["rede"]], q["route"]
        dl = int(time.time()) + 300
        if rt["tipo"] == "v3":
            return V3_ROUTER, v3_sell_data(q["token"], c["wrapped"], rt["fee"], addr, dl, q["amount"], min_out)
        if rt["tipo"] == "v4":
            return self._v4_checked(q), v4_data(rt["key"], q["amount"], min_out, dl, sell=True)
        return c["router"], evm.call_data(c.get("sell_sel") or SEL_SELL_ETH, q["amount"], min_out, rt["path"], addr, dl)

    def _v4_checked(self, q: dict) -> str:
        """Universal Router da rede, só se a chave do pool passou pela conferência na rede (keccak = id do pool) e é o par ETH/este token."""
        key = q["route"].get("key") or []
        if q["rede"] not in V4 or len(key) != 5 or key[0] != ZERO or key[1] != q["token"] or self._v4keys.get(v4_pool_id(key)) != key:
            raise BuyError("pool V4 não conferido: nada foi enviado")
        return V4[q["rede"]]["ur"]

    @staticmethod
    def _spender(q: dict) -> str:
        """Quem o token autoriza: o roteador fixo, ou o Permit2 na V4 (que por sua vez autoriza só o Universal Router)."""
        t = q["route"]["tipo"]
        return PERMIT2 if t == "v4" else V3_ROUTER if t == "v3" else CHAINS[q["rede"]]["router"]

    async def _p2_ok(self, c: dict, q: dict, addr: str) -> bool:
        """Permit2 já deixa o Universal Router puxar este valor por mais 2 min?"""
        w = evm.words(await self._call(c, PERMIT2, SEL_P2_ALLOW + evm.w_addr(addr) + evm.w_addr(q["token"]) + evm.w_addr(V4[q["rede"]]["ur"])) or "0x")
        return len(w) >= 2 and w[0] >= q["amount"] and w[1] > time.time() + 120

    async def preview_sell(self, uid: str, compra_id: str, pct) -> dict:
        rows = await self.db.select("dormant_buys", {"id": str(compra_id or ""), "user_id": uid}, limit=1) or []
        if not rows or rows[0].get("status") != "confirmada":
            raise BuyError("compra não encontrada")
        r = rows[0]
        chain = r.get("rede")
        if chain not in CHAINS:
            raise BuyError("rede inválida")
        try:
            pct = int(pct)
        except (TypeError, ValueError):
            raise BuyError("porcentagem inválida") from None
        if not 1 <= pct <= 100:
            raise BuyError("porcentagem inválida")
        c, bloq, avisos = CHAINS[chain], [], []
        await self.resolve_pending(uid)
        if not self.allowed():
            bloq.append("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
        wal = await self.wallet_row(uid, chain)
        if not wal:
            bloq.append(f"cadastre a carteira da rede {c['nome']} em Carteiras e compra")
        elif wal["endereco"] != r.get("endereco"):
            bloq.append("a carteira desta rede foi trocada depois da compra: o token está na carteira antiga")
        if await self.pending_on(uid, chain):
            bloq.append("há uma operação sem confirmação nesta rede: espere ela terminar (veja Minhas compras)")
        usd_n = await self.native_usd(chain)
        if not usd_n:
            bloq.append(f"sem a cotação de {c['moeda']} em dólar")
        gb, ga = judge_goplus(chain, await self.goplus(chain, r["token"]))
        avisos += gb + ga                          # na venda não bloqueia: se der para sair, a decisão é do dono; a simulação recusa se não der
        cfg = await self.cfg(uid)
        q = {"lado": "venda", "uid": uid, "compra": r["id"], "key": r.get("cmc"), "cg": r.get("cg"), "rede": chain, "token": r["token"], "pct": pct, "usd_n": usd_n,
             "nome": r.get("nome"), "simbolo": r.get("simbolo"), "t": time.time(), "slip": cfg["slip_pct"], "end": r.get("endereco")}
        det = await ({"solana": self._sell_preview_sol, "cardano": self._sell_preview_ada, "cosmos": self._sell_preview_osmo}.get(c["tipo"], self._sell_preview_evm))(q, bloq, avisos)
        row = self.watch.rows.get(r.get("cg")) or {}
        px = row.get("current_price")
        usd_out = det.get("recebe") * usd_n if det.get("recebe") and usd_n else None
        if usd_out and px and det.get("vende"):
            dif = (usd_out / (det["vende"] * px) - 1) * 100
            det["dif_cg"] = round(dif, 2)
            if dif < -VENDA_BLOQ:
                bloq.append(f"você receberia {-dif:.0f}% abaixo do preço da CoinGecko: pool errado, manipulado ou sem dinheiro")
            elif dif < -PRECO_AVISO:
                avisos.append(f"você recebe {-dif:.0f}% abaixo do preço da CoinGecko")
        imp = det.get("impacto")
        if imp is not None and imp > IMPACTO_AVISO:
            avisos.append(f"esta venda move o preço em {imp:.0f}%: pool pequeno para este valor")
        out = {"moeda": {"nome": q["nome"], "simbolo": q["simbolo"]}, "rede": chain, "rede_nome": c["nome"], "token": q["token"], "moeda_rede": c["moeda"], "carteira": q["end"],
               "slip": cfg["slip_pct"], "pct": pct, "usd": usd_out, "bloqueia": bloq, "avisos": avisos, **det}
        if not bloq:
            self._prune()
            qid = uuid.uuid4().hex
            self.quotes[qid] = q
            out.update(quote_id=qid, validade_s=QUOTE_TTL_S)
        return out

    async def _sell_preview_evm(self, q: dict, bloq: list, avisos: list) -> dict:
        c, addr = CHAINS[q["rede"]], q["end"]
        try:
            dec = await self._erc20_word(c, q["token"], SEL_DECIMALS)
            saldo = await self._erc20_word(c, q["token"], SEL_BALANCE + evm.w_addr(addr))
        except BuyError as e:
            bloq.append("não consegui ler o token: " + str(e))
            return {"dex": c["dex"]}
        if saldo <= 0:
            bloq.append("a carteira não tem este token")
            return {"dex": c["dex"], "saldo": 0}
        amount = saldo if q["pct"] == 100 else saldo * q["pct"] // 100
        rt = await self.evm_sell_best(q["rede"], q["token"], amount)
        if not rt:
            bloq.append(f"nenhum pool com a moeda da rede em {c['dex']} para este token")
            return {"dex": c["dex"], "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec}
        # token que cobra taxa na venda entrega menos que a cotação: sem isto a folga não bastaria e a transação falharia
        tax = 0.0
        try:
            tax = max(0.0, float(((await self.goplus(q["rede"], q["token"])) or {}).get("sell_tax") or 0))
        except (TypeError, ValueError):
            pass
        min_out = int(rt["out"] * (10000 - int(q["slip"] * 100)) / 10000 * (1 - min(tax, 0.5)))
        q.update(route={k: v for k, v in rt.items() if k != "out"}, amount=amount, min_out=min_out, dec=dec)
        small = await self._sell_out(c, rt, max(amount // 50, 1), q["token"])
        impacto = round(max(0.0, (1 - rt["out"] / (small * 50)) * 100), 2) if small else None
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        q["gp"] = gp
        allow = await self._erc20_word(c, q["token"], SEL_ALLOW + evm.w_addr(addr) + evm.w_addr(self._spender(q)))
        v4 = rt["tipo"] == "v4"
        p2_falta = v4 and not await self._p2_ok(c, q, addr)
        aprovar = allow < amount or p2_falta
        gas = 300000 + (70000 if allow < amount else 0) + (70000 if p2_falta else 0)
        if not aprovar:
            try:
                to, data = self._sell_tx(q, min_out, addr)
                gas = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": "0x0"}]), 16)
            except BuyError as e:
                bloq.append("a rede recusou na simulação: " + str(e))
        bal = int(await self.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        if bal < int(gas * 1.3) * gp:
            bloq.append(f"falta {c['moeda']} para pagar o gás da venda: a carteira tem {bal / 1e18:.6f}; use Abastecer em Carteiras e compra")
        if aprovar and v4:
            n = (allow < amount) + p2_falta
            avisos.append(("vão sair duas autorizações" if n == 2 else "vai sair uma autorização") + " antes da venda (Uniswap V4: o token autoriza o "
                          "Permit2 e o Permit2 autoriza o roteador oficial), só no valor exato desta venda e vencendo em 30 min (cada uma paga gás)")
        elif aprovar:
            avisos.append("vai sair uma autorização antes da venda: só no valor exato desta venda, só para o roteador oficial (paga gás)")
        if rt.get("hook"):
            avisos.append(f"o pool tem um contrato extra (hook {rt['key'][4][:8]}…): o valor vem da simulação dele, e a venda é recusada pela rede se receber menos que o mínimo")
        return {"dex": rt["dex"], "rota": rt["rota"], "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec, "recebe": rt["out"] / 1e18, "minimo": min_out / 1e18,
                "impacto": impacto, "gas_usd": round(gas * gp / 1e18 * (q["usd_n"] or 0), 4), "aprovar": aprovar}

    async def _sell_preview_sol(self, q: dict, bloq: list, avisos: list) -> dict:
        try:
            res = await self.rpc(self.sol_rpc(), "getTokenAccountsByOwner", [q["end"], {"mint": q["token"]}, {"encoding": "jsonParsed"}])
            infos = [a["account"]["data"]["parsed"]["info"]["tokenAmount"] for a in (res or {}).get("value") or []]
            saldo, dec = sum(int(i["amount"]) for i in infos), (int(infos[0]["decimals"]) if infos else 0)
            sol = (await self.rpc(self.sol_rpc(), "getBalance", [q["end"]]))["value"]
        except (BuyError, KeyError, TypeError, ValueError, IndexError):
            bloq.append("não consegui ler o saldo da carteira")
            return {"dex": "Jupiter"}
        if saldo <= 0:
            bloq.append("a carteira não tem este token")
            return {"dex": "Jupiter", "saldo": 0}
        if sol < 3_000_000:
            bloq.append(f"falta SOL para pagar a taxa da venda: a carteira tem {sol / 1e9:.5f}; use Abastecer em Carteiras e compra")
        amount = saldo if q["pct"] == 100 else saldo * q["pct"] // 100
        q.update(amount=amount, dec=dec)
        jq = await self._jup_quote(q, q["token"], WSOL, amount)
        if not jq or not int(jq.get("outAmount") or 0):
            bloq.append("a Jupiter não achou rota para este token")
            return {"dex": "Jupiter", "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec}
        q["min_out"] = int(jq.get("otherAmountThreshold") or 0)
        labels = [((x.get("swapInfo") or {}).get("label") or "?") for x in (jq.get("routePlan") or [])]
        try:
            imp = round(float(jq.get("priceImpactPct") or 0) * 100, 2)
        except (TypeError, ValueError):
            imp = None
        return {"dex": "Jupiter", "rota": " → ".join(labels[:4]), "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec, "recebe": int(jq["outAmount"]) / 1e9,
                "minimo": q["min_out"] / 1e9, "impacto": imp, "gas_usd": round((q["usd_n"] or 0) * 0.0001, 4), "aprovar": False}

    async def sell(self, uid: str, quote_id: str, senha: str, confirmar: str) -> dict:
        if confirmar != "VENDER":
            raise BuyError("digite VENDER para confirmar")
        async with self.lock(uid):
            self._prune()
            q = self.quotes.get(str(quote_id or ""))
            if not q or q["uid"] != uid or q.get("lado") != "venda":
                raise BuyError("esta cotação venceu: peça outra")
            if not self.allowed():
                raise BuyError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            wal = await self.wallet_row(uid, q["rede"])
            if not wal or wal["endereco"] != q["end"]:
                raise BuyError("a carteira desta rede mudou: peça outra cotação")
            secret = await self._open(uid, wal, senha)
            self.quotes.pop(quote_id, None)
            if await self.pending_on(uid, q["rede"]):
                raise BuyError("há uma operação sem confirmação nesta rede: espere ela terminar")
            if CHAINS[q["rede"]]["tipo"] == "solana":
                return await self._sell_sol(q, wal, secret)
            if CHAINS[q["rede"]]["tipo"] == "cardano":
                return await self._sell_ada(q, wal, secret)
            if CHAINS[q["rede"]]["tipo"] == "cosmos":
                return await self._sell_osmo(q, wal, secret)
            return await self._sell_evm(q, wal, secret)

    def _sell_row(self, q: dict, wal: dict, tx: str | None, dex: str | None, rota: str | None) -> dict:
        return {"id": uuid.uuid4().hex, "user_id": q["uid"], "em": _iso(time.time()), "rede": q["rede"], "compra": q["compra"], "cg": q["cg"], "nome": q["nome"], "simbolo": q["simbolo"],
                "token": q["token"], "endereco": wal["endereco"], "dex": dex, "rota": rota, "qty": q["amount"] / 10 ** int(q.get("dec") or 0), "casas": q.get("dec"), "nativo_usd": q["usd_n"], "tx": tx, "status": "enviando"}

    async def _sell_finish(self, row: dict, **v) -> dict:
        row.update(v)
        await self.db.update("dormant_sells", {"id": row["id"], "user_id": row["user_id"]}, v)
        return row

    async def _evm_receipt(self, c: dict, h: str) -> dict | None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECIBO_S:
            await asyncio.sleep(RECIBO_PASSO)
            try:
                rc = await self.rpc(c["rpc"], "eth_getTransactionReceipt", [h])
            except BuyError:
                rc = None
            if rc:
                return rc
        return None

    async def _evm_approve(self, c: dict, key: int, addr: str, token: str, spender: str, amount: int, gp: int) -> None:
        """Autoriza SÓ o valor desta venda, SÓ para o roteador fixo (ou o Permit2). Não vai pelo envio privado: autorização não tem o que roubar."""
        await self._evm_auth_tx(c, key, addr, token, SEL_APPROVE + evm.w_addr(spender) + evm.w_int(amount), gp)

    async def _evm_auth_tx(self, c: dict, key: int, addr: str, to: str, data: str, gp: int) -> None:
        est = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": "0x0"}]), 16)
        nonce = int(await self.rpc(c["rpc"], "eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, int(est * 1.3) + 10000, to, 0, data, c["id"])
        await self.rpc(c["rpc"], "eth_sendRawTransaction", [raw])
        rc = await self._evm_receipt(c, h)
        if not rc or int(rc.get("status") or "0x0", 16) != 1:
            raise BuyError("a autorização não confirmou: a venda não foi enviada, tente de novo (" + h + ")")

    async def _p2_approve(self, c: dict, key: int, addr: str, q: dict, gp: int) -> None:
        """Permit2 → Universal Router: só o valor desta venda, vencendo em 30 min."""
        data = SEL_P2_APPROVE + evm.w_addr(q["token"]) + evm.w_addr(V4[q["rede"]]["ur"]) + evm.w_int(q["amount"]) + evm.w_int(int(time.time()) + P2_VALIDADE_S)
        await self._evm_auth_tx(c, key, addr, PERMIT2, data, gp)

    async def _sell_evm(self, q: dict, wal: dict, secret: str) -> dict:
        c = CHAINS[q["rede"]]
        cid = int(await self.rpc(c["rpc"], "eth_chainId", []) or "0x0", 16)
        if cid != c["id"]:
            raise BuyError("o RPC respondeu de outra rede: nada foi enviado")
        addr = wal["endereco"]
        key = evm.parse_key(secret)
        if evm.address_of(key) != addr:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        if await self._erc20_word(c, q["token"], SEL_BALANCE + evm.w_addr(addr)) < q["amount"]:
            raise BuyError("o saldo do token mudou: nada foi enviado, peça outra cotação")
        out = await self._sell_out(c, q["route"], q["amount"], q["token"])
        if out < q["min_out"]:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        if q.get("gp") and gp > q["gp"] * 2:
            raise BuyError("o gás mais que dobrou desde a cotação: nada foi enviado, peça outra cotação")
        gp = int(gp * c.get("gas_mult", 1.1))
        spender = self._spender(q)
        v4 = q["route"]["tipo"] == "v4"
        if v4:
            self._v4_checked(q)                    # antes de qualquer autorização: pool conferido e roteador oficial
        allow = await self._erc20_word(c, q["token"], SEL_ALLOW + evm.w_addr(addr) + evm.w_addr(spender))
        autorizou = False
        if allow < q["amount"]:
            if allow > 0:                          # USDT e parecidos recusam trocar autorização que não está em zero
                await self._evm_approve(c, key, addr, q["token"], spender, 0, gp)
            await self._evm_approve(c, key, addr, q["token"], spender, q["amount"], gp)
            autorizou = True
        if v4 and not await self._p2_ok(c, q, addr):
            await self._p2_approve(c, key, addr, q, gp)
            autorizou = True
        if autorizou:
            out = await self._sell_out(c, q["route"], q["amount"], q["token"])
            if out < q["min_out"]:                 # sobra autorização no roteador oficial, que só puxa de quem chama: nada a limpar
                raise BuyError("o preço piorou durante a autorização: a venda não foi enviada, peça outra cotação")
        to, data = self._sell_tx(q, q["min_out"], addr)
        est = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": "0x0"}]), 16)
        gas = int(est * 1.3) + 20000
        bal = int(await self.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        if bal < gas * gp:
            raise BuyError(f"falta {c['moeda']} para pagar o gás: a venda não foi enviada")
        nonce = int(await self.rpc(c["rpc"], "eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, gas, to, 0, data, c["id"])
        rt = q["route"]
        row = self._sell_row(q, wal, h, rt["dex"], rt["rota"])
        await self.db.insert("dormant_sells", row)      # grava ANTES de enviar, como na compra
        async def rest():
            try:
                rc = await self._evm_send(c, raw, h)
            except BuyError as e:
                await self._sell_finish(row, status="falhou", motivo=str(e)[:160])
                raise
            if rc:
                return self._public_sell(await self._apply_sell_evm(row, rc, gp, bal0=bal if v4 else None))
            await self._sell_finish(row, status="pendente", motivo="sem confirmação em 90 s: confira em Minhas compras")
            return self._public_sell(row)
        return await self._early(rest()) or self._public_sell(row)

    async def _apply_sell_evm(self, row: dict, rc: dict, gp: int | None = None, bal0: int | None = None) -> dict:
        c = CHAINS[row["rede"]]
        gas_wei = int(rc.get("gasUsed") or "0x0", 16) * int(rc.get("effectiveGasPrice") or hex(gp or 0), 16)
        gas = gas_wei / 1e18
        usd_n = float(row.get("nativo_usd") or 0)
        gas_usd = round(gas * usd_n, 4)
        if int(rc.get("status") or "0x0", 16) != 1:
            return await self._sell_finish(row, status="falhou", motivo="a transação falhou na rede (só o gás foi gasto)", gas_usd=gas_usd)
        got, sold, end = 0, 0, row["endereco"][2:]
        for lg in rc.get("logs") or []:
            tp, adr = lg.get("topics") or [], (lg.get("address") or "").lower()
            if adr == c["wrapped"] and tp and tp[0] == T_WITHDRAW:
                got += int(lg.get("data") or "0x0", 16)
            elif adr == row["token"] and len(tp) >= 3 and tp[0] == T_TRANSFER and tp[1][-40:].lower() == end:
                sold += int(lg.get("data") or "0x0", 16)
        if got <= 0 and row["rede"] in V4:
            # 0.32.258: na V4 o ETH sai do PoolManager direto para a carteira, sem evento. A rede não guarda saldo antigo, então: saldo depois −
            # saldo de antes do envio + gás (lido aqui mesmo); sem o saldo de antes (venda conferida depois), o valor do evento Swap do pool.
            if bal0 is not None:
                try:
                    depois = int(await self.rpc(c["rpc"], "eth_getBalance", [row["endereco"], "latest"]) or "0x0", 16)
                    got = max(0, depois - bal0 + gas_wei)
                except BuyError:
                    got = 0
            if got <= 0:
                got = v4_swap_eth(rc.get("logs") or [], V4[row["rede"]]["pm"])
        if got <= 0:
            return await self._sell_finish(row, status="confira", motivo=f"confirmada, mas o valor recebido não apareceu no recibo: confira em {c['nome']}", gas_usd=gas_usd)
        qty = sold / 10 ** int(row.get("casas") or 18) if sold else row.get("qty")
        return await self._sell_finish(row, status="confirmada", motivo=None, qty=qty, nativo_out=got / 1e18, usd_out=round(got / 1e18 * usd_n, 4), gas_usd=gas_usd)

    async def _sell_sol(self, q: dict, wal: dict, secret: str) -> dict:
        from .jupiter import JupiterWallet
        from .solana_wallet import UserWallet
        from . import txguard
        jq = await self._jup_quote(q, q["token"], WSOL, q["amount"])
        if not jq or not int(jq.get("outAmount") or 0):
            raise BuyError("a Jupiter não achou rota agora: nada foi enviado")
        if int(jq.get("otherAmountThreshold") or 0) < q["min_out"] * 0.99:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        try:
            uw = UserWallet(secret, public_rpc=self.sol_rpc(), jupiter_api_key=self.sys_key("jupiter_api_key"))
        except ValueError:
            raise BuyError("a chave guardada não abriu") from None
        if uw.address != wal["endereco"]:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        jw = JupiterWallet(self.http, uw, self.jup(), priority_sol=0.0001)
        try:
            raw, blockhash = await jw._swap_tx(jq, prio="high", amount=q["amount"], out_mint=WSOL)
        except txguard.TxRejected as e:
            raise BuyError("a transação não passou na conferência: " + str(e)[:160] + ": nada foi enviado") from None
        except Exception as e:
            raise BuyError(f"não consegui montar a transação ({type(e).__name__}): nada foi enviado") from None
        from solders.transaction import VersionedTransaction
        sig = str(VersionedTransaction.from_bytes(base64.b64decode(raw)).signatures[0])
        labels = [((x.get("swapInfo") or {}).get("label") or "?") for x in (jq.get("routePlan") or [])]
        row = self._sell_row(q, wal, sig, "Jupiter", " → ".join(labels[:4]))
        await self.db.insert("dormant_sells", row)
        async def rest():
            s, st, err = await jw._send_and_confirm(raw)
            if st == "pendente":
                st, err = await txguard.reconcile(jw._rpc, s or sig, blockhash)
            if st == "confirmada":
                return self._public_sell(await self._apply_sell_sol(row))
            if st == "pendente":
                await self._sell_finish(row, status="pendente", motivo=(err or "")[:160])
                return self._public_sell(row)
            await self._sell_finish(row, status="falhou", motivo=(err or st)[:160])
            raise BuyError("a venda não entrou: " + (err or st)[:160])
        return await self._early(rest()) or self._public_sell(row)

    async def _apply_sell_sol(self, row: dict) -> dict:
        tx = None
        for _ in range(5):
            try:
                tx = await self.rpc(self.sol_rpc(), "getTransaction", [row["tx"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
            except BuyError:
                tx = None
            if tx:
                break
            await asyncio.sleep(2)
        if not tx or not tx.get("meta"):
            return await self._sell_finish(row, status="confira", motivo="confirmada, mas não consegui ler o valor recebido: confira no Solscan")
        meta = tx["meta"]
        if meta.get("err"):
            return await self._sell_finish(row, status="falhou", motivo=str(meta["err"])[:160])

        def soma(lst):
            return sum(float((b.get("uiTokenAmount") or {}).get("uiAmountString") or 0) for b in lst or []
                       if b.get("mint") == row["token"] and b.get("owner") == row["endereco"])
        qty = soma(meta.get("preTokenBalances")) - soma(meta.get("postTokenBalances"))
        fee = float(meta.get("fee") or 0)
        usd_n = float(row.get("nativo_usd") or 0)
        got = (float(meta["postBalances"][0]) - float(meta["preBalances"][0]) + fee) / 1e9
        if got <= 0 or qty <= 0:
            return await self._sell_finish(row, status="confira", motivo="confirmada, mas os valores não bateram: confira no Solscan", gas_usd=round(fee / 1e9 * usd_n, 4))
        return await self._sell_finish(row, status="confirmada", motivo=None, qty=qty, nativo_out=got, usd_out=round(got * usd_n, 4), gas_usd=round(fee / 1e9 * usd_n, 4))

    @staticmethod
    def _public_sell(r: dict) -> dict:
        c = CHAINS.get(r.get("rede")) or {}
        return {k: r.get(k) for k in ("id", "status", "motivo", "tx", "qty", "nativo_out", "usd_out", "gas_usd", "nome", "simbolo", "dex", "rota")} | {"expl": c.get("expl"), "moeda": c.get("moeda")}

    # ------------------------------------------------------------------ Cardano pela Minswap (0.32.273)
    async def _mswap(self, path: str, body: dict | None = None, params: dict | None = None):
        try:
            h = {"User-Agent": "pump-fun-copy/1.0", "accept": "application/json"}
            r = await (self.http.post(MINSWAP + path, json=body, headers=h, timeout=40) if body is not None
                       else self.http.get(MINSWAP + path, params=params or {}, headers=h, timeout=30))
            js = r.json()
        except Exception as e:
            raise BuyError(f"a Minswap não respondeu ({type(e).__name__})") from None
        if r.status_code != 200 or not isinstance(js, dict):
            msg = (js.get("message") or js.get("error")) if isinstance(js, dict) else None
            raise BuyError(f"a Minswap recusou: {str(msg or r.status_code)[:160]}")
        return js

    async def _ada_wallet(self, addr: str, unit: str | None = None) -> tuple[int, int]:
        """(lovelace, quantidade crua do token) na carteira, pela Minswap."""
        js = await self._mswap("/wallet", params={"address": addr, "amount_in_decimal": "false"})
        tok = 0
        for b in js.get("balance") or []:
            a = b.get("asset") or {}
            if unit and a.get("token_id") == unit:
                tok = int(float(b.get("amount") or 0))
        return int(float(js.get("ada") or 0)), tok

    def _ada_est(self, q: dict, token_in: str, token_out: str, amount: float, dec: int) -> dict:
        return {"amount": f"{amount:.{max(0, min(dec, 12))}f}", "token_in": token_in, "token_out": token_out, "slippage": q["slip"], "amount_in_decimal": True}

    @staticmethod
    def _ada_fees(e: dict) -> tuple[float, float, float]:
        f = lambda k: float(e.get(k) or 0)                      # noqa: E731
        return f("aggregator_fee"), f("total_dex_fee"), f("deposits")

    @staticmethod
    def _ada_route(e: dict) -> str:
        return " → ".join(dict.fromkeys(h.get("protocol") or "?" for p in (e.get("paths") or []) for h in p))[:80] or "?"

    async def _preview_ada(self, q: dict, wal: dict | None, bloq: list, avisos: list) -> dict:
        body = self._ada_est(q, "lovelace", q["token"], q["amt"], 6)
        try:
            e = await self._mswap("/estimate", body)
        except BuyError as er:
            bloq.append(str(er))
            return {"dex": "Minswap"}
        if not float(e.get("amount_out") or 0):
            bloq.append("a Minswap não achou rota para este token")
            return {"dex": "Minswap"}
        dec = int(((e.get("tokens") or {}).get(q["token"]) or {}).get("decimals") or 0)
        agg, dexf, dep = self._ada_fees(e)
        out, mn = float(e["amount_out"]), float(e["min_amount_out"])
        q.update(est=body, min_s=e["min_amount_out"], dec=dec, fees=agg + dexf, dep=dep, out_est=out)
        if wal:
            try:
                lov = (await self._ada_wallet(wal["endereco"]))[0]
                precisa = q["amt"] + agg + dexf + dep + CHAINS["cardano"]["reserva"]
                if lov / 1e6 < precisa:
                    bloq.append(f"saldo insuficiente: a carteira tem {lov / 1e6:.2f} ADA e esta compra precisa de {precisa:.2f} (valor + taxas + depósito que volta + troco mínimo)")
            except BuyError:
                bloq.append("não consegui ler o saldo da carteira")
        avisos.append(f"taxas da Minswap: {agg:g} ADA do agregador + {dexf:g} ADA da DEX; {dep:g} ADA de depósito voltam quando a ordem executa")
        imp = e.get("avg_price_impact")
        return {"dex": "Minswap", "rota": self._ada_route(e), "recebe": out, "qty": out, "minimo": mn,
                "impacto": round(float(imp), 2) if imp is not None else None, "gas_usd": round((agg + dexf + 0.25) * (q["usd_n"] or 0), 4)}

    async def _ada_sign_submit(self, q: dict, wal: dict, secret: str, body: dict, min_s: str, cap: int, token_out: str | None, max_tok: int):
        """Monta pela Minswap, confere, assina e envia. Devolve (hash, cbor, carteira, rota, taxas)."""
        try:
            w = await asyncio.to_thread(cardano.Wallet, secret)
        except ValueError:
            raise BuyError("a frase guardada não abriu") from None
        if w.address != wal["endereco"]:
            raise BuyError("a frase não bate com o endereço da carteira: nada foi enviado")
        e = await self._mswap("/estimate", body)
        if float(e.get("min_amount_out") or 0) < float(min_s) * 0.99:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        agg, dexf, dep = self._ada_fees(e)
        fees_q = (q.get("fees") or 0) + (q.get("dep") or 0)
        if agg + dexf + dep > fees_q * 1.5 + 0.5:
            raise BuyError("as taxas da Minswap subiram desde a cotação: nada foi enviado, peça outra cotação")
        b = await self._mswap("/build-tx", {"sender": w.address, "min_amount_out": min_s, "estimate": body, "amount_in_decimal": True})
        cbor = str(b.get("cbor") or "")
        try:
            h, _ = cardano.check_tx(cbor, w, max_out_lovelace=cap + int((agg + dexf + dep) * 1e6), token_out=token_out, max_token_out=max_tok)
        except (cardano.TxRejected, ValueError, IndexError, KeyError) as er:
            raise BuyError("a transação não passou na conferência: " + str(er)[:160] + ": nada foi enviado") from None
        wit = await asyncio.to_thread(w.witness_set, h)
        return h.hex(), cbor, wit, w, self._ada_route(e), agg + dexf

    async def _ada_submit(self, cbor: str, wit: str, h: str) -> None:
        r = await self._mswap("/finalize-and-submit-tx", {"cbor": cbor, "witness_set": wit})
        if r.get("tx_id") and str(r["tx_id"]).lower() != h:
            log.warning("Dormant: a Minswap devolveu outro id de transação")

    async def _buy_ada(self, q: dict, wal: dict, secret: str) -> dict:
        h, cbor, wit, w, rota, fees = await self._ada_sign_submit(q, wal, secret, q["est"], q["min_s"], int(q["value"]) + 500_000, None, 0)
        pre = (await self._ada_wallet(w.address, q["token"]))[1]
        row = self._row(q, wal, h, "Minswap", rota)
        row["qty"] = q["out_est"]                          # estimativa até a ordem executar (fica se o servidor reiniciar no meio)
        await self.db.insert("dormant_buys", row)
        self.watch.held.add(q["cg"])
        self.__dict__.setdefault("_ada_pre", {})[row["id"]] = (pre, fees)
        try:
            await self._ada_submit(cbor, wit, h)
        except BuyError as er:
            await self._finish(row, status="falhou", motivo=str(er)[:160])
            raise
        await self._finish(row, status="pendente", motivo="ordem enviada à Minswap: o token chega quando a DEX executar (segundos a minutos)")
        return await self._early(self._ada_follow(row, False)) or self._public(row)

    async def _ada_follow(self, row: dict, venda: bool) -> dict:
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECIBO_S:
            await asyncio.sleep(RECIBO_PASSO * 3)
            r = await self._apply_ada(row, venda)
            if r.get("status") != "pendente":
                break
        return self._public_sell(row) if venda else self._public(row)

    async def _ada_confirmed(self, h: str) -> int | None:
        """Confirmações da transação (Koios, pública). None = ainda não entrou."""
        try:
            r = await self.http.post(KOIOS + "/tx_status", json={"_tx_hashes": [h]}, headers={"User-Agent": "pump-fun-copy/1.0", "accept": "application/json"}, timeout=20)
            js = r.json()
            n = (js[0] if isinstance(js, list) and js else {}).get("num_confirmations")
            return int(n) if n is not None else None
        except Exception:
            return None

    async def _ada_order(self, addr: str, h: str) -> dict | None:
        js = await self._mswap("/pending-orders", params={"owner_address": addr, "amount_in_decimal": "false"})
        return next((o for o in js.get("orders") or [] if str(o.get("tx_in") or "").lower().startswith(h.lower())), None)

    async def _apply_ada(self, row: dict, venda: bool) -> dict:
        busy = self.__dict__.setdefault("_ada_busy", set())
        if row["id"] in busy:                              # o acompanhamento e a tela não resolvem a mesma ordem ao mesmo tempo
            return row
        busy.add(row["id"])
        try:
            return await self._apply_ada_go(row, venda)
        finally:
            busy.discard(row["id"])

    async def _apply_ada_go(self, row: dict, venda: bool) -> dict:
        fin = self._sell_finish if venda else self._finish
        idade = time.time() - _ts(row.get("em"))
        conf = await self._ada_confirmed(row["tx"])
        if conf is None:
            if idade > ADA_ORDEM_PARADA_S:
                return await fin(row, status="falhou", motivo="a transação não entrou na blockchain (nada saiu da carteira)")
            return row
        if await self._ada_order(row["endereco"], row["tx"]):
            if idade > ADA_ORDEM_PARADA_S:
                await fin(row, status="pendente", motivo="ordem parada na Minswap: o preço saiu da folga. Cancele em Minhas compras para o valor voltar")
            return row
        pre, fees = self.__dict__.setdefault("_ada_pre", {}).pop(row["id"], (None, None))
        usd_n = float(row.get("nativo_usd") or 0)
        gas = round(((fees or 0) + 0.25) * usd_n, 4)
        dec = int(row.get("casas") or 0)
        lov, tok = await self._ada_wallet(row["endereco"], row["token"])
        if venda:
            if pre is None:
                return await fin(row, status="confirmada", motivo="ADA recebido pela cotação (não conferido na carteira)", gas_usd=gas)
            got = (lov - pre) / 1e6
            if got <= 0:
                return await fin(row, status="confira", motivo="a ordem saiu da DEX sem o ADA aparecer: pode ter sido devolvida; confira no Cardanoscan", gas_usd=gas)
            return await fin(row, status="confirmada", motivo=None, nativo_out=got, usd_out=round(got * usd_n, 4), gas_usd=gas)
        if pre is None:
            return await fin(row, status="confirmada", motivo="quantidade da cotação (não conferida na carteira)", gas_usd=gas,
                             px_in=float(row["usd_in"]) / float(row["qty"]) if row.get("qty") else None)
        qty = (tok - pre) / 10 ** dec
        if qty <= 0:
            return await fin(row, status="confira", motivo="a ordem saiu da DEX sem o token chegar: pode ter sido devolvida; confira no Cardanoscan", gas_usd=gas)
        return await fin(row, status="confirmada", motivo=None, qty=qty, px_in=float(row["usd_in"]) / qty, gas_usd=gas)

    async def _sell_preview_ada(self, q: dict, bloq: list, avisos: list) -> dict:
        try:
            lov, saldo = await self._ada_wallet(q["end"], q["token"])
        except BuyError:
            bloq.append("não consegui ler o saldo da carteira")
            return {"dex": "Minswap"}
        if saldo <= 0:
            bloq.append("a carteira não tem este token")
            return {"dex": "Minswap", "saldo": 0}
        amount = saldo if q["pct"] == 100 else saldo * q["pct"] // 100
        try:                                               # casas do token pela própria Minswap (a cotação de 1 unidade traz)
            e0 = await self._mswap("/estimate", {"amount": "1", "token_in": q["token"], "token_out": "lovelace", "slippage": q["slip"], "amount_in_decimal": False})
            dec = int(((e0.get("tokens") or {}).get(q["token"]) or {}).get("decimals") or 0)
        except BuyError:
            dec = 0
        body = self._ada_est(q, q["token"], "lovelace", amount / 10 ** dec, dec)
        try:
            e = await self._mswap("/estimate", body)
        except BuyError as er:
            bloq.append(str(er))
            return {"dex": "Minswap", "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec}
        agg, dexf, dep = self._ada_fees(e)
        if lov / 1e6 < agg + dexf + dep + CHAINS["cardano"]["reserva"]:
            bloq.append(f"falta ADA para as taxas da venda: a carteira tem {lov / 1e6:.2f} ADA e precisa de {agg + dexf + dep + CHAINS['cardano']['reserva']:.2f}")
        q.update(amount=amount, dec=dec, est=body, min_s=e.get("min_amount_out") or "0", fees=agg + dexf, dep=dep)
        avisos.append(f"taxas da Minswap: {agg:g} ADA do agregador + {dexf:g} ADA da DEX; {dep:g} ADA de depósito voltam quando a ordem executa")
        imp = e.get("avg_price_impact")
        return {"dex": "Minswap", "rota": self._ada_route(e), "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec, "recebe": float(e.get("amount_out") or 0),
                "minimo": float(e.get("min_amount_out") or 0), "impacto": round(float(imp), 2) if imp is not None else None,
                "gas_usd": round((agg + dexf + 0.25) * (q["usd_n"] or 0), 4), "aprovar": False}

    async def _sell_ada(self, q: dict, wal: dict, secret: str) -> dict:
        h, cbor, wit, w, rota, fees = await self._ada_sign_submit(q, wal, secret, q["est"], q["min_s"], 500_000, q["token"], int(q["amount"]))
        pre = (await self._ada_wallet(w.address))[0]
        row = self._sell_row(q, wal, h, "Minswap", rota)
        await self.db.insert("dormant_sells", row)
        self.__dict__.setdefault("_ada_pre", {})[row["id"]] = (pre, fees)
        try:
            await self._ada_submit(cbor, wit, h)
        except BuyError as er:
            await self._sell_finish(row, status="falhou", motivo=str(er)[:160])
            raise
        await self._sell_finish(row, status="pendente", motivo="ordem enviada à Minswap: o ADA chega quando a DEX executar (segundos a minutos)")
        return await self._early(self._ada_follow(row, True)) or self._public_sell(row)

    async def cancel_ada(self, uid: str, tipo: str, op_id: str, senha: str) -> dict:
        """Cancela uma ordem parada na Minswap: o valor volta para a carteira. Só a própria ordem, conferida antes de assinar."""
        tabela = "dormant_sells" if tipo == "venda" else "dormant_buys"
        async with self.lock(uid):
            rows = await self.db.select(tabela, {"id": str(op_id or ""), "user_id": uid}, limit=1) or []
            if not rows or rows[0].get("rede") != "cardano" or rows[0].get("status") != "pendente":
                raise BuyError("não achei uma ordem Cardano pendente com esse número")
            r = rows[0]
            if not self.allowed():
                raise BuyError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            wal = await self.wallet_row(uid, "cardano")
            if not wal or wal["endereco"] != r["endereco"]:
                raise BuyError("a carteira Cardano foi trocada depois desta ordem")
            secret = await self._open(uid, wal, senha)
            o = await self._ada_order(r["endereco"], r["tx"])
            if not o:
                raise BuyError("a ordem não está mais na Minswap (já executou ou foi cancelada): atualize Minhas compras")
            w = await asyncio.to_thread(cardano.Wallet, secret)
            if w.address != wal["endereco"]:
                raise BuyError("a frase não bate com o endereço da carteira: nada foi enviado")
            b = await self._mswap("/cancel-tx", {"sender": w.address, "orders": [{"tx_in": o["tx_in"]}]})
            cbor = str(b.get("cbor") or "")
            try:                                           # cancelar só devolve: nada sai para fora além da taxa da rede
                h, _ = cardano.check_tx(cbor, w, max_out_lovelace=0)
            except (cardano.TxRejected, ValueError, IndexError, KeyError) as er:
                raise BuyError("o cancelamento não passou na conferência: " + str(er)[:160] + ": nada foi enviado") from None
            await self._ada_submit(cbor, await asyncio.to_thread(w.witness_set, h), h.hex())
            fin = self._sell_finish if tipo == "venda" else self._finish
            await fin(r, status="cancelada", motivo="ordem cancelada: o valor volta para a carteira", **({} if tipo == "venda" else {"qty": 0}))
            return {"ok": True, "tx": h.hex(), "expl": CHAINS["cardano"]["expl"]}

    # ------------------------------------------------------------------ Osmosis (0.32.274)
    async def _osmo(self, path: str, body: dict | None = None):
        """Nó público da Osmosis (LCD). Tenta o próximo se um não responder."""
        last = "sem resposta"
        for base in CHAINS["osmosis"]["lcd"]:
            try:
                h = {"User-Agent": "pump-fun-copy/1.0", "accept": "application/json"}
                r = await (self.http.post(base + path, json=body, headers=h, timeout=30) if body is not None else self.http.get(base + path, headers=h, timeout=20))
                js = r.json()
            except Exception as e:
                last = type(e).__name__
                continue
            if r.status_code == 200 and isinstance(js, dict):
                return js
            if isinstance(js, dict) and (js.get("message") or js.get("code") is not None):
                return {"_erro": str(js.get("message") or js.get("code"))[:300], "_status": r.status_code}
            last = f"HTTP {r.status_code}"
        raise BuyError(f"a rede Osmosis não respondeu ({last})")

    async def _sqs(self, path: str) -> dict:
        try:
            r = await self.http.get(CHAINS["osmosis"]["sqs"] + path, headers={"User-Agent": "pump-fun-copy/1.0", "accept": "application/json"}, timeout=25)
            js = r.json()
        except Exception as e:
            raise BuyError(f"o roteador da Osmosis não respondeu ({type(e).__name__})") from None
        if r.status_code != 200 or not isinstance(js, dict):
            raise BuyError("o roteador da Osmosis não achou rota" + (f": {str(js.get('message'))[:120]}" if isinstance(js, dict) and js.get("message") else ""))
        return js

    async def _osmo_bal(self, addr: str, denom: str) -> int:
        from urllib.parse import quote
        js = await self._osmo(f"/cosmos/bank/v1beta1/balances/{addr}/by_denom?denom={quote(denom, safe='')}")
        if js.get("_erro"):
            raise BuyError("não consegui ler o saldo: " + js["_erro"][:120])
        return int(((js.get("balance") or {}).get("amount")) or 0)

    async def _osmo_dec(self, denom: str) -> int | None:
        from urllib.parse import quote
        try:
            js = await self._sqs("/tokens/metadata?denoms=" + quote(denom, safe=""))
            return int((js.get(denom) or {}).get("decimals"))
        except (BuyError, TypeError, ValueError):
            return None

    async def _osmo_quote(self, amount: int, denom_in: str, denom_out: str) -> tuple[int, list, dict]:
        """(quanto sai, rotas [(pools [(id, denom)], quantia)], resposta). Confere: as rotas somam o valor e terminam no token pedido."""
        from urllib.parse import quote
        js = await self._sqs(f"/router/quote?tokenIn={amount}{quote(denom_in, safe='')}&tokenOutDenom={quote(denom_out, safe='')}&singleRoute=false")
        routes, soma = [], 0
        for rt in js.get("route") or []:
            pools = [(int(p["id"]), str(p["token_out_denom"])) for p in rt.get("pools") or []]
            amt = int(rt.get("in_amount") or 0)
            if not pools or pools[-1][1] != denom_out or amt <= 0:
                raise BuyError("o roteador da Osmosis devolveu uma rota que não termina no token pedido")
            routes.append((pools, amt))
            soma += amt
        if not routes or soma != amount:
            raise BuyError("as rotas do roteador não somam o valor pedido")
        return int(js.get("amount_out") or 0), routes, js

    @staticmethod
    def _osmo_label(routes: list) -> str:
        return " + ".join("pool " + " → ".join(str(p[0]) for p in pools) for pools, _ in routes)[:80]

    async def _preview_osmo(self, q: dict, wal: dict | None, bloq: list, avisos: list) -> dict:
        try:
            out, routes, js = await self._osmo_quote(q["value"], osmosis.NATIVE, q["token"])
        except BuyError as er:
            bloq.append(str(er))
            return {"dex": "Osmosis"}
        dec = await self._osmo_dec(q["token"])
        if dec is None or out <= 0:
            bloq.append("não consegui ler as casas decimais do token" if dec is None else "o roteador não achou rota para este token")
            return {"dex": "Osmosis"}
        q.update(min_out=int(out * (1 - q["slip"] / 100)), dec=dec)
        if wal:
            try:
                bal = await self._osmo_bal(wal["endereco"], osmosis.NATIVE)
                if bal < q["value"] + int(CHAINS["osmosis"]["reserva"] * 1e6):
                    bloq.append(f"saldo insuficiente: a carteira tem {bal / 1e6:.4f} OSMO (fica {CHAINS['osmosis']['reserva']:g} OSMO para a taxa)")
            except BuyError:
                bloq.append("não consegui ler o saldo da carteira")
        try:
            imp = round(abs(float(js.get("price_impact") or 0)) * 100, 2)
        except (TypeError, ValueError):
            imp = None
        try:
            tf = float(js.get("effective_fee") or 0) * 100
            if tf:
                avisos.append(f"taxa das pools da Osmosis: {tf:.2f}% (já descontada do que você recebe)")
        except (TypeError, ValueError):
            pass
        return {"dex": "Osmosis", "rota": self._osmo_label(routes), "recebe": out / 10 ** dec, "qty": out / 10 ** dec, "minimo": q["min_out"] / 10 ** dec,
                "impacto": imp, "gas_usd": round(0.02 * (q["usd_n"] or 0), 4)}

    async def _osmo_send(self, w, msg: bytes) -> str:
        """Simula (gás), cobra a taxa pelo preço mínimo da rede, assina e envia. Devolve o hash. A mensagem foi montada aqui."""
        js = await self._osmo(f"/cosmos/auth/v1beta1/accounts/{w.address}")
        acc = js.get("account") or {}
        if js.get("_erro") or acc.get("address") != w.address:
            raise BuyError("a conta não existe na Osmosis ainda: mande um pouco de OSMO para ela primeiro")
        num, seq = int(acc.get("account_number") or 0), int(acc.get("sequence") or 0)
        body = osmosis.body([msg])

        def raw_for(fee: int, gas: int) -> bytes:
            a = osmosis.auth_info(w.pub, seq, fee, gas)
            return osmosis.tx_raw(body, a, osmosis.sign(w.key, osmosis.sign_doc(body, a, num)))
        sim = await self._osmo("/cosmos/tx/v1beta1/simulate", {"tx_bytes": base64.b64encode(await asyncio.to_thread(raw_for, 0, 2_000_000)).decode()})
        if sim.get("_erro"):
            raise BuyError("a rede recusou na simulação: " + sim["_erro"][:200] + ": nada foi enviado")
        used = int((sim.get("gas_info") or {}).get("gas_used") or 0)
        if not 0 < used < 3_000_000:
            raise BuyError("a simulação não devolveu o gás: nada foi enviado")
        try:
            base = float((await self._osmo("/osmosis/txfees/v1beta1/cur_eip_base_fee")).get("base_fee") or 0.025)
        except (BuyError, TypeError, ValueError):
            base = 0.025
        gas = int(used * 1.4) + 20_000
        fee = max(1, math.ceil(gas * max(base, 0.0025) * 1.3))
        if fee > 1_000_000:                                # mais de 1 OSMO de taxa: algo está errado
            raise BuyError("a taxa da rede saiu alta demais: nada foi enviado")
        raw = await asyncio.to_thread(raw_for, fee, gas)
        h = osmosis.tx_hash(raw)
        r = await self._osmo("/cosmos/tx/v1beta1/txs", {"tx_bytes": base64.b64encode(raw).decode(), "mode": "BROADCAST_MODE_SYNC"})
        tr = r.get("tx_response") or {}
        if r.get("_erro") or int(tr.get("code") or 0) != 0:
            raise BuyError("a rede recusou o envio: " + str(r.get("_erro") or tr.get("raw_log") or tr.get("code"))[:200])
        return h

    async def _osmo_tx(self, h: str) -> dict | None:
        try:
            js = await self._osmo(f"/cosmos/tx/v1beta1/txs/{h}")
        except BuyError:
            return None
        return js.get("tx_response") if not js.get("_erro") else None

    async def _osmo_wait(self, h: str) -> dict | None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECIBO_S:
            await asyncio.sleep(RECIBO_PASSO)
            tx = await self._osmo_tx(h)
            if tx:
                return tx
        return None

    @staticmethod
    def _osmo_out(tx: dict, addr: str, denom: str) -> int:
        """Quanto do token chegou na carteira, pelos eventos de transferência do banco na própria transação."""
        got = 0
        for ev in tx.get("events") or []:
            if ev.get("type") != "transfer":
                continue
            at = {a.get("key"): a.get("value") for a in ev.get("attributes") or []}
            if at.get("recipient") != addr:
                continue
            for part in str(at.get("amount") or "").split(","):
                m = re.match(r"^(\d+)(.+)$", part.strip())
                if m and m.group(2) == denom:
                    got += int(m.group(1))
        return got

    async def _buy_osmo(self, q: dict, wal: dict, secret: str) -> dict:
        try:
            w = await asyncio.to_thread(osmosis.Wallet, secret)
        except ValueError:
            raise BuyError("a chave guardada não abriu") from None
        if w.address != wal["endereco"]:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        out, routes, _ = await self._osmo_quote(q["value"], osmosis.NATIVE, q["token"])
        if out < q["min_out"]:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        msg = osmosis.swap_msg(w.address, routes, osmosis.NATIVE, q["min_out"])   # menos que min_out e a rede recusa a troca inteira
        h = await self._osmo_send(w, msg)
        row = self._row(q, wal, h, "Osmosis", self._osmo_label(routes))
        await self.db.insert("dormant_buys", row)
        self.watch.held.add(q["cg"])

        async def rest():
            tx = await self._osmo_wait(h)
            if tx:
                return self._public(await self._apply_osmo(row, tx, False))
            await self._finish(row, status="pendente", motivo="sem confirmação em 90 s: confira em Minhas compras")
            return self._public(row)
        return await self._early(rest()) or self._public(row)

    async def _apply_osmo(self, row: dict, tx: dict, venda: bool) -> dict:
        fin = self._sell_finish if venda else self._finish
        usd_n = float(row.get("nativo_usd") or 0)
        fee = sum(int(c.get("amount") or 0) for c in (((tx.get("tx") or {}).get("auth_info") or {}).get("fee") or {}).get("amount") or [] if c.get("denom") == osmosis.NATIVE)
        gas = round(fee / 1e6 * usd_n, 4)
        if int(tx.get("code") or 0) != 0:
            return await fin(row, status="falhou", motivo="a troca falhou na rede (só a taxa foi paga): " + str(tx.get("raw_log") or "")[:120], gas_usd=gas)
        if venda:
            got = self._osmo_out(tx, row["endereco"], osmosis.NATIVE) / 1e6
            if got <= 0:
                return await fin(row, status="confira", motivo="confirmada, mas o OSMO não apareceu na transação: confira no Mintscan", gas_usd=gas)
            return await fin(row, status="confirmada", motivo=None, nativo_out=got, usd_out=round(got * usd_n, 4), gas_usd=gas)
        got = self._osmo_out(tx, row["endereco"], row["token"])
        if got <= 0:
            return await fin(row, status="confira", motivo="confirmada, mas o token não apareceu na transação: confira no Mintscan", gas_usd=gas)
        qty = got / 10 ** int(row.get("casas") or 6)
        return await fin(row, status="confirmada", motivo=None, qty=qty, px_in=float(row["usd_in"]) / qty, gas_usd=gas)

    async def _sell_preview_osmo(self, q: dict, bloq: list, avisos: list) -> dict:
        try:
            saldo = await self._osmo_bal(q["end"], q["token"])
            osmo = await self._osmo_bal(q["end"], osmosis.NATIVE)
        except BuyError:
            bloq.append("não consegui ler o saldo da carteira")
            return {"dex": "Osmosis"}
        if saldo <= 0:
            bloq.append("a carteira não tem este token")
            return {"dex": "Osmosis", "saldo": 0}
        if osmo < int(CHAINS["osmosis"]["reserva"] * 1e6):
            bloq.append(f"falta OSMO para a taxa da venda: a carteira tem {osmo / 1e6:.4f} OSMO")
        dec = await self._osmo_dec(q["token"]) or 6
        amount = saldo if q["pct"] == 100 else saldo * q["pct"] // 100
        q.update(amount=amount, dec=dec)
        try:
            out, routes, js = await self._osmo_quote(amount, q["token"], osmosis.NATIVE)
        except BuyError as er:
            bloq.append(str(er))
            return {"dex": "Osmosis", "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec}
        q["min_out"] = int(out * (1 - q["slip"] / 100))
        try:
            imp = round(abs(float(js.get("price_impact") or 0)) * 100, 2)
        except (TypeError, ValueError):
            imp = None
        return {"dex": "Osmosis", "rota": self._osmo_label(routes), "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec, "recebe": out / 1e6,
                "minimo": q["min_out"] / 1e6, "impacto": imp, "gas_usd": round(0.02 * (q["usd_n"] or 0), 4), "aprovar": False}

    async def _sell_osmo(self, q: dict, wal: dict, secret: str) -> dict:
        try:
            w = await asyncio.to_thread(osmosis.Wallet, secret)
        except ValueError:
            raise BuyError("a chave guardada não abriu") from None
        if w.address != wal["endereco"]:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        out, routes, _ = await self._osmo_quote(q["amount"], q["token"], osmosis.NATIVE)
        if out < q["min_out"]:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        h = await self._osmo_send(w, osmosis.swap_msg(w.address, routes, q["token"], q["min_out"]))
        row = self._sell_row(q, wal, h, "Osmosis", self._osmo_label(routes))
        await self.db.insert("dormant_sells", row)

        async def rest():
            tx = await self._osmo_wait(h)
            if tx:
                return self._public_sell(await self._apply_osmo(row, tx, True))
            await self._sell_finish(row, status="pendente", motivo="sem confirmação em 90 s: confira em Minhas compras")
            return self._public_sell(row)
        return await self._early(rest()) or self._public_sell(row)

    # ------------------------------------------------------------------ pendências
    async def resolve_pending(self, uid: str) -> None:
        now = time.time()
        vivas = ("enviando", "pendente")
        vendas = await self.db.select("dormant_sells", {"user_id": uid}, order="em.desc", limit=200) or []
        if not any(r.get("status") in vivas for r in vendas + await self._rows(uid, 200)):
            return
        async with self.lock(uid):                 # relê aqui dentro: uma compra em andamento pode ter acabado de terminar
            for r in [x for x in await self._rows(uid, 200) if x.get("status") in vivas]:
                if now - _ts(r.get("em")) < 20:
                    continue
                try:
                    if CHAINS.get(r["rede"], {}).get("tipo") == "evm":
                        rc = await self.rpc(CHAINS[r["rede"]]["rpc"], "eth_getTransactionReceipt", [r["tx"]])
                        if rc:
                            await self._apply_evm(r, rc)
                            continue
                    elif CHAINS.get(r["rede"], {}).get("tipo") == "cardano":
                        await self._apply_ada(r, venda=False)
                        continue
                    elif CHAINS.get(r["rede"], {}).get("tipo") == "cosmos":
                        tx = await self._osmo_tx(r["tx"])
                        if tx:
                            await self._apply_osmo(r, tx, venda=False)
                            continue
                    elif r.get("tx") and r.get("rede") in CHAINS:
                        st = (await self.rpc(self.sol_rpc(), "getSignatureStatuses", [[r["tx"]], {"searchTransactionHistory": True}]))["value"][0]
                        if st and st.get("err"):
                            await self._finish(r, status="falhou", motivo=str(st["err"])[:160])
                            continue
                        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                            await self._apply_sol(r)
                            continue
                except (BuyError, KeyError, TypeError, IndexError):
                    continue
                if now - _ts(r.get("em")) > EXPIRA_S:
                    await self._finish(r, status="expirada", motivo="não entrou na blockchain")
            for r in [x for x in await self.db.select("dormant_sells", {"user_id": uid}, order="em.desc", limit=200) or [] if x.get("status") in vivas]:
                if now - _ts(r.get("em")) < 20:
                    continue
                try:
                    if CHAINS.get(r["rede"], {}).get("tipo") == "evm":
                        rc = await self.rpc(CHAINS[r["rede"]]["rpc"], "eth_getTransactionReceipt", [r["tx"]])
                        if rc:
                            await self._apply_sell_evm(r, rc)
                            continue
                    elif CHAINS.get(r["rede"], {}).get("tipo") == "cardano":
                        await self._apply_ada(r, venda=True)
                        continue
                    elif CHAINS.get(r["rede"], {}).get("tipo") == "cosmos":
                        tx = await self._osmo_tx(r["tx"])
                        if tx:
                            await self._apply_osmo(r, tx, venda=True)
                            continue
                    elif r.get("tx"):
                        st = (await self.rpc(self.sol_rpc(), "getSignatureStatuses", [[r["tx"]], {"searchTransactionHistory": True}]))["value"][0]
                        if st and st.get("err"):
                            await self._sell_finish(r, status="falhou", motivo=str(st["err"])[:160])
                            continue
                        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                            await self._apply_sell_sol(r)
                            continue
                except (BuyError, KeyError, TypeError, IndexError):
                    continue
                if now - _ts(r.get("em")) > EXPIRA_S:
                    await self._sell_finish(r, status="expirada", motivo="não entrou na blockchain")

    # ------------------------------------------------------------------ banco
    async def _rows(self, uid: str, limit: int = 500) -> list[dict]:
        return await self.db.select("dormant_buys", {"user_id": uid}, order="em.desc", limit=limit) or []

    async def spent_today(self, uid: str) -> float:
        since = _iso(time.time() - 86400)
        rows = await self.db.select("dormant_buys", {"user_id": uid}, gte={"em": since}, columns="usd_in,status,rede") or []
        return round(sum(float(r.get("usd_in") or 0) for r in rows if r.get("status") not in ("falhou", "expirada", "cancelada") and not str(r.get("rede") or "").startswith("cex:")), 4)   # exchange tem limite próprio

    async def gas_spent_today(self, uid: str) -> float:
        since = _iso(time.time() - 86400)
        rows = await self.db.select("dormant_gas", {"user_id": uid}, gte={"em": since}, columns="usd_in,status") or []
        return round(sum(float(r.get("usd_in") or 0) for r in rows if r.get("status") not in ("falhou", "expirada", "devolvida")), 4)

    async def pending_on(self, uid: str, chain: str) -> bool:
        since = _iso(time.time() - PENDENTE_S)
        rows = await self.db.select("dormant_buys", {"user_id": uid, "rede": chain}, gte={"em": since}, columns="status") or []
        rows += await self.db.select("dormant_sells", {"user_id": uid, "rede": chain}, gte={"em": since}, columns="status") or []
        rows += await self.db.select("dormant_gas", {"user_id": uid, "rede": chain}, gte={"em": since}, columns="status") or []
        return any(r.get("status") in ("enviando", "pendente") for r in rows)

    async def wallet_row(self, uid: str, chain: str) -> dict | None:
        rows = await self.db.select("dormant_wallets", {"user_id": uid, "rede": chain}, limit=1) or []
        return rows[0] if rows else None

    async def _cfg_row(self, uid: str) -> dict:
        rows = await self.db.select("dormant_buy_cfg", {"user_id": uid}, limit=1) or []
        return rows[0] if rows else {"user_id": uid, "cfg": {}, "erros": 0, "trava_ate": None}

    async def cfg(self, uid: str) -> dict:
        return clean_cfg(None, (await self._cfg_row(uid)).get("cfg") or {})

    async def _put_cfg(self, row: dict) -> None:
        await self.db.insert("dormant_buy_cfg", {"user_id": row["user_id"], "cfg": row.get("cfg") or {}, "erros": int(row.get("erros") or 0),
                                                 "trava_ate": row.get("trava_ate"), "em": _iso(time.time())}, upsert=True, on_conflict="user_id")

    # ------------------------------------------------------------------ senha de compra
    async def _open(self, uid: str, wal: dict, senha: str) -> str:
        """Abre a chave com a senha, contando as erradas. A trava fica no banco: reiniciar o servidor não zera."""
        row = await self._cfg_row(uid)
        ate = _ts(row.get("trava_ate")) if row.get("trava_ate") else 0
        if ate > time.time():
            raise BuyError(f"senha errada demais: travado por mais {max(1, round((ate - time.time()) / 60))} min")
        if not isinstance(senha, str) or not senha or len(senha) > vault.SENHA_MAX:
            raise BuyError("digite a senha de compra")
        try:
            secret = await asyncio.to_thread(vault.unseal, self.box, uid, wal["rede"], wal["endereco"], wal["cifra"], senha)
        except vault.WrongPassword:
            row["erros"] = int(row.get("erros") or 0) + 1
            left = MAX_TRIES - row["erros"]
            if left <= 0:
                row["erros"], row["trava_ate"] = 0, _iso(time.time() + LOCK_S)
            await self._put_cfg(row)
            raise BuyError("senha de compra errada" + (f" (mais {left} tentativas)" if left > 0 else f": travado por {LOCK_S // 60} min")) from None
        except CryptoError:
            raise BuyError("a chave guardada não abre (a chave mestra do servidor mudou?): tire a carteira e cadastre de novo") from None
        if row.get("erros") or row.get("trava_ate"):
            row["erros"], row["trava_ate"] = 0, None
            await self._put_cfg(row)
        return secret

    async def _any_secret(self, uid: str) -> dict | None:
        """Qualquer coisa já cifrada com a senha de compra (carteira ou chave de exchange), no formato que _open entende."""
        rows = await self.db.select("dormant_wallets", {"user_id": uid}, limit=1) or []
        if rows:
            return rows[0]
        for r in await self.db.select("dormant_cex_keys", {"user_id": uid}) or []:
            if not (r.get("info") or {}).get("sem_senha"):     # chave salva sem senha (0.32.320) não serve para conferir a senha
                return {"rede": "cex:" + r["exchange"], "endereco": r["rotulo"], "cifra": r["cifra"]}
        return None

    async def _check_senha(self, uid: str, senha: str) -> None:
        """Confere a senha contra o que já está guardado. Sem nada ainda: a senha nova vale como a primeira."""
        row = await self._any_secret(uid)
        if row:
            await self._open(uid, row, senha)
        else:
            why = vault.check_new_password(senha)
            if why:
                raise BuyError(why)

    # ------------------------------------------------------------------ carteiras
    async def wallets(self, uid: str) -> dict:
        rows = {r["rede"]: r for r in await self.db.select("dormant_wallets", {"user_id": uid}, columns="rede,endereco,em") or []}
        row = await self._cfg_row(uid)
        ate = _ts(row.get("trava_ate")) if row.get("trava_ate") else 0
        return {"redes": [{"rede": k, "nome": c["nome"], "tipo": c["tipo"], "moeda": c["moeda"], "dex": c["dex"], "endereco": (rows.get(k) or {}).get("endereco"),
                           "em": _ts((rows.get(k) or {}).get("em")) or None} for k, c in CHAINS.items()],
                "cfg": clean_cfg(None, row.get("cfg") or {}), "limites": CFG_LIMITS, "tem_senha": bool(rows) or bool(await self._any_secret(uid)), "trava_s": max(0, round(ate - time.time())),
                "trava_geral": bool(self.allowed()), "senha_min": vault.SENHA_MIN}

    async def save_wallet(self, uid: str, chain: str, secret: str, senha: str, todas_evm: bool = False) -> dict:
        if chain not in CHAINS:
            raise BuyError("rede inválida")
        if not isinstance(secret, str) or not 40 <= len(secret.strip()) <= 800:
            raise BuyError({"cardano": "isso não parece uma frase de recuperação", "cosmos": "isso não parece uma frase de recuperação nem uma chave privada"}.get(CHAINS[chain]["tipo"], "isso não parece uma chave privada"))
        secret = secret.strip()
        if CHAINS[chain]["tipo"] in ("cardano", "cosmos") and len(secret.split()) >= 12:   # frase: um espaço entre palavras, minúsculas
            secret = " ".join(secret.lower().split())
        try:
            addr = key_address(chain, secret)
        except ValueError as e:
            raise BuyError(str(e)) from None
        except Exception:
            raise BuyError("isso não parece uma chave privada") from None
        async with self.lock(uid):
            await self._check_senha(uid, senha)
            alvo = EVM_CHAINS if todas_evm and CHAINS[chain]["tipo"] == "evm" else [chain]
            for k in alvo:
                cifra = await asyncio.to_thread(vault.seal, self.box, uid, k, addr, secret, senha)
                await self.db.insert("dormant_wallets", {"user_id": uid, "rede": k, "endereco": addr, "cifra": cifra, "em": _iso(time.time())},
                                     upsert=True, on_conflict="user_id,rede")
        return {"endereco": addr, "redes": alvo}

    async def copy_evm(self, uid: str, senha: str) -> dict:
        """0.32.257 (pedido do dono, 07/11/2026): a mesma chave EVM nas redes EVM que ainda estão sem carteira, sem colar de novo. Abre a chave
        já guardada com a senha de compra (conta tentativa errada) e cifra de novo para cada rede nova; as que já têm carteira não mudam."""
        async with self.lock(uid):
            rows = [r for r in await self.db.select("dormant_wallets", {"user_id": uid}) or [] if (CHAINS.get(r.get("rede")) or {}).get("tipo") == "evm"]
            if not rows:
                raise BuyError("cadastre a chave em uma rede EVM primeiro")
            cont: dict[str, int] = {}
            for r in rows:
                cont[r["endereco"]] = cont.get(r["endereco"], 0) + 1
            addr = max(cont, key=lambda a: cont[a])
            src = next((r for r in rows if r["endereco"] == addr and r["rede"] == "ethereum"), None) or next(r for r in rows if r["endereco"] == addr)
            secret = await self._open(uid, src, senha)
            if key_address(src["rede"], secret) != addr:
                raise BuyError("a chave guardada não bate com o endereço: nada foi copiado")
            tem = {r["rede"] for r in rows}
            novas = [k for k in EVM_CHAINS if k not in tem]
            for k in novas:
                cifra = await asyncio.to_thread(vault.seal, self.box, uid, k, addr, secret, senha)
                await self.db.insert("dormant_wallets", {"user_id": uid, "rede": k, "endereco": addr, "cifra": cifra, "em": _iso(time.time())},
                                     upsert=True, on_conflict="user_id,rede")
        return {"endereco": addr, "redes": novas}

    async def remove_wallet(self, uid: str, chain: str) -> None:
        # sem senha, de propósito: quem esqueceu a senha precisa conseguir tirar a chave. Só apaga; não dá acesso a nada.
        if chain not in CHAINS:
            raise BuyError("rede inválida")
        await self.db.delete("dormant_wallets", {"user_id": uid, "rede": chain})

    async def change_password(self, uid: str, atual: str, nova: str) -> int:
        why = vault.check_new_password(nova)
        if why:
            raise BuyError(why)
        async with self.lock(uid):
            rows = await self.db.select("dormant_wallets", {"user_id": uid}) or []
            chaves = await self.db.select("dormant_cex_keys", {"user_id": uid}) or []
            if not rows and not chaves:
                raise BuyError("ainda não há carteira nem chave cadastrada")
            novas, novas_cex = [], []
            for r in rows:                         # abre tudo antes de gravar qualquer coisa: ou troca todas, ou nenhuma
                secret = await self._open(uid, r, atual)
                novas.append({"user_id": uid, "rede": r["rede"], "endereco": r["endereco"], "em": r.get("em") or _iso(time.time()),
                              "cifra": await asyncio.to_thread(vault.seal, self.box, uid, r["rede"], r["endereco"], secret, nova)})
            for r in chaves:
                pseudo = {"rede": "cex:" + r["exchange"], "endereco": r["rotulo"], "cifra": r["cifra"]}
                info = dict(r.get("info") or {})
                if info.pop("sem_senha", None):        # chave salva sem senha: passa a usar a senha nova
                    secret = await asyncio.to_thread(vault.unseal, self.box, uid, pseudo["rede"], pseudo["endereco"], pseudo["cifra"], "")
                else:
                    secret = await self._open(uid, pseudo, atual)
                novas_cex.append({"user_id": uid, "exchange": r["exchange"], "rotulo": r["rotulo"], "info": info, "em": r.get("em") or _iso(time.time()),
                                  "cifra": await asyncio.to_thread(vault.seal, self.box, uid, pseudo["rede"], r["rotulo"], secret, nova)})
            if novas:
                await self.db.insert("dormant_wallets", novas, upsert=True, on_conflict="user_id,rede")
            if novas_cex:
                await self.db.insert("dormant_cex_keys", novas_cex, upsert=True, on_conflict="user_id,exchange")
        return len(novas) + len(novas_cex)

    # ------------------------------------------------------------------ ligar e limites
    async def set_on(self, uid: str, on: bool, senha: str = "", confirmar: str = "") -> dict:
        row = await self._cfg_row(uid)
        c = clean_cfg(None, row.get("cfg") or {})
        if on:
            if confirmar != "LIGAR":
                raise BuyError("digite LIGAR para confirmar")
            first = await self._any_secret(uid)
            if not first:
                raise BuyError("cadastre uma carteira ou chave de exchange antes")
            async with self.lock(uid):
                await self._open(uid, first, senha)
            row = await self._cfg_row(uid)
        c["on"] = bool(on)                         # desligar não pede nada: tem que ser fácil
        row["cfg"] = c
        await self._put_cfg(row)
        return c

    async def save_limits(self, uid: str, raw: dict, senha: str) -> dict:
        first = await self._any_secret(uid)
        row = await self._cfg_row(uid)
        base = clean_cfg(None, row.get("cfg") or {})
        novo = clean_cfg(raw, base)
        if first and any(novo[k] > base[k] for k in CFG_LIMITS):   # só subir limite pede a senha; baixar é sempre livre
            async with self.lock(uid):
                await self._open(uid, first, senha)
            row = await self._cfg_row(uid)
        row["cfg"] = novo
        await self._put_cfg(row)
        return novo

    async def save_tg(self, uid: str, on, tipos) -> dict:
        """0.32.329: liga/desliga o aviso no Telegram e escolhe os tipos de alerta. Não mexe em dinheiro: não pede a senha."""
        row = await self._cfg_row(uid)
        base = clean_cfg(None, row.get("cfg") or {})
        base["tg_on"] = bool(on)
        base["tg_tipos"] = [t for t in TG_TIPOS if t in (tipos if isinstance(tipos, list) else TG_TIPOS)] or list(TG_TIPOS)
        row["cfg"] = base
        await self._put_cfg(row)
        return base

    # ------------------------------------------------------------------ histórico
    async def history(self, uid: str) -> dict:
        await self.resolve_pending(uid)
        rows = await self._rows(uid)
        sells = await self.db.select("dormant_sells", {"user_id": uid}, order="em.desc", limit=500) or []
        self.watch.held.update(r["cg"] for r in rows if r.get("cg") and r.get("status") == "confirmada")
        out = holdings(rows, self.watch, time.time(), sells=sells)
        out["vendas"] = [{**s, "t": _ts(s.get("em")), "rede_nome": (CHAINS.get(s.get("rede")) or {}).get("nome"), "moeda": (CHAINS.get(s.get("rede")) or {}).get("moeda"),
                          "expl": (CHAINS.get(s.get("rede")) or {}).get("expl")} for s in sells]
        return out
