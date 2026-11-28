// 0.32.208 (pedido do dono, 04/11): painel da Robinhood Chain, isolado da pump.fun e da BNB (página /hood, arquivo próprio,
// rotas /api/hood). Etapa 1: só lê a rede e monta o ranking dos traders de memecoin pela regra do Top traders.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = { visao: ["Visão geral", "a sua cópia e o que a Robinhood Chain está negociando agora"], posicoes: ["Posições", "o que a cópia tem aberto agora"],
    historico: ["Histórico", "posições fechadas da cópia"], carteira: ["Carteira", "cópia FICTÍCIA, carteira REAL e segurança do token"],
    traders: ["Top traders", "ranking dos traders de memecoin e a regra"],
    fluxo: ["Dinheiro entrando", "as 30 moedas que mais recebem dinheiro agora"], admin: ["Administração", "usuários e a situação de cada conta na Robinhood"] };
  // 0.32.279 (pedido do dono, 10/11: "faz 1 a 4"): cópia FICTÍCIA em ETH, conferência do token e carteira REAL (desligada)
  const CF_INFO = [
    ["eth_por_compra", "ETH por compra", "ETH", 0.0001, 5, 0.0001], ["max_abertas", "Posições abertas no máximo", "posições", 1, 100, 1],
    ["max_hold_h", "Tempo máximo da posição", "h", 0.1, 168, 0.5], ["stop_pct", "Stop de perda (0 = desligado)", "%", 0, 100, 1],
    ["slip_pct", "Folga de preço simulada (slippage)", "%", 0, 50, 0.5], ["gas_eth", "Gás simulado por transação", "ETH", 0, 0.01, 0.00001],
    ["saldo_inicial", "Saldo inicial fictício", "ETH", 0.001, 1000, 0.1],
    ["trail_ativa_pct", "Stop móvel liga com lucro de", "%", 1, 10000, 1], ["trail_dist_pct", "Stop móvel sai ao cair do pico", "pontos", 1, 1000, 1],
    ["max_acima_pct", "Não entrar se o preço já subiu mais que", "%", 0, 500, 1], ["max_atraso_s", "Atraso máximo para copiar", "s", 5, 90, 1],
    ["sg_fixo_pct", "Nível do stop de ganho (0 = o robô escolhe)", "%", 0, 500, 1],
  ];
  const RL_INFO = [
    ["real_eth_por_compra", "ETH por compra na REAL", "ETH", 0.0001, 0.5, 0.0001], ["real_max_abertas", "Posições REAL abertas no máximo", "posições", 1, 100, 1],
    ["real_slip_pct", "Folga de preço na REAL (slippage)", "%", 1, 49, 1], ["real_perda_dia", "Perda do dia que para a REAL", "ETH", 0.0005, 5, 0.001],
    ["real_max_hold_h", "Tempo máximo da posição REAL", "h", 0.1, 168, 0.5], ["real_stop_pct", "Stop de perda da REAL (0 = desligado)", "%", 0, 100, 1],
    ["real_trail_ativa_pct", "Stop móvel da REAL liga com lucro de", "%", 1, 10000, 1], ["real_trail_dist_pct", "Stop móvel da REAL sai ao cair do pico", "pontos", 1, 1000, 1],
  ];
  // 0.32.290 (pedido do dono: "sair quando o desenvolvedor sai da moeda ... stop móvel ... botão de ativar"): opções liga/desliga
  const CF_BOOL = ["copia_traders", "sair_travado", "so_verificado", "so_lp_presa", "sair_liquidez", "um_por_token", "sair_trader", "trader_so_lucro", "sair_dev", "trail_on", "pausa_trader", "sg_on"], RL_BOOL = ["real_sg_on", "real_sair_travado", "real_espelho", "real_so_lp_presa", "real_sair_liquidez", "real_um_por_token", "real_sair_trader", "real_trader_so_lucro", "real_sair_dev", "real_trail_on"];
  const NOM = {};
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
  // 0.32.285 (pedido do dono): cada carteira ganha um apelido e um ícone de pixels (o mesmo desenho "blockie" que os exploradores
  // de blockchain mostram, gerado da própria carteira). Os dois saem do endereço: a mesma carteira tem sempre o mesmo nome e ícone.
  const NICK_A = ["Lobo", "Raposa", "Tubarão", "Falcão", "Coruja", "Pantera", "Touro", "Urso", "Baleia", "Polvo", "Tigre", "Leão", "Corvo",
    "Águia", "Cobra", "Lince", "Jaguar", "Dragão", "Fênix", "Golfinho", "Escorpião", "Gavião", "Puma", "Rinoceronte", "Bisão", "Camaleão",
    "Morcego", "Lagarto", "Coiote", "Hiena", "Abutre", "Javali", "Texugo", "Furão", "Arraia", "Piranha", "Mamute", "Gorila", "Leopardo", "Condor"];
  const NICK_B = ["Veloz", "Feroz", "Audaz", "Sagaz", "Voraz", "Tenaz", "Ágil", "Hábil", "Leal", "Rebelde", "Selvagem", "Brilhante",
    "Gigante", "Elegante", "Valente", "Paciente", "Ardente", "Potente", "Polar", "Estelar", "Nuclear", "Radical", "Tropical", "Glacial",
    "Imortal", "Lunar", "Solar", "Turbo", "Neon", "Ninja", "Pirata", "Samurai", "Viking", "Fantasma", "Rubi", "Safira", "Diamante",
    "Platina", "Bronze", "Alfa"];       // só palavras que servem para os dois gêneros (Raposa Veloz, Lobo Veloz)
  const NICK = {}, BKY = {};
  function nick(a) {
    a = String(a || "").toLowerCase();
    if (!NICK[a]) {
      let h = 2166136261;
      for (let i = 0; i < a.length; i++) { h ^= a.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
      NICK[a] = NICK_A[h % NICK_A.length] + " " + NICK_B[Math.floor(h / NICK_A.length) % NICK_B.length];
    }
    return NICK[a];
  }
  function blockie(a) {               // algoritmo dos "blockies" do Ethereum: 8×8 espelhado, 3 cores
    a = String(a || "").toLowerCase();
    if (BKY[a]) return BKY[a];
    const rs = [0, 0, 0, 0];
    for (let i = 0; i < a.length; i++) rs[i % 4] = ((rs[i % 4] << 5) - rs[i % 4] + a.charCodeAt(i)) | 0;
    const rand = () => { const t = rs[0] ^ (rs[0] << 11); rs[0] = rs[1]; rs[1] = rs[2]; rs[2] = rs[3]; rs[3] = rs[3] ^ (rs[3] >> 19) ^ t ^ (t >> 8); return (rs[3] >>> 0) / ((1 << 31) >>> 0); };
    const col = () => "hsl(" + Math.floor(rand() * 360) + "," + (rand() * 60 + 40) + "%," + (rand() + rand() + rand() + rand()) * 25 + "%)";
    const c1 = col(), bg = col(), sp = col();
    const cv = document.createElement("canvas"); cv.width = cv.height = 8;
    const g = cv.getContext("2d");
    if (!g) return "";
    g.fillStyle = bg; g.fillRect(0, 0, 8, 8);
    for (let y = 0; y < 8; y++) {
      const row = [0, 1, 2, 3].map(() => Math.floor(rand() * 2.3));
      row.concat(row.slice().reverse()).forEach((v, x) => { if (v) { g.fillStyle = v === 1 ? c1 : sp; g.fillRect(x, y, 1, 1); } });
    }
    return (BKY[a] = cv.toDataURL());
  }
  const ORIG = { botao: "Botão Comprar", cacador: "Caçador", "cacador-a": "Caçador A", "cacador-b": "Caçador B", "cacador-c": "Caçador C" };
  const addr = (a) => (ORIG[a] ? '<span class="tag neutral">' + ORIG[a] + "</span>" : a ? '<a class="hdwho" href="' + esc(ex()) + "/address/" + esc(a) + '" target="_blank" rel="noopener" title="' + esc(a) + '"><img class="bky" alt="" src="' + blockie(a) +
    '"><span><b>' + esc(nick(a)) + '</b><small class="hdaddr">' + esc(short(a)) + "</small></span></a>" : "—");
  // 0.32.290 (pedido do dono: "no token coloque o nome e endereço que nem você fez para os traders"): ícone, símbolo e endereço curto
  // 0.32.314 (pedido do dono): token em que o criador pode travar a venda aparece com o nome em amarelo, em todas as telas
  let RISCO = {};
  const tok = (a, o) => {
    if (!a) return "—";
    const rk = RISCO[a];
    const m = (o && (o.simbolo || o.nome)) ? o : (NOM[a] || {});
    const sym = m.simbolo || m.nome || "", nm = m.nome && m.nome !== sym ? m.nome : "";
    return '<a class="hdwho" href="https://dexscreener.com/robinhood/' + esc(a) + '" target="_blank" rel="noopener" title="' + esc((rk ? "⚠ " + rk + " · " : "") + (nm ? nm + " · " : "") + a) + '"><img class="bky" alt="" src="' + blockie(a) +
      '"><span><b' + (rk ? ' class="risk"' : "") + ">" + (rk ? "⚠ " : "") + esc(sym || short(a)) + "</b>" + (sym ? '<small class="hdaddr" style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px">' + esc((nm ? (nm.length > 14 ? nm.slice(0, 13) + "…" : nm) + " · " : "") + short(a)) + "</small>" : "") + "</span></a>";
  };
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
    const erro = s.ultimo_erro && s.ultimo_erro_t && Date.now() / 1000 - s.ultimo_erro_t < 120 && s.ultimo_erro_t > (s.leitura_ok_t || 0);
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
      ["Erros da leitura", num(s.erros, 0) + (s.ultimo_erro ? " · último há " + ago(s.ultimo_erro_t) + ": " + esc(s.ultimo_erro) : "") + (s.leitura_ok_t ? " · última volta boa há " + ago(s.leitura_ok_t) : "")],
      ["Outros avisos", s.outro_erro ? "há " + ago(s.outro_erro_t) + ": " + esc(s.outro_erro) + ' <small class="muted">(não para a leitura)</small>' : "—"],
      ["RPC que descansou", num(s.pausas, 0) + " vezes (demorou ou falhou 2 vezes seguidas: 1 min de descanso, os outros seguem lendo)"],
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
  function drawBlocked(all, blk) {
    const byW = {}; all.forEach((r) => { byW[r.wallet] = r; });
    const dz = all.filter((r) => (r.perigo || []).length).map((r) => r.wallet);
    const ws = Array.from(new Set(dz.concat(Array.from(blk))));
    $("trBlB").textContent = "Bloqueados" + (ws.length ? " (" + ws.length + ")" : "");
    $("blSub").textContent = dz.length + " PERIGO · " + blk.size + " bloqueados por você · nunca são copiados";
    const man = new Set(((P && P.cfg_sim && P.cfg_sim.manual) || []));
    table("blT", ["Carteira", "Por quê", "Lucro realizado", "Trades", "Último trade", ""], ws.map((w) => {
      const r = byW[w] || {}, pg = r.perigo || [];
      return [addr(w),
        (pg.length ? '<span class="tag loss dzt">PERIGO · ' + (pg.some((x) => /honeypot/.test(x)) ? "honeypot" : "robô") + '</span><br><small class="down">' + esc(pg.join(" · ")) + "</small>" : "") +
          (blk.has(w) ? (pg.length ? "<br>" : "") + '<span class="tag neutral">bloqueado por você</span>' : "") + (man.has(w) ? '<br><small class="muted">estava na sua lista: não copia mais</small>' : ""),
        r.realized_eth == null ? "—" : eth(r.realized_eth), r.trades == null ? "—" : num(r.trades, 0), r.last_t ? "há " + ago(r.last_t) : '<span class="muted">fora do top 50 agora</span>',
        blk.has(w) ? '<button class="btn sm" data-block="' + esc(w) + '" data-on="0">Desbloquear</button>' : '<span class="muted small">automático</span>'];
    }), "Nenhum trader bloqueado.");
  }
  // 0.32.497 (pedido do dono: "tira o top traders do Caçador e joga esse toggle para dentro de Top traders")
  function drawTrCopia() {
    const box = $("trCopia"), c = (P && P.cfg_sim) || null; if (!box) return;
    if (!c) { box.hidden = true; return; }
    box.hidden = false;
    const on = c.copia_traders !== false;
    box.innerHTML = '<span><b>Copiar os top traders na FICTÍCIA</b><small>' + (on ? "ligado: quando um trader do Copiando agora (ou um que você escolheu) compra, a carteira FICTÍCIA compra junto. São as fechadas \"Cópia de traders\" do Histórico."
      : "desligado: a FICTÍCIA não copia os traders; compra só pelo Caçador e pelo botão Comprar da lista Moedas.") + " A REAL tem as regras dela (Carteira).</small></span>" +
      '<button class="btn tgl sw ' + (on ? "on" : "off") + '" type="button" role="switch" aria-checked="' + on + '" data-czk="copia_traders">' + (on ? "Ligado" : "Desligado") + "</button>";
  }
  function drawTraders() {
    drawTrCopia();
    document.querySelectorAll("#trTab button").forEach((b) => b.classList.toggle("on", b.dataset.trt === TRT));
    $("trRank").hidden = TRT !== "rank"; $("trAj").hidden = TRT !== "aj"; $("trBl").hidden = TRT !== "bl";
    const rk = (R && R.ranking) || {}, all = rk.rows || [];
    // 0.32.302 (pedido do dono): bloqueados por você e PERIGO saem do ranking e vão para a aba Bloqueados
    const blk = new Set(((P && P.cfg_sim && P.cfg_sim.bloqueados) || []));
    const isOut = (r) => blk.has(r.wallet) || (r.perigo || []).length;
    const rows = all.filter((r) => !isOut(r));
    drawBlocked(all, blk);
    const man = new Set(((P && P.cfg_sim && P.cfg_sim.manual) || []));
    const autoOn = !(P && P.cfg_sim && P.cfg_sim.auto_top === false);
    // 0.32.287 (pedido do dono): 3 botões por trader: copiar só na FICTÍCIA, só na REAL ou nas 2
    const modo = (P && P.cfg_sim && P.cfg_sim.modo) || {};
    const MODO_TXT = { sim: "FICTÍCIA", real: "REAL", ambas: "As 2" };
    const btn = (r) => {
      const cur = man.has(r.wallet) ? (modo[r.wallet] || "ambas") : null;
      if ((r.perigo || []).length) {               // 0.32.295 (pedido do dono): trader PERIGO com os botões cinza e travados (o servidor também recusa)
        const tt = "Não dá para copiar: " + r.perigo.join(" · ");
        return '<span class="hdmodes">' + ["sim", "real", "ambas"].map((m) => '<button class="btn sm dz" type="button" disabled title="' + esc(tt) + '">' + MODO_TXT[m] + "</button>").join("") +
          (cur ? '<button class="btn sm" data-follow="' + esc(r.wallet) + '" data-on="0" title="Parar de copiar este trader">Parar</button>' : "") + "</span>";
      }
      const why = r.eligible ? "" : " (fora da regra: " + (r.flags || []).join(" · ") + ")";
      return '<span class="hdmodes">' + ["sim", "real", "ambas"].map((m) => '<button class="btn sm' + (cur === m ? " on" : "") + '" data-follow="' + esc(r.wallet) + '" data-on="' + (cur === m ? "0" : "1") +
        '" data-modo="' + m + '" title="' + esc(cur === m ? "Parar de copiar este trader" : "Copiar " + (m === "ambas" ? "na FICTÍCIA e na REAL" : "só na " + MODO_TXT[m]) + why) + '">' + MODO_TXT[m] + "</button>").join("") +
        (cur ? '<button class="btn sm" data-follow="' + esc(r.wallet) + '" data-on="0" title="Parar de copiar este trader">Parar</button>' : "") +
        '<button class="btn sm blk" data-block="' + esc(r.wallet) + '" data-on="1" title="Bloquear: para de copiar e tira do ranking (vai para a aba Bloqueados)">Bloquear</button>' + "</span>";
    };
    // 0.32.322: o lucro já desconta o token que o trader ainda segura valendo menos da metade do que custou
    const lucro = (r) => eth(r.realized_eth) + (r.bags ? '<br><small class="down">segura ' + r.bags + (r.bags > 1 ? " tokens" : " token") + " no prejuízo: " + num(r.bag_eth, 4) + " ETH</small>" : "");
    const row = (r, i) => [String(i + 1), addr(r.wallet), lucro(r), num(r.vol_eth, 3) + " ETH", num(r.trades, 0), r.winrate == null ? "—" : num(r.winrate, 0) + "% (" + r.closed + ")",
      r.wallet_usd == null ? "—" : "US$ " + num(r.wallet_usd, 0), "há " + ago(r.last_t),
      ((r.perigo || []).length ? '<span class="tag loss dzt" title="' + esc(r.perigo.join(" · ")) + '">PERIGO · ' + esc(r.perigo.some((x) => /honeypot/.test(x)) ? "honeypot" : "robô") + "</span> " +
        (man.has(r.wallet) ? '<span class="tag pause">você ainda copia: a REAL não compra dele</span> ' : "") + '<small class="down">' + esc(r.perigo.join(" · ")) + "</small><br>" : "") +
      (man.has(r.wallet) && !(r.perigo || []).length ? '<span class="tag win">você copia · ' + MODO_TXT[modo[r.wallet] || "ambas"] + "</span> " : "") + (r.copiaria ? '<span class="tag win">copiando</span>' : r.eligible ? '<span class="tag neutral">' + (r.online ? "apto" : "apto · fora (inativo)") + "</span>"
        : '<span class="muted small">' + esc((r.flags || []).join(" · ")) + "</span>"), btn(r)];
    const H = ["#", "Carteira", "Lucro realizado", "Volume", "Trades", "Acerto", "Saldo", "Último trade", "Situação", ""];
    const fora = all.length - rows.length;
    $("hdRkSub").textContent = num(rk.carteiras, 0) + " carteiras negociaram nas últimas 24 h · os 50 que mais lucraram · " + num(rk.aptos, 0) + " aptos" + (fora ? " · " + fora + " na aba Bloqueados" : "");
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
  // 0.32.288 (pedido do dono: "os config estão desalinhados e fora de padrão de palavras"): uma linha por opção, FICTÍCIA e REAL lado a
  // lado, mesmos nomes e mesma ordem. [nome, unidade, chave da FICTÍCIA ou null, chave da REAL ou null, motivo de não ter numa delas]
  const CFG_ROWS = [
    ["ETH por compra", "ETH", "eth_por_compra", "real_eth_por_compra"],
    ["Posições abertas no máximo", "posições", "max_abertas", "real_max_abertas"],
    ["Tempo máximo da posição", "h", "max_hold_h", "real_max_hold_h"],
    ["Stop de perda (0 = desligado)", "%", "stop_pct", "real_stop_pct"],
    // 0.32.332 (pedido do dono, 13/11/2026): stop de ganho autônomo; a REAL que é par da fictícia (espelho) sai junto dela
    ["Stop de ganho autônomo", "vende tudo quando o líquido chega ao nível que o robô escolheu pelo histórico (sem base: +10%) · na REAL vale só para a posição sem par da fictícia", "sg_on", "real_sg_on", "", "bool"],
    ["Nível do stop de ganho", "% líquido (0 = o robô escolhe)", "sg_fixo_pct", null, "a REAL usa o nível da FICTÍCIA"],
    // 0.32.322 (revisão "por que estamos sempre no negativo"): três travas de entrada; a REAL usa o valor da FICTÍCIA
    ["Não entrar se o preço já subiu mais que", "% acima do que o trader pagou, medido no pool na hora (0 = desligado)", "max_acima_pct", null, "a REAL usa o valor da FICTÍCIA"],
    ["Atraso máximo para copiar", "segundos depois da compra do trader; mais que isso não copia", "max_atraso_s", null, "a REAL usa o valor da FICTÍCIA"],
    // 0.32.489 (pedido do Bruxo, áudio de 27/11): desligar a cópia dos top traders na FICTÍCIA (para medir só o Caçador)
    ["Copiar os top traders", "compra quando os traders do ranking ou os escolhidos por você compram · desligado, a FICTÍCIA só compra pelo Caçador e pelo botão (com o espelho, a REAL também para)", "copia_traders", null, "a REAL tem as dela", "bool"],
    ["Parar de copiar trader que dá prejuízo", "no Copiando agora: 3 cópias ou mais em 7 dias somando prejuízo; quem você escolheu no botão continua", "pausa_trader", null, "a REAL usa o valor da FICTÍCIA", "bool"],
    ["Token com trava do criador: sair no lucro", "nome em amarelo; vende assim que ficar positivo (em partes, se o pool não aceitar tudo)", "sair_travado", "real_sair_travado", "", "bool"],
    ["Só token com a liquidez presa", "não compra se uma carteira comum tem metade ou mais da liquidez do pool (pode tirar tudo a qualquer hora, como no TEXEL e no mihao)", "so_lp_presa", "real_so_lp_presa", "", "bool"],
    ["Sair quando o dono tira liquidez", "o dono tirou 30% ou mais da liquidez do pool de uma posição aberta: vende antes de ele tirar o resto", "sair_liquidez", "real_sair_liquidez", "", "bool"],
    ["Só token com contrato verificado", "não compra token cujo código não está publicado no explorador (com o espelho, vale para a REAL também)", "so_verificado", null, "a REAL segue a fictícia", "bool"],
    ["REAL segue a FICTÍCIA (espelho)", "a REAL compra quando a fictícia compra e fecha quando ela fecha", null, "real_espelho", "a FICTÍCIA é a que manda", "bool"],
    ["Uma entrada por token", "não compra de novo um token que já está aberto, mesmo que outro trader compre", "um_por_token", "real_um_por_token", "", "bool"],
    ["Sair quando o trader sai da moeda", "vende tudo quando o saldo dele no token some", "sair_trader", "real_sair_trader", "", "bool"],
    ["Trader saiu: só vende no lucro", "no prejuízo (já com taxas) segura e vende quando ficar positivo · desligado por padrão: segurar o perdedor até o tempo máximo foi a maior causa de prejuízo", "trader_so_lucro", "real_trader_so_lucro", "", "bool"],
    ["Sair quando o dev sai da moeda", "vende tudo quando quem criou o token vende metade ou mais", "sair_dev", "real_sair_dev", "", "bool"],
    ["Stop móvel", "liga no lucro e sai se cair do pico (regra da Solana)", "trail_on", "real_trail_on", "", "bool"],
    ["Stop móvel liga com lucro de", "%", "trail_ativa_pct", "real_trail_ativa_pct"],
    ["Stop móvel sai ao cair do pico", "pontos (trava no mínimo +2%)", "trail_dist_pct", "real_trail_dist_pct"],
    ["Folga de preço (slippage)", "%", "slip_pct", "real_slip_pct"],
    ["Perda do dia que para a cópia", "ETH", null, "real_perda_dia", "só na REAL"],
    ["Gás por transação", "ETH", "gas_eth", null, "na REAL é o gás de verdade"],
    ["Saldo inicial", "ETH", "saldo_inicial", null, "na REAL é o saldo da carteira"],
  ];
  // 0.32.296 (pedido do dono: "conversão direta ... 0,01 ETH = 5 dólares, consultando a cotação real"): cotação do ETH da
  // DexScreener (a mesma do Monitor), conversor ETH ↔ dólar e "≈ US$" ao lado de cada campo em ETH
  const usdRate = () => (P && P.eth_usd) || (R && R.status && R.status.eth_usd) || (FX && FX.eth_usd) || null;
  const usdOf = (e) => { const r = usdRate(); return r && e !== "" && e != null && isFinite(e) ? "≈ US$ " + num(Number(e) * r, Number(e) * r >= 100 ? 0 : 2) : ""; };
  function usdHints() { document.querySelectorAll("[data-usd]").forEach((h) => { const el = $(h.dataset.usd); h.textContent = el ? usdOf(el.value) : ""; }); }
  function drawConv() {
    const r = usdRate();
    if ($("cvRate")) $("cvRate").textContent = r ? "1 ETH = US$ " + num(r, 2) + " · cotação real da DexScreener" : "cotação do ETH ainda não chegou (o conversor liga quando chegar)";
    if ($("cvQuick")) $("cvQuick").innerHTML = [0.001, 0.002, 0.005, 0.01, 0.05, 0.1].map((v) => '<button class="btn sm" type="button" data-cveth="' + v + '">' + num(v, 3) + " ETH" +
      (r ? ' <span class="muted">= US$ ' + num(v * r, v * r >= 100 ? 0 : 2) + "</span>" : "") + "</button>").join("");
    usdHints();
  }
  function conv(from) {
    const r = usdRate(); if (!r || !$("cvEth")) return;
    if (from === "eth") { const v = parseFloat($("cvEth").value); $("cvUsd").value = isFinite(v) ? +(v * r).toFixed(2) : ""; }
    else { const v = parseFloat($("cvUsd").value); $("cvEth").value = isFinite(v) ? +(v / r).toFixed(6) : ""; }
  }
  // 0.32.313 (pedido do dono: "copiar config de outro usuário e na carteira mostrar se tá igual ou diferente", como na Solana).
  // Compara com outro admin, marca cada opção (= igual / ≠ dele), copia só depois de ver a lista e guarda o "desfazer" no navegador.
  let CMP = null, CMP_U = null, CMP_UID = null, CMP_AT = 0, CMP_PLAN = null, CMP_BUSY = false;
  let CMP_TAB = null;                      // 0.32.499 (pedido do dono): clicar no "1 diferente" abre a lista do que está diferente
  try { CMP_UID = localStorage.getItem("hood_cmp") || null; } catch (e) { /* */ }
  const cmpName = () => { const u = (CMP_U || []).find((x) => x.user_id === CMP_UID); return u ? u.nome : "o outro"; };
  const cmpEq = (a, b) => (typeof a === "number" || typeof b === "number" ? Number(a) === Number(b) : !!a === !!b);
  const cmpShow = (v) => (typeof v === "boolean" ? (v ? "Ligado" : "Desligado") : v == null ? "—" : num(v, 6));
  function cmpLabel(k) { const r = CFG_ROWS.find((x) => x[2] === k || x[3] === k); return r ? r[0] : k; }
  function cmpDiffs() {
    if (!CMP || !CMP.sim || !P) return null;
    const c = P.cfg_sim || {}, rc = P.real_cfg || {}, out = { sim: [], real: [] };
    CFG_ROWS.forEach((r) => {
      if (r[2] && r[2] in CMP.sim && !cmpEq(c[r[2]], CMP.sim[r[2]])) out.sim.push({ k: r[2], meu: c[r[2]], dele: CMP.sim[r[2]] });
      if (r[3] && r[3] in CMP.real && !cmpEq(rc[r[3]], CMP.real[r[3]])) out.real.push({ k: r[3], meu: rc[r[3]], dele: CMP.real[r[3]] });
    });
    const mine = new Set(c.manual || []), bl = new Set(c.bloqueados || []), tb = new Set(c.tokens_bloqueados || []);
    out.tr = (CMP.manual || []).filter((w) => !mine.has(w) && !bl.has(w));
    out.comum = (CMP.manual || []).filter((w) => mine.has(w)).length;
    out.bl = (CMP.bloqueados || []).filter((w) => !bl.has(w)).length + (CMP.tokens_bloqueados || []).filter((w) => !tb.has(w)).length;
    return out;
  }
  function cmpChip(pre, key, mine) {
    if (!CMP || !CMP.sim || !key) return "";
    const src = pre === "cf_" ? CMP.sim : CMP.real;
    if (!(key in src)) return "";
    return cmpEq(mine, src[key]) ? '<span class="cmpeq" title="igual ao de ' + esc(cmpName()) + '">= igual</span>'
      : '<span class="cmpne" title="valor de ' + esc(cmpName()) + '">≠ ' + esc(cmpName().split(" ")[0]) + ": " + esc(cmpShow(src[key])) + "</span>";
  }
  async function loadCmp(force) {
    if (CMP_BUSY || (!force && CMP && Date.now() - CMP_AT < 60000)) return;
    CMP_BUSY = true;
    try {
      if (!CMP_U || force) {
        const u = await BB.api("/api/hood/config/usuarios", { quiet: true });
        CMP_U = (u && u.users) || [];
        if (!CMP_UID || !CMP_U.some((x) => x.user_id === CMP_UID)) {
          const b = CMP_U.find((x) => x.tem_conta && /bruxo/i.test(x.nome)) || CMP_U.find((x) => x.tem_conta);
          CMP_UID = b ? b.user_id : null;
        }
      }
      if (CMP_UID) {
        const r = await BB.api("/api/hood/config/peer?uid=" + encodeURIComponent(CMP_UID), { quiet: true });
        CMP = r && r.ok ? r : { error: (r && r.error) || "não carregou" };
      } else CMP = null;
      CMP_AT = Date.now();
    } finally { CMP_BUSY = false; }
    drawCmp(); cmpRows();
  }
  function cmpRows() {
    if (!P || CF_DIRTY || RL_DIRTY || document.activeElement.closest("#cfRows")) return;
    $("cfRows").innerHTML = cfgRows(P.cfg_sim || {}, P.real_cfg || {}); usdHints();
  }
  function cmpUndo() { try { return JSON.parse(localStorage.getItem("hood_cmpundo") || "null"); } catch (e) { return null; } }
  function drawCmp() {
    const box = $("cmpBox"); if (!box) return;
    if (!CMP_U) { box.innerHTML = '<p class="muted">Carregando…</p>'; return; }
    const opts = CMP_U.map((u) => '<option value="' + esc(u.user_id) + '"' + (u.user_id === CMP_UID ? " selected" : "") + (u.tem_conta ? "" : " disabled") + ">" +
      esc(u.nome) + (u.email ? " · " + esc(u.email) : "") + (u.tem_conta ? "" : " (ainda não abriu a Robinhood)") + "</option>").join("");
    let h = '<div class="row cmpsel"><label for="cmpSel">Comparar com</label><select class="in" id="cmpSel">' + (opts || '<option value="">Nenhum outro admin</option>') + "</select></div>";
    const u = cmpUndo();
    const undo = u ? '<button class="btn sm" id="cmpUndo" type="button" title="Volta os valores de antes da última cópia (de ' + esc(u.de) + ')">Desfazer a cópia de ' + esc(u.de) + "</button>" : "";
    if (!CMP_UID || !CMP) { box.innerHTML = h + '<p class="muted">Escolha um usuário que já abriu a Robinhood.</p>' + undo; return; }
    if (CMP.error) { box.innerHTML = h + '<p class="down">' + esc(CMP.error) + "</p>" + undo; return; }
    const d = cmpDiffs(), n = cmpName();
    if (!d) { box.innerHTML = h; return; }
    const mineTr = (P.cfg_sim || {}).manual || [], soEu = mineTr.filter((w) => !(CMP.manual || []).includes(w));
    const st = (k, lst) => '<div class="cmpst"><button type="button" class="' + (CMP_TAB === k ? "on" : "") + '" data-cmptab="' + k + '" title="Ver o que está diferente"><span class="tag ' + k + '">' + (k === "sim" ? "FICTÍCIA" : "REAL") + "</span> " +
      (lst.length ? '<b class="cmpne">' + lst.length + " diferente" + (lst.length > 1 ? "s" : "") + "</b>" : '<b class="cmpeq">100% igual</b>') + " <i>" + (CMP_TAB === k ? "▲" : "▼") + "</i></button></div>";
    h += '<div class="cmpsts">' + st("sim", d.sim) + st("real", d.real) +
      '<div class="cmpst"><button type="button" class="' + (CMP_TAB === "tr" ? "on" : "") + '" data-cmptab="tr" title="Ver os traders de cada um">Traders: você copia ' + mineTr.length + ", " + esc(n) + " copia " + (CMP.manual || []).length + " · " + d.comum + " em comum <i>" + (CMP_TAB === "tr" ? "▲" : "▼") + "</i></button></div></div>";
    const all = d.sim.map((x) => ["sim", x]).concat(d.real.map((x) => ["real", x]));
    if (CMP_TAB === "sim" || CMP_TAB === "real") {
      const L = CMP_TAB === "sim" ? d.sim : d.real;
      h += '<div class="cmpdet"><b>' + (CMP_TAB === "sim" ? "FICTÍCIA" : "REAL") + ": o que está diferente da de " + esc(n) + "</b>" +
        (L.length ? '<div class="tbl-wrap"><table><thead><tr><th>Opção</th><th>Sua</th><th>De ' + esc(n) + "</th><th></th></tr></thead><tbody>" +
          L.map((x) => "<tr><td>" + esc(cmpLabel(x.k)) + '</td><td class="muted">' + esc(cmpShow(x.meu)) + "</td><td><b>" + esc(cmpShow(x.dele)) + '</b></td><td><button class="btn sm" type="button" data-cmpone="' + esc(x.k) + '">Copiar só esta</button></td></tr>').join("") + "</tbody></table></div>"
          : '<p class="muted">Tudo igual: nenhuma opção ' + (CMP_TAB === "sim" ? "da FICTÍCIA" : "da REAL") + " está diferente.</p>") + "</div>";
    } else if (CMP_TAB === "tr") {
      const lst = (ws, vazio) => (ws.length ? '<div class="cmplist">' + ws.slice(0, 60).map((w) => "<div>" + addr(w) + "</div>").join("") + (ws.length > 60 ? '<div class="muted">e mais ' + (ws.length - 60) + "</div>" : "") + "</div>" : '<p class="muted">' + vazio + "</p>");
      h += '<div class="cmpdet"><b>Só ' + esc(n) + " copia (" + d.tr.length + ")</b>" + lst(d.tr, "nenhum") + "<b>Só você copia (" + soEu.length + ")</b>" + lst(soEu, "nenhum") + "</div>";
    }
    h += '<div class="cmpver"><span class="muted">Toda cópia e toda mudança ficam guardadas como uma versão: dá para voltar a qualquer uma no</span><a class="btn sm" href="#carteira" data-goversao="1">Histórico da configuração ↓</a></div>';
    const btn = (k, txt, off) => '<button class="btn sm' + (k === "all" ? " primary" : "") + '" type="button" data-cmpgo="' + k + '"' + (off ? " disabled" : "") + ">" + txt + "</button>";
    h += '<div class="row cmpbtns">' + btn("all", "Ficar igual a " + esc(n) + " (FICTÍCIA e REAL)", !all.length) + btn("sim", "Só a FICTÍCIA", !d.sim.length) + btn("real", "Só a REAL", !d.real.length) +
      btn("tr", "Copiar os traders de " + esc(n) + (d.tr.length ? " (+" + d.tr.length + ")" : ""), !d.tr.length) + btn("bl", "Juntar os bloqueios" + (d.bl ? " (+" + d.bl + ")" : ""), !d.bl) + undo + "</div>";
    if (CMP_PLAN) {
      h += '<div class="hdask cmpask"><b>Vai mudar na sua conta:</b><ul>' + CMP_PLAN.linhas.map((l) => "<li>" + l + "</li>").join("") + '</ul><p class="muted">A carteira REAL não liga nem desliga e o saldo não muda. Dá para desfazer depois.</p>' +
        '<div class="row"><button class="btn primary" id="cmpOk" type="button">Confirmar</button><button class="btn sm" id="cmpNo" type="button">Cancelar</button></div></div>';
    }
    box.innerHTML = h;
  }
  function cmpPlan(kind) {
    const d = cmpDiffs(); if (!d) return;
    const n = cmpName(), linhas = [], plan = { kind, keys: [], traders: kind === "tr", bloqueios: kind === "bl", linhas };
    const take = (w, lst) => lst.forEach((x) => { plan.keys.push(x.k); linhas.push('<span class="tag ' + w + '">' + (w === "sim" ? "FICT." : "REAL") + "</span> " + esc(cmpLabel(x.k)) + ": " + esc(cmpShow(x.meu)) + " → <b>" + esc(cmpShow(x.dele)) + "</b>"); });
    if (kind.startsWith("one:")) {                 // 0.32.499: copiar só uma opção, a partir da lista de diferenças
      const k = kind.slice(4);
      take(d.sim.some((x) => x.k === k) ? "sim" : "real", d.sim.concat(d.real).filter((x) => x.k === k));
    }
    if (kind === "all" || kind === "sim") take("sim", d.sim);
    if (kind === "all" || kind === "real") take("real", d.real);
    if (kind === "tr") linhas.push("Começa a copiar " + d.tr.length + " trader" + (d.tr.length > 1 ? "s" : "") + " que " + esc(n) + " copia (no mesmo modo FICTÍCIA/REAL dele; os que você bloqueou ficam de fora)");
    if (kind === "bl") linhas.push("Soma " + d.bl + " bloqueio" + (d.bl > 1 ? "s" : "") + " de " + esc(n) + " (traders e moedas) aos seus");
    CMP_PLAN = plan; drawCmp();
  }
  async function cmpApply(btn) {
    const pl = CMP_PLAN; if (!pl || !P) return;
    const c = P.cfg_sim || {}, rc = P.real_cfg || {}, u = { de: cmpName(), sim: {}, real: {} };
    pl.keys.forEach((k) => { if (k in (CMP.sim || {})) u.sim[k] = c[k]; else u.real[k] = rc[k]; });
    if (pl.traders) { u.sim.manual = c.manual || []; u.sim.modo = c.modo || {}; }
    if (pl.bloqueios) { u.sim.bloqueados = c.bloqueados || []; u.sim.tokens_bloqueados = c.tokens_bloqueados || []; }
    const r = await post("/api/hood/config/copiar", { uid: CMP_UID, keys: pl.keys, traders: pl.traders, bloqueios: pl.bloqueios }, btn);
    if (!r || r.error) { alert((r && r.error) || "Não copiou."); return; }
    try { localStorage.setItem("hood_cmpundo", JSON.stringify(u)); } catch (e) { /* */ }
    P.cfg_sim = r.cfg; P.real_cfg = r.real_cfg; CF_DIRTY = RL_DIRTY = false; CMP_PLAN = null;
    drawCmp(); cmpRows(); toast("Salvo.");
  }
  // 0.32.319 (pedido do dono: "as configurações ficam salvas e eu posso voltar para o que era antes", como no PUMP FUN Solana):
  // cada mudança vira uma versão; "Voltar a esta" põe a configuração como estava nela. Ligar a REAL e a fictícia nunca muda.
  let HIST = null, HIST_AT = 0, HIST_ALL = false;
  async function loadHist(force) {
    if (!force && HIST && Date.now() - HIST_AT < 30000) return;
    HIST_AT = Date.now();
    const r = await BB.api("/api/hood/config/historico", { quiet: true });
    HIST = r && r.ok ? r : { error: (r && r.error) || "não carregou" };
    drawHist();
  }
  const hLbl = (k) => ({ manual: "Traders copiados", modo: "Modo de cada trader (FICTÍCIA/REAL/ambas)", bloqueados: "Traders bloqueados", tokens_bloqueados: "Moedas bloqueadas", auto_top: "Copiar o ranking sozinho" }[k] || cmpLabel(k));
  const hSide = (k) => (k.startsWith("real_") ? '<span class="tag real">REAL</span> ' : ["manual", "modo", "bloqueados", "tokens_bloqueados"].includes(k) ? "" : '<span class="tag sim">FICT.</span> ');
  function hChange(m) {
    const v = m.lista ? [(m.entrou ? "+" + m.entrou : ""), (m.saiu ? "−" + m.saiu : "")].filter(Boolean).join(" ") + ' <span class="muted">(' + m.de + " → " + m.para + ")</span>"
      : '<span class="muted">' + esc(cmpShow(m.de)) + "</span> → <b>" + esc(cmpShow(m.para)) + "</b>";
    return "<li>" + hSide(m.k) + esc(hLbl(m.k)) + ": " + v + "</li>";
  }
  function drawHist() {
    const box = $("hiBox"); if (!box) return;
    if (!HIST) { box.innerHTML = '<p class="muted">Carregando…</p>'; return; }
    if (HIST.error) { box.innerHTML = '<p class="down">' + esc(HIST.error) + "</p>"; return; }
    const vs = HIST.versoes || [];
    if (!vs.length) { box.innerHTML = '<p class="muted">Nenhuma mudança guardada ainda. A partir de agora, cada mudança na configuração vira uma versão aqui.</p>'; return; }
    const show = HIST_ALL ? vs : vs.slice(0, 12);
    box.innerHTML = '<div class="hilist">' + show.map((v) => {
      const atual = v.n === HIST.atual_n, ch = v.mudou || [];
      return '<div class="hiv' + (atual ? " atual" : "") + '"><div class="hih"><b>Versão ' + v.n + "</b> <span class=\"muted\">" + esc(hora(Date.parse(v.em) / 1000)) + " · " + esc(v.origem || "") + "</span>" +
        (atual ? ' <span class="tag win">atual</span>' : ' <button class="btn sm" type="button" data-hback="' + v.n + '">Voltar a esta</button>') + "</div>" +
        (ch.length ? "<ul>" + ch.slice(0, 12).map(hChange).join("") + (ch.length > 12 ? '<li class="muted">e mais ' + (ch.length - 12) + "</li>" : "") + "</ul>" : '<p class="muted small">como a configuração estava antes das mudanças guardadas</p>') + "</div>";
    }).join("") + "</div>" + (vs.length > 12 ? '<button class="btn sm" type="button" id="hiAll">' + (HIST_ALL ? "Mostrar só as 12 últimas" : "Mostrar todas (" + vs.length + ")") + "</button>" : "");
  }
  async function hBack(n, btn) {
    if (!confirm("Voltar a configuração da cópia para como estava na versão " + n + "?\n\nA FICTÍCIA e a REAL não são ligadas nem desligadas e o saldo não muda. Dá para voltar de novo depois.")) return;
    const r = await post("/api/hood/config/voltar", { n }, btn);
    if (!r || r.error) { alert((r && r.error) || "não voltou"); return; }
    HIST = r; HIST_AT = Date.now(); drawHist();
    CF_DIRTY = RL_DIRTY = false;
    toast(r.mudou ? "Voltou " + r.mudou + " opções para a versão " + n + "." : "Já estava igual à versão " + n + ".");
    await load();
  }
  async function cmpDoUndo(btn) {
    const u = cmpUndo(); if (!u) return;
    if (Object.keys(u.sim || {}).length) { const r = await post("/api/hood/conta", u.sim, btn); if (r && r.error) { alert(r.error); return; } if (P && r && r.cfg) P.cfg_sim = r.cfg; }
    if (Object.keys(u.real || {}).length) { const r = await post("/api/hood/real/cfg", u.real, btn); if (r && r.error) { alert(r.error); return; } if (P && r && r.cfg) P.real_cfg = r.cfg; }
    try { localStorage.removeItem("hood_cmpundo"); } catch (e) { /* */ }
    CF_DIRTY = RL_DIRTY = false; drawCmp(); cmpRows(); toast("Salvo.");
  }
  function cfgCell(pre, key, info, c, p, na, kind, unit) {
    const col = pre === "cf_" ? " cf-sim" : " cf-real";
    if (!key) return '<div class="cfc na' + col + '">' + esc(na || "—") + "</div>";
    if (kind === "bool") {
      const v = !!c[key];
      return '<div class="cfc' + col + '"><button class="btn tgl sw ' + (v ? "on" : "off") + '" id="' + pre + key + '" type="button" role="switch" data-bool="1" aria-checked="' + v + '">' +
        (v ? "Ligado" : "Desligado") + "</button>" + (p && p[key] !== c[key] ? '<span class="muted">padrão ' + (p[key] ? "ligado" : "desligado") + "</span>" : "") + cmpChip(pre, key, c[key]) + "</div>";
    }
    const x = info.find((i) => i[0] === key) || [key, "", "", 0, 1e9, "any"];
    return '<div class="cfc' + col + '"><input class="in" id="' + pre + key + '" type="number" min="' + x[3] + '" max="' + x[4] + '" step="' + x[5] + '" value="' + esc(c[key]) +
      '" aria-label="' + esc(x[1]) + '">' + (unit === "ETH" ? '<span class="usdh" data-usd="' + pre + key + '">' + esc(usdOf(c[key])) + "</span>" : "") +
      (p && p[key] !== c[key] ? '<span class="muted">padrão ' + esc(p[key]) + "</span>" : "") + cmpChip(pre, key, c[key]) + "</div>";
  }
  // 0.32.315 (pedido do dono, 11/11: fictícia fechando tudo em segundos com "stop de 1%"): o resultado já desconta a folga e a taxa na
  // entrada e na saída, então um stop menor que esse custo dispara no primeiro trade, mesmo com o preço parado
  function stopWarn(c, rc) {
    const w = [];
    const ida = (s) => 2 * (Number(s) || 0) + 0.5;
    if (c.stop_pct > 0 && c.stop_pct < ida(c.slip_pct)) w.push("FICTÍCIA: " + num(c.stop_pct, 1) + "% é menor que o custo de entrar e sair (~" + num(ida(c.slip_pct), 1) + "% com folga de " + num(c.slip_pct, 1) + "%): fecha logo depois de comprar");
    if (rc.real_stop_pct > 0 && rc.real_stop_pct < ida(rc.real_slip_pct)) w.push("REAL: " + num(rc.real_stop_pct, 1) + "% é menor que o custo estimado de entrar e sair (~" + num(ida(rc.real_slip_pct), 1) + "%)");
    return w.length ? '<small class="down">' + esc(w.join(" · ")) + "</small>" : "";
  }
  function cfgRows(c, rc) {
    return CFG_ROWS.map((r) => '<div class="cfl">' + esc(r[0]) + "<small>" + esc(r[1]) + "</small>" + (r[2] === "stop_pct" ? stopWarn(c, rc) : "") + "</div>" +
      cfgCell("cf_", r[2], CF_INFO, c, P.padrao, r[4], r[5], r[1]) + cfgCell("rl_", r[3], RL_INFO, rc, P.real_padrao, r[4], r[5], r[1])).join("");
  }
  function fieldHtml(pre, info, c, p) {
    return info.map((x) => '<div class="field"><label for="' + pre + x[0] + '">' + esc(x[1]) + '</label><div class="row"><input class="in w120" id="' + pre + x[0] +
      '" type="number" min="' + x[3] + '" max="' + x[4] + '" step="' + x[5] + '" value="' + esc(c[x[0]]) + '"><span class="muted">' + esc(x[2]) +
      (p && p[x[0]] !== c[x[0]] ? " · padrão " + esc(p[x[0]]) : "") + "</span></div></div>").join("");
  }
  // 0.32.302 (pedido do dono): o valor em dólar junto do ETH, pelo preço do ETH que a leitura já usa (DexScreener)
  const usdL = (v, sinal = true) => { const u = usdOf(v); return u ? '<span class="usdl">' + (!sinal ? u : v > 0 ? u.replace("US$ ", "+US$ ") : v < 0 ? u.replace("US$ ", "−US$ ").replace("−US$ -", "−US$ ") : u) + "</span>" : ""; };
  function drawMy() {
    const w = (P && P.carteira) || {}, pr = (w.periodos || []);
    if (REAL) {
      kpis("myK", [["Saldo da carteira " + mtag(), w.saldo == null ? "—" : num(w.saldo, 5) + " ETH" + usdL(w.saldo, false), w.endereco ? short(w.endereco) : "sem chave salva", "mon"],
        ["Resultado " + mtag(), eth(w.resultado, 5) + usdL(w.resultado), pct(w.resultado_pct) + " do que entrou", "tr"],
        ["Posições abertas", num(w.abertas, 0), num(w.fechadas, 0) + " fechadas", "tr"],
        ["Acerto", w.acerto == null ? "—" : num(w.acerto, 0) + "%", "posições fechadas com lucro", "usr"]]);
    } else {
      kpis("myK", [["Saldo " + mtag(), num(w.saldo, 5) + " ETH" + usdL(w.saldo, false), "começou com " + num(w.inicial, 4) + " ETH", "mon"],
        ["Resultado " + mtag(), eth(w.resultado, 5) + usdL(w.resultado), pct(w.resultado_pct) + " sobre o inicial", "tr"],
        ["Posições abertas", num(w.abertas, 0), num(w.em_posicoes, 5) + " ETH nelas", "tr"],
        ["Acerto", w.acerto == null ? "—" : num(w.acerto, 0) + "%", num(w.fechadas, 0) + " fechadas", "usr"]]);
    }
    kpis("myP", pr.map((x) => ["Últimas " + x.h + " h", eth(x.pnl, 5) + (x.n ? usdL(x.pnl) : ""), x.n ? x.n + " fechadas · " + x.ganhos + " com lucro · " + x.traders + " traders" + (x.taxas ? " · taxas " + num(x.taxas, 5) + " ETH" : "") : "nenhuma fechada", "tr"])
      .concat([["Taxas pagas " + mtag(), '<span class="down">' + num(w.taxas || 0, 5) + " ETH</span>" + usdL(w.taxas || 0, false), "total: pool + gás, fechadas e abertas", "mon"]]));
    table("ovEv", ["Hora", "O que fez", "Token", "Trader", "Motivo"], ((P && P.eventos) || []).slice(0, 80).map((e) => [hora(e.t),
      /não|falhou/.test(e.acao) ? '<span class="tag loss">' + esc(e.acao) + "</span>" : /comprou|copiou/.test(e.acao) ? '<span class="tag buy">' + esc(e.acao) + "</span>" : '<span class="tag neutral">' + esc(e.acao) + "</span>",
      tok(e.token), addr(e.wallet), esc(e.motivo || "") + (e.tx ? " · " + txl(e.tx) : "")]),
    REAL ? "Nada ainda. A REAL só age depois de ligada em Carteira." : "Nada ainda. Assim que um trader do \"Copiando agora\" comprar, aparece aqui.");
  }
  // 0.32.304 (pedido do dono, 11/11: "o pico deu 10%, não entendi"): texto ao passar o mouse (ou tocar) no título Pico
  const PICO_TXT = "Pico = o melhor resultado que a posição chegou a ter enquanto estava aberta, já descontadas as taxas e a folga. Ex.: pico +10% e fechou −2%: chegou a estar ganhando 10%, mas o preço voltou e o stop vendeu depois. O stop móvel só protege o lucro a partir do valor de \"Stop móvel liga com lucro de\".";
  const PICO_H = '<span class="hint" title="' + PICO_TXT.replace(/"/g, "&quot;") + '">Pico ⓘ</span>';
  function drawPos() {
    const ps = (P && P.posicoes) || [];
    $("poT").innerHTML = "Posições abertas " + mtag();
    $("poSub").textContent = ps.length + " abertas · " + ((P && P.carteira && P.carteira.fechadas) || 0) + " fechadas";
    $("poAll").hidden = !ps.length;
    // 0.32.313 (pedido do dono: "botão para vender cada posição"): o Vender sai da última coluna (ficava fora da tela entre 860 e
    // 1280 px) e vai para a primeira, junto da hora; os avisos (venda travada, segurando, erro) ficam na coluna Situação
    const sellBtn = (p) => '<button class="btn sm pobtn" data-close="' + esc(p.id) + '"' + (p.selling ? " disabled" : "") + ">" + (p.selling ? "Vendendo…" : "Vender") + "</button>";
    table("poTb", ["", "Aberta", "Token", "Trader", "Entrou", "Agora", "Resultado", PICO_H, "Fecha em", "Situação"], ps.map((p) => [
      sellBtn(p),
      hora(p.open_t) + '<br><small class="muted">há ' + ago(p.open_t) + " · " + num(p.lag_s, 0) + " s depois do trader</small>",
      tok(p.token, p), addr(p.wallet), num(p.eth_in, 5) + " ETH" + (usdRate() ? '<br><small class="muted">' + usdOf(p.eth_in) + "</small>" : "") + (p.vendas && p.vendas.length ? '<br><small class="muted">' + p.vendas.length + " vendas parciais</small>" : ""),
      pct(p.pnl_pct) + '<br><small class="muted">preço de ' + (p.px_t ? "há " + ago(p.px_t) : "—") + (p.px_src === "dexscreener" ? " · DexScreener" : "") + "</small>" +
        (p.sem_liquidez ? '<br><small class="down"><b>pool sem liquidez</b>: o criador tirou o ETH do pool (rug pull); o token vale 0</small>'
          : p.venda_travada ? '<br><small class="down"><b>venda travada no pool</b>: este resultado não dá para realizar</small>' : ""),
      eth(p.pnl_eth, 5), pct(p.best_pct) + ' <small class="muted">pior ' + num(p.worst_pct, 1) + "%</small>",
      p.sim_id && P.real_cfg && P.real_cfg.real_espelho ? '<span class="tag sim">segue a fictícia</span>' : (p.fecha_em > Date.now() / 1000 ? "em " + dur(p.fecha_em - Date.now() / 1000) : "agora") + (p.solta ? '<br><small class="muted">' + esc(p.solta) + "</small>" : ""),
      (p.espera ? '<small class="muted">segurando: ' + esc(p.espera.motivo || "trader saiu") + ", vende quando ficar positivo</small><br>" : "") +
      (p.sell_error ? '<small class="down">' + esc(p.sell_error) + "</small>" : "") + (!p.espera && !p.sell_error ? '<small class="muted">—</small>' : "")]),
    REAL ? "Nenhuma posição REAL aberta." : "Nenhuma posição aberta. A cópia compra quando um trader do \"Copiando agora\" comprar.");
    // 0.32.308 (pedido do dono: "a real tem que seguir 100% a fictícia; verificação completa"): par de cada posição da FICTÍCIA na REAL
    const m = REAL && P && P.espelho, mc = $("mrCard");
    if (mc) mc.hidden = !m;
    if (m) {
      $("mrSub").innerHTML = (m.ligado ? '<span class="up">espelho ligado</span>' : '<span class="down">espelho desligado: a REAL decide sozinha</span>') +
        " · " + m.com_real + " de " + m.ficticia + " posições da FICTÍCIA com par na REAL" + (m.soltas.length ? " · " + m.soltas.length + " REAL soltas" : "");
      table("mrTb", ["FICTÍCIA abriu", "Token", "Trader", "REAL", "Motivo"], m.linhas.map((x) => [hora(x.open_t), tok(x.token, x), addr(x.wallet),
        x.real ? '<span class="tag win">comprou</span><br><small class="muted">' + num(x.real_open_t - x.open_t, 0) + " s depois</small>" : '<span class="tag loss">não</span>',
        esc(x.motivo || "")]), "A FICTÍCIA não tem posição aberta.");
      table("mrSo", ["REAL solta desde", "Token", "Trader", "Por quê"], m.soltas.map((x) => [hora(x.open_t), tok(x.token, x), addr(x.wallet), esc(x.motivo)]), "Nenhuma posição REAL solta: todas seguem a fictícia.");
    }
  }
  // 0.32.491 (pedido do dono: "seguir o mesmo padrão do /app#historico com card e bem bonitinho"): fechadas em cartões, com filtro por
  // origem (cópia de traders, Caçador, botão Comprar); os quadrados de cima seguem o filtro
  let HIF = "todas", HI_N = 40;
  try { HIF = localStorage.getItem("hood_hif") || "todas"; } catch (e) { /* */ }
  const HI_ORIG = { todas: "Todas", copia: "Cópia de traders", cacador: "Caçador (compras)", botao: "Botão Comprar", hold: "Hold", sa: "Caçador A · sombra", sb: "Caçador B · sombra", sc: "Caçador C · sombra" };
  const HI_SOMBRA = { sa: "a", sb: "b", sc: "c" };
  // 0.32.492 (pedido do dono: "no Histórico, o Caçador A, B e C e ver as compras"): as entradas de mentira do Caçador (US$ 0,10 cada),
  // com o resultado de cada saída fixa. Não são compras da carteira.
  // 0.32.493 (pedido do dono: "mostra o valor ganho em ETH e em dólar, um info como no Histórico do BOOST, o total que ganhou, o que perdeu
  // e o saldo total"): escolhe a saída medida (a melhor vem marcada); os cartões e os totais usam essa saída
  let HSX = {};
  const SX_NOME = { "1": "1 h", "6": "6 h", "24": "24 h", x2: "2×", x5: "5×", x10: "10×", x100: "100×" };
  const hEth = (usdv) => { const r = (CZ && CZ.eth_usd) || usdRate(); return r && usdv != null ? usdv / r : null; };
  const hMoney = (usdv, big) => {
    if (usdv == null) return '<span class="muted">aberta</span>';
    const e = hEth(usdv), sg = usdv > 0 ? "+" : usdv < 0 ? "−" : "";
    return '<span class="' + cls(usdv) + '">' + (e == null ? sg + "US$ " + num(Math.abs(usdv), 2) : sg + num(Math.abs(e), 6) + " ETH") + "</span>" +
      (e == null ? "" : '<small class="' + (big ? "usdv" : "hiusd") + " " + cls(usdv) + '">' + sg + "US$ " + num(Math.abs(usdv), 2) + "</small>");
  };
  function hiPop(L, sx, win) {
    const X = L.filter((t) => t.r[sx] != null && (win ? t.r[sx] > 0 : t.r[sx] <= 0)).sort((a, b) => (win ? b.r[sx] - a.r[sx] : a.r[sx] - b.r[sx]));
    if (!X.length) return "";
    return '<div class="perpop" role="tooltip"><small>' + (win ? "Moedas com ganho" : "Moedas com perda") + "</small><ul>" + X.slice(0, 80).map((t) => {
      const e = hEth(t.r[sx]);
      return "<li><span><b>" + esc(t.simbolo || t.nome || short(t.token)) + "</b><i>" + hora(t.t) + "</i></span><span><em>" + (e == null ? "" : (e > 0 ? "+" : "−") + num(Math.abs(e), 6) + " ETH") + "</em><i>" + (t.r[sx] > 0 ? "+" : "−") + "US$ " + num(Math.abs(t.r[sx]), 2) + "</i></span></li>";
    }).join("") + (X.length > 80 ? '<li class="muted">e mais ' + (X.length - 80) + "</li>" : "") + "</ul></div>";
  }
  function hiSombra(k) {
    if (!CZ) { loadCz(false); $("hiCards").innerHTML = '<p class="muted">Carregando o Caçador…</p>'; $("hiMore").hidden = true; return; }
    const L = (CZ.entradas || {})[k] || [], E = (((CZ.estudo || {}).estrategias) || {})[k] || {};
    const best = (E.saidas || []).filter((r) => r.n).reduce((a, r) => (!a || r.resultado_usd > a.resultado_usd ? r : a), null);
    const sx = HSX[k] || (best && best.saida) || "x2";
    $("hiSom").hidden = false;
    $("hiSx").innerHTML = (E.saidas || [{ saida: "1" }, { saida: "6" }, { saida: "24" }, { saida: "x2" }, { saida: "x5" }, { saida: "x10" }, { saida: "x100" }]).map((r) =>
      '<button type="button" class="hisx' + (r.saida === sx ? " on" : "") + '" data-hsx="' + k + ":" + r.saida + '">' + (SX_NOME[r.saida] || r.saida) + (best && r.saida === best.saida ? " ★" : "") + "</button>").join("");
    $("hiSxT").textContent = (CZ_SAIDA_TXT[sx] || "") + (best && sx === best.saida ? " · ★ a melhor do período" : "");
    const F = L.filter((t) => t.r[sx] != null), G = F.filter((t) => t.r[sx] > 0), Pd = F.filter((t) => t.r[sx] <= 0);
    const soma = (X) => X.reduce((a, t) => a + t.r[sx], 0), sg = soma(G), sp = soma(Pd), tot = sg + sp;
    const kp = (l, v, s, pop) => '<div class="perk' + (pop ? ' hov" tabindex="0' : "") + '"><small>' + l + "</small><b>" + v + "</b>" + (s ? "<span>" + s + "</span>" : "") + (pop || "") + "</div>";
    $("hiSum").innerHTML = kp("Acertos", '<span class="up">' + G.length + "</span>", G.length ? "soma dos ganhos " + hMoney(sg) : "nenhuma entrada ganhou", hiPop(L, sx, true)) +
      kp("Erros", '<span class="down">' + Pd.length + "</span>", Pd.length ? "soma das perdas " + hMoney(sp) : "nenhuma entrada perdeu", hiPop(L, sx, false)) +
      kp("Saldo total", F.length ? hMoney(tot) : "—", F.length ? F.length + " fechada" + (F.length > 1 ? "s" : "") + " · " + num(100 * G.length / F.length, 0) + "% de acerto · US$ " + num(F.length * 0.1, 2) + " investidos" : "nenhuma fechou com esta saída") +
      kp("Abertas", String(L.length - F.length), "ainda sem resultado nesta saída (" + (SX_NOME[sx] || sx) + ")");
    kpis("hiK", [["Entradas " + k.toUpperCase() + " (sombra)", num(E.entradas || 0, 0), "US$ " + num(CZ.estudo ? CZ.estudo.valor_usd || 0.1 : 0.1, 2) + " de mentira cada · período do Caçador", "tr"],
      ["Chegaram a 10×", num(E.x10 || 0, 0), num(E.x100 || 0, 0) + " chegaram a 100×", "up"],
      ["Liquidez tirada", num(E.liquidez_tirada || 0, 0), "a entrada vale zero", "mon"], ["Venda travada", num(E.venda_travada || 0, 0), "honeypot: vale zero", "mon"],
      ["Melhor saída fixa", best ? usd(best.resultado_usd, 2) : "—", best ? best.nome + " · " + best.n + " fechadas · acerto " + num(best.acerto, 0) + "%" : "esperando entradas fecharem", "usr"]]);
    $("hiSub").textContent = "entradas de mentira do Caçador " + k.toUpperCase() + " · não são compras da carteira · mais novas primeiro";
    const V = L.slice(0, HI_N), R = [["1", "1 h"], ["24", "24 h"], ["x2", "2×"], ["x5", "5×"], ["x10", "10×"]];
    $("hiCards").innerHTML = V.map((t) => {
      const sym = t.simbolo || t.nome || short(t.token), ag = t.x_agora;
      return '<div class="abc hc"><div class="abc-t"><b>' + esc(sym) + '</b><span class="sp"></span><b class="hc-r">' + hMoney(t.r[sx], true) + "</b></div>" +
        '<div class="hiorig"><span class="tag pause">CAÇADOR ' + k.toUpperCase() + '</span><span class="tag neutral">SOMBRA · US$ 0,10</span></div>' +
        '<div class="hc-t">' + tok(t.token, t) + "</div>" + '<div class="abc-d hc-m">' + czTraps(t.travas) + "</div>" +
        '<div class="abc-n"><div><small>Entrou</small><b>' + (t.x_ini == null ? "—" : num(t.x_ini, 2) + "×") + '</b><small class="usdv">do preço inicial</small></div><div><small>Pico</small><b>' + (t.x_pico == null ? "—" : xx(t.x_pico)) +
        '</b></div><div><small>Agora</small><b>' + (ag == null ? "—" : xx(ag)) + '</b><small class="usdv">pool nasceu há ' + ago(t.nasceu) + "</small></div></div>" +
        '<div class="czr5">' + R.map((z) => '<div class="' + (z[0] === sx ? "on" : "") + '"><small>' + z[1] + (z[0] === sx ? " ✓" : "") + "</small><b>" + (t.r[z[0]] == null ? '<span class="muted">aberta</span>' : '<span class="' + cls(t.r[z[0]]) + '">' + (t.r[z[0]] > 0 ? "+" : t.r[z[0]] < 0 ? "−" : "") + "$" + num(Math.abs(t.r[z[0]]), 2) + "</span>") + "</b></div>").join("") + "</div>" +
        '<div class="muted small">entrou ' + hora(t.t) + "</div></div>";
    }).join("") || '<p class="muted">Nenhuma entrada ' + k.toUpperCase() + " no período do Caçador.</p>";
    $("hiMore").hidden = L.length <= HI_N;
  }
  const hiOrig = (x) => (x.aba === "hold" ? "hold" : x.aba === "cacador" || String(x.wallet || "").startsWith("cacador") ? "cacador" : x.aba === "botao" || x.wallet === "botao" ? "botao" : "copia");
  // 0.32.494 (pedido do dono: "no Histórico, o saldo da carteira e os ganhos em 1, 6, 12 e 24 h e o total"): sempre da carteira inteira
  function hiWallet(w) {
    const box = $("hiW"); if (!box) return;
    const per = {}; (w.periodos || []).forEach((p) => { per[p.h] = p; });
    const uS = (v, sinal) => { const r = usdRate(); if (!r || v == null) return ""; const d = v * r; return (sinal && d > 0 ? "+" : d < 0 ? "−" : "") + "US$ " + num(Math.abs(d), Math.abs(d) >= 100 ? 0 : 2); };
    const pe = (h) => { const p = per[h]; return '<div class="perk"><small>Últimas ' + h + " h</small><b>" + (p && p.n ? eth(p.pnl, 5) : '<span class="muted">—</span>') + "</b>" +
      (p && p.n ? '<span class="hiusd">' + uS(p.pnl, true) + "</span><span>" + p.n + " fechada" + (p.n > 1 ? "s" : "") + " · " + p.ganhos + " com lucro</span>" : "<span>nenhuma fechou</span>") + "</div>"; };
    box.innerHTML = '<div class="perk"><small>Saldo da carteira ' + mtag() + "</small><b>" + (w.total == null ? "—" : num(w.total, 5) + " ETH") + '</b><span class="hiusd">' + esc(usdOf(w.total) || "") + "</span><span>" + (w.saldo == null ? "" : "livre " + num(w.saldo, 5) + " · em posições " + num(w.em_posicoes || 0, 5)) + "</span></div>" +
      pe(1) + pe(6) + pe(12) + pe(24) +
      '<div class="perk"><small>Total</small><b>' + (w.resultado == null ? eth(w.realizado, 5) : eth(w.resultado, 5)) + '</b><span class="hiusd">' + uS(w.resultado == null ? w.realizado : w.resultado, true) + "</span><span>" + (w.resultado_pct != null ? pct(w.resultado_pct) + " desde o saldo inicial (" + num(w.inicial, 3) + " ETH)" : "todas as fechadas") + "</span></div>";
  }
  function drawHist() {
    const all = (P && P.trades) || [], w = (P && P.carteira) || {};
    const tx = (x) => (x.taxas_eth != null ? x.taxas_eth : (x.fees || 0));
    const cnt = { todas: all.length, copia: 0, cacador: 0, botao: 0, hold: 0 };
    all.forEach((x) => { cnt[hiOrig(x)]++; });
    const som = REAL ? [] : ["sa", "sb", "sc"];                 // a sombra do Caçador não é carteira: só aparece na FICTÍCIA
    som.forEach((k) => { cnt[k] = CZ && CZ.entradas ? ((CZ.entradas[HI_SOMBRA[k]]) || []).length : null; });
    if (!HI_SOMBRA[HIF] && !cnt[HIF]) HIF = "todas";
    if (HI_SOMBRA[HIF] && REAL) HIF = "todas";
    $("hiF").innerHTML = ["todas", "copia", "cacador", "botao", "hold"].filter((k) => k === "todas" || cnt[k]).concat(som).map((k, i) => (k === "sa" ? '<span class="hisep">|</span>' : "") +
      '<button type="button" class="' + (k === HIF ? "on" : "") + '" data-hif="' + k + '">' + HI_ORIG[k] + (cnt[k] == null ? "" : " <small>" + cnt[k] + "</small>") + "</button>").join("");
    if (HI_SOMBRA[HIF]) { hiSombra(HI_SOMBRA[HIF]); drawWhy(); return; }
    $("hiSom").hidden = true;
    if (!REAL && !CZ) loadCz(false);
    hiWallet(w);
    const ts = HIF === "todas" ? all : all.filter((x) => hiOrig(x) === HIF);
    // 0.32.294 (pedido do Bruxo, 11/11): taxas pagas e lucro real (já sem as taxas) em cada fechada e no total
    const pn = ts.reduce((a, x) => a + (x.pnl_eth || 0), 0), win = ts.filter((x) => x.pnl_eth > 0).length, txs = ts.reduce((a, x) => a + tx(x), 0);
    const nome = HIF === "todas" ? "" : " · " + HI_ORIG[HIF];
    kpis("hiK", [["Fechadas " + mtag() + nome, num(ts.length, 0), win + " com lucro", "tr"], ["Lucro real das fechadas", eth(pn, 5) + usdL(pn), "já descontadas as taxas", "tr"],
      ["Taxas pagas nas fechadas", '<span class="down">' + num(txs, 5) + " ETH</span>" + usdL(txs, false), "sem elas o resultado seria " + num(pn + txs, 5) + " ETH " + usdOf(pn + txs), "mon"],
      ["Acerto", ts.length ? num(100 * win / ts.length, 0) + "%" : "—", "", "usr"], ["Lucro final (tudo)", eth(w.realizado, 5) + usdL(w.realizado), "já descontadas as taxas · todas as fechadas", "mon"]]);
    $("hiSub").innerHTML = "mais novas primeiro · " + num(ts.length, 0) + " fechada" + (ts.length === 1 ? "" : "s") + (HIF === "todas" ? "" : " em " + esc(HI_ORIG[HIF])) +
      (REAL && P && !P.hist_escondidas && all.length ? ' <button class="btn sm danger" type="button" data-rlzerar title="Esconde as fechadas REAL até agora (não apaga nada; dá para mostrar de novo)">Zerar o histórico REAL</button>' : "") +
      (REAL && P && P.hist_escondidas ? ' · <b>histórico REAL zerado em ' + hora(P.hist_desde) + "</b> (" + P.hist_escondidas + ' antigas escondidas, nada apagado) <a href="#" data-rhshow>mostrar de novo</a>' : "");
    const ul = (v, s) => { const u = usdOf(Math.abs(v || 0)); return u ? '<small class="usdv">' + (s && v > 0 ? "+" : s && v < 0 ? "−" : "") + esc(u.replace("≈ ", "")) + "</small>" : ""; };
    const tagO = (x) => { const o = hiOrig(x);
      return o === "cacador" ? '<span class="tag pause">CAÇADOR' + (x.cz && x.cz.entrada ? " " + esc(x.cz.entrada) : "") + "</span>" + (x.cz ? ' <span class="tag neutral">entrada ' + esc(x.cz.entrada || "") + " · alvo +" + num(x.cz.alvo, 0) + "% · stop −" + num(x.cz.stop, 0) + "%</span>" : "")
        : o === "botao" ? '<span class="tag neutral">BOTÃO COMPRAR</span>' : '<span class="tag win">CÓPIA DE TRADER</span>'; };
    // 0.32.500 (pedido do dono: "quando repetir, mostrar que entrou de novo"): conta as entradas pelo nome, da mais antiga para a mais
    // nova; a 2ª em diante ganha "2ª ENTRADA" e borda âmbar. Mesmo nome em outro contrato = token copiado (outro endereço)
    const symOf = (x) => String(x.simbolo || x.nome || (NOM[x.token] || {}).simbolo || "").trim().toUpperCase();
    const rep = {}, first = {};
    all.slice().sort((p, q) => (p.open_t || 0) - (q.open_t || 0)).forEach((x) => {
      const k = symOf(x) || x.token; rep[k] = (rep[k] || 0) + 1; x._ord = rep[k];
      if (!first[k]) first[k] = x.token; x._outro = first[k] !== x.token;
    });
    const holdTag = (x) => (x.hold_pct ? '<span class="tag hihold" title="no alvo vendeu uma parte e guardou o resto (Carteira → Shitcoin hold)">VENDEU ' + num(100 - x.hold_pct, 0) + "% · HOLD DE " + num(x.hold_pct, 0) + "%</span>"
      : x.hold_parte ? '<span class="tag hihold">VENDEU ' + num(x.hold_parte * 100, 0) + "% DO HOLD</span>" + (x.hold_de && x.hold_de.entrada ? ' <span class="tag neutral">do Caçador ' + esc(x.hold_de.entrada) + "</span>" : "")
      : x.aba === "hold" || x.hold ? '<span class="tag hihold">HOLD ' + num(+x.hold || 0, 0) + "% VENDIDO</span>" + (x.hold_de && x.hold_de.entrada ? ' <span class="tag neutral">do Caçador ' + esc(x.hold_de.entrada) + "</span>" : "") : "");
    // 0.32.504 (pedido do dono: "dá match de cores para sabermos se a moeda repetiu"): cada moeda repetida ganha a sua cor
    const RC = ["#f59e0b", "#06b6d4", "#ec4899", "#84cc16", "#8b5cf6", "#ef4444", "#14b8a6", "#f97316", "#3b82f6", "#eab308"];
    const repCor = {}; let nCor = 0;
    all.slice().sort((p, q) => (p.open_t || 0) - (q.open_t || 0)).forEach((x) => { const k = symOf(x) || x.token; if ((rep[k] || 1) > 1 && !(k in repCor)) repCor[k] = RC[nCor++ % RC.length]; });
    const corDe = (x) => repCor[symOf(x) || x.token];
    const repTag = (x) => { const k = symOf(x) || x.token, n = rep[k] || 1; if (n < 2) return "";
      return '<span class="tag hirep" style="--rc:' + corDe(x) + '" title="' + n + ' entradas em ' + esc(k) + ' no Histórico">' + x._ord + "ª ENTRADA de " + n + "</span>" +
        (x._outro ? ' <span class="tag loss" title="mesmo nome, outro endereço: provavelmente um token copiado">OUTRO CONTRATO</span>' : ""); };
    const V = ts.slice(0, HI_N);
    $("hiCards").innerHTML = V.map((x) => {
      const sym = x.simbolo || x.nome || (NOM[x.token] || {}).simbolo || short(x.token);
      return '<div class="abc hc' + ((rep[symOf(x) || x.token] || 1) > 1 ? " hcrep" : "") + '"' + (corDe(x) ? ' style="--rc:' + corDe(x) + '"' : "") + '><div class="abc-t"><b>' + esc(sym) + '</b><span class="sp"></span><b class="hc-r">' + eth(x.pnl_eth, 5) + ul(x.pnl_eth, true) + "</b></div>" +
        '<div class="hiorig">' + tagO(x) + repTag(x) + holdTag(x) + "</div>" + (hiOrig(x) === "copia" ? '<div class="hc-t">' + addr(x.wallet) + "</div>" : "") +
        '<div class="hc-t">' + tok(x.token, x) + "</div>" +
        '<div class="abc-d hc-m">' + esc(x.motivo || "") + "</div>" +
        '<div class="abc-n"><div><small>%</small><b>' + pct(x.pnl_pct) + "</b></div><div><small>Investido</small><b>" + num(x.eth_in, 5) + ul(x.eth_in) + "</b></div><div><small>Segurou</small><b>" + dur(Math.max(0, (x.close_t || 0) - (x.open_t || 0))) + "</b></div></div>" +
        '<div class="abc-n hc-f"><div><small>Pico</small><b>' + pct(x.best_pct) + '</b></div><div><small>Taxas pagas</small><b><span class="down">' + num(tx(x), 6) + "</span>" + ul(tx(x)) + "</b></div><div><small>Recebeu</small><b>" + num(x.eth_out, 5) + ul(x.eth_out) + "</b></div></div>" +
        '<div class="muted small">' + hora(x.close_t) + (x.tx_out ? " · " + txl(x.tx_out) : "") + "</div></div>";
    }).join("") || '<p class="muted">' + (REAL ? "Nenhuma posição REAL fechada ainda." : HIF === "todas" ? "Nenhuma posição fechada ainda." : "Nenhuma fechada em " + HI_ORIG[HIF] + ".") + "</p>";
    $("hiMore").hidden = ts.length <= HI_N;
    drawWhy();
  }
  // 0.32.322 (pedido do dono, 11/11: "por que estamos sempre no negativo"): fechadas dos últimos 7 dias por motivo de saída, por atraso
  // da entrada e por trader, com o peso das taxas. Só mede: é daqui que sai a próxima correção.
  function drawWhy() {
    if (!$("pqK")) return;
    const q = (P && P.porque) || {};
    $("pqSub").innerHTML = "fechadas dos últimos " + (q.dias || 7) + " dias " + mtag() + " · só mede, não muda nada";
    const falta = q.acerto != null && q.acerto_empate != null;
    kpis("pqK", [
      ["Ganho médio quando ganha", q.ganho_medio_pct == null ? "—" : pct(q.ganho_medio_pct), "por posição com lucro", "tr"],
      ["Perda média quando perde", q.perda_media_pct == null ? "—" : pct(q.perda_media_pct), "por posição no prejuízo", "tr"],
      ["Acerto × o que empata", (q.acerto == null ? "—" : num(q.acerto, 0) + "%") + " × " + (q.acerto_empate == null ? "—" : num(q.acerto_empate, 0) + "%"),
        falta ? (q.acerto >= q.acerto_empate ? "acima do que precisa" : "abaixo do que precisa") : "falta ganho ou perda", "usr"],
      ["Taxas sobre o investido", '<span class="down">' + num(q.taxas_pct || 0, 1) + "%</span>", num(q.taxas || 0, 5) + " ETH em " + num(q.n || 0, 0) + " fechadas", "mon"],
      ["Teve lucro e fechou perdendo", num(q.devolveu || 0, 0), "pico de +10% ou mais", "tr"]]);
    const H = ["Fechadas", "Com lucro", "Resultado", "Sobre o investido", "Taxas", "Pior"];
    const row = (d, nome) => [nome, num(d.n, 0), d.ganhos + " de " + d.n, eth(d.pnl, 5) + usdL(d.pnl), pct(d.pct), '<span class="down">' + num(d.taxas, 5) + "</span>", pct(d.pior)];
    table("pqM", ["Motivo da saída"].concat(H), (q.motivos || []).map((d) => row(d, esc(d.k))), "Nenhuma posição fechada nos últimos 7 dias.");
    table("pqA", ["Atraso da entrada"].concat(H), (q.atraso || []).map((d) => row(d, esc(d.k))), "Sem posição fechada com o atraso guardado.");
    table("pqT", ["Trader (pior primeiro)"].concat(H), (q.traders || []).map((d) => row(d, addr(d.k))), "Nenhum trader com posição fechada nos últimos 7 dias.");
  }
  // 0.32.503 (pedido do dono: "na Carteira um quadrado Shitcoin hold; clicou, mostra quanto temos, quanto vale, quanto cresceu e um
  // botão para vender agora"): as posições guardadas no alvo do Caçador, da carteira que está no topo (FICTÍCIA ou REAL)
  let SH_OPEN = false;
  function drawHold() {
    const box = $("shCard"); if (!box) return;
    // 0.32.505 (caso BITGOIN: "o hold aparece e some"): mostrava só a carteira do topo; agora vêm os holds da FICTÍCIA e da REAL juntos
    const L = (P && P.holds) || ((P && P.posicoes) || []).filter((p) => p.hold);
    const inv = L.reduce((a, p) => a + (+p.eth_in || 0), 0), val = L.reduce((a, p) => a + (+p.eth_in || 0) + (+p.pnl_eth || 0), 0);
    const pc = inv ? (val / inv - 1) * 100 : null;
    box.innerHTML = '<button type="button" class="shsum" id="shOpen" aria-expanded="' + SH_OPEN + '"><span class="shico">💎</span><span><b>Shitcoin hold</b> <span class="tag sim">FICTÍCIA</span> <span class="tag real">REAL</span>' +
      "<small>" + (L.length ? L.length + " moeda" + (L.length > 1 ? "s" : "") + " guardada" + (L.length > 1 ? "s" : "") + " · investido " + num(inv, 5) + " ETH" : "nada guardado ainda · ligue \"Guardar uma parte no alvo\" no Caçador") + "</small></span>" +
      '<span class="sp"></span>' + (L.length ? "<span class=\"shv\"><b>" + num(val, 5) + " ETH</b><small>" + esc(usdOf(val) || "") + "</small>" + pct(pc) + "</span>" : "") + "<i>" + (SH_OPEN ? "▲" : "▼") + "</i></button>" +
      (SH_OPEN ? (L.length ? '<div class="abgrid shgrid">' + L.map((p) => { const v = (+p.eth_in || 0) + (+p.pnl_eth || 0);
        return '<div class="abc"><div class="abc-t">' + tok(p.token, p) + '<span class="sp"></span><b class="hc-r">' + pct(p.pnl_pct) + "</b></div>" +
          '<div class="hiorig">' + (p.real ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>') + ' <span class="tag hihold">HOLD ' + num(+p.hold || 0, 0) + "%</span>" + (p.hold_de && p.hold_de.entrada ? ' <span class="tag neutral">Caçador ' + esc(p.hold_de.entrada) + "</span>" : "") + "</div>" +
          '<div class="abc-n"><div><small>Tokens</small><b>' + num(+p.tokens_left || 0, 0) + '</b></div><div><small>Custou</small><b>' + num(p.eth_in, 6) + '</b><small class="usdv">' + esc(usdOf(p.eth_in) || "") + '</small></div><div><small>Vale agora</small><b>' + num(v, 6) + '</b><small class="usdv">' + esc(usdOf(v) || "") + "</small></div></div>" +
          '<div class="muted small">guardado ' + hora(p.open_t) + " · desde a compra " + pct(p.pnl_pct) + "</div>" +
          (p.sell_error ? '<div class="small down">' + esc(p.sell_error) + "</div>" : "") +
          '<button class="btn sm primary" type="button" data-shsell="' + esc(p.id) + '" data-shreal="' + (p.real ? 1 : 0) + '"' + (p.selling ? " disabled" : "") + ">" + (p.selling ? "Vendendo…" : "Vender…") + "</button></div>"; }).join("") + "</div>"
        : '<p class="muted">Quando o Caçador bater o alvo com "Guardar uma parte no alvo" ligado, a parte guardada aparece aqui.</p>') : "");
  }
  // 0.32.505 (pedido do dono: "vender o hold escolhendo 10, 20, 30… 100% numa janela"): cada venda vira um trade no Histórico
  let SHV = null;
  function openShSell(id, real) {
    const p = ((P && P.holds) || []).find((x) => x.id === id && !!x.real === real); if (!p) return;
    SHV = { id, real, pc: 100, p };
    $("shMT").textContent = "Vender o hold de " + (p.simbolo || p.nome || short(p.token));
    $("shMS").innerHTML = (real ? '<span class="tag real">REAL</span> dinheiro de verdade' : '<span class="tag sim">FICTÍCIA</span>') + " · escolha quanto do hold vender";
    drawShSell(); $("shM").hidden = false;
  }
  function drawShSell() {
    if (!SHV) return;
    const p = SHV.p, f = SHV.pc / 100, v = ((+p.eth_in || 0) + (+p.pnl_eth || 0)) * f;
    $("shMB").innerHTML = '<div class="seg czholdp" style="flex-wrap:wrap">' + [10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map((x) => '<button type="button" data-shpc="' + x + '" class="' + (x === SHV.pc ? "on" : "") + '">' + x + "%</button>").join("") + "</div>" +
      '<div class="abc-n" style="margin-top:12px"><div><small>Tokens a vender</small><b>' + num((+p.tokens_left || 0) * f, 0) + "</b></div><div><small>Custou (essa parte)</small><b>" + num((+p.eth_in || 0) * f, 6) + ' ETH</b><small class="usdv">' + esc(usdOf((+p.eth_in || 0) * f) || "") + "</small></div>" +
      "<div><small>Vale agora (estimado)</small><b>" + num(v, 6) + ' ETH</b><small class="usdv">' + esc(usdOf(v) || "") + "</small></div></div>" +
      '<p class="small muted">' + (SHV.pc === 100 ? "Vende todo o hold e ele sai da Carteira." : "O resto (" + (100 - SHV.pc) + "%) continua guardado.") + " A venda fica no Histórico, na aba Hold." +
      (SHV.real ? " Na REAL o valor recebido depende do pool na hora (folga da carteira REAL)." : "") + (p.sem_liquidez ? ' <b class="down">O pool está sem liquidez: a venda dá baixa em 0.</b>' : "") + "</p>" +
      '<div class="row" style="gap:8px;justify-content:flex-end"><button class="btn sm" type="button" id="shNo">Cancelar</button><button class="btn sm ' + (SHV.real ? "danger" : "primary") + '" type="button" id="shGo">Vender ' + SHV.pc + "%" + (SHV.real ? " na REAL" : "") + "</button></div>";
  }
  function drawCarteira() {
    drawHold();
    drawConv();
    if (!P) return;
    const c = P.cfg_sim || {}, rc = P.real_cfg || {}, st = P.real_status || {};
    const on = $("cfOn"); on.classList.toggle("on", !!c.on); on.textContent = c.on ? "Ligada" : "Desligada"; on.setAttribute("aria-checked", c.on ? "true" : "false");
    const ro = $("rlOn"); ro.classList.toggle("on", !!st.ligada); ro.textContent = st.ligada ? "Ligada" : "Desligada"; ro.setAttribute("aria-checked", st.ligada ? "true" : "false");
    if (!CF_DIRTY && !RL_DIRTY && !document.activeElement.closest("#cfRows")) $("cfRows").innerHTML = cfgRows(c, rc);
    if ($("sgBox")) $("sgBox").innerHTML = BB.sgHtml(P.stop_ganho);
    if (!CMP_PLAN && !document.activeElement.closest("#cmpBox")) drawCmp();
    loadCmp(false);
    loadHist(false);
    $("rlSt").innerHTML = [
      "Trava geral do servidor: " + (st.permitido ? '<span class="up">aberta</span>' : '<span class="down">fechada (PUMP_REAL_ALLOWED): nada é enviado</span>'),
      "Chave: " + (st.chave ? '<span class="up">salva</span> · carteira ' + addr(st.endereco) : '<span class="muted">não salva</span>'),
      // 0.32.298 (pedido do dono: "como sei a carteira"): endereço inteiro, com Copiar, para mandar ETH na Robinhood Chain
      st.endereco ? 'Endereço: <code class="hdfull">' + esc(st.endereco) + '</code> <button class="btn sm" type="button" data-copyaddr="' + esc(st.endereco) + '">Copiar</button>' : "",
      "Saldo: " + (st.saldo == null ? "—" : num(st.saldo, 5) + " ETH"),
      "REAL: " + (st.ligada ? '<span class="up">ligada</span> desde ' + hora(st.desde) : '<span class="down">desligada</span>'),
    ].filter(Boolean).join("<br>");
    const sf = P.seguranca || {}, s = sf.stat || {}, cp = sf.copia || {}, rg = sf.regras || {};
    kpis("sfK", [["Compras vistas", num(cp.compras_vistas, 0), "dos traders do \"Copiando agora\"", "tr"], ["Copiadas", num(cp.copiadas, 0), "token aprovado", "tr"],
      ["Barradas", num(cp.barradas, 0), num(cp.sem_pool, 0) + " sem pool de ETH na V4", "tr"],
      ["GoPlus", num(s.goplus_com_dados, 0) + " com dados", num(s.goplus_sem_dados, 0) + " sem dados desta rede", "usr"]]);
    table("sfT", ["Hora", "Token", "Veredito", "Ida e volta", "GoPlus"], (sf.recentes || []).map((x) => [hora(x.t), tok(x.token),
      x.ok ? '<span class="tag win">aprovado</span>' : '<span class="tag loss">' + (x.erro ? "sem conferência" : "barrado") + "</span> " + esc(x.why || ""),
      x.ida_volta_pct == null ? "—" : num(x.ida_volta_pct, 1) + "% (máx. " + num(rg.ida_volta_max_pct, 0) + "%)", esc(x.goplus || "—")]),
    "Nenhum token conferido ainda: a conferência roda na primeira compra de um trader do \"Copiando agora\".");
  }
  // ------------------------------------------------------------------ 0.32.286: saldo e abastecer de outra rede (Relay)
  let GA = null, GA_AT = 0, GA_BUSY = false, GA_PICK = null, GA_Q = null, GA_QT = 0, GA_QV = 60, GA_SEQ = 0, GA_TM = null, GA_FIRST = false;
  // 0.32.299 (pedido do dono: "na hora que colocar o valor ele cota o que vai receber a carteira robinhood"): a cotação sai
  // sozinha 0,8 s depois de digitar o valor ou trocar a rede; o botão "Enviar para a Robinhood" envia (cota de novo se venceu).
  async function gaQuote(btn) {
    if (!GA_PICK) { drawQuote({ error: "Nenhuma rede de origem com saldo." }); return null; }
    const v = Number($("gaUsd").value || 0);
    if (!(v > 0)) { $("gaP").hidden = true; return null; }
    const seq = ++GA_SEQ, el = $("gaP");
    el.hidden = false; el.innerHTML = '<span class="muted">Cotando quanto chega na Robinhood…</span>';
    GA_Q = null;
    const r = await BB.api("/api/hood/abastecer/cotar", { body: { origem: GA_PICK, usd: v }, quiet: true });
    if (seq !== GA_SEQ) return null;                       // o valor mudou enquanto cotava: vale a cotação mais nova
    if (r && r.quote_id) { GA_Q = r.quote_id; GA_QT = Date.now(); GA_QV = Number(r.validade_s) || 60; }
    drawQuote(r || { error: "sem resposta" });
    return r;
  }
  function gaAuto() { clearTimeout(GA_TM); GA_TM = setTimeout(() => gaQuote(), 800); }
  async function loadGas(force) {
    if (GA_BUSY || (!force && Date.now() - GA_AT < 30000)) return;
    GA_BUSY = true;
    try { const r = await BB.api("/api/hood/abastecer", { quiet: true }); if (r && !r.error) { GA = r; GA_AT = Date.now(); } } finally { GA_BUSY = false; drawGas(); }
  }
  function drawGas() {
    const box = $("rlBal"), card = $("gaCard");
    if (!box || !card) return;
    if (!GA || !GA.chave) { box.hidden = true; card.hidden = true; return; }
    box.hidden = false; card.hidden = false;
    box.className = "hdbal " + (GA.precisa ? "low" : "ok");
    box.innerHTML = '<small class="muted">Saldo na Robinhood Chain</small><b class="big">' + (GA.saldo == null ? "—" : num(GA.saldo, 6) + " ETH") + "</b>" +
      (GA.saldo_usd != null ? "≈ US$ " + num(GA.saldo_usd, 2) + " · " : "") + "dá para " + num(GA.compras, 0) + " compras REAL de " + num(GA.por_compra, 4) + " ETH" +
      (GA.precisa ? '<br><b class="down">Precisa abastecer:</b> faltam ≈ US$ ' + num(GA.falta_usd, 2) + " para " + 5 + " compras e o gás das vendas. Use \"Enviar para a Robinhood\" logo abaixo."
        : '<br><span class="up">Saldo suficiente para começar.</span>');
    const rot = GA.rotas || [];
    if (!GA_PICK || !rot.some((x) => x.origem === GA_PICK && x.ok)) GA_PICK = (rot.find((x) => x.ok) || {}).origem || null;
    $("gaR").innerHTML = rot.map((x) => '<label class="garow"><input type="radio" name="gaO" value="' + esc(x.origem) + '"' + (x.ok ? "" : " disabled") + (x.origem === GA_PICK ? " checked" : "") + '>' +
      '<span class="gn">' + esc(x.nome) + '</span><span class="gs">' + (x.saldo == null ? "—" : num(x.saldo, 6) + " " + esc(x.moeda) + (x.saldo_usd != null ? " (US$ " + num(x.saldo_usd, 2) + ")" : "")) + "</span>" +
      (x.ok ? '<span class="up">taxa ≈ ' + num(x.taxa_pct, 1) + "% · ~" + num(x.tempo_s || 0, 0) + " s</span>" : '<span class="muted">' + esc(x.motivo || "") + "</span>") + "</label>").join("") +
      (rot.some((x) => x.ok) ? "" : '<p class="muted">Nenhuma das suas outras redes tem saldo para mandar. Deposite ETH (Ethereum, Base, Arbitrum) ou BNB neste mesmo endereço: ' + addr(GA.endereco) + "</p>") +
      '<p class="muted small">Limites: até US$ ' + num(GA.limites.por_vez_usd, 0) + " por vez e US$ " + num(GA.limites.dia_usd, 0) + " em 24 h (já foram US$ " + num(GA.limites.gasto_24h, 2) + ")" +
      (GA.permitido ? "" : ' · <b class="down">trava geral do servidor fechada: só cotação</b>') + "</p>";
    gaConv();
    if (!GA_FIRST && GA_PICK && GA.permitido !== undefined) { GA_FIRST = true; gaAuto(); }   // ao abrir já mostra quanto chega
    table("gaH", ["Hora", "De", "Pagou", "Chega", "Situação", "Transação"], (GA.historico || []).map((x) => [hora(x.t), esc(x.origem_nome),
      num(x.paga, 6) + " " + esc(x.moeda) + '<br><small class="muted">US$ ' + num(x.usd, 2) + "</small>", num(x.recebe, 6) + " ETH",
      (x.status === "confirmada" ? '<span class="tag win">entregue</span>' : x.status === "falhou" ? '<span class="tag loss">falhou</span>' : x.status === "devolvida" ? '<span class="tag neutral">devolvida</span>' : '<span class="tag buy">' + esc(x.status) + "</span>") +
        (x.motivo ? '<br><small class="muted">' + esc(x.motivo) + "</small>" : ""),
      x.tx && x.expl ? '<a class="hdaddr" href="' + esc(x.expl + x.tx) + '" target="_blank" rel="noopener">' + esc(x.tx.slice(0, 10)) + "…</a>" : "—"]), "Nenhum abastecimento ainda.");
  }
  function gaConv() {
    const el = $("gaConv"); if (!el || !GA) return;
    const r = (GA.rotas || []).find((x) => x.origem === GA_PICK), v = Number($("gaUsd").value || 0);
    el.textContent = r && r.usd_moeda && v > 0 ? "≈ " + num(v / r.usd_moeda, 6) + " " + r.moeda + (r.max_usd ? " · máx. US$ " + num(r.max_usd, 2) + " nesta rede" : "") : "";
  }
  function drawQuote(q) {
    const el = $("gaP"); el.hidden = false;
    if (q.error) { el.innerHTML = '<span class="down">' + esc(q.error) + "</span>"; return; }
    el.innerHTML = '<div class="garec">A carteira Robinhood recebe <b class="up">' + num(q.recebe, 6) + " ETH</b> <span>≈ US$ " + num(q.usd_recebe, 2) + "</span></div>" +
      "Sai <b>" + num(q.paga, 6) + " " + esc(q.moeda) + "</b> de " + esc(q.origem_nome) + " (US$ " + num(q.usd, 2) + ")" +
      "<br>Taxa da ponte ≈ " + num(q.taxa_pct, 2) + "% · gás na origem ≈ US$ " + num(q.gas_usd, 3) + " · entrega em ~" + num(q.tempo_s || 0, 0) + " s" +
      (q.avisos && q.avisos.length ? '<br><span class="warn">' + q.avisos.map(esc).join(" · ") + "</span>" : "") +
      (q.bloqueia && q.bloqueia.length ? '<br><b class="down">Não dá para enviar: ' + q.bloqueia.map(esc).join(" · ") + "</b>"
        : '<div class="row" style="margin-top:10px;flex-wrap:wrap;gap:8px"><button class="btn primary" id="gaGo" type="button">Enviar para a Robinhood</button><small class="muted">cotação vale ' + num(q.validade_s, 0) + " s; se vencer, cota de novo ao enviar</small></div>");
  }
  // ------------------------------------------------------------------ 0.32.294: Dinheiro entrando e Administração
  let FX = null, FXH = 1, FX_AT = 0, AD = null, AD_AT = 0;
  try { FXH = Number(localStorage.getItem("hood_fxh")) || 1; } catch (e) { /* */ }
  async function loadFx(force) {
    if (!force && Date.now() - FX_AT < 15000) return;
    FX_AT = Date.now();
    const r = await BB.api("/api/hood/fluxo?h=" + FXH, { quiet: true });
    if (r && !r.error) { FX = r; (r.rows || []).forEach((x) => { if (x.simbolo || x.nome) NOM[x.token] = { nome: x.nome || "", simbolo: x.simbolo || "" }; }); }
    drawFx();
  }
  // 0.32.303 (pedido do dono): conferência de cada moeda, aba Honeypot e bloqueadas, botões Bloquear e Comprar
  let FXT = "cz";                                   // 0.32.497 (pedido do dono): o Caçador é a 1ª aba e já abre nela
  const fxHp = (x) => !!(x.seguranca && x.seguranca.venda_travada);
  function fxSafe(x) {
    const v = x.seguranca;
    if (!v || v.erro) return '<span class="fxsg"><span class="tag neutral">conferindo…</span></span>';
    if (v.ok && v.lp_livre) return '<span class="fxsg"><span class="tag loss">LIQUIDEZ SOLTA</span> <span class="down">' + esc(v.lp_livre) + "</span></span>";
    if (v.ok) return '<span class="fxsg"><span class="tag win">conferido</span> <span class="muted">dá para comprar e vender' + (v.ida_volta_pct != null ? " · ida e volta −" + num(v.ida_volta_pct, 1) + "%" : "") + "</span></span>";
    if (v.venda_travada) return '<span class="fxsg"><span class="tag loss dzt">HONEYPOT</span> <span class="down">' + esc(v.why || "") + "</span></span>";
    return '<span class="fxsg"><span class="tag loss">barrado</span> <span class="muted">' + esc(v.why || "") + "</span></span>";
  }
  function fxBtns(x, bloq) {
    const ok = !!(x.seguranca && x.seguranca.ok) && !bloq;
    const tt = bloq ? "moeda bloqueada por você" : !x.seguranca ? "ainda conferindo esta moeda" : !x.seguranca.ok ? "barrada na conferência: " + (x.seguranca.why || "") : "";
    const b = (m, txt) => ok ? '<button class="btn sm" data-fxbuy="' + esc(x.token) + '" data-modo="' + m + '" title="Comprar agora ' + (m === "ambas" ? "na FICTÍCIA e na REAL" : "na " + txt) + '">' + txt + "</button>"
      : '<button class="btn sm dz" type="button" disabled title="' + esc(tt) + '">' + txt + "</button>";
    return '<span class="fxbuy"><small class="muted">Comprar:</small>' + b("sim", "FICTÍCIA") + b("real", "REAL") + b("ambas", "As 2") +
      (bloq ? '<button class="btn sm" data-fxblock="' + esc(x.token) + '" data-on="0">Desbloquear</button>'
        : '<button class="btn sm blk" data-fxblock="' + esc(x.token) + '" data-on="1" title="Nunca comprar esta moeda (cópia e botão)">Bloquear</button>') + "</span>";
  }
  // 0.32.484 (pedido do dono, caso Super Iguana): Caçador de explosões, só em sombra (nunca compra)
  let CZ = null, CZD = 7, CZ_AT = 0;
  try { CZD = Number(localStorage.getItem("hood_czd")) || 7; } catch (e) { /* */ }
  async function loadCz(force) {
    if (!force && Date.now() - CZ_AT < 20000) return drawCz();
    CZ_AT = Date.now();
    const r = await BB.api("/api/hood/cacador?dias=" + CZD, { quiet: true });
    if (r && !r.error) { CZ = r; (r.agora || []).forEach((x) => { if (x.simbolo || x.nome) NOM[x.token] = { nome: x.nome || "", simbolo: x.simbolo || "" }; }); }
    drawCz();
    if (VIEW === "historico") drawHist();                       // 0.32.492: abas do Caçador A/B/C no Histórico
  }
  const usd = (v, d) => (v == null ? "—" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : v < 0 ? "−" : "") + "US$ " + num(Math.abs(v), d == null ? 2 : d) + "</span>");
  const xx = (v) => (v == null ? "—" : '<span class="' + (v >= 1 ? "up" : "down") + '">' + (v >= 100 ? num(v, 0) : v >= 10 ? num(v, 1) : num(v, 2)) + "×</span>");
  function czTraps(list) {
    return (list || []).length ? list.map((t) => '<span class="tag ' + (/tirada|travada/.test(t) ? "loss" : "pause") + '">' + esc(t) + "</span>").join(" ") : '<span class="tag win">nenhuma trava</span>';
  }
  function czEnt(e) {
    if (!e) return '<span class="muted">não entrou</span>';
    return "entrou " + xx(e.x_ini) + ' do início<br><small class="muted">pico ' + (e.x_pico == null ? "—" : num(e.x_pico, 2) + "×") + " · agora " + (e.x_agora == null ? "—" : num(e.x_agora, 2) + "×") +
      (e.r24 != null ? " · 24 h " + usd(e.r24, 3) : "") + "</small>";
  }
  // 0.32.489 (pedido do Bruxo, áudio de 27/11): compras FICTÍCIAS pelas entradas do Caçador e a grade de % de entrada e saída
  const CZ_IN = [["cz_eth", "Valor por compra", "ETH", 0.0001, 5, 0.0001], ["cz_entrada_max_pct", "Só entra até (acima do preço inicial do pool; 0 = sem limite)", "%", 0, 100000, 10],
    ["cz_alvo_pct", "Vende tudo no alvo", "%", 1, 100000, 5], ["cz_stop_pct", "Stop de perda (0 = sem stop)", "%", 0, 100, 5], ["cz_max_h", "Tempo máximo", "h", 0.1, 168, 1]];
  let CZG = null;
  // 0.32.491 (pedido do dono: "explica o A, B e C, o que fazem e como são"): as 3 entradas viram cartões que dá para escolher
  const CZ_ENT = {
    a: ["Cega", "Compra na 1ª compra que aparece no pool novo, sem olhar nada.", "Pega o começo de tudo, inclusive os golpes. Serve de régua: é o que acontece sem filtro nenhum."],
    b: ["Com sinais e sem travas", "Espera o pool juntar 5 compradores diferentes e 0,05 ETH em compras nos primeiros 30 min, e só entra se nenhuma trava estiver acesa.", "Travas: liquidez na mão de uma carteira, token que já existia, hook que cobra nas trocas, código perigoso, venda travada ou liquidez tirada."],
    c: ["Com sinais, sem olhar as travas", "O mesmo sinal da B (5 compradores e 0,05 ETH), mas entra mesmo com trava acesa.", "Mostra quanto as travas da B protegem: se a C ganha menos que a B, as travas estão ajudando."],
  };
  function czBuyDraw() {
    const box = $("czBuy"); if (!box) return;
    const c = (P && P.cfg_sim) || null;
    if (!c) { box.innerHTML = '<p class="muted">carregando a sua carteira…</p>'; return; }
    if (document.activeElement && box.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;   // não apaga o que está digitando
    const sw = (k, on) => '<button class="btn tgl sw ' + (on ? "on" : "off") + '" type="button" role="switch" aria-checked="' + on + '" data-czk="' + k + '">' + (on ? "Ligado" : "Desligado") + "</button>";
    // 0.32.494 (pedido do dono: "poder desligar o A, B ou C"; "está confuso: desligado não compra nada?"): A, B e C são chaves
    // independentes, e o topo diz em uma frase o que está acontecendo de verdade na sua carteira
    // 0.32.495 (pedido do dono: "esses botões fazem mais sentido dentro de cada um, A, B e C; posso querer ligar somente a REAL"):
    // cada entrada tem a chave da FICTÍCIA e a da REAL (a REAL começa desligada e precisa da carteira REAL ligada)
    const ents = c.cz_on ? String(c.cz_ents == null ? (c.cz_entrada || "b") : c.cz_ents) : "", rents = String(c.cz_real_ents || "");
    const E = ((CZ && CZ.estudo) || {}).estrategias || {}, realOn = !!(P && P.real_cfg && P.real_cfg.real_on);
    const ps = ((P && P.posicoes) || []).filter((p) => p.aba === "cacador"), ts = ((P && P.trades) || []).filter((t) => t.aba === "cacador");
    const res = ts.reduce((x, t) => x + (+t.pnl_eth || 0), 0), win = ts.filter((t) => (+t.pnl_eth || 0) > 0).length;
    const L = (x) => x.split("").map((k) => k.toUpperCase()).join(", ");
    const partes = [];
    if (ents) partes.push("na <b>FICTÍCIA</b> nas entradas " + L(ents) + " (" + num(c.cz_eth, 4) + " ETH cada)");
    if (rents) partes.push("na <b>REAL</b> nas entradas " + L(rents) + (realOn ? " (o valor por compra da carteira REAL)" : ' — <span class="down">mas a carteira REAL está desligada, então a REAL não compra</span> <button class="btn sm danger" type="button" data-czrealon>Ligar a carteira REAL</button>'));
    let estado = partes.length
      ? '<div class="czstate on"><b>O Caçador está comprando sozinho</b> ' + partes.join(" e ") + ", e sai pelo alvo, stop e tempo abaixo."
      : '<div class="czstate off"><b>Nenhuma entrada está ligada: o Caçador não compra nada</b>, nem na FICTÍCIA nem na REAL. Os números dos blocos 2 e 3 e das abas "sombra" do Histórico são <b>só simulação</b> (o robô finge entrar com US$ 0,10). Para comprar, ligue a FICTÍCIA ou a REAL dentro de A, B ou C.';
    estado += (REAL ? "" : " Na FICTÍCIA agora: <b>" + ps.length + "</b> aberta" + (ps.length === 1 ? "" : "s") + " · <b>" + ts.length + "</b> fechada" + (ts.length === 1 ? "" : "s") +
      (ts.length ? " · resultado " + eth(res, 5) + (usdOf(res) ? ' <span class="muted">(' + esc(usdOf(res)) + ")</span>" : "") + " · acerto " + num(100 * win / ts.length, 0) + "%" : "") + ' · <a href="#historico" data-hif="cacador">ver no Histórico</a>') + "</div>";
    const swE = (k, tipo, on) => '<button class="btn sm tgl sw ' + (on ? "on" : "off") + (tipo === "real" ? " czreal" : "") + '" type="button" role="switch" aria-checked="' + on + '" data-czent="' + k + '" data-czt="' + tipo + '">' + (on ? "Ligado" : "Desligado") + "</button>";
    box.innerHTML = estado +
      '<p class="small" style="margin:12px 0 4px"><b>Entradas</b> <span class="muted">· ligue a FICTÍCIA, a REAL ou as duas em cada uma · cada entrada compra e é medida separada</span></p><div class="czents">' +
      ["a", "b", "c"].map((k) => { const x = CZ_ENT[k], e = E[k] || {}, on = ents.includes(k), ron = rents.includes(k);
        return '<div class="czent' + (on || ron ? " on" : "") + '"><b><i>' + k.toUpperCase() + "</i>" + esc(x[0]) + "</b><span>" + esc(x[1]) + "</span><span>" + esc(x[2]) + "</span>" +
          (e.entradas != null ? "<em>" + num(e.entradas, 0) + " entradas no período · " + num(e.x10 || 0, 0) + " chegaram a 10× · " + num(e.x100 || 0, 0) + " a 100×</em>" : "") +
          '<div class="czsws"><label><span class="tag sim">FICTÍCIA</span>' + swE(k, "sim", on) + '</label><label><span class="tag real">REAL</span>' + swE(k, "real", ron) + "</label></div></div>"; }).join("") + "</div>" +
      '<p class="small" style="margin:12px 0 0"><b>Valores e saída das compras</b> <span class="muted">· salva sozinho ao sair do campo · valem para A, B e C · na REAL o valor de cada compra é o da carteira REAL</span></p>' +
      // 0.32.505 (pedido do dono): com a REAL no topo, o campo do valor é o da carteira REAL (é ele que a compra REAL do Caçador usa)
      '<div class="czgrid">' + CZ_IN.map((x) => { const rv = REAL && x[0] === "cz_eth", k = rv ? "real_eth_por_compra" : x[0], val = rv ? ((P.real_cfg || {}).real_eth_por_compra) : c[x[0]];
        return '<label class="czin"><span>' + esc(x[1]) + (x[0] === "cz_eth" ? (rv ? " (REAL · o mesmo da carteira REAL)" : " (FICTÍCIA)") : "") + '</span><span class="bmin"><input class="in" type="number" data-czn="' + k + '" min="' + (rv ? 0.0001 : x[3]) + '" max="' + (rv ? 0.5 : x[4]) + '" step="' + x[5] + '" value="' + esc(val) + '"><em>' + x[2] + "</em></span>" +
        (x[0] === "cz_eth" ? '<small class="muted czusd">' + esc(usdOf(val)) + "</small>" : "") + "</label>"; }).join("") + "</div>" +
      // 0.32.503 (pedido do dono): nunca vender 100% no alvo; guarda X% (hold) caso o token exploda
      '<div class="czrow czhold"><span><b>Guardar uma parte no alvo (hold)</b><small>' + (c.cz_hold_on ? "ligado: quando bater o alvo, vende " + num(100 - (+c.cz_hold_pct || 20), 0) + "% e guarda " + num(+c.cz_hold_pct || 20, 0) + "%. A parte guardada não tem stop nem tempo: fica em Carteira → Shitcoin hold até você vender." : "desligado: no alvo vende 100%.") + " Vale para A, B e C, na FICTÍCIA e na REAL.</small>" +
        '<span class="seg czholdp">' + [10, 20, 30, 40, 50, 60, 70, 80, 90].map((v) => '<button type="button" data-czhold="' + v + '" class="' + (+c.cz_hold_pct === v ? "on" : "") + '">' + v + "%</button>").join("") + "</span></span>" +
        '<button class="btn tgl sw ' + (c.cz_hold_on ? "on" : "off") + '" type="button" role="switch" aria-checked="' + !!c.cz_hold_on + '" data-czk="cz_hold_on">' + (c.cz_hold_on ? "Ligado" : "Desligado") + "</button></div>";
  }
  async function czSave(body) {
    const r = await BB.api("/api/hood/conta", { body, quiet: true });
    if (r && r.error) { alert(r.error); return; }
    if (P && r && r.cfg) P.cfg_sim = r.cfg;
    czBuyDraw(); drawTrCopia();
  }
  // 0.32.491 (pedido do dono: "mostra Fechadas 2, mas quais 2?"): cada resultado vira um cartão; "ver as N" abre as entradas que contaram
  const CZ_OPEN = {};
  const czLim = (v) => (v ? "até +" + num(v, 0) + "%" : "sem limite");
  const czCombo = (x) => "entrada " + czLim(x[0]) + " · alvo +" + num(x[1], 0) + "% · stop −" + num(x[2], 0) + "%";
  function czGridDraw() {
    const G = (CZ && CZ.grade) || {}, c = (P && P.cfg_sim) || {};
    CZG = CZG || c.cz_entrada || "b";
    document.querySelectorAll("#czGk button").forEach((b) => { b.classList.toggle("on", b.dataset.czg === CZG); b.textContent = b.dataset.czg.toUpperCase() + " · " + CZ_ENT[b.dataset.czg][0].toLowerCase(); });
    const g = G[CZG], box = $("czGr");
    if (!box) return;
    if (!g || !(g.grupos || []).length) {
      $("czGSt").textContent = g ? num(g.entradas, 0) + " entradas com as marcas de alvo e stop" : "";
      if ($("czUso")) $("czUso").innerHTML = "";
      box.innerHTML = '<p class="muted">Ainda sem entrada ' + CZG.toUpperCase() + " fechada com as marcas novas (cada uma precisa de até 24 h depois de entrar).</p>"; table("czGT", ["—"], [], "Ainda sem dados."); return;
    }
    $("czGSt").textContent = num(g.entradas, 0) + " entradas " + CZG.toUpperCase() + " com as marcas de alvo e stop no período";
    // 0.32.502 (pedido do dono: "como sei qual está sendo usada?"): os números das suas compras (bloco 1) e se esta entrada está ligada
    const usoC = [+(c.cz_entrada_max_pct || 0), +(c.cz_alvo_pct || 0), +(c.cz_stop_pct || 0)];
    const fOn = !!c.cz_on && String(c.cz_ents == null ? (c.cz_entrada || "b") : c.cz_ents).includes(CZG), rOn = String(c.cz_real_ents || "").includes(CZG);
    const ligada = fOn || rOn, onde = [fOn ? "FICTÍCIA" : "", rOn ? "REAL" : ""].filter(Boolean).join(" e ");
    const isUso = (x) => x.combos.some((y) => y[0] === usoC[0] && y[1] === usoC[1] && y[2] === usoC[2]);
    const achou = g.grupos.findIndex(isUso);
    $("czUso").innerHTML = '<div class="czstate ' + (ligada ? "on" : "off") + '"><b>Em uso nas suas compras:</b> ' + esc(czCombo(usoC)) + " · " +
      (ligada ? "entrada " + CZG.toUpperCase() + " ligada na " + onde : "a entrada " + CZG.toUpperCase() + " está desligada, então nenhuma combinação dela está comprando agora") +
      (achou >= 0 ? " · é a <b>#" + (achou + 1) + "</b> da lista (borda amarela)" : " · <b>não está entre as 10 melhores</b> desta entrada") + "</div>";
    box.innerHTML = g.grupos.map((x, i) => {
      const k = CZG + i, aberto = !!CZ_OPEN[k], s = x.sugerida, mais = x.combos.length - 1, uso = i === achou;
      return '<div class="abc' + (uso ? " czuso" : "") + '">' + (uso ? '<span class="tag czusotag">' + (ligada ? "EM USO · " + onde : "SEUS NÚMEROS · entrada desligada") + "</span>" : "") + '<div class="abc-t"><b>#' + (i + 1) + '</b><span class="sp"></span><span class="czres">' + usd(x.resultado_usd, 2) + "</span></div>" +
        '<div class="czsug"><b>' + esc(czCombo(s)) + "</b>" + (mais > 0 ? '<br><small class="muted">e mais ' + mais + " combinaç" + (mais > 1 ? "ões" : "ão") + " com o mesmo resultado</small>" : "") + "</div>" +
        '<div class="abc-n"><div><small>Fechadas</small><b>' + num(x.n, 0) + '</b></div><div><small>Acerto</small><b>' + num(x.acerto, 0) + '%</b></div><div><small>Por entrada</small><b>' + usd(x.por_entrada_usd, 3) + "</b></div></div>" +
        '<div class="row" style="gap:6px;flex-wrap:wrap"><button class="btn sm" type="button" data-czits="' + k + '" aria-expanded="' + aberto + '">' + (aberto ? "Esconder" : "Ver as " + num(x.n, 0)) + "</button>" +
        '<button class="btn sm primary" type="button" data-czuse="' + s.join(":") + '" title="Copia esta entrada, alvo e stop para as suas compras FICTÍCIAS do Caçador (bloco 1). Não compra nada agora.">Usar estes %</button></div>' +
        (aberto ? '<ul class="czits">' + (x.itens || []).map((t) => "<li><span>" + tok(t.token, t) + '<small class="muted">entrou há ' + ago(t.t) + (t.x_ini != null ? " · " + num(t.x_ini, 2) + "× do início" : "") +
          (t.x_pico != null ? " · pico " + num(t.x_pico, 2) + "×" : "") + '</small></span><span><b>' + usd(t.resultado_usd, 3) + '</b><small class="muted">' + esc(t.saida) + "</small></span></li>").join("") +
          (x.n > (x.itens || []).length ? '<li class="muted">mostrando as ' + (x.itens || []).length + " mais novas</li>" : "") + "</ul>" +
          (mais > 0 ? '<details class="czdet"><summary>As ' + x.combos.length + " combinações deste resultado</summary><ul class=\"czits\">" + x.combos.map((y) => "<li><span>" + esc(czCombo(y)) + "</span></li>").join("") + "</ul></details>" : "") : "") + "</div>";
    }).join("");
    const t = g.tabela || {};
    $("czGTh").textContent = "Ver a tabela alvo × stop (entrada " + czLim(t.entrada_max_pct) + ")";
    table("czGT", ["Alvo \\ Stop"].concat((t.stops || []).map((d) => "−" + d + "%")), (t.linhas || []).map((ln, i) => ["+" + t.alvos[i] + "%"].concat(ln.map((x) => (x ? usd(x.resultado_usd, 3) + '<br><small class="muted">' + x.n + " · " + num(x.acerto, 0) + "%</small>" : "—")))),
      "Ainda sem dados.");
  }
  // 0.32.492 (pedido do dono: "Fechadas 76, 32, 14, 7: quero clicar para ver" e melhorar o visual): uma saída fixa por cartão, a melhor
  // com borda; "Ver as N" abre as entradas que contaram, com o resultado de cada uma
  let CZS = null;
  const CZS_OPEN = {};
  const CZ_SAIDA_TXT = { "1": "vende 1 h depois de entrar", "6": "vende 6 h depois de entrar", "24": "vende 24 h depois de entrar", x2: "vende quando dobrar; senão no preço das 24 h",
    x5: "vende em 5×; senão no preço das 24 h", x10: "vende em 10×; senão no preço das 24 h", x100: "vende em 100×; senão no preço das 24 h" };
  function czEntRow(t, code) {
    return "<li><span>" + tok(t.token, t) + '<small class="muted">entrou há ' + ago(t.t) + (t.x_ini != null ? " · " + num(t.x_ini, 2) + "× do início" : "") + (t.x_pico != null ? " · pico " + num(t.x_pico, 2) + "×" : "") +
      (t.liquidez_tirada ? ' · <span class="down">liquidez tirada</span>' : "") + (t.venda_travada ? ' · <span class="down">venda travada</span>' : "") + "</small></span><span><b>" + usd(t.r[code], 3) + "</b></span></li>";
  }
  function czSaidaDraw() {
    const E = ((CZ && CZ.estudo) || {}).estrategias || {}, box = $("czS"); if (!box) return;
    CZS = CZS || CZG || ((P && P.cfg_sim) || {}).cz_entrada || "a";
    document.querySelectorAll("#czSk button").forEach((b) => b.classList.toggle("on", b.dataset.czs === CZS));
    const x = E[CZS] || {}, L = (CZ && CZ.entradas && CZ.entradas[CZS]) || [];
    $("czSSum").textContent = num(x.entradas || 0, 0) + " entradas · liquidez tirada em " + num(x.liquidez_tirada || 0, 0) + " · venda travada em " + num(x.venda_travada || 0, 0);
    const S = (x.saidas || []), bestR = S.filter((r) => r.n).reduce((a, r) => (a == null || r.resultado_usd > a ? r.resultado_usd : a), null);
    box.innerHTML = S.length ? S.map((r) => {
      const k = CZS + ":" + r.saida, aberto = !!CZS_OPEN[k], its = L.filter((t) => t.r && t.r[r.saida] != null);
      return '<div class="abc' + (r.n && r.resultado_usd === bestR ? " best" : "") + '"><div class="abc-t"><b>' + esc(r.nome) + '</b><span class="sp"></span><span class="czres">' + (r.n ? usd(r.resultado_usd, 2) : '<span class="muted">—</span>') + "</span></div>" +
        '<div class="czx">' + esc(CZ_SAIDA_TXT[r.saida] || "") + (r.n && r.resultado_usd === bestR ? ' · <b class="up">a melhor</b>' : "") + "</div>" +
        '<div class="abc-n"><div><small>Fechadas</small><b>' + num(r.n, 0) + '</b></div><div><small>Acerto</small><b>' + (r.acerto == null ? "—" : num(r.acerto, 0) + "%") + '</b></div><div><small>Investido</small><b>US$ ' + num(r.investido_usd, 2) + "</b></div></div>" +
        (r.n ? '<div class="czx">melhor entrada: ' + usd(r.melhor_usd, 3) + "</div>" : '<div class="czx">nenhuma fechou ainda' + (/^\d/.test(r.saida) ? " (precisa de " + r.saida + " h depois da entrada)" : "") + "</div>") +
        (r.n ? '<div class="row" style="gap:6px"><button class="btn sm" type="button" data-czsx="' + k + '" aria-expanded="' + aberto + '">' + (aberto ? "Esconder" : "Ver as " + num(r.n, 0)) + "</button></div>" : "") +
        (aberto ? '<ul class="czits">' + its.slice(0, 60).map((t) => czEntRow(t, r.saida)).join("") + (its.length > 60 ? '<li class="muted">mostrando as 60 mais novas</li>' : "") +
          (its.length < r.n ? '<li class="muted">a lista mostra as ' + its.length + " mais novas guardadas</li>" : "") + "</ul>" : "") + "</div>";
    }).join("") : '<p class="muted">Nenhuma entrada fechou no período ainda.</p>';
  }
  function drawCz() {
    czBuyDraw(); czGridDraw();
    document.querySelectorAll("#czD button").forEach((b) => b.classList.toggle("on", Number(b.dataset.czd) === CZD));
    if (!CZ) { kpis("czK", [["Caçador", "carregando…", "", ""]]); return; }
    if (CZ.ligado === false) { kpis("czK", [["Caçador", "desligado", "leitura da Robinhood desligada no servidor", ""]]); return; }
    const st = CZ.status || {}, es = CZ.estudo || {}, E = es.estrategias || {};
    $("czSt").textContent = "observando " + num(st.observando, 0) + " pools · " + num(st.fechados, 0) + " já fechados (24 h)" + (st.arquivo ? "" : " · sem arquivo: zera no reinício") + (st.erro ? " · " + st.erro : "");
    const best = (k) => { const r = ((E[k] || {}).saidas || []).filter((x) => x.n); return r.length ? r.reduce((a, b) => (b.resultado_usd > a.resultado_usd ? b : a)) : null; };
    const bb = best("b");
    kpis("czK", [["Pools novos pagos em ETH", num(es.pools, 0), num(es.com_troca, 0) + " tiveram troca", "tr"],
      ["Explosões de 100×+", num((es.explosoes || []).length, 0), "desde o preço inicial do pool", "up"],
      ["Entradas B (com sinais)", num((E.b || {}).entradas, 0), num((E.b || {}).x10, 0) + " chegaram a 10× · " + num((E.b || {}).x100, 0) + " a 100×", "usr"],
      ["Melhor saída da B", bb ? usd(bb.resultado_usd, 2) : "—", bb ? bb.nome + " · " + bb.n + " entradas · acerto " + num(bb.acerto, 0) + "%" : "esperando entradas fecharem", bb && bb.resultado_usd > 0 ? "up" : "down"]]);
    czSaidaDraw();
    table("czX", ["Token", "Nasceu", "Pico desde o início", "A entrada B pegou?", "Travas"], (es.explosoes || []).map((x) => [tok(x.token, x), "há " + ago(x.t) + '<br><small class="muted">' + hora(x.t) + "</small>",
      xx(x.x_pico), x.b_entrou ? '<span class="tag win">sim</span> entrou em ' + xx(x.b_x_ini) : '<span class="tag neutral">não</span>', czTraps(x.travas)]), "Nenhuma explosão de 100× no período ainda.");
    table("czT", ["Token", "Nasceu", "Compras × vendas", "Agora", "Entrada A", "Entrada B", "Travas"], (CZ.agora || []).map((x) => [tok(x.token, x) + '<br><small class="muted">criação ' + txl(x.tx) + "</small>",
      "há " + ago(x.t), num(x.compras, 0) + " × " + num(x.vendas, 0) + '<br><small class="muted">' + num(x.compradores, 0) + " compradores · " + num(x.entrou_eth, 4) + " ETH</small>",
      xx(x.x_agora) + (x.valor_usd != null ? '<br><small class="muted">valor ≈ US$ ' + num(x.valor_usd, 0) + "</small>" : ""), czEnt(x.a), czEnt(x.b), czTraps(x.travas)]), "Nenhum pool novo com troca ainda (a lista começa a encher depois que o servidor sobe).");
  }
  // 0.32.504 (pedido do dono): endereços que fizeram rug pull (quem criou o token e quem tinha a liquidez) — nunca mais compramos deles
  function drawRug() {
    const box = $("rugBox"); if (!box) return;
    const R = (P && P.rug) || {}, L = Object.entries(R).sort((a, b) => (b[1].t || 0) - (a[1].t || 0));
    $("fxRugB").textContent = "Rug pull bloqueados" + (L.length ? " (" + L.length + ")" : "");
    box.innerHTML = '<div class="czsombra"><b>Rug pull bloqueados.</b> Quando o criador tira toda a liquidez de um pool em que estávamos, o robô guarda o endereço de quem criou o token e de quem tinha a liquidez. Daí em diante a cópia, o Caçador e o botão Comprar <b>nunca mais compram</b> token criado por eles (vale para todas as contas). Dá para bloquear um endereço à mão.</div>' +
      '<div class="row" style="gap:8px;margin:12px 0;flex-wrap:wrap"><input class="in" id="rugAdd" placeholder="0x… endereço para bloquear" style="flex:1 1 320px;min-width:min(420px,100%);max-width:520px"><button class="btn sm" type="button" id="rugAddB">Bloquear endereço</button></div>' +
      (L.length ? '<div class="abgrid">' + L.map(([a, r]) => '<div class="abc"><div class="abc-t">' + addr(a) + '<span class="sp"></span><span class="tag loss">' + (r.manual ? "À MÃO" : "RUG PULL") + "</span></div>" +
        '<div class="abc-d">' + esc(r.papel || "") + (r.token ? " · token " + tok(r.token, { simbolo: r.simbolo }) : "") + "</div>" +
        '<div class="muted small">bloqueado ' + hora(r.t) + '</div><button class="btn sm" type="button" data-rugoff="' + esc(a) + '">Desbloquear</button></div>').join("") + "</div>"
        : '<p class="muted">Nenhum endereço bloqueado ainda. O primeiro rug pull de uma posição entra aqui sozinho.</p>');
  }
  function drawFx() {
    const cz = FXT === "cz", rg = FXT === "rug";
    $("rugBox").hidden = !rg;
    if (rg) { $("fxMain").hidden = true; $("czBox").hidden = true; $("fxH").hidden = true; document.querySelectorAll("#fxTab button").forEach((b) => b.classList.toggle("on", b.dataset.fxt === FXT)); drawRug(); return; }
    $("fxMain").hidden = cz; $("czBox").hidden = !cz; $("fxH").hidden = cz;
    if (cz) { document.querySelectorAll("#fxTab button").forEach((b) => b.classList.toggle("on", b.dataset.fxt === FXT)); loadCz(false); return; }
    document.querySelectorAll("#fxH button").forEach((b) => b.classList.toggle("on", Number(b.dataset.fxh) === FXH));
    document.querySelectorAll("#fxTab button").forEach((b) => b.classList.toggle("on", b.dataset.fxt === FXT));
    const bl = new Set(((P && P.cfg_sim && P.cfg_sim.tokens_bloqueados) || []));
    const all = (FX && FX.rows) || [], usd = FX && FX.eth_usd;
    const hpRows = all.filter((x) => fxHp(x) || bl.has(x.token));
    const known = new Set(all.map((x) => x.token));
    const extra = Array.from(bl).filter((t) => !known.has(t)).map((t) => ({ token: t, liquido_eth: null, top: [], seguranca: null, _fora: true }));
    $("fxHpB").textContent = "Honeypot e bloqueadas" + (hpRows.length + extra.length ? " (" + (hpRows.length + extra.length) + ")" : "");
    const rows = FXT === "hp" ? hpRows.concat(extra) : all.filter((x) => !fxHp(x) && !bl.has(x.token)).slice(0, 30);
    const per = FXH < 1 ? Math.round(FXH * 60) + " min" : FXH + " h";
    const tot = rows.reduce((a, x) => a + Math.max(0, x.liquido_eth), 0), comTop = rows.filter((x) => (x.top || []).length).length;
    kpis("fxK", [["Tokens com trade em " + per, num(FX && FX.tokens, 0), "lidos na rede", "tr"],
      ["Entrou líquido nas 30", num(tot, 3) + " ETH", usd ? "≈ US$ " + num(tot * usd, 0) : "", "mon"],
      ["Com top trader comprando", num(comTop, 0), "das 30 da lista", "usr"]]);
    const topCell = (x) => !(x.top || []).length ? '<span class="muted">—</span>' : x.top.slice(0, 3).map((t) => addr(t.wallet) + (t.perigo ? ' <span class="tag loss dzt" title="' + esc(t.perigo) + '">PERIGO · ' + (/honeypot/.test(t.perigo) ? "honeypot" : "robô") + "</span>" : t.copiando ? ' <span class="tag win">copiando</span>' : ' <small class="muted">#' + (t.pos || "?") + "</small>")).join("<br>") + (x.top.length > 3 ? '<br><small class="muted">+' + (x.top.length - 3) + "</small>" : "");
    const sym = {}; rows.forEach((x) => { const k = String(x.simbolo || "").toUpperCase(); if (k) sym[k] = (sym[k] || 0) + 1; });
    table("fxT", ["#", "Token", "Entrou líquido", "Compras × vendas", "Carteiras", "Top traders", "Preço no período", "Visto pela 1ª vez"], rows.map((x, i) => x._fora ? [String(i + 1),
      tok(x.token, x) + '<span class="fxsg"><span class="tag neutral">bloqueada por você</span> <span class="muted">sem trade no período</span></span>' + fxBtns(x, true), "—", "—", "—", "—", "—", "—"] : [String(i + 1),
      tok(x.token, x) + fxSafe(x) + (bl.has(x.token) ? '<span class="fxsg"><span class="tag neutral">bloqueada por você</span></span>' : "") +
      (sym[String(x.simbolo || "").toUpperCase()] > 1 ? '<span class="fxsg"><span class="tag pause" title="outro token da lista tem o mesmo símbolo: pode ser cópia">nome repetido</span></span>' : "") + fxBtns(x, bl.has(x.token)),
      eth(x.liquido_eth, 4) + (x.liquido_usd != null ? '<br><small class="muted">≈ US$ ' + num(x.liquido_usd, 0) + "</small>" : ""),
      num(x.entrou_eth, 4) + " ETH (" + x.compras + ")<br><small class=\"muted\">saiu " + num(x.saiu_eth, 4) + " ETH (" + x.vendas + ")</small>",
      num(x.carteiras, 0) + '<br><small class="muted">' + num(x.vendedores, 0) + " venderam</small>", topCell(x), pct(x.preco_pct),
      x.idade_conhecida ? "há " + ago(x.primeiro_t) : "+24 h"]), FXT === "hp" ? "Nenhuma moeda honeypot ou bloqueada no período." : "Nenhum trade no período ainda.");
  }
  async function loadAdmin(force) {
    if (!force && Date.now() - AD_AT < 30000) return drawAdmin();
    AD_AT = Date.now();
    const r = await BB.api("/api/hood/usuarios", { quiet: true });
    if (r && !r.error) AD = r;
    drawAdmin();
  }
  function drawAdmin() {
    const q = String(($("adQ") && $("adQ").value) || "").toLowerCase().trim();
    const us = ((AD && AD.users) || []).filter((u) => !q || (String(u.nome || "") + " " + String(u.email || "")).toLowerCase().includes(q));
    $("adSub").textContent = us.length + " contas · cópia FICTÍCIA, carteira REAL e chave de cada uma · nunca mostra a chave, só se está salva";
    const quando = (v) => { const t = v ? Date.parse(v) / 1000 : 0; return t ? "há " + ago(t) + '<br><small class="muted">' + hora(t) + "</small>" : "—"; };
    table("adT", ["Usuário", "Categoria", "Situação", "Último acesso", "Desde", "FICTÍCIA", "REAL", "Chave"], us.map((u) => {
      const f = (u.hood && u.hood.ficticia) || null, r = (u.hood && u.hood.real) || {};
      return ['<span class="aduser">' + (u.avatar_url ? '<img src="' + esc(u.avatar_url) + '" alt="" referrerpolicy="no-referrer">' : "") + "<span><b>" + esc(u.nome || "—") + '</b><br><small class="muted">' + esc(u.email || "") + "</small></span></span>",
        u.role === "admin" ? '<span class="tag win">Admin</span>' : '<span class="tag neutral">Usuário</span>',
        u.bloqueado ? '<span class="tag loss">bloqueado</span>' : '<span class="tag win">ativo</span>', quando(u.ultimo_acesso), quando(u.criado_em),
        !f ? '<span class="muted">nunca abriu o /hood</span>' : (f.ligada ? '<span class="tag win">ON</span> ' : '<span class="tag loss">OFF</span> ') + eth(f.resultado, 4) +
          '<br><small class="muted">' + f.fechadas + " fechadas · " + f.abertas + " abertas" + (f.acerto != null ? " · " + num(f.acerto, 0) + "%" : "") + " · taxas " + num(f.taxas, 5) + " · " + f.traders + " traders à mão</small>",
        (r.ligada ? '<span class="tag real">ON</span> ' : '<span class="tag neutral">OFF</span> ') + eth(r.resultado, 5) + '<br><small class="muted">' + (r.fechadas || 0) + " fechadas · " + (r.abertas || 0) + " abertas" + (r.saldo != null ? " · saldo " + num(r.saldo, 5) + " ETH" : "") + "</small>",
        r.chave ? '<span class="tag win">CARTEIRA</span><br>' + addr(r.endereco) : '<span class="muted">sem chave</span>'];
    }), "Nenhum usuário.");
  }
  function draw() {
    drawSys();
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.mode === "real") === REAL));
    if (VIEW === "visao") { drawMy(); drawVisao(); }
    if (VIEW === "posicoes") drawPos();
    if (VIEW === "historico") drawHist();
    if (VIEW === "carteira") { drawCarteira(); drawGas(); loadGas(false); }
    if (VIEW === "traders") drawTraders();
    if (VIEW === "fluxo") { drawFx(); loadFx(false); }
    if (VIEW === "admin") loadAdmin(false);
  }

  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try {
      const [r, p] = await Promise.all([BB.api("/api/hood", { quiet: true }), BB.api("/api/hood/painel" + (REAL ? "?real=1" : ""), { quiet: true })]);
      if (r && !r.error) R = r;
      if (p && !p.error && p.ligado !== false) {
        P = p;
        RISCO = p.riscos || {};
        Object.assign(NOM, p.nomes || {});
        (p.posicoes || []).concat(p.trades || []).forEach((x) => { if (x.token && (x.simbolo || x.nome)) NOM[x.token] = { nome: x.nome || "", simbolo: x.simbolo || "" }; });
      }
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
  document.addEventListener("change", (e) => {
    if (e.target && e.target.name === "gaO") { GA_PICK = e.target.value; gaConv(); gaAuto(); }
    if (e.target && e.target.id === "cmpSel") { CMP_UID = e.target.value || null; CMP_PLAN = null; try { localStorage.setItem("hood_cmp", CMP_UID || ""); } catch (x) { /* */ } CMP = null; loadCmp(true); }
  });
  document.addEventListener("input", (e) => {
    const t = e.target && e.target.closest ? e.target : null; if (!t) return;
    if (t.id === "gaUsd") { gaConv(); gaAuto(); }
    if (t.id === "adQ") drawAdmin();
    if (t.closest("#hdCfg")) DIRTY = true;
    if (t.id === "cvEth" || t.id === "cvUsd") { conv(t.id === "cvEth" ? "eth" : "usd"); return; }
    if (t.closest("#cfRows") && t.type === "number") usdHints();
    if (t.closest("#cfRows") && t.id.startsWith("cf_")) { CF_DIRTY = true; autoSave("cf"); }
    if (t.closest("#cfRows") && t.id.startsWith("rl_")) { RL_DIRTY = true; autoSave("rl"); }
  });
  // 0.32.287 (pedido do dono): os valores salvam sozinhos (0,8 s depois de parar de digitar) e aparece "Salvo." em verde
  const SAVE_T = {};
  function autoSave(which) {
    clearTimeout(SAVE_T[which]);
    SAVE_T[which] = setTimeout(async () => {
      const real = which === "rl";
      // 0.32.508 (caso do dono: "coloquei 0.001 na REAL e voltou para 0.0002"; "troco num lugar e tenho que mudar no outro"): manda só as
      // opções que mudaram na tela; antes mandava todas e o valor antigo de um campo desta tela apagava o que foi salvo em outra
      const all = real ? vals("rl_", RL_INFO, RL_BOOL) : vals("cf_", CF_INFO, CF_BOOL), cur = (P && (real ? P.real_cfg : P.cfg_sim)) || {};
      const body = {}; Object.keys(all).forEach((k) => { if (cur[k] === undefined || String(cur[k]) !== String(all[k])) body[k] = all[k]; });
      if (!Object.keys(body).length) { if (real) RL_DIRTY = false; else CF_DIRTY = false; return; }
      const r = await BB.api(real ? "/api/hood/real/cfg" : "/api/hood/conta", { body, quiet: true });
      if (r && r.error) { alert(r.error); return; }
      if (real) RL_DIRTY = false; else CF_DIRTY = false;
      if (P && r && r.cfg) { if (real) P.real_cfg = r.cfg; else P.cfg_sim = r.cfg; }
      toast("Salvo.");
    }, 800);
  }
  const vals = (pre, info, bools) => {
    const b = {}; info.forEach((x) => { const el = $(pre + x[0]); if (el && el.value !== "") b[x[0]] = Number(el.value); });
    (bools || []).forEach((k) => { const el = $(pre + k); if (el) b[k] = el.classList.contains("on"); });
    return b;
  };
  const setBool = (el, v) => { el.classList.toggle("on", v); el.classList.toggle("off", !v); el.setAttribute("aria-checked", String(v)); el.textContent = v ? "Ligado" : "Desligado"; };
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target.closest("[data-czk],[data-czent],[data-czg],[data-czuse],[data-czits],[data-hif],#hiMore,[data-czs],[data-czsx],[data-hsx],[data-czhold],[data-shsell],#shOpen,#rugAddB,[data-rugoff],[data-czrealon]") : null; if (!t) return;
    if (t.dataset.czrealon != null) {             // 0.32.508: liga a carteira REAL aqui mesmo, sem ir para Carteira
      const w = prompt("Ligar a carteira REAL da Robinhood?\n\nAs entradas do Caçador com REAL ligada passam a comprar com DINHEIRO DE VERDADE (" + num(((P && P.real_cfg) || {}).real_eth_por_compra, 4) + " ETH cada).\n\nDigite LIGAR para confirmar:");
      if (!w) return;
      const r = await post("/api/hood/real", { on: true, confirm: w }, t);
      if (r && r.error) { alert(r.error); return; }
      toast("Carteira REAL ligada"); P = null; return load();
    }
    if (t.dataset.czhold) { czSave({ cz_hold_pct: +t.dataset.czhold }); return; }
    if (t.id === "rugAddB" || t.dataset.rugoff) {
      const on = t.id === "rugAddB", a = on ? String($("rugAdd").value || "").trim() : t.dataset.rugoff;
      if (on && !/^0x[0-9a-fA-F]{40}$/.test(a)) { alert("Cole um endereço 0x… válido."); return; }
      if (!on && !confirm("Desbloquear este endereço? A cópia e o Caçador voltam a poder comprar tokens dele.")) return;
      const r = await post("/api/hood/rug", { addr: a, on }, t);
      if (r && r.error) { alert(r.error); return; }
      if (P && r && r.rug) P.rug = r.rug;
      drawRug(); return;
    }
    if (t.id === "shOpen") { SH_OPEN = !SH_OPEN; drawHold(); return; }
    if (t.dataset.shsell) { openShSell(t.dataset.shsell, t.dataset.shreal === "1"); return; }
    if (t.dataset.czs) { CZS = t.dataset.czs; czSaidaDraw(); return; }
    if (t.dataset.hsx) { const [k, x] = t.dataset.hsx.split(":"); HSX[k] = x; drawHist(); return; }
    if (t.dataset.czsx) { CZS_OPEN[t.dataset.czsx] = !CZS_OPEN[t.dataset.czsx]; czSaidaDraw(); return; }
    if (t.dataset.czits) { CZ_OPEN[t.dataset.czits] = !CZ_OPEN[t.dataset.czits]; czGridDraw(); return; }
    if (t.dataset.hif) { HIF = t.dataset.hif; HI_N = 40; try { localStorage.setItem("hood_hif", HIF); } catch (x) { /* */ } if (VIEW === "historico") drawHist(); return; }
    if (t.id === "hiMore") { HI_N += 40; drawHist(); return; }
    const c = (P && P.cfg_sim) || {};
    if (t.dataset.czk) {
      const k = t.dataset.czk, on = k === "copia_traders" ? c.copia_traders === false : k === "cz_hold_on" ? !c.cz_hold_on : !c.cz_on;
      const ents = String(c.cz_ents == null ? (c.cz_entrada || "b") : c.cz_ents);
      if (k === "cz_on" && on && !confirm("Ligar as compras FICTÍCIAS pelo Caçador?\n\nCada entrada " + (ents.split("").map((x) => x.toUpperCase()).join(", ") || "(nenhuma ligada)") + " compra " + num(c.cz_eth, 4) + " ETH do saldo fictício, sozinha, e sai pelo alvo, stop e tempo que estão na tela. Nunca compra na REAL.")) return;
      czSave({ [k]: on });
    } else if (t.dataset.czent) {
      const k = t.dataset.czent, real = t.dataset.czt === "real";
      if (real) {
        const cur = String(c.cz_real_ents || ""), liga = !cur.includes(k);
        // 0.32.508 (pedido do dono: "ter que ligar a REAL em 2 cantos não faz sentido"): com a carteira REAL desligada, a mesma
        // confirmação (digitar LIGAR) liga a carteira REAL e a entrada juntas
        const rOn = !!(P && P.real_cfg && P.real_cfg.real_on);
        if (liga && !rOn) {
          const w = prompt("Ligar a REAL na entrada " + k.toUpperCase() + " do Caçador?\n\nA carteira REAL está desligada: isto liga a carteira REAL e a entrada " + k.toUpperCase() + " juntas. Compra com DINHEIRO DE VERDADE o valor por compra da carteira REAL (" + num((P.real_cfg || {}).real_eth_por_compra, 4) + " ETH), sozinha, e vende pelo alvo, stop e tempo do Caçador.\n\nDigite LIGAR para confirmar:");
          if (!w) return;
          const r = await post("/api/hood/real", { on: true, confirm: w }, t);
          if (r && r.error) { alert(r.error); return; }
          if (P && P.real_cfg) P.real_cfg.real_on = true;
        } else if (liga && !confirm("Ligar a REAL na entrada " + k.toUpperCase() + " do Caçador?\n\nIsto compra com DINHEIRO DE VERDADE: cada entrada " + k.toUpperCase() + " compra na carteira REAL o valor por compra da carteira REAL, sozinha, e vende pelo alvo, stop e tempo do Caçador.")) return;
        czSave({ cz_real_ents: "abc".split("").filter((x) => (x === k ? liga : cur.includes(x))).join("") });
      } else {
        const cur = c.cz_on ? String(c.cz_ents == null ? (c.cz_entrada || "b") : c.cz_ents) : "";
        const nv = "abc".split("").filter((x) => (x === k ? !cur.includes(x) : cur.includes(x))).join("");
        czSave({ cz_ents: nv, cz_on: nv.length > 0, cz_entrada: nv[0] || c.cz_entrada || "b" });
      }
    }
    else if (t.dataset.czg) { CZG = t.dataset.czg; czGridDraw(); }
    else if (t.dataset.czuse) {
      const [mx, up, dn] = t.dataset.czuse.split(":").map(Number);
      const cur = c.cz_on ? String(c.cz_ents == null ? (c.cz_entrada || "b") : c.cz_ents) : "";
      if (!confirm("Copiar estes números para as compras do Caçador?\n\n• só entra até " + (mx ? "+" + mx + "%" : "qualquer altura") + " acima do preço inicial do pool\n• vende tudo no alvo de +" + up + "%\n• stop de perda de −" + dn + "%\n• liga a FICTÍCIA da entrada " + CZG.toUpperCase() + "\n\nIsto NÃO compra nada agora: vale para as próximas compras. A REAL não é ligada por aqui.")) return;
      czSave({ cz_entrada_max_pct: mx, cz_alvo_pct: up, cz_stop_pct: dn, cz_on: true, cz_ents: cur.includes(CZG) ? cur : "abc".split("").filter((x) => x === CZG || cur.includes(x)).join("") });
    }
  });
  // 0.32.505 (pedido do dono: "digito outro valor e o dólar embaixo não muda"): o dólar segue o que está sendo digitado
  document.addEventListener("input", (e) => {
    const k = e.target && e.target.dataset && e.target.dataset.czn; if (k !== "cz_eth" && k !== "real_eth_por_compra") return;
    const u = e.target.closest("label") && e.target.closest("label").querySelector(".czusd"); if (!u) return;
    const v = parseFloat(String(e.target.value).replace(",", "."));
    u.textContent = isFinite(v) ? (usdOf(v) || "") : "";
  });
  document.addEventListener("change", async (e) => {
    const k = e.target && e.target.dataset && e.target.dataset.czn; if (!k) return;
    const v = parseFloat(String(e.target.value).replace(",", "."));
    if (!isFinite(v)) return;
    e.target.blur();
    if (k.startsWith("real_")) {                  // 0.32.505: valor da carteira REAL pelo Caçador
      const r = await BB.api("/api/hood/real/cfg", { body: { [k]: v }, quiet: true });
      if (r && r.error) { alert(r.error); return; }
      if (P && r && r.cfg) P.real_cfg = r.cfg;
      czBuyDraw(); toast("Valor por compra da REAL: " + num(v, 4) + " ETH"); return;
    }
    czSave({ [k]: v });
  });
  async function post(url, body, btn) {
    if (btn) btn.disabled = true;
    try { return await BB.api(url, { body }); } finally { if (btn) btn.disabled = false; }
  }
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target.closest("button,a") : null; if (!t) return;
    if (t.dataset.mode) { REAL = t.dataset.mode === "real"; try { localStorage.setItem("hood_mode", REAL ? "real" : "sim"); } catch (x) { /* */ } P = null; draw(); load(); return; }
    if (t.dataset.block) {
      const on = t.dataset.on === "1";
      if (on && !confirm("Bloquear este trader? Ele para de ser copiado (FICTÍCIA e REAL) e vai para a aba Bloqueados.")) return;
      const r = await post("/api/hood/bloquear", { wallet: t.dataset.block, on }, t);
      if (r && r.error) { alert(r.error); return; }
      if (P && P.cfg_sim) { P.cfg_sim.bloqueados = r.bloqueados; P.cfg_sim.manual = r.manual; P.cfg_sim.modo = r.modo; }
      toast(on ? "Bloqueado: foi para a aba Bloqueados." : "Desbloqueado.");
      draw(); return load();
    }
    if (t.dataset.follow) {
      const on = t.dataset.on === "1", m = t.dataset.modo || "ambas";
      const realOn = !!(P && P.real_status && P.real_status.ligada);
      if (on && m !== "sim" && realOn && !confirm("As compras deste trader vão para a carteira REAL (dinheiro de verdade). Copiar?")) return;
      const r = await post("/api/hood/seguir", { wallet: t.dataset.follow, on, modo: m }, t);
      if (r && r.error) { alert(r.error); return; }
      if (P && P.cfg_sim) { P.cfg_sim.manual = r.manual; P.cfg_sim.modo = r.modo; }
      toast(!on ? "Parou de copiar este trader." : m === "sim" ? "Copiando na FICTÍCIA." : (realOn ? "Copiando " + (m === "real" ? "na REAL." : "na FICTÍCIA e na REAL.") : "Salvo. A REAL está desligada: ligue em Carteira para ela comprar."));
      draw(); return load();
    }
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
    if (t.dataset.copyaddr) {
      try { await navigator.clipboard.writeText(t.dataset.copyaddr); toast("Endereço copiado."); } catch (x) { prompt("Copie o endereço:", t.dataset.copyaddr); }
      return;
    }
    if (t.id === "cfZerar") {
      const w = (P && !REAL && P.carteira) || {};
      const ok = prompt("Zerar a carteira FICTÍCIA da Robinhood?\n\nApaga as posições abertas, todo o histórico e os eventos da FICTÍCIA e volta o saldo para o saldo inicial. Valores da cópia, traders e a REAL não mudam. Não dá para desfazer.\n\nDigite ZERAR para confirmar:");
      if (!ok) return;
      const r = await post("/api/hood/conta/zerar", { confirma: ok }, t);
      if (r && r.error) { alert(r.error); return; }
      toast("Fictícia zerada: " + r.abertas + " abertas e " + r.fechadas + " fechadas apagadas · saldo " + num(r.saldo, 4) + " ETH");
      P = null; return load();
    }
    if (t.dataset.cmpgo) return cmpPlan(t.dataset.cmpgo);
    if (t.dataset.cmptab) { CMP_TAB = CMP_TAB === t.dataset.cmptab ? null : t.dataset.cmptab; return drawCmp(); }
    if (t.dataset.cmpone) return cmpPlan("one:" + t.dataset.cmpone);
    if (t.dataset.goversao) { e.preventDefault(); const c = $("hiCard"); if (c) c.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (t.id === "cmpOk") return cmpApply(t);
    if (t.id === "cmpNo") { CMP_PLAN = null; return drawCmp(); }
    if (t.dataset.hback) { await hBack(Number(t.dataset.hback), t); return; }
    if (t.id === "hiAll") { HIST_ALL = !HIST_ALL; drawHist(); return; }
    if (t.id === "cmpUndo") { if (confirm("Voltar os valores de antes da última cópia?")) await cmpDoUndo(t); return; }
    if (t.dataset.cveth) { $("cvEth").value = t.dataset.cveth; conv("eth"); return; }
    if (t.dataset.bool && t.closest("#cfRows")) { setBool(t, !t.classList.contains("on")); if (t.id.startsWith("rl_")) RL_DIRTY = true; else CF_DIRTY = true; return autoSave(t.id.startsWith("rl_") ? "rl" : "cf"); }
    if (t.id === "cfReset") { CF_DIRTY = true; const p = (P && P.padrao) || {}; CF_INFO.forEach((x) => { if ($("cf_" + x[0])) $("cf_" + x[0]).value = p[x[0]]; }); CF_BOOL.forEach((k) => { if ($("cf_" + k)) setBool($("cf_" + k), !!p[k]); }); return autoSave("cf"); }
    if (t.id === "rlReset") { RL_DIRTY = true; const p = (P && P.real_padrao) || {}; RL_INFO.forEach((x) => { if ($("rl_" + x[0])) $("rl_" + x[0]).value = p[x[0]]; }); RL_BOOL.forEach((k) => { if ($("rl_" + k)) setBool($("rl_" + k), !!p[k]); }); return autoSave("rl"); }
    if (t.id === "rlKeySave") {
      const v = $("rlKey").value.trim(); if (!v) return;
      const r = await post("/api/hood/chave", { value: v }, t);
      $("rlKey").value = "";
      if (r && r.error) alert(r.error); else toast("Chave salva · carteira " + short(r.endereco));
      GA = null; drawGas(); loadGas(true);
      return load();
    }
    if (t.id === "gaRe") { $("gaP").hidden = true; return loadGas(true); }
    if (t.id === "gaQ") { clearTimeout(GA_TM); t.disabled = true; try { await gaQuote(); } finally { t.disabled = false; } return; }
    if (t.id === "gaGo") {
      if (!GA_Q || Date.now() - GA_QT > (GA_QV - 5) * 1000) {           // cotação vencida: cota de novo e mostra antes de enviar
        const q = await gaQuote();
        if (q && !q.error && !(q.bloqueia && q.bloqueia.length)) toast("A cotação venceu e foi refeita: confira o valor e clique em Enviar de novo.");
        return;
      }
      const r = await post("/api/hood/abastecer/confirmar", { quote_id: GA_Q, confirmar: "ABASTECER" }, t);      // 0.32.287: o dono não quer digitar; o servidor segue conferindo
      if (r && r.error) { drawQuote({ error: r.error }); return; }
      $("gaP").innerHTML = '<span class="up">Enviado. A entrega costuma levar segundos; acompanhe no histórico abaixo.</span>';
      toast("Abastecimento enviado.");
      setTimeout(() => loadGas(true), 4000); setTimeout(() => loadGas(true), 15000); setTimeout(() => loadGas(true), 45000);
      return loadGas(true);
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
    if (t.dataset.fxt) { FXT = t.dataset.fxt; return drawFx(); }
    if (t.dataset.czd) { CZD = Number(t.dataset.czd) || 7; try { localStorage.setItem("hood_czd", String(CZD)); } catch (e) { /* */ } CZ_AT = 0; return loadCz(true); }
    if (t.dataset.fxblock) {
      const on = t.dataset.on === "1";
      if (on && !confirm("Bloquear esta moeda? A cópia e o botão Comprar nunca mais compram ela (vai para Honeypot e bloqueadas).")) return;
      const r = await post("/api/hood/token/bloquear", { token: t.dataset.fxblock, on }, t);
      if (r && r.error) { alert(r.error); return; }
      if (P && P.cfg_sim) P.cfg_sim.tokens_bloqueados = r.tokens_bloqueados;
      toast(on ? "Moeda bloqueada." : "Moeda desbloqueada."); return drawFx();
    }
    if (t.dataset.fxbuy) {
      const m = t.dataset.modo, nm = (NOM[t.dataset.fxbuy] && NOM[t.dataset.fxbuy].simbolo) || short(t.dataset.fxbuy);
      if (!confirm("Comprar " + nm + " agora " + (m === "ambas" ? "na FICTÍCIA e na REAL" : "na " + (m === "real" ? "REAL (dinheiro de verdade)" : "FICTÍCIA")) + ", com o valor por compra da carteira? A saída segue o stop, o stop móvel e o tempo máximo da carteira.")) return;
      const r = await post("/api/hood/token/comprar", { token: t.dataset.fxbuy, modo: m }, t);
      if (r && r.error) { alert(r.error); return; }
      toast([r.ficticia ? "FICTÍCIA: " + r.ficticia : "", r.real ? "REAL: " + r.real : ""].filter(Boolean).join(" · ") || "Enviado.");
      return load();
    }
    if (t.dataset.fxh) { FXH = Number(t.dataset.fxh); try { localStorage.setItem("hood_fxh", String(FXH)); } catch (x) { /* */ } return loadFx(true); }
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
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("sysM").hidden = true; $("shM").hidden = true; } });
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target.closest("[data-shpc],#shGo,#shNo,#shMX,#rlZerar,[data-rlzerar],[data-rhshow]") : null;
    if (!t) { if (e.target && e.target.id === "shM") $("shM").hidden = true; return; }
    if (t.dataset.shpc) { SHV.pc = +t.dataset.shpc; drawShSell(); return; }
    if (t.id === "shNo" || t.id === "shMX") { $("shM").hidden = true; return; }
    if (t.id === "shGo" && SHV) {
      const r = await post("/api/hood/fechar", { id: SHV.id, real: SHV.real, frac: SHV.pc / 100 }, t);
      if (r && r.error) { alert(r.error); return; }
      $("shM").hidden = true;
      toast("Hold vendido (" + SHV.pc + "%): " + (r && r.trade ? (r.trade.pnl_eth >= 0 ? "+" : "") + num(r.trade.pnl_eth, 5) + " ETH" : "ok"));
      P = null; return load();
    }
    // 0.32.505 (pedido do dono: "zerar o histórico REAL antigo"): esconde (não apaga) o que fechou até agora
    if (t.id === "rlZerar" || t.dataset.rlzerar != null) {
      const ok = prompt("Zerar o histórico REAL da Robinhood?\n\nAs posições REAL fechadas até agora saem do Histórico e dos resultados da tela. Nada é apagado do banco (é registro de dinheiro de verdade) e dá para mostrar de novo no Histórico. Posições abertas e a perda do dia não mudam.\n\nDigite ZERAR para confirmar:");
      if (!ok) return;
      const r = await post("/api/hood/real/historico", { esconder: true, confirma: ok }, t);
      if (r && r.error) { alert(r.error); return; }
      toast("Histórico REAL zerado na tela: " + r.escondidas + " fechadas escondidas");
      P = null; return load();
    }
    if (t.dataset.rhshow != null) {
      const r = await post("/api/hood/real/historico", { esconder: false }, t);
      if (r && r.error) { alert(r.error); return; }
      toast("Histórico REAL antigo mostrado de novo"); P = null; return load();
    }
  });
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
