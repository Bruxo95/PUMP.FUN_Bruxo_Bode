// 0.32.168 (pedido do dono, 02/11): painel BNB · Four.Meme, isolado do painel da Solana (arquivo próprio, rota própria).
// 0.32.169: página própria (/bnb), escolhida em /entrar; nada dela fica dentro do painel da pump.fun.
// 0.32.170 (pedido do dono, 03/11): menu no padrão do painel da pump.fun (Visão geral, Top traders, Posições, Histórico,
// Semana × fim de semana, Abas de trades, Configurações, Administração, Changelog), Fictícia/Real no topo e a cópia
// FICTÍCIA dos traders do ranking. A Real ainda não existe na BNB: a tela diz isso, nada é enviado.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = {
    visao: ["Visão geral", "sua carteira da BNB e o que a cópia fez"], traders: ["Top traders", "ranking da Four.Meme e quem é copiado"],
    posicoes: ["Posições", "o que está aberto agora"], historico: ["Histórico", "trades fechados"],
    semanas: ["Semana × fim de semana", "o resultado de segunda a sexta comparado com sábado e domingo"],
    abas: ["Abas de trades", "liga e desliga as compras de cada aba"], config: ["Configurações", "valor por compra, limites e saídas"],
    admin: ["Administração", "leitura da rede e regra do ranking"],
    logs: ["Log geral", "registro de segurança e log do servidor"], changelog: ["Changelog", "o que mudou no projeto da BNB"],
  };
  const REAL_VIEWS = ["visao", "posicoes", "historico", "semanas", "abas"];
  const RK_INFO = [
    ["days", "Dias do ranking", "dias", 1, 7, 1], ["min_trades", "Trades mínimos no período", "trades", 0, 100000, 1],
    ["min_winrate", "Acerto acima de", "%", 0, 100, 1], ["min_closed", "Tokens fechados mínimos (para medir o acerto)", "tokens", 1, 1000, 1],
    ["min_wallet_usd", "Saldo mínimo da carteira (BNB + dólar)", "US$", 0, 10000000, 100], ["online_min", "Online = negociou nos últimos", "min", 1, 1440, 1],
    ["top_n", "Quantos copia", "carteiras", 1, 50, 1], ["bot_per_day", "Robô = mais trades por dia que", "trades/dia", 10, 100000, 10],
  ];
  const CF_INFO = [
    ["bnb_por_compra", "BNB por compra", "BNB", 0.001, 10, 0.01], ["max_abertas", "Máximo de posições abertas", "posições", 1, 100, 1],
    ["max_hold_h", "Tempo máximo da posição", "horas", 0.1, 168, 0.5], ["stop_pct", "Stop de perda (0 = sem stop)", "%", 0, 100, 1],
    ["slip_pct", "Slippage em cada lado", "%", 0, 50, 0.5], ["gas_bnb", "Gás por transação", "BNB", 0, 0.01, 0.0001],
    ["saldo_inicial", "Saldo inicial da fictícia", "BNB", 0.01, 1000, 0.1],
  ];
  // 0.32.171 (pedido do dono, 03/11): Log geral com o Registro de segurança e o Log do servidor (as mesmas rotas de
  // Administração do painel da pump.fun). "Só BNB" filtra o que é da BNB; "Tudo" mostra os dois projetos.
  const LG = { tab: "seg", f: "bnb", lv: "INFO", after: 0, key: "" };
  let VIEW = "visao", REAL = false, R = null, P = null, CHG = null, BUSY = false, READY = false, DIRTY = { rk: false, cf: false };

  // ------------------------------------------------------------------ formatos
  const num = (v, d) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: d == null ? 4 : d }));
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
  const bnb = (v, d) => (v == null ? "—" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : "") + num(v, d == null ? 4 : d) + " BNB</span>");
  const pct = (v) => (v == null ? "—" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : "") + num(v, 1) + "%</span>");
  const hora = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
  function ago(t) {
    if (!t) return "—";
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : s < 86400 ? (s / 3600).toFixed(1).replace(".", ",") + " h" : (s / 86400).toFixed(1).replace(".", ",") + " dias";
  }
  const dur = (s) => (s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : (s / 3600).toFixed(1).replace(".", ",") + " h");
  const sw = (w) => esc(String(w).slice(0, 6) + "…" + String(w).slice(-4));
  const wal = (w) => '<a href="https://bscscan.com/address/' + esc(w) + '" target="_blank" rel="noopener" title="' + esc(w) + '">' + sw(w) + "</a>";
  const tok = (t) => '<a href="https://four.meme/token/' + esc(t) + '" target="_blank" rel="noopener" title="' + esc(t) + '">' + sw(t) + "</a>";
  const txl = (h) => (h ? '<a href="https://bscscan.com/tx/' + esc(h) + '" target="_blank" rel="noopener">ver</a>' : "—");

  function table(id, head, rows, empty) {
    const el = $(id); if (!el) return;
    if (!rows.length) { el.innerHTML = '<tr><td class="empty" colspan="' + head.length + '">' + esc(empty || "Nada por aqui ainda.") + "</td></tr>"; return; }
    const lab = head.map((h) => esc(String(h).replace(/<[^>]*>/g, "")));
    el.innerHTML = "<thead><tr>" + head.map((h) => "<th>" + h + "</th>").join("") + "</tr></thead><tbody>" +
      rows.map((r) => "<tr>" + r.map((c, i) => '<td data-l="' + lab[i] + '">' + (c == null ? "" : c) + "</td>").join("") + "</tr>").join("") + "</tbody>";
  }
  function kpis(id, items) {
    const el = $(id); if (!el) return;
    el.innerHTML = items.map((x) => '<div class="kpi"><div class="k"><span>' + x[0] + '</span></div><div class="v ' + (x[3] || "") + '">' + x[1] + '</div><div class="d">' + (x[2] || "&nbsp;") + "</div></div>").join("");
  }
  function form(id, info, cfg, padrao, pre) {
    $(id).innerHTML = info.map((c) => '<div class="field"><label for="' + pre + c[0] + '">' + esc(c[1]) + '</label><div class="row"><input class="in w80" id="' + pre + c[0] +
      '" type="number" min="' + c[3] + '" max="' + c[4] + '" step="' + c[5] + '" value="' + esc(cfg[c[0]]) + '"><span class="muted">' + esc(c[2]) +
      (padrao && padrao[c[0]] !== cfg[c[0]] ? " · padrão " + esc(padrao[c[0]]) : "") + "</span></div></div>").join("");
  }
  const realMsg = (id, cols) => table(id, Array(cols).fill(""), [], "Carteira REAL da BNB ainda não existe: só a FICTÍCIA.");

  // ------------------------------------------------------------------ telas
  function drawVisao() {
    if (!P) return;
    if (REAL) { kpis("ovK", [["Carteira REAL", "—", "ainda não existe na BNB"]]); $("ovP").innerHTML = ""; realMsg("ovOps", 4); return; }
    const w = P.carteira;
    kpis("ovK", [
      ["Saldo livre", num(w.saldo, 4) + " BNB", "inicial " + num(w.inicial, 4) + " BNB"],
      ["Em posições", num(w.em_posicoes, 4) + " BNB", w.abertas + " abertas"],
      ["Total", num(w.total, 4) + " BNB", "saldo + posições"],
      ["Resultado", bnb(w.resultado), pct(w.resultado_pct) + " desde o início", cls(w.resultado)],
      ["Fechadas", num(w.fechadas, 0), "realizado " + num(w.realizado, 4) + " BNB"],
      ["Acerto", w.acerto == null ? "—" : num(w.acerto, 0) + "%", "trades fechados com lucro"],
      ["Copiando agora", num((P.copiaria || []).length, 0), "traders do ranking"],
    ]);
    kpis("ovP", (w.periodos || []).map((x) => ["Últimas " + x.h + " h", bnb(x.pnl), x.n ? x.n + " trades · " + x.ganhos + " com lucro · " + x.traders + " traders" : "nenhum trade fechado", cls(x.pnl)]));
    table("ovOps", ["Hora", "Trader", "Token", "O que fez"], (P.eventos || []).slice(0, 40).map((e) => [hora(e.t), wal(e.wallet), tok(e.token), esc(e.acao) + (e.motivo ? ' <span class="muted">· ' + esc(e.motivo) + "</span>" : "")]),
      "Nenhuma operação ainda. Assim que um trader do ranking comprar, a fictícia copia.");
    const st = $("ovSt");
    st.className = "decbox " + (P.leitura_ok ? "ok" : "bad");
    st.innerHTML = (P.leitura_ok ? "Leitura da Four.Meme funcionando." : "<b>Leitura da Four.Meme com problema</b> (veja Administração).") +
      " Cópia fictícia: <b>" + (P.cfg.on ? "ligada" : "desligada") + "</b> · " + num(P.cfg.bnb_por_compra, 4) + " BNB por compra · até " + P.cfg.max_abertas +
      " posições · tempo máximo " + num(P.cfg.max_hold_h, 1) + " h" + (P.cfg.stop_pct ? " · stop " + P.cfg.stop_pct + "%" : " · sem stop") +
      ". Copiando " + (P.copiaria || []).length + " trader(s) agora.";
  }
  function drawTraders() {
    if (!R || !R.ligado) { kpis("bnK", [["Leitura", "desligada", (R && R.motivo) || "", "down"]]); return; }
    const s = R.status || {}, rk = R.ranking || { rows: [], copiaria: [] };
    kpis("bnK", [
      ["Trades em 24 h", num(s.trades_24h, 0), num(s.compras_24h, 0) + " compras · " + num(s.tokens_24h, 0) + " tokens"],
      ["Carteiras em 24 h", num(s.carteiras_24h, 0), "no ranking: " + num(rk.carteiras, 0) + " em " + num(R.cfg.days, 0) + " dias"],
      ["Aptos", num(rk.aptos, 0), num(rk.aptos_online, 0) + " online agora"],
      ["Copiados agora", num((rk.copiaria || []).length, 0), "de " + num(R.cfg.top_n, 0) + " vagas", (rk.copiaria || []).length ? "up" : ""],
      ["Último trade lido", ago(s.ultimo_trade_t), hora(s.ultimo_trade_t)],
      ["BNB em dólar", s.bnb_usd ? "US$ " + num(s.bnb_usd, 2) : "—", "PancakeSwap USDT/WBNB"],
    ]);
    $("nbTr").textContent = (rk.copiaria || []).length || "";
    $("bnSelSub").textContent = "os " + R.cfg.top_n + " melhores aptos que negociaram nos últimos " + R.cfg.online_min + " min · a fictícia copia as compras e vendas deles";
    const rows = rk.rows || [];
    const line = (r, i) => [String(i + 1), wal(r.wallet), bnb(r.realized_bnb), r.winrate == null ? "—" : num(r.winrate, 0) + "%",
      num(r.trades, 0) + " · " + num(r.per_day, 0) + "/dia", r.closed + " fechados · " + r.open + " abertos" + (r.grad_open ? " (" + r.grad_open + " já na Pancake)" : ""),
      r.wallet_usd == null ? "—" : "US$ " + num(r.wallet_usd, 0), (r.online ? '<span class="tag win">online</span> ' : "") + ago(r.last_t)];
    table("bnSel", ["#", "Carteira", "Lucro realizado", "Acerto", "Trades", "Tokens", "Saldo", "Último trade"],
      rows.filter((r) => r.copiaria).map((r) => line(r, rows.indexOf(r))),
      rows.length ? "Ninguém apto e online agora. O ranking enche com os dias; veja o motivo de cada um abaixo." : "Ainda sem trades lidos.");
    $("bnRkSub").textContent = "os 50 que mais lucraram em " + R.cfg.days + " dias · " + (rk.fora_moeda ? rk.fora_moeda + " trades fora das contas (moeda da curva desconhecida)" : "todos os trades nas contas");
    table("bnRk", ["#", "Carteira", "Lucro realizado", "Acerto", "Trades", "Tokens", "Saldo", "Último trade", "Por que não"],
      rows.map((r, i) => line(r, i).concat([r.copiaria ? '<span class="tag win">copiando</span>' : r.eligible ? '<span class="muted">apto, mas offline ou fora das vagas</span>' : esc((r.flags || []).join(" · "))])),
      "Ainda sem trades lidos.");
  }
  function drawPosicoes() {
    if (!P) return;
    $("nbPos").textContent = REAL ? "" : (P.posicoes || []).length || "";
    if (REAL) { kpis("poK", [["Posições REAL", "—", "ainda não existe na BNB"]]); realMsg("poT", 9); return; }
    const ps = P.posicoes || [], tot = ps.reduce((a, p) => a + p.pnl_bnb, 0), inv = ps.reduce((a, p) => a + p.bnb_in, 0);
    kpis("poK", [["Abertas", num(ps.length, 0), "de " + P.cfg.max_abertas], ["Investido", num(inv, 4) + " BNB", ""],
      ["Resultado agora", bnb(tot), inv ? pct(100 * tot / inv) : "", cls(tot)], ["No lucro", num(ps.filter((p) => p.pnl_bnb > 0).length, 0), "posições"]]);
    const now = Date.now() / 1000;
    table("poT", ["Abriu", "Trader", "Token", "Investido", "Agora", "Melhor · pior", "Preço", "Fecha em", ""],
      ps.map((p) => [hora(p.open_t) + '<br><span class="muted">há ' + ago(p.open_t) + "</span>", wal(p.wallet), tok(p.token) + (p.graduou ? ' <span class="tag sim">Pancake</span>' : ""),
        num(p.bnb_in, 4) + " BNB" + (p.proceeds ? '<br><span class="muted">já recebeu ' + num(p.proceeds, 4) + "</span>" : ""),
        bnb(p.pnl_bnb) + "<br>" + pct(p.pnl_pct), pct(p.best_pct) + " · " + pct(p.worst_pct),
        '<span class="muted">' + (p.px_t ? "há " + ago(p.px_t) : "—") + "</span>", p.fecha_em > now ? dur(p.fecha_em - now) : "agora",
        '<button class="btn sm" data-bnclose="' + esc(p.id) + '">Vender</button>']),
      "Nenhuma posição aberta.");
  }
  function drawHistorico() {
    if (!P) return;
    if (REAL) { kpis("hiK", [["Trades REAL", "—", "ainda não existe na BNB"]]); realMsg("hiT", 8); return; }
    const ts = P.trades || [], tot = ts.reduce((a, x) => a + x.pnl_bnb, 0), g = ts.filter((x) => x.pnl_bnb > 0);
    kpis("hiK", [["Fechados", num(ts.length, 0), ""], ["Resultado", bnb(tot), "", cls(tot)], ["Acerto", ts.length ? num(100 * g.length / ts.length, 0) + "%" : "—", g.length + " com lucro"],
      ["Melhor", ts.length ? bnb(Math.max(...ts.map((x) => x.pnl_bnb))) : "—", ""], ["Pior", ts.length ? bnb(Math.min(...ts.map((x) => x.pnl_bnb))) : "—", ""]]);
    table("hiT", ["Fechou", "Trader", "Token", "Investido", "Recebido", "Resultado", "Tempo", "Motivo"],
      ts.map((x) => [hora(x.close_t), wal(x.wallet), tok(x.token), num(x.bnb_in, 4), num(x.bnb_out, 4), bnb(x.pnl_bnb) + "<br>" + pct(x.pnl_pct),
        dur(x.close_t - x.open_t), esc(x.motivo)]),
      "Nenhum trade fechado ainda.");
  }
  function drawSemanas() {
    if (!P) return;
    if (REAL) { kpis("wkK", [["Carteira REAL", "—", "ainda não existe na BNB"]]); realMsg("wkT", 4); return; }
    const b = P.semana.blocos, it = (n, x) => [n, bnb(x.pnl), x.n ? x.n + " trades · acerto " + num(x.acerto, 0) + "% · investido " + num(x.investido, 3) + " BNB" : "nenhum trade fechado", cls(x.pnl)];
    kpis("wkK", [it("Segunda a sexta", b.semana), it("Sábado e domingo", b.fds)]);
    table("wkT", ["Dia", "Trades", "Acerto", "Resultado"], P.semana.dias.map((d) => [esc(d.dia), num(d.n, 0), d.acerto == null ? "—" : num(d.acerto, 0) + "%", bnb(d.pnl)]));
  }
  function drawAbas() {
    if (!P) return;
    if (REAL) { $("abG").innerHTML = '<p class="muted">Carteira REAL da BNB ainda não existe: só a FICTÍCIA.</p>'; return; }
    $("abG").innerHTML = (P.abas || []).map((a) => '<div class="bnaba"><h3>' + esc(a.nome) + '</h3><div class="muted">copia os traders do ranking (Top traders) · ' + a.abertas + " abertas · " + a.fechadas + " fechadas · resultado " + bnb(a.resultado) +
      '</div><div class="row" style="margin-top:10px"><button class="btn sm tgl sw ' + (a.ligada ? "on" : "off") + '" role="switch" aria-checked="' + a.ligada + '" data-bnaba="' + esc(a.aba) + '">' + (a.ligada ? "Ligado" : "Desligado") +
      '</button><span class="muted">compras na FICTÍCIA</span></div><div class="per">' +
      (a.periodos || []).map((x) => "<div>" + x.h + " h<b>" + bnb(x.pnl, 3) + '</b><span class="muted">' + x.n + " trades</span></div>").join("") + "</div></div>").join("");
  }
  function drawConfig() {
    if (!P || DIRTY.cf) return;
    form("cfF", CF_INFO, P.cfg, P.padrao, "cf_");
  }
  function drawAdmin() {
    if (!R || !R.ligado) return;
    const s = R.status || {};
    const st = $("bnSt");
    const erro = s.ultimo_erro && s.ultimo_erro_t && Date.now() / 1000 - s.ultimo_erro_t < 120;
    const moedas = Object.entries(s.moedas_24h || {}).map((x) => esc(x[0]) + " " + x[1]).join(" · ");
    st.className = "decbox " + (erro ? "bad" : s.ultimo_trade_t ? "ok" : "");
    st.innerHTML = (erro ? "<b>Erro na leitura há " + ago(s.ultimo_erro_t) + ":</b> " + esc(s.ultimo_erro) + "<br>" : "") +
      "RPC grátis: <b>" + esc(s.rpc || "—") + "</b> · " + num(s.chamadas, 0) + " consultas desde " + hora(s.desde) + " · atraso " + (s.atraso_s == null ? "—" : num(s.atraso_s, 1) + " s") +
      " · " + num(s.trades_memoria, 0) + " trades na memória" + (s.carregados ? " (" + num(s.carregados, 0) + " recuperados do banco)" : "") +
      (moedas ? " · moedas da curva em 24 h: " + moedas : "") + (s.a_gravar ? " · " + num(s.a_gravar, 0) + " esperando gravar" : "") +
      (R.carregado ? "" : " · <b>carregando os dias guardados…</b>");
    if (!DIRTY.rk) form("bnCfg", RK_INFO, R.cfg, R.padrao, "bnc_");
    table("bnTr", ["Hora", "Carteira", "Token", "Lado", "BNB", "Moeda", "Tx"],
      (R.recentes || []).map((t) => [hora(t.t), wal(t.wallet), tok(t.token), t.side === "buy" ? '<span class="up">compra</span>' : '<span class="down">venda</span>',
        t.bnb == null ? "—" : num(t.bnb, 4), esc(t.moeda), txl(t.tx)]), "Ainda sem trades lidos.");
  }
  function drawChangelog() {
    if (!CHG) return;
    const it = CHG.filter((x) => x.projeto === "bnb");
    $("chL").innerHTML = it.length ? it.map((x) => '<div class="bnchg"><span class="tag sim">' + esc(x.versao) + "</span> <span class=\"muted\">" + esc(x.inicio ? hora(Date.parse(x.inicio) / 1000) : x.data) + " · " + esc(x.tipo) +
      "</span><h3>" + esc(x.titulo) + '</h3><p class="muted">' + esc(x.onde) + "</p><p>" + esc(x.oque) + "</p></div>").join("") : '<p class="muted">Nada ainda.</p>';
  }
  const isBnb = (txt) => /bnb|four\.?meme/i.test(String(txt || ""));
  async function loadLogs(reset) {
    if (VIEW !== "logs") return;
    document.querySelectorAll("#lgTab button").forEach((b) => b.classList.toggle("on", b.dataset.lgt === LG.tab));
    document.querySelectorAll("#lgF button").forEach((b) => b.classList.toggle("on", b.dataset.lgf === LG.f));
    document.querySelectorAll("#lgLv button").forEach((b) => b.classList.toggle("on", b.dataset.lglv === LG.lv));
    $("lgSeg").hidden = LG.tab !== "seg"; $("lgSrv").hidden = LG.tab !== "srv";
    if (LG.tab === "seg") {
      const L = await BB.api("/api/admin/audit?limit=500", { quiet: true }); if (!Array.isArray(L)) return;
      const rows = LG.f === "bnb" ? L.filter((a) => isBnb(a.acao) || isBnb(a.detalhe)) : L;
      $("lgSegSub").textContent = rows.length + " registros" + (LG.f === "bnb" ? " da BNB (de " + L.length + " no total)" : "") + " · o detalhe nunca mostra chaves";
      table("lgAud", ["Quando", "Usuário", "Ação", "Detalhe"], rows.map((a) => [a.at ? hora(Date.parse(a.at) / 1000) : "—", esc(a.email || (a.user_id || "").slice(0, 8)),
        esc(a.acao), '<span style="white-space:normal;display:block;max-width:520px">' + esc(a.detalhe || "") + "</span>"]),
        LG.f === "bnb" ? "Nada da BNB registrado ainda. Mudar a regra, a configuração ou vender uma posição da BNB aparece aqui." : "Nada registrado ainda.");
      return;
    }
    const q = ($("lgQ").value || "").trim(), key = LG.f + "|" + LG.lv + "|" + q;
    if (reset || key !== LG.key) { LG.after = 0; LG.key = key; $("lgLog").innerHTML = ""; }
    const r = await BB.api("/api/admin/logs?after=" + LG.after + "&level=" + LG.lv + "&q=" + encodeURIComponent(q || (LG.f === "bnb" ? "bnb" : "")), { quiet: true });
    if (!r || r.error) return;
    const el = $("lgLog"), atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    (r.logs || []).forEach((x) => {
      LG.after = Math.max(LG.after, x.id);
      if (LG.f === "bnb" && !isBnb(x.name + " " + x.msg)) return;
      const d = document.createElement("div"); d.className = x.level;
      d.innerHTML = '<span class="t">' + new Date(x.t * 1000).toLocaleString("pt-BR") + '</span><span class="n">' + esc(x.level) + " · " + esc(x.name) + "</span>" + esc(x.msg);
      el.appendChild(d);
    });
    while (el.childNodes.length > 1500) el.removeChild(el.firstChild);
    if (atEnd) el.scrollTop = el.scrollHeight;
    if (!el.childNodes.length) el.innerHTML = '<div class="muted">' + (LG.f === "bnb" ? "Nenhuma linha da BNB no log ainda (a leitura só escreve quando algo dá errado)." : "Nada no log.") + "</div>";
    $("lgSrvSub").textContent = (r.total || 0) + " registros guardados · " + (r.warnings || 0) + " avisos · " + (r.errors || 0) + " erros · chaves mascaradas";
  }

  function draw() {
    $("bnReal").hidden = !(REAL && REAL_VIEWS.includes(VIEW));
    ({ visao: drawVisao, traders: drawTraders, posicoes: drawPosicoes, historico: drawHistorico, semanas: drawSemanas, abas: drawAbas, config: drawConfig, admin: drawAdmin, changelog: drawChangelog }[VIEW] || (() => {}))();
    if (VIEW !== "posicoes") drawPosicoesBadge();
  }
  function drawPosicoesBadge() { if (P) $("nbPos").textContent = REAL ? "" : (P.posicoes || []).length || ""; }

  // ------------------------------------------------------------------ dados
  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try {
      const needR = ["traders", "admin"].includes(VIEW) || !R;
      const [p, r] = await Promise.all([BB.api("/api/pump/bnb/painel", { quiet: true }), needR ? BB.api("/api/pump/bnb", { quiet: true }) : Promise.resolve(null)]);
      if (p && !p.error) P = p.ligado === false ? null : p;
      if (r && !r.error) R = r;
      if (VIEW === "logs") await loadLogs(false);
      if (VIEW === "changelog" && !CHG) { const c = await BB.api("/api/admin/novidades", { quiet: true }); CHG = (c && c.itens) || []; }
      draw();
    } catch (e) { /* tenta de novo na próxima volta */ } finally { BUSY = false; }
  }
  function route() {
    const v = (location.hash || "#visao").slice(1);
    VIEW = TITLES[v] ? v : "visao";
    document.querySelectorAll(".view").forEach((s) => (s.hidden = s.dataset.view !== VIEW));
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === VIEW));
    document.querySelectorAll("#tabbar [data-tv]").forEach((a) => a.classList.toggle("on", a.dataset.tv === VIEW));
    $("tbMenu").classList.toggle("on", !["visao", "traders", "posicoes", "historico"].includes(VIEW));
    $("pgTitle").textContent = TITLES[VIEW][0]; $("pgSub").textContent = TITLES[VIEW][1];
    closeDrawer();
    window.scrollTo(0, 0);
    draw();
    load();
  }
  function setMode(real) {
    REAL = real;
    try { localStorage.setItem("bnb_mode", real ? "real" : "sim"); } catch (e) { /* */ }
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.mode === "real") === REAL));
    draw();
  }
  const openDrawer = () => { $("side").classList.add("open"); $("scrim").classList.add("open"); };
  const closeDrawer = () => { $("side").classList.remove("open"); $("scrim").classList.remove("open"); };

  // ------------------------------------------------------------------ ações
  let LGQ_T = 0;
  document.addEventListener("input", (e) => {
    const id = (e.target && e.target.id) || "";
    if (id === "lgQ") { clearTimeout(LGQ_T); LGQ_T = setTimeout(() => loadLogs(true), 400); }
    if (id.startsWith("bnc_")) DIRTY.rk = true;
    if (id.startsWith("cf_")) DIRTY.cf = true;
  });
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target : null; if (!t) return;
    const mb = t.closest("#modeSeg button"); if (mb) { setMode(mb.dataset.mode === "real"); return; }
    const rk = t.closest("#bnSave, #bnReset");
    if (rk) {
      const body = {};
      if (rk.id === "bnReset") Object.assign(body, (R && R.padrao) || {});
      else RK_INFO.forEach((c) => { const el = $("bnc_" + c[0]); if (el && el.value !== "") body[c[0]] = Number(el.value); });
      const r = await BB.api("/api/pump/bnb/cfg", { body: body });
      DIRTY.rk = false;
      if (r && r.ok && R) { R.cfg = r.cfg; drawAdmin(); load(); }
      return;
    }
    const cf = t.closest("#cfSave, #cfReset");
    if (cf) {
      const body = {};
      if (cf.id === "cfReset") Object.assign(body, (P && P.padrao) || {});
      else CF_INFO.forEach((c) => { const el = $("cf_" + c[0]); if (el && el.value !== "") body[c[0]] = Number(el.value); });
      const r = await BB.api("/api/pump/bnb/conta", { body: body });
      DIRTY.cf = false;
      if (r && r.ok && P) { P.cfg = r.cfg; drawConfig(); load(); }
      return;
    }
    const ab = t.closest("[data-bnaba]");
    if (ab && P) {
      const r = await BB.api("/api/pump/bnb/conta", { body: { on: !P.cfg.on } });
      if (r && r.ok) { P.cfg = r.cfg; P.abas.forEach((a) => (a.ligada = r.cfg.on)); drawAbas(); load(); }
      return;
    }
    const lg = t.closest("[data-lgt], [data-lgf], [data-lglv]");
    if (lg) {
      if (lg.dataset.lgt) LG.tab = lg.dataset.lgt;
      if (lg.dataset.lgf) LG.f = lg.dataset.lgf;
      if (lg.dataset.lglv) LG.lv = lg.dataset.lglv;
      loadLogs(true);
      return;
    }
    const cl = t.closest("[data-bnclose]");
    if (cl) {
      if (!confirm("Vender esta posição FICTÍCIA agora pelo último preço?")) return;
      cl.disabled = true;
      await BB.api("/api/pump/bnb/fechar", { body: { id: cl.dataset.bnclose } });
      load();
    }
  });

  async function boot() {
    $("boot").innerHTML = BB.loader("Carregando", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
    $("bnOut").addEventListener("click", BB.logout);
    $("burger").addEventListener("click", openDrawer);
    $("tbMenu").addEventListener("click", openDrawer);
    $("scrim").addEventListener("click", closeDrawer);
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão: volta ao início */ }
    if (!s) { location.href = "/"; return; }
    const me = await BB.api("/api/me", { quiet: true });
    if (me.error || me.role !== "admin") { location.replace("/app"); return; }      // a BNB é só do admin
    try { sessionStorage.setItem("pf_hub", "bnb"); } catch (e) { /* */ }
    $("ver").textContent = "versão " + String(me.version || "").split(" · ")[0];
    let m = "sim"; try { m = localStorage.getItem("bnb_mode") || "sim"; } catch (e) { /* */ }
    $("boot").hidden = true; $("shell").hidden = false;
    READY = true;
    setMode(m === "real");
    route();
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", load);
  boot();
  setInterval(load, 10000);
})();
