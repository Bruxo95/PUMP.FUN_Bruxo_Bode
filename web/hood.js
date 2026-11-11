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
    ["trail_ativa_pct", "Stop móvel liga com lucro de", "%", 1, 10000, 1], ["trail_dist_pct", "Stop móvel sai ao cair do pico", "pontos", 1, 1000, 1],
  ];
  const RL_INFO = [
    ["real_eth_por_compra", "ETH por compra na REAL", "ETH", 0.0002, 0.5, 0.0005], ["real_max_abertas", "Posições REAL abertas no máximo", "posições", 1, 30, 1],
    ["real_slip_pct", "Folga de preço na REAL (slippage)", "%", 1, 49, 1], ["real_perda_dia", "Perda do dia que para a REAL", "ETH", 0.0005, 5, 0.001],
    ["real_max_hold_h", "Tempo máximo da posição REAL", "h", 0.1, 168, 0.5], ["real_stop_pct", "Stop de perda da REAL (0 = desligado)", "%", 0, 100, 1],
    ["real_trail_ativa_pct", "Stop móvel da REAL liga com lucro de", "%", 1, 10000, 1], ["real_trail_dist_pct", "Stop móvel da REAL sai ao cair do pico", "pontos", 1, 1000, 1],
  ];
  // 0.32.290 (pedido do dono: "sair quando o desenvolvedor sai da moeda ... stop móvel ... botão de ativar"): opções liga/desliga
  const CF_BOOL = ["sair_trader", "trader_so_lucro", "sair_dev", "trail_on"], RL_BOOL = ["real_sair_trader", "real_trader_so_lucro", "real_sair_dev", "real_trail_on"];
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
  const addr = (a) => (a ? '<a class="hdwho" href="' + esc(ex()) + "/address/" + esc(a) + '" target="_blank" rel="noopener" title="' + esc(a) + '"><img class="bky" alt="" src="' + blockie(a) +
    '"><span><b>' + esc(nick(a)) + '</b><small class="hdaddr">' + esc(short(a)) + "</small></span></a>" : "—");
  // 0.32.290 (pedido do dono: "no token coloque o nome e endereço que nem você fez para os traders"): ícone, símbolo e endereço curto
  const tok = (a, o) => {
    if (!a) return "—";
    const m = (o && (o.simbolo || o.nome)) ? o : (NOM[a] || {});
    const sym = m.simbolo || m.nome || "", nm = m.nome && m.nome !== sym ? m.nome : "";
    return '<a class="hdwho" href="https://dexscreener.com/robinhood/' + esc(a) + '" target="_blank" rel="noopener" title="' + esc((nm ? nm + " · " : "") + a) + '"><img class="bky" alt="" src="' + blockie(a) +
      '"><span><b>' + esc(sym || short(a)) + "</b>" + (sym ? '<small class="hdaddr" style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px">' + esc((nm ? (nm.length > 14 ? nm.slice(0, 13) + "…" : nm) + " · " : "") + short(a)) + "</small>" : "") + "</span></a>";
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
    const man = new Set(((P && P.cfg_sim && P.cfg_sim.manual) || []));
    const autoOn = !(P && P.cfg_sim && P.cfg_sim.auto_top === false);
    // 0.32.287 (pedido do dono): 3 botões por trader: copiar só na FICTÍCIA, só na REAL ou nas 2
    const modo = (P && P.cfg_sim && P.cfg_sim.modo) || {};
    const MODO_TXT = { sim: "FICTÍCIA", real: "REAL", ambas: "As 2" };
    const btn = (r) => {
      const cur = man.has(r.wallet) ? (modo[r.wallet] || "ambas") : null;
      const why = r.eligible ? "" : " (fora da regra: " + (r.flags || []).join(" · ") + ")";
      return '<span class="hdmodes">' + ["sim", "real", "ambas"].map((m) => '<button class="btn sm' + (cur === m ? " on" : "") + '" data-follow="' + esc(r.wallet) + '" data-on="' + (cur === m ? "0" : "1") +
        '" data-modo="' + m + '" title="' + esc(cur === m ? "Parar de copiar este trader" : "Copiar " + (m === "ambas" ? "na FICTÍCIA e na REAL" : "só na " + MODO_TXT[m]) + why) + '">' + MODO_TXT[m] + "</button>").join("") +
        (cur ? '<button class="btn sm" data-follow="' + esc(r.wallet) + '" data-on="0" title="Parar de copiar este trader">Parar</button>' : "") + "</span>";
    };
    const row = (r, i) => [String(i + 1), addr(r.wallet), eth(r.realized_eth), num(r.vol_eth, 3) + " ETH", num(r.trades, 0), r.winrate == null ? "—" : num(r.winrate, 0) + "% (" + r.closed + ")",
      r.wallet_usd == null ? "—" : "US$ " + num(r.wallet_usd, 0), "há " + ago(r.last_t),
      (man.has(r.wallet) ? '<span class="tag win">você copia · ' + MODO_TXT[modo[r.wallet] || "ambas"] + "</span> " : "") + (r.copiaria ? '<span class="tag win">copiando</span>' : r.eligible ? '<span class="tag neutral">' + (r.online ? "apto" : "apto · fora (inativo)") + "</span>"
        : '<span class="muted small">' + esc((r.flags || []).join(" · ")) + "</span>"), btn(r)];
    const H = ["#", "Carteira", "Lucro realizado", "Volume", "Trades", "Acerto", "Saldo", "Último trade", "Situação", ""];
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
  // 0.32.288 (pedido do dono: "os config estão desalinhados e fora de padrão de palavras"): uma linha por opção, FICTÍCIA e REAL lado a
  // lado, mesmos nomes e mesma ordem. [nome, unidade, chave da FICTÍCIA ou null, chave da REAL ou null, motivo de não ter numa delas]
  const CFG_ROWS = [
    ["ETH por compra", "ETH", "eth_por_compra", "real_eth_por_compra"],
    ["Posições abertas no máximo", "posições", "max_abertas", "real_max_abertas"],
    ["Tempo máximo da posição", "h", "max_hold_h", "real_max_hold_h"],
    ["Stop de perda (0 = desligado)", "%", "stop_pct", "real_stop_pct"],
    ["Sair quando o trader sai da moeda", "vende tudo quando o saldo dele no token some", "sair_trader", "real_sair_trader", "", "bool"],
    ["Trader saiu: só vende no lucro", "no prejuízo (já com taxas) segura e vende quando ficar positivo", "trader_so_lucro", "real_trader_so_lucro", "", "bool"],
    ["Sair quando o dev sai da moeda", "vende tudo quando quem criou o token vende metade ou mais", "sair_dev", "real_sair_dev", "", "bool"],
    ["Stop móvel", "liga no lucro e sai se cair do pico (regra da Solana)", "trail_on", "real_trail_on", "", "bool"],
    ["Stop móvel liga com lucro de", "%", "trail_ativa_pct", "real_trail_ativa_pct"],
    ["Stop móvel sai ao cair do pico", "pontos (trava no mínimo +2%)", "trail_dist_pct", "real_trail_dist_pct"],
    ["Folga de preço (slippage)", "%", "slip_pct", "real_slip_pct"],
    ["Perda do dia que para a cópia", "ETH", null, "real_perda_dia", "só na REAL"],
    ["Gás por transação", "ETH", "gas_eth", null, "na REAL é o gás de verdade"],
    ["Saldo inicial", "ETH", "saldo_inicial", null, "na REAL é o saldo da carteira"],
  ];
  function cfgCell(pre, key, info, c, p, na, kind) {
    const col = pre === "cf_" ? " cf-sim" : " cf-real";
    if (!key) return '<div class="cfc na' + col + '">' + esc(na || "—") + "</div>";
    if (kind === "bool") {
      const v = !!c[key];
      return '<div class="cfc' + col + '"><button class="btn tgl sw ' + (v ? "on" : "off") + '" id="' + pre + key + '" type="button" role="switch" data-bool="1" aria-checked="' + v + '">' +
        (v ? "Ligado" : "Desligado") + "</button>" + (p && p[key] !== c[key] ? '<span class="muted">padrão ' + (p[key] ? "ligado" : "desligado") + "</span>" : "") + "</div>";
    }
    const x = info.find((i) => i[0] === key) || [key, "", "", 0, 1e9, "any"];
    return '<div class="cfc' + col + '"><input class="in" id="' + pre + key + '" type="number" min="' + x[3] + '" max="' + x[4] + '" step="' + x[5] + '" value="' + esc(c[key]) +
      '" aria-label="' + esc(x[1]) + '">' + (p && p[key] !== c[key] ? '<span class="muted">padrão ' + esc(p[key]) + "</span>" : "") + "</div>";
  }
  function cfgRows(c, rc) {
    return CFG_ROWS.map((r) => '<div class="cfl">' + esc(r[0]) + "<small>" + esc(r[1]) + "</small></div>" +
      cfgCell("cf_", r[2], CF_INFO, c, P.padrao, r[4], r[5]) + cfgCell("rl_", r[3], RL_INFO, rc, P.real_padrao, r[4], r[5])).join("");
  }
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
      tok(p.token, p), addr(p.wallet), num(p.eth_in, 5) + " ETH" + (p.vendas && p.vendas.length ? '<br><small class="muted">' + p.vendas.length + " vendas parciais</small>" : ""),
      pct(p.pnl_pct) + '<br><small class="muted">preço de ' + (p.px_t ? "há " + ago(p.px_t) : "—") + (p.px_src === "dexscreener" ? " · DexScreener" : "") + "</small>",
      eth(p.pnl_eth, 5), pct(p.best_pct) + ' <small class="muted">pior ' + num(p.worst_pct, 1) + "%</small>",
      p.fecha_em > Date.now() / 1000 ? "em " + dur(p.fecha_em - Date.now() / 1000) : "agora",
      (p.espera ? '<small class="muted">segurando: ' + esc(p.espera.motivo || "trader saiu") + ", vende quando ficar positivo</small><br>" : "") +
      (p.sell_error ? '<small class="down">' + esc(p.sell_error) + "</small><br>" : "") + '<button class="btn sm" data-close="' + esc(p.id) + '"' + (p.selling ? " disabled" : "") + ">" + (p.selling ? "Vendendo…" : "Vender") + "</button>"]),
    REAL ? "Nenhuma posição REAL aberta." : "Nenhuma posição aberta. A cópia compra quando um trader do \"Copiando agora\" comprar.");
  }
  function drawHist() {
    const ts = (P && P.trades) || [], w = (P && P.carteira) || {};
    const pn = ts.reduce((a, x) => a + (x.pnl_eth || 0), 0), win = ts.filter((x) => x.pnl_eth > 0).length;
    kpis("hiK", [["Fechadas " + mtag(), num(ts.length, 0), win + " com lucro", "tr"], ["Resultado das fechadas", eth(pn, 5), "", "tr"],
      ["Acerto", ts.length ? num(100 * win / ts.length, 0) + "%" : "—", "", "usr"], ["Realizado (tudo)", eth(w.realizado, 5), "", "mon"]]);
    table("hiTb", ["Fechou", "Token", "Trader", "Entrou", "Saiu", "Resultado", "Pico", "Motivo"], ts.slice(0, 300).map((x) => [hora(x.close_t) + '<br><small class="muted">ficou ' + dur(x.close_t - x.open_t) + "</small>",
      tok(x.token, x), addr(x.wallet), num(x.eth_in, 5) + " ETH", num(x.eth_out, 5) + " ETH", eth(x.pnl_eth, 5) + "<br>" + pct(x.pnl_pct), pct(x.best_pct),
      esc(x.motivo || "") + (x.tx_out ? " · " + txl(x.tx_out) : "")]), REAL ? "Nenhuma posição REAL fechada ainda." : "Nenhuma posição fechada ainda.");
  }
  function drawCarteira() {
    if (!P) return;
    const c = P.cfg_sim || {}, rc = P.real_cfg || {}, st = P.real_status || {};
    const on = $("cfOn"); on.classList.toggle("on", !!c.on); on.textContent = c.on ? "Ligada" : "Desligada"; on.setAttribute("aria-checked", c.on ? "true" : "false");
    const ro = $("rlOn"); ro.classList.toggle("on", !!st.ligada); ro.textContent = st.ligada ? "Ligada" : "Desligada"; ro.setAttribute("aria-checked", st.ligada ? "true" : "false");
    if (!CF_DIRTY && !RL_DIRTY && !document.activeElement.closest("#cfRows")) $("cfRows").innerHTML = cfgRows(c, rc);
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
  // ------------------------------------------------------------------ 0.32.286: saldo e abastecer de outra rede (Relay)
  let GA = null, GA_AT = 0, GA_BUSY = false, GA_PICK = null, GA_Q = null;
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
      (GA.precisa ? '<br><b class="down">Precisa abastecer:</b> faltam ≈ US$ ' + num(GA.falta_usd, 2) + " para " + 5 + " compras e o gás das vendas. Use \"Abastecer de outra rede\" logo abaixo."
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
    el.innerHTML = "Paga <b>" + num(q.paga, 6) + " " + esc(q.moeda) + "</b> em " + esc(q.origem_nome) + " (US$ " + num(q.usd, 2) + ") · chega <b>" + num(q.recebe, 6) + " ETH</b> na Robinhood (≈ US$ " + num(q.usd_recebe, 2) + ")" +
      "<br>Taxa da ponte ≈ " + num(q.taxa_pct, 2) + "% · gás na origem ≈ US$ " + num(q.gas_usd, 3) + " · entrega em ~" + num(q.tempo_s || 0, 0) + " s" +
      (q.avisos && q.avisos.length ? '<br><span class="warn">' + q.avisos.map(esc).join(" · ") + "</span>" : "") +
      (q.bloqueia && q.bloqueia.length ? '<br><b class="down">Não dá para enviar: ' + q.bloqueia.map(esc).join(" · ") + "</b>"
        : '<div class="row" style="margin-top:10px;flex-wrap:wrap;gap:8px"><button class="btn primary" id="gaGo" type="button">Abastecer agora</button><small class="muted">cotação vale ' + num(q.validade_s, 0) + " s</small></div>");
  }
  function draw() {
    drawSys();
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.mode === "real") === REAL));
    if (VIEW === "visao") { drawMy(); drawVisao(); }
    if (VIEW === "posicoes") drawPos();
    if (VIEW === "historico") drawHist();
    if (VIEW === "carteira") { drawCarteira(); drawGas(); loadGas(false); }
    if (VIEW === "traders") drawTraders();
  }

  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try {
      const [r, p] = await Promise.all([BB.api("/api/hood", { quiet: true }), BB.api("/api/hood/painel" + (REAL ? "?real=1" : ""), { quiet: true })]);
      if (r && !r.error) R = r;
      if (p && !p.error && p.ligado !== false) {
        P = p;
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
  document.addEventListener("change", (e) => { if (e.target && e.target.name === "gaO") { GA_PICK = e.target.value; gaConv(); $("gaP").hidden = true; } });
  document.addEventListener("input", (e) => {
    const t = e.target && e.target.closest ? e.target : null; if (!t) return;
    if (t.id === "gaUsd") { gaConv(); $("gaP").hidden = true; }
    if (t.closest("#hdCfg")) DIRTY = true;
    if (t.closest("#cfRows") && t.id.startsWith("cf_")) { CF_DIRTY = true; autoSave("cf"); }
    if (t.closest("#cfRows") && t.id.startsWith("rl_")) { RL_DIRTY = true; autoSave("rl"); }
  });
  // 0.32.287 (pedido do dono): os valores salvam sozinhos (0,8 s depois de parar de digitar) e aparece "Salvo." em verde
  const SAVE_T = {};
  function autoSave(which) {
    clearTimeout(SAVE_T[which]);
    SAVE_T[which] = setTimeout(async () => {
      const real = which === "rl";
      const body = real ? vals("rl_", RL_INFO, RL_BOOL) : vals("cf_", CF_INFO, CF_BOOL);
      if (!Object.keys(body).length) return;
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
  async function post(url, body, btn) {
    if (btn) btn.disabled = true;
    try { return await BB.api(url, { body }); } finally { if (btn) btn.disabled = false; }
  }
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target.closest("button,a") : null; if (!t) return;
    if (t.dataset.mode) { REAL = t.dataset.mode === "real"; try { localStorage.setItem("hood_mode", REAL ? "real" : "sim"); } catch (x) { /* */ } P = null; draw(); load(); return; }
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
    if (t.id === "gaQ") {
      if (!GA_PICK) { alert("Nenhuma rede de origem com saldo."); return; }
      GA_Q = null;
      const r = await post("/api/hood/abastecer/cotar", { origem: GA_PICK, usd: Number($("gaUsd").value) }, t);
      if (r && r.quote_id) GA_Q = r.quote_id;
      drawQuote(r || { error: "sem resposta" }); return;
    }
    if (t.id === "gaGo") {
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
