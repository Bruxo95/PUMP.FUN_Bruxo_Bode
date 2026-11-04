// 0.32.168 (pedido do dono, 02/11): painel BNB · Four.Meme, isolado do painel da Solana (arquivo próprio, rota própria).
// 0.32.169: página própria (/bnb), escolhida em /entrar; nada dela fica dentro do painel da pump.fun.
// 0.32.170 (pedido do dono, 03/11): menu no padrão do painel da pump.fun (Visão geral, Top traders, Posições, Histórico,
// Semana × fim de semana, Abas de trades, Configurações, Administração, Changelog), Fictícia/Real no topo e a cópia
// FICTÍCIA dos traders do ranking.
// 0.32.172 (pedido do dono, 03/11): Monitor no menu da esquerda, Evolução da carteira e Operações recentes na Visão geral,
// os ajustes juntos em Top traders → Ajustes, Vender todas em Posições e a carteira REAL (chave e ligar em Configurações;
// o botão Real do topo troca todas as telas para ela).
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = {
    visao: ["Visão geral", "sua carteira da BNB e o que a cópia fez"], traders: ["Top traders", "ranking da Four.Meme, quem é copiado e os ajustes"],
    posicoes: ["Posições", "o que está aberto agora"], historico: ["Histórico", "trades fechados"],
    semanas: ["Semana × fim de semana", "o resultado de segunda a sexta comparado com sábado e domingo"],
    abas: ["Abas de trades", "liga e desliga as compras de cada aba"], config: ["Configurações", "carteira REAL: chave e ligar/desligar"],
    admin: ["Administração", "leitura da rede"],
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
    ["slip_pct", "Slippage simulado em cada lado", "%", 0, 50, 0.5], ["gas_bnb", "Gás simulado por transação", "BNB", 0, 0.01, 0.0001],
    ["saldo_inicial", "Saldo inicial da fictícia", "BNB", 0.01, 1000, 0.1],
  ];
  // 0.32.175 (pedido do dono, 03/11): tempo máximo e stop num quadro próprio, porque valem para a FICTÍCIA e para a REAL
  const SA_INFO = [["max_hold_h", "Tempo máximo da posição", "horas", 0.1, 168, 0.5], ["stop_pct", "Stop de perda (0 = sem stop)", "%", 0, 100, 1]];
  const RC_INFO = [
    ["real_bnb_por_compra", "BNB por compra na REAL", "BNB", 0.001, 1, 0.001], ["real_max_abertas", "Máximo de posições REAL abertas", "posições", 1, 30, 1],
    ["real_slip_pct", "Slippage máximo (compra e venda)", "%", 1, 49, 1], ["real_perda_dia", "Perda máxima por dia", "BNB", 0.001, 10, 0.01],
    ["real_gwei", "Preço do gás", "gwei", 0.05, 5, 0.05],
  ];
  // 0.32.171 (pedido do dono, 03/11): Log geral com o Registro de segurança e o Log do servidor (as mesmas rotas de
  // Administração do painel da pump.fun). "Só BNB" filtra o que é da BNB; "Tudo" mostra os dois projetos.
  const LG = { tab: "seg", f: "bnb", lv: "INFO", after: 0, key: "" };
  let VIEW = "visao", REAL = false, R = null, P = null, CHG = null, BUSY = false, READY = false, DIRTY = { rk: false, cf: false, rc: false, sa: false };
  let ME = null, USERS = null;
  let TRT = "rank", RANGE = 1, AJT = "rk";
  try { TRT = localStorage.getItem("bnb_trt") || "rank"; RANGE = Number(localStorage.getItem("bnb_range")) || 1; AJT = localStorage.getItem("bnb_ajt") || "rk"; } catch (e) { /* */ }
  if (AJT !== "rk") AJT = "cp";          // 0.32.176: Saídas, FICTÍCIA e REAL viraram uma aba só (Cópia)

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
  const modeTag = () => (REAL ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>');

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
  const RS = () => (P && P.real_status) || {};

  // ------------------------------------------------------------------ monitor (menu da esquerda)
  function sysInfo() {
    const s = (R && R.status) || {};
    const erro = s.ultimo_erro && s.ultimo_erro_t && Date.now() / 1000 - s.ultimo_erro_t < 120;
    const parado = !s.ultimo_trade_t || Date.now() / 1000 - s.ultimo_trade_t > 600;
    const atraso = s.atraso_s != null && s.atraso_s > 60;
    const ok = !!(R && R.ligado && !erro && !parado && !atraso);
    return { s, ok, probs: [erro && "erro na leitura", parado && "sem trade lido há mais de 10 min", atraso && "leitura atrasada"].filter(Boolean) };
  }
  function drawSys() {
    const i = sysInfo(), s = i.s;
    $("sysDot").className = "dot " + (i.ok ? "on" : "off");
    $("sysT").textContent = !R ? "Monitor…" : !R.ligado ? "Monitor OFF" : i.ok ? "Monitor ON" : "Monitor com problema";
    $("sysS").textContent = !R ? "conectando" : !R.ligado ? "leitura desligada" : i.ok ? "último trade há " + ago(s.ultimo_trade_t) + " · atraso " + num(s.atraso_s, 0) + " s" : i.probs.join(" · ");
    $("sysBox").title = i.probs.length ? "Com problema: " + i.probs.join(", ") : "Tudo ok · clique para ver a leitura da rede";
    if (!$("sysM").hidden) drawSysModal();
  }
  function drawSysModal() {
    const i = sysInfo(), s = i.s, rk = (R && R.ranking) || {};
    const rows = [
      ["Leitura", R && R.ligado ? (i.ok ? '<span class="up">funcionando</span>' : '<span class="down">' + esc(i.probs.join(" · ") || "com problema") + "</span>") : '<span class="down">desligada</span>'],
      ["RPC grátis", esc(s.rpc || "—") + " · " + num(s.chamadas, 0) + " consultas desde " + hora(s.desde)],
      ["Bloco", num(s.bloco, 0) + " · lido até " + num(s.lido_ate, 0) + " · atraso " + (s.atraso_s == null ? "—" : num(s.atraso_s, 1) + " s")],
      ["Último trade lido", ago(s.ultimo_trade_t) + " · " + hora(s.ultimo_trade_t)],
      ["Últimas 24 h", num(s.trades_24h, 0) + " trades · " + num(s.compras_24h, 0) + " compras · " + num(s.carteiras_24h, 0) + " carteiras · " + num(s.tokens_24h, 0) + " tokens"],
      ["Moeda das curvas (24 h)", Object.entries(s.moedas_24h || {}).map((x) => esc(x[0]) + " " + x[1]).join(" · ") || "—"],
      ["Ranking", num(rk.aptos, 0) + " aptos · " + num((rk.copiaria || []).length, 0) + " copiados agora"],
      ["BNB em dólar", s.bnb_usd ? "US$ " + num(s.bnb_usd, 2) : "—"],
      ["Gravação", num(s.trades_memoria, 0) + " trades na memória · " + num(s.a_gravar, 0) + " esperando gravar"],
      ["Erros", num(s.erros, 0) + (s.ultimo_erro ? " · último há " + ago(s.ultimo_erro_t) + ": " + esc(s.ultimo_erro) : "")],
      ["Carteira REAL", RS().ligada ? '<span class="up">ligada</span> desde ' + hora(RS().desde) : "desligada"],
    ];
    $("sysMB").innerHTML = '<div class="tbl-wrap"><table class="systbl nocard"><tbody>' + rows.map((r) => "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>").join("") + "</tbody></table></div>";
  }

  // ------------------------------------------------------------------ gráfico da carteira
  let CURVE = null;
  function drawCurve() {
    const el = $("curve"); if (!el || !P) return;
    const Wd = el.clientWidth || 600, H = el.clientHeight || 260, PL = 58, B = 22;
    const start = REAL ? 0 : Number(P.carteira.inicial || 0);
    const ts = (P.trades || []).slice().sort((a, b) => a.close_t - b.close_t);
    let acc = start; const pts = ts.map((x) => { acc += x.pnl_bnb; return [x.close_t * 1000, acc]; });
    $("curveSub").textContent = REAL ? "BNB · REAL · resultado somado dos trades fechados" : "BNB · FICTÍCIA · saldo pelos trades fechados";
    const now = Date.now(), t0 = now - RANGE * 86400000;
    const before = pts.filter((p) => p[0] < t0), base = before.length ? before[before.length - 1][1] : start;
    const S = [[t0, base]].concat(pts.filter((p) => p[0] >= t0)); S.push([now, S[S.length - 1][1]]);
    if (!pts.length) { el.innerHTML = '<div class="empty" style="padding-top:90px">' + (REAL ? "A linha aparece a partir do primeiro trade REAL fechado." : "A carteira começa com " + num(start, 4) + " BNB. A linha aparece a partir do primeiro trade fechado.") + "</div>"; $("curveRes").innerHTML = ""; CURVE = null; return; }
    const ys = S.map((p) => p[1]); let lo = Math.min(...ys), hi = Math.max(...ys); if (hi - lo < 0.002) { lo -= 0.001; hi += 0.001; }
    const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
    const X = (t) => PL + ((t - t0) / (now - t0)) * (Wd - PL - 10), Y = (v) => 10 + ((hi - v) / (hi - lo)) * (H - B - 14);
    const up = S[S.length - 1][1] >= base, col = up ? "#22c55e" : "#ef4444";
    let path = ""; S.forEach((p, i) => { const x = X(p[0]).toFixed(1), y = Y(p[1]).toFixed(1); path += i ? " H" + x + " V" + y : "M" + x + " " + y; });
    const grid = [0, 1, 2, 3].map((i) => { const v = lo + ((hi - lo) * i) / 3; return '<line x1="' + PL + '" x2="' + Wd + '" y1="' + Y(v) + '" y2="' + Y(v) + '" stroke="#1e1e22"/><text x="4" y="' + (Y(v) + 4) + '" font-size="10.5" fill="#5d5d66" font-family="JetBrains Mono,monospace">' + v.toFixed(4) + "</text>"; }).join("");
    const xl = [0, 0.5, 1].map((k) => { const t = t0 + k * (now - t0), d = new Date(t); const lab = RANGE <= 1 ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }); return '<text x="' + Math.min(Wd - 40, Math.max(PL, X(t) - 16)) + '" y="' + (H - 4) + '" font-size="10.5" fill="#5d5d66">' + lab + "</text>"; }).join("");
    el.innerHTML = '<svg viewBox="0 0 ' + Wd + " " + H + '" preserveAspectRatio="none"><defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + col + '" stop-opacity=".25"/><stop offset="1" stop-color="' + col + '" stop-opacity="0"/></linearGradient></defs>' + grid +
      '<line x1="' + PL + '" x2="' + Wd + '" y1="' + Y(base) + '" y2="' + Y(base) + '" stroke="#5d5d66" stroke-dasharray="3 4" opacity=".6"/>' +
      '<path d="' + path + " V" + (H - B) + " H" + X(t0) + 'Z" fill="url(#cg)"/><path d="' + path + '" fill="none" stroke="' + col + '" stroke-width="2"/>' + xl + '</svg><i class="cline" id="cLine" hidden></i><i class="cdot" id="cDot" hidden></i><div class="ctip" id="cTip" hidden></div>';
    let g = 0, l = 0;
    const C = S.map((p, i) => { const d = i ? p[1] - S[i - 1][1] : 0; if (d > 0) g += d; else l += d; return { t: p[0], v: p[1], g, l }; });
    CURVE = { C, base, t0, t1: now, Wd, PL, X, Y, H, B };
    const fim = C[C.length - 1];
    $("curveRes").innerHTML = [["Início", num(base, 4) + " BNB"], ["Ganhou", bnb(fim.g)], ["Perdeu", bnb(fim.l)], ["Agora", num(fim.v, 4) + " BNB" + (base ? " " + pct((fim.v - base) / Math.abs(base) * 100) : "")]].map((x) => "<div><small>" + x[0] + "</small><b>" + x[1] + "</b></div>").join("");
  }
  function curveTip(x) {
    const c = CURVE, tip = $("cTip"); if (!c || !tip) return;
    const t = c.t0 + Math.max(0, Math.min(1, (x - c.PL) / (c.Wd - c.PL - 10))) * (c.t1 - c.t0);
    let i = 0; while (i + 1 < c.C.length && c.C[i + 1].t <= t) i++;
    const p = c.C[i], px = c.X(t);
    tip.innerHTML = "<b>" + esc(new Date(t).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })) + "</b><span>" + (REAL ? "Resultado" : "Saldo") + " <b>" + num(p.v, 4) + " BNB</b></span><span>Ganhou " + bnb(p.g) + "</span><span>Perdeu " + bnb(p.l) + "</span>";
    tip.hidden = false; $("cLine").hidden = false; $("cDot").hidden = false;
    $("cLine").style.left = px + "px"; $("cLine").style.height = (c.H - c.B) + "px";
    $("cDot").style.left = px + "px"; $("cDot").style.top = c.Y(p.v) + "px";
    tip.style.left = px > c.Wd / 2 ? Math.max(0, px - tip.offsetWidth - 12) + "px" : px + 12 + "px";
  }
  function curveMove(e) {
    const el = e.target.closest && e.target.closest("#curve");
    if (el && CURVE) { const r = el.getBoundingClientRect(); curveTip((e.clientX - r.left) * (CURVE.Wd / r.width)); }
    else ["cTip", "cLine", "cDot"].forEach((id) => { if ($(id)) $(id).hidden = true; });
  }

  // ------------------------------------------------------------------ telas
  function opKind(a, motivo) {
    if (/falhou/.test(a)) return '<span class="tag err">Erro</span>';
    if (/não copiou/.test(a)) return '<span class="tag pause">Ficou de fora</span>';
    if (/comprou|copiou compra/.test(a)) return '<span class="tag buy">Compra</span>';
    if (/vendeu parte/.test(a)) return '<span class="tag trail">Venda parcial</span>';
    if (/fechou/.test(a)) return /[+]\d/.test(motivo || "") ? '<span class="tag win">Venda c/ lucro</span>' : '<span class="tag loss">Venda c/ prejuízo</span>';
    return "";
  }
  function drawOps() {
    const ev = (P.eventos || []).slice(0, 30);
    $("opsSub").textContent = (REAL ? "carteira REAL" : "carteira FICTÍCIA") + " · compras, vendas e o que ficou de fora";
    $("ops").innerHTML = ev.length ? ev.map((e) => '<div class="op"><div style="min-width:0"><div class="t">' + esc(e.acao) + " · " + sw(e.token) +
      '</div><div class="m">há ' + ago(e.t) + " · trader " + sw(e.wallet) + (e.motivo ? " · " + esc(e.motivo) : "") + "</div>" +
      '<div class="opb"><a class="btn sm ghost" href="https://four.meme/token/' + esc(e.token) + '" target="_blank" rel="noopener">Token</a>' +
      (e.tx ? ' <a class="btn sm ghost tx" href="https://bscscan.com/tx/' + esc(e.tx) + '" target="_blank" rel="noopener">Transação</a>' : "") +
      '</div></div><div><div class="tags">' + opKind(e.acao, e.motivo) + modeTag() + "</div></div></div>").join("")
      : '<div class="empty">' + (REAL ? (RS().ligada ? "A REAL está ligada e esperando a próxima compra de um trader do ranking." : "A carteira REAL está desligada. Ligue em Configurações.") : "Nenhuma operação ainda. Assim que um trader do ranking comprar, a fictícia copia.") + "</div>";
  }
  function drawVisao() {
    if (!P) return;
    const w = P.carteira, rs = RS();
    if (REAL) {
      kpis("ovK", [
        ["Saldo na carteira", w.saldo == null ? "—" : num(w.saldo, 4) + " BNB", w.endereco ? sw(w.endereco) : "sem chave configurada"],
        ["Em posições", num(w.em_posicoes, 4) + " BNB", w.abertas + " abertas"],
        ["Total", w.total == null ? "—" : num(w.total, 4) + " BNB", "saldo + posições"],
        ["Resultado", bnb(w.resultado), pct(w.resultado_pct) + " sobre o investido", cls(w.resultado)],
        ["Fechadas", num(w.fechadas, 0), "realizado " + num(w.realizado, 4) + " BNB"],
        ["Acerto", w.acerto == null ? "—" : num(w.acerto, 0) + "%", "trades fechados com lucro"],
        ["REAL", rs.ligada ? '<span class="up">ligada</span>' : '<span class="down">desligada</span>', rs.ligada ? "desde " + hora(rs.desde) : "ligue em Configurações"],
      ]);
    } else {
      kpis("ovK", [
        ["Saldo livre", num(w.saldo, 4) + " BNB", "inicial " + num(w.inicial, 4) + " BNB"],
        ["Em posições", num(w.em_posicoes, 4) + " BNB", w.abertas + " abertas"],
        ["Total", num(w.total, 4) + " BNB", "saldo + posições"],
        ["Resultado", bnb(w.resultado), pct(w.resultado_pct) + " desde o início", cls(w.resultado)],
        ["Fechadas", num(w.fechadas, 0), "realizado " + num(w.realizado, 4) + " BNB"],
        ["Acerto", w.acerto == null ? "—" : num(w.acerto, 0) + "%", "trades fechados com lucro"],
        ["Copiando agora", num((P.copiaria || []).length, 0), "traders do ranking"],
      ]);
    }
    kpis("ovP", (w.periodos || []).map((x) => ["Últimas " + x.h + " h", bnb(x.pnl), x.n ? x.n + " trades · " + x.ganhos + " com lucro · " + x.traders + " traders" : "nenhum trade fechado", cls(x.pnl)]));
    document.querySelectorAll("#rangeSeg button").forEach((b) => b.classList.toggle("on", Number(b.dataset.r) === RANGE));
    drawCurve();
    drawOps();
    const st = $("ovSt"), c = P.cfg;
    st.className = "decbox " + (P.leitura_ok ? "ok" : "bad");
    st.innerHTML = (P.leitura_ok ? "Leitura da Four.Meme funcionando." : "<b>Leitura da Four.Meme com problema</b> (veja o Monitor no menu).") +
      " Cópia " + (REAL ? "REAL" : "FICTÍCIA") + ": <b>" + (c.on ? "ligada" : "desligada") + "</b> · " + num(c.bnb_por_compra, 4) + " BNB por compra · até " + c.max_abertas +
      " posições · tempo máximo " + num(c.max_hold_h, 1) + " h" + (c.stop_pct ? " · stop " + c.stop_pct + "%" : " · sem stop") +
      ". Copiando " + (P.copiaria || []).length + " trader(s) agora.";
  }
  function drawTraders() {
    document.querySelectorAll("#trTab button").forEach((b) => b.classList.toggle("on", b.dataset.trt === TRT));
    $("trRank").hidden = TRT !== "rank"; $("trAj").hidden = TRT !== "aj";
    if (TRT === "aj") { drawAjustes(); return; }
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
    $("bnSelSub").textContent = "os " + R.cfg.top_n + " melhores aptos que negociaram nos últimos " + R.cfg.online_min + " min · a FICTÍCIA (e a REAL, se ligada) copia as compras e vendas deles";
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
    // 0.32.178 (pedido do dono): tokens que graduaram para a PancakeSwap e quem ganha com eles
    const gr = rk.graduados || [];
    table("bnGr", ["Carteira", "Lucro nos graduados", "Acerto nos graduados", "Tokens graduados", "Trades na Pancake", "Lucro total", "Situação"],
      gr.map((r) => [wal(r.wallet), bnb(r.grad_realized_bnb), r.grad_winrate == null ? "—" : num(r.grad_winrate, 0) + "% de " + r.grad_closed,
        num(r.grad_tokens, 0), num(r.pancake_trades, 0), bnb(r.realized_bnb),
        r.copiaria ? '<span class="tag win">copiando</span>' : r.bot ? '<span class="muted">robô: ' + num(r.per_day, 0) + " trades/dia</span>" : r.no_top ? '<span class="muted">no ranking</span>' : '<span class="muted">fora dos 50 do ranking</span>']),
      "Ainda ninguém lucrou com tokens graduados (os trades na PancakeSwap começam a ser lidos nesta versão).");
    const pk = R.pancake || {}, toks = pk.tokens || [];
    kpis("bnPcK", [["Graduados achados", num(pk.pares, 0), "lendo " + num(pk.lendo, 0) + " pares"], ["Trades lidos na Pancake", num(pk.trades, 0), "desde que o servidor subiu"],
      ["Com trades em 24 h", num(toks.filter((x) => x.trades_24h).length, 0), "tokens"], ["Falhas da leitura", num(pk.erros, 0), pk.ultimo_erro ? esc(pk.ultimo_erro).slice(0, 80) : "nenhuma", pk.erros ? "down" : ""]]);
    table("bnPc", ["Token", "Graduou", "Trades 24 h", "Compradores · vendedores 24 h", "Volume 24 h", "Preço desde o 1º trade lido na Pancake", "Último trade"],
      toks.map((x) => [tok(x.token) + ' <a class="muted" href="https://pancakeswap.finance/swap?outputCurrency=' + esc(x.token) + '&chain=bsc" target="_blank" rel="noopener">Pancake</a>',
        x.graduou_t ? "há " + ago(x.graduou_t) : "—", num(x.trades_24h, 0), num(x.compradores_24h, 0) + " · " + num(x.vendedores_24h, 0),
        num(x.vol_24h_bnb, 3) + " BNB", pct(x.desde_pct), x.ultimo_t ? "há " + ago(x.ultimo_t) : "—"]),
      "Nenhum token graduado achado ainda. O robô confere a cada 3 min os tokens que negociaram na curva nas últimas 3 h.");
  }
  function drawAjustes() {
    if (R && R.ligado && !DIRTY.rk) form("bnCfg", RK_INFO, R.cfg, R.padrao, "bnc_");
    document.querySelectorAll("#ajTab button").forEach((b) => b.classList.toggle("on", b.dataset.ajt === AJT));
    document.querySelectorAll("[data-ajp]").forEach((c) => (c.hidden = c.dataset.ajp !== AJT));
    if (P && !DIRTY.cf) form("cfF", CF_INFO, P.cfg_sim || P.cfg, P.padrao, "cf_");
    if (P && !DIRTY.sa) form("saF", SA_INFO, P.cfg_sim || P.cfg, P.padrao, "sa_");
    if (P && !DIRTY.rc && P.real_cfg) form("rcF", RC_INFO, P.real_cfg, P.real_padrao, "rc_");
    if (P) {
      const sw2 = (id, on) => { const el = $(id); el.className = "btn sm tgl sw " + (on ? "on" : "off"); el.setAttribute("aria-checked", on ? "true" : "false"); el.textContent = on ? "Ligado" : "Desligado"; };
      sw2("cfTgl", !!(P.cfg_sim || P.cfg).on);
      sw2("rcTgl", !!RS().ligada);
    }
  }
  function drawPosicoes() {
    if (!P) return;
    drawPosicoesBadge();
    const ps = P.posicoes || [], tot = ps.reduce((a, p) => a + p.pnl_bnb, 0), inv = ps.reduce((a, p) => a + p.bnb_in, 0);
    $("poSub").textContent = REAL ? "carteira REAL · o resultado agora já desconta a taxa de 1% e o slippage máximo da saída" : "carteira FICTÍCIA · o resultado já desconta a taxa de 1%, o gás e o slippage da saída";
    $("poAll").hidden = !ps.length;
    kpis("poK", [["Abertas", num(ps.length, 0), "de " + P.cfg.max_abertas + " · " + (REAL ? "REAL" : "FICTÍCIA")], ["Investido", num(inv, 4) + " BNB", ""],
      ["Resultado agora", bnb(tot), inv ? pct(100 * tot / inv) : "", cls(tot)], ["No lucro", num(ps.filter((p) => p.pnl_bnb > 0).length, 0), "posições"]]);
    // 0.32.174 (pedido do dono): posições em cartões, como no painel da pump.fun (PC e celular, sem rolagem lateral)
    const box = $("poT"); if (!box) return;
    box.innerHTML = ps.length ? ps.map(bnCard).join("") : '<div class="empty">' + (REAL ? (RS().ligada ? "Nenhuma posição REAL aberta." : "Nenhuma posição REAL. A carteira REAL está desligada (Configurações).") : "Nenhuma posição aberta.") + "</div>";
  }
  const PO_OPEN = new Set();   // "Mais detalhes" abertos continuam abertos entre atualizações
  function bnCard(p) {
    const now = Date.now() / 1000, c = P.cfg || {};
    const chg = p.px_in && p.px_now ? (p.px_now / p.px_in - 1) * 100 : null, up = (p.pnl_bnb || 0) >= 0;
    const stopV = c.stop_pct || 0, stopOff = !stopV;
    const lo = stopOff ? Math.min(-50, (p.worst_pct || 0) * 1.1) : -stopV;
    const hi = Math.max((p.best_pct || 0) * 1.1, (chg || 0) * 1.1, 30);
    const at = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)).toFixed(1);
    const range = chg == null ? "" : '<div class="pc-range" title="faixa entre o stop de perda e o melhor momento; ● = agora, ▲ = pico">' +
      '<div class="pc-bar"><span class="pc-zero" style="left:' + at(0) + '%"></span>' +
      (p.best_pct != null ? '<span class="pc-peak" style="left:' + at(p.best_pct) + '%" title="pico ' + num(p.best_pct, 1) + '%"></span>' : "") +
      '<span class="pc-now ' + (chg >= 0 ? "up" : "down") + '" style="left:' + at(chg) + '%"></span></div>' +
      '<div class="pc-rl"><span>' + (stopOff ? "sem stop" : "stop −" + num(stopV, 0) + "%") + "</span><span>" + (p.best_pct != null ? "pico " + num(p.best_pct, 1) + "%" : "") + "</span></div></div>";
    const rest = p.fecha_em - now;
    const tags = (REAL ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>') + (p.graduou ? ' <span class="tag sim">Pancake</span>' : "") + (p.selling ? ' <span class="tag pause">Vendendo…</span>' : "");
    const st = (k, v) => "<div><dt>" + k + "</dt><dd>" + v + "</dd></div>";
    const vendas = (p.vendas || []).map((x) => "<li>" + hora(x.t) + " · " + num((x.frac || 0) * 100, 0) + "% · " + num(x.bnb, 4) + " BNB" + (x.motivo ? " · " + esc(x.motivo) : "") + "</li>").join("");
    const id = String(p.id);
    return '<article class="pcard ' + (up ? "is-up" : "is-down") + (REAL ? " is-real" : "") + '">' +
      '<header class="pc-h"><div class="pc-tk">' + tok(p.token) + " " + tags + "</div>" +
      '<div class="pc-sub">trader ' + wal(p.wallet) + " · aberta há <b>" + ago(p.open_t) + "</b></div></header>" +
      '<div class="pc-box"><div><small>Ganho agora</small><b class="pc-big ' + (up ? "up" : "down") + '">' + (p.pnl_bnb > 0 ? "+" : "") + num(p.pnl_bnb, 4) + " BNB</b><small>" + num(p.pnl_pct, 1) + "% do investido</small></div>" +
      '<div class="pc-var"><small>Variação do preço</small><b>' + pct(chg) + "</b></div></div>" + range +
      '<dl class="pc-grid">' + st("Investido", num(p.bnb_in, 4) + " BNB") + st("Já recebido", num(p.proceeds || 0, 4) + " BNB") +
      st("Melhor / pior", pct(p.best_pct) + " / " + pct(p.worst_pct)) + st("Preço lido", p.px_t ? "há " + ago(p.px_t) : "—") + "</dl>" +
      '<div class="pc-sec"><div><small>Sai por tempo em</small>' + (rest > 0 ? "<b>" + dur(rest) + "</b>" : '<b class="down">agora</b>') + '<small class="dim">limite ' + num(c.max_hold_h, 1) + " h</small></div></div>" +
      (p.selling ? "" : '<div class="pc-act"><button class="btn sm pill no" type="button" data-bnclose="' + esc(id) + '">' + (REAL ? "Vender tudo" : "Fechar 100%") + "</button></div>") +
      (p.sell_error ? '<div class="pc-err down">venda falhou: ' + esc(p.sell_error) + " · tenta de novo em 1 min</div>" : "") +
      '<details class="pc-more" data-poid="' + esc(id) + '"' + (PO_OPEN.has(id) ? " open" : "") + "><summary>Mais detalhes</summary>" +
      '<dl class="pc-grid">' + st("Abriu", hora(p.open_t)) + st("Atraso na cópia", p.lag_s == null ? "—" : num(p.lag_s, 1) + " s") +
      st("Preço de entrada", p.px_in == null ? "—" : Number(p.px_in).toPrecision(4)) + st("Preço agora", p.px_now == null ? "—" : Number(p.px_now).toPrecision(4)) +
      st("Aba", esc(p.aba || "Top traders BNB")) + st("Transação", REAL && p.tx_in ? txl(p.tx_in) : "—") + "</dl>" +
      (vendas ? '<p class="pc-lbl">Vendas parciais</p><ul class="pc-list">' + vendas + "</ul>" : "") + "</details></article>";
  }
  function drawHistorico() {
    if (!P) return;
    $("hiSub").textContent = (REAL ? "carteira REAL" : "carteira FICTÍCIA") + " · mais novos primeiro";
    const ts = P.trades || [], tot = ts.reduce((a, x) => a + x.pnl_bnb, 0), g = ts.filter((x) => x.pnl_bnb > 0);
    kpis("hiK", [["Fechados", num(ts.length, 0), REAL ? "REAL" : "FICTÍCIA"], ["Resultado", bnb(tot), "", cls(tot)], ["Acerto", ts.length ? num(100 * g.length / ts.length, 0) + "%" : "—", g.length + " com lucro"],
      ["Melhor", ts.length ? bnb(Math.max(...ts.map((x) => x.pnl_bnb))) : "—", ""], ["Pior", ts.length ? bnb(Math.min(...ts.map((x) => x.pnl_bnb))) : "—", ""]]);
    table("hiT", ["Fechou", "Trader", "Token", "Investido", "Recebido", "Resultado", "Tempo", "Motivo"],
      ts.map((x) => [hora(x.close_t) + (x.tx_out ? "<br>" + txl(x.tx_out) : ""), wal(x.wallet), tok(x.token), num(x.bnb_in, 4), num(x.bnb_out, 4), bnb(x.pnl_bnb) + "<br>" + pct(x.pnl_pct),
        dur(x.close_t - x.open_t), esc(x.motivo)]),
      REAL ? "Nenhum trade REAL fechado ainda." : "Nenhum trade fechado ainda.");
  }
  function drawSemanas() {
    if (!P) return;
    const b = P.semana.blocos, it = (n, x) => [n, bnb(x.pnl), x.n ? x.n + " trades · acerto " + num(x.acerto, 0) + "% · investido " + num(x.investido, 3) + " BNB" : "nenhum trade fechado", cls(x.pnl)];
    kpis("wkK", [it("Segunda a sexta" + (REAL ? " · REAL" : ""), b.semana), it("Sábado e domingo" + (REAL ? " · REAL" : ""), b.fds)]);
    table("wkT", ["Dia", "Trades", "Acerto", "Resultado"], P.semana.dias.map((d) => [esc(d.dia), num(d.n, 0), d.acerto == null ? "—" : num(d.acerto, 0) + "%", bnb(d.pnl)]));
  }
  function drawAbas() {
    if (!P) return;
    $("abG").innerHTML = (P.abas || []).map((a) => '<div class="bnaba"><h3>' + esc(a.nome) + " " + modeTag() + '</h3><div class="muted">copia os traders do ranking (Top traders) · ' + a.abertas + " abertas · " + a.fechadas + " fechadas · resultado " + bnb(a.resultado) +
      '</div><div class="row" style="margin-top:10px"><button class="btn sm tgl sw ' + (a.ligada ? "on" : "off") + '" role="switch" aria-checked="' + a.ligada + '" data-bnaba="' + esc(a.aba) + '">' + (a.ligada ? "Ligado" : "Desligado") +
      '</button><span class="muted">compras na ' + (REAL ? "REAL" : "FICTÍCIA") + '</span></div><div class="per">' +
      (a.periodos || []).map((x) => "<div>" + x.h + " h<b>" + bnb(x.pnl, 3) + '</b><span class="muted">' + x.n + " trades</span></div>").join("") + "</div></div>").join("");
  }
  function drawConfig() {
    if (!P) return;
    // 0.32.177 (pedido do dono): segurança do token antes de comprar
    const sf = P.seguranca;
    if (sf) {
      const rg = sf.regras || {}, st = sf.stat || {};
      $("sfRules").innerHTML = "<p>Antes de comprar, o robô confere o token e <b>não compra</b> quando:</p><ul>" +
        "<li>a GoPlus aponta <b>honeypot</b> (não deixa vender), <b>não deixa vender tudo</b>, o dono pode <b>pausar as transferências</b> (congelar), tem <b>lista negra</b>, espera obrigatória entre trades, o dono pode mudar saldo ou taxa, taxa diferente por carteira ou dono escondido;</li>" +
        "<li>a taxa da Four.Meme na compra ou na venda passa de <b>" + num(rg.max_taxa_curva_pct, 0) + "%</b> (o normal é 1%; mais que isso é o modo anti-sniper ou token com taxa) — conferido na rede, simulando compra e venda;</li>" +
        "<li>a taxa do próprio token (compra ou venda) passa de <b>" + num(rg.max_taxa_token_pct, 0) + "%</b>;</li>" +
        "<li>o token já foi para a PancakeSwap e a GoPlus ainda não tem dados dele, ou a conferência falhou (nunca compra sem conferir).</li></ul>" +
        '<p class="muted">Token barrado fica fora por ' + num(rg.barrado_h, 0) + " h. A conferência não vende posições que já estão abertas.</p>";
      kpis("sfK", [["Conferidos", num(st.conferidos, 0), "desde que o servidor subiu"], ["Barrados", num(st.barrados, 0), "não comprou", st.barrados ? "down" : ""],
        ["GoPlus", num(st.goplus, 0), (st.goplus_sem_dados || 0) + " ainda sem dados"], ["Falhas", num(st.erros, 0), "tenta de novo em 1 min"]]);
      table("sfT", ["Hora", "Token", "Por que não comprou", "Taxa compra · venda"], (sf.barrados || []).map((x) => [hora(x.t), tok(x.token), esc(x.why),
        x.taxa_compra == null ? "—" : num(x.taxa_compra, 1) + "% · " + num(x.taxa_venda, 1) + "%"]), "Nenhum token barrado nas últimas 24 h.");
    }
    const rs = RS(), el = $("rlSt");
    el.className = "decbox " + (rs.ligada ? "ok" : "");
    el.innerHTML = (!rs.permitido ? "<b>Trava geral do servidor fechada</b> (PUMP_REAL_ALLOWED=false): a REAL não liga nem envia nada.<br>" : "") +
      (rs.chave ? 'Carteira: <span class="bnaddr">' + esc(rs.endereco) + '</span> · <a href="https://bscscan.com/address/' + esc(rs.endereco) + '" target="_blank" rel="noopener">BscScan</a>' +
        " · saldo " + (rs.saldo == null ? "—" : num(rs.saldo, 4) + " BNB") : "Nenhuma chave de carteira BNB salva.") +
      "<br>REAL: <b>" + (rs.ligada ? "ligada desde " + hora(rs.desde) : "desligada") + "</b>";
    const t = $("rlTgl");
    t.className = "btn sm tgl sw " + (rs.ligada ? "on" : "off"); t.setAttribute("aria-checked", rs.ligada ? "true" : "false"); t.textContent = rs.ligada ? "Ligado" : "Desligado";
    $("rlKeyDel").hidden = !rs.chave;
  }
  // 0.32.173 (pedido do dono, 03/11): usuários na Administração da BNB, com Visualizar tela (só leitura, igual ao painel da pump.fun)
  function drawUsers() {
    if (!USERS) return;
    const q = ($("bnUQ").value || "").trim().toLowerCase();
    const L = USERS.users.filter((x) => !q || (String(x.nome || "") + " " + String(x.email || "")).toLowerCase().includes(q));
    const av = (x) => (x.avatar_url ? '<img src="' + esc(x.avatar_url) + '" alt="" referrerpolicy="no-referrer">' : "<i>" + esc(String(x.nome || x.email || "?").slice(0, 1).toUpperCase()) + "</i>");
    table("bnU", ["Usuário", "Categoria", "Último acesso", "BNB FICTÍCIA", "BNB REAL", ""], L.map((x) => {
      const f = x.bnb && x.bnb.ficticia, r = x.bnb && x.bnb.real;
      return ['<div class="bnuser">' + av(x) + "<div><b>" + esc(x.nome || "—") + "</b><small>" + esc(x.email || "") + "</small></div></div>",
        (x.role === "admin" ? '<span class="tag win">Admin</span>' : '<span class="tag">Usuário</span>') + (x.bloqueado ? ' <span class="tag loss">bloqueado</span>' : ""),
        x.ultimo_acesso ? "há " + ago(Date.parse(x.ultimo_acesso) / 1000) : "—",
        f ? bnb(f.resultado) + '<br><span class="muted">' + f.fechadas + " fechados · " + f.abertas + " abertas" + (f.acerto == null ? "" : " · " + num(f.acerto, 0) + "%") + "</span>" : '<span class="muted">nunca abriu a BNB</span>',
        r && (r.ligada || r.endereco || r.fechadas) ? (r.ligada ? '<span class="tag real">ON</span> ' : '<span class="tag">OFF</span> ') + bnb(r.resultado) +
          '<br><span class="muted">' + r.fechadas + " fechados · " + r.abertas + " abertas" + (r.endereco ? " · " + sw(r.endereco) : "") + "</span>" : '<span class="muted">sem carteira</span>',
        x.user_id === USERS.me ? '<span class="muted">você</span>' : '<button class="btn sm" data-viewas="' + esc(x.user_id) + '">Visualizar tela</button>'];
    }), "Nenhum usuário.");
  }
  async function loadUsers() {
    if (ME && ME.view_by) { $("bnUCard").hidden = true; return; }
    const r = await BB.api("/api/pump/bnb/usuarios", { quiet: true });
    if (r && r.users) { USERS = r; drawUsers(); }
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

  function drawBanner() {
    const el = $("bnReal"), rs = RS();
    el.hidden = !(REAL && REAL_VIEWS.includes(VIEW));
    if (el.hidden) return;
    el.innerHTML = rs.ligada ? "<b>Carteira REAL da BNB ligada</b> desde " + hora(rs.desde) + " · " + (rs.saldo == null ? "" : "saldo " + num(rs.saldo, 4) + " BNB · ") +
      'só entra nas compras novas dos traders. <a href="#config">Configurações</a>'
      : "<b>Carteira REAL da BNB desligada.</b> " + (rs.chave ? "A chave já está salva; ligue em " : "Cole a chave da carteira e ligue em ") + '<a href="#config">Configurações</a>. Nada é enviado enquanto estiver desligada.';
  }
  function draw() {
    drawBanner();
    drawSys();
    ({ visao: drawVisao, traders: drawTraders, posicoes: drawPosicoes, historico: drawHistorico, semanas: drawSemanas, abas: drawAbas, config: drawConfig, admin: drawAdmin, changelog: drawChangelog }[VIEW] || (() => {}))();
    if (VIEW !== "posicoes") drawPosicoesBadge();
  }
  function drawPosicoesBadge() {
    if (P) $("nbPos").textContent = (P.posicoes || []).length || "";
    if (R && R.ranking) $("nbTr").textContent = (R.ranking.copiaria || []).length || "";
  }

  // ------------------------------------------------------------------ dados
  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try {
      const real = REAL;
      const [p, r] = await Promise.all([BB.api("/api/pump/bnb/painel" + (real ? "?real=1" : ""), { quiet: true }), BB.api("/api/pump/bnb", { quiet: true })]);
      if (p && !p.error && real === REAL) P = p.ligado === false ? null : p;
      if (r && !r.error) R = r;
      if (VIEW === "logs") await loadLogs(false);
      if (VIEW === "admin") await loadUsers();
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
    if (REAL !== real) P = null;
    REAL = real;
    try { localStorage.setItem("bnb_mode", real ? "real" : "sim"); } catch (e) { /* */ }
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.mode === "real") === REAL));
    draw();
    load();
  }
  const openDrawer = () => { $("side").classList.add("open"); $("scrim").classList.add("open"); };
  const closeDrawer = () => { $("side").classList.remove("open"); $("scrim").classList.remove("open"); };
  const closeSys = () => { $("sysM").hidden = true; };

  async function toggleReal() {
    const rs = RS();
    if (rs.ligada) {
      if (!confirm("Desligar a carteira REAL da BNB? Ela para de comprar na hora. As posições REAL abertas continuam e são vendidas pelas regras (trader vendeu, tempo máximo, stop) ou por você.")) return;
      await BB.api("/api/pump/bnb/real", { body: { on: false } });
    } else {
      if (!rs.chave) { alert("Para ligar a REAL, salve antes a chave da carteira BNB em Configurações."); location.hash = "#config"; return; }
      const c = (P && P.real_cfg) || {};
      const v = prompt("Ligar a carteira REAL da BNB?\n\nEla compra " + num(c.real_bnb_por_compra, 4) + " BNB a cada compra NOVA de um trader do ranking (até " + c.real_max_abertas +
        " posições, perda máxima de " + num(c.real_perda_dia, 4) + " BNB por dia). As posições que a fictícia já tem NÃO são compradas.\n\nDigite LIGAR para confirmar.");
      if (v == null) return;
      const r = await BB.api("/api/pump/bnb/real", { body: { on: true, confirm: v } });
      if (r && r.error) { alert(r.error); return; }
    }
    await load();
  }

  // ------------------------------------------------------------------ ações
  let LGQ_T = 0;
  document.addEventListener("input", (e) => {
    const id = (e.target && e.target.id) || "";
    if (id === "lgQ") { clearTimeout(LGQ_T); LGQ_T = setTimeout(() => loadLogs(true), 400); }
    if (id === "bnUQ") drawUsers();
    if (id.startsWith("bnc_")) DIRTY.rk = true;
    if (id.startsWith("cf_")) DIRTY.cf = true;
    if (id.startsWith("sa_")) DIRTY.sa = true;
    if (id.startsWith("rc_")) DIRTY.rc = true;
  });
  document.addEventListener("pointermove", curveMove);
  document.addEventListener("pointerdown", curveMove);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSys(); });
  window.addEventListener("resize", () => { if (VIEW === "visao") drawCurve(); });
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target : null; if (!t) return;
    const mb = t.closest("#modeSeg button"); if (mb) { setMode(mb.dataset.mode === "real"); return; }
    const va = t.closest("[data-viewas]");
    if (va) {
      try { sessionStorage.setItem("pf_viewas", va.dataset.viewas); } catch (x) { alert("O navegador bloqueou a visualização."); return; }
      location.hash = "#visao"; location.reload(); return;
    }
    if (t.closest("#viewExit")) { try { sessionStorage.removeItem("pf_viewas"); } catch (x) { /* */ } location.hash = "#admin"; location.reload(); return; }
    if (t.closest("#sysBox")) { drawSysModal(); $("sysM").hidden = false; return; }
    if (t.closest("#sysMX") || t.id === "sysM") { closeSys(); return; }
    const rg = t.closest("#rangeSeg button");
    if (rg) { RANGE = Number(rg.dataset.r) || 1; try { localStorage.setItem("bnb_range", RANGE); } catch (x) { /* */ } drawVisao(); return; }
    const tt = t.closest("[data-trt], [data-gotr]");
    if (tt) { TRT = tt.dataset.trt || tt.dataset.gotr; try { localStorage.setItem("bnb_trt", TRT); } catch (x) { /* */ } if (VIEW === "traders") drawTraders(); return; }
    const rk = t.closest("#bnSave, #bnReset");
    if (rk) {
      const body = {};
      if (rk.id === "bnReset") Object.assign(body, (R && R.padrao) || {});
      else RK_INFO.forEach((c) => { const el = $("bnc_" + c[0]); if (el && el.value !== "") body[c[0]] = Number(el.value); });
      const r = await BB.api("/api/pump/bnb/cfg", { body: body });
      DIRTY.rk = false;
      if (r && r.ok && R) { R.cfg = r.cfg; drawAjustes(); load(); }
      return;
    }
    const aj = t.closest("[data-ajt]");
    if (aj) { AJT = aj.dataset.ajt; try { localStorage.setItem("bnb_ajt", AJT); } catch (x) { /* */ } drawAjustes(); return; }
    // 0.32.176 (pedido do dono): aba Cópia com um Salvar só (saídas + fictícia na conta; valores da REAL na rota da REAL)
    const cp = t.closest("#cpSave, #cpReset");
    if (cp) {
      const reset = cp.id === "cpReset", body = {}, rbody = {};
      if (reset && !confirm("Voltar Saídas, FICTÍCIA e REAL aos valores padrão?")) return;
      SA_INFO.concat(CF_INFO).forEach((c) => {
        const pre = SA_INFO.includes(c) ? "sa_" : "cf_", el = $(pre + c[0]);
        if (reset) { if (P && P.padrao && c[0] in P.padrao) body[c[0]] = P.padrao[c[0]]; } else if (el && el.value !== "") body[c[0]] = Number(el.value);
      });
      RC_INFO.forEach((c) => { const el = $("rc_" + c[0]); if (reset) { if (P && P.real_padrao) rbody[c[0]] = P.real_padrao[c[0]]; } else if (el && el.value !== "") rbody[c[0]] = Number(el.value); });
      cp.disabled = true;
      const [r1, r2] = await Promise.all([BB.api("/api/pump/bnb/conta", { body: body }), BB.api("/api/pump/bnb/real/cfg", { body: rbody })]);
      cp.disabled = false;
      DIRTY.cf = DIRTY.sa = DIRTY.rc = false;
      if (P && r1 && r1.ok) P.cfg_sim = r1.cfg;
      if (P && r2 && r2.ok) P.real_cfg = r2.cfg;
      if (!(r1 && r1.ok) || !(r2 && r2.ok)) alert("Não salvou tudo: " + ((r1 && r1.error) || (r2 && r2.error) || "tente de novo"));
      drawAjustes(); load();
      return;
    }
    if (t.closest("#cfTgl") && P) {
      const on = !(P.cfg_sim || P.cfg).on;
      const r = await BB.api("/api/pump/bnb/conta", { body: { on } });
      if (r && r.ok) { P.cfg_sim = r.cfg; if (!REAL) P.cfg = r.cfg; drawAjustes(); load(); }
      return;
    }
    if (t.closest("#rcTgl")) { await toggleReal(); return; }
    if (t.closest("#rlTgl")) { await toggleReal(); return; }
    if (t.closest("#rlKeySave")) {
      const v = ($("rlKey").value || "").trim();
      if (!v) { alert("Cole a chave privada da carteira BNB."); return; }
      const r = await BB.api("/api/pump/bnb/chave", { body: { value: v } });
      $("rlKey").value = "";
      if (r && r.error) { alert(r.error); return; }
      alert("Chave salva. Carteira: " + r.endereco);
      await load();
      return;
    }
    if (t.closest("#rlKeyDel")) {
      if (!confirm("Remover a chave da carteira BNB? A REAL da BNB desliga. As posições REAL abertas ficam paradas até você salvar a chave de novo.")) return;
      await BB.api("/api/pump/bnb/chave/remover", { body: {} });
      await load();
      return;
    }
    const ab = t.closest("[data-bnaba]");
    if (ab && P) {
      if (REAL) { await toggleReal(); return; }
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
    const all = t.closest("#poAll");
    if (all) {
      const n = ((P && P.posicoes) || []).length;
      let confirmTxt = "";
      if (REAL) {
        confirmTxt = prompt("Vender TODAS as " + n + " posições REAL agora, a mercado (com o slippage máximo dos Ajustes)?\n\nDigite VENDER para confirmar.");
        if (confirmTxt == null) return;
      } else if (!confirm("Vender todas as " + n + " posições FICTÍCIAS agora pelo último preço?")) return;
      all.disabled = true;
      const r = await BB.api("/api/pump/bnb/fechar-todas", { body: { real: REAL, confirm: confirmTxt } });
      all.disabled = false;
      if (r && r.error) alert(r.error); else if (r) alert(r.vendidas + " vendidas" + (r.falhas ? " · " + r.falhas + " falharam (tenta de novo em 1 min)" : ""));
      load();
      return;
    }
    const cl = t.closest("[data-bnclose]");
    if (cl) {
      if (!confirm(REAL ? "Vender esta posição REAL agora, a mercado?" : "Vender esta posição FICTÍCIA agora pelo último preço?")) return;
      cl.disabled = true;
      const r = await BB.api("/api/pump/bnb/fechar", { body: { id: cl.dataset.bnclose, real: REAL } });
      if (r && r.error) alert(r.error);
      load();
    }
  });

  document.addEventListener("toggle", (e) => {
    const d = e.target; if (!d.dataset || !d.dataset.poid) return;
    d.open ? PO_OPEN.add(d.dataset.poid) : PO_OPEN.delete(d.dataset.poid);
  }, true);

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
    if (me.error || (me.role !== "admin" && !me.view_by)) { location.replace("/app"); return; }      // a BNB é só do admin
    ME = me;
    try { sessionStorage.setItem("pf_hub", "bnb"); } catch (e) { /* */ }
    if (me.view_by) {
      // visualização da tela de um usuário: só leitura (o servidor recusa qualquer alteração e nada é gravado para ele)
      document.body.classList.add("viewas");
      $("viewBar").hidden = false;
      $("viewBar").innerHTML = '<div class="viewbar"><span>👁 Você está vendo a tela da BNB de <b>' + esc(me.nome || me.email || "usuário") + "</b>" + (me.email ? " · " + esc(me.email) : "") +
        " — somente visualização: nada pode ser alterado e as chaves não aparecem.</span><button class=\"btn sm primary\" id=\"viewExit\">Sair da visualização</button></div>";
    }
    $("ver").textContent = "versão " + String(me.version || "").split(" · ")[0];
    let m = "sim"; try { m = localStorage.getItem("bnb_mode") || "sim"; } catch (e) { /* */ }
    $("boot").hidden = true; $("shell").hidden = false;
    READY = true;
    REAL = m === "real";
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", (b.dataset.mode === "real") === REAL));
    route();
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", load);
  boot();
  setInterval(load, 10000);
})();
