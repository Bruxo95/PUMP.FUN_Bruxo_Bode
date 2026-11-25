"""0.32.458 (pedido do dono): compras × vendas do BOOST ao vivo pela blockchain, desde o instante em que o token entra na análise.
Sem internet: logs de transação montados aqui no formato que o RPC manda no logsNotification."""
from app import boostflow
from app.boostflow import Flow, merge, parse_logs
from app.boostmig import BoostMig
from tests.test_boostmig import DEV, M, M2, Svc, pronto, run

AMM, PF = boostflow.PROGS[1], boostflow.PROGS[0]
CB = "ComputeBudget111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def tx(prog, ins, via=None):
    out = [f"Program {CB} invoke [1]", f"Program {CB} success"]
    d = 1
    if via:
        out.append(f"Program {via} invoke [1]")
        d = 2
    out += [f"Program {prog} invoke [{d}]", f"Program log: Instruction: {ins}",
            f"Program {TOKEN} invoke [{d + 1}]", "Program log: Instruction: TransferChecked", f"Program {TOKEN} success",
            f"Program {prog} success"]
    if via:
        out.append(f"Program {via} success")
    return out


def test_le_compra_e_venda_da_pumpswap_e_da_curva_mesmo_por_roteador():
    assert parse_logs(tx(AMM, "Buy")) == (1, 0)
    assert parse_logs(tx(AMM, "Sell")) == (0, 1)
    assert parse_logs(tx(PF, "BuyExactSolIn")) == (1, 0)
    assert parse_logs(tx(AMM, "Buy", via="JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")) == (1, 0)   # por roteador (CPI)
    # "Instruction: Transfer" do programa de token não conta; programa que não é da pump.fun também não
    assert parse_logs(tx("Outro1111111111111111111111111111111111111", "Buy")) == (0, 0)
    assert parse_logs(["Program log: Instruction: Buy"]) == (0, 0)


def test_conta_uma_vez_por_assinatura_e_so_os_ultimos_5_min():
    t = [1000.0]
    fl = Flow(clock=lambda: t[0])
    fl.start(M, 1000)
    fl.note(M, "s1", tx(AMM, "Buy"))
    fl.note(M, "s1", tx(AMM, "Buy"))                    # mesma transação chegou de novo
    fl.note(M, "s2", tx(AMM, "Sell"))
    fl.note(M, "s3", tx(AMM, "Buy"), err={"InstructionError": [2, {"Custom": 6004}]})   # falhou: não conta
    assert fl.count(M) == {"buys": 1, "sells": 1, "cobre_s": 0, "since": 1000, "last": 1000}
    t[0] = 1301
    assert fl.count(M)["buys"] == 0 and fl.count(M)["cobre_s"] == 300
    assert fl.count(M2) is None


def test_vale_o_maior_entre_blockchain_e_dexscreener():
    assert merge({"buys": 85, "sells": 20}, None) == (85, 20, "blockchain")
    assert merge({"buys": 85, "sells": 20}, {"buys_m5": 0, "sells_m5": 0}) == (85, 20, "blockchain")
    assert merge({"buys": 10, "sells": 3}, {"buys_m5": 90, "sells_m5": 40}) == (90, 40, "DexScreener")   # assinou atrasado
    assert merge(None, {"buys_m5": 7, "sells_m5": 2}) == (7, 2, "DexScreener")
    assert merge(None, {}) == (None, None, None)


def test_assina_o_token_que_esta_em_analise_e_solta_quando_todos_descartam():
    now = 5_000_000.0
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 20, now)                    # acabou de migrar, ninguém analisou: já assina
    assert bm.flow_want(now) == [M]
    b["users"] = {"u1": {"estado": "esperar"}}
    assert bm.flow_want(now) == [M]
    b["users"] = {"u1": {"estado": "fora", "real": {"estado": "fora"}}}
    assert bm.flow_want(now) == []                      # todos descartaram
    b["users"] = {"u1": {"estado": "esperar"}}
    bm.scam_devs[DEV] = {"t": now, "mints": {}}
    assert bm.flow_want(now) == []                      # DEV scam
    del bm.scam_devs[DEV]
    b["users"] = {"u1": {"estado": "entrou"}}
    assert bm.flow_want(now + 600) == [M]               # quem está dentro segue até o fim do BOOST e do tempo extra
    b["users"] = {}
    assert bm.flow_want(now + 600) == []                # BOOST acabou e ninguém dentro
    bm.q["ativo"] = False
    assert bm.flow_want(now) == []                      # consultas do BOOST ativo desligadas


def test_contagem_da_blockchain_aparece_antes_da_dexscreener_e_libera_a_entrada():
    """Caso SPCXDROP (25/11): 12% do BOOST com "aguardando compras: 0 de 80" porque a DexScreener ainda não tinha o par."""
    now = 6_000_000.0
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 36, now, buys_m5=None, sells_m5=None)
    bm.flow.start(M, now - 35)
    bm.flow_subs = {M}
    for i in range(95):
        bm.flow.note(M, f"b{i}", tx(AMM, "Buy"), now=now - 30 + i * 0.2)
    for i in range(30):
        bm.flow.note(M, f"s{i}", tx(AMM, "Sell"), now=now - 20 + i * 0.2)
    run(bm.tick(now))
    assert (b["buys_m5"], b["sells_m5"], b["buys_src"]) == (95, 30, "blockchain")
    assert bm.view(b)["buys_src"] == "blockchain"
