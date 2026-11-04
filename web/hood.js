// 0.32.208 (pedido do dono, 04/11): painel da Robinhood Chain, isolado da pump.fun e da BNB (página /hood, arquivo próprio,
// rotas /api/hood). Etapa 1: só lê a rede e monta o ranking dos traders de memecoin pela regra do Top traders.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = { visao: ["Visão geral", "o que a Robinhood Chain está negociando agora"], traders: ["Top traders", "ranking dos traders de memecoin e a regra"] };
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
      ["RPC grátis", esc(s.rpc || "—") + " · " + num(s.chamadas, 0) + " consultas desde " + hora(s.desde) + (s.limite_429 ? " · " + num(s.limite_429, 0) + " vezes pediu para esperar" : "")],
      ["Bloco", num(s.bloco, 0) + " · lido até " + num(s.lido_ate, 0) + " · atraso " + (s.atraso_s == null ? "—" : num(s.atraso_s, 1) + " s")],
      ["Último trade lido", ago(s.ultimo_trade_t) + " · " + hora(s.ultimo_trade_t)],
      ["Trocas lidas", num(s.trocas, 0) + " · viraram trade: " + num((s.trocas || 0) - (s.fora_rota || 0) - (s.fora_outro || 0), 0) + " · rota com vários pools: " + num(s.fora_rota, 0) + " · sem trader ou memecoin claro: " + num(s.fora_outro, 0)],
      ["Últimas 24 h", num(s.trades_24h, 0) + " trades · " + num(s.compras_24h, 0) + " compras · " + num(s.carteiras_24h, 0) + " carteiras · " + num(s.tokens_24h, 0) + " tokens"],
      ["Pago em (24 h)", Object.entries(s.moedas_24h || {}).map((x) => esc(x[0] === "USD" ? "USDG" : x[0]) + " " + num(x[1], 0)).join(" · ") || "—"],
      ["Ranking", num(rk.aptos, 0) + " aptos · " + num((rk.copiaria || []).length, 0) + " copiaria agora"],
      ["ETH em dólar", s.eth_usd ? "US$ " + num(s.eth_usd, 2) + " (DexScreener)" : "—"],
      ["Memória", num(s.trades_memoria, 0) + " trades (últimas 24 h) · " + num(s.roteadores, 0) + " roteadores vistos"],
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
      r.copiaria ? '<span class="tag win">copiaria</span>' : r.eligible ? '<span class="tag neutral">' + (r.online ? "apto" : "apto · fora (inativo)") + "</span>"
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
  function draw() {
    drawSys();
    if (VIEW === "visao") drawVisao();
    if (VIEW === "traders") drawTraders();
  }

  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try {
      const r = await BB.api("/api/hood", { quiet: true });
      if (r && !r.error) R = r;
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
  document.addEventListener("input", (e) => { if (e.target && e.target.closest && e.target.closest("#hdCfg")) DIRTY = true; });
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target.closest("button,a") : null; if (!t) return;
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
