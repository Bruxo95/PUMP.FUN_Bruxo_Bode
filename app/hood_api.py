"""Rotas da Robinhood Chain (0.32.208). Só admin. Separadas de api.py e da BNB para ficar isolada do que já funciona."""
from __future__ import annotations

from fastapi import Depends

from .db import audit


def add_routes(app, get_watch, admin_only, db) -> None:
    @app.get("/api/hood")
    async def hood_state(u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"ligado": False, "motivo": "leitura da Robinhood Chain desligada no servidor (HOOD_ON=false)"}
        return w.state()

    # 0.32.294 (pedido do dono): moedas com mais dinheiro entrando e a lista de usuários (só admin, como todo o /hood)
    @app.get("/api/hood/fluxo")
    async def hood_fluxo(h: float = 1.0, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"ligado": False}
        out = w.flow(hours=min(24.0, max(0.25, float(h or 1))), limit=60)
        await w.fill_names([r["token"] for r in out["rows"]])
        w.copier._spawn(w.flow_scan([r["token"] for r in out["rows"]]))   # 0.32.303: confere as moedas da lista sem esperar a cópia
        for r in out["rows"]:
            m = w.copier.meta.get(r["token"]) or {}
            r["nome"], r["simbolo"] = m.get("nome") or r.get("nome"), m.get("simbolo") or r.get("simbolo")
        return out

    @app.post("/api/hood/token/bloquear")
    async def hood_token_bloquear(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        tk, on = str((body or {}).get("token") or ""), bool((body or {}).get("on"))
        try:
            bl = await w.copier.block_token(u["id"], tk, on)
        except ValueError as e:
            return {"error": str(e)}
        await audit(db, u["id"], "Robinhood: " + ("bloquear moeda" if on else "desbloquear moeda"), tk[:42])
        return {"ok": True, "tokens_bloqueados": bl}

    @app.post("/api/hood/token/comprar")
    async def hood_token_comprar(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        tk, modo = str((body or {}).get("token") or ""), str((body or {}).get("modo") or "sim")
        try:
            r = await w.copier.buy_token(u["id"], tk, modo)
        except ValueError as e:
            return {"error": str(e)}
        await audit(db, u["id"], "Robinhood: comprar moeda pelo botão (" + {"sim": "FICTÍCIA", "real": "REAL", "ambas": "FICTÍCIA e REAL"}.get(modo, modo) + ")", tk[:42])
        return {"ok": True, **r}

    @app.get("/api/hood/usuarios")
    async def hood_usuarios(u: dict = Depends(admin_only)):
        w = get_watch()
        rows = await db.select("profiles", None, order="criado_em.asc") or []
        out = []
        for p in rows:
            uid = p.get("user_id")
            out.append({"user_id": uid, "email": p.get("email"), "nome": p.get("nome"), "avatar_url": p.get("avatar_url"),
                        "role": p.get("role") or "user", "bloqueado": bool(p.get("bloqueado")), "ultimo_acesso": p.get("ultimo_acesso"),
                        "criado_em": p.get("criado_em"), "hood": w.copier.user_summary(uid) if w is not None else None})
        return {"users": out, "me": u["id"]}

    @app.post("/api/hood/cfg")
    async def hood_cfg(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        cfg = await w.save_cfg(body if isinstance(body, dict) else {})
        await audit(db, u["id"], "Robinhood: regra do ranking mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}

    # 0.32.279 (pedido do dono, 10/11: "faz 1 a 4"): cópia fictícia em ETH, conferência do token e carteira REAL (desligada)
    def cp():
        w = get_watch()
        return None if w is None else w.copier

    @app.get("/api/hood/painel")
    async def hood_painel(real: int = 0, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"ligado": False, "motivo": "leitura da Robinhood Chain desligada no servidor (HOOD_ON=false)"}
        await c.get_key(u["id"])                      # endereço da carteira (a chave nunca vai para a tela)
        return {"ligado": True, **c.painel(u["id"], real=bool(real))}

    @app.post("/api/hood/conta")
    async def hood_conta(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        cfg = await c.save_book_cfg(u["id"], body if isinstance(body, dict) else {})
        await audit(db, u["id"], "Robinhood: configuração da cópia fictícia mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}

    @app.post("/api/hood/seguir")
    async def hood_seguir(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        w, on = str((body or {}).get("wallet") or ""), bool((body or {}).get("on"))
        modo = str((body or {}).get("modo") or "ambas")
        try:
            lst = await c.follow(u["id"], w, on, modo)
        except ValueError as e:
            return {"error": str(e)}
        nomes = {"sim": "só FICTÍCIA", "real": "só REAL", "ambas": "FICTÍCIA e REAL"}
        await audit(db, u["id"], "Robinhood: " + ("copiar trader (" + nomes.get(modo, modo) + ")" if on else "parar de copiar trader"), w[:42])
        return {"ok": True, "manual": lst, "modo": c.book(u["id"]).cfg.get("modo") or {}}

    # 0.32.313 (pedido do dono): comparar e copiar a configuração de outro usuário (como na Solana). Só entre admins, só leitura
    # da conta do outro; a cópia mexe só na conta de quem clica, nunca liga a REAL nem mexe no saldo.
    def _mask(e):
        e = str(e or "")
        if "@" not in e:
            return ""
        n, d = e.split("@", 1)
        return n[:2] + "***@" + d

    async def _admins(me):
        rows = await db.select("profiles", {"role": "admin"}) or []
        return [p for p in rows if p.get("user_id") and p.get("user_id") != me and not p.get("bloqueado")]

    @app.get("/api/hood/config/usuarios")
    async def hood_cfg_users(u: dict = Depends(admin_only)):
        c = cp()
        out = [{"user_id": p["user_id"], "nome": p.get("nome") or _mask(p.get("email")) or "sem nome", "email": _mask(p.get("email")),
                "tem_conta": bool(c and c.share_cfg(p["user_id"]))} for p in await _admins(u["id"])]
        out.sort(key=lambda x: (not x["tem_conta"], x["nome"].lower()))
        return {"users": out}

    @app.get("/api/hood/config/peer")
    async def hood_cfg_peer(uid: str, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        if uid not in {p["user_id"] for p in await _admins(u["id"])}:
            return {"error": "conta não encontrada"}
        src = c.share_cfg(uid)
        if src is None:
            return {"error": "essa conta ainda não abriu a Robinhood"}
        return {"ok": True, **src}

    @app.post("/api/hood/config/copiar")
    async def hood_cfg_copy(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        b = body if isinstance(body, dict) else {}
        peer = str(b.get("uid") or "")
        adm = {p["user_id"]: p for p in await _admins(u["id"])}
        if peer not in adm:
            return {"error": "conta não encontrada"}
        keys = b.get("keys")
        keys = [str(k) for k in keys][:200] if isinstance(keys, list) else None
        try:
            r = await c.copy_cfg(u["id"], peer, keys, traders=bool(b.get("traders")), bloqueios=bool(b.get("bloqueios")))
        except ValueError as e:
            return {"error": str(e)}
        nome = adm[peer].get("nome") or _mask(adm[peer].get("email"))
        await audit(db, u["id"], "Robinhood: configuração copiada de outro usuário",
                    f"de {nome}: {r['ficticia']} na FICTÍCIA, {r['real']} na REAL" + (", traders" if b.get("traders") else "") +
                    (", bloqueios" if b.get("bloqueios") else ""))
        return {"ok": True, **r}

    @app.post("/api/hood/bloquear")
    async def hood_bloquear(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        w, on = str((body or {}).get("wallet") or ""), bool((body or {}).get("on"))
        try:
            bl = await c.block(u["id"], w, on)
        except ValueError as e:
            return {"error": str(e)}
        await audit(db, u["id"], "Robinhood: " + ("bloquear trader" if on else "desbloquear trader"), w[:42])
        b = c.book(u["id"])
        return {"ok": True, "bloqueados": bl, "manual": b.cfg.get("manual") or [], "modo": b.cfg.get("modo") or {}}

    # 0.32.286 (pedido do dono): saldo da carteira, se precisa abastecer, e abastecer de outra rede pela Relay
    @app.get("/api/hood/abastecer")
    async def hood_gas(u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        return await c.gas.status(u["id"])

    @app.post("/api/hood/abastecer/cotar")
    async def hood_gas_quote(body: dict, u: dict = Depends(admin_only)):
        from .hoodgas import FillError
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        try:
            return await c.gas.preview(u["id"], str((body or {}).get("origem") or ""), (body or {}).get("usd"))
        except FillError as e:
            return {"error": str(e)}

    @app.post("/api/hood/abastecer/confirmar")
    async def hood_gas_fill(body: dict, u: dict = Depends(admin_only)):
        from .hoodgas import FillError
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        try:
            row = await c.gas.fill(u["id"], str((body or {}).get("quote_id") or ""), str((body or {}).get("confirmar") or ""))
        except FillError as e:
            return {"error": str(e)}
        await audit(db, u["id"], "Robinhood: abastecer de outra rede", f"{row['origem_nome']} → Robinhood · US$ {row['usd']:.2f} · {row['tx']}")
        return {"ok": True, "abastecimento": row}

    @app.post("/api/hood/fechar")
    async def hood_fechar(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        pid, real = str((body or {}).get("id") or ""), bool((body or {}).get("real"))
        try:
            tr = await c.close_real(u["id"], pid) if real else c.close_manual(u["id"], pid)
        except Exception as e:
            return {"error": "a venda REAL não saiu: " + str(e)[:200]}
        if not tr:
            return {"error": "posição não encontrada (já fechou?)"}
        await c.flush()
        await audit(db, u["id"], "Robinhood: vendeu posição " + ("REAL" if real else "fictícia"), f"{tr['token'][:10]}… {tr['pnl_eth']:+.5f} ETH")
        return {"ok": True, "trade": tr}

    @app.post("/api/hood/fechar-todas")
    async def hood_fechar_todas(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        real = bool((body or {}).get("real"))
        if real and str((body or {}).get("confirm") or "").strip().upper() != "VENDER":
            return {"error": "para vender todas as posições REAL, digite VENDER"}
        r = await c.close_all(u["id"], real)
        await audit(db, u["id"], "Robinhood: vendeu todas as posições " + ("REAL" if real else "fictícias"), f"{r['vendidas']} vendidas, {r['falhas']} falharam")
        return {"ok": True, **r}

    @app.post("/api/hood/chave")
    async def hood_chave(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None or c.vault is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        try:
            addr = await c.set_key(u["id"], str((body or {}).get("value") or ""))
        except ValueError as e:
            return {"error": str(e)}
        except Exception:
            return {"error": "não consegui salvar no banco agora"}
        await audit(db, u["id"], "Robinhood: salvar chave da carteira", addr)       # só o endereço público, nunca a chave
        return {"ok": True, "endereco": addr}

    @app.post("/api/hood/chave/remover")
    async def hood_chave_remover(u: dict = Depends(admin_only)):
        c = cp()
        if c is None or c.vault is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        await c.remove_key(u["id"])
        await audit(db, u["id"], "Robinhood: remover chave da carteira", "execução REAL da Robinhood desligada")
        return {"ok": True}

    @app.post("/api/hood/real")
    async def hood_real(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        on = bool((body or {}).get("on"))
        if on and str((body or {}).get("confirm") or "").strip().upper() != "LIGAR":
            return {"error": "para ligar a REAL da Robinhood, digite LIGAR"}
        try:
            st = await c.set_real(u["id"], on)
        except ValueError as e:
            return {"error": str(e)}
        await audit(db, u["id"], "Robinhood: execução REAL " + ("ligada" if on else "desligada"), st.get("endereco") or "")
        return {"ok": True, "status": st}

    @app.post("/api/hood/conta/zerar")
    async def hood_zerar(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        if str((body or {}).get("confirma") or "").strip().upper() != "ZERAR":
            return {"error": "para zerar a carteira fictícia, digite ZERAR"}
        r = await c.reset_sim(u["id"])
        await audit(db, u["id"], "Robinhood: carteira fictícia zerada", f"{r['abertas']} abertas e {r['fechadas']} fechadas apagadas, saldo {r['saldo']:g} ETH")
        return {"ok": True, **r}

    @app.post("/api/hood/real/cfg")
    async def hood_real_cfg(body: dict, u: dict = Depends(admin_only)):
        c = cp()
        if c is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        rc = await c.save_real_cfg(u["id"], body if isinstance(body, dict) else {})
        await audit(db, u["id"], "Robinhood: valores da REAL mudados", ", ".join(f"{k}={v}" for k, v in sorted(rc.items()) if k != "on_since"))
        return {"ok": True, "cfg": rc}
