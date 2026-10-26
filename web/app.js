/* Painel do usuário — PUMP FUN COPY.
   Tudo o que a aba PUMP.FUN original mostrava, reorganizado: visão geral, top traders, posições, histórico,
   feed, execução real, configurações (com chaves pessoais) e como funciona. Sem handlers inline (CSP). */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = BB.esc;
  let D = null, W = null, ME = null, EV = -1, BUSY = false, RANGE = 1, MONF = "all", MODE = null, ADMIN = null;
  try { MODE = localStorage.getItem("pf:mode"); RANGE = +localStorage.getItem("pf:range") || 1; } catch (e) { /* */ }

  // ------------------------------------------------------------------ formatação
  const f = (n, d = 2) => (n == null || isNaN(n) ? "–" : Number(n).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }));
  const s4 = (n) => (n == null || isNaN(n) ? "–" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: 4 }));
  const cls = (n) => (n > 0 ? "up" : n < 0 ? "down" : "");
  const sg = (n, u = " SOL") => (n == null ? "–" : '<span class="' + cls(n) + '">' + (n > 0 ? "+" : "") + s4(n) + u + "</span>");
  const pc = (n, d = 1) => (n == null ? "–" : '<span class="' + cls(n) + '">' + (n > 0 ? "+" : "") + f(n, d) + "%</span>");
  const usd = (v, d = 0) => (v == null ? "–" : "$" + f(v, d));
  const usdS = (v) => (v == null ? "–" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : v < 0 ? "−" : "") + "$" + f(Math.abs(v), 0) + "</span>");
  const uk = (v) => (v == null ? "–" : v >= 1e6 ? "$" + f(v / 1e6, 2) + " M" : v >= 1e3 ? "$" + f(v / 1e3, 1) + " mil" : "$" + f(v, 0));
  const ex = (n) => (n ? Number(n).toExponential(3) : "–");
  const hms = (s) => { if (s == null) return "–"; s = Math.max(0, Math.round(s)); if (s < 60) return s + " s"; if (s < 3600) return Math.floor(s / 60) + " min " + String(s % 60).padStart(2, "0") + " s"; if (s < 86400) return Math.floor(s / 3600) + " h " + String(Math.floor((s % 3600) / 60)).padStart(2, "0") + " min"; return Math.floor(s / 86400) + " d " + Math.floor((s % 86400) / 3600) + " h"; };
  const agoT = (t) => hms(Date.now() / 1000 - t);
  const agoIso = (x) => (x ? hms((Date.now() - new Date(x)) / 1000) : "–");
  const dt = (x) => { if (!x) return "–"; const d = new Date(x); return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
  const shortW = (w) => (w ? w.slice(0, 4) + "…" + w.slice(-4) : "");
  const pfW = (w) => '<a href="https://pump.fun/profile/' + encodeURIComponent(w) + '" target="_blank" rel="noopener" title="' + esc(w) + '">' + esc(shortW(w)) + "</a>";
  const pfM = (m, s) => '<a href="https://pump.fun/coin/' + encodeURIComponent(m) + '" target="_blank" rel="noopener" title="' + esc(m) + '">' + esc(s || m.slice(0, 6)) + "</a>" +
    '<button class="tkinfo" data-tk="' + esc(m) + '" title="Ficha do token">i</button>';
  const tx = (sig) => (sig ? '<a href="https://solscan.io/tx/' + encodeURIComponent(sig) + '" target="_blank" rel="noopener">tx</a>' : "");
  const btn = (label, act, data, extra) => '<button class="btn sm ' + (extra || "") + '" data-act="' + act + '"' + Object.entries(data || {}).map(([k, v]) => " data-" + k + '="' + esc(v) + '"').join("") + ">" + label + "</button>";
  const st = (on, real) => '<span class="st ' + (on ? (real ? "real" : "on") : "off") + '">' + (on ? "ON" : "OFF") + "</span>";

  function table(id, head, rows, empty) {
    const el = $(id); if (!el) return;
    if (!rows.length) { el.innerHTML = '<tr><td class="empty" colspan="' + head.length + '">' + (empty || "Nada por aqui ainda.") + "</td></tr>"; return; }
    el.innerHTML = "<thead><tr>" + head.map((h) => "<th>" + h + "</th>").join("") + "</tr></thead><tbody>" + rows.map((r) => "<tr>" + r.map((c) => "<td>" + (c == null ? "" : c) + "</td>").join("") + "</tr>").join("") + "</tbody>";
  }
  const IC = {
    wallet: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="18" height="14" rx="2"/><path d="M16 13h2M3 10h18"/></svg>',
    pnl: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>',
    pos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>',
    tr: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 4v6h6"/><path d="M4.5 15A8 8 0 1 0 6 6.5L4 10"/></svg>',
    hit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/></svg>',
    usr: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/></svg>',
    mon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
  };
  function kpis(id, items) {
    const el = $(id); if (!el) return;
    el.innerHTML = items.map((x) => '<div class="kpi"><div class="k"><span>' + x[0] + "</span>" + (x[3] ? IC[x[3]] : "") + '</div><div class="v ' + (x[4] || "") + '">' + x[1] + '</div><div class="d">' + (x[2] || "&nbsp;") + "</div></div>").join("");
  }
  // Novidades ficam marcadas em verde ("NOVO") até a data de data-novo-ate (AAAA-MM-DD); depois somem sozinhas.
  function marcarNovos() {
    const hoje = new Date().toISOString().slice(0, 10);
    document.querySelectorAll("[data-novo-ate]").forEach((el) => el.classList.toggle("novo", el.dataset.novoAte >= hoje));
  }
  marcarNovos();
  // ------------------------------------------------------------------ relatórios (/api/pump/reports)
  let REP_DAYS = 7, REP_AT = 0, REP_MODE = null;
  async function loadReports() {
    const rm = realMode(), r = await BB.api("/api/pump/reports?days=" + REP_DAYS + "&real=" + (rm ? 1 : 0));
    if (r.error) { toast(r.error); return; }
    REP_AT = Date.now(); REP_MODE = rm;
    const t = r.total || {}, fp = r.fee_parts || {}, pctW = (x) => (x == null ? "–" : f(x * 100, 0) + "%");
    kpis("repKpis", [["Resultado", sg(t.pnl_sol), t.trades + " trades fechados", "pnl"], ["Taxa de acerto", pctW(t.win_rate), (t.wins || 0) + " ganhos", "hit"],
      ["Média por trade", sg(t.avg_pnl_sol), "investido " + s4(t.invested_sol) + " SOL", "tr"],
      ["Atraso médio das cópias", t.avg_lag_s == null ? "–" : f(t.avg_lag_s, 1) + "<small> s</small>", "do trade do trader até a sua cópia", "mon"],
      ["Taxas pagas", s4(t.fees_sol) + "<small> SOL</small>", "pump.fun " + s4(fp.platform) + " · PumpPortal " + s4(fp.portal) + " · rede " + s4(fp.network), "wallet"]]);
    const ST2 = { copiando: '<span class="tag win">copiando</span>', pausado: '<span class="tag pause">pausado</span>', fora: '<span class="tag neutral">fora</span>' };
    table("repTr", ["Trader", "Situação", "Trades", "Acerto", "Resultado p/ você", "Média", "Taxas", "Segurou (média)", "Último"], (r.traders || []).map((x) => [pfW(x.wallet), ST2[x.status] || "", String(x.trades), pctW(x.win_rate), "<b>" + sg(x.pnl_sol) + "</b>", sg(x.avg_pnl_sol), s4(x.fees_sol), hms(x.avg_hold_s), dt(x.last)]), "Nenhum trade fechado no período.");
    table("repEx", ["Motivo", "Trades", "Acerto", "Resultado", "Média"], (r.exits || []).map((x) => [esc(x.reason), String(x.trades), pctW(x.win_rate), sg(x.pnl_sol), sg(x.avg_pnl_sol)]), "Nenhum trade fechado no período.");
    $("repSkSub").textContent = "quantas cópias cada filtro barrou · " + r.skips_seen + " nos últimos " + r.feed_kept + " eventos guardados";
    table("repSk", ["Motivo", "Vezes"], (r.skips || []).map((x) => [esc(x.reason), String(x.count)]), "Nenhuma cópia barrada no período.");
    table("repDay", ["Dia", "Trades", "Acerto", "Resultado", "Taxas"], (r.days_list || []).map((x) => [esc(x.day.split("-").reverse().join("/")), String(x.trades), pctW(x.win_rate), sg(x.pnl_sol), s4(x.fees_sol)]), "Nenhum trade fechado no período.");
    const wi = r.whatif || {}, cu = r.custo || {};
    $("repWiSub").textContent = wi.trades ? "estimativa com " + wi.trades + " trades · resultado real no período: " + s4(wi.real_sol) + " SOL · quando o trade passou pelo alvo e pelo stop, conta o stop" : "ainda sem trades com o dado (a partir da 0.18.0)";
    table("repWi", ["Regra", "Resultado estimado", "Diferença p/ o real"], wi.trades ? (wi.rows || []).map((x) => [esc(x.regra), sg(x.pnl_sol), sg(x.diff_sol)]) : [], "");
    kpis("repCusto", [["Entrada mais cara que o trader", cu.entry_worse_pct == null ? "–" : "+" + f(cu.entry_worse_pct, 1) + "%", "média de " + (cu.with_px || 0) + " trades (atraso + slippage)", "mon"],
      ["Taxas", cu.fees_pct == null ? "–" : f(cu.fees_pct, 1) + "%", "do valor investido · " + s4(cu.fees_sol) + " SOL", "wallet"],
      ["Antes × depois das taxas", sg(cu.gross_sol), "líquido: " + s4(cu.net_sol) + " SOL", "pnl"]]);
    table("repScore", ["Nota", "Trades", "Acerto", "Resultado", "Média por trade"], (r.by_score || []).map((x) => [esc(x.faixa), String(x.trades), pctW(x.win_rate), sg(x.pnl_sol), sg(x.avg_pnl_sol)]), "");
    const m = r.mesa || {}, pc = (v) => (v == null ? "–" : '<span class="' + (v > 0 ? "up" : v < 0 ? "down" : "") + '">' + (v > 0 ? "+" : "") + f(v, 1) + "%</span>");
    if (!m.trades) { $("repMesa").innerHTML = '<p class="muted">Ainda sem trades fechados com esse dado (começa a contar a partir da 0.18.0).</p>'; $("repMesaEx").innerHTML = ""; return; }
    kpis("repMesa", [["Melhor momento (média)", pc(m.avg_best_pct), "o máximo que as posições chegaram a ganhar", "pnl"], ["Fechou em (média)", pc(m.avg_final_pct), "pior momento médio " + f(m.avg_worst_pct, 1) + "%", "tr"],
      ["Ficou na mesa", pc(m.avg_left_pct), "diferença média entre o melhor momento e a saída", "mon"],
      ["Devolveu o lucro", String(m.gave_back), "chegaram a +30% ou mais e fecharam no zero ou pior", "hit"],
      ["Stop depois de ganhar", m.stops_were_up + " de " + m.stops, "stops de perda que antes estavam +10% ou mais", "pos"]]);
    table("repMesaEx", ["Motivo de saída", "Trades", "Melhor momento (média)", "Fechou em (média)"], (m.exits || []).map((x) => [esc(x.reason), String(x.trades), pc(x.avg_best_pct), pc(x.avg_final_pct)]), "");
  }

  // ------------------------------------------------------------------ estratégias fantasma (/api/pump/ghosts, 0.18.0)
  // ------------------------------------------------------------------ base da pump.fun (/api/pump/base, 0.21.0)
  let BS_T = null;
  async function loadBase() {
    clearTimeout(BS_T); BS_T = setTimeout(() => { if (VIEW === "base") loadBase(); }, 20000);
    const r = await BB.api("/api/pump/base");
    if (r.error) { toast(r.error); return; }
    const d = r.day || {}, L = d.labels || {}, pc = (a, b) => (b ? f(a / b * 100, 0) + "%" : "–");
    $("bsSub").textContent = "observando desde " + dt(r.since) + " · " + r.live + " tokens em observação agora · até " + r.max_per_min + " novos por minuto" + (r.dropped ? " (" + r.dropped + " ficaram de fora por limite)" : "");
    kpis("bsKpis", [["Tokens fechados (24 h)", String(d.finished || 0), "com as 4 fotos ou graduados", "tr"], ["Subiram", pc(d.up || 0, d.finished), (L.graduou || 0) + " graduaram · " + (L["5x"] || 0) + " deram 5x · " + (L["2x"] || 0) + " deram 2x", "hit"],
      ["Despencaram", pc(L.despencou || 0, d.finished), "subiram e caíram mais da metade", "pos"], ["Morreram", pc(L.morreu || 0, d.finished), "ficaram parados no market cap inicial", "mon"]]);
    const hr = (k) => new Date(k).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    table("bsHours", ["Hora", "Criados", "Observados", "Fechados", "Subiram", "Graduaram", "Despencaram", "Morreram"], (r.hours || []).slice().reverse().map((h) => [hr(h.hora), String(h.created), String(h.tracked), String(h.finished),
      h.up_pct == null ? "–" : f(h.up_pct, 1) + "%", String(h.grad), h.rug_pct == null ? "–" : f(h.rug_pct, 1) + "%", h.dead_pct == null ? "–" : f(h.dead_pct, 1) + "%"]), "Ainda sem dados: a primeira hora fecha em até 60 min.");
    const ls = r.lessons || {};
    $("bsLsSub").textContent = (r.kept || 0) + " tokens guardados (até " + r.keep_days + " dias) · " + (ls.tokens || 0) + " com resultado · em média " + (ls.base_up_pct == null ? "–" : f(ls.base_up_pct, 1) + "%") + " sobem (graduou, 5x ou 2x)";
    $("bsLsBest").innerHTML = (ls.best || []).length ? "<p><b>Sinais fortes até agora</b> (pelo menos " + ls.min_n + " tokens e o dobro da média subindo):</p>" + ls.best.map((b) => "<p>" + esc(b.sinal) + ' → <span class="up">' + f(b.up_pct, 0) + "% subiram</span> · " + f(b.rug_pct, 0) + "% despencaram · " + b.n + " tokens</p>").join("")
      : '<p class="muted">Ainda sem sinal forte: precisa de pelo menos ' + (ls.min_n || 30) + " tokens numa faixa e o dobro da média subindo. Com algumas horas de dados as tabelas abaixo começam a dizer o que funciona.</p>";
    $("bsLs").innerHTML = (ls.tables || []).map((tb, i) => '<div><h3 style="margin:6px 0">' + esc(tb.nome) + '</h3><div class="tbl-wrap"><table id="bsLs' + i + '"></table></div></div>').join("");
    (ls.tables || []).forEach((tb, i) => table("bsLs" + i, ["Faixa", "Tokens", "Subiram", "Despencaram"], tb.linhas.map((x) => [esc(String(x.faixa) + (tb.nome.startsWith("Hora") ? "h" : "")), String(x.n), '<span class="' + (ls.base_up_pct != null && x.up_pct >= ls.base_up_pct * 2 && x.n >= 30 ? "up" : "") + '">' + f(x.up_pct, 1) + "%</span>", f(x.rug_pct, 1) + "%"]), "Sem dados ainda."));
    table("bsWords", ["Palavra", "Subiram", "Criados"], (r.words || []).map((w) => [esc(w.word), String(w.up), String(w.all)]), "Nenhuma palavra repetida entre os que subiram.");
    const bst = (b) => !b || b.t == null && !b.active ? '<span class="muted">…</span>' : b.active ? '<span class="tag win" title="o time do token está pagando boost na DexScreener">Boost ON' + (b.amount_24h ? " · " + b.amount_24h + "x" : "") + "</span>" + (b.paid && b.paid.length ? '<small>pagou: ' + esc(b.paid.join(", ")) + "</small>" : "")
      : '<span class="tag neutral">Boost OFF</span>' + (b.paid && b.paid.length ? '<small>pagou: ' + esc(b.paid.join(", ")) + "</small>" : "");
    const buy = (m, s) => '<button class="btn sm primary" data-buy="' + esc(m) + '" data-sym="' + esc(s || "") + '">Comprar</button>';
    table("bsMine", ["Token", "Situação", "Investiu", "Resultado", "Boost pago", "Quando", ""], (r.mine || []).map((x) => [pfM(x.mint, x.symbol) + (x.real ? ' <span class="tag real">REAL</span>' : ""),
      x.open ? '<span class="tag sim">aberta</span>' : '<span class="tag neutral">fechada</span><small>' + esc(x.reason || "") + "</small>", s4(x.sol_in) + " SOL",
      x.open ? (x.chg_pct == null ? "–" : '<span class="' + (x.chg_pct >= 0 ? "up" : "down") + '">' + (x.chg_pct > 0 ? "+" : "") + f(x.chg_pct, 1) + "%</span>") : sg(x.pnl_sol) + "<small>" + f(x.pnl_pct || 0, 1) + "%</small>",
      bst(x.boost), dt(x.open ? x.opened_at : x.closed_at), x.open ? '<a class="btn sm" href="#posicoes">Ver posição</a>' : ""]), "Você ainda não comprou nada por esta tela.");
    table("bsRise", ["Token", "Ganho", "Market cap início → última foto", "Idade", "Criador", "Boost pago", ""], (r.rising || []).map((x) => [pfM(x.mint, x.symbol), '<span class="up">+' + f(x.gain_pct, 0) + "%</span>",
      f(x.mcap0, 0) + " → " + f(x.mcap, 0) + " SOL", f(x.age_min, 0) + " min · " + x.fotos + "/4 fotos",
      x.creator_stats ? x.creator_stats.tokens + " tokens · " + x.creator_stats.x2 + " subiram · " + x.creator_stats.rugs + " despencaram" : "novo", bst(x.boost), buy(x.mint, x.symbol)]), "Nenhum token em observação subiu ainda.");
    table("bsUp", ["Token", "Rótulo", "Market cap inicial → pico", "Criado", "Boost pago", ""], (r.recent_up || []).map((x) => [pfM(x.mint, x.symbol), '<span class="tag win">' + esc(x.label) + "</span>", f(x.mcap0 || 0, 0) + " → " + (x.label === "graduou" ? "graduou (~410)" : f(x.peak || 0, 0)) + " SOL", dt(x.created_at), bst(x.boost), buy(x.mint, x.symbol)]), "Nenhum ainda.");
    const crt = (L2) => (L2 || []).map((c) => [pfW(c.creator), String(c.tokens), String(c.x2), String(c.rugs)]);
    table("bsBad", ["Criador", "Tokens", "Subiram", "Despencaram"], crt(r.bad_creators), "Nenhum criador com 2+ tokens ainda.");
    table("bsGood", ["Criador", "Tokens", "Subiram", "Despencaram"], crt(r.good_creators), "Nenhum ainda.");
  }

  // ------------------------------------------------------------------ lista negra (/api/pump/blacklist, 0.20.0)
  async function loadBlacklist() {
    const r = await BB.api("/api/pump/blacklist");
    if (r.error) { toast(r.error); return; }
    $("blSub").textContent = r.count + " endereços · a opção \"Não copiar quem está na lista negra\" está " + (r.on ? "LIGADA" : "DESLIGADA") + " para você";
    table("blTbl", ["Endereço", "Tipo", "Motivo", "Desde", ""], (r.items || []).map((x) => [pfW(x.endereco), x.tipo === "dev" ? "criador" : "carteira", esc(x.motivo || ""), dt(x.criado_em),
      '<button class="btn sm" data-blr="' + esc(x.endereco) + '">Tirar</button>']), "Lista vazia.");
  }
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.id === "blAdd") {
      const raw = $("blAddr").value.trim(), a = (raw.match(/[1-9A-HJ-NP-Za-km-z]{32,44}/) || [""])[0];
      const r = await BB.api("/api/pump/blacklist", { body: { endereco: a, tipo: $("blTipo").value, motivo: $("blMot").value.trim(), action: "add" } });
      toast(r.error ? "Não adicionou: " + r.error : "Adicionado à lista negra."); if (!r.error) { $("blAddr").value = ""; $("blMot").value = ""; }
      return loadBlacklist();
    }
    if (t.dataset.blr) { if (!confirm("Tirar da lista negra?")) return; const r = await BB.api("/api/pump/blacklist", { body: { endereco: t.dataset.blr, action: "remove" } }); toast(r.error || "Removido."); return loadBlacklist(); }
    if (t.dataset.buy) {
      const amt = cfg().pump_copy_sol, real = !!(D && D.real && D.real.enabled);
      if (!confirm("Comprar " + (t.dataset.sym || "este token") + " agora?\n\nCarteira fictícia: " + amt + " SOL" + (real ? "\nCarteira REAL: até " + cfg().pump_real_max_sol + " SOL (execução real ligada)" : "\nCarteira real: não (execução real desligada)"))) return;
      t.disabled = true;
      const r = await BB.api("/api/pump/manual-buy", { body: { mint: t.dataset.buy } });
      t.disabled = false;
      toast(r.error ? "Não comprou: " + r.error : "Fictícia: " + r.sim + (r.real ? " · Real: " + r.real : ""));
      poll(true); return;
    }
    if (t.id === "tgTest") { const r = await BB.api("/api/pump/telegram/test", { body: {} }); toast(r.error ? "Não enviou: " + r.error : "Enviado. Confira o Telegram."); }
  });

  let GH = null;
  async function loadGhosts() {
    const r = await BB.api("/api/pump/ghosts");
    if (r.error) { toast(r.error); return; }
    GH = r;
    const pctW = (x) => (x == null ? "–" : f(x * 100, 0) + "%"), roi = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + f(v, 1) + "%");
    const best = (r.variants || []).find((v) => v.id === r.best), y = r.yours || {};
    $("ghSub").textContent = r.since ? "comparando desde " + dt(r.since) + " · cada cópia fictícia também é \"copiada\" por " + (r.variants || []).length + " regras de saída" : "começa a contar na próxima cópia fictícia";
    kpis("ghKpis", [["Suas regras atuais", sg(y.pnl_sol), y.trades + " trades · retorno " + roi(y.roi_pct), "pnl"],
      ["Melhor variante", best ? sg(best.pnl_sol) : "–", best ? esc(best.nome) : "ainda sem trades fechados", "hit"],
      ["Diferença", best && y.trades ? sg(best.pnl_sol - y.pnl_sol) : "–", "melhor variante − suas regras", "tr"]]);
    const rows = [y].concat(r.variants || []);
    table("ghTbl", ["Regra de saída", "Trades", "Abertas", "Acerto", "Resultado", "Retorno", "Melhor momento (média)"], rows.map((v) => [
      (v.id === "suas" ? "<b>" + esc(v.nome) + "</b>" : esc(v.nome)) + (v.id === r.best ? ' <span class="tag win">melhor</span>' : ""), String(v.trades), String(v.open), pctW(v.win_rate),
      "<b>" + sg(v.pnl_sol) + "</b>", roi(v.roi_pct), v.avg_best_pct == null ? "–" : "+" + f(v.avg_best_pct, 1) + "%"]), "");
    const sel = $("ghSel"), cur = sel.value;
    sel.innerHTML = (r.variants || []).map((v) => '<option value="' + esc(v.id) + '">' + esc(v.nome) + "</option>").join("");
    if (cur) sel.value = cur;
    ghRecent();
  }
  function ghRecent() {
    const rec = ((GH && GH.recent) || {})[$("ghSel").value] || [];
    table("ghRec", ["Quando", "Token", "Saída", "Resultado", "Melhor momento"], rec.map((x) => [dt(x.at), pfM(x.mint, x.symbol), esc(x.why), sg(x.pnl_sol) + (x.pnl_pct == null ? "" : "<small> " + f(x.pnl_pct, 1) + "%</small>"), "+" + f(x.best, 1) + "%"]), "Nenhum fechamento ainda nesta variante.");
  }
  document.addEventListener("change", (e) => { if (e.target.id === "ghSel") ghRecent(); });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#repDays button"); if (!b) return;
    REP_DAYS = +b.dataset.d; document.querySelectorAll("#repDays button").forEach((x) => x.classList.toggle("on", x === b)); loadReports();
  });

  // ------------------------------------------------------------------ aprendizado diário (/api/pump/aprendizado)
  let AP_AT = 0, AP_MODE = null, AP_SUG = [];
  async function loadLearning() {
    const rm = realMode(), r = await BB.api("/api/pump/aprendizado?real=" + (rm ? 1 : 0));
    if (r.error) { toast(r.error); return; }
    AP_AT = Date.now(); AP_MODE = rm; AP_SUG = r.suggestions || [];
    $("apSub").textContent = "atualizado " + dt(r.generated_at) + " · o que os top traders fizeram e o que as suas cópias fizeram";
    $("apSum").innerHTML = (r.summary || []).map((s) => "<p>" + esc(s) + "</p>").join("");
    $("apSug").innerHTML = AP_SUG.length ? AP_SUG.map((s, i) => '<div class="sug"><div><span class="tag neutral">base: ' + s.base + " casos</span> " + esc(s.text) + "</div>" +
      (s.action ? '<button class="btn sm" data-ap="' + i + '">Aplicar</button>' : "") + "</div>").join("")
      : '<p class="muted">Nenhuma sugestão por enquanto: ainda não há casos suficientes ou nada fora do normal. As sugestões aparecem quando os números têm base mínima.</p>';
    const tt = r.traders_today || {}, w = tt.winners || {}, l = tt.losers || {}, mm = (s) => (s == null ? "–" : f(s / 60, 1) + " min");
    kpis("apKpis", [["Tokens fechados", String(tt.tokens_closed || 0), (tt.watched || 0) + " carteiras acompanhadas", "tr"],
      ["Com lucro", String(w.n || 0), "seguraram " + mm(w.hold_med_s) + " (mediana)", "hit"],
      ["Market cap na entrada (acertos)", w.mcap_in_med == null ? "–" : f(w.mcap_in_med, 0) + "<small> SOL</small>", "erros: " + (l.mcap_in_med == null ? "–" : f(l.mcap_in_med, 0) + " SOL"), "pnl"]]);
    $("apTtSub").textContent = "carteiras que você copia + top do ranking, vistas pelo monitor · " + (tt.traders || []).length + " negociaram";
    table("apTr", ["Trader", "Tokens", "Acerto", "Resultado dele", "Segurou (mediana)", "Market cap na entrada", "Saldo"], (tt.traders || []).map((x) => [pfW(x.wallet) + (x.followed ? ' <span class="tag win">copiando</span>' : ""), String(x.closed),
      f(x.win_rate * 100, 0) + "%", sg(x.pnl_sol), mm(x.hold_med_s), x.mcap_in_med == null ? "–" : f(x.mcap_in_med, 0) + " SOL", x.wallet_usd == null ? "–" : "$" + f(x.wallet_usd, 0)]), "Sem tokens fechados pelos traders nas últimas 24 h.");
    const off = -new Date().getTimezoneOffset() / 60, hrs = (tt.trades_by_hour_utc || []).map((n, h) => ({ h: (h + off + 24) % 24, n }));
    const top = hrs.filter((x) => x.n).sort((a, b) => b.n - a.n).slice(0, 8);
    table("apHr", ["Hora", "Negociações"], top.map((x) => [String(x.h).padStart(2, "0") + "h", String(x.n)]), "Sem negociações registradas.");
    table("apRich", ["Carteira", "Saldo"], (tt.richest || []).map((x) => [pfW(x.wallet), "$" + f(x.usd, 0)]), "Saldo das carteiras ainda não consultado.");
    $("apLim").innerHTML = (r.limits || []).map((s) => "<p>" + esc(s) + "</p>").join("");
    const hi = r.history || {};
    $("apHiSub").textContent = r.history_error ? r.history_error : hi.days ? hi.days + " dias guardados desde " + esc(String(hi.first).split("-").reverse().join("/")) + " · consistência vale mais que um dia bom" : "o primeiro dia é guardado em até 30 min";
    table("apHiTr", ["Trader", "Dias com lucro", "Resultado somado", "Tokens"], (hi.traders || []).map((x) => [pfW(x.wallet) + (x.followed ? ' <span class="tag win">copiando</span>' : ""), x.days_positive + " de " + x.days_seen, sg(x.pnl_sol), String(x.tokens)]), "Ainda sem dias guardados.");
    table("apHiDay", ["Dia", "Suas cópias", "Acerto", "Resultado"], (hi.mine_by_day || []).map((x) => [esc(String(x.dia).split("-").reverse().join("/")), String(x.trades || 0), x.win_rate == null ? "–" : f(x.win_rate * 100, 0) + "%", sg(x.pnl_sol)]), "Ainda sem dias guardados.");
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-ap]"); if (!b) return;
    const s = AP_SUG[+b.dataset.ap]; if (!s || !s.action) return;
    if (!confirm("Aplicar esta sugestão?\n\n" + s.text)) return;
    const a = s.action;
    const r = a.type === "pause" ? await BB.api("/api/pump/wallets", { body: { wallet: a.wallet, action: "pause", hours: a.hours } })
      : a.type === "add" ? await BB.api("/api/pump/wallets", { body: { wallet: a.wallet, action: "add" } })
      : await BB.api("/api/pump/settings", { body: a.values });
    toast(r.error ? "Não aplicou: " + r.error : "Aplicado.");
    poll(true); loadLearning();
  });

  // ------------------------------------------------------------------ ficha do token (/api/pump/token/{mint})
  async function openToken(m) {
    $("tkCard").hidden = false; $("tkT").textContent = "Carregando…"; $("tkM").textContent = m; $("tkB").innerHTML = "";
    const r = await BB.api("/api/pump/token/" + encodeURIComponent(m));
    if (r.error) { $("tkB").innerHTML = '<p class="muted">' + esc(r.error) + "</p>"; return; }
    $("tkT").innerHTML = esc(r.symbol || "Token") + (r.name ? ' <span class="muted">' + esc(r.name) + "</span>" : "") +
      ' <a class="muted" href="https://pump.fun/coin/' + encodeURIComponent(m) + '" target="_blank" rel="noopener">abrir na pump.fun ↗</a>';
    if (!r.seen) { $("tkB").innerHTML = '<p class="muted">O sistema ainda não acompanhou este token.</p>'; return; }
    const v = r.vol || {}, ch = r.chg || {}, fl = r.flow || {}, rk = r.risk;
    const bar = (a, b, la, lb) => { const t = (a || 0) + (b || 0), p = t ? (a / t) * 100 : 50;
      return '<div class="tkbar"><div class="row2"><span class="up">' + la + '</span><span class="down">' + lb + '</span></div><div class="track"><i style="width:' + f(p, 1).replace(",", ".") + '%"></i></div></div>'; };
    const win = (k, lab) => { const b = v["buys_" + k], s = v["sells_" + k], u = fl[k] || {};
      return '<div class="tkwin"><div class="k">' + lab + (ch[k] != null ? ' · <span class="' + (ch[k] >= 0 ? "up" : "down") + '">' + (ch[k] > 0 ? "+" : "") + f(ch[k], 1) + "%</span>" : "") + "</div>" +
        (b != null ? bar(b, s, f(b, 0) + " compras", f(s, 0) + " vendas") : "") +
        (u.buy_vol != null ? bar(u.buy_vol, u.sell_vol, "$" + f(u.buy_vol, 0) + " vol. compra", "$" + f(u.sell_vol, 0) + " vol. venda") : "") +
        (u.buyers != null ? bar(u.buyers, u.sellers, f(u.buyers, 0) + " compradores", f(u.sellers, 0) + " vendedores") : "") + "</div>"; };
    const hold = (r.holders || []).map((h) => '<div class="tkh"><span>' + pfW(h.owner) + (h.creator ? ' <span class="tag loss">criador</span>' : "") + (h.followed ? ' <span class="tag win">seu trader</span>' : "") +
      '</span><div class="track"><i style="width:' + Math.min(100, h.pct * 3).toFixed(1) + '%"></i></div><b class="mono">' + f(h.pct, 1) + "%</b></div>").join("");
    $("tkB").innerHTML =
      '<div class="cfgs">' + [["Market cap", r.mcap_usd ? "$" + f(r.mcap_usd, 0) : r.mcap_sol ? f(r.mcap_sol, 0) + " SOL" : "–"], ["Liquidez", r.liq_usd ? "$" + f(r.liq_usd, 0) : "–"],
        ["Curva", r.graduated ? "graduou (PumpSwap)" : r.curve_pct != null ? f(r.curve_pct, 0) + "%" : "–"], ["Idade", r.age_min != null ? f(r.age_min, 0) + " min" : "–"],
        ["Pressão de compra", r.pressure != null ? f(r.pressure, 0) + "% · " + esc(r.pressure_src) : "–"], ["10 maiores carteiras", r.top10_pct != null ? f(r.top10_pct, 0) + "%" : "–"],
        ["Risco", rk ? (rk.rugged ? "sem liquidez (rug)" : (rk.score != null ? rk.score + "/10" : "–") + (rk.danger && rk.danger.length ? " · " + rk.danger.join(", ") : "")) : "não checado"]]
        .map((x) => '<div><span class="k">' + x[0] + '</span><span class="v">' + esc(x[1]) + "</span></div>").join("") + "</div>" +
      "<h3>Compras × vendas</h3>" + win("m5", "5 min") + win("h1", "1 h") + win("h24", "24 h") +
      (!r.flow ? '<p class="muted small">Compradores/vendedores únicos e volume de compra × venda aparecem quando a Solana Tracker responder para este token.</p>' : "") +
      "<h3>Maiores carteiras</h3>" + (hold || '<p class="muted">Ainda não consultado.</p>') +
      ((r.traders_in || []).length ? "<h3>Seus traders neste token</h3>" + r.traders_in.map((x) => "<div>" + pfW(x.wallet) + " · investiu " + s4(x.invested_sol) + " SOL · " + (x.chg_pct == null ? "–" : f(x.chg_pct, 1) + "%") + "</div>").join("") : "") +
      ((r.my_trades || []).length ? "<h3>Suas operações neste token</h3>" + r.my_trades.map((t) => "<div>" + dt(t.closed_at) + " · " + sg(t.pnl_sol) + " · " + esc(t.reason || "") + "</div>").join("") : "");
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".tkinfo"); if (b) { e.preventDefault(); openToken(b.dataset.tk); return; }
    if (e.target.id === "tkX" || e.target.id === "tkCard") $("tkCard").hidden = true;
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("tkCard").hidden = true; });

  // ------------------------------------------------------------------ radar de KOLs (/api/pump/radar)
  const RADAR = { data: null, at: 0, updatedAt: 0, stale: false, error: "", busy: false, pending: false, revision: 0, dirty: false, saving: false };
  const radarDate = (v) => dt(typeof v === "number" ? v * 1000 : v);
  const radarOutdated = () => RADAR.stale || !RADAR.updatedAt || Date.now() - RADAR.updatedAt > 8000;
  const RADAR_LABELS = { hot: "HOT", selling: "Participantes vendendo", watch: "Em observação", stale: "Esfriou", incomplete: "Dados incompletos" };
  function radarCallout(w, r) {
    const c = w.callout || {}, mon = r.monitor || {}, selling = w.status === "selling" || w.seller_count > 0;
    let state = Object.prototype.hasOwnProperty.call(RADAR_LABELS, c.state) ? c.state : "watch";
    const reasons = Array.isArray(c.reasons) ? c.reasons.filter((s) => typeof s === "string").slice(0, 5) : [];
    if (!c.state || (state === "hot" && (!reasons.length || !r.callout_policy))) {
      state = "watch"; reasons.unshift("Classificação dos destaques ainda não disponível nesta leitura.");
    }
    if (state === "hot" && selling) state = "selling";
    if (radarOutdated() || !mon.running || !mon.connected || r.truncated) {
      state = "incomplete";
      const warnings = [];
      if (radarOutdated()) warnings.push("A tela está sem uma leitura atual; os destaques HOT ficam suspensos até atualizar.");
      if (!mon.running || !mon.connected) warnings.push("Monitor desconectado; movimentos podem estar ausentes.");
      if (r.truncated) warnings.push("A memória do radar atingiu o limite; primeiras entradas ou movimentos podem estar ausentes.");
      if (selling) warnings.push("Há vendas observadas de participantes nesta onda.");
      reasons.unshift(...warnings);
    }
    return { state: state, label: RADAR_LABELS[state], reasons: [...new Set(reasons)].slice(0, 5),
      rank: Number.isInteger(c.rank) && c.rank > 0 ? c.rank : null };
  }
  function invalidateRadar(message) {
    RADAR.stale = true; RADAR.error = message || "falha de conexão";
    if (RADAR.data) renderRadar();
    else { $("radarStatus").textContent = "Não foi possível atualizar o radar: " + RADAR.error; $("radarStatus").className = "radar-status warn"; }
  }
  function radarControls() {
    const r = RADAR.data, disabled = !r || RADAR.saving;
    ["radarToggle", "radarMin", "radarWindow", "radarSave"].forEach((id) => { $(id).disabled = disabled; });
    const b = $("radarToggle"), on = !!(r && r.enabled);
    b.textContent = RADAR.saving ? "Salvando…" : "Radar: " + (on ? "ON" : "OFF");
    b.className = "btn tgl " + (on ? "on" : "off"); b.setAttribute("aria-pressed", String(on));
    if (r && !RADAR.dirty && !RADAR.saving) { $("radarMin").value = r.min_wallets; $("radarWindow").value = r.window_min; }
    $("radarDraft").hidden = !RADAR.dirty;
  }
  function renderRadar() {
    const r = RADAR.data; radarControls(); if (!r) return;
    const waves = r.enabled ? r.waves || [] : [], mon = r.monitor || {}, connected = !!(mon.running && mon.connected);
    const outdated = radarOutdated(), callouts = waves.map((w) => radarCallout(w, r)), policy = r.callout_policy || {};
    const status = $("radarStatus");
    status.className = "radar-status " + (!r.enabled ? "muted" : !connected || outdated || r.truncated ? "warn" : "up");
    status.textContent = !r.enabled ? "Radar desligado. Ligue para receber avisos de compras em conjunto."
      : outdated ? (RADAR.error ? "Não foi possível atualizar o radar: " + RADAR.error + ". " : "Aguardando uma leitura atual do radar. ") + "Destaques HOT suspensos; mostrando a última leitura."
      : !connected ? "Monitor desconectado. Os dados abaixo podem estar incompletos; aguardando reconexão."
      : r.truncated ? "Memória incompleta: limite de dados atingido. Os destaques HOT ficam suspensos."
      : r.wallet_count < r.min_wallets ? "Adicione mais carteiras ao estudo: são necessárias " + r.min_wallets + " e sua lista tem " + r.wallet_count + "."
      : "Radar ligado · Hot callouts ordenam as ondas e mostram o motivo de cada destaque.";
    $("radarSince").textContent = "Observação desde " + radarDate(r.observed_since) + " · atualização da tela a cada 4 s."
      + (RADAR.updatedAt ? " Última leitura da tela: " + dt(RADAR.updatedAt) + "." : "")
      + (r.truncated ? " Limite de eventos atingido: parte da memória pode estar ausente." : "");
    kpis("radarKpis", [["Carteiras da sua lista", f(r.wallet_count, 0), "gerenciadas em Carteiras em estudo", "usr"],
      ["Ondas nesta janela", f(waves.length, 0), "mínimo " + f(r.min_wallets, 0) + " carteiras em " + f(r.window_min, 0) + " min", "mon"],
      ["HOT agora", f(callouts.filter((c) => c.state === "hot").length, 0), outdated || !connected || r.truncated ? "aguardando dados atuais e completos" : "convergência recente sem vendas observadas", "hit"],
      ["Ondas com vendas", f(waves.filter((w) => w.status === "selling").length, 0), "participantes já começaram a vender", "tr"]]);
    $("radarSub").textContent = (outdated ? "última ordem recebida · " : "ondas por prioridade · ") + "janela de " + f(r.window_min, 0) + " min · " + f(r.event_count, 0) + " eventos da sua lista · cada carteira conta uma vez";
    $("radarPolicy").textContent = policy.entry_window_s != null && policy.last_buy_max_age_s != null && policy.stale_after_s != null && policy.min_buy_pressure_pct != null
      ? "HOT exige pelo menos " + f(r.min_wallets, 0) + " carteiras distintas com primeira entrada observada nos últimos " + hms(policy.entry_window_s)
        + ", última compra há no máximo " + hms(policy.last_buy_max_age_s) + ", pressão de compra observada de pelo menos " + f(policy.min_buy_pressure_pct, 0)
        + "% e fluxo em SOL positivo, sem vendas observadas dos participantes. Sem compra por mais de " + hms(policy.stale_after_s)
        + ", a onda esfria. " + (policy.entry_memory_s != null ? "A primeira entrada é conferida na memória de " + hms(policy.entry_memory_s) + " do radar, para uma recompra não parecer uma carteira nova. " : "Repetir a compra da mesma carteira não renova sua entrada. ")
        + "Participantes e volumes usam a janela de compras salva acima. Monitor desconectado, memória incompleta ou tela sem atualizar suspendem HOT."
      : "Os critérios dos destaques ainda não chegaram nesta leitura. Nenhuma onda será marcada HOT sem a classificação atual do radar.";
    if (!waves.length) {
      $("radarWaves").innerHTML = '<div class="radar-empty">' + (!r.enabled ? "Ligue o radar para acompanhar as ondas."
        : r.wallet_count < r.min_wallets ? 'Sua lista ainda não tem carteiras suficientes. <a href="#estudo">Adicionar carteiras ao estudo</a>.'
        : !connected ? "Aguardando o monitor conectar para observar novas operações."
        : "Nenhuma onda com esses critérios por enquanto. As compras precisam ser de carteiras diferentes, no mesmo token e dentro da janela.") + "</div>";
      return;
    }
    $("radarWaves").innerHTML = waves.map((w, i) => {
      const selling = w.status === "selling", mint = String(w.mint || ""), participants = w.wallets || [];
      const callout = callouts[i], tone = { hot: "win", selling: "pause", watch: "buy", stale: "neutral", incomplete: "neutral" }[callout.state];
      const pressure = w.buy_pressure == null ? "–" : f(w.buy_pressure, 0) + "%";
      const stat = (label, value) => "<div><dt>" + label + "</dt><dd>" + value + "</dd></div>";
      return '<article class="radar-wave ' + callout.state + '"><div class="radar-wave-head"><div class="radar-wave-title"><span class="radar-rank" title="Posição na ordem de atenção recebida">#' + f(callout.rank || i + 1, 0) + '</span><h3>' + pfM(mint, String(w.symbol || "")) + '</h3></div><span class="tag ' + tone + '">'
        + esc(callout.label) + '</span></div><div class="radar-callout"><strong>' + (outdated ? "Motivos da última leitura" : "Por que está aqui") + '</strong><ul class="radar-reasons">'
        + callout.reasons.map((reason) => "<li>" + esc(reason) + "</li>").join("") + '</ul></div><dl class="radar-stats">'
        + stat("Carteiras distintas", f(w.wallet_count, 0)) + stat("Compras observadas", s4(w.buy_sol) + " SOL <small>" + f(w.buy_count, 0) + " operações</small>")
        + stat("Vendas após a compra", s4(w.sell_sol) + " SOL <small>" + f(w.seller_count, 0) + (w.seller_count === 1 ? " participante" : " participantes") + "</small>")
        + stat("Saldo do fluxo", sg(w.net_sol)) + stat("Pressão de compra", pressure)
        + stat("Primeira compra na janela", esc(radarDate(w.first_buy)) + "<small>há " + hms(w.age_s) + "</small>")
        + '</dl><div class="radar-wallets"><span class="muted small">Participantes:</span>' + participants.map((p) => {
          const sold = p.last_sell != null, title = "Primeira compra: " + radarDate(p.first_buy) + " · comprou " + s4(p.buy_sol) + " SOL · vendeu " + s4(p.sell_sol) + " SOL";
          return '<span class="radar-wallet' + (sold ? " sold" : "") + '" title="' + esc(title) + '">' + pfW(String(p.wallet || "")) + (sold ? '<span class="small">vendeu</span>' : "") + "</span>";
        }).join("") + '</div><div class="small muted radar-last">Último movimento: ' + esc(radarDate(w.last_trade)) + "</div></article>";
    }).join("");
  }
  async function loadRadar(force) {
    if (RADAR.data && !RADAR.stale && radarOutdated()) { RADAR.stale = true; renderRadar(); }
    if (RADAR.saving) return;
    if (RADAR.busy) { if (force) RADAR.pending = true; return; }
    if (!force && Date.now() - RADAR.at < 4000) return;
    RADAR.busy = true; RADAR.at = Date.now(); const revision = RADAR.revision;
    try {
      const r = await BB.api("/api/pump/radar");
      if (revision !== RADAR.revision) return;
      if (r.error) throw new Error(r.error);
      RADAR.data = r; RADAR.updatedAt = Date.now(); RADAR.stale = false; RADAR.error = ""; renderRadar();
    } catch (e) {
      if (revision === RADAR.revision) {
        invalidateRadar(e.message || "falha de conexão");
      }
    } finally {
      RADAR.busy = false;
      if (RADAR.pending) { RADAR.pending = false; loadRadar(true); }
    }
  }
  async function saveRadar(body, criteria) {
    if (RADAR.saving || !RADAR.data) return;
    RADAR.saving = true; RADAR.revision += 1; radarControls();
    try {
      const r = await BB.api("/api/pump/settings", { body: body }), errors = Object.values(r.errors || {});
      if (r.error || errors.length) throw new Error(r.error || errors.join("; "));
      const applied = r.applied || {}, fields = { pump_radar_enabled: "enabled", pump_radar_min_wallets: "min_wallets", pump_radar_window_min: "window_min" };
      Object.keys(fields).forEach((key) => { if (Object.prototype.hasOwnProperty.call(applied, key)) RADAR.data[fields[key]] = applied[key]; });
      if (criteria) RADAR.dirty = false;
      RADAR.stale = true; RADAR.error = "";
      toast(criteria ? "Critérios do radar salvos." : body.pump_radar_enabled ? "Radar ligado." : "Radar desligado.");
    } catch (e) { toast("Não salvou o radar: " + (e.message || "falha de conexão")); }
    finally { RADAR.saving = false; renderRadar(); await loadRadar(true); }
  }
  $("radarToggle").addEventListener("click", () => saveRadar({ pump_radar_enabled: !RADAR.data.enabled }, false));
  ["radarMin", "radarWindow"].forEach((id) => $(id).addEventListener("input", () => { RADAR.dirty = true; $("radarDraft").hidden = false; }));
  $("radarForm").addEventListener("submit", (e) => {
    e.preventDefault(); if (!$("radarForm").reportValidity()) return;
    const n = Number($("radarMin").value), windowMin = Number($("radarWindow").value);
    if (!Number.isInteger(n) || n < 2 || n > 30 || !Number.isInteger(windowMin) || windowMin < 1 || windowMin > 30) { toast("Use 2 a 30 carteiras e uma janela de 1 a 30 minutos, com números inteiros."); return; }
    saveRadar({ pump_radar_min_wallets: n, pump_radar_window_min: windowMin }, true);
  });

  // ------------------------------------------------------------------ carteiras em estudo (/api/pump/study)
  const money = (v, u) => (v == null ? "–" : (u === "US$" ? (v < 0 ? "−$" : "$") + f(Math.abs(v), Math.abs(v) < 10 ? 2 : 0) : s4(v) + " SOL"));
  const mny = (v, u) => (v == null ? "–" : '<span class="' + (v > 0 ? "up" : v < 0 ? "down" : "") + '">' + (v > 0 ? "+" : "") + money(v, u) + "</span>");
  async function loadStudy() {
    const r = await BB.api("/api/pump/study");
    if (r.error && !(r.wallets || []).length) { $("stList").innerHTML = '<tbody><tr><td class="muted">' + esc(r.error) + "</td></tr></tbody>"; return; }
    const VD = { "compensa copiar": "win", "não compensa": "loss", "no limite": "pause", "poucos dados": "neutral" };
    const pr = r.params || {};
    $("stRkSub").textContent = "quanto VOCÊ teria ganho copiando com " + s4(pr.amt) + " SOL por cópia nos últimos 30 dias · atraso " + f(pr.lag_s, 1) + " s" + (pr.lag_measured ? " (medido nas suas cópias)" : " (estimado)") + (pr.delay_s ? " + espera " + f(pr.delay_s, 0) + " s" : "") + " · taxas e slippage do simulado";
    table("stRank", ["#", "Carteira", "Você copiando (30 d)", "Por dia (7 d)", "Acerto copiando", "Rápido demais p/ copiar", "Veredito", ""], (r.ranking || []).map((x, i) => [String(i + 1),
      pfW(x.wallet) + (x.apelido ? " <b>" + esc(x.apelido) + "</b>" : ""), "<b>" + sg(x.pnl_30d) + "</b><small>" + x.n_30d + " tokens</small>", sg(x.per_day_7d),
      x.win_rate == null ? "–" : f(x.win_rate * 100, 0) + "%", x.fast_pct == null ? "–" : f(x.fast_pct * 100, 0) + "%", '<span class="tag ' + (VD[x.verdict] || "neutral") + '">' + esc(x.verdict) + "</span>",
      x.followed ? '<span class="tag win">copiando</span>' : '<button class="btn sm" data-stc="' + esc(x.wallet) + '">Copiar</button>']), "Ainda sem tokens fechados suficientes para calcular.");
    $("stSub").textContent = "o sistema acompanha e aprende com a carteira, sem copiar · " + (r.wallets || []).length + " de " + r.limit +
      (r.key ? " · histórico pela Solana Tracker" : " · sem chave da Solana Tracker: só o que o monitor ver daqui em diante");
    const mm = (s) => (s == null ? "–" : s < 120 ? f(s, 0) + " s" : f(s / 60, 1) + " min");
    table("stList", ["Carteira", "Ganho/hora (24 h)", "Ganho/dia (média 7 d)", "Acerto", "Segura (mediana)", "Tokens fechados", ""], (r.wallets || []).map((x) => { const s = x.summary || {};
      return [pfW(x.wallet) + (x.apelido ? " <b>" + esc(x.apelido) + "</b>" : "") + (x.followed ? ' <span class="tag win">copiando</span>' : ""), mny(s.per_hour, s.unit), mny(s.per_day_7d, s.unit),
        s.win_rate == null ? "–" : f(s.win_rate * 100, 0) + "%", mm(s.hold_med_s), s.closed == null ? "–" : String(s.closed),
        '<button class="btn sm" data-stp="' + esc(x.wallet) + '">Perfil</button> <button class="btn sm" data-sts="' + esc(x.wallet) + '">Compartilhar</button> ' + (x.followed ? "" : '<button class="btn sm" data-stc="' + esc(x.wallet) + '">Copiar</button> ') + '<button class="btn sm" data-str="' + esc(x.wallet) + '">Remover</button>']; }),
      "Nenhuma carteira em estudo. Cole um endereço acima.");
  }
  // compartilhar uma carteira em estudo com outro usuário (0.17.1): ela entra na lista de estudo da pessoa
  async function openShare(w) {
    const r = await BB.api("/api/pump/study/share-targets");
    const us = r.users || [];
    $("stShW").textContent = w.slice(0, 4) + "…" + w.slice(-4); $("stShare").dataset.w = w;
    $("stShU").innerHTML = us.length ? us.map((u) => '<option value="' + esc(u.user_id) + '">' + esc((u.nome || "sem nome") + (u.email ? " · " + u.email : "")) + "</option>").join("")
      : '<option value="">Nenhum outro usuário cadastrado</option>';
    $("stShGo").disabled = !us.length; $("stShare").hidden = false;
    $("stShare").scrollIntoView({ behavior: "smooth", block: "center" });
  }
  async function openStudy(w) {
    const r = await BB.api("/api/pump/study/" + encodeURIComponent(w));
    $("stProf").hidden = false; $("stPT").innerHTML = "Perfil · " + pfW(w);
    if (r.error) { $("stK").innerHTML = '<p class="muted">' + esc(r.error) + "</p>"; return; }
    const m = r.main || r.live || {}, u = m.unit, mm = (s) => (s == null ? "–" : s < 120 ? f(s, 0) + " s" : f(s / 60, 1) + " min");
    $("stPS").textContent = "fonte: " + (m.source || "sem dados ainda") + " · " + r.trades_seen + " operações vistas pelo monitor";
    kpis("stK", [["Ganho por minuto", mny(m.per_min, u), "média das últimas 24 h", "pnl"], ["Ganho por hora", mny(m.per_hour, u), (m.n_24h || 0) + " tokens fechados em 24 h", "pnl"],
      ["Ganho por dia", mny(m.per_day_7d, u), "média dos últimos 7 dias", "pnl"], ["Últimos 7 / 30 dias", mny(m.pnl_7d, u) + "<small> / " + money(m.pnl_30d, u) + "</small>", (m.n_7d || 0) + " / " + (m.n_30d || 0) + " tokens", "tr"],
      ["Acerto", m.win_rate == null ? "–" : f(m.win_rate * 100, 0) + "%", (m.closed || 0) + " fechados", "hit"], ["Segura (mediana)", mm(m.hold_med_s), m.invested_med != null ? "aposta mediana " + money(m.invested_med, u) : "", "pos"]]);
    const cp = r.copy;
    if (cp) {
      const as = cp.assumptions || {};
      kpis("stCK", [["Você copiando (30 d)", sg(cp.pnl_30d), cp.n_30d + " tokens · " + s4(cp.amt) + " SOL por cópia", "pnl"], ["Por dia (7 d)", sg(cp.per_day_7d), "média por dia", "pnl"],
        ["Acerto copiando", cp.win_rate == null ? "–" : f(cp.win_rate * 100, 0) + "%", "a carteira: " + (cp.trader_win_rate == null ? "–" : f(cp.trader_win_rate * 100, 0) + "%"), "hit"],
        ["Rápido demais", cp.fast_pct == null ? "–" : f(cp.fast_pct * 100, 0) + "%", "saiu antes do seu atraso + espera", "mon"]]);
      $("stCN").textContent = "Veredito: " + cp.verdict + ". Premissas: taxa " + f(as.fee_pct_each_side, 2) + "% e slippage " + f(as.slip_pct_each_side, 2) + "% em cada lado, prioridade " + s4(as.prio_sol) + " SOL por operação, atraso " + f(as.lag_s, 1) + " s" + (as.lag_measured ? " (medido)" : " (estimado)") + (as.delay_s ? " + espera " + f(as.delay_s, 0) + " s" : "") + ". Estimativa: quando a carteira sai antes de você entrar, conta só a perda de taxas e slippage — na prática costuma ser pior.";
    } else { $("stCK").innerHTML = '<p class="muted">Ainda sem tokens vendidos por inteiro para calcular.</p>'; $("stCN").textContent = ""; }
    table("stDay", ["Dia", "Resultado"], (m.days || []).map((d) => [esc(d[0].split("-").reverse().join("/")), mny(d[1], u)]), "Sem dias ainda.");
    const off = -new Date().getTimezoneOffset() / 60, hrs = (m.buys_by_hour_utc || []).map((n, h) => ({ h: (h + off + 24) % 24, n })).filter((x) => x.n).sort((a, b) => b.n - a.n).slice(0, 8);
    table("stHr", ["Hora", "Compras"], hrs.map((x) => [String(x.h).padStart(2, "0") + "h", String(x.n)]), "Sem dados de horário.");
    table("stBest", ["Token", "Resultado", "ROI", "Investiu", "Segurou"], (m.best || []).map((p) => [pfM(p.token, p.symbol), mny(p.realized, u), p.roi == null ? "–" : f(p.roi, 0) + "%", money(p.invested, u), mm(p.hold_s)]), "Sem histórico da Solana Tracker.");
    table("stRec", ["Quando", "Token", "Operação", "SOL", "Market cap"], (r.recent || []).map((t) => [dt(t.at), pfM(t.mint), t.side === "buy" ? '<span class="tag buy">Compra</span>' : '<span class="tag loss">Venda</span>', s4(t.sol), t.mcap_sol == null ? "–" : f(t.mcap_sol, 0) + " SOL"]), "O monitor ainda não viu operações desta carteira.");
    $("stNotes").innerHTML = (r.notes || []).map((s) => "<p>" + esc(s) + "</p>").join("");
    $("stProf").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.id === "stAdd") {
      const raw = $("stW").value.trim(), w = (raw.match(/[1-9A-HJ-NP-Za-km-z]{32,44}/) || [""])[0];
      const r = await BB.api("/api/pump/study", { body: { wallet: w, action: "add", apelido: $("stA").value.trim() } });
      toast(r.error ? "Não adicionou: " + r.error : r.already ? "Essa carteira já está no estudo." : "Carteira adicionada ao estudo. O histórico chega em alguns segundos.");
      if (!r.error) { $("stW").value = ""; $("stA").value = ""; setTimeout(loadStudy, 4000); }
      return loadStudy();
    }
    if (t.id === "stPX") { $("stProf").hidden = true; return; }
    if (t.dataset.stp) return openStudy(t.dataset.stp);
    if (t.dataset.sts) return openShare(t.dataset.sts);
    if (t.id === "stShX") { $("stShare").hidden = true; return; }
    if (t.id === "stShGo") {
      const to = $("stShU").value; if (!to) return;
      const r = await BB.api("/api/pump/study/share", { body: { wallet: $("stShare").dataset.w, to } });
      toast(r.error ? "Não compartilhou: " + r.error : r.already ? "Essa pessoa já estuda essa carteira." : "Carteira compartilhada. Ela já aparece nas Carteiras em estudo da pessoa.");
      if (!r.error) $("stShare").hidden = true;
      return;
    }
    if (t.dataset.stc) { if (!confirm("Passar a COPIAR esta carteira (entra como carteira manual)?")) return; const r = await BB.api("/api/pump/wallets", { body: { wallet: t.dataset.stc, action: "add" } }); toast(r.error || "Agora copiando."); poll(true); return loadStudy(); }
    if (t.dataset.str) { if (!confirm("Remover do estudo?")) return; await BB.api("/api/pump/study", { body: { wallet: t.dataset.str, action: "remove" } }); $("stProf").hidden = true; return loadStudy(); }
  });

  // ------------------------------------------------------------------ novidades (só admin: /api/admin/novidades, lista em app/novidades.json)
  let NOV = null, NOV_TIPO = "";
  async function loadNovidades() {
    if (!NOV) {
      const r = await BB.api("/api/admin/novidades");
      if (r.error || !r.itens) { $("tNov").innerHTML = '<tbody><tr><td class="muted">Não consegui carregar a lista de novidades.</td></tr></tbody>'; return; }
      NOV = r.itens;
    }
    const hoje = Date.now(), TAG = { novo: "win", melhoria: "buy", "segurança": "pause", "correção": "trail" };
    const rows = NOV.filter((x) => !NOV_TIPO || x.tipo === NOV_TIPO);
    $("tNov").innerHTML = "<thead><tr><th>Versão</th><th>Data</th><th>Tipo</th><th>Onde fica</th><th>O que é e o que faz</th></tr></thead><tbody>" +
      rows.map((x) => {
        const recente = hoje - new Date(x.data + "T00:00:00").getTime() < 14 * 86400000;
        return '<tr class="' + (recente ? "nov-recente" : "") + '"><td class="mono">' + esc(x.versao) +
          '</td><td class="mono">' + esc(x.data.split("-").reverse().join("/")) + '</td><td><span class="tag ' + (TAG[x.tipo] || "neutral") + '">' + esc(x.tipo) +
          "</span></td><td>" + esc(x.onde) + "</td><td><b>" + esc(x.titulo) + '</b><br><span class="muted">' + esc(x.oque) + "</span></td></tr>";
      }).join("") + "</tbody>";
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#novTipo button"); if (!b) return;
    NOV_TIPO = b.dataset.t; document.querySelectorAll("#novTipo button").forEach((x) => x.classList.toggle("on", x === b)); loadNovidades();
  });

  function toast(m) { const d = document.createElement("div"); d.textContent = m; $("toasts").prepend(d); setTimeout(() => d.remove(), 8000); }
  const cfg = () => (D && D.cfg) || {};
  const realMode = () => (MODE ? MODE === "real" : !!(D && D.real && D.real.enabled));

  // ------------------------------------------------------------------ navegação
  const TITLES = { visao: ["Visão geral", "sua carteira e o que o bot fez"], traders: ["Top traders", "quem está sendo copiado e por quê"], posicoes: ["Posições", "o que está aberto agora"],
    historico: ["Histórico", "trades fechados, líquidos de taxas"], relatorios: ["Relatórios", "o que está dando certo e errado nas cópias"],
    aprendizado: ["Aprendizado diário", "o que os top traders fazem e o que dá para ajustar"],
    base: ["Base da pump.fun", "a vida de cada token novo, criadores e mercado por hora"], listanegra: ["Lista negra", "criadores e carteiras que ninguém copia"], fantasma: ["Estratégias fantasma", "várias regras de saída testadas ao mesmo tempo, só no simulado"], novas: ["Opções novas de cópia", "em teste: ligue para usar ou deixe desligado para descartar"], estudo: ["Carteiras em estudo", "entender o que as carteiras fazem e quanto ganham"], radar: ["Radar de KOLs", "ondas de compras e primeiras vendas nas carteiras em estudo"], feed: ["Feed ao vivo", "cada movimento dos traders copiados"], real: ["Execução real", "carteira de verdade · começa desligada"],
    config: ["Configurações", "regras de cópia, proteções e chaves"], admin: ["Administração", "usuários, sistema e logs"],
    novidades: ["Novidades", "o que foi implementado, onde fica e o que faz"], ajuda: ["Como funciona", ""] };
  let VIEW = "visao";
  function route() {
    const v = (location.hash || "#visao").slice(1);
    VIEW = TITLES[v] ? v : "visao";
    // Administração e o menu "Usar ou descartar" (0.17.3, pedido do dono em 2026-10-25) são só do admin
    if (["admin", "novidades", "estudo", "radar", "relatorios", "aprendizado", "novas", "fantasma", "listanegra", "base"].includes(VIEW) && !(ME && ME.role === "admin")) VIEW = "visao";
    document.querySelectorAll(".view").forEach((s) => (s.hidden = s.dataset.view !== VIEW));
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === VIEW));
    if (document.querySelector("#navSub a.on")) { $("navGrp").classList.remove("fechado"); $("navGrpH").setAttribute("aria-expanded", "true"); }
    $("pgTitle").textContent = TITLES[VIEW][0]; $("pgSub").textContent = TITLES[VIEW][1];
    closeDrawer();
    if (VIEW === "config") { loadSecrets(); loadAudit(); }
    if (VIEW === "admin") { loadAdmin(); loadSysKeys(); loadUsers(); loadAAudit(); LOG_AFTER = 0; $("logs").innerHTML = ""; loadLogs(); }
    if (VIEW === "real") walletLoad(true);
    if (VIEW === "novidades") loadNovidades();
    if (VIEW === "relatorios") loadReports();
    if (VIEW === "fantasma") loadGhosts();
    if (VIEW === "listanegra") loadBlacklist();
    if (VIEW === "base") loadBase();
    if (VIEW === "aprendizado") loadLearning();
    if (VIEW === "estudo") loadStudy();
    if (VIEW === "radar") loadRadar(true);
    render();
    window.scrollTo(0, 0);
  }
  function closeDrawer() { $("side").classList.remove("open"); $("scrim").classList.remove("open"); }

  // ------------------------------------------------------------------ notificações (som + aviso)
  let NTF = false, NTF_AT = 0;
  try { NTF = localStorage.getItem("ntf") === "1"; } catch (e) { /* */ }
  function ntfBtn() { const b = $("ntfB"); b.textContent = "🔔 Notificações: " + (NTF ? "ON" : "OFF"); b.className = "btn tgl ntf " + (NTF ? "on" : "off"); }
  function tone(C, t0, fr, dur, type, vol) { const o = C.createOscillator(), g = C.createGain(); o.type = type; o.frequency.setValueAtTime(fr, t0); g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(vol, t0 + 0.012); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur); o.connect(g); g.connect(C.destination); o.start(t0); o.stop(t0 + dur + 0.02); }
  function play(kind, vol) {
    try {
      const C = window.__ac || (window.__ac = new (window.AudioContext || window.webkitAudioContext)()); if (C.state === "suspended") C.resume();
      const t = C.currentTime + 0.01, v = vol || 0.35;
      const S = { buy: [[0, 880, 0.09, "triangle"], [0.09, 1320, 0.16, "triangle"]], win: [[0, 1046, 0.1, "sine"], [0.1, 1318, 0.1, "sine"], [0.2, 1568, 0.1, "sine"], [0.3, 2093, 0.28, "sine"]],
        loss: [[0, 523, 0.16, "sawtooth"], [0.16, 392, 0.3, "sawtooth"]], sell: [[0, 1320, 0.09, "triangle"], [0.09, 990, 0.16, "triangle"]],
        alert: [[0, 1760, 0.07, "square"], [0.12, 1760, 0.07, "square"], [0.24, 2349, 0.12, "square"]], error: [[0, 220, 0.18, "square"], [0.22, 180, 0.28, "square"]] }[kind] || [[0, 1000, 0.1, "sine"]];
      S.forEach((x) => tone(C, t + x[0], x[1], x[2], x[3], v * (x[3] === "square" || x[3] === "sawtooth" ? 0.35 : 1)));
    } catch (e) { /* sem áudio */ }
  }
  function classify(m) {
    m = String(m || "");
    if (/^Radar\b/i.test(m)) return "alert";
    if (/^Top traders atualizados/i.test(m)) return "trader";
    if (/PAUSADO|parece robô/.test(m)) return "alert";
    if (/segurando/i.test(m)) return null;
    if (/falhou|N[ÃA]O feita|N[ÃA]O feito|n[ãa]o comprou|n[ãa]o vendeu|(^|[^a-z])erro([^a-z]|$)|ATEN[ÇC][ÃA]O/i.test(m)) return "error";
    if (/fechou|vendeu|saiu|stop|alvo/i.test(m)) { const tail = m.split("→").pop(); const mm = tail.match(/([+−-]) ?[$]?[0-9]/); if (mm) return mm[1] === "+" ? "win" : "loss"; return "sell"; }
    if (/comprou|copiou [^:]*: compra|copiou compra|entrou/i.test(m)) return "buy";
    if (/PAUSADO|robô/i.test(m)) return "alert";
    return null;
  }
  function onEvent(e) {
    const k = classify(e.msg); const real = /REAL/.test(e.msg);
    mascReact(e.msg);
    if (real || k === "error" || /^Radar\b/i.test(e.msg)) toast(e.msg.slice(0, 180));
    if (!NTF || !k || k === "trader") return;
    const now = Date.now(); if (now - NTF_AT < 1200 && k !== "error") return; NTF_AT = now;
    play(k, real ? 0.55 : 0.28);
    try { if (document.hidden && window.Notification && Notification.permission === "granted") new Notification({ buy: "Compra", win: "Lucro", loss: "Prejuízo", sell: "Venda", alert: "Aviso", error: "Erro" }[k] + (real ? " (REAL)" : ""), { body: e.msg.slice(0, 200), silent: true }); } catch (x) { /* */ }
  }

  // ------------------------------------------------------------------ mascote (Visão geral)
  // Humor = como a carteira está; cada notificação faz ele reagir por alguns segundos e depois volta ao humor.
  const MASC = {
    rindo: ["rindo", "m-pula", "ok"], feliz: ["acenando", "m-balanca", "ok"], pensativo: ["ideia", "m-pensa", ""],
    triste: ["triste", "m-murcha", "bad"], chorando: ["chorando", "m-soluca", "bad"], bravo: ["bravo", "m-treme", "warn"],
    timido: ["timido", "m-balanca", ""], oi: ["acenando", "m-balanca", ""],
  };
  const M = { pose: "", anim: "", until: 0, t: null };
  function mascSrc(n) { const im = $("mascImg"); return im ? im.getAttribute("src").replace(/\/[a-z]+\.webp/, "/" + n + ".webp") : ""; }
  (function preload() { if ($("mascImg")) ["rindo", "acenando", "ideia", "triste", "chorando", "bravo", "timido"].forEach((n) => { const i = new Image(); i.src = mascSrc(n); }); })();
  function mascShow(key, anim, title, sub, pop) {
    const box = $("masc"), im = $("mascImg"); if (!box || !im) return;
    const [pose, a0, tone] = MASC[key]; const an = anim || a0;
    $("mascT").textContent = title; $("mascS").textContent = sub || "";
    box.classList.remove("ok", "bad", "warn"); if (tone) box.classList.add(tone);
    if (pop) { box.classList.remove("pop"); void box.offsetWidth; box.classList.add("pop"); }
    if (pose === M.pose && an === M.anim) return;
    clearTimeout(M.t2);
    if (pose !== M.pose) { im.src = mascSrc(pose); im.className = "m-entra"; M.t2 = setTimeout(() => { im.className = an; }, 350); }
    else im.className = an;
    M.pose = pose; M.anim = an;
  }
  function mascMood() {
    if (!D || Date.now() < M.until) return;
    const rm = realMode(), Wt = (rm ? D.real_wallet : D.wallet) || {}, RP = D.rpc || {};
    if (!RP.ws) return mascShow("bravo", "m-pensa", "Monitor parado", "sem o monitor eu não vejo os traders; já tentando reconectar");
    let pct = null;
    if (rm) { const base = W && W.sol ? W.sol : 0; const day = D.real_curve || []; const since = Date.now() - 86400000; let d = 0; day.forEach((p, i) => { if (new Date(p[0]) >= since) d += p[1] - (i ? day[i - 1][1] : 0); }); if (base) pct = (d / base) * 100; }
    else if (Wt.start_sol) pct = (Wt.pnl_sol / Wt.start_sol) * 100;
    const txt = pct == null ? "" : (pct >= 0 ? "+" : "") + pct.toFixed(1).replace(".", ",") + "%" + (rm ? " em 24 h" : " desde o início");
    if (!Wt.count && !Wt.open) return mascShow("oi", "", "Oi! Tudo pronto", "esperando o primeiro trade dos traders copiados");
    if (pct == null) return mascShow("pensativo", "", "Pensando…", "ainda sem saldo para comparar");
    if (pct >= 5) return mascShow("rindo", "", "Tá voando!", "carteira " + txt);
    if (pct >= 1) return mascShow("feliz", "", "Indo bem", "carteira " + txt);
    if (pct > -1) return mascShow("pensativo", "", "Hmm, no zero a zero", "carteira " + txt + (Wt.open ? " · " + Wt.open + " posições abertas" : ""));
    if (pct > -5) return mascShow("triste", "", "Meio pra baixo", "carteira " + txt);
    return mascShow("chorando", "", "Dia difícil…", "carteira " + txt);
  }
  // Lê a notificação e diz QUAL ação foi (título curto) e como o mascote reage. A mais específica vem primeiro.
  function mascKind(msg) {
    const m = String(msg || ""), real = /\[PUMP REAL\]/.test(m) ? " (REAL)" : "";
    const pc = (m.split("→")[1] || "").match(/\(([+−-]?[0-9]+(?:[.,][0-9]+)?)%\)/);
    const pct = pc ? " " + (/^[+−-]/.test(pc[1]) ? "" : "+") + pc[1].replace(".", ",") + "%" : "";
    const neg = /→\s*[−-]/.test(m), pos = /→\s*\+/.test(m);
    if (/^Radar\b/i.test(m)) return /vend/i.test(m) ? ["pensativo", "m-pensa", "Venda na onda"] : /\bHOT\b/i.test(m) ? ["pensativo", "m-pula", "HOT no radar"] : ["pensativo", "m-pula", "Onda no radar"];
    if (/^Top traders atualizados/i.test(m)) return ["timido", "m-balanca", "Troquei os traders"];
    if (/PAUSADO/.test(m)) return ["bravo", "m-treme", "Trader pausado"];
    if (/parece robô/i.test(m)) return ["bravo", "m-treme", "Robô detectado"];
    if (/voltou a ser copiado/i.test(m)) return ["feliz", "m-balanca", "Trader voltou"];
    if (/DESLIGADA/.test(m)) return ["bravo", "m-pensa", "Modo real desligado"];
    if (/N[ÃA]O feit|falhou|(^|[^a-z])erro([^a-z]|$)|ATEN[ÇC][ÃA]O/i.test(m)) return ["bravo", "m-treme", "Deu erro" + real];
    if (/adiada|pendente/i.test(m)) return ["pensativo", "m-pensa", "Venda aguardando" + real];
    if (/segurando/i.test(m)) return ["pensativo", "m-pensa", "Segurando a posição"];
    if (/: compra |\] comprou /i.test(m)) return ["pensativo", "m-pula", "Compra copiada" + real];
    if (/fechou/i.test(m)) {
      if (pos) return ["rindo", "m-pula-forte", (/stop móvel/i.test(m) ? "Stop móvel no lucro" : /gradua/i.test(m) ? "Saiu antes da graduação" : "Venda com lucro") + pct + real];
      if (neg) return [/stop/i.test(m) ? "chorando" : "triste", "m-treme", (/stop de perda|stop/i.test(m) ? "Stop de perda" : /tempo/i.test(m) ? "Saiu por tempo" : "Venda com prejuízo") + pct + real];
      return ["feliz", "m-balanca", "Posição fechada" + real];
    }
    if (/vendeu [0-9]+%|vendendo [0-9]+%/i.test(m)) { const q = m.match(/vend(?:eu|endo) ([0-9]+%)/i); return ["feliz", /em partes/i.test(m) ? "m-pula" : "m-balanca", (/em partes/i.test(m) ? "Realizou lucro " : "Venda parcial ") + (q ? q[1] : "") + real]; }
    if (/removida/i.test(m)) return ["timido", "m-balanca", "Posição removida"];
    return null;
  }
  // Várias notificações juntas: mostra uma de cada vez (2,5 s cada); a última fica 6 s e ele volta ao humor da carteira.
  function mascReact(msg) {
    const R = mascKind(msg); if (!R) return;
    M.q = (M.q || []).concat([[R, String(msg || "")]]).slice(-5);
    if (!M.busy) mascNext();
  }
  function mascNext() {
    const it = (M.q || []).shift();
    if (!it) { M.busy = false; M.until = 0; mascMood(); return; }
    M.busy = true; M.until = Date.now() + 7000;
    const [R, msg] = it;
    mascShow(R[0], R[1], R[2], msg.replace(/^Pump\.fun:\s*/, "").replace(/^\[PUMP (SIM|REAL)\]\s*/, "").slice(0, 110), true);
    clearTimeout(M.t); M.t = setTimeout(mascNext, M.q.length ? 2500 : 6000);
  }
  window.BB.mascote = mascReact;   // para testar a reação no console: BB.mascote("[PUMP SIM] fechou X … → +0.01 SOL (+5.0%)")

  // ------------------------------------------------------------------ dados
  async function poll(force) {
    // O intervalo do painel continua expirando os destaques mesmo se uma consulta ficar pendurada.
    if (VIEW === "radar" && RADAR.data && !RADAR.stale && radarOutdated()) { RADAR.stale = true; renderRadar(); }
    if (BUSY && !force) return; BUSY = true;
    try {
      const r = await BB.api("/api/pump?ev=" + Math.max(EV, 0));
      if (r.error) { $("sysS").textContent = r.error; if (VIEW === "radar") invalidateRadar(r.error); return; }
      D = r;
      const evs = r.events || [];
      if (EV < 0) EV = evs.length ? evs[evs.length - 1].id : 0;
      else evs.forEach((e) => { if (e.id > EV) { EV = e.id; onEvent(e); } });
      render();
    } catch (e) { if (VIEW === "radar") invalidateRadar(e.message || "falha de conexão"); } finally { BUSY = false; }
  }
  async function walletLoad(force) { try { W = await BB.api("/api/pump/wallet" + (force ? "?force=1" : "")); if (VIEW === "real") renderReal(); } catch (e) { /* */ } }

  async function setCfg(body) {
    const r = await BB.api("/api/pump/settings", { body: body });
    const errs = Object.entries(r.errors || {});
    toast(r.error || (errs.length ? "Não aplicado: " + errs.map((e) => e[0].replace("pump_", "") + " (" + e[1] + ")").join(", ") : "Salvo."));
    poll(true);
  }

  // ------------------------------------------------------------------ render geral
  function render() {
    if (!D) return;
    const c = cfg(), R = D.real || {}, RP = D.rpc || {};
    const rm = realMode();
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === (rm ? "real" : "sim")));
    document.querySelectorAll("[data-mtag]").forEach((e) => { e.textContent = rm ? "Real" : "Simulado"; e.className = "tag " + (rm ? "real" : "sim"); });
    $("nbTr").textContent = (D.followed || []).length || "";
    $("nbPos").textContent = (D.positions || []).filter((p) => !!p.real === rm).length || "";
    $("nbReal").textContent = R.enabled ? "ON" : "";
    $("sysDot").className = "dot " + (RP.ws ? "on" : "off");
    $("sysT").textContent = "Monitor " + (RP.ws ? "ON" : "OFF");
    $("sysS").textContent = RP.ws ? (RP.subs || 0) + " carteiras · " + (RP.parsed || 0) + " trades lidos" : (RP.error || "aguardando o monitor compartilhado");
    // controles de configuração (inputs, liga/desliga)
    document.querySelectorAll("[data-cfg]").forEach((el) => { if (document.activeElement !== el) el.value = c[el.dataset.cfg] ?? ""; });
    document.querySelectorAll("[data-toggle]").forEach((b) => { const on = !!c[b.dataset.toggle]; b.textContent = on ? "ON" : "OFF"; b.classList.add("tgl"); b.classList.toggle("on", on); b.classList.toggle("off", !on); });
    $("delayN").textContent = (c.pump_copy_delay_s > 0 ? "só copia se o trader ainda estiver no token depois de " + c.pump_copy_delay_s + " s (entra no preço de então)" : "copia na hora") + ((D.pending || []).length ? " · " + D.pending.length + " aguardando" : "");
    $("trailN").textContent = "ex.: chegou a +" + c.pump_trail_start_pct + "% líquido → stop móvel ligado; subiu até +50% → sai se voltar a +" + Math.max(50 - c.pump_trail_dist_pct, c.pump_trail_min_lock_pct || 0) + "% (nunca abaixo de +" + (c.pump_trail_min_lock_pct || 0) + "%)";
    $("foot").textContent = "versão " + (D.version || "") + (D.started_at ? " · no ar desde " + D.started_at : "") + " · SOL $" + f(D.sol_usd, 2);
    if (VIEW === "visao") renderOverview();
    else if (VIEW === "traders") renderTraders();
    else if (VIEW === "posicoes") renderPositions();
    else if (VIEW === "historico") renderHistory();
    else if (VIEW === "relatorios" && (Date.now() - REP_AT > 30000 || REP_MODE !== realMode())) loadReports();
    else if (VIEW === "aprendizado" && (Date.now() - AP_AT > 60000 || AP_MODE !== realMode())) loadLearning();
    else if (VIEW === "radar") loadRadar(false);
    else if (VIEW === "feed") renderFeed();
    else if (VIEW === "real") renderReal();
  }

  // ------------------------------------------------------------------ visão geral
  function renderOverview() {
    const c = cfg(), R = D.real || {}, rm = realMode(), Wt = (rm ? D.real_wallet : D.wallet) || {}, st0 = D.status || {}, RP = D.rpc || {};
    const pnlPct = Wt.start_sol ? (Wt.pnl_sol / Wt.start_sol) * 100 : null;
    const day = (rm ? D.real_curve : D.curve) || [];
    const since = Date.now() - 86400000; let d24 = 0; day.forEach((p, i) => { if (new Date(p[0]) >= since) d24 += p[1] - (i ? day[i - 1][1] : (rm ? 0 : Wt.start_sol)); });
    kpis("kpis", [
      [rm ? "Carteira real" : "Saldo fictício", rm ? (W && W.sol != null ? s4(W.sol) + "<small> SOL</small>" : "–") : s4(Wt.equity_sol) + "<small> SOL</small>", rm ? (W && W.configured ? "na blockchain" : "carteira não configurada") : (D.sol_usd ? "≈ " + usd(Wt.equity_sol * D.sol_usd, 2) : "início " + s4(Wt.start_sol) + " SOL"), "wallet"],
      ["Resultado", sg(Wt.pnl_sol, ""), (pnlPct != null ? pc(pnlPct) + " desde o início · " : "") + "24 h " + sg(d24, ""), "pnl"],
      ["Posições abertas", String(Wt.open || 0), "valor " + s4(Wt.open_value_sol) + " SOL · máx. " + (rm ? c.pump_real_max_open : c.pump_max_open), "pos"],
      ["Trades fechados", String(Wt.count || 0), '<span class="up">' + (Wt.wins || 0) + " ganhos</span> · <span class=\"down\">" + (Wt.losses || 0) + " perdas</span>", "tr"],
      ["Taxa de acerto", Wt.win_rate == null ? "–" : f(Wt.win_rate * 100, 0) + "%", "ganhos " + s4(Wt.gains_sol) + " · perdas " + s4(Wt.losses_sol), "hit"],
      ["Traders copiados", String(st0.followed || 0), (D.paused || []).length ? D.paused.length + " pausados" : (st0.wallets_seen || 0) + " carteiras vistas", "usr"],
      ["Monitor", RP.ws ? '<span class="up">ON</span>' : '<span class="down">OFF</span>', RP.ws ? (RP.subs || 0) + " carteiras · real " + (R.enabled ? "LIGADO" : "OFF") : esc(RP.error || "aguardando"), "mon"],
    ]);
    $("curveSub").textContent = "SOL · " + (rm ? "real" : "simulado");
    document.querySelectorAll("#rangeSeg button").forEach((b) => b.classList.toggle("on", +b.dataset.r === RANGE));
    drawCurve(rm ? 0 : Wt.start_sol, rm ? D.real_curve : D.curve);
    renderOps(rm);
    renderCfgStatus();
    mascMood();
  }

  function drawCurve(start, pts) {
    const el = $("curve"); const Wd = el.clientWidth || 600, H = el.clientHeight || 260, P = 54, B = 22;
    pts = (pts || []).map((p) => [new Date(p[0]).getTime(), p[1]]);
    const t0 = Date.now() - RANGE * 86400000;
    const before = pts.filter((p) => p[0] < t0); let base = before.length ? before[before.length - 1][1] : start;
    let S = [[t0, base]].concat(pts.filter((p) => p[0] >= t0)); S.push([Date.now(), S[S.length - 1][1]]);
    if (S.length <= 2 && !pts.length) { el.innerHTML = '<div class="empty" style="padding-top:90px">A carteira começa com ' + s4(start) + " SOL. A linha aparece a partir do primeiro trade fechado.</div>"; return; }
    const ys = S.map((p) => p[1]); let lo = Math.min(...ys, start), hi = Math.max(...ys, start); if (hi - lo < 0.01) { lo -= 0.005; hi += 0.005; }
    const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
    const X = (t) => P + ((t - t0) / (Date.now() - t0)) * (Wd - P - 10), Y = (v) => 10 + ((hi - v) / (hi - lo)) * (H - B - 14);
    const up = S[S.length - 1][1] >= base, col = up ? "#22c55e" : "#ef4444";
    let path = ""; S.forEach((p, i) => { const x = X(p[0]).toFixed(1), y = Y(p[1]).toFixed(1); path += i ? " H" + x + " V" + y : "M" + x + " " + y; });
    const grid = [0, 1, 2, 3].map((i) => { const v = lo + ((hi - lo) * i) / 3; return '<line x1="' + P + '" x2="' + Wd + '" y1="' + Y(v) + '" y2="' + Y(v) + '" stroke="#1e1e22"/><text x="4" y="' + (Y(v) + 4) + '" font-size="10.5" fill="#5d5d66" font-family="JetBrains Mono,monospace">' + v.toFixed(3) + "</text>"; }).join("");
    const xl = [0, 0.5, 1].map((k) => { const t = t0 + k * (Date.now() - t0); const d = new Date(t); const lab = RANGE === 1 ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }); return '<text x="' + Math.min(Wd - 40, Math.max(P, X(t) - 16)) + '" y="' + (H - 4) + '" font-size="10.5" fill="#5d5d66">' + lab + "</text>"; }).join("");
    el.innerHTML = '<svg viewBox="0 0 ' + Wd + " " + H + '" preserveAspectRatio="none"><defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + col + '" stop-opacity=".25"/><stop offset="1" stop-color="' + col + '" stop-opacity="0"/></linearGradient></defs>' + grid +
      '<line x1="' + P + '" x2="' + Wd + '" y1="' + Y(start) + '" y2="' + Y(start) + '" stroke="#5d5d66" stroke-dasharray="3 4" opacity=".6"/>' +
      '<path d="' + path + " V" + (H - B) + " H" + X(t0) + 'Z" fill="url(#cg)"/><path d="' + path + '" fill="none" stroke="' + col + '" stroke-width="2"/>' + xl + "</svg>";
  }

  function opTag(kind) {
    return { buy: '<span class="tag buy">Compra</span>', win: '<span class="tag win">Venda c/ lucro</span>', loss: '<span class="tag loss">Venda c/ prejuízo</span>', stop: '<span class="tag stop">Stop</span>',
      trail: '<span class="tag trail">Stop móvel</span>', err: '<span class="tag err">Erro</span>', pause: '<span class="tag pause">Pausado</span>' }[kind];
  }
  function renderOps(rm) {
    const out = [];
    (D.trades || []).forEach((t) => {
      const r = String(t.reason || ""); const k = /stop móvel/.test(r) ? "trail" : /^stop de perda/.test(r) ? "stop" : t.pnl_sol > 0 ? "win" : "loss";
      out.push({ at: t.closed_at, k, real: !!t.real, t: (t.symbol || "?") + " · " + r, m: "copiado de " + shortW(t.wallet), amt: sg(t.pnl_sol) + '<div class="m">' + pc(t.pnl_pct) + "</div>" });
    });
    (D.feed || []).forEach((e) => {
      const a = String(e.action || ""); let k = null;
      if (a === "copiou compra" || a === "REAL comprou") k = "buy"; else if (/falhou/.test(a)) k = "err"; else if (/pausad/.test(String(e.reason || ""))) k = "pause";
      if (k) out.push({ at: e.at, k, real: /REAL/.test(a), t: (e.symbol || "?") + " · " + (k === "buy" ? "copiou " + shortW(e.wallet) : e.reason), m: "trader " + shortW(e.wallet) + (e.sol != null ? " · ele usou " + s4(e.sol) + " SOL" : ""), amt: "" });
    });
    (D.paused || []).forEach((p) => out.push({ at: p.at, k: "pause", real: false, t: shortW(p.wallet) + " · " + (p.reason || "pausado"), m: p.until ? "volta em " + hms(p.until - Date.now() / 1000) : "até você retomar", amt: "" }));
    out.sort((a, b) => new Date(b.at) - new Date(a.at));
    const L = out.slice(0, 9);
    $("ops").innerHTML = L.length ? L.map((o) => '<div class="op"><div style="min-width:0"><div class="t">' + esc(o.t) + '</div><div class="m">há ' + agoIso(o.at) + " · " + esc(o.m) + '</div></div><div><div class="tags">' + opTag(o.k) + (o.real ? '<span class="tag real">Real</span>' : '<span class="tag sim">Simulado</span>') + '</div><div class="amt">' + o.amt + "</div></div></div>").join("")
      : '<div class="empty">Ainda não houve operação. Quando um trader copiado comprar, aparece aqui.</div>';
  }

  function renderCfgStatus() {
    const c = cfg(), R = D.real || {}, n = (v) => (v == null ? "–" : f(v, v % 1 ? 2 : 0));
    const it = [["Execução REAL", R.enabled ? "compra " + n(c.pump_real_max_sol) + " SOL" : "—", st(R.enabled, 1)], ["Cópia automática", (D.followed || []).length + " traders", st(D.copy_enabled)],
      ["Fictício: valor por cópia", n(c.pump_copy_sol) + " SOL", ""], ["Esperar antes de copiar", c.pump_copy_delay_s > 0 ? n(c.pump_copy_delay_s) + " s" : "na hora", st(c.pump_copy_delay_s > 0)],
      ["Fora da pump.fun (fictício)", "pool ≥ $" + n(c.pump_other_min_liq_usd), st(c.pump_copy_other)], ["Fora da pump.fun (real)", "via Jupiter", st(c.pump_copy_other_real, 1)],
      ["Segurar até lucro", "após taxas", st(c.pump_hold_until_profit)], ["Stop móvel", "+" + n(c.pump_trail_start_pct) + "% · −" + n(c.pump_trail_dist_pct) + " pts · " + n(c.pump_trail_fast_s) + " s", st(c.pump_trail_enabled)],
      ["Stop de perda", "−" + n(c.pump_stop_pct) + "%", st(c.pump_stop_pct > 0)], ["Pausa automática", n(c.pump_autopause_stops) + " stops/24 h → " + n(c.pump_autopause_hours) + " h", st(c.pump_autopause_stops > 0 && c.pump_autopause_hours > 0)],
      ["Traders pausados", String((D.paused || []).length), ""], ["Tempo máximo", n(c.pump_max_hold_h) + " h", st(c.pump_max_hold_h > 0)], ["Alvo fixo", c.pump_tp_pct > 0 ? "+" + n(c.pump_tp_pct) + "%" : "—", st(c.pump_tp_pct > 0)],
      ["Acerto mínimo do trader", "> " + n(c.pump_min_winrate) + "%", st(c.pump_min_winrate > 0)], ["Trades mínimos do trader", "≥ " + n(c.pump_lb_min_trades), st(c.pump_lb_min_trades > 0)],
      ["Saldo mínimo do trader", "$" + n(c.pump_min_wallet_usd), st(c.pump_min_wallet_usd > 0)], ["Compra mínima do trader", n(c.pump_min_trader_sol) + " SOL", st(c.pump_min_trader_sol > 0)],
      ["Market cap mínimo", "$" + n(c.pump_min_mcap_usd), st(c.pump_min_mcap_usd > 0)], ["Volume 1 h mínimo", "$" + n(c.pump_min_vol_h1_usd), st(c.pump_min_vol_h1_usd > 0)],
      ["Negociações 1 h mínimas", n(c.pump_min_txns_h1), st(c.pump_min_txns_h1 > 0)], ["10 maiores carteiras máx.", n(c.pump_max_top10_pct) + "%", st(c.pump_max_top10_pct > 0)], ["Venda em partes", c.pump_tp1_on && c.pump_tp1_pct > 0 ? "+" + n(c.pump_tp1_pct) + "% → " + n(c.pump_tp1_frac_pct) + "%" : "OFF", st(c.pump_tp1_on && c.pump_tp1_pct > 0)],
      ["Sair antes da graduação", c.pump_curve_exit_on && c.pump_curve_exit_pct > 0 ? "curva " + n(c.pump_curve_exit_pct) + "%" : "OFF", st(c.pump_curve_exit_on && c.pump_curve_exit_pct > 0)],
      ["Pressão de compra mín.", c.pump_buy_pressure_on && c.pump_min_buy_pressure_pct > 0 ? n(c.pump_min_buy_pressure_pct) + "%" : "OFF", st(c.pump_buy_pressure_on && c.pump_min_buy_pressure_pct > 0)],
      ["Velocidade mín. da curva", c.pump_curve_speed_on && c.pump_min_curve_speed > 0 ? n(c.pump_min_curve_speed) + "%/min" : "OFF", st(c.pump_curve_speed_on && c.pump_min_curve_speed > 0)],
      ["Token já graduado", c.pump_skip_graduated ? "não copia" : "copia", st(!!c.pump_skip_graduated)],
      ["Valor conforme o trader", c.pump_size_by_trader ? "ligado" : "desligado", st(!!c.pump_size_by_trader)],
      ["Preço subiu desde o trader (máx.)", c.pump_chase_on && c.pump_max_chase_pct > 0 ? n(c.pump_max_chase_pct) + "%" : "OFF", st(c.pump_chase_on && c.pump_max_chase_pct > 0)], ["Risco do token máx.", c.pump_risk_check ? n(c.pump_max_risk_score) + "/10" : "não checa", st(!!c.pump_risk_check)],
      ["Lista negra", c.pump_blacklist_on ? "não copia" : "desligada", st(!!c.pump_blacklist_on)], ["Telegram", c.pump_tg_on ? (c.pump_tg_all ? "tudo" : "só importantes") : "desligado", st(!!c.pump_tg_on)],
      ["Sair quando o dev vende", c.pump_exit_dev_sell ? "ligado" : "desligado", st(!!c.pump_exit_dev_sell)], ["Sair quando gradua", c.pump_exit_migrate ? "ligado" : "desligado", st(!!c.pump_exit_migrate)],
      ["Sair com pressão virando", c.pump_exit_pressure_on ? "< " + n(c.pump_exit_pressure_pct) + "%" : "OFF", st(!!c.pump_exit_pressure_on)], ["Sair com outras vendendo", c.pump_exit_kol_on ? n(c.pump_exit_kol_n) + " carteiras" : "OFF", st(!!c.pump_exit_kol_on)],
      ["Nota mínima", c.pump_score_min_on ? n(c.pump_score_min) : "OFF", st(!!c.pump_score_min_on)], ["Valor pela nota", c.pump_size_by_score ? "ligado" : "desligado", st(!!c.pump_size_by_score)],
      ["Pausa por perdas seguidas", c.pump_streak_on ? n(c.pump_streak_n) + " → " + n(c.pump_streak_h) + " h" : "OFF", st(!!c.pump_streak_on)], ["Mercado frio", c.pump_cold_on ? "< " + n(c.pump_cold_wr) + "%" : "OFF", st(!!c.pump_cold_on)],
      ["Posições máx.", "fictício " + n(c.pump_max_open) + " · real " + n(c.pump_real_max_open), ""], ["Perda máx. no dia (real)", n(c.pump_real_daily_loss_sol) + " SOL", st(c.pump_real_daily_loss_sol > 0)], ["Período do top", n(c.pump_lb_days) + " dias", ""]];
    // opções da tela "Opções novas de cópia" (menu Usar ou descartar) só aparecem para o admin (0.17.3)
    const NOVAS = ["Lista negra", "Telegram", "Sair quando o dev vende", "Sair quando gradua", "Sair com pressão virando", "Sair com outras vendendo", "Nota mínima", "Valor pela nota", "Pausa por perdas seguidas", "Mercado frio", "Venda em partes", "Sair antes da graduação", "Pressão de compra mín.", "Velocidade mín. da curva", "Token já graduado", "Valor conforme o trader", "Preço subiu desde o trader (máx.)", "Risco do token máx."];
    $("cfgS").innerHTML = it.filter((x) => (ME && ME.role === "admin") || !NOVAS.includes(x[0])).map((x) => '<div><span class="k">' + x[0] + '</span><span class="v">' + esc(x[1]) + x[2] + "</span></div>").join("");
  }

  // ------------------------------------------------------------------ top traders
  const ST = { online: '<span class="tag win">● online</span>', inativo: '<span class="tag pause">● inativo</span>', "sem atividade": '<span class="tag neutral">○ sem atividade</span>', robô: '<span class="tag loss">robô</span>' };
  function stat(a, last) {
    a = a || {};
    if (a.status === "sem atividade" && last) { const s = (Date.now() - last) / 1000; return (s < 600 ? ST.online : s < 86400 ? ST.inativo : ST["sem atividade"]) + "<small>último trade há " + hms(s) + "</small>"; }
    return (ST[a.status] || "–") + (a.bot_reason ? "<small>" + esc(a.bot_reason) + "</small>" : a.last ? "<small>tx há " + agoT(a.last) + (a.pump_last ? " · pump há " + agoT(a.pump_last) : "") + "</small>" : "");
  }
  function renderTraders() {
    const c = cfg(), L = D.leaderboard || [], ls = D.lb_status || {};
    document.querySelectorAll("#lbDays button").forEach((b) => b.classList.toggle("on", +b.dataset.d === +(c.pump_lb_days || 7)));
    $("lbKey").hidden = !!ls.key_set;
    $("lbSub").textContent = ls.key_set ? L.length + " traders · Solana Tracker (app pump.fun)" + (ls.own_key === false ? " · usando a chave do sistema (visualização)" : "") + (ls.at ? " · atualizado há " + agoIso(ls.at) : "") + " · copiando pelo " + (ls.source || "") : "precisa da chave grátis da Solana Tracker";
    table("tLb", ["#", "Trader", "Status", "Saldo", "Lucro", "ROI", "Acerto", "Trades", "Tokens", "Dias", "Último trade", "Situação", ""], L.map((r) => [String(r.rank), pfW(r.wallet) + (r.name ? "<small>" + esc(r.name) + "</small>" : ""), stat(r.act, r.last_trade),
      r.wallet_usd == null ? '<span class="dim">…</span>' : usd(r.wallet_usd), usdS(r.realized_usd), r.roi == null ? "–" : pc(r.roi, 0), r.winrate == null ? "–" : f(r.winrate, 0) + "%", r.trades == null ? "–" : String(r.trades), r.tokens == null ? "–" : String(r.tokens), r.days_active == null ? "–" : String(r.days_active), r.last_trade ? agoIso(r.last_trade) : "–",
      r.paused ? '<span class="tag pause">Pausado</span>' : r.followed ? '<span class="tag win">Copiando</span>' : r.eligible ? (c.pump_only_online && !r.online ? '<span class="tag pause">Apto · fora (inativo)</span>' : '<span class="tag neutral">Apto</span>') : '<span class="dim" style="white-space:normal;display:block;max-width:260px">' + esc((r.flags || []).join(" · ")) + "</span>",
      r.paused ? btn("Retomar", "w", { a: "resume", w: r.wallet }, "tgl on") : r.followed ? btn("Pausar", "w", { a: "pause", w: r.wallet }) : r.manual ? "" : btn("Copiar", "w", { a: "add", w: r.wallet })]),
      ls.key_set ? (ls.error ? '<span class="down">Erro da Solana Tracker: ' + esc(ls.error) + "</span>" : "Buscando o ranking…") : "A lista aparece assim que a chave da Solana Tracker for salva.");
    $("lbNote").innerHTML = (ls.error && ls.key_set && L.length ? '<span class="down">Erro da Solana Tracker: ' + esc(ls.error) + "</span><br>" : "") + "Ranking por lucro realizado em US$ no período. Os " + (c.pump_top_n || 10) + " primeiros aptos são copiados (carteiras manuais vêm antes). Só copia quem tem acerto ACIMA de " + (c.pump_min_winrate || 50) + "% e pelo menos " + (c.pump_lb_min_trades || 0) + " trades no período. Robôs, devs de token e corretoras ficam de fora. " + (c.pump_only_online ? "Só copia quem está ONLINE (negociou nos últimos " + (c.pump_online_min || 10) + " min): a cada 10 min quem ficou inativo sai e entra o melhor do top que estiver online. " : "") + "O ranking é consultado a cada 10 min.";
    const F = D.followed || [];
    $("folSub").textContent = F.length + " carteiras" + ((D.paused || []).length ? " · " + D.paused.length + " pausadas" : "") + " · manuais primeiro";
    table("tFol", ["#", "Carteira", "Origem", "Status", "Última transação", "Trades pump.fun", "Fora da pump.fun", "Lucro (top)", "Copiado", "Ações"],
      F.map((r, i) => { const cp = r.copied, a = r.act || {}, lb = r.lb || {}; return [String(i + 1), pfW(r.wallet), r.manual ? '<span class="tag pause">Manual</span>' : r.source === "leaderboard" ? '<span class="tag win">Top #' + lb.rank + "</span>" : '<span class="tag neutral">Ranking próprio</span>',
        (ST[a.status] || "–") + (a.bot_reason ? "<small>" + esc(a.bot_reason) + "</small>" : a.tx_min ? "<small>" + a.tx_min + " tx/min</small>" : ""), a.last ? "há " + agoT(a.last) + (a.pump_last ? "<small>pump.fun há " + agoT(a.pump_last) + "</small>" : "") : '<span class="dim">nenhuma desde a conexão</span>',
        String(a.pump || 0), a.other ? a.other + " tx<small>" + (r.other_copied || 0) + " de token · " + (r.ignored || 0) + " ignoradas</small>" : "0", lb.realized_usd != null ? usdS(lb.realized_usd) + "<small>" + (lb.winrate != null ? f(lb.winrate, 0) + "% acerto" : "") + "</small>" : "–",
        cp ? sg(cp.pnl_sol) + "<small>" + cp.n + " trades</small>" : '<span class="dim">–</span>',
        (r.manual ? btn("Tirar", "w", { a: "remove", w: r.wallet }) + " " : "") + btn("Pausar", "w", { a: "pause", w: r.wallet }) + " " + btn("Banir", "w", { a: "ban", w: r.wallet }, "tgl off")]; })
        .concat((D.paused || []).map((r) => { const a = r.act || {}, lb = r.lb || {}, cp = r.copied; return ["–", pfW(r.wallet), '<span class="tag pause">⏸ Pausado</span>', ST[a.status] || "–", esc(r.reason || "") + "<small>" + (r.until ? "volta em " + hms(r.until - Date.now() / 1000) : "até você retomar") + "</small>", "–", "–", lb.realized_usd != null ? usdS(lb.realized_usd) : "–", cp ? sg(cp.pnl_sol) : "–", btn("Retomar", "w", { a: "resume", w: r.wallet }, "tgl on")]; })),
      "Nenhum trader copiado ainda — salve a chave da Solana Tracker ou adicione uma carteira manual.");
    // monitor
    document.querySelectorAll("#monSeg button").forEach((b) => b.classList.toggle("on", b.dataset.f === MONF));
    const RP = D.rpc || {}, Lv = (D.live || []).filter((e) => MONF === "all" || e.kind === MONF);
    $("monSub").innerHTML = (RP.ws ? '<span class="up">● conectado</span>' : '<span class="down">● desconectado</span>') + " · " + F.length + " carteiras · " + (D.live || []).length + " eventos";
    const AC = { entrou: '<span class="tag win">Entrou</span>', aumentou: '<span class="tag win">Aumentou</span>', saiu: '<span class="tag loss">Saiu</span>', "vendeu parte": '<span class="tag pause">Vendeu parte</span>' };
    table("tMon", ["Hora", "Há", "Trader", "Ação", "Token", "SOL", "Preço", "Mcap", "Resultado dele", ""], Lv.map((e) => [dt(e.t * 1000), agoT(e.t), pfW(e.wallet), AC[e.action] || esc(e.action), pfM(e.mint, e.symbol), s4(e.sol), ex(e.price), e.mcap_sol == null ? "–" : f(e.mcap_sol, 0) + " SOL",
      e.kind === "sell" ? (e.pnl_pct == null ? '<span class="dim">entrada não vista</span>' : pc(e.pnl_pct)) + (e.sold_pct != null ? "<small>" + e.sold_pct + "% da posição</small>" : "") : '<span class="dim">–</span>', tx(e.signature)]),
      F.length ? "Aguardando a próxima compra ou venda dos traders copiados…" : "Nenhum trader copiado ainda.");
    table("tTP", ["Trader", "Token", "Investiu", "Preço médio", "Agora", "Variação", "Valor", "Mcap", "Segurando há"], (D.trader_pos || []).map((p) => [pfW(p.wallet), pfM(p.mint, p.symbol), s4(p.invested_sol) + " SOL", ex(p.avg_price), ex(p.price), pc(p.chg_pct), p.value_sol == null ? "–" : s4(p.value_sol) + " SOL", p.mcap_sol == null ? "–" : f(p.mcap_sol, 0) + " SOL", hms(p.held_s)]),
      "Nenhuma posição aberta vista ainda (aparece quando um trader copiado compra).");
    // ranking próprio
    const rr = D.ranking || [];
    $("rkSub").textContent = rr.length + " carteiras com ≥ " + c.pump_min_closed + " tokens fechados em " + (c.pump_rank_hours || 24) + " h";
    table("tRk", ["Carteira", "Lucro 24h", "Acerto", "Segura", "Trades/h", "Abertos", "Situação", ""], rr.slice(0, 40).map((r) => [pfW(r.wallet), sg(r.pnl_sol), f(r.winrate, 0) + "% (" + r.wins + "/" + r.closed + ")", hms(r.hold_s), String(r.trades_h), String(r.open),
      r.followed ? '<span class="tag win">Copiando</span>' : r.eligible ? '<span class="tag neutral">Apta</span>' : '<span class="dim">' + esc((r.flags || []).join(" · ")) + "</span>", r.followed ? "" : btn("Copiar", "w", { a: "add", w: r.wallet })]),
      "O ranking próprio enche com o tempo (ele precisa ver os trades de todos os tokens novos).");
    $("rkNote").innerHTML = (D.paid_stream ? "" : "<b>Sem dados:</b> o ranking próprio precisa ver os trades de todos os tokens novos, e a PumpPortal cobra por isso. Por isso o bot copia pelos Top traders acima. ") + "Filtros: acerto ≥ " + c.pump_min_winrate + "%, segura ≥ " + c.pump_min_hold_s + " s (abaixo disso é robô sniper), até " + c.pump_max_trades_h + " trades/h, sem dev." +
      ((D.banned || []).length ? "<br>Banidas: " + D.banned.map((w) => pfW(w) + " " + btn("liberar", "w", { a: "unban", w: w })).join(" · ") : "");
  }

  // ------------------------------------------------------------------ posições / histórico / feed
  function renderPositions() {
    const c = cfg(), rm = realMode(), P = (D.positions || []).filter((p) => !!p.real === rm);
    $("posSub").textContent = (rm ? "REAL · " : "FICTÍCIO · ") + P.length + " de " + (rm ? c.pump_real_max_open : c.pump_max_open) + " · " + s4(rm ? c.pump_real_max_sol : c.pump_copy_sol) + " SOL cada" + (rm ? " (valores medidos na carteira)" : " · slippage extra " + c.pump_extra_slip_pct + "%") + " · variação já líquida de taxas";
    const vol = (p) => { const v = p.vol; if (!v) return '<span class="dim">aguardando</span>'; return "<b>" + uk(v.h1) + '</b> <span class="dim">1 h</span><small>5 min ' + uk(v.m5) + " · 24 h " + uk(v.h24) + "</small><small>" + (v.buys_h1 || 0) + " compras · " + (v.sells_h1 || 0) + " vendas</small>"; };
    table("tPos", ["Token", "Trader", "Entrada", "Investido", "Agora", "Variação", "Volume do token", "Vendido", "Aberta há", ""], P.map((p) => [pfM(p.mint, p.symbol) + (p.mcap_now ? "<small>mcap " + f(p.mcap_now, 0) + " SOL</small>" : "") + (p.venue_in ? "<small>" + esc(p.venue_in) + "</small>" : ""), pfW(p.wallet), ex(p.price_in), s4(p.sol_in) + " SOL",
      ex(p.price_now || p.price_in) + (p.price_at ? "<small>há " + agoT(p.price_at) + "</small>" : ""), pc(p.chg_pct), vol(p), (p.sells || []).length ? s4(p.proceeds) + " SOL" : "–", agoIso(p.opened_at),
      (p.trail_peak != null ? '<span class="tag trail">Stop móvel</span><small>pico ' + pc(p.trail_peak) + " · sai em +" + f(p.trail_exit, 1) + "%</small>" : "") + (p.hold_profit ? '<span class="tag pause">Segurando até lucro</span><small>desde ' + dt(p.hold_since) + "</small>" : "") +
      (p.selling ? '<span class="tag pause">Vendendo…</span>' : btn(p.real ? "Vender" : "Fechar", "close", { id: p.id, real: p.real ? 1 : 0 }, p.real ? "tgl off" : "")) + (p.sell_error ? '<small class="down">' + esc(p.sell_error) + "</small>" : "")]),
      rm ? "Nenhuma posição REAL aberta." : "Nenhuma posição aberta. Quando um trader copiado comprar, a cópia aparece aqui.");
  }
  function renderHistory() {
    const rm = realMode(), T = (D.trades || []).filter((t) => !!t.real === rm);
    $("trSub").textContent = T.length + " trades · líquido = depois de TODAS as taxas (pump.fun/PumpSwap, PumpPortal, rede) e do slippage";
    const fee = (t) => { const fp = t.fee_parts || {}; if (t.fees_sol == null) return "–"; const tip = "pump.fun/PumpSwap: " + s4(fp.platform) + " · PumpPortal: " + s4(fp.portal) + " · rede: " + s4(fp.network) + (fp.slippage ? " · slippage: " + s4(fp.slippage) : ""); return '<span title="' + esc(tip) + '">' + s4(t.fees_sol) + " SOL</span><small>" + (t.sol_in ? f((t.fees_sol / t.sol_in) * 100, 1) + "% do investido" : "") + "</small>"; };
    table("tTr", ["Fechou", "Token", "Trader", "Investido", "Recebido", "Taxas", "Bruto", "Líquido", "%", "Segurou", "Motivo", "Tipo"], T.map((t) => [dt(t.closed_at), pfM(t.mint, t.symbol) + (t.venue ? "<small>" + esc(t.venue) + "</small>" : ""), pfW(t.wallet), s4(t.sol_in), s4(t.sol_out), fee(t), sg(t.gross_sol), "<b>" + sg(t.pnl_sol) + "</b>", pc(t.pnl_pct), hms(t.hold_s),
      '<span style="white-space:normal;display:block;max-width:280px">' + esc(t.reason) + "</span>", t.real ? '<span class="tag real">Real</span>' : '<span class="tag sim">Sim</span>']), "Nenhum trade fechado ainda.");
    const by = {}; T.forEach((t) => { const b = (by[t.wallet] = by[t.wallet] || { n: 0, w: 0, p: 0, pp: 0, po: 0, np: 0, no: 0 }); const isP = String(t.venue || "pump").toLowerCase().indexOf("pump") >= 0; b.n++; b.w += t.pnl_sol > 0; b.p += t.pnl_sol; if (isP) { b.pp += t.pnl_sol; b.np++; } else { b.po += t.pnl_sol; b.no++; } });
    table("tBy", ["Trader", "Trades", "Acerto", "Resultado", "pump.fun", "Fora da pump.fun"], Object.entries(by).sort((a, b) => b[1].p - a[1].p).map(([w, b]) => [pfW(w), String(b.n), f((b.w / b.n) * 100, 0) + "%", sg(b.p), b.np ? sg(b.pp) + "<small>" + b.np + " trades</small>" : "–", b.no ? sg(b.po) + "<small>" + b.no + " trades</small>" : "–"]), "Sem trades fechados ainda.");
  }
  function renderFeed() {
    table("tFeed", ["Hora", "Trader", "Token", "Trader fez", "SOL", "Mcap", "O bot"], (D.feed || []).map((e) => [dt(e.at), pfW(e.wallet), pfM(e.mint, e.symbol), e.kind === "buy" ? '<span class="tag buy">Compra</span>' : '<span class="tag loss">Venda</span>', s4(e.sol), e.mcap_sol == null ? "–" : f(e.mcap_sol, 0) + " SOL",
      '<span style="white-space:normal;display:block;max-width:420px" class="' + (e.action === "não copiou" ? "dim" : "") + '"><b>' + esc(e.action) + "</b>: " + esc(e.reason) + "</span>"]), "O feed enche quando os traders copiados fizerem algo.");
  }

  // ------------------------------------------------------------------ execução real
  function renderReal() {
    const c = cfg(), R = D ? D.real || {} : {}, w = W || {}, p = w.sol_usd || (D && D.sol_usd) || 0, Rw = (D && D.real_wallet) || {};
    kpis("wKpis", w.configured ? [["Saldo da carteira", w.sol == null ? "–" : s4(w.sol) + " SOL", p && w.sol != null ? "≈ $" + f(w.sol * p, 2) : esc(w.error || ""), "wallet"],
      ["USDC na carteira", w.usdc_in_sol == null ? "–" : s4(w.usdc_in_sol) + " SOL", "$" + f(w.usdc || 0, 2) + " USDC — troque por SOL para usar", "pnl"],
      ["Compras possíveis", w.sol == null || !c.pump_real_max_sol ? "–" : String(Math.max(0, Math.floor((w.sol - (w.reserve_sol || 0.02)) / (c.pump_real_max_sol * 1.02 + 0.0006)))), "de " + s4(c.pump_real_max_sol) + " SOL (guarda 0,02 SOL p/ taxas)", "pos"],
      ["Resultado real", sg(Rw.pnl_sol, ""), (Rw.count || 0) + " trades · " + (Rw.open || 0) + " abertas", "tr"]]
      : [["Carteira do bot", "não configurada", "cole a chave em Configurações → Chaves", "wallet"], ["Resultado real", sg(Rw.pnl_sol, ""), (Rw.count || 0) + " trades", "tr"]]);
    const b = $("realB"); b.textContent = R.enabled ? "REAL: ON — clique para desligar" : "REAL: OFF — clique para ligar"; b.className = "btn tgl big " + (R.enabled ? "on" : "off");
    $("realSub").textContent = R.enabled ? "LIGADA — compras de verdade com até " + s4(c.pump_real_max_sol) + " SOL cada" : "desligada";
    $("realInfo").innerHTML = '<div class="cfgs" style="grid-template-columns:repeat(auto-fill,minmax(200px,1fr))">' +
      [["Carteira do bot", R.wallet_configured ? '<span class="up">configurada</span>' : '<span class="down">não configurada</span>'], ["Endereço", R.address ? '<a href="https://solscan.io/account/' + encodeURIComponent(R.address) + '" target="_blank" rel="noopener">' + esc(shortW(R.address)) + "</a>" : "–"],
        ["Chave PumpPortal (opcional)", R.api_key_set ? "salva" : "não"], ["Trava do servidor", R.allowed ? '<span class="up">liberado</span>' : '<span class="down">travado (.env)</span>'], ["Fila real", ((D && D.real_pending) || {}).queue || 0]]
        .map((x) => '<div><span class="k">' + x[0] + '</span><span class="v">' + x[1] + "</span></div>").join("") + "</div>";
    $("rMaxN").textContent = "Cada cópia real compra no máximo este valor (+ taxa da pump.fun, 0,5% da PumpPortal e taxa de rede)." + (p && c.pump_real_max_sol ? " ≈ $" + f(c.pump_real_max_sol * p, 2) : "");
    $("rLossU").textContent = p && c.pump_real_daily_loss_sol ? "≈ $" + f(c.pump_real_daily_loss_sol * p, 2) : "";
    $("cvN").textContent = p ? "1 SOL = $" + f(p, 2) + " · 1 USDC = " + s4(1 / p) + " SOL" : "aguardando preço do SOL";
  }
  function conv(src) { const p = (W && W.sol_usd) || (D && D.sol_usd) || 0; if (!p) return; if (src === "u") { const u = +$("cvU").value || 0; $("cvS").value = u ? (u / p).toFixed(4) : ""; } else { const x = +$("cvS").value || 0; $("cvU").value = x ? (x * p).toFixed(2) : ""; } }
  async function swap(b) {
    const u = +$("cvU").value || 0; if (!u) { toast("Digite quantos USDC quer trocar."); return; }
    b.disabled = true; $("swN").textContent = "Cotando…";
    const q = await BB.api("/api/pump/swap/quote?usdc=" + u);
    if (q.error) { $("swN").textContent = q.error; b.disabled = false; return; }
    $("swN").textContent = "Cotação: " + f(q.usdc, 2) + " USDC → " + s4(q.sol_out) + " SOL (" + (q.venue || "") + ", impacto " + f(q.impact_pct || 0, 3) + "%)";
    if (!confirm("Trocar " + f(q.usdc, 2) + " USDC por cerca de " + s4(q.sol_out) + " SOL na carteira do bot (via " + (q.venue || "Jupiter") + ")?\n\nIsto é uma transação REAL.")) { b.disabled = false; return; }
    $("swN").textContent = "Enviando a troca…";
    const r = await BB.api("/api/pump/swap", { body: { usdc: u, confirm: true } }); b.disabled = false;
    if (r.ok) { $("swN").textContent = "Feito: recebeu " + s4(r.sol_received) + " SOL · saldo agora " + s4(r.sol_balance) + " SOL"; $("cvU").value = ""; $("cvS").value = ""; }
    else $("swN").textContent = "Não trocou: " + (r.error || r.reason || r.status || "erro");
    walletLoad(true);
  }
  async function realToggle() {
    const R = (D && D.real) || {}, c = cfg();
    if (!R.enabled) {
      const t = prompt("Ligar a cópia com DINHEIRO REAL?\n\nCada compra usa até " + c.pump_real_max_sol + " SOL. Para confirmar, digite LIGAR:");
      if ((t || "").trim().toUpperCase() !== "LIGAR") { toast("Execução real continua DESLIGADA."); return; }
      const r = await BB.api("/api/pump/real", { body: { enabled: true, confirm: "LIGAR" } }); toast(r.error || "Execução REAL LIGADA.");
    } else { const r = await BB.api("/api/pump/real", { body: { enabled: false } }); toast(r.error || "Execução real desligada."); }
    poll(true);
  }

  // ------------------------------------------------------------------ chaves / admin / auditoria
  const KEY_HINT = { telegram_bot_token: "Crie um bot no Telegram com o @BotFather e cole o token aqui. Usado só para mandar os avisos para você.",
    telegram_chat_id: "Mande uma mensagem para o @userinfobot e cole o número (Id). Depois mande /start para o seu bot.", solanatracker_api_key: "Grátis em solanatracker.io → Data API. Usada para o ranking oficial dos top traders.",
    pumpportal_api_key: "Opcional. Só para dados extras pagos da PumpPortal.",
    wallet_private_key: "Chave privada (base58 da Phantom/Solflare ou os 64 números do id.json) de uma carteira NOVA só para o bot. Fica criptografada e só é usada no servidor para assinar.",
    rpc_url: "Opcional. Endereço https:// de um RPC próprio (Helius, QuickNode…) — mais rápido e sem limite do público.",
    jupiter_api_key: "Opcional. Aumenta o limite de cotações da Jupiter para a sua carteira." };
  async function loadSecrets() {
    const r = await BB.api("/api/secrets"); if (r.error) return;
    const w = r.wallet || {};
    const using = (v) => v.configured ? '<span class="tag win">Usando: sua chave</span>' : v.system ? '<span class="tag sim">Usando: chave do sistema (só visualização)</span>' : '<span class="tag loss">Não configurada</span>';
    $("secrets").innerHTML = Object.entries(r.keys).map(([k, v]) => '<div class="secret"><div><div class="name">' + esc(v.label) + '</div><div class="muted" style="font-size:12.5px">' + esc(KEY_HINT[k] || "") +
      (v.link ? ' <a href="' + esc(v.link) + '" target="_blank" rel="noopener">' + (k === "wallet_private_key" ? "Criar uma carteira nova →" : k === "rpc_url" ? "Criar um RPC →" : "Criar minha chave →") + "</a>" : "") +
      (k === "wallet_private_key" && w.address ? '<br>Endereço público: <span class="mono">' + esc(w.address) + "</span>" : "") + (k === "rpc_url" && w.rpc_set ? '<br>Servidor: <span class="mono">' + esc(w.rpc_host || "") + "</span>" : "") + "</div></div>" +
      "<div>" + using(v) + "</div>" +
      '<div class="row"><input class="in" type="password" autocomplete="new-password" spellcheck="false" data-secret="' + k + '" placeholder="' + (v.configured ? "colar nova para trocar" : "colar a sua chave aqui") + '">' +
      btn("Salvar", "secret-save", { k: k }, "primary") + (v.configured ? btn("Remover", "secret-del", { k: k }, "tgl off") : "") + "</div></div>").join("");
  }
  async function loadSysKeys() {
    const r = await BB.api("/api/admin/keys"); if (r.error) return;
    $("sysKeys").innerHTML = Object.entries(r.keys).map(([k, v]) => '<div class="secret"><div><div class="name">' + esc(v.label) + '</div><div class="muted" style="font-size:12.5px">' + esc(KEY_HINT[k] || "") +
      (v.link ? ' <a href="' + esc(v.link) + '" target="_blank" rel="noopener">Onde criar →</a>' : "") + (v.updated_at ? "<br>Atualizada em " + dt(v.updated_at) : "") + "</div></div>" +
      "<div>" + (v.configured ? '<span class="tag win">Configurada: sim</span>' : '<span class="tag loss">Configurada: não</span>') + "</div>" +
      '<div class="row"><input class="in" type="password" autocomplete="new-password" spellcheck="false" data-syskey="' + k + '" placeholder="' + (v.configured ? "colar nova para trocar" : "colar aqui") + '">' +
      btn("Salvar", "syskey-save", { k: k }, "primary") + (v.configured ? btn("Remover", "syskey-del", { k: k }, "tgl off") : "") + "</div></div>").join("");
  }
  async function loadAudit() {
    const L = await BB.api("/api/audit"); if (!Array.isArray(L)) return;
    table("tAudit", ["Quando", "Ação", "Detalhe"], L.map((a) => [dt(a.at), esc(a.acao), '<span style="white-space:normal">' + esc(a.detalhe || "") + "</span>"]), "Nenhuma ação registrada ainda.");
  }
  async function loadAdmin() {
    const A = (ADMIN = await BB.api("/api/admin/status")); if (A.error) return;
    const m = A.monitor || {}, rpc = m.rpc || {}, pp = m.pumpportal || {}, j = m.jupiter || {};
    $("adminS").innerHTML = [["Usuários cadastrados", A.users_total], ["Motores carregados", A.users_loaded], ["Com execução real ON", A.real_on], ["Trava do real (.env)", A.real_allowed ? "liberado" : "travado"],
      ["Monitor Solana", rpc.ws ? "conectado · " + (rpc.subs || 0) + " carteiras" : rpc.error || "desconectado"], ["Trades lidos / erros", (rpc.parsed || 0) + " / " + (rpc.tx_errors || 0)], ["PumpPortal (tokens novos)", pp.ws ? "conectado · " + (pp.new_tokens || 0) : pp.error || "desconectado"],
      ["Jupiter", j && j.on ? "ok " + (j.latency_ms || "") + " ms" : (j && j.error) || "–"], ["Preço do SOL", m.sol_usd ? "$" + f(m.sol_usd, 2) : "–"], ["Chaves do sistema", Object.entries(A.system_keys || {}).filter((x) => x[1]).map((x) => ({ solanatracker_api_key: "Solana Tracker", pumpportal_api_key: "PumpPortal", jupiter_api_key: "Jupiter" }[x[0]])).join(", ") || "nenhuma"], ["No ar há", hms(A.uptime_s)],
      ["Erros de gravação no banco", (A.db_errors || []).length ? A.db_errors.map((e) => e.user + ": " + (e.error || e.queued + " gravações na fila")).join(" · ") : "nenhum"]]
      .map((x) => '<div><span class="k">' + x[0] + '</span><span class="v">' + esc(x[1]) + "</span></div>").join("");
  }

  // ------------------------------------------------------------------ administração: usuários, registro e logs
  let USERS = [], LOG_AFTER = 0, LOG_LV = "INFO", LOG_LIVE = true;
  async function loadUsers() {
    const r = await BB.api("/api/admin/users"); if (r.error) { toast(r.error); return; }
    USERS = r.users || []; USERS.me = r.me; renderUsers();
    const sel = $("aAudUser"), cur = sel.value;
    sel.innerHTML = '<option value="">Todos os usuários</option>' + USERS.map((u) => '<option value="' + esc(u.user_id) + '">' + esc(u.email || u.user_id.slice(0, 8)) + "</option>").join("");
    sel.value = cur;
    const day = Date.now() - 86400000, A = ADMIN || {};
    kpis("aKpis", [["Usuários", String(USERS.length), USERS.filter((u) => u.role === "admin").length + " admin", "usr"],
      ["Ativos em 24 h", String(USERS.filter((u) => u.ultimo_acesso && new Date(u.ultimo_acesso) > day).length), "abriram o painel", "mon"],
      ["Bloqueados", String(USERS.filter((u) => u.bloqueado).length), "não copiam nem entram", "hit"],
      ["Com real ON", String(USERS.filter((u) => u.stats && u.stats.real_enabled).length), A.real_allowed ? "trava do servidor: liberado" : "trava do servidor: travado", "pnl"],
      ["Copiando agora", String(USERS.filter((u) => u.stats && u.stats.copy_enabled && u.stats.followed).length), "cópia ligada e com traders", "tr"],
      ["Erros de banco", String((A.db_errors || []).length), (A.db_errors || []).length ? "veja o status geral" : "nenhum", "pos"]]);
    $("nbAdm").textContent = USERS.filter((u) => u.bloqueado).length || "";
  }
  function renderUsers() {
    const q = ($("aFind").value || "").toLowerCase().trim(), me = USERS.me;
    const L = USERS.filter((u) => !q || (String(u.email || "") + " " + String(u.nome || "")).toLowerCase().indexOf(q) >= 0);
    const key = (on, label) => '<span class="tag ' + (on ? "win" : "neutral") + '" title="' + label + (on ? ": configurada" : ": não configurada") + '">' + label + "</span>";
    table("tUsers", ["Usuário", "Categoria", "Situação", "Último acesso", "Desde", "Cópia", "Fictício", "Real", "Chaves", "Ações"], L.map((u) => {
      const S = u.stats || {}, k = S.keys || {}, mine = u.user_id === me;
      return ['<div class="who">' + (u.avatar_url ? '<img alt="" referrerpolicy="no-referrer" src="' + esc(u.avatar_url) + '">' : '<span class="ph">' + esc((u.nome || u.email || "?").slice(0, 1).toUpperCase()) + "</span>") +
          "<div>" + esc(u.nome || "—") + (mine ? ' <span class="tag neutral">você</span>' : "") + "<small>" + esc(u.email || u.user_id) + "</small></div></div>",
        '<select class="in" data-urole="' + esc(u.user_id) + '"><option value="user"' + (u.role !== "admin" ? " selected" : "") + '>Usuário</option><option value="admin"' + (u.role === "admin" ? " selected" : "") + ">Admin</option></select>",
        u.bloqueado ? '<span class="tag loss">Bloqueado</span>' : '<span class="tag win">Ativo</span>',
        u.ultimo_acesso ? "há " + agoIso(u.ultimo_acesso) + "<small>" + dt(u.ultimo_acesso) + "</small>" : '<span class="dim">nunca</span>',
        u.criado_em ? new Date(u.criado_em).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "2-digit" }) : "–",
        u.stats ? st(S.copy_enabled) + "<small>" + S.followed + " traders</small>" : '<span class="dim">–</span>',
        u.stats ? sg(S.pnl_sol) + "<small>" + S.trades + " trades · " + S.open + " abertas" + (S.win_rate != null ? " · " + f(S.win_rate * 100, 0) + "%" : "") + "</small>" : "–",
        u.stats ? st(S.real_enabled, 1) + (S.real_trades ? " " + sg(S.real_pnl_sol) : "") + "<small>" + (S.wallet ? "carteira configurada" : "sem carteira") + "</small>" : "–",
        u.stats ? '<div class="keys">' + key(k.solanatracker_api_key, "Tracker") + key(k.wallet_private_key, "Carteira") + key(k.rpc_url, "RPC") + "</div>" + (S.db_error ? '<small class="down">banco: ' + esc(S.db_error) + "</small>" : "") : '<span class="dim">–</span>',
        '<div style="display:flex;flex-direction:column;gap:4px;align-items:stretch">' + (mine ? "" : u.bloqueado ? btn("Desbloquear", "u-block", { uid: u.user_id, v: "0" }, "tgl on") : btn("Bloquear", "u-block", { uid: u.user_id, v: "1" }, "tgl off")) +
          (S.real_enabled ? btn("Desligar real", "u-realoff", { uid: u.user_id }, "tgl off") : "") + btn("Registro", "u-audit", { uid: u.user_id }) + "</div>"];
    }), "Nenhum usuário encontrado.");
  }
  async function adminUser(uid, body, msg) {
    const r = await BB.api("/api/admin/users/" + encodeURIComponent(uid), { body: body });
    toast(r.error ? "Não alterou: " + r.error : (r.changed && r.changed.length ? msg || "Alterado: " + r.changed.join("; ") : "Nada mudou."));
    loadUsers(); loadAAudit(); loadAdmin();
  }
  async function loadAAudit() {
    const u = $("aAudUser").value;
    const L = await BB.api("/api/admin/audit?limit=300" + (u ? "&user_id=" + encodeURIComponent(u) : "")); if (!Array.isArray(L)) return;
    table("tAAudit", ["Quando", "Usuário", "Ação", "Detalhe"], L.map((a) => [dt(a.at), esc(a.email || (a.user_id || "").slice(0, 8)), esc(a.acao), '<span style="white-space:normal;display:block;max-width:520px">' + esc(a.detalhe || "") + "</span>"]), "Nada registrado ainda.");
  }
  async function loadLogs() {
    const r = await BB.api("/api/admin/logs?after=" + LOG_AFTER + "&level=" + LOG_LV + "&q=" + encodeURIComponent($("logQ").value || "")); if (r.error) return;
    const el = $("logs"), atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    (r.logs || []).forEach((x) => { LOG_AFTER = Math.max(LOG_AFTER, x.id); const d = document.createElement("div"); d.className = x.level;
      d.innerHTML = '<span class="t">' + new Date(x.t * 1000).toLocaleString("pt-BR") + '</span><span class="n">' + esc(x.level) + " · " + esc(x.name) + "</span>" + esc(x.msg); el.appendChild(d); });
    while (el.childNodes.length > 1500) el.removeChild(el.firstChild);
    if (atEnd) el.scrollTop = el.scrollHeight;
    $("logSub").textContent = (r.total || 0) + " registros guardados · " + (r.warnings || 0) + " avisos · " + (r.errors || 0) + " erros · chaves mascaradas";
    document.querySelectorAll("#logLv button").forEach((b) => b.classList.toggle("on", b.dataset.lv === LOG_LV));
  }
  function logsReset() { LOG_AFTER = 0; $("logs").innerHTML = ""; loadLogs(); }

  // ------------------------------------------------------------------ busca (⌘K / Ctrl+K)
  let CK = [], CKI = 0;
  function ckOpen() { $("cmdk").hidden = false; $("cmdkIn").value = ""; ckFill(""); setTimeout(() => $("cmdkIn").focus(), 0); }
  function ckClose() { $("cmdk").hidden = true; }
  function ckFill(q) {
    q = q.trim().toLowerCase(); const items = [], seen = new Set();
    const add = (it) => { if (seen.has(it.key)) return; seen.add(it.key); items.push(it); };
    if (D) {
      (D.positions || []).concat(D.trades || []).forEach((p) => add({ key: "t" + p.mint, label: (p.symbol || "?") + " · " + shortW(p.mint), tag: "Token", url: "https://pump.fun/coin/" + p.mint, hay: (p.symbol + " " + p.mint).toLowerCase() }));
      (D.followed || []).forEach((r) => add({ key: "w" + r.wallet, label: shortW(r.wallet) + (r.lb && r.lb.name ? " · " + r.lb.name : ""), tag: "Copiando", url: "https://pump.fun/profile/" + r.wallet, hay: (r.wallet + " " + ((r.lb || {}).name || "")).toLowerCase() }));
      (D.leaderboard || []).forEach((r) => add({ key: "w" + r.wallet, label: "#" + r.rank + " " + shortW(r.wallet) + (r.name ? " · " + r.name : ""), tag: "Top", url: "https://pump.fun/profile/" + r.wallet, hay: (r.wallet + " " + (r.name || "")).toLowerCase() }));
    }
    Object.entries(TITLES).forEach(([k, v]) => add({ key: "p" + k, label: v[0], tag: "Página", hash: k, hay: v[0].toLowerCase() }));
    CK = items.filter((it) => !q || it.hay.indexOf(q) >= 0).slice(0, 30);
    if (/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(q.trim()) || /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(($("cmdkIn").value || "").trim())) {
      const w = $("cmdkIn").value.trim(); CK.unshift({ key: "add", label: "Copiar a carteira " + shortW(w), tag: "Adicionar", add: w });
    }
    CKI = 0; ckDraw();
  }
  function ckDraw() { $("cmdkList").innerHTML = CK.length ? CK.map((it, i) => '<li data-i="' + i + '" class="' + (i === CKI ? "on" : "") + '">' + esc(it.label) + '<span class="tag neutral">' + esc(it.tag) + "</span></li>").join("") : '<li class="dim">Nada encontrado</li>'; }
  async function ckGo(i) {
    const it = CK[i]; if (!it) return; ckClose();
    if (it.hash) location.hash = it.hash; else if (it.add) wallet("add", it.add); else if (it.url) window.open(it.url, "_blank", "noopener");
  }

  // ------------------------------------------------------------------ ações
  async function wallet(a, w, hours) {
    w = (w || "").trim(); if (!w) return;
    if (a === "ban" && !confirm("Banir " + shortW(w) + "? Ele nunca será copiado (até você liberar).")) return;
    const r = await BB.api("/api/pump/wallets", { body: { wallet: w, action: a, hours: hours } });
    toast(r.error || { add: "Carteira adicionada à cópia.", remove: "Carteira manual removida.", ban: "Carteira banida.", unban: "Carteira liberada.", pause: "Trader PAUSADO (entra o próximo do top).", resume: "Trader retomado." }[a]);
    if (a === "add" && !r.error) $("addW").value = "";
    poll(true);
  }
  document.addEventListener("click", async (ev) => {
    const t = ev.target.closest("button,[data-act]"); if (!t) return;
    if (t.dataset.toggle) { const k = t.dataset.toggle, on = !cfg()[k]; if (on && t.dataset.confirm && !confirm(t.dataset.confirm)) return; setCfg({ [k]: on }); return; }
    if (t.dataset.set) { setCfg({ [t.dataset.set]: +t.dataset.val }); return; }
    if (t.dataset.mode) { MODE = t.dataset.mode; try { localStorage.setItem("pf:mode", MODE); } catch (e) { /* */ } render(); return; }
    if (t.dataset.r) { RANGE = +t.dataset.r; try { localStorage.setItem("pf:range", RANGE); } catch (e) { /* */ } render(); return; }
    if (t.dataset.f) { MONF = t.dataset.f; render(); return; }
    if (t.dataset.d && t.closest("#lbDays")) { toast("Buscando top traders (" + t.dataset.d + " dias)…"); const r = await BB.api("/api/pump/leaderboard", { body: { days: +t.dataset.d } }); toast(r.error ? "Leaderboard: " + r.error : "Leaderboard atualizado: " + (r.count || 0) + " traders"); poll(true); return; }
    if (t.dataset.goto) { $("menu").hidden = true; location.hash = t.dataset.goto; return; }
    const a = t.dataset.act; if (!a) return;
    if (a === "w") return wallet(t.dataset.a, t.dataset.w);
    if (a === "u-block") { const blk = t.dataset.v === "1", u = USERS.find((x) => x.user_id === t.dataset.uid) || {};
      if (!confirm((blk ? "Bloquear " : "Desbloquear ") + (u.email || "este usuário") + "?" + (blk ? "\n\nA conta para de copiar na hora, a execução real dele desliga e ele não consegue mais entrar no painel." : ""))) return;
      return adminUser(t.dataset.uid, { bloqueado: blk }); }
    if (a === "u-realoff") { if (!confirm("Desligar a execução REAL deste usuário agora?")) return; return adminUser(t.dataset.uid, { real_off: true }, "Execução real do usuário desligada."); }
    if (a === "u-audit") { $("aAudUser").value = t.dataset.uid; loadAAudit(); $("tAAudit").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (a === "addw") return wallet("add", $("addW").value);
    if (a === "close") { if (!confirm(t.dataset.real === "1" ? "VENDER de verdade esta posição REAL agora (100%)?" : "Fechar esta posição fictícia agora no preço atual?")) return; const r = await BB.api("/api/pump/close", { body: { id: t.dataset.id } }); toast(r.error || r.msg || "Fechada."); return poll(true); }
    if (a === "reset") { if (!confirm("Zerar a carteira fictícia? Apaga posições e histórico simulados.")) return; await BB.api("/api/pump/reset", { body: {} }); toast("Carteira fictícia zerada."); return poll(true); }
    if (a === "swap") return swap(t);
    if (a === "swapmax") { $("cvU").value = Math.floor(((W && W.usdc) || 0) * 100) / 100; return conv("u"); }
    if (a === "secret-save") {
      const k = t.dataset.k, inp = document.querySelector('[data-secret="' + k + '"]'), v = (inp.value || "").trim(); if (!v) { toast("Cole a chave no campo primeiro."); return; }
      t.disabled = true; const r = await BB.api("/api/secrets", { body: { name: k, value: v } }); inp.value = ""; t.disabled = false;
      toast(r.error ? "Não salvou: " + r.error : "Chave salva (criptografada)." + (r.count != null ? " " + r.count + " top traders carregados." : "") + (r.address ? " Carteira " + shortW(r.address) : ""));
      loadSecrets(); loadAudit(); poll(true); walletLoad(true); return;
    }
    if (a === "syskey-save") {
      const k = t.dataset.k, inp = document.querySelector('[data-syskey="' + k + '"]'), v = (inp.value || "").trim(); if (!v) { toast("Cole a chave no campo primeiro."); return; }
      t.disabled = true; const r = await BB.api("/api/admin/keys", { body: { name: k, value: v } }); inp.value = ""; t.disabled = false;
      toast(r.error ? "Não salvou: " + r.error : "Chave do sistema salva (criptografada). Quem não tem chave própria já usa ela para visualizar.");
      loadSysKeys(); loadAdmin(); loadAAudit(); poll(true); return;
    }
    if (a === "syskey-del") { if (!confirm("Remover esta chave do sistema? Quem não tem chave própria deixa de ver o que depende dela.")) return; const r = await BB.api("/api/admin/keys/remove", { body: { name: t.dataset.k } }); toast(r.error || "Chave do sistema removida."); loadSysKeys(); loadAdmin(); loadAAudit(); poll(true); return; }
    if (a === "secret-del") { if (!confirm("Remover esta chave? Ela será apagada do banco.")) return; const r = await BB.api("/api/secrets/remove", { body: { name: t.dataset.k } }); toast(r.error || "Chave removida."); loadSecrets(); loadAudit(); poll(true); return; }
  });
  document.addEventListener("change", (ev) => {
    const el = ev.target; if (!el.dataset) return;
    if (el.dataset.cfg) setCfg({ [el.dataset.cfg]: +el.value });
    if (el.dataset.urole) { const u = USERS.find((x) => x.user_id === el.dataset.urole) || {}, role = el.value;
      if (!confirm("Mudar " + (u.email || "este usuário") + " para " + (role === "admin" ? "ADMIN (vê o status geral, logs e gerencia usuários)" : "USUÁRIO comum") + "?")) { el.value = u.role; return; }
      adminUser(el.dataset.urole, { role: role }); }
    if (el.id === "aAudUser") loadAAudit();
  });

  // ------------------------------------------------------------------ início
  async function boot() {
    document.querySelectorAll("[data-logo]").forEach((e) => (e.innerHTML = BB.logo));
    let s;
    try { s = await BB.session(); } catch (e) { $("boot").textContent = e.message || String(e); return; }
    if (!s) { location.href = "/"; return; }
    if (location.search) history.replaceState(null, "", location.pathname + location.hash);
    ME = await BB.api("/api/me");
    if (ME.error) { $("boot").textContent = ME.error; return; }
    $("boot").hidden = true; $("shell").hidden = false;
    $("ver").textContent = "versão " + ME.version;
    $("mName").textContent = ME.nome || "Sua conta"; $("mMail").textContent = ME.email || ""; $("mRole").textContent = ME.role === "admin" ? "administrador" : "usuário";
    const av = $("avatarB"); av.innerHTML = ME.avatar ? '<img alt="" referrerpolicy="no-referrer" src="' + esc(ME.avatar) + '">' : esc((ME.nome || ME.email || "?").slice(0, 1).toUpperCase());
    $("kbdHint").textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Ctrl K";
    av.onclick = (e) => { e.stopPropagation(); $("menu").hidden = !$("menu").hidden; };
    document.addEventListener("click", (e) => { if (!e.target.closest("#menu")) $("menu").hidden = true; });
    $("logoutB").onclick = BB.logout;
    $("burger").onclick = () => { $("side").classList.add("open"); $("scrim").classList.add("open"); };
    // computador: botão no topo do menu recolhe para só ícones (fica lembrado neste navegador)
    document.querySelectorAll("#nav a").forEach((a) => { a.title = a.textContent.trim().replace(/NOVO$/, "").replace(/\d+$/, "").trim(); });
    const setMini = (on) => {
      $("shell").classList.toggle("mini", on);
      $("sideTgl").title = $("sideTgl").ariaLabel = on ? "Abrir o menu" : "Recolher o menu";
      try { localStorage.setItem("pf_menu_mini", on ? "1" : "0"); } catch (e) { /* sem armazenamento: só não lembra */ }
    };
    let mini = false;
    try { mini = localStorage.getItem("pf_menu_mini") === "1"; } catch (e) { mini = false; }
    setMini(mini);
    $("sideTgl").onclick = () => setMini(!$("shell").classList.contains("mini"));
    $("scrim").onclick = closeDrawer;
    $("ntfB").onclick = () => { NTF = !NTF; try { localStorage.setItem("ntf", NTF ? "1" : "0"); } catch (e) { /* */ } ntfBtn(); if (NTF) { play("buy", 0.4); try { if (window.Notification && Notification.permission === "default") Notification.requestPermission(); } catch (e) { /* */ } } toast("Notificações " + (NTF ? "LIGADAS" : "DESLIGADAS")); };
    ntfBtn();
    $("realB").onclick = realToggle;
    $("navAdmin").hidden = ME.role !== "admin";
    $("navNov").hidden = ME.role !== "admin";
    $("navGrp").hidden = ME.role !== "admin";
    $("aFind").oninput = renderUsers;
    $("logQ").oninput = () => { clearTimeout(window.__lq); window.__lq = setTimeout(logsReset, 400); };
    $("logLv").onclick = (e) => { const b = e.target.closest("button[data-lv]"); if (b) { LOG_LV = b.dataset.lv; logsReset(); } };
    $("logLive").onclick = () => { LOG_LIVE = !LOG_LIVE; $("logLive").textContent = "Ao vivo: " + (LOG_LIVE ? "ON" : "OFF"); $("logLive").className = "btn sm tgl " + (LOG_LIVE ? "on" : "off"); };
    $("cvU").oninput = () => conv("u"); $("cvS").oninput = () => conv("s");
    $("searchBtn").onclick = ckOpen; $("searchBtn").onkeydown = (e) => { if (e.key === "Enter") ckOpen(); };
    $("cmdk").onclick = (e) => { if (e.target.id === "cmdk") ckClose(); const li = e.target.closest("li[data-i]"); if (li) ckGo(+li.dataset.i); };
    $("cmdkIn").oninput = (e) => ckFill(e.target.value);
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("cmdk").hidden ? ckOpen() : ckClose(); return; }
      if ($("cmdk").hidden) return;
      if (e.key === "Escape") ckClose(); else if (e.key === "ArrowDown") { CKI = Math.min(CK.length - 1, CKI + 1); ckDraw(); e.preventDefault(); } else if (e.key === "ArrowUp") { CKI = Math.max(0, CKI - 1); ckDraw(); e.preventDefault(); } else if (e.key === "Enter") ckGo(CKI);
    });
  // menu "Usar ou descartar" (0.17.2): agrupa o que é novo e ainda em teste; abre/fecha e lembra a escolha
  const grpOpen = (on) => { $("navGrp").classList.toggle("fechado", !on); $("navGrpH").setAttribute("aria-expanded", on ? "true" : "false"); };
  try { grpOpen(localStorage.getItem("pf_menu_grp") !== "0"); } catch (e) { /* */ }
  $("navGrpH").addEventListener("click", () => { const on = $("navGrp").classList.contains("fechado"); grpOpen(on); try { localStorage.setItem("pf_menu_grp", on ? "1" : "0"); } catch (e) { /* */ } });
    $("addW").onkeydown = (e) => { if (e.key === "Enter") wallet("add", $("addW").value); };
    window.addEventListener("hashchange", route);
    window.addEventListener("resize", () => { if (VIEW === "visao" && D) renderOverview(); });
    route();
    await poll(true);
    walletLoad(false);
    setInterval(() => poll(false), 2000);
    setInterval(() => walletLoad(false), 20000);
    setInterval(() => { if (VIEW === "admin" && LOG_LIVE) loadLogs(); }, 4000);
    setInterval(() => { if (VIEW === "admin") { loadUsers(); loadAdmin(); } }, 30000);
  }
  boot();
})();
