// 0.32.227 (pedido do dono, 05/11): Dormant, painel próprio (/dormant, rotas /api/dormant) isolado da pump.fun, da BNB e da
// Robinhood. Vigia a watchlist da CoinMarketCap do dono pela CoinGecko e diz o que está dormindo, acordando, num pump ou num
// dump. Só observa.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => BB.esc(s);
  const TITLES = { visao: ["Visão geral", "o que acordou, o que deu pump ou dump e o que está dormindo"], moedas: ["Moedas", "todas as moedas da lista com a situação de cada uma"],
    grupos: ["Por blockchain e categoria", "as moedas da lista divididas por rede e por categoria"],
    config: ["Lista e regras", "chave da CoinGecko, regras e as moedas da lista"] };
  const ST = { pump: "Pump", dump: "Dump", acordando: "Acordando", dormindo: "Dormindo", normal: "Normal", parada: "Parada", morta: "Morta", sem_cg: "Sem par" };
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
  const pc = (v) => (v == null ? "—" : Math.abs(v) < 0.05 ? "0%" : '<span class="' + cls(v) + '">' + (v > 0 ? "+" : "") + num(v, 1) + "%</span>");
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
  const hora = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
  function ago(t) {
    if (!t) return "—";
    const s = Math.max(0, Date.now() / 1000 - t);
    return s < 60 ? Math.round(s) + " s" : s < 3600 ? Math.round(s / 60) + " min" : s < 86400 ? (s / 3600).toFixed(1).replace(".", ",") + " h" : (s / 86400).toFixed(1).replace(".", ",") + " dias";
  }
  const tag = (st) => '<span class="dmst ' + esc(st || "normal") + '">' + esc(ST[st] || "—") + "</span>";
  function coin(m) {
    const cg = m.cg ? '<a href="https://www.coingecko.com/en/coins/' + esc(m.cg) + '" target="_blank" rel="noopener">CoinGecko</a>' : "";
    return '<div class="dmcoin">' + (m.img ? '<img src="' + esc(m.img) + '" alt="" loading="lazy">' : "") + "<div><b>" + esc(m.nome) + "</b> <small>" + esc(m.simbolo || "") +
      (m.rank ? " · #" + m.rank : "") + (m.chain_nome ? '<span class="dmch" title="' + esc((m.chains || []).join(", ")) + '">' + esc(m.chain_nome) + "</span>" : "") + "</small>" +
      '<div class="dmlinks">' + cg + (m.extra ? "" : '<a href="https://coinmarketcap.com/currencies/' + esc(m.cmc) + '/" target="_blank" rel="noopener">CoinMarketCap</a>') +
      (m.extra ? '<a href="#" data-dmdel="' + esc(m.cmc) + '">tirar da lista</a>' : "") + "</div>" +
      (m.extra ? '<span class="dmby">adicionada por <b>' + esc(m.add_por) + "</b> · " + hora(m.add_t) + "</span>" : "") +
      ((m.cats || []).length ? '<div class="dmcats">' + m.cats.slice(0, 3).map((c) => "<span>" + esc(c) + "</span>").join("") + "</div>" : "") + "</div></div>";
  }
  function spark(p) {
    if (!p || p.length < 2) return "—";
    const lo = Math.min(...p), hi = Math.max(...p), W = 120, H = 32, sp = hi - lo || 1;
    const pts = p.map((v, i) => (i * (W / (p.length - 1))).toFixed(1) + "," + (H - 2 - ((v - lo) / sp) * (H - 4)).toFixed(1)).join(" ");
    const c = p[p.length - 1] >= p[0] ? "#22c55e" : "#ef4444";
    return '<svg class="dmspark" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" aria-label="gráfico de 7 dias"><polyline fill="none" stroke="' + c + '" stroke-width="1.6" points="' + pts + '"/></svg>';
  }
  function table(id, head, rows, empty) {
    const el = $(id); if (!el) return;
    if (!rows.length) { el.innerHTML = '<tr><td class="empty" colspan="' + head.length + '">' + esc(empty || "Nada por aqui ainda.") + "</td></tr>"; return; }
    const lab = head.map((h) => esc(String(h).replace(/<[^>]*>/g, "")));
    el.innerHTML = "<thead><tr>" + head.map((h) => "<th>" + h + "</th>").join("") + "</tr></thead><tbody>" +
      rows.map((r) => "<tr>" + r.map((c, i) => '<td data-l="' + lab[i] + '">' + (c == null ? "" : c) + "</td>").join("") + "</tr>").join("") + "</tbody>";
  }

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
    table("ovAl", ["Quando", "Moeda", "Virou", "1 h", "24 h", "Por quê"], ((R && R.alertas) || []).slice(0, 50).map((a) => [hora(a.t),
      "<b>" + esc(a.nome || a.cmc) + "</b> <small class=\"muted\">" + esc(a.simbolo || "") + "</small>", tag(a.para) + ' <small class="muted">era ' + esc(ST[a.de] || a.de) + "</small>", pc(a.h1), pc(a.h24),
      '<small class="muted">' + esc((a.por || []).join(" · ")) + "</small>"]), "Nenhum alerta ainda. Eles aparecem quando uma moeda muda para pump, dump ou acordando.");
    const vivas = M().filter((m) => m.h24 != null && m.status !== "parada");
    const up = vivas.slice().sort((a, b) => b.h24 - a.h24).slice(0, 8), dn = vivas.slice().sort((a, b) => a.h24 - b.h24).slice(0, 8);
    table("ovMv", ["Moeda", "24 h", "7 dias", "Situação"], up.concat(dn).map((m) => [coin(m), pc(m.h24), pc(m.d7), tag(m.status)]), "A primeira leitura ainda não terminou.");
    const dorm = M().filter((m) => m.status === "dormindo").sort((a, b) => Math.abs(a.d30 || 0) - Math.abs(b.d30 || 0)).slice(0, 15);
    table("ovDm", ["Moeda", "Preço", "7 dias", "30 dias", "Volume 24 h", "Gráfico 7 dias", "Por quê"], dorm.map((m) => [coin(m), price(m.preco), pc(m.d7), pc(m.d30), usd(m.vol), spark(m.spark),
      '<small class="muted">' + esc((m.por || []).join(" · ")) + "</small>"]), "Nenhuma moeda dormindo agora.");
  }
  function drawMoedas() {
    const c = (R && R.contagem) || {};
    $("mFilt").innerHTML = '<button data-dmf=""' + (F.st ? "" : ' class="on"') + ">Todas · " + num(M().length, 0) + "</button>" +
      ST_ORD.filter((k) => c[k]).map((k) => '<button data-dmf="' + k + '"' + (F.st === k ? ' class="on"' : "") + ">" + esc(ST[k]) + " · " + num(c[k], 0) + "</button>").join("");
    if ($("mQ").value !== F.q && document.activeElement !== $("mQ")) $("mQ").value = F.q;
    $("mSort").value = F.sort;
    const q = F.q.trim().toLowerCase();
    const chs = {}, cats = {};
    M().forEach((m) => { if (m.chain_nome) chs[m.chain_nome] = (chs[m.chain_nome] || 0) + 1; (m.cats || []).forEach((c) => { cats[c] = (cats[c] || 0) + 1; }); });
    $("mChain").innerHTML = '<option value="">Todas as blockchains</option>' + Object.entries(chs).sort((a, b) => b[1] - a[1]).map((x) => '<option value="' + esc(x[0]) + '"' + (F.ch === x[0] ? " selected" : "") + ">" + esc(x[0]) + " · " + x[1] + "</option>").join("");
    $("mCat").innerHTML = '<option value="">Todas as categorias</option>' + Object.entries(cats).sort((a, b) => b[1] - a[1]).map((x) => '<option value="' + esc(x[0]) + '"' + (F.cat === x[0] ? " selected" : "") + ">" + esc(x[0]) + " · " + x[1] + "</option>").join("");
    let L = M().filter((m) => (!F.st || m.status === F.st) && (!F.ch || m.chain_nome === F.ch) && (!F.cat || (m.cats || []).includes(F.cat)) &&
      (!q || (m.nome + " " + m.simbolo + " " + m.cmc + " " + (m.chain_nome || "") + " " + (m.cats || []).join(" ")).toLowerCase().includes(q)));
    const k = F.sort.replace("-", ""), dir = F.sort.startsWith("-") ? 1 : -1;
    L = L.slice().sort((a, b) => k === "nome" ? String(a.nome).localeCompare(String(b.nome)) : ((a[k] == null) - (b[k] == null)) || dir * ((a[k] || 0) - (b[k] || 0)));
    table("mT", ["Moeda", "Situação", "Preço", "1 h", "24 h", "7 dias", "30 dias", "Volume 24 h", "Valor de mercado", "Gráfico 7 dias"], L.slice(0, 400).map((m) => [coin(m),
      tag(m.status) + (m.por && m.por.length ? '<span class="dmwhy">' + esc(m.por.join(" · ")) + "</span>" : ""), price(m.preco), pc(m.h1), pc(m.h24), pc(m.d7), pc(m.d30),
      usd(m.vol) + (m.vol_x ? '<span class="dmwhy">' + num(m.vol_x, 1) + "× o normal</span>" : ""), usd(m.mcap), spark(m.spark)]), "Nenhuma moeda com esse filtro.");
    $("mSub").textContent = num(L.length, 0) + " moedas" + (L.length > 400 ? " · mostrando as 400 primeiras" : "") + " · gráfico = últimos 7 dias (CoinGecko)";
  }
  function drawGrupos() {
    const g = (R && R.grupos) || {}, s = (R && R.status) || {};
    const row = (x, tipo) => ['<b>' + esc(x.nome) + "</b>", num(x.n, 0),
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
  function draw() {
    drawSys();
    if (VIEW === "visao") drawVisao();
    if (VIEW === "moedas") drawMoedas();
    if (VIEW === "grupos") drawGrupos();
    if (VIEW === "config") drawConfig();
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
    if (e.target.id === "mChain") { F.ch = e.target.value; saveF(); drawMoedas(); }
    if (e.target.id === "mCat") { F.cat = e.target.value; saveF(); drawMoedas(); }
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
      "<div><b>" + esc(x.nome) + "</b> <small class=\"muted\">" + esc(x.simbolo) + '</small><div class="dmcats">' + (x.blockchains || []).map((b) => "<span>" + esc(b) + "</span>").join("") + "</div></div>" +
      '<span class="sp"></span><small class="muted">' + price(x.preco) + " · " + usd(x.mcap) + "</small>" +
      (x.ja_tem ? '<span class="tag neutral">já está na lista</span>' : '<button class="btn sm primary" data-dmaddid="' + esc(x.id) + '">Adicionar</button>') + "</div>").join("")
      : '<span class="muted">Nada encontrado. Tente o símbolo (ex.: PEPE) ou cole o link da moeda na CoinGecko.</span>';
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target && e.target.id === "addQ") { e.preventDefault(); addSearch(); } });
  document.addEventListener("click", async (e) => {
    const k = e.target.closest && e.target.closest("[data-dmst]");
    if (k) { F.st = k.dataset.dmst; saveF(); location.hash = "#moedas"; return; }
    const g = e.target.closest && e.target.closest("tr[data-dmch],tr[data-dmcat]");
    if (g) { F.st = ""; F.ch = g.dataset.dmch || ""; F.cat = g.dataset.dmcat || ""; saveF(); location.hash = "#moedas"; return; }
    const t = e.target.closest ? e.target.closest("button,a") : null; if (!t) return;
    if (t.dataset.dmf != null) { F.st = t.dataset.dmf; saveF(); drawMoedas(); return; }
    if (t.dataset.dmadd) { addOpen(); return; }
    if (t.id === "addMX") { $("addM").hidden = true; return; }
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
    if (e.key === "Escape") { $("sysM").hidden = true; $("addM").hidden = true; }
    if ((e.key === "Enter" || e.key === " ") && e.target && e.target.dataset && e.target.dataset.dmst) { e.preventDefault(); e.target.click(); }
  });
  $("sysM").addEventListener("click", (e) => { if (e.target === $("sysM")) $("sysM").hidden = true; });
  $("addM").addEventListener("click", (e) => { if (e.target === $("addM")) $("addM").hidden = true; });

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
