"""Curva da pump.fun cotada em outra moeda (SPCX, ZEC…): não usar a conta da curva como preço em SOL (0.31.52).
Caso real: SEALLIS deu +133.475% porque a entrada foi calculada ~1.000× mais barata. Contas copiadas da mainnet
em 2026-10-27 (públicas)."""
import asyncio
import base64

from tests.test_pump import _pump

SPCX_CURVE = "F7f4N2DYrGAz+mfC9EkBAOnF7AMAAAAAM2JVdmNLAAB/EZkCAAAAAACAxqR+jQMAAJQMuJjP8yyaxCsyjlRluagtZgMznm5py6rE18t0z2i+AAAGgJ7cv3QlqzNYXckcvuzhehb+FLCqPbXi4XlUIe+FgAAAAAAAAAAAAAEXFAAAAAAAAMwfAAAAAAAAAGq0UwEAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
SOL_CURVE = "F7f4N2DYrGDc9M7pZawCAINJuPUJAAAA3Fy8ndStAQCDnZT5AgAAAACAxqR+jQMAABnEz+/4a6jhVlzFyS+PzKiv047OSklAuahHbAYJRTKUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB7wAAAAAAAAAAAAAAAAAAAACsI/wGAAAAAAAAAAAAAAAAAAAAAAAAAA=="


def test_curve_quote_reads_quote_mint():
    from app.pumpfun import PumpFun
    assert PumpFun.curve_quote(base64.b64decode(SPCX_CURVE)) == "SPCXxcqXj6e5dJDVNovHN8744zkbhM2bYudU45BimGb"
    assert PumpFun.curve_quote(base64.b64decode(SOL_CURVE)) is None


def test_non_sol_curve_gives_no_sol_price(tmp_path):
    pf = _pump(tmp_path, paid=False)
    a, b = "Spcx".ljust(40, "1") + "pump", "SolC".ljust(40, "1") + "pump"
    pf.curve_pda = lambda m: "PDA" + m[:4]

    async def multi(keys, enc, public_first=False):
        return [{"data": [SPCX_CURVE if k == "PDASpcx" else SOL_CURVE, "base64"]} for k in keys]
    pf._rpc_multi = multi
    rest = asyncio.run(pf._curve_prices([a, b]))
    assert rest == [a] and "price" not in pf.tokens[a] and pf.tokens[a]["quote_mint"].startswith("SPCX")
    assert abs(pf.tokens[b]["price"] - 5.684650169865416e-08) < 1e-15                  # curva em SOL segue igual


JEWLON_CURVE = "F7f4N2DYrGDpxNvdqbIBABCn3rXqBQAA6SzJkRi0AAB4V7cNSAMAAACAxqR+jQMAAFHzsdpGEDJGoBNjVx18HFBT6k1Rhr3y9T39k4zI4cSnAAAFfxH+pDlVxGTNFWJUhE2nVuuSXF4L+hGKVyrXugZEZSwBAAAAAAAAAACTUY4YAAAAAAAAAAAAAAAAAZhPJ6iiAgAAAAAAAAAAAAAAAAAAAAAAAA=="


def test_jewlon_curve_is_quoted_in_ntrndm():
    """Jewlon (27/10): curva cotada em NTRNDM; a leitura antiga dava 56,7× o preço real e o alvo +150% disparou falso
    na carteira real do Bruxo (vendeu com −13%). A curva agora não vira preço em SOL."""
    from app.pumpfun import PumpFun
    assert PumpFun.curve_quote(base64.b64decode(JEWLON_CURVE)) == "NTRNDMqQSiwEC2jJs3wJiZS6bpGYQJtMNQJgiX3WyV6"
