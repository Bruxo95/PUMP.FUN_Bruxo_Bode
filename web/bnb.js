// 0.32.168 (pedido do dono, 02/11): aba BNB · Four.Meme, isolada do painel da Solana (arquivo próprio, rota própria).
// Etapa 1: só mostra o que a leitura da rede encontrou e o ranking dos traders; não copia nada.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const CFG_INFO = [
    ["days", "Dias do ranking", "dias", 1, 7, 1],
    ["min_trades", "Trades mínimos no período", "trades", 0, 100000, 1],
    ["min_winrate", "Acerto acima de", "%", 0, 100, 1],
    ["min_closed", "Tokens fechados mínimos (para medir o acerto)", "tokens", 1, 1000, 1],
    ["min_wallet_usd", "Saldo mínimo da carteira (BNB + dólar)", "US$", 0, 10000000, 100],
    ["online_min", "Online = negociou nos últimos", "min", 1, 1440, 1],
    ["top_n", "Quantos copiaria", "carteiras", 1, 50, 1],
    ["bot_per_day", "Robô = mais trades por dia que", "trades/dia", 10, 100000, 10],
  ];
  let D = null, BUSY = false, DIRTY = false;

  const num = (v, d) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: d == null ? 4 : d }));
  const bnb = (v) => (v == null ? "—" : '<span class="' + (v > 0 ? "up" : v < 0 ? "down" : "") + '">' + (v > 0 ? "+" : "") + num(v, 4) + " BNB</span>");
  const hora = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—");
  function ago(t) {
    if (!t) return "—";
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : s < 86400 ? (s / 3600).toFixed(1).replace(".", ",") + " h" : (s / 86400).toFixed(1).replace(".", ",") + " dias";
  }
  const sw = (w) => esc(w.slice(0, 6) + "…" + w.slice(-4));
  const wal = (w) => '<a href="https://bscscan.com/address/' + esc(w) + '" target="_blank" rel="noopener" title="' + esc(w) + '">' + sw(w) + "</a>";
  const tok = (t) => '<a href="https://four.meme/token/' + esc(t) + '" target="_blank" rel="noopener" title="' + esc(t) + '">' + sw(t) + "</a>";
  const txl = (h) => '<a href="https://bscscan.com/tx/' + esc(h) + '" target="_blank" rel="noopener">ver</a>';

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

  function drawCfg() {
    if (DIRTY || !D || !D.cfg) return;
    $("bnCfg").innerHTML = CFG_INFO.map((c) => '<div class="field"><label for="bnc_' + c[0] + '">' + esc(c[1]) + '</label><div class="row"><input class="in w80" id="bnc_' + c[0] +
      '" type="number" min="' + c[3] + '" max="' + c[4] + '" step="' + c[5] + '" value="' + esc(D.cfg[c[0]]) + '"><span class="muted">' + esc(c[2]) +
      (D.padrao && D.padrao[c[0]] !== D.cfg[c[0]] ? " · padrão " + esc(D.padrao[c[0]]) : "") + "</span></div></div>").join("");
  }

  function draw() {
    if (!D) return;
    if (!D.ligado) {
      kpis("bnK", [["Leitura", "desligada", D.motivo || "", "down"]]);
      return;
    }
    const s = D.status || {}, rk = D.ranking || { rows: [], copiaria: [] };
    const moedas = Object.entries(s.moedas_24h || {}).map((x) => esc(x[0]) + " " + x[1]).join(" · ");
    kpis("bnK", [
      ["Trades em 24 h", num(s.trades_24h, 0), num(s.compras_24h, 0) + " compras · " + num(s.tokens_24h, 0) + " tokens"],
      ["Carteiras em 24 h", num(s.carteiras_24h, 0), "no ranking: " + num(rk.carteiras, 0) + " em " + num(D.cfg.days, 0) + " dias"],
      ["Aptos", num(rk.aptos, 0), num(rk.aptos_online, 0) + " online agora"],
      ["Seriam copiados", num((rk.copiaria || []).length, 0), "de " + num(D.cfg.top_n, 0) + " vagas", (rk.copiaria || []).length ? "up" : ""],
      ["Último trade lido", ago(s.ultimo_trade_t), hora(s.ultimo_trade_t)],
      ["Atraso da leitura", s.atraso_s == null ? "—" : num(s.atraso_s, 1) + " s", "bloco " + num(s.lido_ate, 0), s.atraso_s > 60 ? "down" : ""],
      ["BNB em dólar", s.bnb_usd ? "US$ " + num(s.bnb_usd, 2) : "—", "PancakeSwap USDT/WBNB"],
    ]);
    const st = $("bnSt");
    const erro = s.ultimo_erro && s.ultimo_erro_t && Date.now() / 1000 - s.ultimo_erro_t < 120;
    st.className = "decbox " + (erro ? "bad" : s.ultimo_trade_t ? "ok" : "");
    st.innerHTML = (erro ? "<b>Erro na leitura há " + ago(s.ultimo_erro_t) + ":</b> " + esc(s.ultimo_erro) + "<br>" : "") +
      "RPC grátis: <b>" + esc(s.rpc || "—") + "</b> · " + num(s.chamadas, 0) + " consultas desde " + hora(s.desde) +
      " · " + num(s.trades_memoria, 0) + " trades na memória" + (s.carregados ? " (" + num(s.carregados, 0) + " recuperados do banco)" : "") +
      (moedas ? " · moedas da curva em 24 h: " + moedas : "") + (s.a_gravar ? " · " + num(s.a_gravar, 0) + " esperando gravar" : "") +
      (D.carregado ? "" : " · <b>carregando os dias guardados…</b>");
    $("bnSelSub").textContent = "os " + D.cfg.top_n + " melhores aptos que negociaram nos últimos " + D.cfg.online_min + " min · ainda não copia (etapa 1)";
    const rows = rk.rows || [];
    const line = (r, i) => [String(i + 1), wal(r.wallet), bnb(r.realized_bnb), r.winrate == null ? "—" : num(r.winrate, 0) + "%",
      num(r.trades, 0) + " · " + num(r.per_day, 0) + "/dia", r.closed + " fechados · " + r.open + " abertos" + (r.grad_open ? " (" + r.grad_open + " já na Pancake)" : ""),
      r.wallet_usd == null ? "—" : "US$ " + num(r.wallet_usd, 0), (r.online ? '<span class="tag win">online</span> ' : "") + ago(r.last_t)];
    table("bnSel", ["#", "Carteira", "Lucro realizado", "Acerto", "Trades", "Tokens", "Saldo", "Último trade"],
      rows.filter((r) => r.copiaria).map((r) => line(r, rows.indexOf(r))),
      rows.length ? "Ninguém apto e online agora. O ranking enche com os dias; veja o motivo de cada um abaixo." : "Ainda sem trades lidos.");
    $("bnRkSub").textContent = "os 50 que mais lucraram em " + D.cfg.days + " dias · " + (rk.fora_moeda ? rk.fora_moeda + " trades fora das contas (moeda da curva desconhecida)" : "todos os trades nas contas");
    table("bnRk", ["#", "Carteira", "Lucro realizado", "Acerto", "Trades", "Tokens", "Saldo", "Último trade", "Por que não"],
      rows.map((r, i) => line(r, i).concat([r.copiaria ? '<span class="tag win">copiaria</span>' : r.eligible ? '<span class="muted">apto, mas offline ou fora das vagas</span>' : esc((r.flags || []).join(" · "))])),
      "Ainda sem trades lidos.");
    table("bnTr", ["Hora", "Carteira", "Token", "Lado", "BNB", "Moeda", "Tx"],
      (D.recentes || []).map((t) => [hora(t.t), wal(t.wallet), tok(t.token), t.side === "buy" ? '<span class="up">compra</span>' : '<span class="down">venda</span>',
        t.bnb == null ? "—" : num(t.bnb, 4), esc(t.moeda), txl(t.tx)]),
      "Ainda sem trades lidos.");
    drawCfg();
  }

  async function load() {
    const sec = document.querySelector('.view[data-view="bnb"]');
    if (!sec || sec.hidden || BUSY || !BB.api) return;
    BUSY = true;
    try {
      const r = await BB.api("/api/pump/bnb", { quiet: true });
      if (r && !r.error) { D = r; draw(); }
    } catch (e) { /* tenta de novo na próxima volta */ } finally { BUSY = false; }
  }

  document.addEventListener("input", (e) => { if (e.target && e.target.id && e.target.id.startsWith("bnc_")) DIRTY = true; });
  document.addEventListener("click", async (e) => {
    const b = e.target.closest && e.target.closest("#bnSave, #bnReset");
    if (!b) return;
    const body = {};
    if (b.id === "bnReset") Object.assign(body, (D && D.padrao) || {});
    else CFG_INFO.forEach((c) => { const el = $("bnc_" + c[0]); if (el && el.value !== "") body[c[0]] = Number(el.value); });
    const r = await BB.api("/api/pump/bnb/cfg", { body: body });
    DIRTY = false;
    if (r && r.ok && D) { D.cfg = r.cfg; drawCfg(); load(); }
  });
  window.addEventListener("hashchange", () => setTimeout(load, 50));
  setTimeout(load, 800);
  setInterval(load, 10000);
})();
