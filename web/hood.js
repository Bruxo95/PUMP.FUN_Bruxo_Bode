// 0.32.208 (pedido do dono, 04/11): painel da Robinhood Chain, isolado da pump.fun e da BNB (página /hood, arquivo próprio,
// rotas /api/hood). Etapa 1: só lê a rede e monta o ranking dos traders de memecoin pela regra do Top traders.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = { visao: ["Visão geral", "a sua cópia e o que a Robinhood Chain está negociando agora"], posicoes: ["Posições", "o que a cópia tem aberto agora"],
    historico: ["Histórico", "posições fechadas da cópia"], carteira: ["Carteira", "cópia FICTÍCIA, carteira REAL e segurança do token"],
    traders: ["Top traders", "ranking dos traders de memecoin e a regra"] };
  // 0.32.279 (pedido do dono, 10/11: "faz 1 a 4"): cópia FICTÍCIA em ETH, conferência do token e carteira REAL (desligada)
  const CF_INFO = [
    ["eth_por_compra", "ETH por compra", "ETH", 0.0005, 5, 0.001], ["max_abertas", "Posições abertas no máximo", "posições", 1, 100, 1],
    ["max_hold_h", "Tempo máximo da posição", "h", 0.1, 168, 0.5], ["stop_pct", "Stop de perda (0 = desligado)", "%", 0, 100, 1],
    ["slip_pct", "Folga de preço simulada (slippage)", "%", 0, 50, 0.5], ["gas_eth", "Gás simulado por transação", "ETH", 0, 0.01, 0.00001],
    ["saldo_inicial", "Saldo inicial fictício", "ETH", 0.001, 1000, 0.1],
  ];
  const RL_INFO = [
    ["real_eth_por_compra", "ETH por compra na REAL", "ETH", 0.0002, 0.5, 0.0005], ["real_max_abertas", "Posições REAL abertas no máximo", "posições", 1, 30, 1],
    ["real_slip_pct", "Folga de preço na REAL (slippage)", "%", 1, 49, 1], ["real_perda_dia", "Perda do dia que para a REAL", "ETH", 0.0005, 5, 0.001],
  ];
  let P = null, REAL = false, PBUSY = false, CF_DIRTY = false, RL_DIRTY = false;
  try { REAL = localStorage.getItem("hood_mode") === "real"; } catch (e) { /* */ }
  const RK_INFO = [
    ["min_trades", "Trades mínimos no período", "trades", 0, 100000, 1], ["min_winrate", "Acerto acima de", "%", 0, 100, 1],
    ["min_closed", "Tokens fechados mínimos (para medir o acerto)", "tokens", 1, 1000, 1],
    ["min_wallet_usd", "Saldo mínimo da carteira (ETH + WETH + USDG)", "US$", 0, 10000000, 100],
    ["online_min", "Online = negociou nos últimos", "min", 1, 1440, 1], ["top_n", "Quantos copiaria", "carteiras", 1, 50, 1],
    ["bot_per_day", "Robô = mais trades por dia que", "trades/dia", 10, 100000, 10],
  ];
  let VIEW = "visao", R = null, BUSY = false, READY = false, DIRTY = false, TRT = "rank";
  try { TRT = localStorage.getItem("hood_trt") || "rank"; } catch (e) { /* */ }

  // ------------------------------------------------------------------ formatos
  const num = (v, d) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: d == null ? 4 : d }));
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
  const eth = (v, d) => (v == null ? "—" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : "") + num(v, d == null ? 4 : d) + " ETH</span>");
  const hora = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
  function ago(t) {
    if (!t) return "—";
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : s < 86400 ? (s / 3600).toFixed(1).replace(".", ",") + " h" : (s / 86400).toFixed(1).replace(".", ",") + " dias";
  }
  const ex = () => (R && R.explorer) || "https://robinhoodchain.blockscout.com";
  const short = (a) => (a ? a.slice(0, 6) + "…" + a.slice(-4) : "—");
  const addr = (a) => (a ? '<a class="hdaddr" href="' + esc(ex()) + "/address/" + esc(a) + '" target="_blank" rel="noopener">' + esc(short(a)) + "</a>" : "—");
  const tok = (a) => (a ? '<a class="hdaddr" href="https://dexscreener.com/robinhood/' + esc(a) + '" target="_blank" rel="noopener">' + esc(short(a)) + "</a>" : "—");
  const txl = (h) => (h ? '<a class="hdaddr" href="' + esc(ex()) + "/tx/" + esc(h) + '" target="_blank" rel="noopener">' + esc(h.slice(0, 10)) + "…</a>" : "—");
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

  // ------------------------------------------------------------------ monitor (menu da esquerda)
  function sysInfo() {
    const s = (R && R.status) || {};
    const erro = s.ultimo_erro && s.ultimo_erro_t && Date.now() / 1000 - s.ultimo_erro_t < 120;
    const parado = !s.ultimo_trade_t || Date.now() / 1000 - s.ultimo_trade_t > 600;
    const atraso = s.atraso_s != null && s.atraso_s > 120;
    const ok = !!(R && R.ligado && !erro && !parado && !atraso);
    return { s, ok, probs: [erro && "erro na leitura", parado && "sem trade lido há mais de 10 min", atraso && "leitura atrasada", s.pausa_s && "RPC pediu para esperar (" + s.pausa_s + " s)"].filter(Boolean) };
  }
  function drawSys() {
    const i = sysInfo(), s = i.s;
    $("sysDot").className = "dot " + (i.ok ? "on" : "off");
    $("sysT").textContent = !R ? "Monitor…" : !R.ligado ? "Monitor OFF" : i.ok ? "Monitor ON" : "Monitor com problema";
    $("sysS").textContent = !R ? "conectando" : !R.ligado ? "leitura desligada" : i.ok ? "último trade há " + ago(s.ultimo_trade_t) + " · atraso " + num(s.atraso_s, 0) + " s" : i.probs.join(" · ");
    if (!$("sysM").hidden) drawSysModal();
  }
  function drawSysModal() {
    const i = sysInfo(), s = i.s, rk = (R && R.ranking) || {};
    const rows = [
      ["Leitura", R && R.ligado ? (i.ok ? '<span class="up">funcionando</span>' : '<span class="down">' + esc(i.probs.join(" · ") || "com problema") + "</span>") : '<span class="down">desligada</span>'],
      ["RPC grátis (revezando)", (s.rpcs || []).map((x) => esc(x.rpc) + " " + (x.pausa_s ? '<span class="down">descansando ' + x.pausa_s + " s</span>" : '<span class="up">ok</span>') +
        " · " + num((s.por_rpc || {})[x.rpc], 0) + " consultas").join("<br>") + "<br>" + num(s.chamadas, 0) + " consultas desde " + hora(s.desde) + (s.limite_429 ? " · " + num(s.limite_429, 0) + " vezes um deles pediu para esperar" : "")],
      ["Bloco", num(s.bloco, 0) + " · lido até " + num(s.lido_ate, 0) + " · atraso " + (s.atraso_s == null ? "—" : num(s.atraso_s, 1) + " s")],
      ["Último trade lido", ago(s.ultimo_trade_t) + " · " + hora(s.ultimo_trade_t)],
      ["Trocas lidas", num(s.trocas, 0) + " · viraram trade: " + num((s.trocas || 0) - (s.fora_rota || 0) - (s.fora_outro || 0), 0) + " · rota com vários pools: " + num(s.fora_rota, 0) + " · sem trader ou memecoin claro: " + num(s.fora_outro, 0)],
      ["Últimas 24 h", num(s.trades_24h, 0) + " trades · " + num(s.compras_24h, 0) + " compras · " + num(s.carteiras_24h, 0) + " carteiras · " + num(s.tokens_24h, 0) + " tokens"],
      ["Pago em (24 h)", Object.entries(s.moedas_24h || {}).map((x) => esc(x[0] === "USD" ? "USDG" : x[0]) + " " + num(x[1], 0)).join(" · ") || "—"],
      ["Ranking", num(rk.aptos, 0) + " aptos · " + num((rk.copiaria || []).length, 0) + " copiando agora"],
      ["ETH em dólar", s.eth_usd ? "US$ " + num(s.eth_usd, 2) + " (DexScreener)" : "—"],
      ["Memória", num(s.trades_memoria, 0) + " trades (últimas 24 h) · " + num(s.roteadores, 0) + " roteadores vistos"],
      ["Banco da VPS", !s.arquivo ? '<span class="down">desligado: o ranking zera quando o site atualiza</span>'
        : (s.arquivo_erro ? '<span class="down">' + esc(s.arquivo_erro) + "</span> · " : '<span class="up">guardando</span> · ') +
          num(s.salvos, 0) + " trades guardados desde a subida · " + num(s.do_arquivo, 0) + " voltaram na subida" + (s.arquivo_fila ? " · " + num(s.arquivo_fila, 0) + " na fila" : "")],
      ["Erros", num(s.erros, 0) + (s.ultimo_erro ? " · último há " + ago(s.ultimo_erro_t) + ": " + esc(s.ultimo_erro) : "")],
      ["Última volta da leitura", s.volta_t ? "há " + ago(s.volta_t) : "—"],
    ];
    $("sysMB").innerHTML = '<div class="tbl-wrap"><table class="systbl nocard"><tbody>' + rows.map((r) => "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>").join("") + "</tbody></table></div>";
  }

  // ------------------------------------------------------------------ telas
  function drawVisao() {
    const s = (R && R.status) || {};
    kpis("ovK", [["Trades na última hora", num(s.trades_1h, 0), "compras e vendas de memecoin", "tr"],
      ["Trades em 24 h", num(s.trades_24h, 0), num(s.compras_24h, 0) + " compras", "tr"],
      ["Carteiras em 24 h", num(s.carteiras_24h, 0), num(s.tokens_24h, 0) + " tokens", "usr"],
      ["ETH movimentado em 24 h", num(s.eth_24h, 2) + " ETH", s.eth_usd ? "≈ US$ " + num((s.eth_24h || 0) * s.eth_usd, 0) : "", "mon"]]);
    table("ovTk", ["Token", "Trades (1 h)"], ((R && R.tokens_1h) || []).map((x) => [tok(x.token), num(x.trades, 0)]), "Nenhum trade na última hora ainda.");
    table("ovTr", ["Hora", "Lado", "Token", "Carteira", "ETH", "Pago em", "Transação"], ((R && R.recentes) || []).map((t) => [hora(t.t),
      t.side === "buy" ? '<span class="tag buy">compra</span>' : '<span class="tag loss">venda</span>', tok(t.token), addr(t.wallet), num(t.eth, 5),
      esc(t.quote === "USD" ? "USDG" : t.quote), txl(t.tx)]), "A leitura começou agora: os trades aparecem em alguns segundos.");
    const i = sysInfo();
    $("ovSt").innerHTML = R && R.ligado ? (i.ok ? '<span class="up">Lendo a rede normalmente.</span> ' : '<span class="down">' + esc(i.probs.join(" · ")) + ".</span> ") +
      "Último bloco " + num(s.bloco, 0) + ", lido até " + num(s.lido_ate, 0) + " (atraso " + (s.atraso_s == null ? "—" : num(s.atraso_s, 0) + " s") + "). " +
      "Desde o início: " + num(s.trocas, 0) + " trocas lidas, " + num(s.fora_rota, 0) + " de rotas com vários pools e " + num(s.fora_outro, 0) + " sem trader ou memecoin claro ficaram de fora."
      : '<span class="down">' + esc((R && R.motivo) || "A leitura da Robinhood Chain está desligada no servidor.") + "</span>";
  }
  function drawTraders() {
    document.querySelectorAll("#trTab button").forEach((b) => b.classList.toggle("on", b.dataset.trt === TRT));
    $("trRank").hidden = TRT !== "rank"; $("trAj").hidden = TRT !== "aj";
    const rk = (R && R.ranking) || {}, rows = rk.rows || [];
    const row = (r, i) => [String(i + 1), addr(r.wallet), eth(r.realized_eth), num(r.vol_eth, 3) + " ETH", num(r.trades, 0), r.winrate == null ? "—" : num(r.winrate, 0) + "% (" + r.closed + ")",
      r.wallet_usd == null ? "—" : "US$ " + num(r.wallet_usd, 0), "há " + ago(r.last_t),
      r.copiaria ? '<span class="tag win">copiando</span>' : r.eligible ? '<span class="tag neutral">' + (r.online ? "apto" : "apto · fora (inativo)") + "</span>"
        : '<span class="muted small">' + esc((r.flags || []).join(" · ")) + "</span>"];
    const H = ["#", "Carteira", "Lucro realizado", "Volume", "Trades", "Acerto", "Saldo", "Último trade", "Situação"];
    $("hdRkSub").textContent = num(rk.carteiras, 0) + " carteiras negociaram nas últimas 24 h · os 50 que mais lucraram · " + num(rk.aptos, 0) + " aptos";
    table("hdSel", H, rows.filter((r) => r.copiaria).map(row), "Nenhum trader apto e online agora. O ranking enche com as horas de leitura.");
    table("hdRk", H, rows.map(row), "O ranking enche com as horas de leitura.");
    if (!DIRTY && R && R.cfg) {
      const c = R.cfg, p = R.padrao || {};
      $("hdCfg").innerHTML = RK_INFO.map((x) => '<div class="field"><label for="hd_' + x[0] + '">' + esc(x[1]) + '</label><div class="row"><input class="in w80" id="hd_' + x[0] +
        '" type="number" min="' + x[3] + '" max="' + x[4] + '" step="' + x[5] + '" value="' + esc(c[x[0]]) + '"><span class="muted">' + esc(x[2]) +
        (p[x[0]] !== c[x[0]] ? " · padrão " + esc(p[x[0]]) : "") + "</span></div></div>").join("");
    }
  }
  // ------------------------------------------------------------------ cópia (0.32.279)
  function toast(msg) {
    let el = $("hdToast");
    if (!el) { el = document.createElement("div"); el.id = "hdToast"; el.className = "hdtoast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
    el.textContent = msg; el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, 2600);
  }
  const dur = (s) => (s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : s < 86400 ? (s / 3600).toFixed(1).replace(".", ",") + " h" : (s / 86400).toFixed(1).replace(".", ",") + " dias");
  const mtag = () => (REAL ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>');
  const pct = (v) => (v == null ? "—" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : "") + num(v, 1) + "%</span>");
  function fieldHtml(pre, info, c, p) {
    return info.map((x) => '<div class="field"><label for="' + pre + x[0] + '">' + esc(x[1]) + '</label><div class="row"><input class="in w120" id="' + pre + x[0] +
      '" type="number" min="' + x[3] + '" max="' + x[4] + '" step="' + x[5] + '" value="' + esc(c[x[0]]) + '"><span class="muted">' + esc(x[2]) +
      (p && p[x[0]] !== c[x[0]] ? " · padrão " + esc(p[x[0]]) : "") + "</span></div></div>").join("");
  }
  function drawMy() {
    const w = (P && P.carteira) || {}, pr = (w.periodos || []);
    if (REAL) {
      kpis("myK", [["Saldo da carteira " + mtag(), w.saldo == null ? "—" : num(w.saldo, 5) + " ETH", w.endereco ? short(w.endereco) : "sem chave salva", "mon"],
        ["Resultado " + mtag(), eth(w.resultado, 5), pct(w.resultado_pct) + " do que entrou", "tr"],
        ["Posições abertas", num(w.abertas, 0), num(w.fechadas, 0) + " fechadas", "tr"],
        ["Acerto", w.acerto == null ? "—" : num(w.acerto, 0) + "%", "posições fechadas com lucro", "usr"]]);
    } else {
      kpis("myK", [["Saldo " + mtag(), num(w.saldo, 5) + " ETH", "começou com " + num(w.inicial, 4) + " ETH", "mon"],
        ["Resultado " + mtag(), eth(w.resultado, 5), pct(w.resultado_pct) + " sobre o inicial", "tr"],
        ["Posições abertas", num(w.abertas, 0), num(w.em_posicoes, 5) + " ETH nelas", "tr"],
        ["Acerto", w.acerto == null ? "—" : num(w.acerto, 0) + "%", num(w.fechadas, 0) + " fechadas", "usr"]]);
    }
    kpis("myP", pr.map((x) => ["Últimas " + x.h + " h", eth(x.pnl, 5), x.n ? x.n + " fechadas · " + x.ganhos + " com lucro · " + x.traders + " traders" : "nenhuma fechada", "tr"]));
    table("ovEv", ["Hora", "O que fez", "Token", "Trader", "Motivo"], ((P && P.eventos) || []).slice(0, 80).map((e) => [hora(e.t),
      /não|falhou/.test(e.acao) ? '<span class="tag loss">' + esc(e.acao) + "</span>" : /comprou|copiou/.test(e.acao) ? '<span class="tag buy">' + esc(e.acao) + "</span>" : '<span class="tag neutral">' + esc(e.acao) + "</span>",
      tok(e.token), addr(e.wallet), esc(e.motivo || "") + (e.tx ? " · " + txl(e.tx) : "")]),
    REAL ? "Nada ainda. A REAL só age depois de ligada em Carteira." : "Nada ainda. Assim que um trader do \"Copiando agora\" comprar, aparece aqui.");
  }
  function drawPos() {
    const ps = (P && P.posicoes) || [];
    $("poT").innerHTML = "Posições abertas " + mtag();
    $("poSub").textContent = ps.length + " abertas · " + ((P && P.carteira && P.carteira.fechadas) || 0) + " fechadas";
    $("poAll").hidden = !ps.length;
    table("poTb", ["Aberta", "Token", "Trader", "Entrou", "Agora", "Resultado", "Pico", "Fecha em", ""], ps.map((p) => [
      hora(p.open_t) + '<br><small class="muted">há ' + ago(p.open_t) + " · " + num(p.lag_s, 0) + " s depois do trader</small>",
      tok(p.token), addr(p.wallet), num(p.eth_in, 5) + " ETH" + (p.vendas && p.vendas.length ? '<br><small class="muted">' + p.vendas.length + " vendas parciais</small>" : ""),
      pct(p.pnl_pct) + '<br><small class="muted">preço de ' + (p.px_t ? "há " + ago(p.px_t) : "—") + "</small>",
      eth(p.pnl_eth, 5), pct(p.best_pct) + ' <small class="muted">pior ' + num(p.worst_pct, 1) + "%</small>",
      p.fecha_em > Date.now() / 1000 ? "em " + dur(p.fecha_em - Date.now() / 1000) : "agora",
      (p.sell_error ? '<small class="down">' + esc(p.sell_error) + "</small><br>" : "") + '<button class="btn sm" data-close="' + esc(p.id) + '"' + (p.selling ? " disabled" : "") + ">" + (p.selling ? "Vendendo…" : "Vender") + "</button>"]),
    REAL ? "Nenhuma posição REAL aberta." : "Nenhuma posição aberta. A cópia compra quando um trader do \"Copiando agora\" comprar.");
  }
  function drawHist() {
    const ts = (P && P.trades) || [], w = (P && P.carteira) || {};
    const pn = ts.reduce((a, x) => a + (x.pnl_eth || 0), 0), win = ts.filter((x) => x.pnl_eth > 0).length;
    kpis("hiK", [["Fechadas " + mtag(), num(ts.length, 0), win + " com lucro", "tr"], ["Resultado das fechadas", eth(pn, 5), "", "tr"],
      ["Acerto", ts.length ? num(100 * win / ts.length, 0) + "%" : "—", "", "usr"], ["Realizado (tudo)", eth(w.realizado, 5), "", "mon"]]);
    table("hiTb", ["Fechou", "Token", "Trader", "Entrou", "Saiu", "Resultado", "Pico", "Motivo"], ts.slice(0, 300).map((x) => [hora(x.close_t) + '<br><small class="muted">ficou ' + dur(x.close_t - x.open_t) + "</small>",
      tok(x.token), addr(x.wallet), num(x.eth_in, 5) + " ETH", num(x.eth_out, 5) + " ETH", eth(x.pnl_eth, 5) + "<br>" + pct(x.pnl_pct), pct(x.best_pct),
      esc(x.motivo || "") + (x.tx_out ? " · " + txl(x.tx_out) : "")]), REAL ? "Nenhuma posição REAL fechada ainda." : "Nenhuma posição fechada ainda.");
  }
  function drawCarteira() {
    if (!P) return;
    const c = P.cfg_sim || {}, rc = P.real_cfg || {}, st = P.real_status || {};
    const on = $("cfOn"); on.classList.toggle("on", !!c.on); on.textContent = c.on ? "Ligada" : "Desligada"; on.setAttribute("aria-checked", c.on ? "true" : "false");
    const ro = $("rlOn"); ro.classList.toggle("on", !!st.ligada); ro.textContent = st.ligada ? "Ligada" : "Desligada"; ro.setAttribute("aria-checked", st.ligada ? "true" : "false");
    if (!CF_DIRTY) $("cfF").innerHTML = fieldHtml("cf_", CF_INFO, c, P.padrao);
    if (!RL_DIRTY) $("rlF").innerHTML = fieldHtml("rl_", RL_INFO, rc, P.real_padrao);
    $("rlSt").innerHTML = [
      "Trava geral do servidor: " + (st.permitido ? '<span class="up">aberta</span>' : '<span class="down">fechada (PUMP_REAL_ALLOWED): nada é enviado</span>'),
      "Chave: " + (st.chave ? '<span class="up">salva</span> · carteira ' + addr(st.endereco) : '<span class="muted">não salva</span>'),
      "Saldo: " + (st.saldo == null ? "—" : num(st.saldo, 5) + " ETH"),
      "REAL: " + (st.ligada ? '<span class="up">ligada</span> desde ' + hora(st.desde) : '<span class="down">desligada</span>'),
    ].join("<br>");
    const sf = P.seguranca || {}, s = sf.stat || {}, cp = sf.copia || {}, rg = sf.regras || {};
    kpis("sfK", [["Compras vistas", num(cp.compras_vistas, 0), "dos traders do \"Copiando agora\"", "tr"], ["Copiadas", num(cp.copiadas, 0), "token aprovado", "tr"],
      ["Barradas", num(cp.barradas, 0), num(cp.sem_pool, 0) + " sem pool de ETH na V4", "tr"],
      ["GoPlus", num(s.goplus_com_dados, 0) + " com dados", num(s.goplus_sem_dados, 0) + " sem dados desta rede", "usr"]]);
    table("sfT", ["Hora", "Token", "Veredito", "Ida e volta", "GoPlus"], (sf.recentes || []).map((x) => [hora(x.t), tok(x.token),
      x.ok ? '<span class="tag win">aprovado</span>' : '<span class="tag loss">' + (x.erro ? "sem conferência" : "barrado") + "</span> " + esc(x.why || ""),
      x.ida_volta_pct == null ? "—" : num(x.ida_volta_pct, 1) + "% (máx. " + num(rg.ida_volta_max_pct, 0) + "%)", esc(x.goplus || "—")]),
    "Nenhum token conferido ainda: a conferência roda na primeira compra de um trader do \"Copiando agora\".");
  }
  function draw() {
    drawSys();
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.mode === "real") === REAL));
    if (VIEW === "visao") { drawMy(); drawVisao(); }
    if (VIEW === "posicoes") drawPos();
    if (VIEW === "historico") drawHist();
    if (VIEW === "carteira") drawCarteira();
    if (VIEW === "traders") drawTraders();
  }

  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try {
      const [r, p] = await Promise.all([BB.api("/api/hood", { quiet: true }), BB.api("/api/hood/painel" + (REAL ? "?real=1" : ""), { quiet: true })]);
      if (r && !r.error) R = r;
      if (p && !p.error && p.ligado !== false) P = p;
      draw();
    } catch (e) { /* tenta de novo na próxima volta */ } finally { BUSY = false; }
  }
  function route() {
    const v = (location.hash || "#visao").slice(1);
    VIEW = TITLES[v] ? v : "visao";
    document.querySelectorAll(".view").forEach((s) => (s.hidden = s.dataset.view !== VIEW));
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === VIEW));
    document.querySelectorAll("#tabbar [data-tv]").forEach((a) => a.classList.toggle("on", a.dataset.tv === VIEW));
    $("pgTitle").textContent = TITLES[VIEW][0]; $("pgSub").textContent = TITLES[VIEW][1];
    closeDrawer();
    window.scrollTo(0, 0);
    draw();
    load();
  }
  const openDrawer = () => { $("side").classList.add("open"); $("scrim").classList.add("open"); };
  const closeDrawer = () => { $("side").classList.remove("open"); $("scrim").classList.remove("open"); };

  // ------------------------------------------------------------------ ações
  document.addEventListener("input", (e) => {
    const t = e.target && e.target.closest ? e.target : null; if (!t) return;
    if (t.closest("#hdCfg")) DIRTY = true;
    if (t.closest("#cfF")) CF_DIRTY = true;
    if (t.closest("#rlF")) RL_DIRTY = true;
  });
  const vals = (pre, info) => { const b = {}; info.forEach((x) => { const el = $(pre + x[0]); if (el && el.value !== "") b[x[0]] = Number(el.value); }); return b; };
  async function post(url, body, btn) {
    if (btn) btn.disabled = true;
    try { return await BB.api(url, { body }); } finally { if (btn) btn.disabled = false; }
  }
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target.closest("button,a") : null; if (!t) return;
    if (t.dataset.mode) { REAL = t.dataset.mode === "real"; try { localStorage.setItem("hood_mode", REAL ? "real" : "sim"); } catch (x) { /* */ } P = null; draw(); load(); return; }
    if (t.dataset.close) {
      if (REAL && !confirm("Vender esta posição na carteira REAL agora?")) return;
      const r = await post("/api/hood/fechar", { id: t.dataset.close, real: REAL }, t);
      if (r && r.error) alert(r.error); else toast("Vendida.");
      return load();
    }
    if (t.id === "poAll") {
      let body = { real: REAL };
      if (REAL) { const w = prompt("Vender TODAS as posições REAL agora? Digite VENDER"); if (!w) return; body.confirm = w; }
      else if (!confirm("Vender todas as posições fictícias?")) return;
      const r = await post("/api/hood/fechar-todas", body, t);
      if (r && r.error) alert(r.error); else toast(r.vendidas + " vendidas" + (r.falhas ? ", " + r.falhas + " falharam" : "") + ".");
      return load();
    }
    if (t.id === "cfOn") { const r = await post("/api/hood/conta", { on: !(P && P.cfg_sim && P.cfg_sim.on) }, t); if (r && r.error) alert(r.error); return load(); }
    if (t.id === "cfReset") { CF_DIRTY = true; const p = (P && P.padrao) || {}; CF_INFO.forEach((x) => { if ($("cf_" + x[0])) $("cf_" + x[0]).value = p[x[0]]; }); return; }
    if (t.id === "cfSave") { const r = await post("/api/hood/conta", vals("cf_", CF_INFO), t); if (r && r.error) { alert(r.error); return; } CF_DIRTY = false; toast("Salvo."); return load(); }
    if (t.id === "rlSave") { const r = await post("/api/hood/real/cfg", vals("rl_", RL_INFO), t); if (r && r.error) { alert(r.error); return; } RL_DIRTY = false; toast("Salvo."); return load(); }
    if (t.id === "rlKeySave") {
      const v = $("rlKey").value.trim(); if (!v) return;
      const r = await post("/api/hood/chave", { value: v }, t);
      $("rlKey").value = "";
      if (r && r.error) alert(r.error); else toast("Chave salva · carteira " + short(r.endereco));
      return load();
    }
    if (t.id === "rlKeyDel") {
      if (!confirm("Remover a chave da carteira da Robinhood? A REAL desliga.")) return;
      const r = await post("/api/hood/chave/remover", {}, t); if (r && r.error) alert(r.error); return load();
    }
    if (t.id === "rlOn") {
      if (P && P.real_status && P.real_status.ligada) {
        const r = await post("/api/hood/real", { on: false }, t); if (r && r.error) alert(r.error); else toast("REAL desligada."); return load();
      }
      $("rlAsk").hidden = false; $("rlWord").value = ""; $("rlWord").focus(); return;
    }
    if (t.id === "rlNo") { $("rlAsk").hidden = true; return; }
    if (t.id === "rlGo") {
      const r = await post("/api/hood/real", { on: true, confirm: $("rlWord").value }, t);
      if (r && r.error) { alert(r.error); return; }
      $("rlAsk").hidden = true; toast("REAL ligada."); return load();
    }
    if (t.dataset.trt) { TRT = t.dataset.trt; try { localStorage.setItem("hood_trt", TRT); } catch (x) { /* */ } draw(); return; }
    if (t.id === "sysBox") { $("sysM").hidden = false; drawSysModal(); return; }
    if (t.id === "sysMX") { $("sysM").hidden = true; return; }
    if (t.id === "hdReset") { DIRTY = false; const p = (R && R.padrao) || {}; RK_INFO.forEach((x) => { if ($("hd_" + x[0])) $("hd_" + x[0]).value = p[x[0]]; }); DIRTY = true; return; }
    if (t.id === "hdSave") {
      const body = {}; RK_INFO.forEach((x) => { const el = $("hd_" + x[0]); if (el && el.value !== "") body[x[0]] = Number(el.value); });
      t.disabled = true;
      const r = await BB.api("/api/hood/cfg", { body });
      t.disabled = false;
      if (r && r.error) { alert(r.error); return; }
      DIRTY = false; t.textContent = "Salvo"; setTimeout(() => { t.textContent = "Salvar regra"; }, 2000);
      await load();
    }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("sysM").hidden = true; });
  $("sysM").addEventListener("click", (e) => { if (e.target === $("sysM")) $("sysM").hidden = true; });

  async function boot() {
    $("boot").innerHTML = BB.loader("Carregando", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
    $("hdOut").addEventListener("click", BB.logout);
    $("burger").addEventListener("click", openDrawer);
    $("tbMenu").addEventListener("click", openDrawer);
    $("scrim").addEventListener("click", closeDrawer);
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão: volta ao início */ }
    if (!s) { location.href = "/"; return; }
    const me = await BB.api("/api/me", { quiet: true });
    if (me.error || me.role !== "admin" || me.view_by) { location.replace("/app"); return; }      // a Robinhood é só do admin
    try { sessionStorage.setItem("pf_hub", "hood"); } catch (e) { /* */ }
    $("ver").textContent = "versão " + String(me.version || "").split(" · ")[0];
    $("boot").hidden = true; $("shell").hidden = false;
    READY = true;
    route();
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", load);
  boot();
  setInterval(load, 10000);
})();
