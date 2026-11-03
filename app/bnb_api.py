"""Rotas do painel BNB (0.32.168). Só admin. Separadas de api.py para a BNB ficar isolada do que já funciona."""
from __future__ import annotations

from fastapi import Depends

from .db import audit

OFF = {"ligado": False, "motivo": "leitura da BNB desligada no servidor (BNB_ON=false)"}


def add_routes(app, get_watch, admin_only, db) -> None:
    @app.get("/api/pump/bnb")
    async def bnb_state(u: dict = Depends(admin_only)):
        w = get_watch()
        return OFF if w is None else w.state()

    @app.post("/api/pump/bnb/cfg")
    async def bnb_cfg(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        cfg = await w.save_cfg(body if isinstance(body, dict) else {})
        await audit(db, u["id"], "BNB: regra do ranking mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}

    # 0.32.170: carteira fictícia da conta (Visão geral, Posições, Histórico, Semana × fim de semana, Abas, Configurações)
    @app.get("/api/pump/bnb/painel")
    async def bnb_painel(real: int = 0, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return OFF
        await w.get_key(u["id"])                      # endereço da carteira BNB (a chave nunca vai para a tela)
        return {"ligado": True, **w.painel(u["id"], real=bool(real))}

    @app.post("/api/pump/bnb/conta")
    async def bnb_conta(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        cfg = await w.save_book_cfg(u["id"], body if isinstance(body, dict) else {})
        await audit(db, u["id"], "BNB: configuração da cópia fictícia mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}

    @app.post("/api/pump/bnb/fechar")
    async def bnb_fechar(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        pid, real = str((body or {}).get("id") or ""), bool((body or {}).get("real"))
        try:
            tr = await w.close_real(u["id"], pid) if real else w.close_manual(u["id"], pid)
        except Exception as e:
            return {"error": "a venda REAL não saiu: " + str(e)[:200]}
        if not tr:
            return {"error": "posição não encontrada (já fechou?)"}
        await w.flush_books()
        await audit(db, u["id"], "BNB: vendeu posição " + ("REAL" if real else "fictícia"), f"{tr['token'][:10]}… {tr['pnl_bnb']:+.4f} BNB")
        return {"ok": True, "trade": tr}

    # 0.32.172 (pedido do dono, 03/11): Vender todas (fictícia ou REAL) e a carteira REAL da BNB
    @app.post("/api/pump/bnb/fechar-todas")
    async def bnb_fechar_todas(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        real = bool((body or {}).get("real"))
        if real and str((body or {}).get("confirm") or "").strip().upper() != "VENDER":
            return {"error": "para vender todas as posições REAL, digite VENDER"}
        r = await w.close_all(u["id"], real)
        await audit(db, u["id"], "BNB: vendeu todas as posições " + ("REAL" if real else "fictícias"),
                    f"{r['vendidas']} vendidas, {r['falhas']} falharam")
        return {"ok": True, **r}

    @app.post("/api/pump/bnb/chave")
    async def bnb_chave(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None or w.vault is None:
            return {"error": "leitura da BNB desligada no servidor"}
        try:
            addr = await w.set_key(u["id"], str((body or {}).get("value") or ""))
        except ValueError as e:
            return {"error": str(e)}
        except Exception:
            return {"error": "não consegui salvar no banco agora"}
        await audit(db, u["id"], "BNB: salvar chave da carteira", addr)          # só o endereço público, nunca a chave
        return {"ok": True, "endereco": addr}

    @app.post("/api/pump/bnb/chave/remover")
    async def bnb_chave_remover(u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None or w.vault is None:
            return {"error": "leitura da BNB desligada no servidor"}
        await w.remove_key(u["id"])
        await audit(db, u["id"], "BNB: remover chave da carteira", "execução REAL da BNB desligada")
        return {"ok": True}

    @app.post("/api/pump/bnb/real")
    async def bnb_real(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        on = bool((body or {}).get("on"))
        if on and str((body or {}).get("confirm") or "").strip().upper() != "LIGAR":
            return {"error": "para ligar a REAL da BNB, digite LIGAR"}
        try:
            st = await w.set_real(u["id"], on)
        except ValueError as e:
            return {"error": str(e)}
        await audit(db, u["id"], "BNB: execução REAL " + ("ligada" if on else "desligada"), st.get("endereco") or "")
        return {"ok": True, "status": st}

    @app.post("/api/pump/bnb/real/cfg")
    async def bnb_real_cfg(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        rc = await w.save_real_cfg(u["id"], body if isinstance(body, dict) else {})
        await audit(db, u["id"], "BNB: valores da REAL mudados",
                    ", ".join(f"{k}={v}" for k, v in sorted(rc.items()) if k not in ("on_since",)))
        return {"ok": True, "cfg": rc}
