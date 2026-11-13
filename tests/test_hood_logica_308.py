"""0.32.336 (pedido do dono, 13/11): a lógica de compra e venda da Robinhood voltou à da 0.32.308. Ficam o histórico e a cópia de
configuração (0.32.313/0.32.319), que não mexem em compra nem venda."""
from app import hoodcopy, hoodreal


def test_motor_da_robinhood_e_o_da_0_32_308():
    assert not hasattr(hoodreal, "SellBlocked")                     # venda em partes/trava de venda (0.32.309) ficou de fora
    assert "sg_on" not in hoodcopy.CFG_DEFAULT and "so_verificado" not in hoodcopy.CFG_DEFAULT
    assert hoodcopy.CFG_LIMITS["eth_por_compra"][0] == 0.0005
    for m in ("cfg_history", "cfg_back", "share_cfg", "copy_cfg"):
        assert hasattr(hoodcopy.Copier, m)
