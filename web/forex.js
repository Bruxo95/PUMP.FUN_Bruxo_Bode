// 0.32.368 (pedido do dono, 15/11/2026): painel do Projeto Forex, no mesmo padrão do /hood (rotas /api/forex, página /forex).
// Etapa 1: ranking (vazio até o conector do cTrader), carteira FICTÍCIA e regras do lote. Nada vai para corretora.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = { visao: ["Visão geral", "a sua cópia fictícia e a conexão com as corretoras"], ranking: ["Ranking", "os melhores mestres pelo risco ajustado"],
    posicoes: ["Posições", "o que a cópia tem aberto agora"], historico: ["Histórico", "posições fechadas da cópia"], copia: ["Regras da cópia", "lote, custos e limites da carteira fictícia"] };
  // [chave, nome, unidade, mín, máx, passo, dica]
  const CF = [
    ["saldo_inicial", "Saldo inicial fictício", "US$", 100, 10000000, 100, "com quanto a carteira começa"],
    ["multiplicador", "Multiplicador", "×", 0.01, 50, 0.01, "no modo patrimônio ajusta o lote; no modo multiplicador é o lote do mestre × isso"],
    ["lote_fixo", "Lote fixo", "lote", 0.01, 100, 0.01, "só no modo fixo"],
    ["lote_max", "Lote máximo por ordem", "lote", 0.01, 100, 0.01, "teto, em qualquer modo"],
    ["slip_pips", "Slippage simulado", "pips", 0, 50, 0.1, "em cada entrada e saída"],
    ["comissao_lote", "Comissão por lote (ida e volta)", "US$", 0, 100, 0.5, "média de conta ECN ≈ US$ 7"],
    ["alavancagem", "Alavancagem", "1:", 1, 2000, 1, "para conferir a margem antes de copiar"],
    ["atraso_max_s", "Atraso máximo para copiar", "s", 1, 600, 1, "ordem do mestre mais velha que isso não é copiada"],
    ["perda_dia_max", "Perda do dia que para a cópia (0 = sem limite)", "US$", 0, 10000000, 10, "conta só o que fechou hoje"],
  ];
  let P = null, VIEW = "visao", BUSY = false, READY = false, DIRTY = false;
  const num = (v, d) => (v == null || isNaN(v) ? "—" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d }));
  const usd = (v) => (v == null ? "—" : (v < 0 ? "−" : "") + "US$ " + num(Math.abs(v)));
  const sgn = (v) => (v == null ? "—" : '<b class="' + (v > 0 ? "up" : v < 0 ? "down" : "") + '">' + (v > 0 ? "+" : v < 0 ? "−" : "") + "US$ " + num(Math.abs(v)) + "</b>");
  const dt = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
  const lado = (l) => (l === "buy" ? '<span class="tag win">COMPRA</span>' : '<span class="tag loss">VENDA</span>');

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
  function toast(msg) {
    let el = $("fxToast");
    if (!el) { el = document.createElement("div"); el.id = "fxToast"; el.className = "hdtoast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
    el.textContent = msg; el.hidden = false; clearTimeout(el._t); el._t = setTimeout(() => { el.hidden = true; }, 2600);
  }

  // ------------------------------------------------------------------ telas
  function draw() {
    if (!P) return;
    if (P.ligado === false) { $("ovK").innerHTML = '<div class="card">' + esc(P.motivo || "Forex desligado no servidor") + "</div>"; return; }
    const w = P.carteira || {}, cfg = P.cfg || {};
    if (VIEW === "visao") {
      kpis("ovK", [
        ["Saldo FICTÍCIO", usd(w.total), "começou com " + usd(w.inicial), "mon"],
        ["Resultado", sgn(w.resultado), w.resultado_pct == null ? "" : num(w.resultado_pct, 2) + "% do saldo inicial", ""],
        ["Posições abertas", String((P.posicoes || []).length), "margem usada " + usd(w.margem_usada), ""],
        ["Mestres copiados", String(P.seguindo || 0), (P.ranking || []).length ? (P.ranking || []).filter((r) => r.elegivel).length + " elegíveis no ranking" : "nenhum mestre conectado ainda", ""],
      ]);
      table("cnT", ["Plataforma", "Situação", "Como conecta"], (P.conectores || []).map((c) =>
        ["<b>" + esc(c.plataforma) + "</b>", '<span class="st-wait">' + esc(c.status) + "</span>", esc(c.como)]));
      table("evT", ["Hora", "Ação", "Ativo", "Mestre", "Motivo"], (P.eventos || []).slice(0, 40).map((e) =>
        [dt(e.t), "<b>" + esc(e.acao) + "</b>", esc(e.token || ""), esc(e.mestre || ""), esc(e.motivo || "")]),
        "Nenhum evento ainda: os eventos aparecem quando um mestre conectado abrir ou fechar uma ordem.");
    }
    if (VIEW === "ranking") {
      table("rkT", ["#", "Mestre", "Nota", "Retorno", "Max DD", "Profit factor", "Sharpe", "Trades / dias", "Situação"], (P.ranking || []).map((r, i) => [
        String(i + 1), "<b>" + esc(r.apelido || r.id) + "</b><br><small class=\"muted\">" + esc(r.plataforma || "") + "</small>", "<b>" + num(r.score, 1) + "</b>",
        num(r.retorno_pct, 1) + "%", num(r.mdd_pct, 1) + "%", r.profit_factor == null ? "—" : num(r.profit_factor, 2), r.sharpe == null ? "—" : num(r.sharpe, 2),
        r.trades + " / " + r.dias, r.elegivel ? '<span class="tag win">elegível</span>' : '<span class="tag neutral">fora</span><br><small class="muted">' + esc((r.motivos || []).join(" · ")) + "</small>"]),
        "Nenhum mestre conectado ainda. Na próxima etapa (conector cTrader), os mestres entram aqui com a nota calculada a cada 15 min.");
    }
    if (VIEW === "posicoes") {
      table("poT", ["Abriu", "Ativo", "Lado", "Lote (mestre)", "Preço", "SL / TP", "Mestre", "Atraso"], (P.posicoes || []).map((p) => [
        dt(p.abriu_t), "<b>" + esc(p.simbolo) + "</b>", lado(p.lado), num(p.lote) + " (" + num(p.lote_mestre) + ")", num(p.preco, 5),
        (p.sl ? num(p.sl, 5) : "—") + " / " + (p.tp ? num(p.tp, 5) : "—"), esc(p.mestre), num(p.atraso_s, 1) + " s"]), "Nenhuma posição aberta.");
    }
    if (VIEW === "historico") {
      const tr = P.trades || [];
      kpis("hiK", [["Fechadas", String(w.fechadas || 0), "", ""], ["Acerto", w.acerto == null ? "—" : num(w.acerto, 1) + "%", "", ""], ["Resultado", sgn(w.resultado), "", ""]]);
      table("hiT", ["Fechou", "Ativo", "Lado", "Lote", "Resultado", "Motivo", "Mestre"], tr.map((t) => [
        dt(t.fechou_t), "<b>" + esc(t.simbolo) + "</b>", lado(t.lado), num(t.lote), sgn(t.lucro), esc(t.motivo || ""), esc(t.mestre)]), "Nenhuma posição fechada ainda.");
    }
    if (VIEW === "copia" && !DIRTY) drawCfg(cfg);
  }
  function drawCfg(cfg) {
    const modo = cfg.modo_lote || "equity";
    $("cfF").innerHTML = '<label>Como calcular o lote<select class="in" id="cf_modo_lote"><option value="equity"' + (modo === "equity" ? " selected" : "") +
      '>Proporcional ao patrimônio</option><option value="multiplicador"' + (modo === "multiplicador" ? " selected" : "") + '>Multiplicador do lote do mestre</option><option value="fixo"' +
      (modo === "fixo" ? " selected" : "") + '>Lote fixo</option></select><small>padrão: proporcional ao patrimônio</small></label>' +
      CF.map((x) => '<label>' + esc(x[1]) + ' <small>(' + esc(x[2]) + ')</small><input class="in" id="cf_' + x[0] + '" type="number" inputmode="decimal" min="' + x[3] + '" max="' + x[4] + '" step="' + x[5] +
        '" value="' + esc(cfg[x[0]] == null ? "" : cfg[x[0]]) + '"><small>' + esc(x[6]) + "</small></label>").join("") +
      '<label>Copiar stop (SL) e alvo (TP) do mestre<select class="in" id="cf_copiar_sl_tp"><option value="1"' + (cfg.copiar_sl_tp !== false ? " selected" : "") +
      '>Sim</option><option value="0"' + (cfg.copiar_sl_tp === false ? " selected" : "") + ">Não</option></select><small>se não, a posição só fecha quando o mestre fechar</small></label>";
  }

  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try { P = await BB.api("/api/forex/painel", { quiet: true }); draw(); } catch (e) { /* tenta de novo */ } finally { BUSY = false; }
  }
  function route() {
    const v = (location.hash || "#visao").slice(1);
    VIEW = TITLES[v] ? v : "visao";
    document.querySelectorAll(".view").forEach((s) => (s.hidden = s.dataset.view !== VIEW));
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === VIEW));
    document.querySelectorAll("#tabbar [data-tv]").forEach((a) => a.classList.toggle("on", a.dataset.tv === VIEW));
    $("pgTitle").textContent = TITLES[VIEW][0]; $("pgSub").textContent = TITLES[VIEW][1];
    closeDrawer(); window.scrollTo(0, 0); DIRTY = false; draw(); load();
  }
  const openDrawer = () => { $("side").classList.add("open"); $("scrim").classList.add("open"); };
  const closeDrawer = () => { $("side").classList.remove("open"); $("scrim").classList.remove("open"); };

  document.addEventListener("input", (e) => { if (e.target && e.target.closest && e.target.closest("#cfF")) DIRTY = true; });
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target.closest("button,a") : null; if (!t) return;
    if (t.id === "cfSave") {
      const body = { modo_lote: $("cf_modo_lote").value, copiar_sl_tp: $("cf_copiar_sl_tp").value === "1" };
      CF.forEach((x) => { const el = $("cf_" + x[0]); if (el && el.value !== "") body[x[0]] = Number(el.value); });
      t.disabled = true;
      const r = await BB.api("/api/forex/conta", { body });
      t.disabled = false;
      if (r && r.error) { alert(r.error); return; }
      DIRTY = false; toast("Regras salvas."); return load();
    }
    if (t.id === "cfZero") {
      if (!confirm("Zerar a carteira fictícia do Forex? Fecha as posições abertas (sem resultado), apaga o histórico e volta ao saldo inicial. As regras ficam.")) return;
      const r = await BB.api("/api/forex/zerar", { body: {} });
      if (r && r.error) { alert(r.error); return; }
      toast("Carteira fictícia zerada."); return load();
    }
  });

  async function boot() {
    $("boot").innerHTML = BB.loader("Carregando", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
    $("fxOut").addEventListener("click", BB.logout);
    $("burger").addEventListener("click", openDrawer);
    $("tbMenu").addEventListener("click", openDrawer);
    $("scrim").addEventListener("click", closeDrawer);
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão: volta ao início */ }
    if (!s) { location.href = "/"; return; }
    const me = await BB.api("/api/me", { quiet: true });
    if (me.error || me.role !== "admin" || me.view_by) { location.replace("/app"); return; }      // o Forex é só do admin (etapa de teste)
    try { sessionStorage.setItem("pf_hub", "forex"); } catch (e) { /* */ }
    $("ver").textContent = "versão " + String(me.version || "").split(" · ")[0];
    $("boot").hidden = true; $("shell").hidden = false;
    READY = true;
    route();
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", load);
  boot();
  setInterval(load, 5000);
})();
