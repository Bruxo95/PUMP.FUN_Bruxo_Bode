// 0.32.227 (pedido do dono, 05/11): Dormant, painel próprio (/dormant, rotas /api/dormant) isolado da pump.fun, da BNB e da
// Robinhood. Vigia a watchlist da CoinMarketCap do dono pela CoinGecko e diz o que está dormindo, acordando, num pump ou num
// dump. Só observa.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = { visao: ["Visão geral", "o que acordou, o que deu pump ou dump e o que está dormindo"], moedas: ["Moedas", "todas as moedas da lista com a situação de cada uma"],
    grupos: ["Por blockchain e categoria", "as moedas da lista divididas por rede e por categoria"],
    config: ["Lista e regras", "chave da CoinGecko, regras e as moedas da lista"],
    carteiras: ["Carteiras e compra", "as carteiras de cada blockchain, a senha de compra e os limites"],
    compras: ["Minhas compras", "o que você comprou e quanto está ganhando em 1 h, 12 h, 24 h, 7 dias e no total"] };
  const ST = { pump: "Pump", dump: "Dump", acordando: "Acordando", dormindo: "Dormindo", normal: "Normal", parada: "Parada", morta: "Morta", sem_cg: "Sem par",
    acordou_chain: "Acordou na blockchain", parada_chain: "Parada na blockchain" };
  // 0.32.229 (áudio do Bruxo): as últimas 3 ações de cada moeda, lidas na blockchain (GeckoTerminal); link para o explorador da rede
  const EXPL = { eth: "https://etherscan.io/tx/", bsc: "https://bscscan.com/tx/", solana: "https://solscan.io/tx/", base: "https://basescan.org/tx/",
    arbitrum: "https://arbiscan.io/tx/", polygon_pos: "https://polygonscan.com/tx/", avax: "https://snowtrace.io/tx/", tron: "https://tronscan.org/#/transaction/",
    optimism: "https://optimistic.etherscan.io/tx/", ton: "https://tonviewer.com/transaction/", "sui-network": "https://suiscan.xyz/mainnet/tx/" };
  // 0.32.233 (pedido do dono): cada blockchain com a sua cor e um ícone simples (desenhado aqui, só para reconhecer a rede)
  const CHI = {
    eth: '<path d="M8 1l4.5 7.3L8 11 3.5 8.3z" fill="currentColor"/><path d="M8 12l4.5-2.7L8 15l-4.5-5.7z" fill="currentColor" opacity=".6"/>',
    sol: '<path d="M4 3.5h9l-2 2H2zM2 7h9l2 2H4zM4 10.5h9l-2 2H2z" fill="currentColor"/>',
    bnb: '<path d="M8 2l2 2-2 2-2-2zM4 6l2 2-2 2-2-2zM12 6l2 2-2 2-2-2zM8 6l2 2-2 2-2-2zM8 10l2 2-2 2-2-2z" fill="currentColor"/>',
    base: '<circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="M8 4.5a3.5 3.5 0 1 1-3.4 4.3h5.6V7.2H4.6A3.5 3.5 0 0 1 8 4.5z" fill="#0a0a0a"/>',
    arb: '<path d="M8 1.5l5.6 3.2v6.6L8 14.5l-5.6-3.2V4.7z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6.5 10.5l2.5-6 1.4.8-2.2 5.2z" fill="currentColor"/>',
    poly: '<path d="M5 4.5l3-1.7 3 1.7v3.4l-3 1.7-3-1.7zM2 8.6l3-1.7M11 7.9l3 1.7v3.4l-3 1.7-3-1.7" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    avax: '<path d="M8 2.5l6 10.5H2z" fill="currentColor"/><path d="M8 7.5l2.2 3.8H5.8z" fill="#0a0a0a"/>',
    tron: '<path d="M2 3l12 2.5L8.5 14z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M2 3l6.5 11M14 5.5L6 7" stroke="currentColor" stroke-width="1.2"/>',
    op: '<circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="M5.2 9.8a1.6 1.8 0 1 0 0-3.6 1.6 1.8 0 1 0 0 3.6zM8.6 6.2h1.6a1 1 0 0 1 0 2.2H9.3l-.3 1.4" fill="none" stroke="#0a0a0a" stroke-width="1.1"/>',
    ton: '<path d="M2.5 4h11L8 14z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 4v10" stroke="currentColor" stroke-width="1.4"/>',
    propria: '<path d="M6.5 9.5l3-3M5 7.5l-1.3 1.3a2.1 2.1 0 0 0 3 3L8 10.5M11 8.5l1.3-1.3a2.1 2.1 0 0 0-3-3L8 5.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    dot: '<circle cx="8" cy="8" r="5" fill="currentColor"/>',
  };
  const CHS = { "Ethereum": ["#8a9cf0", "eth"], "Solana": ["#14F195", "sol"], "BNB Chain": ["#F0B90B", "bnb"], "Base": ["#3b82f6", "base"],
    "Arbitrum": ["#28A0F0", "arb"], "Polygon": ["#a47bf0", "poly"], "Avalanche": ["#E84142", "avax"], "TRON": ["#ff3b3f", "tron"],
    "Optimism": ["#FF0420", "op"], "TON": ["#0098EA", "ton"], "Blockchain própria": ["#9ca3af", "propria"], "Cronos": ["#5b8def", "dot"],
    "Sui": ["#4DA2FF", "dot"], "Fantom": ["#1969FF", "dot"], "Kaia": ["#BFF009", "dot"], "Chiliz": ["#ff4d6d", "dot"], "Cardano": ["#3468d1", "dot"],
    "Linea": ["#61DFFF", "dot"], "Mantle": ["#65b3ae", "dot"], "Sonic": ["#fe9a4c", "dot"], "Osmosis": ["#a855f7", "dot"], "Cosmos": ["#6f7390", "dot"],
    "Robinhood Chain": ["#c3f53c", "dot"], "Gnosis": ["#3e6957", "dot"], "Celo": ["#FCFF52", "dot"], "Near": ["#00ec97", "dot"], "NEAR": ["#00ec97", "dot"] };
  function chainTag(nome, extra) {
    if (!nome) return "";
    const c = CHS[nome] || ["#9ca3af", "dot"];
    return '<span class="dmch dmchc" style="--cc:' + c[0] + '"' + (extra ? ' title="' + esc(extra) + '"' : "") + '><svg viewBox="0 0 16 16" aria-hidden="true">' + CHI[c[1]] + "</svg>" + esc(nome) + "</span>";
  }
  const n24 = (b) => (b.n24 >= 300 ? "300+" : String(b.n24 || 0));
  function bcCell(m, full) {
    const b = m.bc;
    if (m.rede_propria) return '<span class="muted small">rede própria · sem pool para ler (usa a CoinGecko)</span>';
    if (!m.bc_alvo) return '<span class="muted small">sem contrato conhecido</span>';
    if (!b || !b.t) return '<span class="muted small">na fila para ler</span>';
    if (b.sem_pool) return '<span class="muted small">sem pool de negociação achado</span>';
    const L = (b.last3 || []).map((x) => '<div><span class="' + (x.kind === "compra" ? "c" : "v") + '">' + esc(x.kind) + "</span> US$ " + num(x.usd, x.usd >= 100 ? 0 : 2) + " · há " + ago(x.t) +
      (x.tx && EXPL[b.net] ? ' · <a href="' + EXPL[b.net] + esc(x.tx) + '" target="_blank" rel="noopener">ver</a>' : "") + "</div>").join("");
    return '<div class="dmbc"><b>' + (b.ultima_t ? "última há " + ago(b.ultima_t) : "parada há mais de 24 h") + "</b>" +
      ' <span class="muted">· ' + n24(b) + " negócios em 24 h</span>" + (full === false ? "" : L) + "</div>";
  }
  const ST_ORD = ["acordando", "pump", "dump", "dormindo", "normal", "parada", "sem_cg", "morta"];
  const RG = [["pump_1h", "Pump: alta em 1 h de pelo menos", "%"], ["pump_24h", "Pump: ou alta em 24 h de pelo menos", "%"],
    ["dump_1h", "Dump: queda em 1 h de", "%"], ["dump_24h", "Dump: ou queda em 24 h de", "%"],
    ["sono_faixa_7d", "Dormindo: preço numa faixa menor que (7 dias)", "%"], ["sono_30d", "Dormindo: e o mês variou menos que", "%"],
    ["acorda_rompe", "Acordando: passou o topo da faixa em", "%"], ["acorda_vol_x", "Acordando: ou volume X vezes a mediana de 7 dias", "×"],
    ["acorda_24h", "Acordando: com alta mínima em 24 h de", "%"], ["vol_min_usd", "Parada: negociou menos que (24 h)", "US$"]];
  let VIEW = "visao", R = null, BUSY = false, READY = false, DIRTY = false;
  const F = { st: "", q: "", sort: "h24", ch: "", cat: "" };
  try { Object.assign(F, JSON.parse(localStorage.getItem("dm_f") || "{}")); } catch (e) { /* */ }
  const saveF = () => { try { localStorage.setItem("dm_f", JSON.stringify(F)); } catch (e) { /* */ } };

  // ------------------------------------------------------------------ formatos
  const num = (v, d) => (v == null ? "—" : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: d == null ? 2 : d }));
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
  const pc = (v) => (v == null ? "—" : Math.abs(v) < 0.05 ? "0%" : '<span class="dmpc ' + cls(v) + '">' + (v > 0 ? "+" : "") + num(v, 1) + "%</span>");
  function usd(v) {
    if (v == null) return "—";
    const a = Math.abs(v);
    if (a >= 1e9) return "US$ " + num(v / 1e9, 2) + " bi";
    if (a >= 1e6) return "US$ " + num(v / 1e6, 2) + " mi";
    if (a >= 1e3) return "US$ " + num(v / 1e3, 1) + " mil";
    return "US$ " + num(v, 0);
  }
  function price(v) {
    if (v == null) return "—";
    if (v >= 1) return "US$ " + num(v, 2);
    if (v >= 0.01) return "US$ " + num(v, 4);
    const s = v.toExponential(3).split("e-"), z = Number(s[1]) - 1;
    return "US$ 0,0<sub>" + z + "</sub>" + s[0].replace(".", "").slice(0, 4);
  }
  const dia = (t) => (t ? new Date(t * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" }) : "—");
  const hora = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
  function ago(t) {
    if (!t) return "—";
    const s = Math.max(0, Date.now() / 1000 - t);
    const d = s / 86400;
    return s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : s < 86400 ? (s / 3600).toFixed(1).replace(".", ",") + " h"
      : d < 60 ? (d < 10 ? d.toFixed(1).replace(".", ",") : Math.round(d)) + " dias" : d < 365 ? Math.round(d / 30.4) + " meses" : (d / 365).toFixed(1).replace(".", ",") + " anos";
  }
  const tag = (st) => '<span class="dmst ' + esc(st || "normal") + '">' + esc(ST[st] || "—") + "</span>";
  function coin(m) {
    const cg = m.cg ? '<a href="https://www.coingecko.com/en/coins/' + esc(m.cg) + '" target="_blank" rel="noopener">CoinGecko</a>' : "";
    return '<div class="dmcoin">' + (m.img ? '<img src="' + esc(m.img) + '" alt="" loading="lazy" data-dmcoin="' + esc(m.cmc) + '">' : "") + '<div><b data-dmcoin="' + esc(m.cmc) + '" title="abrir a moeda">' + esc(m.nome) + "</b> <small>" + esc(m.simbolo || "") +
      (m.rank ? " · #" + esc(m.rank) : "") + (m.chain_nome ? chainTag(m.chain_nome, (m.chains || []).join(", ")) : "") + "</small>" +
      '<div class="dmlinks">' + cg + (m.extra ? "" : '<a href="https://coinmarketcap.com/currencies/' + esc(m.cmc) + '/" target="_blank" rel="noopener">CoinMarketCap</a>') +
      (m.extra ? '<a href="#" data-dmdel="' + esc(m.cmc) + '">tirar da lista</a>' : "") + "</div>" +
      (m.extra ? '<span class="dmby">adicionada por <b>' + esc(m.add_por) + "</b> · " + hora(m.add_t) + "</span>" : "") +
      ((m.cats || []).length ? '<div class="dmcats">' + m.cats.slice(0, 3).map((c) => "<span>" + esc(c) + "</span>").join("") + "</div>" : "") +
      ((m.comprar || []).length ? '<button type="button" class="btn sm primary dmbuy" data-dmbuy="' + esc(m.cmc) + '">Comprar</button>' : "") + "</div></div>";
  }
  function spark(p) {
    if (!p || p.length < 2) return "—";
    const lo = Math.min(...p), hi = Math.max(...p), W = 120, H = 32, sp = hi - lo || 1;
    const pts = p.map((v, i) => (i * (W / (p.length - 1))).toFixed(1) + "," + (H - 2 - ((v - lo) / sp) * (H - 4)).toFixed(1)).join(" ");
    const c = p[p.length - 1] >= p[0] ? "#22c55e" : "#ef4444";
    return '<svg class="dmspark" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" aria-label="gráfico de 7 dias"><polyline fill="none" stroke="' + c + '" stroke-width="1.6" points="' + pts + '"/></svg>';
  }
  // 0.32.232 (pedido do dono): célula {h: html, v: valor} deixa a coluna ordenável clicando no título (de novo inverte)
  const TS = {};
  function table(id, head, rows, empty) {
    const el = $(id); if (!el) return;
    if (!rows.length) { el.innerHTML = '<tr><td class="empty" colspan="' + head.length + '">' + esc(empty || "Nada por aqui ainda.") + "</td></tr>"; return; }
    const lab = head.map((h) => esc(String(h).replace(/<[^>]*>/g, "")));
    const sortable = head.map((_, i) => rows[0][i] != null && typeof rows[0][i] === "object" && "v" in rows[0][i]);
    el.innerHTML = "<thead><tr>" + head.map((h, i) => "<th" + (sortable[i] ? ' data-tsi="' + i + '" title="clique para ordenar; de novo para inverter"' : "") + ">" + h + "</th>").join("") + "</tr></thead><tbody>" +
      rows.map((r) => "<tr>" + r.map((c, i) => { const o = c != null && typeof c === "object"; const v = o ? c.v : null;
        return '<td data-l="' + lab[i] + '"' + (o ? ' data-v="' + esc(v == null ? "" : v) + '"' : "") + ">" + ((o ? c.h : c) == null ? "" : (o ? c.h : c)) + "</td>"; }).join("") + "</tr>").join("") + "</tbody>";
    tsApply(id);
  }
  function tsApply(id) {
    const el = $(id), s = TS[id]; if (!el || !s) return;
    const tb = el.tBodies[0]; if (!tb) return;
    const val = (tr) => { const d = tr.children[s.i] && tr.children[s.i].dataset.v; return d === "" || d == null ? null : isNaN(+d) ? d.toLowerCase() : +d; };
    const rows = [...tb.rows].sort((a, b) => { const x = val(a), y = val(b);
      if (x == null || y == null) return (x == null) - (y == null);
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return s.asc ? c : -c; });
    rows.forEach((r) => tb.appendChild(r));
    el.querySelectorAll("th[data-tsi]").forEach((th) => { th.classList.toggle("on", +th.dataset.tsi === s.i); th.textContent = th.textContent.replace(/ [▲▼]$/, "") + (+th.dataset.tsi === s.i ? (s.asc ? " ▲" : " ▼") : ""); });
  }
  const V = (h, v) => ({ h, v });
  const stV = (st) => { const i = ST_ORD.indexOf(st); return i < 0 ? 99 : i; };

  // ------------------------------------------------------------------ monitor
  function sysInfo() {
    const s = (R && R.status) || {};
    const erro = s.ultimo_erro && s.ultimo_erro_t && (!s.leitura_t || s.ultimo_erro_t > s.leitura_t);
    const velho = !s.leitura_t || Date.now() / 1000 - s.leitura_t > 3 * 3600;
    const ok = !!(R && R.ligado && !erro && !velho);
    return { s, ok, probs: [erro && s.ultimo_erro, velho && !erro && (s.leitura_t ? "sem leitura há mais de 3 h" : "primeira leitura ainda não terminou"), s.pausa_s && "CoinGecko pediu para esperar (" + s.pausa_s + " s)"].filter(Boolean) };
  }
  function drawSys() {
    const i = sysInfo(), s = i.s;
    $("sysDot").className = "dot " + (i.ok ? "on" : "off");
    $("sysT").textContent = !R ? "Monitor…" : !R.ligado ? "Monitor OFF" : i.ok ? "Monitor ON" : "Monitor com problema";
    $("sysS").textContent = !R ? "conectando" : !R.ligado ? "desligado" : i.ok ? "lido há " + ago(s.leitura_t) + " · " + num(s.achadas, 0) + " moedas" : i.probs.join(" · ");
    if (!$("sysM").hidden) drawSysModal();
  }
  function drawSysModal() {
    const i = sysInfo(), s = i.s;
    const rows = [
      ["Leitura", R && R.ligado ? (i.ok ? '<span class="up">funcionando</span>' : '<span class="down">' + esc(i.probs.join(" · ") || "com problema") + "</span>") : '<span class="down">desligada</span>'],
      ["Chave", R && R.chave ? "chave Demo da CoinGecko" : "sem chave · API pública (mais lenta, pode pedir para esperar)"],
      ["Última leitura", s.leitura_t ? hora(s.leitura_t) + " (há " + ago(s.leitura_t) + ") · lê a cada " + num(s.a_cada_min, 0) + " min · próxima em " + ago(Date.now() / 1000 - (s.proxima_s || 0)) : "ainda não"],
      ["Moedas", num(s.moedas, 0) + " na lista · " + num(s.achadas, 0) + " com preço na CoinGecko"],
      ["Ligação com a CoinGecko", s.mapa_t ? "feita " + hora(s.mapa_t) + " (refeita toda semana)" : "ainda não"],
      ["Consultas", num(s.consultas, 0) + " desde " + hora(s.desde) + (s.limite_429 ? " · " + num(s.limite_429, 0) + " vezes pediu para esperar" : "")],
      ["Fotos guardadas", num(s.fotos, 0) + " de hora em hora (o volume “acima do normal” precisa de 24)"],
      ["Blockchain (GeckoTerminal)", (() => { const b = (R && R.blockchain) || {}; return num(b.lidas || 0, 0) + " de " + num(b.vigiadas || 0, 0) + " moedas lidas · " + num(b.consultas || 0, 0) + " consultas" +
        (b.limite_429 ? " · pediu para esperar " + num(b.limite_429, 0) + " vezes" : "") + (b.ultimo_erro ? " · último erro há " + ago(b.ultimo_erro_t) + ": " + esc(b.ultimo_erro) : ""); })()],
      ["Erros", num(s.erros, 0) + (s.ultimo_erro ? " · último há " + ago(s.ultimo_erro_t) + ": " + esc(s.ultimo_erro) : "")],
    ];
    $("sysMB").innerHTML = '<div class="tbl-wrap"><table class="systbl nocard"><tbody>' + rows.map((r) => "<tr><td>" + r[0] + "</td><td>" + r[1] + "</td></tr>").join("") + "</tbody></table></div>";
  }

  // ------------------------------------------------------------------ telas
  const M = () => (R && R.moedas) || [];
  function drawVisao() {
    const c = (R && R.contagem) || {};
    $("ovK").innerHTML = ["acordando", "pump", "dump", "dormindo", "normal", "parada", "morta"].map((k) =>
      '<div class="kpi dmk" data-dmst="' + k + '" role="button" tabindex="0"><div class="k"><span>' + esc(ST[k]) + '</span></div><div class="v">' + num(c[k] || 0, 0) + '</div><div class="d">' +
      { acordando: "saindo do sono agora", pump: "alta forte em 1 h ou 24 h", dump: "queda forte em 1 h ou 24 h", dormindo: "preço parado, faixa estreita", normal: "mexendo sem exagero", parada: "quase sem negócio", morta: "sem preço na CoinMarketCap" }[k] + "</div></div>").join("");
    const ex = M().filter((m) => m.extra).length;
    $("ovAddN").textContent = num(M().length, 0) + " moedas vigiadas" + (ex ? " · " + ex + " adicionadas na tela" : "");
    table("ovAl", ["Quando", "Moeda", "Virou", "1 h", "24 h", "Por quê"], ((R && R.alertas) || []).slice(0, 50).map((a) => [V(hora(a.t), a.t),
      V('<span class="dmcoin"><b data-dmcoin="' + esc(a.cmc) + '">' + esc(a.nome || a.cmc) + "</b></span> <small class=\"muted\">" + esc(a.simbolo || "") + "</small>", a.nome || a.cmc),
      V(tag(a.para) + ' <small class="muted">era ' + esc(ST[a.de] || a.de) + "</small>", a.para), V(pc(a.h1), a.h1), V(pc(a.h24), a.h24),
      '<small class="muted">' + esc((a.por || []).join(" · ")) + "</small>"]), "Nenhum alerta ainda. Eles aparecem quando uma moeda muda para pump, dump ou acordando.");
    const vivas = M().filter((m) => m.h24 != null && m.status !== "parada");
    const up = vivas.slice().sort((a, b) => b.h24 - a.h24).slice(0, 8), dn = vivas.slice().sort((a, b) => a.h24 - b.h24).slice(0, 8);
    table("ovMv", ["Moeda", "24 h", "7 dias", "Situação"], up.concat(dn).map((m) => [V(coin(m), m.nome), V(pc(m.h24), m.h24), V(pc(m.d7), m.d7), V(tag(m.status), stV(m.status))]), "A primeira leitura ainda não terminou.");
    const ev = [];
    M().forEach((m) => ((m.bc && m.bc.last3) || []).forEach((x) => ev.push([x, m])));
    ev.sort((a, b) => b[0].t - a[0].t);
    const bs = (R && R.blockchain) || {};
    $("ovBcSub").textContent = "as negociações mais recentes das moedas da lista, lidas direto da blockchain (GeckoTerminal) · " + num(bs.lidas || 0, 0) + " de " + num(bs.vigiadas || 0, 0) +
      " moedas já lidas · cada uma é lida de novo a cada " + num(bs.a_cada_min || 30, 0) + " min · " + num(bs.paradas_24h || 0, 0) + " paradas há mais de 24 h";
    table("ovBc", ["Quando", "Moeda", "Ação", "Valor", "Rede", "Transação"], ev.slice(0, 30).map(([x, m]) => [V("há " + ago(x.t), x.t), V('<span class="dmcoin"><b data-dmcoin="' + esc(m.cmc) + '">' + esc(m.nome) + '</b></span> <small class="muted">' + esc(m.simbolo) + "</small>", m.nome),
      V('<span class="' + (x.kind === "compra" ? "up" : "down") + '">' + esc(x.kind) + "</span>", x.kind), V("US$ " + num(x.usd, x.usd >= 100 ? 0 : 2), x.usd), V(chainTag(m.chain_nome), m.chain_nome || ""),
      x.tx && EXPL[m.bc.net] ? '<a href="' + EXPL[m.bc.net] + esc(x.tx) + '" target="_blank" rel="noopener">ver na blockchain</a>' : "—"]), "A leitura da blockchain começa logo depois da primeira leitura da CoinGecko (1 moeda a cada 6 s).");
    const dorm = M().filter((m) => m.status === "dormindo").sort((a, b) => Math.abs(a.d30 || 0) - Math.abs(b.d30 || 0)).slice(0, 15);
    table("ovDm", ["Moeda", "Preço", "7 dias", "30 dias", "Volume 24 h", "Gráfico 7 dias", "Por quê"], dorm.map((m) => [V(coin(m), m.nome), V(price(m.preco), m.preco), V(pc(m.d7), m.d7), V(pc(m.d30), m.d30), V(usd(m.vol), m.vol), spark(m.spark),
      '<small class="muted">' + esc((m.por || []).join(" · ")) + "</small>"]), "Nenhuma moeda dormindo agora.");
  }
  // 0.32.234 (pedido do dono): gráfico da DEX dentro da janela da moeda e botões para abrir a moeda nos sites de DEX
  const DS = { eth: "ethereum", bsc: "bsc", solana: "solana", base: "base", arbitrum: "arbitrum", polygon_pos: "polygon", avax: "avalanche", tron: "tron",
    optimism: "optimism", ton: "ton", "sui-network": "sui", cro: "cronos", ftm: "fantom", sonic: "sonic", mantle: "mantle", linea: "linea" };
  const DT = { eth: "ether", bsc: "bnb", solana: "solana", base: "base", arbitrum: "arbitrum", polygon_pos: "polygon", avax: "avalanche", tron: "tron", optimism: "optimism" };
  function dexLinks(m, r) {
    const p = (r && r.pool) || {}, a = (r && r.alvo) || {}, net = p.net || a.net, pool = p.pool;
    const L = [];
    if (net && pool) L.push(["GeckoTerminal", "https://www.geckoterminal.com/" + net + "/pools/" + pool]);
    if (net && pool && DS[net]) L.push(["DexScreener", "https://dexscreener.com/" + DS[net] + "/" + pool]);
    else L.push(["DexScreener", "https://dexscreener.com/search?q=" + encodeURIComponent(a.contrato || m.simbolo || m.nome)]);
    if (net && pool && DT[net]) L.push(["DEXTools", "https://www.dextools.io/app/en/" + DT[net] + "/pair-explorer/" + pool]);
    if (net === "solana" && a.contrato) L.push(["Birdeye", "https://birdeye.so/token/" + a.contrato + "?chain=solana"]);
    if (m.cg) L.push(["CoinGecko", "https://www.coingecko.com/en/coins/" + m.cg]);
    return '<div class="cmdex">' + L.map((x) => '<a class="btn sm" href="' + esc(x[1]) + '" target="_blank" rel="noopener">' + esc(x[0]) + " ↗</a>").join("") + "</div>";
  }
  function dexEmbed(src) {
    const r = CM && CM.r, p = (r && r.pool) || {}, box = $("cmDex"); if (!box) return;
    document.querySelectorAll("#cmSrc button").forEach((b) => b.classList.toggle("on", b.dataset.cms === src));
    $("cmChart").hidden = src !== "cg"; box.hidden = src === "cg";
    if (src === "cg") return;
    if (!p.pool || !p.net) { box.innerHTML = '<span class="muted">' + (r && r.moeda && r.moeda.rede_propria ? "moeda da própria rede: não tem pool de DEX" : "pool da DEX não achado para esta moeda") + "</span>"; return; }
    const url = src === "gt" ? "https://www.geckoterminal.com/" + p.net + "/pools/" + p.pool + "?embed=1&info=0&swaps=0&light_chart=0"
      : DS[p.net] ? "https://dexscreener.com/" + DS[p.net] + "/" + p.pool + "?embed=1&theme=dark&info=0&trades=0" : null;
    box.innerHTML = url ? '<iframe src="' + esc(url) + '" title="gráfico da DEX" loading="lazy" referrerpolicy="no-referrer" allowfullscreen></iframe>' : '<span class="muted">a DexScreener não tem esta rede</span>';
  }
  // 0.32.232 (pedido do dono): janela da moeda — gráfico de 30 dias, porcentagens, blockchain e as últimas negociações
  let CM = null;
  async function openCoin(key) {
    const m = M().find((x) => x.cmc === key); if (!m) return;
    CM = { key, r: null, rng: CM && CM.rng || 30 };
    $("coinMH").innerHTML = (m.img ? '<img src="' + esc(m.img) + '" alt="">' : "") + '<div style="min-width:0"><h2 id="coinMT">' + esc(m.nome) + ' <small class="muted">' + esc(m.simbolo || "") + "</small></h2>" +
      '<div class="sub">' + tag(m.status) + (m.chain_nome ? " " + chainTag(m.chain_nome) : "") + (m.rank ? " · #" + esc(m.rank) + " em valor de mercado" : "") + "</div>" +
      ((m.comprar || []).length ? '<button type="button" class="btn sm primary dmbuy" data-dmbuy="' + esc(m.cmc) + '">Comprar</button>' : "") + "</div>";
    $("coinMB").innerHTML = coinBody(m, null);
    $("coinM").hidden = false;
    const r = await BB.api("/api/dormant/moeda?key=" + encodeURIComponent(key), { quiet: true });
    if (!CM || CM.key !== key) return;
    CM.r = r;
    $("coinMB").innerHTML = coinBody((r && r.moeda) || m, r);
    drawCoinChart();
  }
  function coinBody(m, r) {
    const k = (l, v, s) => "<div><small>" + l + "</small><b>" + v + "</b>" + (s ? "<small>" + s + "</small>" : "") + "</div>";
    let h = '<div class="cmgrid">' + k("Preço", price(m.preco)) + k("1 h", pc(m.h1)) + k("24 h", pc(m.h24)) + k("7 dias", pc(m.d7)) + k("30 dias", pc(m.d30)) +
      k("Volume 24 h", usd(m.vol), m.vol_x ? num(m.vol_x, 1) + "× o normal" : "") + k("Valor de mercado", usd(m.mcap)) +
      k("Máxima histórica", price(m.ath), (m.ath_t ? "em " + dia(m.ath_t) + " (há " + ago(m.ath_t) + ")<br>" : "") + (m.ath_pct != null ? pc(m.ath_pct) + " dela" : "")) +
      k("Mínima histórica", price(m.atl), (m.atl_t ? "em " + dia(m.atl_t) + " (há " + ago(m.atl_t) + ")<br>" : "") + (m.atl_pct != null ? pc(m.atl_pct) + " acima dela" : "")) + "</div>";
    h += (m.por && m.por.length ? '<div class="decbox"><b>Por que está ' + esc((ST[m.status] || "").toLowerCase()) + ":</b> " + esc(m.por.join(" · ")) + "</div>" : "");
    const fonte = (r && r.grafico && r.grafico.fonte) || "CoinGecko";
    h += '<div class="card" style="margin-top:12px"><header><div><h2>Gráfico</h2><div class="sub">' + esc(fonte === "CoinGecko" ? "preço em dólar (CoinGecko)" : "preço em dólar do pool da DEX (" + fonte + "), porque a CoinGecko pediu para esperar") +
      ' · passe o mouse ou o dedo para ver cada ponto</div></div><div class="sp"></div>' +
      '<div class="seg" id="cmSrc"><button data-cms="cg" class="on">Preço</button><button data-cms="gt">DEX · GeckoTerminal</button><button data-cms="ds">DEX · DexScreener</button></div>' +
      '<div class="seg" id="cmRng"><button data-cmr="1">24 h</button><button data-cmr="7">7 dias</button><button data-cmr="30">30 dias</button></div></header>' +
      '<div class="cmchart" id="cmChart">' + (r ? "" : '<span class="muted">carregando…</span>') + '</div><div class="cmdexbox" id="cmDex" hidden></div>' +
      (r ? '<div style="margin-top:10px"><small class="muted">Ver esta moeda nos gráficos de DEX:</small>' + dexLinks(m, r) + "</div>" : "") + "</div>";
    const n = r && r.negocios;
    h += '<div class="card"><header><div><h2>Últimas negociações na blockchain</h2><div class="sub">' +
      (m.rede_propria ? "moeda da própria rede: não tem pool de negociação para ler" : n && !n.erro ? num(n.n24 >= 300 ? 300 : n.n24, 0) + (n.n24 >= 300 ? "+" : "") + " negócios nas últimas 24 h · lidas direto da blockchain (GeckoTerminal)" + (r.pool && r.pool.nome ? " · pool " + esc(r.pool.nome) : "")
        : n && n.erro ? '<span class="down">' + esc(n.erro) + "</span>" : r ? "a moeda ainda não foi lida na blockchain (fila de 1 a cada 6 s)" : "carregando…") + "</div></div></header>" +
      '<div class="tbl-wrap"><table id="cmTr"></table></div></div>';
    const ct = (r && r.contratos) || [], cats = (r && r.info && r.info.cats) || m.cats || [];
    h += '<div class="card"><header><div><h2>Sobre a moeda</h2></div></header><div class="help">' +
      "<p><b>Blockchain:</b> " + (chainTag(m.chain_nome) || "?") + (m.chains && m.chains.length > 1 ? " · também em " + m.chains.filter((c) => c !== m.chain_nome).map((c) => chainTag(c)).join(" ") : "") + "</p>" +
      (ct.length ? "<p><b>Contratos:</b></p>" + ct.map((c) => '<div class="cmaddr" style="margin:4px 0">' + chainTag(c.rede) + " " + esc(c.endereco) + "</div>").join("") : "") +
      (cats.length ? '<p><b>Categorias:</b></p><div class="dmcats">' + cats.map((c) => "<span>" + esc(c) + "</span>").join("") + "</div>" : "") +
      "<p><b>Na lista desde:</b> " + (m.extra ? "adicionada por " + esc(m.add_por) + " em " + hora(m.add_t) : "watchlist da CoinMarketCap (05/11/2026)") + "</p>" +
      '<p class="dmlinks">' + (m.cg ? '<a href="https://www.coingecko.com/en/coins/' + esc(m.cg) + '" target="_blank" rel="noopener">CoinGecko</a>' : "") +
      (m.extra ? "" : '<a href="https://coinmarketcap.com/currencies/' + esc(m.cmc) + '/" target="_blank" rel="noopener">CoinMarketCap</a>') +
      (r && r.pool && r.pool.pool ? '<a href="https://www.geckoterminal.com/' + esc(r.pool.net) + "/pools/" + esc(r.pool.pool) + '" target="_blank" rel="noopener">GeckoTerminal (pool)</a>' : "") + "</p></div></div>";
    setTimeout(() => {
      const L = (n && n.lista) || [];
      table("cmTr", ["Quando", "Ação", "Valor", "Carteira", "Transação"], L.map((x) => [V(hora(x.t) + ' <small class="muted">há ' + ago(x.t) + "</small>", x.t),
        V('<span class="' + (x.kind === "compra" ? "up" : "down") + '">' + esc(x.kind) + "</span>", x.kind), V("US$ " + num(x.usd, x.usd >= 100 ? 0 : 2), x.usd),
        V('<span class="cmaddr">' + esc((x.wallet || "").slice(0, 6) + "…" + (x.wallet || "").slice(-4)) + "</span>", x.wallet || ""),
        x.tx && EXPL[n.net] ? '<a href="' + EXPL[n.net] + esc(x.tx) + '" target="_blank" rel="noopener">ver</a>' : "—"]), r ? "Sem negociações para mostrar." : "carregando…");
    }, 0);
    return h;
  }
  function drawCoinChart() {
    const box = $("cmChart"); if (!box || !CM || !CM.r) return;
    document.querySelectorAll("#cmRng button").forEach((b) => b.classList.toggle("on", +b.dataset.cmr === CM.rng));
    const g = CM.r.grafico || {};
    if (g.erro) { box.innerHTML = '<span class="down">' + esc(g.erro) + "</span>"; return; }
    const lim = Date.now() / 1000 - CM.rng * 86400;
    const P = (g.precos || []).filter((p) => p[0] >= lim), Vv = (g.volumes || []).filter((p) => p[0] >= lim);
    if (P.length < 2) { box.innerHTML = '<span class="muted">sem pontos suficientes neste período</span>'; return; }
    const W = 900, H = 220, top = 10, ph = 150, vh = 50;
    const lo = Math.min(...P.map((p) => p[1])), hi = Math.max(...P.map((p) => p[1])), sp = hi - lo || hi || 1;
    const t0 = P[0][0], t1 = P[P.length - 1][0], tw = t1 - t0 || 1, vmax = Math.max(1, ...Vv.map((v) => v[1]));
    const X = (t) => ((t - t0) / tw) * W, Y = (v) => top + ph - ((v - lo) / sp) * ph;
    const up = P[P.length - 1][1] >= P[0][1], cor = up ? "#22c55e" : "#ef4444";
    const line = P.map((p) => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" ");
    const bw = Math.max(1, W / Math.max(1, Vv.length) - 1);
    const bars = Vv.map((v) => '<rect x="' + X(v[0]).toFixed(1) + '" y="' + (H - (v[1] / vmax) * vh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + ((v[1] / vmax) * vh).toFixed(1) + '" fill="rgba(167,139,250,.35)"/>').join("");
    box.innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none">' + bars +
      '<polygon points="0,' + (top + ph) + " " + line + " " + W + "," + (top + ph) + '" fill="' + cor + '" fill-opacity=".08"/>' +
      '<polyline points="' + line + '" fill="none" stroke="' + cor + '" stroke-width="2" vector-effect="non-scaling-stroke"/>' +
      '<line id="cmCur" x1="0" x2="0" y1="0" y2="' + H + '" stroke="var(--muted)" stroke-dasharray="3 3" visibility="hidden"/></svg>' +
      '<div class="cmtip" id="cmTip"></div><div class="sub" style="display:flex;justify-content:space-between"><span>' + hora(t0) + "</span><span>mín " + price(lo) + " · máx " + price(hi) +
      " · " + pc((P[P.length - 1][1] / P[0][1] - 1) * 100) + "</span><span>" + hora(t1) + "</span></div>";
    const svg = box.querySelector("svg");
    const move = (ev) => {
      const r = svg.getBoundingClientRect(), cx = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) / r.width;
      const t = t0 + cx * tw; let best = P[0]; for (const p of P) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
      const cur = $("cmCur"), tip = $("cmTip"); if (!cur || !tip) return;
      cur.setAttribute("x1", X(best[0])); cur.setAttribute("x2", X(best[0])); cur.setAttribute("visibility", "visible");
      const vol = Vv.reduce((a, v) => (Math.abs(v[0] - best[0]) < Math.abs(a[0] - best[0]) ? v : a), Vv[0] || [0, null]);
      tip.innerHTML = hora(best[0]) + " · <b>" + price(best[1]) + "</b>" + (vol && vol[1] != null ? " · vol. " + usd(vol[1]) : "");
      tip.style.display = "block";
      tip.style.left = Math.min(r.width - tip.offsetWidth, Math.max(0, cx * r.width - tip.offsetWidth / 2)) + "px"; tip.style.top = "0px";
    };
    svg.addEventListener("mousemove", move); svg.addEventListener("touchmove", move, { passive: true });
    svg.addEventListener("mouseleave", () => { const t = $("cmTip"), c = $("cmCur"); if (t) t.style.display = "none"; if (c) c.setAttribute("visibility", "hidden"); });
  }
  function drawMoedas() {
    const c = (R && R.contagem) || {};
    $("mFilt").innerHTML = '<button data-dmf=""' + (F.st ? "" : ' class="on"') + ">Todas · " + num(M().length, 0) + "</button>" +
      ST_ORD.filter((k) => c[k]).map((k) => '<button data-dmf="' + k + '"' + (F.st === k ? ' class="on"' : "") + ">" + esc(ST[k]) + " · " + num(c[k], 0) + "</button>").join("");
    if ($("mQ").value !== F.q && document.activeElement !== $("mQ")) $("mQ").value = F.q;
    $("mSort").value = [...$("mSort").options].some((o) => o.value === F.sort) ? F.sort : "";
    const q = F.q.trim().toLowerCase();
    const chs = {}, cats = {};
    M().forEach((m) => { if (m.chain_nome) chs[m.chain_nome] = (chs[m.chain_nome] || 0) + 1; (m.cats || []).forEach((c) => { cats[c] = (cats[c] || 0) + 1; }); });
    // 0.32.241 (pedido do dono): blockchains como botões pequenos; clicar abre a lista daquela rede, clicar de novo volta para todas
    $("mChain").innerHTML = '<button type="button" class="dmchip all' + (F.ch ? "" : " on") + '" data-dmchf="" aria-pressed="' + !F.ch + '">Todas · ' + num(M().length, 0) + "</button>" +
      Object.entries(chs).sort((a, b) => b[1] - a[1]).map((x) => '<button type="button" class="dmchip' + (F.ch === x[0] ? " on" : "") + '" data-dmchf="' + esc(x[0]) + '" aria-pressed="' + (F.ch === x[0]) + '">' + chainTag(x[0]) + "<small>" + x[1] + "</small></button>").join("");
    $("mCat").innerHTML = '<option value="">Todas as categorias</option>' + Object.entries(cats).sort((a, b) => b[1] - a[1]).map((x) => '<option value="' + esc(x[0]) + '"' + (F.cat === x[0] ? " selected" : "") + ">" + esc(x[0]) + " · " + x[1] + "</option>").join("");
    let L = M().filter((m) => (!F.st || m.status === F.st) && (!F.ch || m.chain_nome === F.ch) && (!F.cat || (m.cats || []).includes(F.cat)) &&
      (!q || (m.nome + " " + m.simbolo + " " + m.cmc + " " + (m.chain_nome || "") + " " + (m.cats || []).join(" ")).toLowerCase().includes(q)));
    L.forEach((m) => { m.bc_t = m.bc && m.bc.t && !m.bc.sem_pool ? (m.bc.ultima_t || 1) : null; });
    // 0.32.231 (pedido do dono): clicar no título da coluna ordena; clicar de novo inverte (maior → menor / menor → maior)
    const sk = F.sort.replace("-", ""), asc = F.sort.startsWith("-");
    const k = sk === "bc" ? "bc_t" : sk, stI = (m) => { const i = ST_ORD.indexOf(m.status); return i < 0 ? 99 : i; };
    L = L.slice().sort((a, b) => {
      if (k === "nome") return (asc ? -1 : 1) * String(a.nome).localeCompare(String(b.nome));
      if (k === "status") return (asc ? -1 : 1) * (stI(a) - stI(b));
      return ((a[k] == null) - (b[k] == null)) || (asc ? 1 : -1) * ((a[k] || 0) - (b[k] || 0));
    });
    const th = (nome, key) => '<button type="button" class="dmth' + (sk === key ? " on" : "") + '" data-dmsort="' + key + '" title="clique para ordenar; de novo para inverter">' + nome +
      (sk === key ? ((asc !== (key === "nome" || key === "status")) ? " ▲" : " ▼") : "") + "</button>";
    table("mT", [th("Moeda", "nome"), th("Situação", "status"), th("Últimas 3 ações na blockchain", "bc"), th("Preço", "preco"), th("1 h", "h1"), th("24 h", "h24"), th("7 dias", "d7"),
      th("30 dias", "d30"), th("Volume 24 h", "vol"), th("Valor de mercado", "mcap"), "Gráfico 7 dias"], L.slice(0, 400).map((m) => [coin(m),
      tag(m.status) + (m.por && m.por.length ? '<span class="dmwhy">' + esc(m.por.join(" · ")) + "</span>" : ""), bcCell(m), price(m.preco), pc(m.h1), pc(m.h24), pc(m.d7), pc(m.d30),
      usd(m.vol) + (m.vol_x ? '<span class="dmwhy">' + num(m.vol_x, 1) + "× o normal</span>" : ""), usd(m.mcap), spark(m.spark)]), "Nenhuma moeda com esse filtro.");
    $("mSub").textContent = num(L.length, 0) + " moedas" + (L.length > 400 ? " · mostrando as 400 primeiras" : "") + " · gráfico = últimos 7 dias (CoinGecko)";
  }
  function drawGrupos() {
    const g = (R && R.grupos) || {}, s = (R && R.status) || {};
    const row = (x, tipo) => [tipo === "ch" ? chainTag(x.nome) : '<b>' + esc(x.nome) + "</b>", num(x.n, 0),
      ["acordando", "pump", "dump", "dormindo"].map((k) => x.st[k] ? tag(k) + " " + x.st[k] : "").filter(Boolean).join(" ") || '<span class="muted">—</span>',
      pc(x.h24), pc(x.d7), x.top ? esc(x.top.simbolo || x.top.nome) + " " + pc(x.top.h24) : "—", x.fundo ? esc(x.fundo.simbolo || x.fundo.nome) + " " + pc(x.fundo.h24) : "—"];
    const H = ["Grupo", "Moedas", "Acordando, pump, dump, dormindo", "Mediana 24 h", "Mediana 7 dias", "Maior alta 24 h", "Maior queda 24 h"];
    table("gCh", H, (g.blockchain || []).map((x) => row(x, "ch")), "A primeira leitura ainda não terminou.");
    table("gCat", H, (g.categoria || []).map((x) => row(x, "cat")), "As categorias chegam aos poucos (uma moeda a cada 20 s).");
    document.querySelectorAll("#gCh tbody tr").forEach((tr, i) => { const x = (g.blockchain || [])[i]; if (x) { tr.className = "dmgo"; tr.dataset.dmch = x.nome; } });
    document.querySelectorAll("#gCat tbody tr").forEach((tr, i) => { const x = (g.categoria || [])[i]; if (x) { tr.className = "dmgo"; tr.dataset.dmcat = x.nome; } });
    $("gCatSub").textContent = "categorias da CoinGecko (uma moeda pode estar em várias) · " + num(s.com_info || 0, 0) + " de " + num(s.achadas || 0, 0) +
      " moedas já com categoria (chegam aos poucos, uma a cada 20 s) · clique numa linha para ver as moedas";
  }
  function drawConfig() {
    $("kSt").innerHTML = R && R.chave ? '<span class="up">Chave Demo configurada.</span> As consultas usam a sua cota grátis (10 mil por mês).' : "Sem chave: usando a API pública da CoinGecko. Funciona, mas é mais lenta e pode pedir para esperar.";
    $("kDel").hidden = !(R && R.chave);
    if (!DIRTY && R && R.cfg) {
      const c = R.cfg, p = R.padrao || {};
      $("rCfg").innerHTML = RG.map((x) => '<div class="field"><label for="dm_' + x[0] + '">' + esc(x[1]) + '</label><div class="row"><input class="in w100" id="dm_' + x[0] +
        '" type="number" step="any" value="' + esc(c[x[0]]) + '"><span class="muted">' + esc(x[2]) + (p[x[0]] !== c[x[0]] ? " · padrão " + esc(p[x[0]]) : "") + "</span></div></div>").join("");
    }
    const ord = { sem_cg: 0, morta: 1, parada: 2 };
    const L = M().filter((m) => m.extra || m.status in ord || !m.status).sort((a, b) => (b.extra - a.extra) || ((ord[a.status] ?? 3) - (ord[b.status] ?? 3)));
    $("lSub").textContent = "a watchlist da CoinMarketCap lida em 05/11/2026 · " + num(M().length, 0) + " moedas · abaixo as que não têm leitura útil";
    table("lT", ["Moeda", "Situação", "O que quer dizer"], L.map((m) => [coin(m), tag(m.status || "sem_cg"),
      m.extra ? "adicionada na tela por " + esc(m.add_por) + " em " + hora(m.add_t) : m.status === "morta" ? "sem preço na CoinMarketCap e não achada com negócio na CoinGecko: projeto parado ou tirado das corretoras"
        : m.status === "parada" ? "existe, mas quase ninguém negocia (menos que o mínimo de volume em 24 h)" : "não achei a mesma moeda na CoinGecko pelo nome"]), "Todas as moedas da lista têm leitura.");
  }
  // ------------------------------------------------------------------ 0.32.242: carteiras, compra e histórico
  // Senha e chave ficam só nos campos, e os campos são limpos logo depois de cada ação; nada disso vai para localStorage ou variável.
  const REDE = { solana: "Solana", ethereum: "Ethereum", "binance-smart-chain": "BNB Chain", base: "Base", "polygon-pos": "Polygon", avalanche: "Avalanche", "arbitrum-one": "Arbitrum" };
  const MOEDA = { solana: "SOL", ethereum: "ETH", "binance-smart-chain": "BNB", base: "ETH", "polygon-pos": "POL", avalanche: "AVAX", "arbitrum-one": "ETH" };
  const LIM = [["max_usd", "Máximo por compra", "US$"], ["dia_usd", "Máximo em 24 h", "US$"], ["slip_pct", "Folga de preço (slippage)", "%"]];
  let WAL = null;
  const clearPass = () => ["wPass", "wPass2", "wPassN", "wPassN2", "buySenha", "buyOk", "askSenha", "askOk"].forEach((id) => { if ($(id)) $(id).value = ""; });
  async function loadWal() {
    const r = await BB.api("/api/dormant/carteiras", { quiet: true });
    if (!r || r.error) { $("wList").innerHTML = '<span class="down">' + esc((r && r.error) || "não consegui ler as carteiras") + "</span>"; return; }
    WAL = r;
    drawWal();
    const b = await BB.api("/api/dormant/carteiras/saldos", { quiet: true });
    if (b && !b.error) document.querySelectorAll("[data-wbal]").forEach((el) => { const v = b[el.dataset.wbal]; el.textContent = v == null ? "saldo não lido" : "saldo: " + num(v, 6) + " " + el.dataset.wm; });
  }
  function drawWal() {
    const w = WAL, c = w.cfg;
    const on = $("wOn");
    on.className = "tgl sw " + (c.on ? "on" : "off"); on.textContent = c.on ? "Ligado" : "Desligado"; on.setAttribute("aria-checked", c.on ? "true" : "false");
    $("wOnSub").textContent = c.on ? "o botão Comprar funciona, sempre com a sua confirmação e a senha" : "desligado: nenhuma compra sai, mesmo com a senha certa";
    const avisos = [];
    if (!w.trava_geral) avisos.push("A trava geral do servidor (PUMP_REAL_ALLOWED) está fechada: nenhuma compra sai enquanto ela não for aberta no Portainer.");
    if (w.trava_s) avisos.push("Senha errada muitas vezes: compras e chaves travadas por mais " + Math.max(1, Math.round(w.trava_s / 60)) + " min.");
    $("wWarn").hidden = !avisos.length; $("wWarn").textContent = avisos.join(" ");
    $("wLim").innerHTML = LIM.map((x) => '<div class="field"><label for="wl_' + x[0] + '">' + esc(x[1]) + '</label><div class="row"><input class="in w100" id="wl_' + x[0] + '" type="number" step="any" min="' + esc(w.limites[x[0]][0]) + '" max="' + esc(w.limites[x[0]][1]) + '" value="' + esc(c[x[0]]) + '"><span class="muted">' + esc(x[2]) + "</span></div></div>").join("");
    $("wPassT").textContent = w.tem_senha ? "Senha de compra" : "Crie a senha de compra";
    $("wPassS").textContent = w.tem_senha ? "digite aqui para salvar uma carteira ou subir um limite" : "mínimo de " + w.senha_min + " caracteres · vale para todas as carteiras · não dá para recuperar, guarde num lugar seguro";
    $("wPass").placeholder = w.tem_senha ? "senha de compra" : "senha nova"; $("wPass2").hidden = w.tem_senha; $("wPassCh").hidden = !w.tem_senha;
    $("wList").innerHTML = w.redes.map((r) => '<div class="dmwal"><div class="h">' + chainTag(r.nome) + ' <small class="muted">compra por ' + esc(r.dex) + " · paga em " + esc(r.moeda) + '</small><span class="sp"></span>' +
      (r.endereco ? '<span class="tag win">configurada</span> <button type="button" class="btn sm tgl off" data-wdel="' + esc(r.rede) + '">Remover</button>' : '<span class="tag neutral">sem carteira</span>') + "</div>" +
      (r.endereco ? '<div class="ad">' + esc(r.endereco) + '</div><div class="muted small" data-wbal="' + esc(r.rede) + '" data-wm="' + esc(r.moeda) + '">lendo o saldo…</div>' : "") +
      '<div class="f"><input class="in" id="wk_' + esc(r.rede) + '" type="password" autocomplete="off" spellcheck="false" autocapitalize="off" placeholder="' + (r.endereco ? "trocar: cole a nova chave privada" : "cole a chave privada") + '" aria-label="Chave privada de ' + esc(r.nome) + '">' +
      (r.tipo === "evm" ? '<label class="small muted"><input type="checkbox" id="we_' + esc(r.rede) + '"> usar nas 6 redes EVM</label>' : "") +
      '<button type="button" class="btn primary sm" data-wsave="' + esc(r.rede) + '">Salvar</button></div></div>').join("");
  }
  let ASK = null;
  function ask(titulo, html, onGo) {
    $("askMT").textContent = titulo; $("askMB").innerHTML = html; $("askM").hidden = false; ASK = onGo;
    const f = $("askMB").querySelector("input"); if (f) setTimeout(() => f.focus(), 50);
  }
  const closeAsk = () => { $("askM").hidden = true; $("askMB").innerHTML = ""; ASK = null; };
  const askPass = (label) => '<div class="buyform"><div><label for="askSenha">' + esc(label) + '</label><input class="in" id="askSenha" type="password" autocomplete="off" spellcheck="false"></div>';
  // compra: passo 1 valor, passo 2 confere e confirma, passo 3 resultado
  let BUY = null;
  function closeBuy() { clearPass(); if (BUY && BUY.timer) clearInterval(BUY.timer); BUY = null; $("buyM").hidden = true; $("buyMB").innerHTML = ""; }
  function openBuy(key) {
    const m = M().find((x) => x.cmc === key); if (!m || !(m.comprar || []).length) return;
    BUY = { key, m };
    $("buyMT").textContent = "Comprar " + (m.simbolo || m.nome);
    $("buyMS").innerHTML = esc(m.nome) + " · preço na CoinGecko: " + price(m.preco);
    $("buyMB").innerHTML = '<div class="buyform">' + '<div><label for="buyRede">Blockchain</label><select class="in" id="buyRede">' + m.comprar.map((k) => '<option value="' + esc(k) + '">' + esc(REDE[k] || k) + "</option>").join("") + "</select></div>" +
      '<div><label for="buyVal" id="buyValL">Quanto gastar</label><input class="in" id="buyVal" type="number" step="any" min="0" inputmode="decimal" placeholder="valor na moeda da rede"></div>' +
      '<div class="row dmact"><button class="btn primary" type="button" id="buyQuote">Ver cotação</button><span class="muted small">só mostra; nada é enviado neste passo</span></div></div><div id="buyPrev"></div>';
    buyUnit(); $("buyM").hidden = false; setTimeout(() => $("buyVal").focus(), 50);
  }
  const buyUnit = () => { const k = $("buyRede").value; $("buyValL").textContent = "Quanto gastar, em " + (MOEDA[k] || "moeda da rede"); $("buyVal").placeholder = "valor em " + (MOEDA[k] || "moeda da rede"); };
  async function buyQuote() {
    if (!BUY) return;
    const valor = $("buyVal").value;
    if (!(Number(valor) > 0)) { $("buyPrev").innerHTML = '<div class="buybad">Digite quanto quer gastar.</div>'; return; }
    if (BUY.timer) clearInterval(BUY.timer);
    $("buyPrev").innerHTML = '<div class="muted" style="margin-top:10px">cotando e conferindo o token…</div>';
    const r = await BB.api("/api/dormant/compra/cotar", { body: { key: BUY.key, rede: $("buyRede").value, valor } });
    if (!BUY) return;
    if (!r || r.error) { $("buyPrev").innerHTML = '<div class="buybad">' + esc((r && r.error) || "não consegui cotar") + "</div>"; return; }
    BUY.q = r;
    const q = (v) => (v == null ? "—" : num(v, v >= 1000 ? 0 : v >= 1 ? 4 : 8));
    const line = (a, b) => "<tr><td>" + a + "</td><td>" + b + "</td></tr>";
    const list = (cl, tt, L) => (L.length ? '<div class="' + cl + '"><b>' + esc(tt) + "</b><ul>" + L.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul></div>" : "");
    let h = '<div class="tbl-wrap" style="margin-top:12px"><table class="systbl nocard"><tbody>' +
      line("Você paga", "<b>" + num(r.valor, 8) + " " + esc(r.moeda_rede) + "</b>" + (r.usd != null ? " (US$ " + num(r.usd, 2) + ")" : "")) +
      line("Recebe, mais ou menos", "<b>" + q(r.recebe) + " " + esc(r.moeda.simbolo) + "</b>") +
      line("Recebe no mínimo", q(r.minimo) + " " + esc(r.moeda.simbolo) + " (folga de " + num(r.slip, 2) + "%)") +
      line("Onde", esc(r.dex || "—") + (r.rota ? " · " + esc(r.rota) : "")) +
      line("Preço pago × CoinGecko", r.dif_cg == null ? "—" : pc(r.dif_cg)) +
      line("Quanto a compra move o preço", r.impacto == null ? "—" : num(r.impacto, 2) + "%") +
      line("Gás / taxa da rede, perto de", r.gas_usd == null ? "—" : "US$ " + num(r.gas_usd, 4)) +
      line("Carteira", r.carteira ? '<span class="cmaddr">' + esc(r.carteira) + "</span>" : "—") +
      line("Contrato do token", '<span class="cmaddr">' + esc(r.token) + "</span>") + "</tbody></table></div>" +
      list("buybad", "Não dá para comprar:", r.bloqueia || []) + list("buywarn", "Atenção:", r.avisos || []);
    if (r.quote_id) {
      h += '<div class="buyform"><div><label for="buySenha">Senha de compra</label><input class="in" id="buySenha" type="password" autocomplete="off" spellcheck="false"></div>' +
        '<div><label for="buyOk">Digite COMPRAR para confirmar</label><input class="in" id="buyOk" type="text" autocomplete="off" spellcheck="false" autocapitalize="characters"></div>' +
        '<div class="row dmact"><button class="btn primary" type="button" id="buyGo">Comprar agora</button><span class="muted small" id="buyTime"></span></div></div>';
    }
    $("buyPrev").innerHTML = h;
    if (r.quote_id) {
      const fim = Date.now() + r.validade_s * 1000;
      const tick = () => { const s = Math.round((fim - Date.now()) / 1000), el = $("buyTime"), go = $("buyGo"); if (!el || !go) return;
        if (s <= 0) { go.disabled = true; el.textContent = "esta cotação venceu: clique em Ver cotação de novo"; clearInterval(BUY.timer); } else el.textContent = "cotação vale por mais " + s + " s"; };
      tick(); BUY.timer = setInterval(tick, 1000);
    }
  }
  async function buyGo(btn) {
    if (!BUY || !BUY.q || !BUY.q.quote_id) return;
    const senha = $("buySenha").value, confirmar = $("buyOk").value.trim();
    btn.disabled = true; btn.textContent = "Enviando…";
    const r = await BB.api("/api/dormant/compra/confirmar", { body: { quote_id: BUY.q.quote_id, senha, confirmar } });
    if (!BUY) return;
    btn.disabled = false; btn.textContent = "Comprar agora";
    $("buySenha").value = "";
    if (!r || r.error) {
      const old = $("buyErr"); if (old) old.remove();
      btn.closest(".buyform").insertAdjacentHTML("beforebegin", '<div class="buybad" id="buyErr">' + esc((r && r.error) || "a compra não saiu") + "</div>");
      return;
    }
    if (BUY.timer) clearInterval(BUY.timer);
    const c = r.compra || {};
    const link = c.tx && c.expl ? '<a href="' + esc(c.expl + c.tx) + '" target="_blank" rel="noopener">ver a transação na blockchain</a>' : "";
    $("buyPrev").innerHTML = (c.status === "confirmada" ? '<div class="buyok"><b>Comprado.</b> ' + num(c.qty, 6) + " " + esc(c.simbolo) + " por US$ " + num(c.usd_in, 2) + ". " + link + "</div>"
      : '<div class="buywarn"><b>' + esc(c.status === "pendente" ? "Enviada, ainda sem confirmação." : "Confira esta compra.") + "</b> " + esc(c.motivo || "") + " " + link + "</div>") +
      '<div class="row dmact" style="margin-top:10px"><a class="btn primary" href="#compras" id="buyHist">Ver em Minhas compras</a></div>';
  }
  async function drawCompras() {
    const r = await BB.api("/api/dormant/compras", { quiet: true });
    if (VIEW !== "compras") return;
    if (!r || r.error) { $("cpT").innerHTML = '<tr><td class="empty down">' + esc((r && r.error) || "não consegui ler as compras") + "</td></tr>"; return; }
    const s = r.resumo, kp = (k, v, d) => '<div class="kpi"><div class="k"><span>' + esc(k) + '</span></div><div class="v">' + v + '</div><div class="d">' + esc(d) + "</div></div>";
    $("cpK").innerHTML = kp("Investido", "US$ " + num(s.investido, 2), "o que saiu da carteira, com gás") + kp("Valor agora", "US$ " + num(s.valor, 2), "no preço da CoinGecko") +
      kp("Ganho total", '<span class="' + cls(s.ganho) + '">US$ ' + num(s.ganho, 2) + "</span>", "valor agora − investido") + kp("Total", pc(s.total), "desde as compras") +
      kp("1 h", pc(s.h1), "última hora") + kp("12 h", pc(s.h12), "últimas 12 horas") + kp("24 h", pc(s.h24), "últimas 24 horas") + kp("7 dias", pc(s.h168), "últimos 7 dias");
    $("cpSub").textContent = "as porcentagens são do preço de cada moeda; quem foi comprada dentro do período conta desde a compra · preço da CoinGecko" + (r.leitura_t ? ", lido há " + ago(r.leitura_t) : "") +
      " · não desconta a taxa de uma venda futura · para vender, use a sua carteira (o painel ainda não vende)";
    const ok = r.itens.filter((x) => x.status === "confirmada"), fora = r.itens.filter((x) => x.status !== "confirmada");
    const tx = (x) => (x.tx && x.expl ? '<a href="' + esc(x.expl + x.tx) + '" target="_blank" rel="noopener">ver</a>' : "—");
    const moeda = (x) => '<div class="dmcoin">' + (x.img ? '<img src="' + esc(x.img) + '" alt="" loading="lazy">' : "") + "<div><b>" + esc(x.nome) + "</b> <small>" + esc(x.simbolo || "") + "</small></div></div>";
    table("cpT", ["Moeda", "Rede", "Quando", "Investido", "Quantidade", "Preço pago", "Agora", "1 h", "12 h", "24 h", "7 dias", "Total", "Ganho", "Transação"], ok.map((x) => [V(moeda(x), x.nome), V(chainTag(x.rede_nome), x.rede_nome || ""),
      V(hora(x.t), x.t), V("US$ " + num(x.custo, 2) + '<span class="dmwhy">' + num(x.nativo, 6) + " " + esc(x.moeda) + "</span>", x.custo), V(num(x.qty, 4), x.qty), V(price(x.px_in), x.px_in), V(price(x.px_agora), x.px_agora),
      V(pc(x.h1), x.h1), V(pc(x.h12), x.h12), V(pc(x.h24), x.h24), V(pc(x.h168), x.h168), V(pc(x.total), x.total), V(x.ganho == null ? "—" : '<span class="' + cls(x.ganho) + '">US$ ' + num(x.ganho, 2) + "</span>", x.ganho), tx(x)]),
      "Nenhuma compra ainda. Em Moedas, use o botão Comprar.");
    const ST_C = { enviando: "enviando", pendente: "sem confirmação", falhou: "falhou", expirada: "não entrou", confira: "confira" };
    table("cpF", ["Quando", "Moeda", "Rede", "Valor", "Situação", "Motivo", "Transação"], fora.map((x) => [V(hora(x.t), x.t), V(moeda(x), x.nome), V(chainTag(x.rede_nome), x.rede_nome || ""), V("US$ " + num(x.usd_in, 2), x.usd_in),
      V('<span class="dmst ' + (x.status === "falhou" || x.status === "expirada" ? "dump" : "acordando") + '">' + esc(ST_C[x.status] || x.status) + "</span>", x.status), '<small class="muted">' + esc(x.motivo || "") + "</small>", tx(x)]), "Nada aqui.");
  }
  function draw() {
    drawSys();
    if (VIEW === "visao") drawVisao();
    if (VIEW === "moedas") drawMoedas();
    if (VIEW === "grupos") drawGrupos();
    if (VIEW === "config") drawConfig();
    if (VIEW === "compras") drawCompras();
  }

  async function load() {
    if (!READY || BUSY || document.hidden) return;
    BUSY = true;
    try {
      const r = await BB.api("/api/dormant", { quiet: true });
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
    if (VIEW === "carteiras") loadWal();     // só ao abrir: redesenhar sozinho apagaria uma chave que está sendo colada
    draw();
    load();
  }
  const openDrawer = () => { $("side").classList.add("open"); $("scrim").classList.add("open"); };
  const closeDrawer = () => { $("side").classList.remove("open"); $("scrim").classList.remove("open"); };

  // ------------------------------------------------------------------ ações
  document.addEventListener("input", (e) => {
    if (e.target && e.target.closest && e.target.closest("#rCfg")) DIRTY = true;
    if (e.target && e.target.id === "mQ") { F.q = e.target.value; saveF(); drawMoedas(); }
  });
  document.addEventListener("change", (e) => {
    if (!e.target) return;
    if (e.target.id === "mSort") { F.sort = e.target.value; saveF(); drawMoedas(); }
    if (e.target.id === "mCat") { F.cat = e.target.value; saveF(); drawMoedas(); }
    if (e.target.id === "buyRede") { buyUnit(); $("buyPrev").innerHTML = ""; if (BUY && BUY.timer) clearInterval(BUY.timer); }
  });
  // 0.32.228 (pedido do dono): adicionar moeda pela busca da CoinGecko; fica o nome de quem adicionou
  function addOpen() { $("addM").hidden = false; $("addR").innerHTML = ""; $("addQ").value = ""; setTimeout(() => $("addQ").focus(), 50); }
  async function addSearch() {
    const q = $("addQ").value.trim(); if (!q) return;
    $("addR").innerHTML = '<span class="muted">buscando…</span>';
    const r = await BB.api("/api/dormant/buscar?q=" + encodeURIComponent(q), { quiet: true });
    if (r && r.error) { $("addR").innerHTML = '<span class="down">' + esc(r.error) + "</span>"; return; }
    const L = (r && r.itens) || [];
    $("addR").innerHTML = L.length ? L.map((x) => '<div class="r">' + (x.img ? '<img src="' + esc(x.img) + '" alt="" width="22" height="22" style="border-radius:50%">' : "") +
      "<div><b>" + esc(x.nome) + "</b> <small class=\"muted\">" + esc(x.simbolo) + '</small><div class="dmcats">' + (x.blockchains || []).map((b) => chainTag(b)).join(" ") + "</div></div>" +
      '<span class="sp"></span><small class="muted">' + price(x.preco) + " · " + usd(x.mcap) + "</small>" +
      (x.ja_tem ? '<span class="tag neutral">já está na lista</span>' : '<button class="btn sm primary" data-dmaddid="' + esc(x.id) + '">Adicionar</button>') + "</div>").join("")
      : '<span class="muted">Nada encontrado. Tente o símbolo (ex.: PEPE) ou cole o link da moeda na CoinGecko.</span>';
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target && e.target.id === "addQ") { e.preventDefault(); addSearch(); } });
  document.addEventListener("click", async (e) => {
    const bb = e.target.closest && e.target.closest("[data-dmbuy]");
    if (bb) { e.preventDefault(); e.stopPropagation(); openBuy(bb.dataset.dmbuy); return; }
    const k = e.target.closest && e.target.closest("[data-dmst]");
    if (k) { F.st = k.dataset.dmst; saveF(); location.hash = "#moedas"; return; }
    const th = e.target.closest && e.target.closest("th[data-tsi]");
    if (th) { const tbl = th.closest("table"), i = +th.dataset.tsi, s = TS[tbl.id];
      TS[tbl.id] = s && s.i === i ? { i, asc: !s.asc } : { i, asc: false }; tsApply(tbl.id); return; }
    const cc = e.target.closest && e.target.closest("[data-dmcoin]");
    if (cc && !e.target.closest("a")) { e.preventDefault(); openCoin(cc.dataset.dmcoin); return; }
    const g = e.target.closest && e.target.closest("tr[data-dmch],tr[data-dmcat]");
    if (g) { F.st = ""; F.ch = g.dataset.dmch || ""; F.cat = g.dataset.dmcat || ""; saveF(); location.hash = "#moedas"; return; }
    const t = e.target.closest ? e.target.closest("button,a") : null; if (!t) return;
    if (t.dataset.dmf != null) { F.st = t.dataset.dmf; saveF(); drawMoedas(); return; }
    if (t.dataset.dmchf != null) { F.ch = F.ch === t.dataset.dmchf ? "" : t.dataset.dmchf; saveF(); drawMoedas(); return; }
    if (t.dataset.dmsort) { const key = t.dataset.dmsort; F.sort = F.sort === key ? "-" + key : key; saveF(); drawMoedas(); return; }
    if (t.dataset.dmadd) { addOpen(); return; }
    if (t.id === "addMX") { $("addM").hidden = true; return; }
    if (t.id === "buyMX") { closeBuy(); return; }
    if (t.id === "buyQuote") { buyQuote(); return; }
    if (t.id === "buyGo") { buyGo(t); return; }
    if (t.id === "buyHist") { closeBuy(); $("coinM").hidden = true; CM = null; return; }
    if (t.id === "askMX") { closeAsk(); return; }
    if (t.id === "askGo") { if (ASK) await ASK(t); return; }
    if (t.dataset.wsave) {
      const rede = t.dataset.wsave, f = $("wk_" + rede), senha = $("wPass").value, e2 = $("we_" + rede);
      if (!f.value.trim()) { alert("Cole a chave privada."); return; }
      if (!WAL.tem_senha && senha !== $("wPass2").value) { alert("As duas senhas estão diferentes."); return; }
      t.disabled = true;
      const r = await BB.api("/api/dormant/carteiras/salvar", { body: { rede, chave: f.value, senha, todas_evm: !!(e2 && e2.checked) } });
      t.disabled = false; f.value = "";
      if (r && r.error) { alert(r.error); return; }
      clearPass(); await loadWal(); return;
    }
    if (t.dataset.wdel) {
      if (!confirm("Remover a chave desta carteira do sistema? O dinheiro continua na blockchain; a chave só precisa estar guardada com você.")) return;
      const r = await BB.api("/api/dormant/carteiras/remover", { body: { rede: t.dataset.wdel } });
      if (r && r.error) { alert(r.error); return; }
      await loadWal(); return;
    }
    if (t.id === "wOn") {
      if (!WAL) return;
      if (WAL.cfg.on) { const r = await BB.api("/api/dormant/compra/ligar", { body: { on: false } }); if (r && r.error) alert(r.error); await loadWal(); return; }
      ask("Ligar as compras", askPass("Senha de compra") + '<div><label for="askOk">Digite LIGAR para confirmar</label><input class="in" id="askOk" type="text" autocomplete="off" spellcheck="false"></div><div class="row dmact"><button class="btn primary" type="button" id="askGo">Ligar</button></div></div>', async (b) => {
        b.disabled = true;
        const r = await BB.api("/api/dormant/compra/ligar", { body: { on: true, senha: $("askSenha").value, confirmar: $("askOk").value.trim() } });
        b.disabled = false; $("askSenha").value = "";
        if (r && r.error) { alert(r.error); return; }
        closeAsk(); await loadWal();
      });
      return;
    }
    if (t.id === "wLimSave") {
      const body = { senha: $("wPass").value }; LIM.forEach((x) => { const el = $("wl_" + x[0]); if (el && el.value !== "") body[x[0]] = Number(el.value); });
      t.disabled = true; const r = await BB.api("/api/dormant/compra/limites", { body }); t.disabled = false;
      if (r && r.error) { alert(r.error); return; }
      clearPass(); WAL.cfg = r.cfg; drawWal(); return;
    }
    if (t.id === "wPassGo") {
      if ($("wPassN").value !== $("wPassN2").value) { alert("As duas senhas novas estão diferentes."); return; }
      t.disabled = true; const r = await BB.api("/api/dormant/carteiras/senha", { body: { atual: $("wPass").value, nova: $("wPassN").value } }); t.disabled = false;
      if (r && r.error) { alert(r.error); return; }
      clearPass(); $("wPassCh").open = false; alert("Senha trocada em " + r.carteiras + " carteiras."); return;
    }
    if (t.id === "coinMX") { $("coinM").hidden = true; CM = null; return; }
    if (t.dataset.cmr) { if (CM) { CM.rng = +t.dataset.cmr; dexEmbed("cg"); drawCoinChart(); } return; }
    if (t.dataset.cms) { dexEmbed(t.dataset.cms); return; }
    if (t.id === "addGo") { addSearch(); return; }
    if (t.dataset.dmaddid) {
      t.disabled = true;
      const r = await BB.api("/api/dormant/adicionar", { body: { id: t.dataset.dmaddid } });
      if (r && r.error) { t.disabled = false; alert(r.error); return; }
      t.outerHTML = '<span class="tag win">adicionada</span>';
      await load(); return;
    }
    if (t.dataset.dmdel) {
      e.preventDefault();
      if (!confirm("Tirar esta moeda da lista do Dormant?")) return;
      const r = await BB.api("/api/dormant/remover", { body: { key: t.dataset.dmdel } });
      if (r && r.error) { alert(r.error); return; }
      await load(); return;
    }
    if (t.id === "sysBox") { $("sysM").hidden = false; drawSysModal(); return; }
    if (t.id === "sysMX") { $("sysM").hidden = true; return; }
    if (t.id === "kSave") {
      const v = $("kVal").value.trim(); if (!v) return;
      t.disabled = true; const r = await BB.api("/api/dormant/chave", { body: { value: v } }); t.disabled = false;
      if (r && r.error) { alert(r.error); return; }
      $("kVal").value = ""; await load(); return;
    }
    if (t.id === "kDel") {
      if (!confirm("Remover a chave da CoinGecko? O Dormant volta a usar a API pública.")) return;
      await BB.api("/api/dormant/chave/remover", { body: {} }); await load(); return;
    }
    if (t.id === "rReset") { const p = (R && R.padrao) || {}; RG.forEach((x) => { if ($("dm_" + x[0])) $("dm_" + x[0]).value = p[x[0]]; }); DIRTY = true; return; }
    if (t.id === "rSave") {
      const body = {}; RG.forEach((x) => { const el = $("dm_" + x[0]); if (el && el.value !== "") body[x[0]] = Number(el.value); });
      t.disabled = true; const r = await BB.api("/api/dormant/cfg", { body }); t.disabled = false;
      if (r && r.error) { alert(r.error); return; }
      DIRTY = false; t.textContent = "Salvo"; setTimeout(() => { t.textContent = "Salvar regras"; }, 2000);
      await load();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { $("sysM").hidden = true; $("addM").hidden = true; $("coinM").hidden = true; CM = null; closeBuy(); closeAsk(); }
    if ((e.key === "Enter" || e.key === " ") && e.target && e.target.dataset && e.target.dataset.dmst) { e.preventDefault(); e.target.click(); }
  });
  $("sysM").addEventListener("click", (e) => { if (e.target === $("sysM")) $("sysM").hidden = true; });
  $("addM").addEventListener("click", (e) => { if (e.target === $("addM")) $("addM").hidden = true; });
  $("buyM").addEventListener("click", (e) => { if (e.target === $("buyM")) closeBuy(); });
  $("askM").addEventListener("click", (e) => { if (e.target === $("askM")) closeAsk(); });
  $("coinM").addEventListener("click", (e) => { if (e.target === $("coinM")) { $("coinM").hidden = true; CM = null; } });

  async function boot() {
    $("boot").innerHTML = BB.loader("Carregando", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
    $("dmOut").addEventListener("click", BB.logout);
    $("burger").addEventListener("click", openDrawer);
    $("tbMenu").addEventListener("click", openDrawer);
    $("scrim").addEventListener("click", closeDrawer);
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão: volta ao início */ }
    if (!s) { location.href = "/"; return; }
    const me = await BB.api("/api/me", { quiet: true });
    if (me.error || me.role !== "admin" || me.view_by) { location.replace("/app"); return; }      // o Dormant é só do admin
    try { sessionStorage.setItem("pf_hub", "dormant"); } catch (e) { /* */ }
    $("ver").textContent = "versão " + String(me.version || "").split(" · ")[0];
    $("boot").hidden = true; $("shell").hidden = false;
    READY = true;
    route();
  }
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", load);
  boot();
  setInterval(load, 60000);
})();
