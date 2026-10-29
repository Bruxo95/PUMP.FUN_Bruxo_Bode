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
  // 0.32.51 (pedido do dono): preço pequeno com os zeros contados, como na pump.fun/DexScreener — 0,0₆3831 = 0,0000003831
  const ex = (n) => { n = Number(n); if (!n || !isFinite(n)) return "–";
    if (n >= 0.001) return n.toLocaleString("pt-BR", { maximumSignificantDigits: 4 });
    const z = -Math.floor(Math.log10(n)) - 1, d = Math.min(9999, Math.round(n * Math.pow(10, z + 4))).toString().replace(/0+$/, "");
    return '<span class="px" title="' + n.toExponential(3) + '">0,0<sub>' + z + "</sub>" + d + "</span>"; };
  const hms = (s) => { if (s == null) return "–"; s = Math.max(0, Math.round(s)); if (s < 60) return s + " s"; if (s < 3600) return Math.floor(s / 60) + " min " + String(s % 60).padStart(2, "0") + " s"; if (s < 86400) return Math.floor(s / 3600) + " h " + String(Math.floor((s % 3600) / 60)).padStart(2, "0") + " min"; const d = Math.floor(s / 86400); return d + (d === 1 ? " dia " : " dias ") + Math.floor((s % 86400) / 3600) + " h"; };
  const agoT = (t) => hms(Date.now() / 1000 - t);
  const agoIso = (x) => (x ? hms((Date.now() - new Date(x)) / 1000) : "–");
  const dt = (x) => { if (!x) return "–"; const d = new Date(x); return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) + " " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
  // 0.31.73 (pedido do dono): "manual" não é carteira — é o marcador das compras que não vieram de um trader (automáticas
  // do Explorar/Base/Maiores traders, botão Comprar, cópia de outra conta). Mostra de onde veio, sem link quebrado.
  const ORIG_NOME = { bruxo: "Aba do Bruxo (automática, só fictícia)", calls: "Calls quentes (automática)", explorar: "Explorar (automática)", base: "Base (automática)", elite: "Maiores traders (automática)", barrado: "Barrado que subiu (automática, só fictícia)", barrado_btn: "Barrado que subiu (você comprou)" };
  // legenda ao passar o mouse (pedido do dono: "explicar o que é Explorar")
  const ORIG_DESC = { "Barrado que subiu (automática, só fictícia)": "o robô comprou sozinho, só na fictícia, um token que o filtro do Explorar barrou mas que subiu depois", "Barrado que subiu (você comprou)": "você clicou em Comprar num token da lista Barrado que subiu, no Explorar", "Explorar (automática)": "o robô comprou sozinho um token da lista Quase graduando do Explorar: veredito chance alta e passou em todos os seus filtros e proteções",
    "Base (automática)": "compra automática da tela Base da pump.fun (ex.: token com Boost ON)",
    "Maiores traders (automática)": "compra feita quando vários dos maiores traders entraram no mesmo token",
    "botão Comprar (você)": "você clicou em Comprar", "compra automática": "compra feita pelo robô, sem copiar um trader" };
  const whoLabel = (x) => { x = x || {}; const fo = x.follow_of; if (fo) return "copiou a conta " + (fo.nome || "outra conta");
    if (ORIG_NOME[x.origem]) return ORIG_NOME[x.origem]; if ((x.auto && x.auto !== true) || x.short === "automático") return "compra automática"; return x.manual || x.wallet === "manual" ? "botão Comprar (você)" : "compra automática"; };
  const shortW = (w, x) => (w === "manual" ? whoLabel(x || { wallet: w }) : w ? w.slice(0, 4) + "…" + w.slice(-4) : "");
  // 0.32.41 (pedido do dono): etiqueta da ABA de onde veio cada trade/posição (o servidor manda o campo "aba")
  const abaTag = (x) => (x && x.aba ? '<span class="tag aba" title="aba do painel que fez esta operação">' + esc(x.aba) + "</span> " : "");
  const pfW = (w, x) => abaTag(x) + pfW0(w, x);
  const pfW0 = (w, x) => w === "manual" ? '<span class="tag ' + (String((x || {}).origem || "").startsWith("barrado") ? "barr" : "neutral") + '" title="' + esc(ORIG_DESC[whoLabel(x || { wallet: w })] || "veio da cópia de trades de outra conta") + '">' + esc(whoLabel(x || { wallet: w })) + "</span>"
    // 0.32.9: o perfil da pump.fun só existe para quem já usou o site ("page not found" para as outras); o link principal
    // vai para o Solscan, que abre qualquer carteira, e o "pf" abre o perfil da pump.fun quando existir
    : '<a href="https://solscan.io/account/' + encodeURIComponent(w) + '" target="_blank" rel="noopener" title="' + esc(w) + ' · abrir no Solscan">' + esc(shortW(w)) + "</a>" +
      ' <a class="pflink" href="https://pump.fun/profile/' + encodeURIComponent(w) + '" target="_blank" rel="noopener" title="Perfil na pump.fun (só existe se a carteira já usou o site)">pf</a>';
  // 0.32.9 (pedido do dono): idade, saldo, transações e tokens criados de uma carteira
  const factsCells = (fx) => { fx = fx || {};
    // carteira com mais de 4.000 transações: só deu para ver as mais novas, então a idade é "pelo menos"
    const age = fx.age_days == null ? "–" : fx.age_more ? '<span title="mais de 4.000 transações: a idade real é maior que isto">muito ativa · ≥ ' + (fx.age_days < 1 ? "horas" : f(fx.age_days, 0) + " dias") + "</span>"
      : fx.age_days < 1 ? "< 1 dia" : f(fx.age_days, 0) + " dias";
    return [fx.lido ? age : '<span class="muted" title="lendo na blockchain (algumas por minuto)">lendo…</span>', fx.usd == null ? "–" : "$" + f(fx.usd, 0),
      fx.txs == null ? "–" : f(fx.txs, 0) + (fx.age_more ? "+" : ""), fx.criados == null ? "–" : String(fx.criados) + (fx.rugs ? ' <span class="down" title="tokens dela que despencaram">(' + fx.rugs + " rug)</span>" : "")]; };
  // 0.32.12: nota geral 0–100 (acerto com poucos tokens pesa menos + quanto do dinheiro foi ganho) e a janela "Ver tudo"
  let SA_LOG = [], BUY_MINT = "", BUY_ORIG = "", POS_DET = null, POS_ID = null, STC_W = "", STAI_ID = "";
  // 0.32.48 (pedido do dono): histórico dos relatórios para o ChatGPT e o estado de cada um
  const SAI_TAG = { gerado: "neutral", esperando: "pause", resposta: "pause", analisado: "win" };
  async function loadStudyAi() {
    if (!$("saiT")) return;
    const r = await BB.api("/api/pump/study/ai/reports"); if (r.error) { $("saiSub").textContent = r.error; return; }
    const nv = r.novas || [];
    $("saiNew").innerHTML = nv.length ? '<div class="decbox"><b>' + nv.length + " carteira(s) nova(s) sem relatório.</b> O próximo sai sozinho com " + r.auto_min +
      ' (ou depois de 24 h). <button class="btn sm primary" id="saiNewGo">Gerar agora com as novas</button></div>' : '<p class="muted small">Todas as carteiras do estudo já estão em algum relatório.</p>';
    table("saiT", ["Gerado", "Carteiras", "Como", "Estado", ""], (r.items || []).map((x) => [dt(x.em), String(x.carteiras.length) + "<small>" + x.carteiras.slice(0, 3).map((w) => w.slice(0, 4) + "…" + w.slice(-4)).join(", ") + (x.carteiras.length > 3 ? "…" : "") + "</small>",
      x.auto ? "automático" : "você gerou", '<span class="tag ' + (SAI_TAG[x.status] || "neutral") + '">' + esc(x.status_txt) + "</span>" + (x.resposta_em ? "<small>resposta em " + dt(x.resposta_em) + "</small>" : x.copiado_em ? "<small>copiado em " + dt(x.copiado_em) + "</small>" : ""),
      '<button class="btn sm" data-saio="' + esc(x.id) + '">Abrir</button>']), "Nenhum relatório ainda.");
  }
  // 0.32.53: a resposta do ChatGPT também pode vir de um arquivo (.md/.txt), lido aqui no navegador
  document.addEventListener("change", async (ev) => { if (ev.target.id !== "staiF") return; const fl = ev.target.files && ev.target.files[0]; if (!fl) return;
    if (fl.size > 4 * 1024 * 1024) { toast("Arquivo grande demais (máx. 4 MB)."); return; }
    $("staiR").value = await fl.text(); $("staiRM").textContent = "Arquivo " + fl.name + " carregado · clique em Salvar resposta"; ev.target.value = ""; });
  async function openStudyAi(id) {
    const r = await BB.api("/api/pump/study/ai/reports/" + encodeURIComponent(id)); if (r.error) { toast(r.error); return; }
    STAI_ID = r.id; $("staiT").value = r.texto || ""; $("staiR").value = r.resposta || ""; $("staiRM").textContent = "";
    $("staiMT").textContent = "Relatório " + r.id + " · " + (r.carteiras || []).length + " carteira(s)"; $("staiMS").textContent = r.status_txt;
    $("staiAn").hidden = !r.analise; $("staiAnT").textContent = r.analise || ""; $("staiM").hidden = false; loadStudyAi();
  }
  function openPosDet(id, refresh) {
    const P = POS_DET && POS_DET.list.find((p) => String(p.id) === String(id));
    if (!P) { if (!refresh) toast("Essa posição já fechou."); $("posM").hidden = true; POS_ID = null; return; }
    POS_ID = id;
    const p = P, row = (k, v) => "<tr><td><b>" + k + "</b></td><td>" + v + "</td></tr>";
    $("posMT").innerHTML = (p.real ? '<span class="tag real">REAL</span> ' : '<span class="tag sim">FICTÍCIA</span> ') + esc(p.symbol || "") ;
    $("posMS").textContent = "aberta " + dt(p.opened_at) + " · origem: " + whoLabel(p);
    $("posMB").innerHTML = '<div class="kpis" style="margin:4px 0 12px">' +
      [["Ganho agora", p.pnl_now_sol == null ? "–" : sg(p.pnl_now_sol), p.pnl_now_pct == null ? "" : f(p.pnl_now_pct, 1) + "% do investido (já vendido + valor de agora, com taxas)"],
       ["Investido", s4(p.sol_in) + " SOL", ""], ["Vale agora", p.value_sol == null ? "–" : s4(p.value_sol) + " SOL", "o que ainda segura, se vendesse agora"],
       ["Já vendido", s4(p.proceeds || 0) + " SOL", (p.sells || []).length + " venda(s) parcial(is)"]]
        .map(([l, v, s]) => '<div class="kpi"><div class="l">' + l + '</div><div class="v">' + v + '</div><div class="s">' + esc(s) + "</div></div>").join("") + "</div>" +
      '<div class="tbl-wrap"><table class="systbl"><tbody>' +
      row("Token", pfM(p.mint, p.symbol) + (p.venue_in ? " · " + esc(p.venue_in) : "") + (p.mcap_in ? " · mcap na entrada " + f(p.mcap_in, 0) + " SOL" : "") + (p.mcap_now ? " · agora " + f(p.mcap_now, 0) + " SOL" : "")) +
      row("Origem", pfW(p.wallet, p)) +
      row("Por que entrou", esc(p.entrou_porque || (p.auto && p.auto !== true ? p.auto : "–"))) +
      row("Preço de entrada", ex(p.price_in) + (p.trader_price ? " · trader " + ex(p.trader_price) : "") + (p.lag_s != null ? " · atraso " + f(p.lag_s, 1) + " s" : "")) +
      row("Preço agora", ex(p.price_now || p.price_in) + (p.price_at ? " · há " + agoT(p.price_at) : "")) +
      row("Variação (o que segura)", pc(p.chg_pct) + (p.best_pct != null ? " · melhor " + pc(p.best_pct) : "") + (p.worst_pct != null ? " · pior " + pc(p.worst_pct) : "")) +
      row("Taxas pagas", p.fees_sol == null ? "–" : s4(p.fees_sol) + " SOL") +
      row("Nota da entrada", p.score == null ? "–" : f(p.score, 0) + " / 100") +
      row("Volume do token", POS_DET.vol(p)) +
      row("Vendas", POS_DET.soldCell(p)) +
      row("Stop móvel", p.trail_peak != null ? "ligado · pico " + pc(p.trail_peak) + " · sai em +" + f(p.trail_exit, 1) + "%" : "ainda não ligou") +
      row("Tempo de saída e regras desta posição", POS_DET.left(p)) +
      row("Antes da entrada (15 min)", p.antes ? "entrou a " + f(p.antes.pos_pct, 0) + "% da faixa (0% = fundo, 100% = topo) · tinha subido " + (p.antes.subiu_antes_pct == null ? "–" : pc(p.antes.subiu_antes_pct)) + " desde o mínimo" : "sem dado (o token não era acompanhado antes da compra)") +
      row("Fotos a cada 15 min", (p.snaps || []).length ? (p.snaps || []).map((x) => x.min + " min: " + (x.chg == null ? "–" : (x.chg > 0 ? "+" : "") + f(x.chg, 1) + "%") + (x.best != null ? " (pico " + f(x.best, 0) + "%)" : "")).join(" · ") : "a primeira foto sai com 15 min de posição") +
      "</tbody></table></div>";
    if ($("posM").hidden) { $("posM").hidden = false; $("posMX").focus(); }
  }
  // 0.32.26 (pedido do dono): ao lado de cada botão Comprar, diz se já tem a moeda na fictícia/real e leva até ela em Posições
  function markBought() {
    const pos = (D && D.positions) || [];
    document.querySelectorAll("[data-buy]").forEach((b) => {
      const m = b.dataset.buy, sim = pos.some((p) => p.mint === m && !p.real), real = pos.some((p) => p.mint === m && p.real);
      const key = (sim ? "s" : "") + (real ? "r" : "") + (pos.some((p) => p.mint === m && p.origem === "barrado") ? "a" : "");
      let tag = b.nextElementSibling && b.nextElementSibling.classList.contains("bought") ? b.nextElementSibling : null;
      if (!key) { if (tag) tag.remove(); return; }
      if (tag && tag.dataset.k === key) return;
      if (!tag) { tag = document.createElement("span"); tag.className = "bought"; b.after(tag); }
      tag.dataset.k = key;
      const auto = pos.some((p) => p.mint === m && !p.real && p.origem === "barrado");
      tag.innerHTML = (sim ? '<a href="#posicoes" class="tag ' + (auto ? "barr" : "sim") + '" data-gopos="' + esc(m) + '" data-gomode="sim" title="Ver esta moeda em Posições (fictícia)">' + (auto ? "✓ AUTO na FICTÍCIA ›" : "✓ na FICTÍCIA ›") + "</a>" : "") +
        (real ? ' <a href="#posicoes" class="tag real" data-gopos="' + esc(m) + '" data-gomode="real" title="Ver esta moeda em Posições (real)">✓ na REAL ›</a>' : "");
    });
  }
  setInterval(() => { try { markBought(); } catch (e) { /* nunca derruba o painel */ } }, 1500);
  const scoreTag = (d) => { if (!d || d.score == null) return "–";
    const c = d.score >= 70 ? "win" : d.score >= 45 ? "neutral" : "loss";
    return '<span class="tag ' + c + '" title="70% acerto (ajustado para poucos tokens) + 30% quanto do dinheiro foi ganho · base ' + d.score_base + ' tokens fechados">' + d.score + "</span>"; };
  // 0.32.14: "copiando" diz em qual carteira (só fictícia ou real + fictícia) e leva ao quadro "Seu resultado copiando"
  const copyState = (w) => { const y = D && (D.followed || []).find((z) => z.wallet === w); if (!y) return null;
    return y.ia_sim || !(D.real || {}).enabled || !((cfg() || {}).pump_real_mirror ?? true) ? "sim" : "both"; };
  const copyTag = (st) => '<a href="#estudo" class="tag win" data-gomine="1" title="Ir para Seu resultado copiando">' +
    (st === "both" ? "copiando · REAL e FICTÍCIA" : "copiando · só FICTÍCIA") + " ↓</a>";
  function openSaRate(valor) {
    // 0.32.16 (pedido do dono): carteiras julgadas que têm esta característica, com a nota
    const seen = new Set();
    const rows = SA_LOG.map((x, i) => [x, i]).filter(([x]) => (x.acao === "aprovou" || x.acao === "descartou") && (x.features || []).includes(valor) && !seen.has(x.wallet) && seen.add(x.wallet));
    $("saMT").textContent = valor;
    $("saMS").textContent = rows.filter(([x]) => x.acao === "aprovou").length + " aprovadas · " + rows.filter(([x]) => x.acao === "descartou").length + " descartadas · em ordem da nota · últimas 60 decisões";
    $("saMB").innerHTML = '<div class="tbl-wrap"><table id="saLT"></table></div>';
    table("saLT", ["Nota", "Carteira", "Decisão", "Resumo", "Por quê", ""], rows.map(([x, i]) => { const d = x.digest || {}, st = copyState(x.wallet);
      return [scoreTag(d), pfW(x.wallet, x), '<span class="tag ' + (x.acao === "aprovou" ? "win" : "loss") + '">' + esc(x.acao) + "</span>",
        x.digest ? (d.n_acertos || 0) + " acertos · " + (d.n_erros || 0) + " erros" + (d.pump_pct == null ? "" : " · " + d.pump_pct + "% pump.fun") : '<span class="muted">sem histórico</span>',
        '<span class="wrapcell">' + esc(x.motivo || "") + "</span>", '<span class="nowrap"><button class="btn sm" data-sadet="' + i + '">Ver tudo</button>' + (st ? " " + copyTag(st) : "") + "</span>"]; }),
      "Nenhuma carteira julgada com esta característica nas últimas 60 decisões.");
    $("saM").hidden = false; $("saMX").focus();
  }
  function openSaList(acao) {
    const NOME = { adicionou: "Adicionadas", aprovou: "Aprovadas", descartou: "Descartadas" }, seen = new Set();
    const rows = SA_LOG.map((x, i) => [x, i]).filter(([x]) => x.acao === acao && !seen.has(x.wallet) && seen.add(x.wallet));
    $("saMT").textContent = (NOME[acao] || acao) + " pela IA";
    $("saMS").textContent = rows.length + " carteiras · em ordem da nota · últimas 60 decisões";
    $("saMB").innerHTML = '<div class="tbl-wrap"><table id="saLT"></table></div>';
    table("saLT", ["Nota", "Carteira", "Resumo", "Quando", "Por quê", ""], rows.map(([x, i]) => { const d = x.digest || {}, st = copyState(x.wallet);
      return [scoreTag(d), pfW(x.wallet, x), x.digest ? (d.n_acertos || 0) + " acertos · " + (d.n_erros || 0) + " erros" + (d.pump_pct == null ? "" : " · " + d.pump_pct + "% pump.fun") : '<span class="muted">sem histórico</span>',
        dt(x.em), '<span class="wrapcell">' + esc(x.motivo || "") + "</span>", '<span class="nowrap"><button class="btn sm" data-sadet="' + i + '">Ver tudo</button>' + (st ? " " + copyTag(st) : "") + "</span>"]; }),
      "Nenhuma carteira nesta lista.");
    $("saM").hidden = false; $("saMX").focus();
  }
  function openSaDet(i) {
    const x = SA_LOG[i]; if (!x) return;
    const d = x.digest || {}, fx = x.facts || {}, [ok] = digestCells(x.digest), fc = factsCells(fx), u = d.unit === "SOL" ? " SOL" : "";
    const money = (v) => d.unit === "US$" ? "$" + f(v, 0) : s4(v) + " SOL";
    $("saMT").innerHTML = "Carteira " + pfW(x.wallet, x);
    $("saMS").textContent = x.acao + " em " + dt(x.em);
    $("saMB").innerHTML = '<div class="kpis" style="margin:4px 0 12px">' +
      [["Nota geral", d.score == null ? "–" : d.score + " / 100", d.score_base ? "base " + d.score_base + " tokens fechados" : "sem tokens fechados"],
       ["Acertos × erros", (d.n_acertos || 0) + " × " + (d.n_erros || 0), d.ganho != null ? "ganhou " + money(d.ganho) + " · perdeu " + money(d.perda) : ""],
       ["Na pump.fun", d.pump_pct == null ? "–" : d.pump_pct + "%", d.ops ? d.pump_ops + " de " + d.ops + " operações vistas" : ""],
       ["Última operação", d.ultima_op ? hms(Math.max(0, Date.now() / 1000 - d.ultima_op)) + " atrás" : "–", ""],
       ["Existe há", fc[0], ""], ["Saldo", fc[1], "SOL + USDC/USDT"], ["Transações", fc[2], ""], ["Tokens criados", fc[3], "os que a Base viu"]]
        .map(([l, v, s]) => '<div class="kpi"><div class="l">' + l + '</div><div class="v">' + v + '</div><div class="s">' + esc(s) + "</div></div>").join("") + "</div>" +
      '<div class="decbox ' + (x.acao === "aprovou" ? "ok" : x.acao === "descartou" ? "bad" : "") + '"><b>Por que ' + esc(x.acao) + ":</b> " + esc(x.motivo || "–") + "</div>" +
      '<div class="help"><p><b>Nota × decisão:</b> a nota mede a própria carteira (acertos, erros e quanto ganhou). A decisão da IA mede se <b>você copiando</b> teria ganho, já com o seu atraso, taxas e slippage. Por isso uma carteira com nota alta pode ser descartada: ela ganha, mas entra e sai rápido demais para quem copia chegar a tempo.</p>' +
      "<p>A nota junta o acerto (70%, ajustado para não dar nota alta com poucos tokens) e quanto do dinheiro movido foi ganho (30%). 70 ou mais = boa; abaixo de 45 = fraca.</p></div>" +
      (copyState(x.wallet) ? "<p>" + copyTag(copyState(x.wallet)) + "</p>" : "") +
      '<div class="tokcol">' + (ok || "") + "</div>" +
      (x.acao === "aprovou" && x.no_estudo ? '<p style="margin-top:12px"><button class="btn sm" data-stc="' + esc(x.wallet) + '">Copiar esta carteira</button></p>' : "");
    $("saM").hidden = false; $("saMX").focus();
  }
  const FACTS_H = ["Existe há", "Saldo (US$)", "Transações", "Tokens criados"];
  // 0.32.10 (pedido do dono): tokens que a carteira acertou/errou, com link, e quanto ela opera na pump.fun
  const tkLink = (x) => { const name = esc(x.symbol || (x.mint || "").slice(0, 6)), val = (x.realized > 0 ? "+" : "") + (x.unit === "US$" ? "$" + f(x.realized, 0) : s4(x.realized) + " SOL");
    const url = x.pump ? "https://pump.fun/coin/" + encodeURIComponent(x.mint) : "https://dexscreener.com/solana/" + encodeURIComponent(x.mint);
    return '<a href="' + url + '" target="_blank" rel="noopener" title="' + esc(x.mint) + (x.pump ? " · token da pump.fun" : " · fora da pump.fun") + '">' + name + "</a>" +
      (x.pump ? ' <span class="tag win mini">pump.fun</span>' : ' <span class="tag neutral mini">outra DEX</span>') + ' <span class="' + (x.realized >= 0 ? "up" : "down") + '">' + val + "</span>" +
      (x.sig ? ' <a href="https://solscan.io/tx/' + encodeURIComponent(x.sig) + '" target="_blank" rel="noopener" title="última transação dela neste token">tx</a>' : ""); };
  const digestCells = (d) => { if (!d) return ['<span class="muted">sem histórico ainda</span>', "–", "–"];
    const ok = (d.acertos || []).map(tkLink).join("<br>"), bad = (d.erros || []).map(tkLink).join("<br>");
    return ['<span class="wrapcell">' + (ok ? "<b>Acertou " + d.n_acertos + "</b><br>" + ok : "nenhum acerto visto") + (bad ? "<br><b>Errou " + d.n_erros + "</b><br>" + bad : "") + "</span>",
      d.pump_pct == null ? "–" : '<span title="' + d.pump_ops + " de " + d.ops + ' operações vistas em tokens da pump.fun">' + d.pump_pct + "% na pump.fun</span>" + (d.pump_pct < 50 ? '<br><small class="muted">opera mais fora</small>' : ""),
      d.ultima_op ? hms(Math.max(0, Date.now() / 1000 - d.ultima_op)) + " atrás" : "–"]; };
  const pfM = (m, s) => '<a href="https://pump.fun/coin/' + encodeURIComponent(m) + '" target="_blank" rel="noopener" title="' + esc(m) + '">' + esc(s || m.slice(0, 6)) + "</a>" +
    '<button class="tkinfo" data-tk="' + esc(m) + '" title="Ficha do token">i</button>';
  const tx = (sig) => (sig ? '<a href="https://solscan.io/tx/' + encodeURIComponent(sig) + '" target="_blank" rel="noopener">tx</a>' : "");
  const btn = (label, act, data, extra) => '<button class="btn sm ' + (extra || "") + '" data-act="' + act + '"' + Object.entries(data || {}).map(([k, v]) => " data-" + k + '="' + esc(v) + '"').join("") + ">" + label + "</button>";
  const st = (on, real) => '<span class="st ' + (on ? (real ? "real" : "on") : "off") + '">' + (on ? "ON" : "OFF") + "</span>";

  // 0.31.54 (pedido do dono: "os horários estão fora de ordem, deixe todos do mais novo para o mais velho"): toda tabela
  // com coluna de data/hora (Fechou, Entrou, Entrada, Quando, Hora, Dia…) sai ordenada do mais recente para o mais antigo
  const TCOL = /^(fechou|fechada|entrou|entrada|sa[ií]da|saiu|quando|hora|data|dia|abriu|aceita|desde|em)\b/i;
  function timeKey(html) {
    const s = String(html == null ? "" : html).replace(/<[^>]*>/g, " ");
    let m = s.match(/(\d{2})\/(\d{2})(?:\/(\d{4}))?,?\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
    const now = new Date();
    if (m) { let y = m[3] ? +m[3] : now.getFullYear(); if (!m[3] && +m[2] > now.getMonth() + 2) y--; return new Date(y, +m[2] - 1, +m[1], +m[4], +m[5], +(m[6] || 0)).getTime(); }
    m = s.match(/(\d{2})\/(\d{2})\/(\d{4})/);
    if (m) return new Date(+m[3], +m[2] - 1, +m[1]).getTime();
    m = s.match(/(\d{2})-(\d{2})-(\d{2})/);
    if (m && /^\s*\d{4}-/.test(s)) { const d = new Date(s.trim().slice(0, 10)); if (!isNaN(d)) return d.getTime(); }
    m = s.match(/\b(\d{2}):(\d{2})(?::(\d{2}))?\b/);
    if (m) return (+m[1]) * 3600 + (+m[2]) * 60 + (+(m[3] || 0));
    return null;
  }
  function byTimeDesc(head, rows) {
    const col = head.findIndex((h) => TCOL.test(String(h).replace(/<[^>]*>/g, "").trim()));
    if (col < 0 || rows.length < 2) return rows;
    const keys = rows.map((r) => timeKey(r[col]));
    if (keys.filter((k) => k != null).length < Math.ceil(rows.length / 2)) return rows;
    return rows.map((r, i) => [r, keys[i], i]).sort((a, b) => (b[1] == null ? -Infinity : b[1]) - (a[1] == null ? -Infinity : a[1]) || a[2] - b[2]).map((x) => x[0]);
  }
  // Indicador "Carregando" (grade animada + cronômetro). Só redesenha se o texto mudou, então a onda não reinicia.
  function busy(id, label) {
    const el = typeof id === "string" ? $(id) : id; if (!el) return;
    const cur = el.querySelector('.lattice-loader[data-status="working"]');
    if (cur && cur.dataset.lbl === label) return;
    el.innerHTML = BB.loader(label);
  }
  function table(id, head, rows, empty) {
    const el = $(id); if (!el) return;
    if (!rows.length) { el.innerHTML = '<tr><td class="empty" colspan="' + head.length + '">' + (empty || "Nada por aqui ainda.") + "</td></tr>"; return; }
    rows = byTimeDesc(head, rows);
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
  // convites de configuração (0.31.17): "usuário X quer compartilhar a configuração dele" no topo do painel
  // 0.31.31 (pedido do dono em 2026-10-27): cada quadro de opções diz se está usando a configuração de outro usuário,
  // conferindo AGORA cada valor (idêntica ou mudou depois), com "Ver o que mudou" (antes de aceitar → enviado → agora).
  let APPLIED = [];
  // 0.31.37 (pedido do dono em 2026-10-27): "você tem N usuários usando a sua configuração · ver usuários"
  // 0.31.40 (pedido do dono em 2026-10-27): no Explorar, a chance de fazer os mesmos trades da conta copiada e os
  // trades depois da cópia com o horário de cada um e a diferença
  let XC = { r: null, f: "comum" };
  async function loadExCopy() {
    const o = APPLIED.find((a) => Object.keys(a.valores || {}).some((k) => k.startsWith("pump_ex_auto_") || k.startsWith("pump_ar_")));
    if (!o || !$("exCopyCard")) { if ($("exCopyCard")) $("exCopyCard").hidden = true; return; }
    const mode = realMode(); XC.mode = mode;
    const r = await BB.api("/api/pump/compare/" + encodeURIComponent(o.id) + "?origem=explorar&real=" + (mode ? 1 : 0));
    if (r.error || mode !== realMode()) { if (r.error) $("exCopyCard").hidden = true; return; }
    XC.r = r; $("exCopyCard").hidden = false; renderExCopy();
  }
  const difT = (s) => s == null ? "–" : (s === 0 ? "mesmo segundo" : (s > 0 ? "você " : "você ") + hms(Math.abs(s)) + (s > 0 ? " depois" : " antes"));
  const hora = (iso) => iso ? new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–";
  function renderExCopy() {
    const r = XC.r; if (!r) return;
    const x = r.x, y = r.y, c = r.chance || {}, pct = (v) => v == null ? "–" : f(v, 0) + "%";
    $("exCopyT").textContent = "Configuração copiada de " + x.nome + ": você × " + x.nome + (r.real ? " · carteira REAL" : " · carteira fictícia");
    $("exCopyS").textContent = "desde " + dt(r.desde) + " · só compras automáticas do Explorar · " + (r.drift_y.length ? "a sua mudou em " + r.drift_y.length + " opção(ões) depois" : "a sua continua idêntica");
    const at = (r.comum || []).filter((m) => m.atraso_s != null).map((m) => m.atraso_s).sort((a, b) => a - b), med = at.length ? at[Math.floor(at.length / 2)] : null;
    kpis("exCopyK", [["Chance de fazer os mesmos trades", pct(c.de_x_que_y_fez), (c.em_comum || 0) + " de " + (c.tokens_x || 0) + " tokens de " + esc(x.nome) + " você também fez", "hit"],
      ["Você fez e " + esc(x.nome) + " também", pct(c.de_y_que_x_fez), (c.em_comum || 0) + " de " + (c.tokens_y || 0) + " dos seus", "tr"],
      [esc(x.nome) + " depois da cópia", sg(x.pnl_sol), x.trades + " trades · acerto " + (x.acerto == null ? "–" : f(x.acerto * 100, 0) + "%"), "pnl"],
      ["Você depois da cópia", sg(y.pnl_sol), y.trades + " trades · acerto " + (y.acerto == null ? "–" : f(y.acerto * 100, 0) + "%"), "pnl"],
      ["Diferença de horário (mediana)", med == null ? "–" : difT(med), "na entrada, nos tokens que os dois fizeram", "mon"]]);
    document.querySelectorAll("#exCopyF button").forEach((b) => b.classList.toggle("on", b.dataset.xcf === XC.f));
    if (XC.f === "comum") {
      table("exCopyTbl", ["Token", "Entrada " + esc(x.nome), "Sua entrada", "Diferença na entrada", "Saída " + esc(x.nome), "Sua saída", "Diferença na saída", "Resultado " + esc(x.nome), "Seu resultado"],
        (r.comum || []).map((m) => [pfM(m.mint, m.token), esc(hora(m.abriu_x)), esc(hora(m.abriu_y)), esc(difT(m.atraso_s)), esc(hora(m.fechou_x)), esc(hora(m.fechou_y)), esc(difT(m.saida_dif_s)),
          sg(m.pnl_x) + (m.pct_x == null ? "" : "<small>" + pc(m.pct_x) + "</small>"), sg(m.pnl_y) + (m.pct_y == null ? "" : "<small>" + pc(m.pct_y) + "</small>")]), "Nenhum token que os dois fizeram depois da cópia ainda.");
    } else {
      const L = XC.f === "x" ? r.so_x : r.so_y, who = XC.f === "x" ? x.nome : "você";
      table("exCopyTbl", ["Token", "Entrada (" + esc(who) + ")", "Saída", "Resultado", "Motivo da saída", XC.f === "x" ? "Por que você não entrou" : "Por que " + esc(x.nome) + " não entrou"],
        (L || []).map((g) => [pfM(g.mint, g.token), esc(hora(g.abriu_iso)), esc(hora(g.fechou_iso)), sg(g.pnl_sol), esc((g.motivos || []).join("; ")), '<b style="color:var(--warn)">' + esc(g.por_que_nao || "–") + "</b>"]),
        XC.f === "x" ? "Você fez todos os trades que " + esc(x.nome) + " fez." : "Nenhum trade só seu.");
    }
  }
  async function loadConfigUsers() {
    let r; try { r = await BB.api("/api/pump/config/users"); } catch (e) { return; }
    const L = (r && r.users) || [], idn = L.filter((u) => u.identica).length;
    document.querySelectorAll("[data-cfgusers]").forEach((box) => {
      box.hidden = !L.length; if (!L.length) return;
      box.querySelector("[data-cfgu-t]").textContent = "Você tem " + L.length + (L.length === 1 ? " usuário usando" : " usuários usando") + " a sua configuração";
      box.querySelector("[data-cfgu-s]").textContent = idn + " com a configuração idêntica à sua agora · " + (L.length - idn) + " mudaram alguma opção depois";
      box.querySelector("[data-cfgu-list]").innerHTML = '<div class="tbl-wrap"><table><thead><tr><th>Usuário</th><th>O que copiou</th><th>Desde</th><th>Situação agora</th></tr></thead><tbody>' +
        L.map((u) => "<tr><td>" + esc(u.nome) + "</td><td>" + esc(u.parte || "") + " · " + u.opcoes + " opções</td><td>" + esc(dt(u.em)) + "</td><td>" +
          (u.mudou == null ? '<span class="tag neutral">sem dados agora</span>' : u.identica ? '<span class="tag win">Idêntica à sua</span>' : '<span class="tag pause">Mudou ' + u.mudou + (u.mudou === 1 ? " opção" : " opções") + "</span>") + "</td></tr>").join("") +
        "</tbody></table></div>";
    });
  }
  async function loadApplied() {
    try { const r = await BB.api("/api/pump/config/applied"); APPLIED = (r && r.applied) || []; } catch (e) { return; }
    renderApplied();
    if (VIEW === "explorar") loadExCopy();
  }
  const cfgEq = (a, b) => (typeof a === "number" || typeof b === "number") && a !== "" && b !== "" && a != null && b != null && !isNaN(+a) && !isNaN(+b) ? Math.abs(+a - +b) < 1e-9 : String(a) === String(b);
  const cfgNow = (k) => { const c = cfg(); return isAutoCfg(k) ? autoValue(k, c) : c[k]; };
  function cardKeys(card) { return [...new Set([...card.querySelectorAll("[data-cfg],[data-toggle]")].map((e) => e.dataset.cfg || e.dataset.toggle))]; }
  function appliedFor(keys) {
    for (const o of APPLIED) { const ks = keys.filter((k) => Object.prototype.hasOwnProperty.call(o.valores, k)); if (ks.length) return [o, ks]; }
    return [null, []];
  }
  function renderApplied() {
    document.querySelectorAll('[data-view="config"] .card, [data-view="explorar"] .card').forEach((card, i) => {
      const h = card.querySelector(":scope > header > div"); if (!h || card.id === "allCfgCard") return;
      let el = h.querySelector(".cfgfrom");
      const [o, ks] = APPLIED.length ? appliedFor(cardKeys(card)) : [null, []];
      if (!o) { if (el) el.remove(); return; }
      const diff = ks.filter((k) => !cfgEq(cfgNow(k), o.valores[k])).length, quem = o.de || "outro usuário";
      const html = (diff ? '<span class="cfgdot diff"></span>Baseada na configuração de <b>' + esc(quem) + "</b> · " + diff + " de " + ks.length + (diff === 1 ? " opção mudou" : " opções mudaram") + " depois"
        : '<span class="cfgdot ok"></span>Você está usando a configuração <b>idêntica</b> à de <b>' + esc(quem) + "</b> (" + ks.length + " opções conferidas agora)") +
        ' · aceita em ' + esc(dt(o.em)) + ' <button class="btn sm" data-cfgdiff="' + o.id + '" data-card="' + i + '">Ver o que mudou</button>' +
        (diff ? '<span class="cfgask">Sua configuração ainda está diferente da de <b>' + esc(quem) + '</b>. Quer deixar idêntica?</span><button class="btn sm primary" data-cfgsync="' + o.id + '">Aplicar idêntica</button>' : "");
      if (!el) { el = document.createElement("div"); el.className = "cfgfrom"; h.appendChild(el); }
      if (el.dataset.h !== html) { el.dataset.h = html; el.innerHTML = html; el.classList.toggle("diff", !!diff); }
    });
  }
  function openCfgDiff(id, idx) {
    const o = APPLIED.find((x) => String(x.id) === String(id)); if (!o) return;
    const card = [...document.querySelectorAll('[data-view="config"] .card, [data-view="explorar"] .card')][+idx];
    const keys = card ? cardKeys(card) : Object.keys(o.valores), ks = keys.filter((k) => Object.prototype.hasOwnProperty.call(o.valores, k));
    const fora = keys.filter((k) => !ks.includes(k)), quem = o.de || "outro usuário", antes = o.antes || {};
    const rows = ks.map((k) => {
      const now = cfgNow(k), igual = cfgEq(now, o.valores[k]), tinha = Object.prototype.hasOwnProperty.call(antes, k);
      const mudouAoAceitar = tinha ? !cfgEq(antes[k], o.valores[k]) : null;
      const sit = !igual ? '<span class="tag pause">Você mudou depois</span>' : mudouAoAceitar === false ? '<span class="tag sim">Já era igual</span>' : '<span class="tag win">Igual ao enviado</span>';
      return [esc(cfgLabel(k)), tinha ? esc(cfgVal(k, antes[k])) : '<span class="muted">não guardado</span>', esc(cfgVal(k, o.valores[k])), "<b>" + esc(cfgVal(k, now)) + "</b>", sit];
    });
    const nDiff = ks.filter((k) => !cfgEq(cfgNow(k), o.valores[k])).length, nMud = ks.filter((k) => Object.prototype.hasOwnProperty.call(antes, k) && !cfgEq(antes[k], o.valores[k])).length;
    $("cfgDiffT").textContent = "Configuração de " + quem;
    $("cfgDiffS").textContent = (o.parte || "") + " · aceita em " + dt(o.em);
    $("cfgDiffB").innerHTML = '<div class="kpis" style="margin:4px 0 12px"><div class="kpi"><div class="l">Opções do convite neste quadro</div><div class="v">' + ks.length + '</div></div>' +
      '<div class="kpi"><div class="l">Mudaram ao aceitar</div><div class="v">' + (Object.keys(antes).length ? nMud : "–") + '</div></div>' +
      '<div class="kpi"><div class="l">Iguais ao enviado agora</div><div class="v ' + (nDiff ? "" : "up") + '">' + (ks.length - nDiff) + '</div></div>' +
      '<div class="kpi"><div class="l">Você mudou depois</div><div class="v ' + (nDiff ? "down" : "") + '">' + nDiff + "</div></div></div>" +
      '<div class="tbl-wrap"><table id="cfgDiffTbl"></table></div>' +
      (fora.length ? '<p class="muted" style="margin-top:10px">Não vieram no convite (continuam suas): ' + esc(fora.map(cfgLabel).join(" · ")) + "</p>" : "") +
      (Object.keys(antes).length ? "" : '<p class="muted">Este convite foi aceito antes da versão 0.31.31, por isso o valor de antes não foi guardado.</p>');
    table("cfgDiffTbl", ["Opção", "Antes de aceitar", "Enviado por " + esc(quem), "Agora", "Situação"], rows, "Nada deste quadro veio no convite.");
    $("cfgDiff").hidden = false; $("cfgDiffX").focus();
  }
  // 0.31.34 (pedido do dono em 2026-10-27): Comparar config copiada — usuário X (origem) × usuário Y (copiou), depois da cópia
  let CMP = { list: [], saved: [], cur: null };
  async function loadCompare() {
    const r = await BB.api("/api/pump/compare"); if (r.error) { $("cmpHelp").textContent = r.error; return; }
    CMP.list = r.copias || []; CMP.saved = r.salvas || [];
    const keep = $("cmpSel").value;
    $("cmpSel").innerHTML = CMP.list.length ? CMP.list.map((c) => '<option value="' + c.id + '">' + esc(c.de + " → " + c.para + " · " + (c.parte || "") + " · " + dt(c.em)) + "</option>").join("")
      : '<option value="">Nenhuma configuração copiada ainda</option>';
    if (keep && CMP.list.some((c) => String(c.id) === keep)) $("cmpSel").value = keep;
    $("cmpGo").disabled = !CMP.list.length;
    table("cmpSaved", ["Salva em", "Origem", "Copiou", "Texto para IA"], CMP.saved.map((s) => [esc(dt(s.em)),
      esc(s.x.nome || "") + "<small>" + (s.x.trades || 0) + " trades · " + f(s.x.pnl_sol || 0, 4) + " SOL</small>",
      esc(s.y.nome || "") + "<small>" + (s.y.trades || 0) + " trades · " + f(s.y.pnl_sol || 0, 4) + " SOL</small>",
      '<button class="btn sm" data-cmptxt="' + s.id + '">Copiar texto</button>']), "Nenhuma análise salva ainda.");
  }
  async function runCompare() {
    const id = $("cmpSel").value; if (!id) return;
    $("cmpGo").disabled = true; $("cmpHelp").textContent = "Analisando…";
    const r = await BB.api("/api/pump/compare/" + encodeURIComponent(id)); $("cmpGo").disabled = false;
    if (r.error) { $("cmpHelp").textContent = r.error; return; }
    CMP.cur = r; const x = r.x, y = r.y, pc = (v) => v == null ? "–" : f(v * 100, 0) + "%";
    $("cmpHelp").textContent = "Desde " + dt(r.desde) + " · " + (r.parte || "") + " · " + r.opcoes + " opções copiadas";
    kpis("cxK", [[esc(x.nome) + " (origem)", sg(x.pnl_sol), x.trades + " trades · acerto " + pc(x.acerto)], [esc(y.nome) + " (copiou)", sg(y.pnl_sol), y.trades + " trades · acerto " + pc(y.acerto)],
      ["Diferença", sg((y.pnl_sol || 0) - (x.pnl_sol || 0)), "copiou − origem"], ["Tokens em comum", String(r.comum.length), r.so_x.length + " só na origem · " + r.so_y.length + " só na cópia"]]);
    $("cmpConc").innerHTML = (r.conclusoes || []).map((c) => "<p>" + esc(c) + "</p>").join("") || '<p class="muted">Sem conclusões ainda.</p>';
    const ori = (o) => (o.por_origem || []).map((g) => [esc(g.nome), String(g.trades), g.acerto == null ? "–" : f(g.acerto * 100, 0) + "%", sg(g.pnl_sol)]);
    $("cmpXo").textContent = x.nome + " por origem"; $("cmpYo").textContent = y.nome + " por origem";
    table("cmpXOri", ["Origem", "Trades", "Acerto", "Resultado"], ori(x), "Nenhum trade depois da cópia.");
    table("cmpYOri", ["Origem", "Trades", "Acerto", "Resultado"], ori(y), "Nenhum trade depois da cópia.");
    table("cmpCom", ["Token", x.nome, y.nome, "Atraso de " + esc(y.nome), "Motivo (" + esc(x.nome) + ")", "Motivo (" + esc(y.nome) + ")"], r.comum.map((c) => [pfM(c.mint, c.token), sg(c.pnl_x), sg(c.pnl_y),
      c.atraso_s == null ? "–" : (c.atraso_s > 0 ? "+" : "") + hms(Math.abs(c.atraso_s)).replace(/^/, c.atraso_s < 0 ? "−" : ""), esc(c.motivo_x), esc(c.motivo_y)]), "Nenhum token em comum ainda.");
    $("cmpOxH").textContent = "Só com " + x.nome + " (não aconteceu com " + y.nome + ")"; $("cmpOyH").textContent = "Só com " + y.nome + " (não aconteceu com " + x.nome + ")";
    const only = (L) => L.map((g) => [pfM(g.mint, g.token), String(g.trades), sg(g.pnl_sol), esc((g.motivos || []).join("; "))]);
    table("cmpOx", ["Token", "Trades", "Resultado", "Motivo da saída"], only(r.so_x), "Nada.");
    table("cmpOy", ["Token", "Trades", "Resultado", "Motivo da saída"], only(r.so_y), "Nada.");
    $("cmpDrift").textContent = "Opções que mudaram depois da cópia: " + x.nome + " " + r.drift_x.length + " · " + y.nome + " " + r.drift_y.length;
    $("cmpOut").hidden = false;
  }
  async function copyText(txt) {
    try { await navigator.clipboard.writeText(txt); toast("Texto copiado. Cole na IA que você usa."); }
    catch (e) { const w = window.open("", "_blank"); if (w) { w.document.body.innerText = txt; } else toast("Não consegui copiar."); }
  }
  async function loadOffers() {
    let r; try { r = await BB.api("/api/pump/config/offers"); } catch (e) { return; }
    const of = (r && r.offers) || [], bar = $("offerBar");
    bar.hidden = !of.length;
    bar.innerHTML = of.map((o) => o.tipo === "atualizacao" ? offerUpdate(o) : '<div class="card" style="border-color:var(--accent,#22c55e);margin-bottom:12px"><header><div><h2>' + esc(o.de || "Outro usuário") + " quer compartilhar a configuração dele</h2>" +
      '<div class="sub">' + esc(o.parte || "") + " · " + o.opcoes + " opções · " + dt(o.em) + '</div></div><div class="sp"></div>' +
      '<button class="btn sm primary" data-ofa="' + esc(String(o.id)) + '">Aceitar e aplicar</button> <button class="btn sm" data-ofr="' + esc(String(o.id)) + '">Não aceitar</button></header>' +
      offerList(o) + "</div>").join("");
  }
  // 0.31.34 (pedido do dono em 2026-10-27): a pessoa de quem você copiou alterou a configuração — o que mudou, se ela
  // ganhou ou perdeu mais depois da mudança (e você, com a configuração antiga, no mesmo período) e aplicar ou não.
  function offerUpdate(o) {
    const e = o.efeito || {}, A = e.origem_antes || {}, D = e.origem_depois || {}, V = e.voce_depois || {}, de = o.de || "outro usuário";
    const lin = (r) => !r.trades ? "nenhum trade" : r.trades + " trades · " + sg(r.pnl_sol) + " · média " + sg(r.media_sol) + "/trade · acerto " + (r.acerto == null ? "–" : f(r.acerto * 100, 0) + "%");
    const verd = !D.trades ? '<span class="tag pause">Ainda sem trades depois da mudança</span> espere alguns trades para ver se a mudança foi boa.'
      : !A.trades ? '<span class="tag sim">Sem base de antes</span> não dá para comparar com o período anterior.'
      : (D.media_sol || 0) > (A.media_sol || 0) ? '<span class="tag win">Ganhou mais depois da mudança</span> média por trade melhorou de ' + sg(A.media_sol) + " para " + sg(D.media_sol) + "."
      : '<span class="tag loss">Perdeu mais depois da mudança</span> média por trade piorou de ' + sg(A.media_sol) + " para " + sg(D.media_sol) + ".";
    const ch = (o.mudou || []).map((m) => "<tr><td>" + esc(cfgLabel(m.k)) + '</td><td class="muted">' + esc(cfgVal(m.k, m.antes)) + "</td><td>→</td><td><b>" + esc(cfgVal(m.k, m.agora)) + "</b></td></tr>").join("");
    return '<div class="card" style="border-color:var(--warn,#f5a524);margin-bottom:12px"><header><div><h2>' + esc(de) + " alterou a configuração que você copiou</h2>" +
      '<div class="sub">você usa a configuração idêntica à dele · ' + (o.mudou || []).length + " opção(ões) mudaram · " + dt(o.em) + '</div></div><div class="sp"></div>' +
      '<button class="btn sm primary" data-ofa="' + esc(String(o.id)) + '">Aplicar a mudança</button> <button class="btn sm" data-ofr="' + esc(String(o.id)) + '">Não aplicar</button></header>' +
      '<p style="margin:4px 0 8px">' + verd + "</p>" +
      '<div class="hint">' + esc(de) + " antes da mudança: " + lin(A) + "<br>" + esc(de) + " depois da mudança: " + lin(D) + "<br>Você no mesmo período (configuração antiga): " + lin(V) + "</div>" +
      (ch ? '<div class="tbl-wrap" style="margin-top:8px"><table><thead><tr><th>O que ' + esc(de) + ' mudou</th><th>Antes</th><th></th><th>Agora</th></tr></thead><tbody>' + ch + "</tbody></table></div>" : "") + "</div>";
  }
  // 0.31.22: o convite mostrava os códigos (pump_ar_stop_pct...). Pedido do dono em 2026-10-27 ("está muito sujo"):
  // agora mostra o nome que a opção tem na tela e "seu valor → valor enviado"; as iguais às suas só são contadas.
  function cfgLabel(k) {
    const el = document.querySelector('[data-cfg="' + k + '"]:not([data-clone])') || document.querySelector('[data-hcfg="' + k + '"]') || document.querySelector('[data-toggle="' + k + '"]:not([data-clone])');
    const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
    if (!el) return clean(k.replace(/^pump_/, "").replace(/_/g, " "));
    const f = el.closest(".field"), lb = (el.id && document.querySelector('label[for="' + el.id + '"]')) || (f && f.querySelector("label"));
    let t = clean(lb && lb.textContent) || clean(el.getAttribute("aria-label"));
    if (!t) { const h = el.closest("header"), sp = el.previousElementSibling; t = clean(sp && sp.tagName === "SPAN" ? sp.textContent : h && (h.querySelector("h3,h2") || {}).textContent); }
    if (el.dataset.cfg && f && f.querySelector("[data-toggle]")) t += " (limite)";
    return t || k;
  }
  function cfgUnit(k) {
    const el = document.querySelector('[data-cfg="' + k + '"]:not([data-clone])'), sp = el && el.nextElementSibling;
    const u = sp && sp.tagName === "SPAN" ? sp.textContent.split("·")[0].trim() : "";
    return u.length <= 14 ? u : "";
  }
  function cfgVal(k, v) {
    if (v === true) return "ON";
    if (v === false) return "OFF";
    if (v === null || v === undefined || v === "") return "—";
    const u = cfgUnit(k);
    return String(v).replace(".", ",") + (u ? (u === "%" ? "%" : " " + u) : "");
  }
  function offerList(o) {
    if ((o.valores || {})._traders) {                        // 0.31.74: convite de lista de traders
      const L = o.valores._traders, mine = new Set(((D && D.manual) || []).map(String));
      const novos = L.filter((w) => !mine.has(w));
      return '<div class="hint">' + novos.length + " carteira(s) nova(s) para a sua lista de traders adicionados à mão" + (L.length - novos.length ? " · " + (L.length - novos.length) + " você já tem" : "") + ":</div>" +
        '<div class="hint">' + L.map((w) => pfW(w)).join(" · ") + "</div>";
    }
    const vals = o.valores || {}, c = cfg(), ks = Object.keys(vals);
    const mine = (k) => (isAutoCfg(k) ? autoValue(k, c) : c[k]);
    const muda = ks.filter((k) => String(mine(k)) !== String(vals[k])), iguais = ks.length - muda.length;
    if (!ks.length) return '<div class="hint muted">' + esc((o.nomes || []).map(cfgLabel).join(" · ")) + "</div>";
    const rows = muda.map((k) => "<tr><td>" + esc(cfgLabel(k)) + '</td><td class="muted">' + esc(cfgVal(k, mine(k))) + "</td><td>→</td><td><b>" + esc(cfgVal(k, vals[k])) + "</b></td></tr>").join("");
    return (muda.length ? '<div class="tbl-wrap" style="margin-top:6px"><table><thead><tr><th>O que muda</th><th>Seu valor</th><th></th><th>Valor enviado</th></tr></thead><tbody>' + rows + "</tbody></table></div>"
      : '<div class="hint">Nenhuma opção muda: os valores enviados são iguais aos seus.</div>') +
      (iguais && muda.length ? '<div class="hint muted">Mais ' + iguais + " " + (iguais === 1 ? "opção igual à sua" : "opções iguais às suas") + " (não muda nada).</div>" : "");
  }
  const cfgShareCards = () => [...document.querySelectorAll('[data-view="config"] .card')].filter((c) => c.id !== "cfShareTop" && c.querySelector("[data-cfsh]"));
  // sanfona (0.31.20): quadro com 3+ opções (ou as chaves pessoais) começa fechado; clique no título abre/fecha e a
  // escolha fica lembrada neste navegador. Execução real e relatórios ficam sempre abertos.
  function sanfona() {
    let saved = {}; try { saved = JSON.parse(localStorage.getItem("pf_sanf") || "{}"); } catch (e) { /* */ }
    document.querySelectorAll("section.view .card").forEach((card, i) => {
      const view = card.closest("section.view").dataset.view, h = card.querySelector(":scope > header");
      // 0.32.23: data-nosanf = quadro que nunca recolhe (o funil do Explorar "sumiu" ao ganhar as opções dos barrados, 28/10)
      if (!h || card.hasAttribute("data-nosanf") || card.classList.contains("sanf") || ["real", "estudo", "tradercfg"].includes(view) || /Share$/.test(card.id || "")) return;
      if (card.id !== "secretsCard" && !card.hasAttribute("data-sanf") && card.querySelectorAll("[data-cfg],[data-toggle],[data-set]").length < 3) return;
      const key = view + ":" + ((card.querySelector("h2") || {}).textContent || i).toString().trim().slice(0, 40);
      card.classList.add("sanf"); card.classList.toggle("fechado", saved[key] !== 1);
      h.setAttribute("aria-expanded", String(saved[key] === 1)); h.title = "Clique para abrir ou fechar";
      h.addEventListener("click", (e) => {
        if (e.target.closest("button,input,select,a,label")) return;
        const open = card.classList.toggle("fechado") === false;
        h.setAttribute("aria-expanded", String(open));
        try { const s = JSON.parse(localStorage.getItem("pf_sanf") || "{}"); s[key] = open ? 1 : 0; localStorage.setItem("pf_sanf", JSON.stringify(s)); } catch (err) { /* */ }
      });
    });
  }
  // 0.31.50 (pedido do dono: "são muitas telas de ON/OFF, quero tudo num lugar"): lê do próprio painel todas as opções de
  // todas as telas. Em Configurações vira um quadro editável (os botões e campos são os mesmos data-toggle/data-cfg, então
  // salvar aqui é salvar lá); na Visão geral vira um resumo só de leitura, junto com "está copiando alguém?".
  let ALLCFG = null;
  const ADMIN_VIEWS = ["admin", "novidades", "estudo", "radar", "relatorios", "aprendizado", "novas", "fantasma", "listanegra", "base", "explorar", "elite", "comparar", "bruxo"];
  function cfgItems() {
    if (ALLCFG) return ALLCFG;
    const out = [], seen = new Set(), adm = !!(ME && ME.role === "admin");
    document.querySelectorAll("section.view").forEach((sec) => {
      const v = sec.dataset.view; if (!TITLES[v] || (ADMIN_VIEWS.includes(v) && !adm)) return;
      sec.querySelectorAll(".card").forEach((card) => {
        if (card.id === "allCfgCard" || card.id === "sumCard") return;
        const ct = ((card.querySelector("h2") || {}).textContent || "").trim();
        card.querySelectorAll("[data-toggle],[data-cfg],[data-hcfg]").forEach((el) => {
          const k = el.dataset.toggle || el.dataset.cfg || el.dataset.hcfg; if (!k || seen.has(k) || el.dataset.clone) return; seen.add(k);
          out.push({ v, vt: TITLES[v][0], ct, k, tog: !!el.dataset.toggle, label: cfgLabel(k), unit: el.dataset.hcfg ? "min" : el.dataset.cfg ? cfgUnit(k) : "",
            min: el.dataset.hcfg ? "1" : el.getAttribute("min"), max: el.dataset.hcfg ? "1440" : el.getAttribute("max"), step: el.dataset.hcfg ? "1" : el.getAttribute("step"), confirm: el.dataset.confirm || "" });
        });
      });
    });
    return ME ? (ALLCFG = out) : out;            // sem saber se é admin ainda, não guarda
  }
  function buildAllCfg() {
    if (!ME || !$("allCfg") || $("allCfg").dataset.ok) return;
    const items = cfgItems().filter((x) => x.v !== "config"), by = {};
    items.forEach((x) => { (by[x.v] = by[x.v] || []).push(x); });
    const ctl = (x) => x.tog ? '<button class="btn sm tgl" data-clone="1" data-toggle="' + esc(x.k) + '"' + (x.confirm ? ' data-confirm="' + esc(x.confirm) + '"' : "") + ">…</button>"
      : '<input class="in w100" type="number" data-clone="1" data-cfg="' + esc(x.k) + '"' + (x.min != null ? ' min="' + esc(x.min) + '"' : "") + (x.max != null ? ' max="' + esc(x.max) + '"' : "") + (x.step != null ? ' step="' + esc(x.step) + '"' : "") + ' aria-label="' + esc(x.label) + '">' + (x.unit ? ' <span class="muted">' + esc(x.unit) + "</span>" : "");
    $("allCfg").innerHTML = Object.keys(by).map((v) => {
      let last = "";
      return '<details class="allcfg"><summary><b>' + esc(by[v][0].vt) + "</b> <span class=\"muted\">" + by[v].length + ' opções</span> <span data-allid="' + esc(v) + '"></span> <a class="btn sm" href="#' + v + '">abrir a tela</a></summary>' +
        by[v].map((x) => (x.ct !== last ? '<div class="allcfg-h">' + esc((last = x.ct)) + "</div>" : "") + '<div class="allcfg-r"><span>' + esc(x.label) + "</span><span>" + ctl(x) + "</span></div>").join("") + "</details>";
    }).join("") || '<p class="muted">Nenhuma opção de outra tela disponível para esta conta.</p>';
    $("allCfg").dataset.ok = "1";
    if (D) render();
  }
  // 0.31.51 (pedido do dono): confirmação "100% igual" conferindo agora cada opção que veio de outro usuário
  // 0.31.53 (pedido do dono: "o que é essa coisa diferente?"): cópia antiga cujas opções vieram de novo numa cópia mais
  // nova não conta mais (era ela que aparecia como "1 diferente"); cada cópia com diferença ganha o botão que abre o modal
  function liveCopies() {
    const L = APPLIED.slice().sort((a, b) => new Date(b.em) - new Date(a.em)), seen = new Set(), out = [];
    L.forEach((o) => { const ks = Object.keys(o.valores || {}).filter((k) => !seen.has(k)); ks.forEach((k) => seen.add(k)); if (ks.length) out.push([o, ks]); });
    return out;
  }
  function copyHtml() {
    const quem = (o) => esc(o.de || "outro usuário"), L = liveCopies();
    return L.length ? L.map(([o, ks]) => {
      const dk = ks.filter((k) => !cfgEq(cfgNow(k), o.valores[k])), pct = ks.length ? Math.round((ks.length - dk.length) / ks.length * 100) : 0;
      return "<p>" + (dk.length ? '<span class="cfgdot diff"></span>' : '<span class="cfgdot ok"></span>') + "Configuração de <b>" + quem(o) + "</b> (" + ks.length + " opções, desde " + esc(dt(o.em)) + "): " +
        (dk.length ? "<b>" + pct + "% igual · " + dk.length + " diferente(s) agora</b> <span class=\"muted\">(" + esc(dk.slice(0, 6).map(cfgLabel).join(", ")) + (dk.length > 6 ? "…" : "") + ')</span> <button class="btn sm primary" data-copydiff="' + esc(String(o.id)) + '">Ver o que está diferente</button>'
          : "<b class=\"up\">100% idêntica agora</b> (" + ks.length + " de " + ks.length + " opções conferidas)") + "</p>";
    }).join("") : "<p>Você <b>não</b> está usando a configuração de ninguém.</p>";
  }
  function openCopyDiff(id) {
    const hit = liveCopies().find(([o]) => String(o.id) === String(id)); if (!hit) return;
    const [o, ks] = hit, quem = o.de || "outro usuário", dk = ks.filter((k) => !cfgEq(cfgNow(k), o.valores[k]));
    $("cfgDiffT").textContent = "O que está diferente da configuração de " + quem;
    $("cfgDiffS").textContent = (o.parte || "") + " · copiada em " + dt(o.em) + " · " + dk.length + " de " + ks.length + " opções diferentes";
    $("cfgDiffB").innerHTML = '<div class="tbl-wrap"><table id="cfgDiffTbl"></table></div>' +
      (dk.length ? '<p style="margin-top:12px">Quer aplicar o valor de <b>' + esc(quem) + "</b> no seu, nessas " + dk.length + ' opção(ões)? O resto da sua configuração não muda.</p><p><button class="btn primary" data-copyapply="' + esc(String(o.id)) + '">Aplicar o dele no meu</button> <button class="btn" id="cfgDiffNo">Não, deixar o meu</button></p>'
        : '<p class="up" style="margin-top:12px">Tudo igual: nada para aplicar.</p>');
    table("cfgDiffTbl", ["Opção", "O seu (agora)", "O de " + esc(quem)], dk.map((k) => [esc(cfgLabel(k)), "<b>" + esc(cfgVal(k, cfgNow(k))) + "</b>", '<b class="up">' + esc(cfgVal(k, o.valores[k])) + "</b>"]), "Nenhuma diferença.");
    $("cfgDiff").hidden = false; $("cfgDiffX").focus();
  }
  // 0.31.61: copiar os TRADES de outro usuário (não só a configuração)
  let FOLLOW = null;
  async function loadFollow() {
    if (!(ME && ME.role === "admin")) return;
    const [r, t] = await Promise.all([BB.api("/api/pump/follow-user"), BB.api("/api/pump/config/share-targets")]);
    if (r.error) return;
    FOLLOW = r; $("followCard").hidden = false;
    const us = (t && t.users) || [];
    $("flSel").innerHTML = '<option value="">Escolha a conta…</option>' + us.map((u) => '<option value="' + esc(u.user_id) + '"' + (u.user_id === r.follow_user ? " selected" : "") + ">" + esc(u.nome || u.email || u.user_id) + "</option>").join("");
    $("flState").innerHTML = (r.follow_user ? '<span class="tag win">ON · Ligado</span> Copiando os trades de <b>' + esc(r.nome) + "</b>." : '<span class="tag loss">OFF · Desligado</span> Não está copiando os trades de ninguém.') +
      (r.seguidores && r.seguidores.length ? ' <span class="muted">· Copiam os SEUS trades: ' + esc(r.seguidores.join(", ")) + "</span>" : "");
  }
  // 0.32.4 (pedido do dono, 28/10): "Copiar igual" — carteiras do leaderboard da pump.fun coladas à mão
  let EQ = null, EQ_W = "", EQ_D = "";
  async function openEqDetail() {
    $("eqDT").textContent = "Acompanhar " + EQ_D.slice(0, 4) + "…" + EQ_D.slice(-4); $("eqDS").textContent = "carregando…"; $("eqD").hidden = false;
    const r = await BB.api("/api/pump/copy-equal/wallet/" + encodeURIComponent(EQ_D)); if (r.error) { $("eqDS").textContent = r.error; return; }
    const modo = !r.ligado || r.modo === "off" ? "parada" : r.modo === "both" ? "copiando na FICTÍCIA e na REAL" : "copiando na FICTÍCIA";
    $("eqDS").textContent = modo + " · última atividade: " + (r.ultima_atividade ? dt(r.ultima_atividade) : "nenhuma vista") + (r.online ? " (online)" : "");
    const aviso = !r.monitor_ok ? '<div class="decbox bad"><b>O monitor da Solana está fora:</b> ' + esc(r.monitor_erro || "sem conexão") + ". Enquanto ele não voltar, as compras desta carteira não chegam e nada é copiado (precisa do RPC próprio no Portainer).</div>"
      : !r.ouvindo ? '<div class="decbox bad"><b>Esta carteira não está sendo ouvida.</b> Clique em Copiar para ela entrar na lista.</div>'
      : '<div class="decbox ok">O monitor está ouvindo esta carteira. Cada compra ou venda dela aparece abaixo em segundos.</div>';
    $("eqDB").innerHTML = aviso + '<p class="muted small"><a href="https://solscan.io/account/' + encodeURIComponent(r.wallet) + '" target="_blank" rel="noopener">Ver a carteira no Solscan</a> (o que ela fez de verdade, para comparar)</p>' +
      "<h3>Posições abertas</h3><div class=\"tbl-wrap\"><table id=\"eqDA\" class=\"daytbl\"></table></div>" +
      "<h3>O que ela fez e o que o robô fez (24 h)</h3><div class=\"tbl-wrap\"><table id=\"eqDE\" class=\"daytbl\"></table></div>" +
      "<h3>Fechadas</h3><div class=\"tbl-wrap\"><table id=\"eqDF\" class=\"daytbl\"></table></div>";
    table("eqDA", ["Aberta", "Token", "Carteira", "Investido", "Agora"], (r.abertas || []).map((p) => [dt(p.aberta_em), pfM(p.mint, p.token), p.real ? '<span class="tag real">REAL</span>' : '<span class="tag">FICTÍCIA</span>', s4(p.investido) + " SOL", p.agora_pct == null ? "–" : pc(p.agora_pct)]), "Nenhuma posição aberta desta carteira.");
    table("eqDE", ["Quando", "Ação", "Token", "SOL dela", "Motivo"], (r.eventos || []).map((x) => [dt(x.em), esc(x.acao || ""), x.mint ? pfM(x.mint, x.token) : esc(x.token || "–"), x.sol == null ? "–" : s4(x.sol), '<span class="wrapcell">' + esc(x.motivo || "") + "</span>"]),
      r.monitor_ok ? "Nenhuma compra ou venda desta carteira vista nas últimas 24 h." : "Nada visto: o monitor está fora.");
    table("eqDF", ["Fechou", "Token", "Carteira", "Resultado", "Tempo", "Saída"], (r.fechadas || []).map((x) => [dt(x.fechou_em), pfM(x.mint, x.token), x.real ? '<span class="tag real">REAL</span>' : '<span class="tag">FICTÍCIA</span>', sg(x.pnl_sol) + "<small>" + pc(x.pnl_pct) + "</small>", x.hold_s == null ? "–" : hms(x.hold_s), '<span class="wrapcell">' + esc(x.motivo || "") + "</span>"]), "Nenhuma operação fechada ainda.");
  }
  async function loadEq() {
    let r; try { r = await BB.api("/api/pump/copy-equal"); } catch (e) { return; }
    if (!r || r.error) return;
    EQ = r;
    $("eqK").innerHTML = [["Modo", r.on ? '<span class="up">ON</span>' : '<span class="down">OFF</span>'], ["Carteiras", r.wallets.length + (r.on ? " · " + r.seguidas + " seguidas" : "")],
      ["Posições abertas", r.abertas], ["Fechadas", r.fechadas], ["Resultado (fictícia)", sg(r.pnl_sol)]]
      .map(([l, v]) => '<div class="kpi"><div class="l">' + l + '</div><div class="v">' + v + "</div></div>").join("");
    // 0.32.65 (pedido do dono): botão Copiar em cada carteira, pergunta fictícia ou REAL
    const eqTag = (w) => !r.on || w.modo === "off" ? '<span class="tag loss">parado</span>' : w.modo === "both" || r.real ? '<span class="tag win">copiando · FICTÍCIA e REAL</span>' : '<span class="tag win">copiando · FICTÍCIA</span>';
    table("eqTbl", ["Carteira", "Cópia", "Online", "Vistas 24 h", "Copiadas 24 h", "Abertas", "Fechadas", "Acerto", "Resultado", "Real", "Último motivo de não copiar"],
      r.wallets.map((w) => [pfW(w.wallet), '<span class="nowrap">' + eqTag(w) + ' <button class="btn sm primary" data-eqc="' + esc(w.wallet) + '">' + (r.on && w.modo !== "off" ? "Mudar" : "Copiar") + '</button> <button class="btn sm" data-eqd="' + esc(w.wallet) + '">Acompanhar</button></span>', w.online ? '<span class="up">sim</span>' : '<span class="muted">não</span>', w.vistas_24h, w.copiadas_24h, w.abertas, w.fechadas,
        w.fechadas ? f(w.ganhos / w.fechadas * 100, 0) + "%" : "–", sg(w.pnl_sol), w.pnl_real_sol ? sg(w.pnl_real_sol) : "–", '<span class="wrapcell">' + esc(w.ultimo_motivo || "–") + "</span>"]),
      "Nenhuma carteira na lista.");
    if (document.activeElement !== $("eqList")) $("eqList").value = r.wallets.map((w) => w.wallet).join("\n");
  }
  function renderAllCfgCopy() {
    if (!$("allCfgCopy")) return;
    const h = copyHtml();
    if ($("allCfgCopy").dataset.h !== h) { $("allCfgCopy").dataset.h = h; $("allCfgCopy").innerHTML = h; }
    const by = {};
    cfgItems().forEach((x) => { (by[x.v] = by[x.v] || []).push(x.k); });
    document.querySelectorAll("[data-allid]").forEach((el) => {
      const ks = by[el.dataset.allid] || [], live = liveCopies(), src = {};
      live.forEach(([o2, ks2]) => ks2.forEach((k) => { src[k] = o2; }));
      const cp = ks.filter((k) => src[k]), o = cp.length ? src[cp[0]] : null;
      if (!o) { el.innerHTML = '<span class="muted">· sua própria configuração</span>'; return; }
      const d = cp.filter((k) => !cfgEq(cfgNow(k), src[k].valores[k])).length;
      el.innerHTML = d ? '<span class="cfgdot diff"></span>' + (cp.length - d) + " de " + cp.length + " iguais às de " + esc(o.de || "outro usuário")
        : '<span class="cfgdot ok"></span><b class="up">100% idêntica</b> à de ' + esc(o.de || "outro usuário") + " (" + cp.length + " opções)";
    });
  }
  function renderSummary() {
    if (!$("sumCard") || !D) return;
    const c = cfg(), R = D.real || {};
    const copy = copyHtml() + (FOLLOW ? "<p>Trades: " + (FOLLOW.follow_user ? '<b class="up">copiando os trades de ' + esc(FOLLOW.nome) + "</b> (abre e fecha junto)" : "<b>não</b> está copiando os trades de ninguém") + ' <a href="#config">mudar</a></p>' : "");
    const html = copy +
      '<p class="hint">Copiar a configuração copia as <b>regras</b>, não os <b>trades</b>: a sua conta decide sozinha, com o seu próprio histórico (aprender com os erros, pausas, limites por hora). Mesmo com a configuração idêntica, os trades podem ser diferentes; veja a comparação no Explorar.</p>' +
      "<p>Execução real: <b class=\"" + (R.enabled ? "up\">LIGADA" : "down\">DESLIGADA") + "</b> · Espelhar a fictícia na real: <b class=\"" + (c.pump_real_mirror !== false ? "up\">ON · Ligado" : "down\">OFF · Desligado") + "</b></p>";
    if ($("sumCopy").dataset.h !== html) { $("sumCopy").dataset.h = html; $("sumCopy").innerHTML = html; }
    const items = cfgItems().filter((x) => x.tog), by = {};
    items.forEach((x) => { (by[x.vt] = by[x.vt] || []).push(x); });
    const h2 = Object.keys(by).map((vt) => {
      const L = by[vt], on = L.filter((x) => !!cfgNow(x.k)).length;
      return '<details class="allcfg"><summary><b>' + esc(vt) + '</b> <span class="muted">' + on + " ligado(s) de " + L.length + "</span></summary>" +
        L.map((x) => '<span class="chip ' + (cfgNow(x.k) ? "on" : "off") + '">' + (cfgNow(x.k) ? "ON" : "OFF") + " · " + esc(x.label) + "</span>").join("") + "</details>";
    }).join("");
    if ($("sumCfg").dataset.h !== h2) { $("sumCfg").dataset.h = h2; $("sumCfg").innerHTML = h2; }
  }
  function cfgShareButtons() {
    if (!(ME && ME.role === "admin")) return;
    $("cfShareTop").hidden = false;
    BB.api("/api/pump/config/share-targets").then((r) => {
      const us = (r && r.users) || [];
      $("cfAllU").innerHTML = us.length ? '<option value="">Escolha a pessoa…</option>' + us.map((u) => '<option value="' + esc(u.user_id) + '">' + esc((u.nome || "sem nome") + (u.email ? " · " + u.email : "") + (u.admin ? " · admin" : "")) + "</option>").join("")
        : '<option value="">Nenhum outro usuário cadastrado</option>';
      $("cfAllGo").disabled = !us.length;
    }).catch(() => {});
    document.querySelectorAll('[data-view="config"] .card').forEach((card) => {
      const h = card.querySelector("header");
      if (!h || card.id === "secretsCard" || card.id === "cfShare" || card.id === "allCfgCard" || h.querySelector("[data-cfsh]") || !card.querySelector("[data-cfg],[data-toggle]")) return;
      if (!h.querySelector(".sp")) { const sp = document.createElement("div"); sp.className = "sp"; h.appendChild(sp); }
      const b = document.createElement("button"); b.className = "btn sm"; b.dataset.cfsh = "card"; b.textContent = "Compartilhar"; h.appendChild(b);
    });
  }
  async function loadTune() {
    const r = await BB.api("/api/pump/tune");
    if (r.error) return;
    const ru = r.rules || {};
    $("tuSub").textContent = (r.on ? "LIGADO" : "DESLIGADO") + (r.real_on ? " · parado: a execução real está ligada" : "") + " · última volta " + (r.last_run ? dt(r.last_run) : "ainda não rodou (roda a cada 6 h)") +
      (r.testing ? " · em teste: " + (r.testing.nome || "") + " desde " + dt(r.testing.desde) : " · nenhuma regra em teste") + " · precisa de " + ru.min_trades + " trades e " + ru.min_days + " dias de fantasmas";
    const AC = { aplicou: "win", manteve: "win", desfez: "loss", pausou: "pause" };
    table("tuLog", ["Quando", "O quê", "Decisão", "Por quê"], (r.log || []).map((x) => [dt(x.em), x.tipo === "saida" ? "saída das cópias" : x.tipo === "saida_auto" ? "saída das automáticas" : "trader", '<span class="tag ' + (AC[x.acao] || "neutral") + '">' + esc(x.acao) + "</span>", esc(x.motivo || "")]),
      "Nenhuma mudança ainda: a primeira sai quando as Estratégias fantasma tiverem base (30 trades e 2 dias) ou quando um trader repetir prejuízo.");
  }
  async function loadReports() {
    loadTune();
    const rm = realMode(), r = await BB.api("/api/pump/reports?days=" + REP_DAYS + "&real=" + (rm ? 1 : 0));
    if (r.error) { toast(r.error); return; }
    REP_AT = Date.now(); REP_MODE = rm;
    const t = r.total || {}, fp = r.fee_parts || {}, pctW = (x) => (x == null ? "–" : f(x * 100, 0) + "%");
    kpis("repKpis", [["Resultado", sg(t.pnl_sol), t.trades + " trades fechados", "pnl"], ["Taxa de acerto", pctW(t.win_rate), (t.wins || 0) + " ganhos", "hit"],
      ["Média por trade", sg(t.avg_pnl_sol), "investido " + s4(t.invested_sol) + " SOL", "tr"],
      ["Atraso médio das cópias", t.avg_lag_s == null ? "–" : f(t.avg_lag_s, 1) + "<small> s</small>", "do trade do trader até a sua cópia", "mon"],
      ["Taxas pagas", s4(t.fees_sol) + "<small> SOL</small>", "pump.fun " + s4(fp.platform) + " · PumpPortal " + s4(fp.portal) + " · rede " + s4(fp.network), "wallet"]]);
    const ST2 = { copiando: '<span class="tag win">copiando</span>', pausado: '<span class="tag pause">pausado</span>', fora: '<span class="tag neutral">fora</span>' };
    table("repTr", ["Trader", "Situação", "Trades", "Acerto", "Resultado p/ você", "Média", "Taxas", "Segurou (média)", "Último"], (r.traders || []).map((x) => [pfW(x.wallet, x), ST2[x.status] || "", String(x.trades), pctW(x.win_rate), "<b>" + sg(x.pnl_sol) + "</b>", sg(x.avg_pnl_sol), s4(x.fees_sol), hms(x.avg_hold_s), dt(x.last)]), "Nenhum trade fechado no período.");
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
    const au = r.autopsy || {};
    $("autSub").textContent = (au.losses || 0) + " trades no prejuízo no período · " + s4(au.lost_sol || 0) + " SOL · as causas do dia ficam guardadas no banco para o aprendizado";
    kpis("autK", (au.causes || []).slice(0, 4).map((c) => [c.nome, sg(c.perdido_sol), c.trades + " trades", "pos"]));
    table("autCause", ["Causa", "Trades", "Perdido", "Correção recomendada"], (au.causes || []).map((c) => [esc(c.nome), String(c.trades), sg(c.perdido_sol), esc(c.correcao)]), "Nenhum trade no prejuízo no período.");
    table("autTr", ["Trader", "Trades", "Acerto", "Resultado", "Segura (média)", "Causa principal", "O que fazer"], (au.traders || []).map((x) => [pfW(x.wallet, x), String(x.trades), f(x.acerto * 100, 0) + "%", sg(x.pnl_sol), hms(x.hold_s), esc(x.causa_nome), esc(x.recomendacao)]), "Nenhum trader no vermelho.");
    table("autTrades", ["Fechou", "Token", "Trader", "Resultado", "Melhor momento", "Segurou", "Motivo", "Causa"], (au.trades || []).map((x) => [dt(x.closed_at), pfM(x.mint || "", x.symbol), pfW(x.wallet || ""),
      sg(x.pnl_sol) + (x.pnl_pct == null ? "" : "<small>" + f(x.pnl_pct, 1) + "%</small>"), x.best_pct == null ? "–" : (x.best_pct > 0 ? "+" : "") + f(x.best_pct, 1) + "%", hms(x.hold_s), esc(x.reason || ""), '<span class="tag loss">' + esc(x.causa_nome) + "</span>"]), "Nenhum.");
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
  // ------------------------------------------------------------------ maiores traders (/api/pump/elite, 0.31.2)
  let EL_T = null, EL = null, EL_TAB = "lucro";
  function renderEliteTraders() {
    const r = EL || {}, rec = new Set(r.recommended || []), fol = new Set(r.followed || []), stu = new Set(r.studying || []);
    let rows = (r.traders || []).slice();
    const by = { lucro: (x) => -(x.realized_usd || 0), acerto: (x) => -(x.winrate || 0), top80: (x) => -(x.realized_usd || 0),
      saldo: (x) => -((x.balance || {}).usd || 0), idade: (x) => -((x.age || {}).age_days || 0) };
    if (EL_TAB === "top80") rows = rows.filter((x) => rec.has(x.wallet));
    rows.sort((a, b) => by[EL_TAB](a) - by[EL_TAB](b));
    const age = (a) => !a || a.age_days == null ? '<span class="muted">…</span>' : (a.more ? "+" : "") + f(a.age_days, a.age_days < 10 ? 1 : 0) + " dias";
    table("elTr", ["#", "Trader", "Acerto", "Lucro (ranking)", "Trades", "Saldo (SOL+USD)", "Idade da carteira", "Dias ativos", "Última ação", ""], rows.map((x, i) => [String(i + 1),
      pfW(x.wallet, x) + (x.name ? " <b>" + esc(x.name) + "</b>" : "") + (x.twitter ? ' <a href="' + esc(x.twitter) + '" target="_blank" rel="noopener">X</a>' : "") + (rec.has(x.wallet) ? ' <span class="tag win">80%+</span>' : "") + (x.bot ? ' <span class="tag loss" title="' + esc(x.bot) + '">robô</span>' : ""),
      x.winrate == null ? "–" : '<b class="' + (x.winrate >= 80 ? "up" : "") + '">' + f(x.winrate, 0) + "%</b>", x.realized_usd == null ? "–" : "$" + f(x.realized_usd, 0), x.trades == null ? "–" : f(x.trades, 0),
      x.balance ? "$" + f(x.balance.usd, 0) + "<small>" + f(x.balance.sol, 1) + " SOL</small>" : '<span class="muted">…</span>', age(x.age), x.days_active == null ? "–" : String(x.days_active),
      x.last ? (x.last.kind === "buy" ? "comprou " : "vendeu ") + esc(x.last.symbol || x.last.mint.slice(0, 6)) + "<small>" + dt(x.last.t * 1000) + "</small>" : "–",
      (fol.has(x.wallet) ? '<span class="tag win">copiando</span> ' : '<button class="btn sm" data-stc="' + esc(x.wallet) + '">Copiar</button> ') +
      (stu.has(x.wallet) ? '<span class="tag sim">em estudo</span>' : '<button class="btn sm" data-elst="' + esc(x.wallet) + '" data-name="' + esc(x.name || "") + '">Estudar</button>')]),
      EL_TAB === "top80" ? "Nenhum dos maiores traders tem 80%+ de acerto com 100+ trades agora." : "Sem ranking ainda.");
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("#elTabs button");
    if (b) { EL_TAB = b.dataset.el; document.querySelectorAll("#elTabs button").forEach((x) => x.classList.toggle("on", x === b)); renderEliteTraders(); return; }
    const t = e.target;
    if (t.dataset && t.dataset.elst) {
      const r = await BB.api("/api/pump/study", { body: { wallet: t.dataset.elst, action: "add", apelido: (t.dataset.name || "").slice(0, 40) } });
      toast(r.error ? "Não adicionou: " + r.error : "Carteira em estudo: veja em Carteiras em estudo se compensa copiar."); loadElite();
    }
  });
  const svgEsc = (s) => esc(String(s));
  // linha do lucro acumulado: uma série, com ponto e valor no fim e dica (title) em cada ponto
  function lineChart(pts) {
    if (pts.length < 2) return '<p class="muted">O gráfico aparece com 2 ou mais compras automáticas fechadas.</p>';
    const W = 640, H = 180, P = 34, xs = pts.map((p) => p.t), ys = pts.map((p) => p.v), x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys), sx = (t) => P + (W - 2 * P) * (x1 > x0 ? (t - x0) / (x1 - x0) : 1), sy = (v) => H - P + (y1 > y0 ? -(H - 2 * P) * (v - y0) / (y1 - y0) : 0);
    const d = pts.map((p, i) => (i ? "L" : "M") + sx(p.t).toFixed(1) + " " + sy(p.v).toFixed(1)).join(" "), last = pts[pts.length - 1];
    return '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Lucro acumulado das compras automáticas"><line class="ax" x1="' + P + '" x2="' + (W - P) + '" y1="' + sy(0) + '" y2="' + sy(0) + '"/><text x="2" y="' + (sy(0) + 4) + '">0</text>' +
      '<path class="' + (last.v >= 0 ? "ln" : "lnd") + '" d="' + d + '"/>' + pts.map((p) => '<circle class="hit" cx="' + sx(p.t) + '" cy="' + sy(p.v) + '" r="9"><title>' + svgEsc(dt(p.t) + " · " + (p.label || "") + " · acumulado " + (p.v > 0 ? "+" : "") + p.v.toFixed(4) + " SOL") + "</title></circle>").join("") +
      '<circle class="dot" cx="' + sx(last.t) + '" cy="' + sy(last.v) + '" r="4"/><text x="' + Math.min(sx(last.t) + 6, W - 70) + '" y="' + (sy(last.v) - 8) + '">' + (last.v > 0 ? "+" : "") + last.v.toFixed(4) + " SOL</text></svg>";
  }
  // barras horizontais (resultado médio em 60 min por trader): positivo verde, negativo vermelho, valor escrito
  function barChart(rows) {
    if (!rows.length) return '<p class="muted">Aparece quando houver sinais encerrados.</p>';
    const W = 640, row = 26, H = rows.length * row + 10, mx = Math.max(1, ...rows.map((r) => Math.abs(r.v))), mid = 260, half = (W - mid - 70) / 2, c = mid + half;
    return '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Resultado médio em 60 minutos por trader"><line class="ax" x1="' + c + '" x2="' + c + '" y1="0" y2="' + H + '"/>' + rows.map((r, i) => {
      const y = 5 + i * row, w = Math.max(2, Math.abs(r.v) / mx * half), x = r.v >= 0 ? c : c - w;
      return '<g class="tipg"><text x="0" y="' + (y + 15) + '">' + svgEsc(r.label.slice(0, 30)) + '</text><rect class="' + (r.v >= 0 ? "bup" : "bdn") + '" x="' + x + '" y="' + (y + 4) + '" width="' + w + '" height="14" rx="3"><title>' + svgEsc(r.label + ": " + (r.v > 0 ? "+" : "") + r.v.toFixed(1) + "% em média · " + r.n + " sinais") + '</title></rect><text x="' + (W - 60) + '" y="' + (y + 15) + '">' + (r.v > 0 ? "+" : "") + r.v.toFixed(0) + "%</text></g>";
    }).join("") + "</svg>";
  }
  // ------------------------------------------------------------------ relatório do dia (/api/pump/daily, 0.31.5, só admin)
  let DAY = "", DAY_T = null, DAY_MODE = null;
  // 0.31.45 (pedido do dono): o relatório segue o botão Fictícia/Real do topo
  const dayQ = (dia) => "?real=" + (realMode() ? 1 : 0) + (dia ? "&dia=" + encodeURIComponent(dia) : "");
  async function loadDaily() {
    if (!(ME && ME.role === "admin")) return;
    clearTimeout(DAY_T); DAY_T = setTimeout(() => { if (VIEW === "visao") loadDaily(); }, 60000);
    const mode = realMode(); DAY_MODE = mode;
    const r = await BB.api("/api/pump/daily" + dayQ(DAY));
    if (r.error || !r.report || mode !== realMode()) return;
    const RL = !!r.report.real;
    $("dayCard").hidden = false; $("dayChartCard").hidden = false;
    const rep = r.report, pts = rep.points || [], first = pts[0] || {}, last = pts[pts.length - 1] || {};
    const sel = $("daySel"), cur = DAY || r.today;
    sel.innerHTML = [r.today].concat((r.days || []).map((d) => d.dia).filter((d) => d !== r.today)).map((d) => '<option value="' + esc(d) + '"' + (d === cur ? " selected" : "") + ">" + esc(d.split("-").reverse().join("/")) + (d === r.today ? " (hoje)" : "") + "</option>").join("");
    $("daySub").textContent = (rep.closed ? "dia fechado" : "ao vivo") + " · " + pts.length + (RL ? " trades reais" : " fotos guardadas") + " · atualizado " + dt(rep.generated_at) + (RL ? " · carteira REAL" : " · carteira fictícia");
    const ch = first.saldo && last.saldo != null ? (last.saldo / first.saldo - 1) * 100 : null;
    $("dayChartSub").textContent = (RL ? "carteira REAL · resultado acumulado · " : "carteira fictícia · ") + (cur || "").split("-").reverse().join("/") + " · troque o dia no Relatório do dia abaixo";
    kpis("dayK", [["Resultado do dia", sg(rep.pnl_sol), rep.trades + " trades fechados · taxas " + s4(rep.fees_sol) + " SOL", "pnl"],
      ["Acerto do dia", rep.acerto == null ? "–" : f(rep.acerto * 100, 0) + "%", rep.wins + " ganhos", "hit"],
      RL ? ["Investido no dia", s4(rep.invested_sol) + " SOL", rep.invested_sol ? "retorno " + pc(rep.pnl_sol / rep.invested_sol * 100) : "nenhuma compra fechada", "wallet"] :
      ["Saldo no dia", ch == null ? "–" : '<span class="' + (ch >= 0 ? "up" : "down") + '">' + (ch > 0 ? "+" : "") + f(ch, 1) + "%</span>", first.saldo ? s4(first.saldo) + " → " + s4(last.saldo) + " SOL" : "", "wallet"],
      ["Devolveu lucro", String(rep.gave_back || 0), "chegaram a +30% e fecharam no zero ou pior", "mon"]]);
    $("dayChart").innerHTML = RL ? lineChart(pts.filter((p) => p.resultado != null).map((p) => ({ t: p.t * 1000, v: p.resultado, label: "resultado real " + s4(p.resultado) + " SOL" })))
      : lineChart(pts.filter((p) => p.saldo != null).map((p) => ({ t: p.t * 1000, v: p.saldo - (first.saldo || 0), label: "saldo " + s4(p.saldo) + " SOL" })));
    $("daySug").innerHTML = (rep.suggestions || []).map((s) => '<p><span class="tag ' + (s.area === "info" ? "neutral" : s.area === "código" ? "pause" : "sim") + '">' + esc(s.area) + "</span> " + esc(s.texto) + (s.base ? ' <span class="muted">(base: ' + s.base + ")</span>" : "") + "</p>").join("");
    const g = (rows) => (rows || []).map((x) => [esc(x.nome), String(x.trades), x.acerto == null ? "–" : f(x.acerto * 100, 0) + "%", sg(x.pnl_sol)]);
    table("dayOri", ["Origem", "Trades", "Acerto", "Resultado"], g(rep.by_origin), "Nenhum trade fechado neste dia.");
    table("dayExit", ["Saída", "Trades", "Acerto", "Resultado"], g(rep.by_exit), "Nenhum trade fechado neste dia.");
    $("dayMenus").innerHTML = (rep.modules || []).map((m) => "<p><b>" + esc(m.menu) + ":</b> " + esc((m.linhas || []).join(" · ")) + "</p>" +
      (m.sugestoes || []).map((s) => '<p style="margin-left:14px"><span class="tag ' + (s.area === "código" ? "pause" : "sim") + '">' + esc(s.area) + "</span> " + esc(s.texto) + (s.base ? ' <span class="muted">(base: ' + s.base + ")</span>" : "") + "</p>").join("")).join("")
      || '<p class="muted">Sem dados dos menus neste dia.</p>';
    $("dayTrH").textContent = "Trades do dia com horário (" + (rep.tz || "UTC") + ")";
    // 0.31.51 (pedido do dono): dia, hora, minuto e segundo da entrada e da saída
    const dhs = (t, hhmm) => t ? new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Berlin" }) : (hhmm || "–");
    const topRows = (L) => (L || []).map((x) => [esc(dhs(x.t_entrada, x.entrada)) + "<small>saiu " + esc(dhs(x.t_saida, x.saida)) + "</small>", pfM(x.mint || "", x.token), esc(x.origem),
      sg(x.pnl_sol) + (x.pnl_pct == null ? "" : "<small>" + (x.pnl_pct > 0 ? "+" : "") + f(x.pnl_pct, 1) + "%</small>"), x.melhor_pct == null ? "–" : (x.melhor_pct > 0 ? "+" : "") + f(x.melhor_pct, 1) + "%", esc(x.motivo || "")]);
    table("dayBest", ["Entrou (dia e hora) → saiu", "Token", "Origem", "Ganhou", "Melhor momento", "Motivo"], topRows(rep.best_trades), "Nenhum ganho neste dia.");
    table("dayWorst", ["Entrou (dia e hora) → saiu", "Token", "Origem", "Perdeu", "Melhor momento", "Motivo"], topRows(rep.worst_trades), "Nenhuma perda neste dia.");
    $("dayMissBox").hidden = !RL;
    if (RL) table("dayMiss", ["Hora", "Token", "O que houve", "Motivo"], (rep.real_misses || []).map((x) => [esc(x.hora), pfM(x.mint || "", x.token), '<span class="tag loss">' + esc(x.acao) + "</span>", esc(x.motivo)]), "Nenhuma falha da real neste dia.");
    table("dayTr", ["Entrada", "Saída", "Duração", "Token", "Origem", "Resultado", "Melhor momento", "Motivo"], (rep.trades_list || []).slice().reverse().map((x) => [esc(x.entrada), esc(x.saida), hms(x.duracao_s),
      pfM(x.mint || "", x.token), esc(x.origem), sg(x.pnl_sol) + (x.pnl_pct == null ? "" : "<small>" + (x.pnl_pct > 0 ? "+" : "") + f(x.pnl_pct, 1) + "%</small>"),
      x.melhor_pct == null ? "–" : (x.melhor_pct > 0 ? "+" : "") + f(x.melhor_pct, 1) + "%", esc(x.motivo || "")]), "Nenhum trade fechado neste dia.");
    const L = r.study || {};
    $("learnCard").hidden = false; $("lrnChartCard").hidden = false;
    $("lrnSub").textContent = (RL ? "carteira REAL · " : "") + (L.days || 0) + " dias guardados · " + (L.positive_days || 0) + " no lucro · todos juntos para estudar o que se repete";
    kpis("lrnK", [["Resultado somado", sg(L.pnl_sol), (L.days || 0) + " dias", "pnl"], ["Dias no lucro", (L.positive_days || 0) + " de " + (L.days || 0), "", "hit"],
      ["Melhor dia", L.best ? esc(L.best.split("-").reverse().join("/")) : "–", "", "tr"], ["Pior dia", L.worst ? esc(L.worst.split("-").reverse().join("/")) : "–", "", "pos"]]);
    let accD = 0;
    $("lrnChartSub").textContent = (RL ? "carteira REAL · " : "carteira fictícia · ") + (L.days || 0) + " dias guardados";
    $("lrnChart").innerHTML = lineChart((L.series || []).map((d) => { accD += d.pnl_sol || 0; return { t: new Date(d.dia + "T23:59:59Z").getTime(), v: accD, label: d.dia.split("-").reverse().join("/") + " " + (d.pnl_sol > 0 ? "+" : "") + s4(d.pnl_sol) + " SOL no dia" }; }));
    $("lrnSug").innerHTML = (L.suggestions || []).map((s) => '<p><span class="tag ' + (s.area === "info" ? "neutral" : s.area === "repetido" ? "loss" : "sim") + '">' + esc(s.area) + "</span> " + esc(s.texto) + (s.base ? ' <span class="muted">(base: ' + s.base + ")</span>" : "") + "</p>").join("");
    table("lrnRec", ["Problema", "Dias", "Último"], (L.recurring || []).map((x) => [esc(x.titulo), String(x.dias), esc((x.ultimo || "").split("-").reverse().join("/"))]), "Nada se repetiu ainda.");
    table("lrnOri", ["Origem", "Dias", "Dias no lucro", "Trades", "Resultado"], (L.origins || []).map((x) => [esc(x.nome), String(x.dias), String(x.dias_positivos), String(x.trades), sg(x.pnl_sol)]), "Sem dias guardados.");
    table("lrnDays", ["Dia", "Resultado", "Trades", "Acerto", "Saldo no fim"], (L.series || []).slice().reverse().map((d) => [esc(d.dia.split("-").reverse().join("/")), sg(d.pnl_sol), String(d.trades || 0), d.acerto == null ? "–" : f(d.acerto * 100, 0) + "%", d.equity_end == null ? "–" : s4(d.equity_end) + " SOL"]), "Sem dias guardados.");
  }
  document.addEventListener("change", (e) => { if (e.target.id === "daySel") { DAY = e.target.value; loadDaily(); } });

  let STP80 = 1, STP_T = null;
  async function loadSteps() {
    clearTimeout(STP_T); STP_T = setTimeout(() => { if (VIEW === "elite") loadSteps(); }, 5000);
    const r = await BB.api("/api/pump/elite/steps?only80=" + STP80);
    if (r.error) return;
    $("stpFol").textContent = (r.following || []).length + " de " + (r.recommended || []).length + " sugeridos sendo copiados agora";
    const act = (x) => {
      const a = x.bot_action || "";
      if (!a) return '<span class="muted">' + (x.kind === "buy" ? "não visto pelo robô" : "–") + "</span>";
      const cls = /não copiou|falhou|robô|não chegou/.test(a) ? "loss" : /aguardando|segurando/.test(a) ? "pause" : "win";
      return '<span class="tag ' + cls + '">' + esc(a) + "</span>" + (x.bot_reason ? "<small>" + esc(x.bot_reason) + "</small>" : "");
    };
    const posi = (p) => !p ? "–" : p.open ? '<span class="tag sim">aberta</span> ' + (p.chg_pct == null ? "" : '<span class="' + (p.chg_pct >= 0 ? "up" : "down") + '">' + (p.chg_pct > 0 ? "+" : "") + f(p.chg_pct, 1) + "%</span>")
      : '<span class="tag neutral">fechada</span> ' + sg(p.pnl_sol) + (p.reason ? "<small>" + esc(p.reason) + "</small>" : "");
    table("stpTbl", ["Quando", "Trader", "Fez", "Token", "SOL", "O robô", "Sua posição"], (r.steps || []).map((x) => [dt(x.t * 1000), esc(x.name),
      x.kind === "buy" ? '<span class="tag buy">Compra</span>' : '<span class="tag loss">Venda</span>', pfM(x.mint, x.symbol), s4(x.sol), act(x), posi(x.position)]),
      STP80 ? "Nenhum passo dos sugeridos (80%+) desde que o servidor ligou." : "Nenhum passo dos maiores traders desde que o servidor ligou.");
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#stpTabs button"); if (!b) return;
    STP80 = +b.dataset.stp80; document.querySelectorAll("#stpTabs button").forEach((x) => x.classList.toggle("on", x === b)); loadSteps();
  });
  async function loadElite() {
    clearTimeout(EL_T); EL_T = setTimeout(() => { if (VIEW === "elite") loadElite(); }, 20000);
    const r = await BB.api("/api/pump/elite");
    if (r.error) { toast(r.error); return; }
    const st = r.study || {}, a = st.all || {}, au = r.auto || {}, per = (au.summary || {}).period || {}, pct = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + f(v, 0) + "%");
    $("elSub").textContent = (r.traders || []).length ? (r.traders || []).length + " maiores traders seguidos · atualiza a cada 20 s" : (r.has_key ? "esperando o ranking da Solana Tracker carregar" : "sem chave da Solana Tracker: cole a sua em Configurações → Chaves (ou o admin configura a do sistema)");
    kpis("elKpis", [["Traders seguidos", String((r.traders || []).length), "os maiores por lucro realizado", "usr"], ["Sinais abertos", String((r.open || []).length), "acompanhados por 60 min", "mon"],
      ["Sinais estudados", String(st.signals || 0), a.n ? "pico médio " + pct(a.avg_peak) + " · fim " + pct(a.avg_60) : "aparecem depois de 60 min", "tr"],
      ["Compra automática", r.settings_on ? "ligada" : "desligada", "resultado: " + s4(per.pnl_sol || 0) + " SOL", "pnl"]]);
    kpis("elResK", [["Lucro acumulado", sg(per.pnl_sol || 0), (per.closed || 0) + " operações fechadas", "pnl"], ["Acerto", per.win_rate == null ? "–" : f(per.win_rate * 100, 0) + "%", "depois das taxas", "hit"],
      ["Fator de lucro", per.profit_factor == null ? "–" : f(per.profit_factor, 2), "ganhos ÷ perdas (acima de 1,3 é bom)", "tr"]]);
    const closed = (au.items || []).filter((x) => !x.open && x.saida_em).sort((x, y) => new Date(x.saida_em) - new Date(y.saida_em));
    let acc = 0;
    $("elChart").innerHTML = lineChart(closed.map((x) => { acc += x.pnl_sol || 0; return { t: new Date(x.saida_em).getTime(), v: acc, label: (x.symbol || "") + " " + (x.pnl_sol > 0 ? "+" : "") + s4(x.pnl_sol) }; }));
    table("elOps", ["Token", "Entrou", "Situação", "Resultado", "Saiu", "Por que saiu", "Duração"], (au.items || []).slice(0, 30).map((x) => [pfM(x.mint, x.symbol), dt(x.entrada_em) + "<small>" + s4(x.sol_in) + " SOL</small>",
      x.open ? '<span class="tag sim">aberta</span>' : '<span class="tag neutral">fechada</span>', x.pnl_sol == null ? (x.pnl_pct == null ? "–" : pct(x.pnl_pct)) : sg(x.pnl_sol) + "<small>" + pct(x.pnl_pct) + "</small>", dt(x.saida_em), esc(x.motivo_saida || ""), hms(x.duration_s)]), "Nenhuma compra automática ainda.");
    const buy = (m, s) => '<button class="btn sm primary" data-buy="' + esc(m) + '" data-sym="' + esc(s || "") + '">Comprar</button>';
    table("elOpen", ["Token", "Sinal", "Traders", "SOL deles", "Desde", "Agora", "Pico", ""], (r.open || []).map((s) => [pfM(s.mint, s.symbol), esc(s.reason), esc((s.names || []).join(", ")), s4(s.sol), dt(s.created_at), pct(s.now_pct), pct(s.peak_pct), buy(s.mint, s.symbol)]), "Nenhum sinal agora.");
    $("elSug").innerHTML = (r.suggestions || []).map((s) => '<p><span class="tag ' + (s.tipo === "info" ? "neutral" : "sim") + '">' + esc(s.tipo) + "</span> " + esc(s.texto) + (s.base ? ' <span class="muted">(base: ' + s.base + ")</span>" : "") + "</p>").join("");
    $("elStSub").textContent = "o que aconteceu em 60 min depois de cada sinal · " + (st.signals || 0) + " sinais encerrados";
    kpis("elStK", [["Chegaram a +30%", a.n ? f(a.hit30_pct, 0) + "%" : "–", "em algum momento dos 60 min", "hit"], ["Caíram 30% ou mais", a.n ? f(a.dump30_pct, 0) + "%" : "–", "em algum momento", "pos"], ["Pico médio", pct(a.avg_peak), "maior alta depois do sinal", "pnl"], ["Fim (60 min)", pct(a.avg_60), "onde estava depois de 1 hora", "tr"]]);
    table("elByN", ["Traders no token", "Sinais", "Chegou a +30%", "Caiu 30%+", "Fim (60 min)"], ["1", "2", "3+"].map((k) => { const b = (st.by_n || {})[k] || {}; return [k, String(b.n || 0), b.n ? f(b.hit30_pct, 0) + "%" : "–", b.n ? f(b.dump30_pct, 0) + "%" : "–", pct(b.avg_60)]; }), "");
    const trs = (st.traders || []).filter((x) => x.n >= 1).slice(0, 12);
    $("elBars").innerHTML = barChart(trs.map((x) => ({ label: x.name, v: x.avg_60 || 0, n: x.n })));
    table("elTrSt", ["Trader", "Sinais", "Chegou a +30%", "Caiu 30%+", "Pico médio", "Fim (60 min)", "Vende em até 5 min"], trs.map((x) => [esc(x.name), String(x.n), f(x.hit30_pct, 0) + "%", f(x.dump30_pct, 0) + "%", pct(x.avg_peak), pct(x.avg_60), f(x.sells_fast_pct, 0) + "%"]), "Sem sinais encerrados ainda.");
    table("elFeed", ["Quando", "Trader", "Operação", "Token", "SOL"], (r.feed || []).slice(0, 40).map((x) => [dt(x.t * 1000), esc(x.name), x.kind === "buy" ? '<span class="tag buy">Compra</span>' : '<span class="tag loss">Venda</span>', pfM(x.mint, x.symbol), s4(x.sol)]), "Ainda nenhuma negociação vista desde que o servidor ligou.");
    EL = r; renderEliteTraders();
    table("elClosed", ["Token", "Traders", "Quando", "5 min", "15 min", "60 min", "Pico", "Queda máx."], (r.closed || []).map((s) => [pfM(s.mint, s.symbol), esc((s.names || []).join(", ")), dt(s.created_at), pct((s.marks || {})["5"]), pct((s.marks || {})["15"]), pct((s.marks || {})["60"]), pct(s.peak_pct), pct(s.low_pct)]), "Nenhum sinal encerrado ainda.");
  }

  // ------------------------------------------------------------------ explorar (/api/pump/explore, 0.28.0)
  let EX = null, EX_TAB = "graduating", EX_T = null;
  const EX_AUTO = { data: null, at: 0, updatedAt: 0, stale: false, busy: false, pending: false, revision: 0, days: 30, error: "", saving: false, values: {} };
  const AUTO_PRESETS = {
    filters: { pump_ex_auto_min_pressure: 60, pump_ex_auto_min_holders: 100, pump_ex_auto_max_risk: 6, pump_ex_auto_curve_min: 60, pump_ex_auto_curve_max: 95, pump_ex_auto_max_chg5: 150 },
    protections: { pump_ar_sol: 0.05, pump_ar_max_open: 3, pump_ar_max_h: 4, pump_ar_daily_loss: 0.25, pump_ar_streak_n: 3, pump_ar_streak_h: 1, pump_ar_stop_pct: 25, pump_ar_tp1_pct: 40, pump_ar_tp1_frac: 50, pump_ar_trail_start: 40, pump_ar_trail_dist: 15, pump_ar_tp_pct: 150, pump_ar_max_hold_min: 30, pump_ar_smart: true }
  };
  const isAutoCfg = (key) => key.startsWith("pump_ex_auto_") || key.startsWith("pump_ar_");
  const autoValue = (key, c) => Object.prototype.hasOwnProperty.call(EX_AUTO.values, key) ? EX_AUTO.values[key] : c[key];
  const autoNum = (v) => typeof v === "number" && Number.isFinite(v) ? v : null;
  const autoDate = (v) => v && Number.isFinite(new Date(v).getTime()) ? esc(dt(v)) : "n/d";
  const autoRate = (v) => autoNum(v) == null ? "n/d" : f(v * 100, 1) + "%";
  const autoFactor = (s) => s.profit_factor_unbounded ? "sem perdas" : autoNum(s.profit_factor) == null ? "n/d" : f(s.profit_factor, 2);
  function autoControls() {
    document.querySelectorAll('[data-view="explorar"] [data-cfg], [data-view="explorar"] [data-toggle], [data-auto-preset], [data-view="explorar"] [data-set]').forEach((el) => {
      const key = el.dataset.cfg || el.dataset.toggle || el.dataset.set;
      if (el.dataset.autoPreset || key && isAutoCfg(key)) el.disabled = EX_AUTO.saving || !D;
    });
  }
  async function loadAutoTrades(force) {
    if (EX_AUTO.busy) { if (force) EX_AUTO.pending = true; return; }
    if (EX_AUTO.saving || !force && Date.now() - EX_AUTO.at < 10000) return;
    EX_AUTO.busy = true; EX_AUTO.at = Date.now();
    const revision = EX_AUTO.revision, days = EX_AUTO.days;
    try {
      const r = await BB.api("/api/pump/auto-trades?origem=explorar&days=" + days);
      if (revision !== EX_AUTO.revision) { EX_AUTO.pending = true; return; }
      if (!r.status || !Array.isArray(r.items)) { EX_AUTO.error = r.error || "resposta do histórico indisponível"; }
      else { EX_AUTO.data = r; EX_AUTO.updatedAt = Date.now(); EX_AUTO.stale = false; EX_AUTO.error = ""; }
    } catch (e) {
      if (revision === EX_AUTO.revision) EX_AUTO.error = e.message || "falha de conexão";
    } finally {
      EX_AUTO.busy = false;
      if (VIEW === "explorar") renderAutoTrades();
      if (EX_AUTO.pending && !EX_AUTO.saving) { EX_AUTO.pending = false; if (VIEW === "explorar") loadAutoTrades(true); }
    }
  }
  function renderAutoState() {
    autoControls();
    const c = cfg(), enabled = !!autoValue("pump_ex_auto_on", c), r = EX_AUTO.data, status = r && r.status || {};
    const stale = !EX_AUTO.updatedAt || Date.now() - EX_AUTO.updatedAt > 30000;
    let text, tone = "muted";
    if (EX_AUTO.saving) text = "Salvando as opções das automáticas…";
    else if (!D) text = "Carregando as entradas automáticas";
    else if (!enabled) text = "Desligada · nenhuma nova entrada automática do Explorar. Posições abertas continuam protegidas.";
    else if (EX_AUTO.error || stale) { text = "Estado aguardando atualização" + (EX_AUTO.error ? ": " + EX_AUTO.error : ".") + " As entradas dependem das travas do motor."; tone = "warn"; }
    else if (status.paused || status.ready === false) {
      text = "Pausada: " + (status.reason || "aguardando o histórico para operar com segurança"); tone = "warn";
      if (autoNum(status.until) != null && status.until * 1000 > Date.now()) text += " · até " + new Date(status.until * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
    } else { text = "Ativa · " + f(autoNum(status.open) || 0, 0) + " posições automáticas abertas · " + f(autoNum(status.entries_h) || 0, 0) + " entradas na última hora."; tone = "up"; }
    $("exAutoState").className = "auto-state " + tone;
    if (EX_AUTO.saving || !D) busy("exAutoState", EX_AUTO.saving ? "Salvando as opções das automáticas" : "Carregando as entradas automáticas");
    else $("exAutoState").textContent = text;
    const real = D && D.real || {};
    $("exAutoMode").textContent = c.pump_auto_real && real.enabled && real.allowed
      ? "A cópia REAL das automáticas já está ligada nos controles existentes. Cada operação REAL aparece identificada; os resumos abaixo usam só o simulado."
      : "Modo simulado para estas entradas. Para considerar dinheiro real, primeiro acompanhe o critério do histórico abaixo.";
    $("exAutoBoost").textContent = c.pump_manual_boost_on ? "Boost ON no token: vende todo o restante em +" + f(autoNum(c.pump_manual_boost_tp) == null ? 80 : c.pump_manual_boost_tp, 0) + "%. Usa a regra de Boost já configurada no botão Comprar." : "A saída por Boost está desligada na configuração existente do botão Comprar.";
  }
  function autoAfter(row, key) {
    if (row.open) return key.replace("m", " min") + ": aguarda a saída";
    const after = row.depois && typeof row.depois === "object" ? row.depois : {};
    if (!Object.prototype.hasOwnProperty.call(after, key)) return key.replace("m", " min") + ": aguardando foto";
    const v = autoNum(after[key]);
    if (v == null) return key.replace("m", " min") + ": foto indisponível";
    return key.replace("m", " min") + ": " + (v > 0 ? "subiu " : v < 0 ? "caiu " : "não variou ") + pc(v) + " depois que saiu";
  }
  function renderAutoTrades() {
    renderAutoState();
    const r = EX_AUTO.data, notice = $("exAutoReadiness");
    document.querySelectorAll("[data-auto-days]").forEach((b) => { b.classList.toggle("on", +b.dataset.autoDays === EX_AUTO.days); b.setAttribute("aria-pressed", String(+b.dataset.autoDays === EX_AUTO.days)); });
    if (!r) {
      $("exAutoKpis").innerHTML = "";
      if (EX_AUTO.error) $("exAutoTradesSub").textContent = "Não foi possível carregar: " + EX_AUTO.error; else busy("exAutoTradesSub", "Carregando as operações automáticas");
      notice.textContent = "Ainda não recomendado para dinheiro real: aguardando o histórico das automáticas."; notice.className = "auto-readiness muted";
      table("exAutoTrades", ["Token", "Entrou", "Situação", "Resultado", "Saiu", "Por que saiu", "Duração", "Melhor momento", "Depois que saiu"], [], EX_AUTO.error ? "Histórico indisponível. A tela tentará atualizar novamente." : BB.loader("Carregando as operações"));
      return;
    }
    const sums = r.summary || {}, day = sums.day || {}, period = sums.period || {}, ready = r.readiness || {};
    const stale = EX_AUTO.error || Date.now() - EX_AUTO.updatedAt > 30000;
    $("exAutoTradesSub").textContent = "Explorar · últimos " + EX_AUTO.days + " dias · resumos só do simulado, após taxas · " + (stale ? "dados desatualizados: " + (EX_AUTO.error || "aguardando atualização") : r.error || "atualizado " + dt(EX_AUTO.updatedAt));
    kpis("exAutoKpis", [["Hoje (UTC) · simulado", sg(autoNum(day.pnl_sol)), f(autoNum(day.closed) || 0, 0) + " operações fechadas", "pnl"],
      ["Período · simulado", sg(autoNum(period.pnl_sol)), f(autoNum(period.closed) || 0, 0) + " operações fechadas em " + EX_AUTO.days + " dias", "tr"],
      ["Acerto · simulado", autoRate(period.win_rate), "hoje: " + autoRate(day.win_rate), "hit"],
      ["Fator de lucro · simulado", autoFactor(period), "hoje: " + autoFactor(day), "pnl"]]);
    const readyText = ready.reason || "Ainda não recomendado para dinheiro real: histórico insuficiente.";
    notice.textContent = (stale || r.error ? "Ainda não recomendado para dinheiro real: histórico incompleto ou desatualizado. " : "") + readyText + " · " + f(autoNum(ready.closed_sim) || 0, 0) + " fechadas em " + f(autoNum(ready.days_sim) || 0, 0) + " dias de simulado · acerto " + autoRate(ready.win_rate) + " · fator " + autoFactor(ready) + (ready.recommended && !stale && !r.error ? ". A execução real continua dependendo dos controles existentes." : "");
    notice.className = "auto-readiness " + (ready.recommended && !stale && !r.error ? "up" : "warn");
    // 0.31.19: ganhou × perdeu, pedido do dono ("mostrar trades que ganhou, que perdeu e a porcentagem")
    // 0.31.39: a pedido do dono os ganhos acima de 20× continuam na conta (na 0.31.38 saíam); só aparecem marcados
    const allClosed = r.items.filter((x) => !x.open && !x.real && autoNum(x.pnl_sol) != null), SUS = allClosed.filter((x) => x.suspeito);
    const closed = allClosed, opn = r.items.filter((x) => x.open && !x.real);
    $("exAutoSus").hidden = true;
    $("exAutoSus").textContent = SUS.length ? SUS.length + (SUS.length === 1 ? " trade suspeito ficou" : " trades suspeitos ficaram") + " FORA da conta (" + SUS.map((x) => String(x.symbol || "") + " " + pc(autoNum(x.pnl_pct))).join(", ") + ", somando " + s4(SUS.reduce((a, x) => a + (autoNum(x.pnl_sol) || 0), 0)) + " SOL). Ganho acima de 20× num token da pump.fun quase sempre é preço lido errado; use o filtro Suspeitos para conferir." : "";
    autoBlocks("exAutoWL", "exAutoEx", closed, opn);
    const FL = EX_AUTO.filt || "all", rows = r.items.filter((x) => FL === "all" || (FL === "sus" ? !!x.suspeito : FL === "open" ? x.open : !x.open && (FL === "win" ? x.pnl_sol > 0 : x.pnl_sol <= 0)));
    document.querySelectorAll("[data-auto-filt]").forEach((b) => b.classList.toggle("on", b.dataset.autoFilt === FL));
    autoTable("exAutoTrades", rows, "Nenhuma operação automática do Explorar neste período. Começa desligada; ao ligar, só entra quando todos os filtros passam.");
    renderRealAuto(r);
  }
  // 0.31.44 (pedido do dono): o mesmo quadro para a carteira REAL — só as linhas reais do Explorar, já com taxas
  function renderRealAuto(r) {
    const R = (r.items || []).filter((x) => x.real), closed = R.filter((x) => !x.open && autoNum(x.pnl_sol) != null), opn = R.filter((x) => x.open);
    const today = new Date().toISOString().slice(0, 10), dayC = closed.filter((x) => x.saida_em && new Date(x.saida_em).toISOString().slice(0, 10) === today);
    const st = (a) => { const g = a.reduce((s, x) => s + Math.max(0, x.pnl_sol), 0), l = -a.reduce((s, x) => s + Math.min(0, x.pnl_sol), 0);
      return { pnl_sol: g - l, closed: a.length, win_rate: a.length ? a.filter((x) => x.pnl_sol > 0).length / a.length : null, profit_factor: l ? g / l : null, profit_factor_unbounded: g > 0 && !l }; };
    const P = st(closed), Dd = st(dayC), real = D && D.real || {};
    $("exRealSub").textContent = "Explorar · últimos " + EX_AUTO.days + " dias · só as compras reais, já com taxas";
    $("exRealNote").textContent = real.enabled ? "Execução real LIGADA: cada compra fictícia do Explorar também é feita na carteira real, com o valor e os limites da carteira real." : "Execução real desligada agora. Aqui aparecem as compras reais já feitas no período.";
    $("exRealNote").className = "auto-readiness " + (real.enabled ? "up" : "muted");
    kpis("exRealKpis", [["Hoje (UTC) · real", sg(Dd.pnl_sol), Dd.closed + " operações fechadas", "pnl"],
      ["Período · real", sg(P.pnl_sol), P.closed + " operações fechadas em " + EX_AUTO.days + " dias", "tr"],
      ["Acerto · real", autoRate(P.win_rate), "hoje: " + autoRate(Dd.win_rate), "hit"],
      ["Fator de lucro · real", autoFactor(P), "hoje: " + autoFactor(Dd), "pnl"]]);
    autoBlocks("exRealWL", "exRealEx", closed, opn);
    const FL = EX_AUTO.rfilt || "all", rows = R.filter((x) => FL === "all" || (FL === "open" ? x.open : !x.open && (FL === "win" ? x.pnl_sol > 0 : x.pnl_sol <= 0)));
    document.querySelectorAll("[data-real-filt]").forEach((b) => b.classList.toggle("on", b.dataset.realFilt === FL));
    autoTable("exRealTrades", rows, "Nenhuma compra real do Explorar neste período.");
  }
  function autoBlocks(wlId, exId, closed, opn) {
    const W = closed.filter((x) => x.pnl_sol > 0), L = closed.filter((x) => x.pnl_sol <= 0);
    const sum = (a, k) => a.reduce((s, x) => s + (autoNum(x[k]) || 0), 0), avg = (a, k) => (a.length ? sum(a, k) / a.length : null);
    const share = (a) => (closed.length ? f(a.length / closed.length * 100, 0) + "% das fechadas" : "sem fechadas");
    const big = (a, best) => a.reduce((m, x) => (m == null || (best ? x.pnl_sol > m.pnl_sol : x.pnl_sol < m.pnl_sol) ? x : m), null);
    const bw = big(W, true), bl = big(L, false);
    kpis(wlId, [["Ganhou", '<span class="up">' + W.length + "</span>", share(W) + " · " + sg(sum(W, "pnl_sol")) + " · média " + pc(avg(W, "pnl_pct")), "hit"],
      ["Perdeu", '<span class="down">' + L.length + "</span>", share(L) + " · " + sg(sum(L, "pnl_sol")) + " · média " + pc(avg(L, "pnl_pct")), "mon"],
      ["Maior ganho", bw ? pc(autoNum(bw.pnl_pct)) : "–", bw ? esc(String(bw.symbol || "")) + " · " + sg(bw.pnl_sol) : "nenhum ainda", "pnl"],
      ["Maior perda", bl ? pc(autoNum(bl.pnl_pct)) : "–", bl ? esc(String(bl.symbol || "")) + " · " + sg(bl.pnl_sol) : "nenhuma ainda", "pnl"],
      ["Abertas agora", String(opn.length), opn.length ? "estimativa " + sg(sum(opn, "pnl_sol")) : "nenhuma", "pos"]]);
    // a conta que o Bruxo faz de cabeça: perda média por erro (e no stop × stop configurado), ganho médio por acerto e
    // ganho esperado por trade (acerto × ganho médio − erro × perda média), com todos os trades
    const stopCfg = autoNum(autoValue("pump_ar_stop_pct", cfg())), ST = L.filter((x) => /^stop de perda/i.test(String(x.motivo_saida || "")));
    const wr = closed.length ? W.length / closed.length : null, aw = avg(W, "pnl_sol"), al = avg(L, "pnl_sol");
    const exp = closed.length ? sum(closed, "pnl_sol") / closed.length : null;
    kpis(exId, [["Ganho médio por acerto", aw == null ? "–" : sg(aw), W.length ? "média " + pc(avg(W, "pnl_pct")) + " · " + W.length + " acertos" : "sem acertos", "hit"],
      ["Perda média por erro", al == null ? "–" : sg(al), L.length ? "média " + pc(avg(L, "pnl_pct")) + " · " + L.length + " erros" : "sem erros", "mon"],
      ["Perda real no stop", ST.length ? pc(avg(ST, "pnl_pct")) : "–", (stopCfg ? "stop configurado −" + f(stopCfg, 0) + "%" : "stop configurado n/d") + (ST.length ? " · " + ST.length + " saídas no stop" + (avg(ST, "pnl_pct") < -(stopCfg || 0) - 5 ? " · escorregou" : "") : ""), "mon"],
      ["Ganho esperado por trade", exp == null ? "–" : sg(exp), wr == null ? "sem fechadas" : (exp > 0 ? "positivo: perde pouco e ganha mais" : "negativo: as perdas pesam mais") + " · " + closed.length + " trades", "pnl"]]);
  }
  function autoTable(id, rows, empty) {
    const PV = { lixo: "loss", fraco: "neutral", "possível": "sim", "chance alta": "win", suspeito: "pause" };
    table(id, ["Token", "Entrou", "Situação", "Resultado", "Saiu", "Por que saiu", "Duração", "Melhor momento", "Depois que saiu"], rows.map((row) => {
      const mint = String(row.mint || ""), partials = Array.isArray(row.partial_exits) ? row.partial_exits.length : 0;
      return [pfM(mint, String(row.symbol || "")) + '<small><span class="tag ' + (row.real ? 'real">REAL' : 'sim">FICTÍCIA') + "</span> · Explorar</small>",
        autoDate(row.entrada_em) + "<small>" + s4(autoNum(row.sol_in)) + " SOL</small>" + '<span class="tag ' + (PV[row.veredito] || "neutral") + '">' + esc(String(row.veredito || "n/d")) + "</span><small>chance: " + (autoNum(row.chance) == null ? "n/d" : f(row.chance, 0) + "%") + "</small>",
        '<span class="tag ' + (row.open ? 'sim">aberta' : 'neutral">fechada') + "</span>" + (partials ? "<small>" + partials + " venda(s) em partes</small>" : ""),
        sg(autoNum(row.pnl_sol)) + "<small>" + pc(autoNum(row.pnl_pct)) + (row.open ? " · estimativa em aberto" : "") + "</small>",
        row.open ? "–" : autoDate(row.saida_em), esc(String(row.motivo_saida || (row.open ? partials ? "venda em partes; restante protegido" : "aguardando saída" : "n/d"))),
        hms(autoNum(row.duration_s)), pc(autoNum(row.best_pct)) + "<small>pior: " + pc(autoNum(row.worst_pct)) + "</small>",
        '<div class="auto-after">' + autoAfter(row, "15m") + "<small>" + autoAfter(row, "60m") + "</small></div>"];
    }), empty);
  }
  // 0.31.66 (pedido do dono): primeiro o que é igual para todas as contas (BASE GERAL), depois quanto disso é da sua conta
  // 0.31.68: só a BASE GERAL (igual em todas as contas); quanto veio desta conta fica na dica do mouse (o dono achou confuso)
  const baseTag = (n, sua) => '<span class="tag pause" title="' + (sua || 0) + ' destas operações aconteceram nesta conta">BASE GERAL ' + (n || 0) + "</span>";
  // 0.31.71 (pedido do dono): Base geral — o cérebro do robô
  // 0.31.85 (pedido do dono): evoluções do cérebro — relatório de cada uma, comparação e voltar para uma anterior
  let EVO = null;
  const pctN = (v) => v == null ? "–" : f(v * 100, 0) + "%";
  async function loadEvo() {
    const r = await BB.api("/api/pump/base/evolucoes"); if (r.error || !$("evoTbl")) return;
    EVO = r; const L = r.evolucoes || [], fz = r.congelado;
    $("evoSub").textContent = L.length + " evoluções · " + (fz ? "sua conta está CONGELADA na E" + fz.numero : "sua conta está no automático (aprende e aplica sozinho)");
    $("evoAuto").hidden = !fz;
    $("evoFreeze").innerHTML = fz ? '<div class="help" style="border-color:var(--warn,#f5a623)"><p><b>Cérebro congelado na E' + fz.numero + "</b> desde " + dt(fz.desde) + ": o Explorar usa as " + (fz.bloqueios || []).length + " faixa(s) bloqueada(s) daquela evolução e o Ajuste automático está parado.</p></div>" : "";
    table("evoTbl", ["Evolução", "Desde", "O que mudou", "Faixas bloqueadas", "Operações", "Acerto", "Lucro", "Por operação", "Barrados", "Real", ""], L.map((x, i) => [
      "<b>E" + x.numero + "</b>" + (i === 0 ? ' <span class="tag win">atual</span>' : "") + (fz && fz.numero === x.numero ? ' <span class="tag neutral">congelado</span>' : ""),
      dt(x.em), '<span class="wrapcell">' + (x.mudancas || []).map(esc).join("<br>") + "</span>", String(x.bloqueios), String(x.operacoes), pctN(x.acerto), sg(x.lucro_sol),
      x.por_trade == null ? "–" : sg(x.por_trade), String(x.sombras), x.real_operacoes ? x.real_operacoes + " · " + sg(x.real_lucro_sol) : "–",
      '<button class="btn sm" data-evorep="' + x.numero + '">Relatório</button> ' + (fz && fz.numero === x.numero ? "" : '<button class="btn sm" data-evoback="' + x.numero + '">Voltar para esta</button>')]),
      "As evoluções começam na próxima foto da Base geral (até 30 min depois de o servidor subir).");
    const opts = L.map((x) => '<option value="' + x.numero + '">E' + x.numero + " · " + dt(x.em) + "</option>").join("");
    const a = $("evoA").value, b = $("evoB").value;
    $("evoA").innerHTML = opts; $("evoB").innerHTML = opts;
    if (a) $("evoA").value = a; else if (L[1]) $("evoA").value = L[1].numero;
    if (b) $("evoB").value = b; else if (L[0]) $("evoB").value = L[0].numero;
  }
  async function showEvo(n) {
    const r = await BB.api("/api/pump/base/evolucoes/" + n); if (r.error) { toast(r.error); return; }
    $("evoOut").innerHTML = "<h3>Relatório da E" + n + "</h3><p class=\"muted\">de " + dt(r.em) + " até " + (r.ate ? dt(r.ate) : "agora") + " · " + f(r.dias || 0, 1) + " dia(s)</p>" +
      '<div class="kpis" id="evoK"></div><div class="grid2"><div><h4>O que aprendeu</h4><div class="tbl-wrap"><table id="evoL" class="daytbl"></table></div></div><div><h4>Por que perdeu</h4><div class="tbl-wrap"><table id="evoM" class="daytbl"></table></div></div></div>' +
      '<h4>Piores operações</h4><div class="tbl-wrap"><table id="evoP" class="daytbl"></table></div><h4>Ajustes automáticos da sua conta no período</h4><div class="tbl-wrap"><table id="evoJ" class="daytbl"></table></div>';
    kpis("evoK", [["Operações", String(r.operacoes), r.ganhos + " ganhos · " + r.perdas + " perdas", "tr"], ["Acerto", pctN(r.acerto), "média " + (r.media_pct == null ? "–" : pc(r.media_pct)), "hit"],
      ["Lucro", sg(r.lucro_sol), r.por_trade == null ? "–" : sg(r.por_trade) + " por operação", "pnl"],
      ["Barrados (sombras)", String(r.sombras), r.sombras ? "média se tivesse entrado " + pc(r.sombras_media_pct) + " · " + r.sombras_ganhariam + " ganhariam" : "–", "mon"],
      ["Real", String(r.real_operacoes), r.real_operacoes ? sg(r.real_lucro_sol) : "sem operações reais", "wallet"]]);
    table("evoL", ["O que mudou"], (r.aprendeu || []).map((x) => ['<span class="wrapcell">' + esc(x) + "</span>"]), "–");
    table("evoM", ["Motivo", "Vezes"], (r.motivos_perda || []).map((x) => ['<span class="wrapcell">' + esc(x.motivo) + "</span>", String(x.n)]), "Nenhuma perda no período.");
    table("evoP", ["Fechou", "Token", "Resultado", "%", "Motivo"], (r.piores || []).map((x) => [dt(x.closed_at), esc(x.symbol || "?"), sg(x.pnl_sol), pc(x.pnl_pct), '<span class="wrapcell">' + esc(x.reason || "") + "</span>"]), "Nenhuma perda no período.");
    table("evoJ", ["Quando", "Ação", "Motivo"], (r.ajustes || []).map((x) => [dt(x.em), esc(x.acao), '<span class="wrapcell">' + esc(x.motivo || "") + "</span>"]), "Nenhum ajuste automático no período.");
    $("evoOut").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function compareEvo() {
    const a = $("evoA").value, b = $("evoB").value; if (!a || !b) return;
    const r = await BB.api("/api/pump/base/evolucoes/comparar?a=" + a + "&b=" + b); if (r.error) { toast(r.error); return; }
    const money = { lucro_sol: 1, por_trade: 1, real_lucro_sol: 1 }, pcts = { acerto: 1 }, pp = { media_pct: 1, sombras_media_pct: 1 };
    const fmt = (k, v) => v == null ? "–" : money[k] ? sg(v) : pcts[k] ? pctN(v) : pp[k] ? pc(v) : f(v, 0);
    const dif = (k, v) => v == null ? "–" : money[k] ? sg(v) : pcts[k] ? (v > 0 ? "+" : "") + f(v * 100, 0) + " pts" : pp[k] ? (v > 0 ? "+" : "") + f(v, 1) + " pts" : (v > 0 ? "+" : "") + f(v, 0);
    // 0.32.24 (pedido do dono): veredito de melhora com %, variação de cada linha e explicação no mouse
    const V = r.veredito || {}, vc = V.resultado === "melhorou" ? "ok" : V.resultado === "piorou" ? "bad" : "";
    const per = (d) => (r[d] || {}).em ? dt(r[d].em) + " até " + ((r[d] || {}).ate ? dt(r[d].ate) : "agora") : "";
    $("evoOut").innerHTML = "<h3>E" + a + " × E" + b + "</h3>" +
      '<div class="decbox ' + vc + '"><b>' + (V.resultado === "melhorou" ? "Melhorou" : V.resultado === "piorou" ? "Piorou" : V.resultado === "igual" ? "Igual" : "Ainda não dá para dizer") +
      (V.pct != null ? " (" + (V.pct > 0 ? "+" : "") + f(V.pct, 1) + "%)" : "") + "</b> — " + esc(V.texto || "") + "</div>" +
      '<p class="muted">E' + a + ": " + esc(per("a")) + " · E" + b + ": " + esc(per("b")) + " · a diferença é E" + b + " − E" + a + ". Passe o mouse no nome de cada linha para ver o que ela significa.</p>" +
      '<div class="tbl-wrap"><table id="evoC" class="daytbl"></table></div>';
    const vd = (x) => x.melhor === "melhorou" ? '<span class="up" title="nesta linha, a E' + b + ' foi melhor">melhorou</span>' : x.melhor === "piorou" ? '<span class="down" title="nesta linha, a E' + b + ' foi pior">piorou</span>' : '<span class="muted" title="esta linha é só informação, ou não mudou">–</span>';
    table("evoC", ["", "E" + a, "E" + b, "Diferença", "Variação", "Melhorou?"], (r.linhas || []).map((x) => ['<span class="hovhelp" title="' + esc(x.explica || "") + '">' + esc(x.nome) + "</span>",
      fmt(x.chave, x.a), fmt(x.chave, x.b), dif(x.chave, x.diferenca), x.pct == null ? "–" : (x.pct > 0 ? "+" : "") + f(x.pct, 1) + "%", vd(x)]), "–");
  }
  // 0.32.41 (pedido do dono): relatório de cada aba a cada 30 min, maiores ganhos/perdas com veredito e o aprendizado
  async function loadTabReports() {
    const r = await BB.api("/api/pump/tab-reports"); if (r.error || !$("trAbas")) return;
    const A = r.agora || {}, VC = { ganhando: "win", "atenção": "pause", perdendo: "loss", "poucos dados": "neutral" };
    const vt = (v) => '<span class="tag ' + (VC[v] || "neutral") + '">' + esc(v) + "</span>";
    const g = (x) => x.n ? x.n + " · " + x.ganhos + "✓ " + x.perdas + "✗ · " + sg(x.pnl_sol) : '<span class="dim">–</span>';
    const T = A.total24 || {};
    kpis("trK", [["Resultado 24 h", sg(T.pnl_sol || 0), (T.n || 0) + " fechadas", "tr"], ["Acerto 24 h", T.acerto == null ? "–" : T.acerto + "%", "todas as abas", "hit"],
      ["Abas perdendo", String((A.abas || []).filter((a) => a.veredito === "perdendo").length), "de " + (A.abas || []).length, "usr"],
      ["Relatórios guardados", String((r.aprendizado || {}).relatorios || 0), r.ultimo ? "último " + dt(r.ultimo.em) : "o 1º sai 2 min depois de subir", "mon"]]);
    table("trAbas", ["Aba", "Últimos 30 min", "24 h", "Acerto", "Veredito", "O que está errado e como corrigir"], (A.abas || []).map((a) => ["<b>" + esc(a.aba) + "</b>", g(a.h30), g(a.h24),
      a.h24.acerto == null ? "–" : a.h24.acerto + "%", vt(a.veredito) + '<small class="wrapcell">' + esc(a.por_que) + "</small>",
      (a.causas || []).slice(0, 3).map((c) => "<b>" + c.n + "×</b> " + esc(c.texto) + " (" + sg(-c.sol) + ')<br><span class="muted small">→ ' + esc(c.corrigir) + "</span>").join("<br>") || '<span class="dim">sem perdas</span>']),
      "Nenhum trade fechado nas últimas 24 h.");
    const big = (L) => L.map((b) => [esc(b.symbol || "") + "<small>" + esc(b.aba) + " · " + dt(b.closed_at) + "</small>", sg(b.pnl_sol) + "<small>" + (b.pnl_pct == null ? "" : pc(b.pnl_pct)) + (b.best_pct == null ? "" : " · pico " + pc(b.best_pct)) + "</small>",
      '<span class="wrapcell">' + esc(b.veredito) + '</span><small class="wrapcell">' + esc(b.reason || "") + "</small>"]);
    table("trWin", ["Maior ganho", "Ganhou", "Veredito"], big(A.maiores_ganhos || []), "Sem ganhos em 24 h.");
    table("trLoss", ["Maior perda", "Perdeu", "Veredito"], big(A.maiores_perdas || []), "Sem perdas em 24 h.");
    $("trStuck").innerHTML = (A.parados || []).length ? '<div class="decbox bad" style="margin-top:10px"><b>Posições com preço parado há mais de 1 h:</b> ' + A.parados.map((p) => esc(p.symbol || "") + " (" + esc(p.aba) + ", " + p.horas + " h)").join(", ") + "</div>" : "";
    const L = r.aprendizado || {};
    table("trLearn", ["Aba", "Relatórios", "Vereditos", "Último", "Causas que se repetem (3+ relatórios)"], (L.abas || []).map((a) => [esc(a.aba), String(a.relatorios),
      Object.entries(a.vereditos || {}).map(([k, v]) => vt(k) + " " + v).join(" "), a.ultimo ? vt(a.ultimo.veredito) + "<small>" + sg(a.ultimo.pnl24) + " em 24 h</small>" : "–",
      (a.repetem || []).map((c) => esc(c.texto) + ' <span class="muted small">→ ' + esc(c.corrigir) + "</span>").join("<br>") || '<span class="dim">nada se repete ainda</span>']), "Ainda sem relatórios guardados.");
    table("trCause", ["Causa das perdas (todas as abas, 7 dias)", "Perdas", "SOL perdido", "Como corrigir"], (L.causas || []).map((c) => [esc(c.texto), String(c.n), sg(-c.sol), esc(c.corrigir)]), "Sem perdas registradas.");
  }

  let BX_T = null;
  async function loadBruxo() {
    const r = await BB.api("/api/pump/bruxo"); if (r.error || !$("bxSig")) return;
    const R = r.resultado || {}, S = r.estudo || {}, B = r.media_inicial || {};
    $("bxSub").textContent = (r.on ? "LIGADA na fictícia" : "desligada (só estudando)") + (r.real ? " · também na REAL" : " · REAL desligada") + " · atualiza a cada 20 s";
    $("bxBase").textContent = "Média inicial dos tokens novos: " + (B.m1 == null ? "aprendendo (" + (B.n1 || 0) + " de 30 tokens)" : f(B.m1, 1) + " SOL/min no 1º min") + (B.m5 == null ? "" : " · " + f(B.m5, 1) + " SOL/min nos 5 primeiros");
    kpis("bxK", [["Sinais em 24 h", String((r.sinais || []).length), "compras de top trader em moeda nova", "mon"], ["Entrou", String((r.sinais || []).filter((s) => s.entrou).length), "nas últimas 24 h", "hit"],
      ["Resultado da aba", sg(R.pnl_sol || 0), (R.n || 0) + " fechadas · acerto " + (R.acerto == null ? "–" : R.acerto + "%"), "tr"], ["Abertas", String((r.abertas || []).length), "fictícia", "usr"]]);
    kpis("bxSt", [["Sinais estudados", String(S.n || 0), "acompanhados 30 min", "mon"], ["Pico típico", S.pico_mediano == null ? "–" : pc(S.pico_mediano), "mediana", "hit"],
      ["Tempo até o pico", S.tempo_ate_pico_mediano_s == null ? "–" : hms(S.tempo_ate_pico_mediano_s), "mediana", "tr"], ["Dobraram", S.dobrou_pct == null ? "–" : S.dobrou_pct + "%", (S.dobrou || 0) + " sinais · em " + (S.tempo_ate_dobrar_mediano_s == null ? "–" : hms(S.tempo_ate_dobrar_mediano_s)), "hit"],
      ["−30% antes de dobrar", S.stop_antes_pct == null ? "–" : S.stop_antes_pct + "%", (S.stop_e_depois_dobrou || 0) + " bateram −30% e DEPOIS dobraram", "usr"], ["Melhor minuto", S.melhor_minuto == null ? "–" : S.melhor_minuto + " min", "maior mediana", "mon"]]);
    $("bxTips").innerHTML = (S.dicas || []).map((d) => '<div class="decbox">' + esc(d) + "</div>").join("") || '<p class="muted small">As dicas aparecem com 15 sinais terminados.</p>';
    table("bxMk", ["Minutos depois", "Sinais", "Mediana", "Subindo"], Object.entries(S.marcas || {}).map(([m, v]) => [m + " min", String(v.n), pc(v.mediana), v.subindo + "%"]), "Ainda sem sinais terminados.");
    table("bxAge", ["Idade na compra", "Sinais", "Dobraram", "−30% antes", "Pico mediano"], Object.entries(S.por_idade || {}).map(([k, v]) => [esc(k), String(v.n), v.dobrou_pct + "%", String(v.stop_antes), pc(v.pico_mediano)]), "Ainda sem sinais terminados.");
    const F = (s) => s.filtros || {};
    table("bxSig", ["Quando", "Token", "Top trader", "Idade", "Ritmo", "Top 10", "Criador", "Entrou?", "Pico em 30 min", "5 / 10 / 25 min"], (r.sinais || []).map((s) => [dt(s.em), pfM(s.mint, s.symbol) +
      '<div style="margin-top:4px"><button class="btn sm primary" data-buy="' + esc(s.mint) + '" data-sym="' + esc(s.symbol || "") + '">Comprar</button></div>',
      esc((s.names || []).join(", ")) + "<small>" + s4(s.sol_traders) + " SOL</small>", s.age_min == null ? "–" : f(s.age_min, 1) + " min",
      F(s).flow == null ? "–" : f(F(s).flow, 1) + "<small>média " + (F(s).flow_base == null ? "–" : f(F(s).flow_base, 1)) + "</small>", F(s).top10 == null ? "–" : f(F(s).top10, 0) + "%",
      F(s).dev_pct == null ? "–" : f(F(s).dev_pct, 1) + "%", s.entrou ? '<span class="tag win">entrou</span>' : '<small class="wrapcell">' + esc(s.motivo || "–") + "</small>",
      s.peak_pct == null ? '<span class="dim">medindo</span>' : pc(s.peak_pct) + "<small>em " + hms(s.peak_s || 0) + "</small>",
      ["5", "10", "25"].map((m) => (s.marks || {})[m] == null ? "–" : pc(s.marks[m])).join(" / ")]), "Nenhum top trader comprou moeda nova nas últimas 24 h.");
    table("bxWhy", ["Motivo", "Sinais"], (r.nao_entrou || []).map((x) => [esc(x.motivo), String(x.n)]), "–");
    // 0.32.59: lançamento sem trader (só estudo)
    const LN = r.lancamento || {}, LS = LN.estudo || {};
    $("lnSub").textContent = (LN.on ? "estudando" : "desligado") + " · tokens no 1º minuto de vida, sem esperar trader · nunca compra";
    kpis("lnK", [["Lançamentos estudados", String(LS.n || 0), (LN.sinais || []).length + " nas últimas 24 h", "mon"], ["Pico típico", LS.pico_mediano == null ? "–" : pc(LS.pico_mediano), "mediana", "hit"],
      ["Dobraram", LS.dobrou_pct == null ? "–" : LS.dobrou_pct + "%", (LS.dobrou || 0) + " · em " + (LS.tempo_ate_dobrar_mediano_s == null ? "–" : hms(LS.tempo_ate_dobrar_mediano_s)), "hit"],
      ["−30% antes de dobrar", LS.stop_antes_pct == null ? "–" : LS.stop_antes_pct + "%", "dos estudados", "usr"]]);
    table("lnT", ["Quando", "Token", "Idade", "Compra do criador", "Pico em 30 min", "5 / 10 / 25 min"], (LN.sinais || []).map((s) => [dt(s.em), pfM(s.mint, s.symbol), s.age_min == null ? "–" : f(s.age_min, 1) + " min",
      (s.filtros || {}).dev_buy == null ? "–" : s4(s.filtros.dev_buy) + " SOL", s.peak_pct == null ? '<span class="dim">medindo</span>' : pc(s.peak_pct) + "<small>em " + hms(s.peak_s || 0) + "</small>",
      ["5", "10", "25"].map((m) => (s.marks || {})[m] == null ? "–" : pc(s.marks[m])).join(" / ")]), "Nenhum lançamento estudado ainda.");
    const rows = (r.abertas || []).map((p) => ["aberta", pfM(p.mint, p.symbol), s4(p.sol_in) + " SOL", pc(p.chg_pct || 0), "–", esc((p.bruxo || {}).names ? p.bruxo.names.join(", ") : "")])
      .concat((r.trades || []).map((t) => [dt(t.closed_at), pfM(t.mint, t.symbol), s4(t.sol_in) + " SOL", sg(t.pnl_sol) + "<small>" + (t.pnl_pct == null ? "" : pc(t.pnl_pct)) + "</small>",
        t.sinal_pico == null ? "–" : pc(t.sinal_pico) + "<small>em " + hms(t.sinal_pico_s || 0) + "</small>", '<small class="wrapcell">' + esc(t.reason || "") + "</small>"]));
    table("bxTr", ["Fechou", "Token", "Investido", "Resultado", "Pico do token (30 min)", "Motivo / trader"], rows, "Nenhuma operação da aba ainda.");
    clearTimeout(BX_T); BX_T = setTimeout(() => { if (VIEW === "bruxo") loadBruxo(); }, 20000);
  }

  async function loadBaseGeral() {
    loadEvo();
    loadTabReports();
    const r = await BB.api("/api/pump/base-geral");
    if (r.error) { $("bgSub").textContent = r.error; return; }
    // 0.32.33 (pedido do dono): aprendizado das posições — entrou/saiu na hora certa
    const PL = r.posicoes || {}, pcv = (v) => v == null ? "–" : v + "%";
    $("plSub").textContent = (PL.n || 0) + " posições fechadas analisadas · últimos 14 dias · todas as contas";
    $("plDicas").innerHTML = (PL.dicas || []).map((d) => '<div class="decbox">' + esc(d) + "</div>").join("");
    const LH = ["", "Posições", "Acerto", "Média", "Saiu cedo", "Saída certa", "Deixou na mesa (média)", "Entrou no topo"];
    const lrow = (x) => [esc(x.nome), String(x.n), pcv(x.acerto), x.media_pct == null ? "–" : pc(x.media_pct), pcv(x.saiu_cedo_pct), pcv(x.saida_certa_pct), x.na_mesa_pct == null ? "–" : "+" + f(x.na_mesa_pct, 0) + "%", x.com_antes ? pcv(x.entrou_no_topo_pct) + "<small>" + x.com_antes + " com dado</small>" : "–"];
    table("plO", LH, (PL.por_origem || []).map(lrow), "Nenhuma posição analisada ainda (começa a contar nesta versão; cada uma leva 1 h depois de fechar).");
    table("plS", LH, (PL.por_saida || []).map(lrow), "–");
    table("plR", ["Fechou", "Token", "Origem", "Saída", "Resultado", "Entrada", "Depois da saída (15/30/60 min)", "Veredito"], (PL.recentes || []).map((d) => [dt(d.closed_at), esc(d.symbol || "?"), esc(d.origem_nome || ""), esc(d.saida_tipo || ""), pc(d.pnl_pct),
      '<span class="wrapcell">' + esc(d.entrada || "") + "</span>", ["15", "30", "60"].map((k) => (d.depois || {})[k] == null ? "–" : pc((d.depois || {})[k], 0)).join(" · "), '<span class="wrapcell">' + esc(d.saida || "") + "</span>"]), "–");
    const m = r.maturidade || {}, s = r.resumo || {}, L = r.learned || {}, G = r.ghosts || {};
    $("bgSub").textContent = (s.contas || 0) + " conta(s) ensinando · " + (s.operacoes || 0) + " compras automáticas fechadas · " + (s.dias || 0) + " dia(s) de histórico";
    kpis("bgK", [["Maturidade da base", f(m.total || 0, 0) + "%", "quanto de dado já tem para decidir", "hit"],
      ["Operações na base", String(s.operacoes || 0), "acerto " + (s.acerto == null ? "–" : f(s.acerto * 100, 0) + "%") + " · " + sg(s.resultado || 0), "tr"],
      ["Resultado médio por trade", s.media_trade == null ? "–" : sg(s.media_trade), "todas as contas, já com taxas", "pnl"],
      ["Faixas", (s.bloqueadas || []).length + " bloqueadas", (s.aprendendo || 0) + " aprendendo · " + Math.max(0, (s.faixas || 0) - (s.bloqueadas || []).length - (s.aprendendo || 0)) + " ok", "mon"],
      ["Melhor regra de saída", esc(s.melhor_regra || "–"), s.melhor_por_trade == null ? "" : sg(s.melhor_por_trade) + " por trade", "pos"]]);
    $("bgParts").innerHTML = (m.partes || []).map((p) => '<div style="margin:10px 0"><div class="row" style="justify-content:space-between"><b>' + esc(p.nome) + "</b><span>" + f(p.pct, 0) + "% <span class=\"muted\">(peso " + f(p.peso * 100, 0) + "%)</span></span></div>" +
      '<div style="height:8px;border-radius:99px;background:var(--line,rgba(255,255,255,.08));margin:6px 0"><div style="height:8px;border-radius:99px;background:var(--up);width:' + Math.min(100, p.pct) + '%"></div></div><small class="muted">' + esc(p.falta) + "</small></div>").join("");
    const F = (r.fotos || []).map((x) => ({ t: new Date(x.em).getTime(), d: x.data || {} }));
    $("bgChM").innerHTML = F.length >= 2 ? lineChart(F.map((x) => ({ t: x.t, v: x.d.maturidade || 0, label: f(x.d.maturidade || 0, 0) + "% de maturidade" }))) : '<p class="muted">O gráfico aparece a partir da 2ª foto (uma a cada 30 min).</p>';
    $("bgChR").innerHTML = F.length >= 2 ? lineChart(F.map((x) => ({ t: x.t, v: x.d.media_trade || 0, label: s4(x.d.media_trade || 0) + " SOL por trade" }))) : '<p class="muted">O gráfico aparece a partir da 2ª foto (uma a cada 30 min).</p>';
    $("bgNext").innerHTML = (r.por_vir || []).length ? (r.por_vir || []).map((x) => "<p>• " + esc(x) + "</p>").join("") : '<p class="muted">Nada perto de mudar agora.</p>';
    const TT = { bloqueou: "loss", liberou: "win", melhor_regra: "sim", inicio: "neutral" };
    const rows = (r.log || []).map((x) => [esc(dt(x.em)), '<span class="tag ' + (TT[x.tipo] || "neutral") + '">' + esc(x.tipo.replace("_", " ")) + "</span>", '<span class="wrapcell" style="max-width:640px">' + esc(x.texto) + "</span>"])
      .concat((r.ajustes || []).map((x) => [esc(dt(x.em)), '<span class="tag pause">ajuste: ' + esc(x.acao) + "</span>", '<span class="wrapcell" style="max-width:640px">' + esc((x.nome ? x.nome + " · " : "") + (x.motivo || "")) + "</span>"]));
    table("bgLog", ["Quando", "O quê", "Detalhe"], rows, "O log começa na primeira foto da base (até 3 min depois de o servidor subir).");
    $("bgLSub").textContent = (L.fechadas || 0) + " operações (compras automáticas + entradas sombra: tokens chance alta barrados, medidos 15 min depois, com 4% de custo) · " + (L.bloqueios || []).length + " faixas bloqueadas · bloqueia com " + (L.min_n || 6) + "+ operações, acerto < 35% e média < −5%";
    // 0.31.84: regra nova (Wilson) só como sombra — mostra o que mudaria, sem bloquear nada
    const Wl = L.wilson || {};
    if ($("bgWil")) $("bgWil").innerHTML = "<p><b>Regra nova em teste (sombra, não bloqueia nada):</b> bloquear só quando o acerto <b>máximo provável</b> da faixa (90% de confiança) fica abaixo de " + f((Wl.max || 0.5) * 100, 0) + "% e a média é ruim. Com poucas operações o acerto real pode estar muito longe do medido (2 ganhos em 6 = entre 12% e 65%). Hoje ela <b>liberaria " + (Wl.liberaria || 0) + "</b> e <b>bloquearia " + (Wl.bloquearia || 0) + "</b> faixa(s) diferente(s) da regra atual. Você decide se troca.</p>";
    const WTAG = { igual: '<span class="muted">igual</span>', liberaria: '<span class="tag win">liberaria</span>', bloquearia: '<span class="tag loss">bloquearia</span>' };
    table("bgL", ["Número da entrada", "Faixa", "Operações", "Delas, sombra", "Acerto", "Acerto provável", "Média", "Resultado", "Rumo à confiança (30)", "Situação", "Regra nova (sombra)"], (L.faixas || []).map((x) => [esc(x.nome), esc(x.faixa), String(x.n), x.n_sombra ? '<span class="tag neutral">SOMBRA ' + x.n_sombra + "</span>" : "–", f(x.acerto * 100, 0) + "%",
      x.acerto_max == null ? "–" : f(x.acerto_min * 100, 0) + "% a " + f(x.acerto_max * 100, 0) + "%",
      (x.media_pct > 0 ? "+" : "") + f(x.media_pct, 1) + "%", sg(x.pnl_sol), f(Math.min(100, x.n / 30 * 100), 0) + "%",
      x.bloqueada ? '<span class="tag loss">bloqueada</span>' : x.n < (L.min_n || 6) ? '<span class="tag neutral">aprendendo (' + x.n + "/" + (L.min_n || 6) + ")</span>" : '<span class="tag win">ok</span>', WTAG[x.wilson] || "–"]), "Ainda sem compras automáticas fechadas.");
    table("bgS", ["Sinal", "Faixa", "Operações", "Delas, sombra", "Acerto", "Média", "Resultado"], (r.sinais || []).map((x) => [esc(x.nome), esc(x.faixa), String(x.n),
      x.n_sombra ? '<span class="tag neutral">SOMBRA ' + x.n_sombra + "</span>" : "–", f(x.acerto * 100, 0) + "%", (x.media_pct > 0 ? "+" : "") + f(x.media_pct, 1) + "%", sg(x.pnl_sol)]),
      "Ainda sem compras ou sombras com estes sinais (começam a ser anotados a partir desta versão).");
    table("bgV", ["Veredito", "Tokens medidos", "Ganhariam", "Acerto", "Média em 15 min", "Pico médio", "Picos de 50%+"], (r.veredito || []).map((x) => [esc(x.veredito), String(x.n), String(x.ganharia),
      f(x.acerto * 100, 0) + "%", pc(x.media_pct), x.pico_medio_pct == null ? "–" : pc(x.pico_medio_pct), String(x.pico_50)]), "As sombras de todos os vereditos começam a ser medidas nesta versão (15 min depois de cada token barrado).");
    if ($("bgXSub")) $("bgXSub").textContent = (r.raiox_n || 0) + " tokens com Raio-X · primeiros compradores, compras em bloco e despejo, cruzados com o que aconteceu";
    table("bgX", ["Sinal do começo do token", "Faixa", "Tokens", "Delas, sombra", "Acerto", "Média"], (r.raiox || []).map((x) => [esc(x.nome), esc(x.faixa), String(x.n),
      x.n_sombra ? '<span class="tag neutral">SOMBRA ' + x.n_sombra + "</span>" : "–", f(x.acerto * 100, 0) + "%", pc(x.media_pct)]), "Ainda sem Raio-X cruzado com resultado.");
    $("bgGSub").textContent = "desde " + (G.since ? dt(G.since) : "–") + " · " + f(r.ghost_days || 0, 1) + " dia(s) · o Ajuste automático precisa de 20+ trades e 2 dias";
    table("bgG", ["Regra de saída", "Trades", "Acerto", "Resultado", "Por trade", "Rumo aos 20 trades"], (G.variants || []).map((v) => [(v.id === G.best ? '<span class="tag win">melhor</span> ' : "") + esc(v.nome), String(v.trades || 0),
      v.win_rate == null ? "–" : f(v.win_rate * 100, 0) + "%", sg(v.pnl_sol || 0), v.trades ? s4(v.pnl_sol / v.trades) : "–", f(Math.min(100, (v.trades || 0) / 20 * 100), 0) + "%"]), "Sem trades nos fantasmas ainda.");
  }
  // 0.31.77 (pedido do dono): os pools do token (PumpSwap, Meteora…) com volume e compras × vendas de 24 h, e a média por
  // negócio — média de centavos com quase só compras é sinal de robô fazendo compras falsas (caso LILY)
  const DEX = { pumpswap: "PumpSwap", pumpfun: "pump.fun", meteora: "Meteora", meteoradbc: "Meteora DBC", raydium: "Raydium", orca: "Orca" };
  function poolsCell(P) {
    if (!P || !P.length) return "";
    return P.map((p) => { const n = (p.buys24 || 0) + (p.sells24 || 0), avg = n ? p.vol24 / n : null;
      // 0.31.93 (pedido do dono: tabela sem rolagem lateral): curto na tela; volume, par e liquidez na dica do mouse
      return '<small title="' + esc(DEX[p.dex] || p.dex || "?") + ": volume $" + f(p.vol24 || 0, 0) + " · " + (p.buys24 || 0) + " compras × " + (p.sells24 || 0) + " vendas" + esc(p.quote ? " · par com " + p.quote : "") + " · liquidez $" + f(p.liq || 0, 0) + '">' + esc(DEX[p.dex] || p.dex || "?") +
        (avg != null ? ' · <span class="' + (avg < 5 && n >= 20 ? "down" : "muted") + '">$' + f(avg, avg < 10 ? 2 : 0) + "/neg.</span>" : "") + "</small>"; }).join("");
  }
  async function loadCopyDiag() {
    const r = await BB.api("/api/pump/copy-diag"); if (r.error || !$("cdK")) return;
    const fl = r.filtros || {};
    $("cdSub").textContent = "desde o último reinício do servidor (" + f(r.desde_reinicio || 0, 1) + " h de dados) · " + (r.seguidos || 0) + " traders copiados · compra mínima do trader: " + f(fl.pump_min_trader_sol || 0, 2) + " SOL · máx. " + (fl.pump_max_open || "–") + " posições";
    kpis("cdK", [["Compras vistas", String(r.vistas || 0), "dos traders copiados", "tr"], ["Copiadas", String(r.copiadas || 0), r.vistas ? f(r.copiadas / r.vistas * 100, 0) + "% das vistas" : "–", "hit"],
      ["Não copiadas", String((r.vistas || 0) - (r.copiadas || 0)), (r.motivos || [])[0] ? "mais comum: " + esc(r.motivos[0].motivo.slice(0, 60)) : "–", "mon"]]);
    table("cdM", ["Por que não copiou", "Vezes"], (r.motivos || []).filter((m) => m.motivo !== "copiou").map((m) => ['<span class="wrapcell">' + esc(m.motivo) + "</span>", String(m.n)]),
      r.vistas ? "Copiou todas as compras vistas." : "Nenhuma compra dos traders copiados chegou ao robô neste período: eles não compraram, ou o monitor não recebeu as transações (confira Monitor ON na Visão geral).");
    table("cdT", ["Trader", "Vistas", "Copiadas", "Motivo principal"], (r.traders || []).map((x) => [pfW(x.wallet), String(x.vistas), String(x.copiadas), '<span class="wrapcell">' + esc(x.principal || "–") + "</span>"]), "–");
  }
  // 0.31.90 (pedido do dono): menu "Logs dos robôs" — os 4 logs num lugar só, guardados para ver depois
  let LOGTAB = "explorar";
  function showLogTab(tab) {
    LOGTAB = tab;
    document.querySelectorAll("#logTabs [data-logtab]").forEach((b) => b.classList.toggle("on", b.dataset.logtab === tab));
    document.querySelectorAll("[data-logpane]").forEach((p) => { p.hidden = p.dataset.logpane !== tab; });
    if (tab === "explorar") loadExLog(); else loadRobotLog(tab);
    loadRobotDays(tab);
  }
  // 0.31.94 (pedido do dono): calls quentes pela blockchain
  let CL_T = null;
  async function loadCalls() {
    const r = await BB.api("/api/pump/calls"); if (r.error || !$("clT")) return;
    const A = r.agora || [], C = r.callers || [], V = r.por_veredito || [];
    const PVc = { "chance alta": "win", "possível": "neutral", "fraco": "pause", "lixo": "loss" };
    kpis("clK", [["Calls na última hora", String(A.length), (r.total || 0) + " guardadas", "mon"], ["Chance alta agora", String(A.filter((x) => x.veredito.verdict === "chance alta").length), "veredito da call", "hit"],
      ["Calls medidas", String(r.medidas || 0), "resultado de quem seguiu em 15 min", "tr"], ["Callers com nota", String(C.filter((x) => x.nota != null).length), "5+ calls medidas", "usr"]]);
    table("clT", ["Token", "Caller", "Veredito", "Há", "Caller pagou", "MC na call", "Desde a entrada", "Pico", "Caller vendeu"], A.map((x) => [pfM(x.mint, x.symbol) +
      '<div style="margin-top:4px"><button class="btn sm primary" data-buy="' + esc(x.mint) + '" data-sym="' + esc(x.symbol || "") + '">Comprar</button></div>',
      pfW(x.wallet) + "<small>" + esc(x.label || "") + " · " + esc(x.fonte || "") + (x.caller != null ? " · nota " + f(x.caller, 0) : "") + "</small>",
      '<span class="tag ' + (PVc[x.veredito.verdict] || "neutral") + '">' + esc(x.veredito.verdict) + " " + x.veredito.chance + '%</span><small class="wrapcell">' + (x.veredito.why || []).map(esc).join(" · ") + "</small>",
      hms(Date.now() / 1000 - x.t), s4(x.sol) + " SOL", x.mcap_sol != null ? f(x.mcap_sol, 0) + " SOL" : "–", x.agora_pct == null ? '<span class="dim">aguardando 1 min</span>' : pc(x.agora_pct),
      x.pico == null ? "–" : pc(x.pico), x.despejo_s != null ? '<span class="down">despejou em ' + hms(x.despejo_s) + "</span>" : x.venda_s != null ? "vendeu parte em " + hms(x.venda_s) : "–"]),
      "Nenhuma call na última hora (as carteiras acompanhadas não compraram).");
    table("clC", ["Caller", "Calls", "Medidas", "Acerto de quem segue", "Média 15 min", "Picos 50%+", "Despeja", "Nota"], C.map((x) => [pfW(x.wallet) + "<small>" + esc(x.label || "") + " · " + esc(x.fonte || "") + "</small>",
      String(x.calls), String(x.medidas), x.acerto == null ? "–" : f(x.acerto * 100, 0) + "%", x.media_pct == null ? "–" : pc(x.media_pct), String(x.picos50 || 0),
      f(x.despejo_pct || 0, 0) + "%", x.nota == null ? '<span class="dim">aprendendo</span>' : "<b>" + f(x.nota, 0) + "</b>"]), "Ainda sem calls.");
    table("clV", ["Veredito na hora da call", "Calls medidas", "Acerto", "Média 15 min"], V.map((x) => [esc(x.veredito), String(x.n), f(x.acerto * 100, 0) + "%", pc(x.media_pct)]), "Ainda sem calls medidas (15 min depois da primeira).");
    clearTimeout(CL_T); CL_T = setTimeout(() => { if (VIEW === "calls") loadCalls(); }, 20000);
  }
  // 0.31.91 (pedido do dono): aprendizado dos logs — resumo de cada dia, sem prazo
  async function loadRobotDays(mod) {
    if (!$("rd_" + mod)) return;
    const r = await BB.api("/api/pump/robot-log/dias?modulo=" + mod); if (r.error) return;
    const T = r.tendencia || {}, tr = document.querySelector('[data-rdtr="' + mod + '"]');
    if (tr) tr.innerHTML = T.dias ? "<p>Em <b>" + T.dias + " dia(s)</b> registrados: " + T.entradas_total + " entrada(s), média de " + f(T.entradas_media_dia, 1) + " por dia, " + T.dias_sem_entrada + " dia(s) sem nenhuma entrada." + (T.motivo_principal ? " O que mais barrou no período todo: <b>" + esc(T.motivo_principal) + "</b>." : "") + "</p>" : "<p>O primeiro resumo aparece no dia seguinte ao primeiro registro (dias fechados, em UTC).</p>";
    table("rd_" + mod, ["Dia", "Registros", "Analisados", mod === "copia" ? "Copiou" : "Entrou", "O que mais barrou", "Outros motivos"], (r.dias || []).map((d) => { const x = d.data || {}, M = x.motivos || [];
      return [esc(String(d.dia || "").split("-").reverse().join("/")), String(x.registros || 0), String(x.analisados || 0) + (x.sem_preco ? "<small>" + x.sem_preco + " sem preço</small>" : ""),
        (x.entradas ? '<b class="up">' + x.entradas + "</b><small>" + (x.nomes || []).slice(0, 5).map(esc).join(", ") + "</small>" : "0"),
        M[0] ? '<span class="wrapcell">' + esc(M[0].motivo) + " (" + f(M[0].pct, 0) + "%)</span>" : "–",
        '<span class="wrapcell">' + M.slice(1, 4).map((m) => esc(m.motivo) + " (" + f(m.pct, 0) + "%)").join("<br>") + "</span>"]; }), "Ainda sem dias fechados.");
  }
  // 0.31.89 (pedido do dono): o mesmo log de análise para os outros robôs (cópia de traders, Base, Maiores traders)
  const RLH = { copia: 24, base: 24, elite: 24, calls: 24 };
  async function loadRobotLog(mod) {
    const box = document.querySelector('[data-rlog="' + mod + '"]'); if (!box) return;
    const r = await BB.api("/api/pump/robot-log?modulo=" + mod + "&horas=" + RLH[mod]); if (r.error) { box.innerHTML = '<p class="muted">' + esc(r.error) + "</p>"; return; }
    const R = r.resumo || {}, B = r.blocos || [], M = R.motivos || [], top = M[0], h = RLH[mod];
    document.querySelectorAll('[data-rlh^="' + mod + ':"]').forEach((b) => b.classList.toggle("on", +b.dataset.rlh.split(":")[1] === h));
    const item = mod === "copia" ? "compras de traders" : mod === "elite" ? "sinais" : "tokens";
    box.innerHTML = '<div class="help"><p><b>Diagnóstico:</b> ' + (R.ligado === false ? "este robô está <b>DESLIGADO</b> nesta conta. " : "") +
      (B.length ? "em " + h + " h o robô analisou " + (R.analisados || 0) + " " + item + " e " + (mod === "copia" ? "copiou " : "comprou ") + (R.entradas || 0) + ((R.nomes || []).length ? " (" + R.nomes.slice(0, 8).map(esc).join(", ") + ")" : "") + ". " +
        (top ? "O que mais barrou: <b>" + esc(top.motivo) + "</b> (" + f(top.pct, 0) + "% das recusas)." : "") : "ainda sem registros (o log começa nesta versão).") + "</p>" +
      ((R.dicas || []).length ? "<p><b>O que dá para ajustar:</b></p><ul>" + R.dicas.map((d) => "<li>" + esc(d) + "</li>").join("") + "</ul>" : "") + "</div>" +
      '<div class="grid2"><div><h4>Por que não ' + (mod === "copia" ? "copiou" : "comprou") + '</h4><div class="tbl-wrap"><table id="rlM_' + mod + '" class="daytbl"></table></div></div>' +
      '<div><h4>A cada 5 min</h4><div class="tbl-wrap tall"><table id="rlB_' + mod + '" class="daytbl"></table></div></div></div>';
    table("rlM_" + mod, ["Motivo", "Vezes", "% das recusas"], M.map((m) => ['<span class="wrapcell">' + esc(m.motivo) + "</span>", String(m.n), f(m.pct, 0) + "%"]), "Nenhuma recusa no período.");
    table("rlB_" + mod, ["Quando", "Analisou", "Entrou", "Principal motivo", "Exemplos"], B.map((b) => [dt(b.em), String(b.analisados || 0), (b.entrou || []).length ? '<b class="up">' + b.entrou.map(esc).join(", ") + "</b>" : "–",
      '<span class="wrapcell">' + esc(b.gargalo || "–") + "</span>", '<span class="wrapcell">' + (b.itens || []).slice(0, 4).map((x) => esc(x.s) + ": " + esc(x.motivo)).join("<br>") + "</span>"]), "Ainda sem registros.");
  }
  // 0.32.64 (pedido do dono): clicar em "Chance alta" abre os tokens, um por linha, com o que aconteceu com cada um
  async function openChance() {
    $("chaMT").textContent = "Chance alta · últimas " + EXLOGH + " h";
    $("chaMS").textContent = "carregando…"; $("chaMB").innerHTML = ""; $("chaM").hidden = false; $("chaMX").focus();
    const r = await BB.api("/api/pump/explore/chance-alta?horas=" + EXLOGH);
    if (r.error) { $("chaMS").textContent = r.error; return; }
    const R = r.resumo || {}, L = r.tokens || [];
    $("chaMS").textContent = R.tokens + " tokens diferentes (o cartão soma as vezes em cada lista de 5 min) · " + R.entrou + " comprados · " + R.barrados + " barrados";
    const res = (x) => !x.op ? "–" : (x.op.aberta ? '<span class="tag">aberta</span> ' : "") + (x.op.pnl_pct == null ? "–" : pc(x.op.pnl_pct)) +
      (x.op.pnl_sol != null ? "<small>" + sg(x.op.pnl_sol) + " SOL</small>" : "") + (x.op.saiu ? '<small class="wrapcell">' + esc(x.op.saiu) + "</small>" : "") + (x.op.hold_s != null ? "<small>" + hms(x.op.hold_s) + "</small>" : "");
    $("chaMB").innerHTML = '<div class="kpis" id="chaK"></div>' +
      (R.motivos && R.motivos.length ? '<p class="muted small" style="margin:8px 0">O que mais barrou: ' + R.motivos.map((m) => esc(m.motivo) + " (" + m.n + ")").join(" · ") + "</p>" : "") +
      '<div class="tbl-wrap"><table id="chaT" class="daytbl"></table></div>' +
      '<p class="muted small">Agora = variação desde que o robô viu o token (preço atual). Pico e 15 min = medição das sombras (token barrado acompanhado 15 min; "ganharia" = acima de +4%, as taxas). Tokens comprados mostram o resultado da operação fictícia.</p>';
    kpis("chaK", [["Tokens", String(R.tokens || 0), (R.entrou || 0) + " comprados · " + (R.barrados || 0) + " barrados", "tr"],
      ["Subiram desde que viu", R.com_preco ? R.subiram_agora + " de " + R.com_preco : "–", R.media_agora_pct == null ? "sem preço" : "média " + pc(R.media_agora_pct), "hit"],
      ["Em 15 min (barrados)", R.medidos_15 ? R.ganhariam_15 + " de " + R.medidos_15 + " ganhariam" : "–", R.media_15_pct == null ? "medindo" : "média " + pc(R.media_15_pct), "mon"],
      ["Pico de +50%", String(R.pico_50 || 0), "nos primeiros 15 min", "pnl"]]);
    table("chaT", ["Visto", "Token", "Listas", "Decisão", "Agora", "Pico / 15 min", "Curva · holders · idade", "Resultado"], L.map((x) => [
      dt(x.first_em) + (x.visto_s ? "<small>por " + hms(x.visto_s) + "</small>" : ""),
      pfM(x.mint, x.symbol) + ' <button class="btn sm primary" data-buy="' + esc(x.mint) + '" data-sym="' + esc(x.symbol || "") + '">Comprar</button>' + (x.graduou ? "<small>graduado</small>" : ""),
      String(x.listas || 0),
      x.entrou ? '<b class="up">comprou</b>' : '<span class="wrapcell">' + esc(x.motivo || "barrado") + "</span>",
      x.agora_pct == null ? "–" : pc(x.agora_pct),
      (x.pico15_pct == null ? "–" : pc(x.pico15_pct)) + " / " + (x.ret15_pct == null ? '<span class="dim">medindo</span>' : pc(x.ret15_pct)),
      [x.curva_pct == null ? null : f(x.curva_pct, 0) + "% curva", x.holders == null ? null : x.holders + " holders", x.idade_min == null ? null : hms(x.idade_min * 60)].filter(Boolean).join(" · ") || "–",
      res(x)]), "Nenhum token com chance alta no período.");
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-chance]")) { e.preventDefault(); openChance(); }
    if (e.target.closest("#chaMX")) $("chaM").hidden = true;
  });
  // 0.31.88 (pedido do dono): log de análise do Explorar — o que o robô fez em cada lista e por que não comprou
  let EXLOGH = 24;
  async function loadExLog() {
    if (!$("exLogC")) return;
    const r = await BB.api("/api/pump/explore/log?horas=" + EXLOGH); if (r.error) { $("exLogSub").textContent = r.error; return; }
    const R = r.resumo || {}, C = r.ciclos || [], M = R.motivos || [];
    document.querySelectorAll("[data-exlogh]").forEach((b) => b.classList.toggle("on", +b.dataset.exlogh === EXLOGH));
    const top = M[0];
    $("exLogDiag").innerHTML = "<p><b>Diagnóstico:</b> " + (!R.ligado ? "a entrada automática do Explorar está <b>DESLIGADA</b> nesta conta. " : "") +
      (R.lista_erro ? "a lista do Explorar está com erro: " + esc(R.lista_erro) + ". " : "") +
      (C.length ? "em " + EXLOGH + " h o robô analisou " + C.length + " listas, " + R.analisados + " tokens (" + R.chance_alta + " com chance alta) e comprou " + (R.entradas || []).length + " token(s)" + ((R.entradas || []).length ? " (" + R.entradas.slice(0, 8).map(esc).join(", ") + ")" : "") + ". " +
        (R.sem_preco ? R.sem_preco + " ficaram sem análise por não ter preço recente (o robô só analisa token com preço lido há até 30 s). " : "") +
        (top ? "O que mais barrou: <b>" + esc(top.motivo) + "</b> (" + f(top.pct, 0) + "% das recusas)." : "")
        : "ainda sem listas registradas (o log começa nesta versão; a 1ª aparece em até 5 min).") + "</p>";
    kpis("exLogK", [["Listas analisadas", String(C.length), "a cada 5 min", "mon"], ["Tokens analisados", String(R.analisados || 0), (R.sem_preco || 0) + " sem preço recente", "tr"],
      ["Chance alta", String(R.chance_alta || 0), '<a href="#" data-chance="1">o veredito liberou · ver os tokens</a>', "hit"], ["Compras", String((R.entradas || []).length), (R.entradas || []).slice(0, 3).map(esc).join(", ") || "nenhuma", "pnl"]]);
    table("exLogM", ["Motivo", "Vezes", "% das recusas"], M.map((m) => ['<span class="wrapcell">' + esc(m.motivo) + "</span>", String(m.n), f(m.pct, 0) + "%"]), "Nenhuma recusa no período.");
    table("exLogF", ["Filtro que barrou", "Tokens medidos", "Ganhariam", "Média em 15 min", "Picos 50%+"], (r.filtros || []).slice(0, 15).map((x) => ['<span class="wrapcell">' + esc(x.motivo) + "</span>", String(x.n) + (x.chance_alta ? "<small>" + x.chance_alta + " chance alta</small>" : ""),
      x.ganhariam + " (" + f(x.acerto * 100, 0) + "%)", pc(x.media_pct), String(x.pico_50)]), "As sombras ainda estão sendo medidas (15 min depois de cada token barrado).");
    table("exLogC", ["Lista de", "Na lista", "Analisados", "Sem preço", "Chance alta", "Comprou", "Principal motivo", "Chance alta barrados"], C.map((c) => [dt(c.em), String(c.na_lista || 0), String(c.analisados || 0), String(c.sem_preco || 0), String(c.chance_alta || 0),
      (c.entrou || []).length ? '<b class="up">' + c.entrou.map(esc).join(", ") + "</b>" : "–", '<span class="wrapcell">' + esc(c.gargalo || "–") + "</span>",
      '<span class="wrapcell">' + (c.chance_alta_barrados || []).slice(0, 6).map((x) => esc(x.symbol || "?") + ": " + esc(x.motivo)).join("<br>") + "</span>"]), "Ainda sem listas registradas.");
  }
  async function loadApiUsage() {
    const r = await BB.api("/api/admin/api-usage"); if (r.error || !$("apiU")) return;
    const bar = (p) => p == null ? '<span class="muted">sem limite publicado</span>' : '<b class="' + (p >= 80 ? "down" : p >= 50 ? "" : "up") + '">' + f(p, 0) + "%</b>";
    table("apiU", ["API", "Chave", "Chamadas no mês", "Limite grátis/mês", "Uso do mês", "No ritmo atual o mês fecha em", "Pico por minuto hoje", "Limite por minuto", "Uso por minuto"],
      (r.apis || []).map((x) => [esc(x.api), esc(x.chave || "–"), f(x.mes, 0), x.limite_mes ? f(x.limite_mes, 0) : "–", bar(x.pct_mes),
        x.limite_mes ? f(x.projecao_mes, 0) + " (" + bar(x.pct_projecao) + ")" : "–", String(x.pico_min), x.limite_min ? f(x.limite_min, 0) : "–", bar(x.pct_min)]),
      "Ainda sem chamadas contadas (o medidor começou nesta versão).");
  }
  function renderFunnel() {
    const F = (EX && EX.funnel) || null; if (!F || !$("exFunK")) return;
    kpis("exFunK", [["Tokens olhados", String(F.vistos), (F.chance_alta || 0) + " com chance alta", "tr"], ["Entraram", String(F.entrou), F.vistos ? f(F.entrou / F.vistos * 100, 0) + "% dos olhados" : "–", "hit"],
      ["Barrados", String(F.barrados), F.barrados_com_preco + " com preço para comparar", "mon"],
      ["Barrados que subiram 50%+", String(F.subiram_50), (F.cairam_30 || 0) + " caíram 30%+ · " + (F.subiram_50 > F.cairam_30 ? "o filtro pode estar barrando coisa boa" : "o filtro está barrando mais coisa ruim"), "pnl"]]);
    table("exFunM", ["Por que foi barrado", "Tokens"], (F.motivos || []).map((m) => ['<span class="wrapcell">' + esc(m.motivo) + "</span>", String(m.n)]), "Nada barrado nas últimas 24 h (ou entrada automática desligada).");
    // 0.31.92 (pedido do dono): botão Comprar ao lado do token barrado (mesmo botão e regras do Comprar da Base)
    // 0.32.22 (pedido do dono: "entrar bem cedo; a maioria subiu mas também teve queda"): pico e pior queda desde que foi visto,
    // e quanto teria dado entrar quando ele subia +10/+20/+30/+50%
    table("exFunCedo", ["Entrar quando subir", "Entradas simuladas", "Acerto", "Média por entrada (já com ~4% de taxas)", "Com 0,05 SOL cada", "Ainda abertas"],
      (F.cedo || []).map((x) => ["+" + x.gatilho + "%", String(x.entradas), x.acerto == null ? "–" : x.acerto + "%", x.media_pct == null ? "–" : pc(x.media_pct), x.soma_005 == null ? "–" : sg(x.soma_005), String(x.abertas)]),
      "Ainda sem barrados medidos (o preço ao vivo deles começou agora).");
    const ast = (b) => b.seguranca ? '<span class="tag loss" title="barrado por segurança: o automático nunca entra">nunca (segurança)</span>' : b.auto_st === "entrou" ? '<span class="tag barr">✓ AUTO entrou</span>'
      : b.auto_st ? '<span class="muted small wrapcell">' + esc(b.auto_st) + "</span>" : '<span class="muted small">abaixo do gatilho</span>';
    table("exFunUp", ["Barrado que subiu", "Agora (desde que foi visto)", "Pico", "Pior queda", "Motivo", "Automático", ""], (F.top_subiram || []).map((b) => [pfM(b.mint, b.symbol), '<span class="up">+' + f(b.chg_pct, 0) + "%</span>", b.hi == null ? "–" : pc(b.hi, 0), b.lo == null ? "–" : pc(b.lo, 0), '<span class="wrapcell">' + esc(b.motivo || "") + "</span>", ast(b),
      '<button class="btn sm primary" data-buy="' + esc(b.mint) + '" data-sym="' + esc(b.symbol || "") + '" data-orig="barrado_btn">Comprar</button>']), "Nenhum barrado subiu 50% ou mais.");
  }
  async function saveAutoCfg(body) {
    if (EX_AUTO.saving) return;
    EX_AUTO.saving = true; EX_AUTO.revision++; EX_AUTO.values = { ...body }; if (D) render(); else renderAutoState();
    try {
      const r = await BB.api("/api/pump/settings", { body: body }), errs = Object.entries(r.errors || {});
      if (r.applied && D) D.cfg = Object.assign({}, D.cfg || {}, r.applied);
      EX_AUTO.values = r.applied || {};
      toast(r.error || (errs.length ? "Não aplicado: " + errs.map((e) => e[0].replace("pump_", "") + " (" + e[1] + ")").join(", ") : "Opções das automáticas salvas."));
      await poll(true);
    } catch (e) { toast("Não foi possível salvar as automáticas: " + (e.message || "falha de conexão")); }
    finally {
      EX_AUTO.saving = false; EX_AUTO.values = {}; EX_AUTO.pending = false; EX_AUTO.revision++;
      if (VIEW === "explorar") { render(); loadAutoTrades(true); }
    }
  }
  async function loadExplore() {
    clearTimeout(EX_T); EX_T = setTimeout(() => { if (VIEW === "explorar") loadExplore(); }, 60000);
    const r = await BB.api("/api/pump/explore");
    if (r.error && !r.lists) { toast(r.error); return; }
    EX = r; renderExplore(); renderFunnel();
  }
  function renderExplore() {
    const r = EX || {};
    $("exSub").textContent = r.error ? "Solana Tracker: " + r.error : r.at ? "atualizado " + dt(r.at * 1000) + " · a cada " + Math.round(r.every_s / 60) + " min · " + r.watching + " tokens em observação para aprender" : "primeira leitura em até 5 min";
    const PV = { lixo: "loss", fraco: "neutral", "possível": "sim", "chance alta": "win" };
    const rows = EX_TAB === "movers" ? r.movers || [] : ((r.lists || {})[EX_TAB] || []);
    const usd = (v) => (v == null ? "–" : "$" + f(v, v >= 1000 ? 0 : 2));
    const pc = (v) => (v == null ? "–" : '<span class="' + (v >= 0 ? "up" : "down") + '">' + (v > 0 ? "+" : "") + f(v, 0) + "%</span>");
    const frs = (x) => !x.fresh ? '<span class="muted">…</span>' : '<span class="' + (x.fresh.pct >= (cfg().pump_ar_fresh_max_pct || 30) ? "down" : "") + '">' + x.fresh.n + " de " + x.fresh.of + "</span>";
    // 0.31.55: o motivo quebra linha (o texto longo do "aprendi com os erros" criava rolagem lateral)
    const aut = (x) => !x.auto ? "–" : (x.auto.ok ? '<span class="tag win">compra</span>' : '<span class="tag neutral">não</span>') + '<small class="wrapcell">' + esc(x.auto.motivo) + "</small>";
    table("exTbl", ["Token", "Veredito", "Automático", "Mcap", "Vol. 24 h", "Curva", "Holders", "Compras × vendas", "5 min / 1 h", "Risco", "Cart. novas", "Traders", "Boost"], rows.map((x) => [pfM(x.mint, x.symbol) +
      '<div style="margin-top:4px"><button class="btn sm primary" data-buy="' + esc(x.mint) + '" data-sym="' + esc(x.symbol || "") + '">Comprar</button></div>',
      '<span class="tag ' + (PV[x.pred.verdict] || "neutral") + '" title="' + esc((x.pred.why || []).join(" · ")) + '">' + esc(x.pred.verdict) + '</span><small class="muted">' + esc((x.pred.why || [])[0] || "") + "</small>", aut(x),
      usd(x.mcap_usd), usd(x.vol24_usd) + poolsCell(x.pools), x.curve_pct == null ? "–" : f(x.curve_pct, 0) + "%", x.holders == null ? "–" : f(x.holders, 0),
      x.pressure == null ? "–" : f(x.buys || 0, 0) + " × " + f(x.sells || 0, 0) + "<small>" + f(x.pressure, 0) + "% compras</small>", pc(x.chg_5m) + "<small>1 h " + pc(x.chg_1h) + "</small>",
      x.risk == null ? "–" : f(x.risk, 0) + "/10", frs(x), x.smart ? '<span class="up">' + x.smart + "</span>" : "0", x.boost && x.boost.active ? '<span class="tag win">ON</span>' : '<span class="tag neutral">OFF</span>']), r.error ? "Sem dados: " + esc(r.error) : "Nada nesta lista agora.");
    const cp = r.compare_auto || {};
    $("cmpSub").textContent = (cp.ganhou || 0) + " ganharam × " + (cp.perdeu || 0) + " perderam · mediana dos números do momento da compra";
    kpis("cmpK", [["Entrou no topo", String(cp.entrou_no_topo || 0), "perdas que nunca passaram de +1%", "mon"],
      ["Stop escorregou (média)", cp.stop_medio_escorregou == null ? "–" : f(cp.stop_medio_escorregou, 1) + " pts", "além do stop configurado", "pnl"],
      ["Por que as perdas saíram", esc(((cp.saidas_perdas || [])[0] || ["–"])[0]), (cp.saidas_perdas || []).map((x) => esc(x[0]) + " " + x[1]).join(" · ") || "sem perdas", "hit"]]);
    const cv = (v) => (v == null ? "–" : f(v, 1));
    table("cmpTbl", ["Número", "Nas que ganharam", "Nas que perderam"], (cp.numeros || []).map((x) => [esc(x.nome), '<span class="up">' + cv(x.ganhou) + "</span>", '<span class="down">' + cv(x.perdeu) + "</span>"]), "Ainda sem operações fechadas.");
    table("cmpStops", ["Token", "Stop", "Saiu em", "Escorregou"], (cp.stops || []).map((x) => [pfM(x.mint || "", x.symbol), "−" + f(x.stop, 0) + "%", pc(x.saiu), f(x.escorregou, 1) + " pts"]), "Nenhuma saída por stop ainda.");
    const ga = r.ghosts_auto || {}, gy = ga.yours || {};
    $("gaSub").textContent = "desde " + (ga.since ? dt(ga.since) : "a próxima compra automática") + " · suas regras: " + (gy.trades || 0) + " trades, " + s4(gy.pnl_sol || 0) + " SOL · o Ajuste automático troca a regra com 20+ trades e 2+ dias";
    table("gaTbl", ["Regra de saída", "Trades", "De onde", "Acerto", "Resultado", "Por trade", "Abertas"], [gy].concat(ga.variants || []).filter((x) => x && x.nome).map((x) => [(x.id === ga.best ? '<span class="tag win">melhor</span> ' : "") + esc(x.nome), String(x.trades || 0),
      x.id === "suas" ? '<span class="tag sim">SUA CONTA</span>' : baseTag(x.trades, x.n_sua),
      x.win_rate == null ? "–" : f(x.win_rate * 100, 0) + "%", sg(x.pnl_sol || 0), x.trades ? s4(x.pnl_sol / x.trades) : "–", String(x.open || 0)]), "Sem dados ainda.");
    const al = r.learned_auto || {};
    $("alSub").textContent = (al.fechadas || 0) + " compras automáticas fechadas (" + (al.fechadas_suas == null ? al.fechadas || 0 : al.fechadas_suas) + " suas + " + ((al.fechadas || 0) - (al.fechadas_suas == null ? al.fechadas || 0 : al.fechadas_suas)) + " de CONHECIMENTO das outras contas) · " + (al.bloqueios || []).length + " faixas bloqueadas · " + (al.morte_rapida || 0) + " perdas em até 60 s depois da compra (entrou no topo)" + (r.learn_on ? "" : " · aprender sozinho DESLIGADO");
    table("alTbl", ["Número da entrada", "Faixa", "Operações", "De onde", "Acerto", "Média", "Resultado", "Situação"], (al.faixas || []).map((x) => [esc(x.nome), esc(x.faixa), String(x.n),
      baseTag(x.n, x.n_sua), f(x.acerto * 100, 0) + "%",
      (x.media_pct > 0 ? "+" : "") + f(x.media_pct, 1) + "%", sg(x.pnl_sol), x.bloqueada ? '<span class="tag loss">bloqueada</span>' : x.n < al.min_n ? '<span class="tag neutral">aprendendo (' + x.n + "/" + al.min_n + ")</span>" : '<span class="tag win">ok</span>']),
      "Ainda sem compras automáticas fechadas para aprender.");
    table("exLs", ["Curva quando apareceu", "Tokens", "Graduaram"], (r.learned || []).map((x) => [esc(x.faixa), String(x.n), f(x.grad_pct, 0) + "%"]), "Ainda aprendendo: cada token espera até 6 h para contar.");
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#exTabs button"); if (!b) return;
    EX_TAB = b.dataset.ex; document.querySelectorAll("#exTabs button").forEach((x) => x.classList.toggle("on", x === b)); renderExplore();
  });

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
    table("bsMine", ["Token", "Situação", "Investiu", "Resultado", "Boost pago", "Quando", ""], (r.mine || []).map((x) => [pfM(x.mint, x.symbol) + (x.real ? ' <span class="tag real">REAL</span>' : ' <span class="tag sim">FICTÍCIA</span>'),
      x.open ? '<span class="tag sim">aberta</span>' : '<span class="tag neutral">fechada</span><small>' + esc(x.reason || "") + "</small>", s4(x.sol_in) + " SOL",
      x.open ? (x.chg_pct == null ? "–" : '<span class="' + (x.chg_pct >= 0 ? "up" : "down") + '">' + (x.chg_pct > 0 ? "+" : "") + f(x.chg_pct, 1) + "%</span>") : sg(x.pnl_sol) + "<small>" + f(x.pnl_pct || 0, 1) + "%</small>",
      bst(x.boost), dt(x.open ? x.opened_at : x.closed_at), x.open ? '<a class="btn sm" href="#posicoes">Ver posição</a>' : ""]), "Você ainda não comprou nada por esta tela.");
    const PV = { lixo: "loss", fraco: "neutral", "possível": "sim", "chance alta": "win", suspeito: "pause" };
    const pred = (p) => !p ? "–" : '<span class="tag ' + (PV[p.verdict] || "neutral") + '" title="' + esc((p.why || []).join(" · ")) + '">' + esc(p.verdict) + "</span>" + (p.chance == null ? "" : "<small>" + f(p.chance, 0) + "% de chance</small>") + '<small class="muted">' + esc((p.why || [])[0] || "") + "</small>";
    const hideT = !!cfg().pump_base_hide_trash;
    const rise = (r.rising || []).filter((x) => !(hideT && x.pred && (x.pred.verdict === "lixo" || x.pred.verdict === "suspeito")));
    const frs2 = (x) => !x.fresh ? '<span class="muted">…</span>' : x.fresh.n + " de " + x.fresh.of;
    table("bsRise", ["Token", "Previsão", "Ganho", "Market cap início → última foto", "Idade", "Criador", "Carteiras novas", "Traders bons", "Boost pago", ""], rise.map((x) => [pfM(x.mint, x.symbol), pred(x.pred), '<span class="up">+' + f(x.gain_pct, 0) + "%</span>",
      f(x.mcap0, 0) + " → " + f(x.mcap, 0) + " SOL", f(x.age_min, 0) + " min · " + x.fotos + "/4 fotos",
      x.creator_stats ? x.creator_stats.tokens + " tokens · " + x.creator_stats.x2 + " subiram · " + x.creator_stats.rugs + " despencaram" : "novo", frs2(x), String(x.smart || 0), bst(x.boost), buy(x.mint, x.symbol)]), hideT && (r.rising || []).length ? "Só lixo agora (desligue \"Esconder lixo\" para ver)." : "Nenhum token em observação subiu ainda.");
    table("bsUp", ["Token", "Rótulo", "Market cap inicial → pico", "Criado", "Boost pago", ""], (r.recent_up || []).map((x) => [pfM(x.mint, x.symbol), '<span class="tag win">' + esc(x.label) + "</span>", f(x.mcap0 || 0, 0) + " → " + (x.label === "graduou" ? "graduou (~410)" : f(x.peak || 0, 0)) + " SOL", dt(x.created_at), bst(x.boost), buy(x.mint, x.symbol)]), "Nenhum ainda.");
    const crt = (L2) => (L2 || []).map((c) => [pfW(c.creator), String(c.tokens), String(c.x2), String(c.rugs), c.bundles ? '<span class="down">' + c.bundles + "</span>" : "0"]);
    table("bsBad", ["Criador", "Tokens", "Subiram", "Despencaram", "Bundle (robô)"], crt(r.bad_creators), "Nenhum criador com 2+ tokens ainda.");
    table("bsGood", ["Criador", "Tokens", "Subiram", "Despencaram", "Bundle (robô)"], crt(r.good_creators), "Nenhum ainda.");
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
    // 0.32.21 (pedido do dono): o Comprar pergunta em qual carteira — só fictícia, só real ou nas duas
    if (t.dataset.buy) {
      const c0 = cfg(), real = !!(D && D.real && D.real.enabled);
      const regras = "Stop −" + c0.pump_manual_stop_pct + "% · alvo " + (c0.pump_manual_tp_pct > 0 ? "+" + c0.pump_manual_tp_pct + "%" : "sem alvo") + (c0.pump_manual_trail_on ? " · stop móvel em +" + c0.pump_manual_trail_start + "% (−" + c0.pump_manual_trail_dist + " pts)" : "") + (c0.pump_manual_boost_on ? " · com Boost ON vende em +" + c0.pump_manual_boost_tp + "%" : "");
      BUY_MINT = t.dataset.buy; BUY_ORIG = t.dataset.orig || "";
      $("buyMT").textContent = "Comprar " + (t.dataset.sym || "este token");
      $("buyMS").textContent = regras;
      $("buyMB").innerHTML = "<p>Carteira fictícia: <b>" + c0.pump_manual_sol + " SOL</b></p><p>Carteira REAL: " + (real ? "<b>até " + c0.pump_real_max_sol + " SOL</b> (execução real ligada)" : '<span class="down">execução real desligada</span>') + "</p>";
      $("buyReal").disabled = $("buyBoth").disabled = !real;
      $("buyM").hidden = false; return;
    }
    if (t.id === "buyMX") { $("buyM").hidden = true; return; }
    if (t.dataset.posdet) { openPosDet(t.dataset.posdet); return; }
    if (t.id === "posMX") { $("posM").hidden = true; POS_ID = null; return; }
    const gp = t.closest && t.closest("[data-gopos]");
    if (gp) {
      e.preventDefault();
      const m = gp.dataset.gopos;
      if ((gp.dataset.gomode === "real") !== realMode()) { MODE = gp.dataset.gomode; try { localStorage.setItem("pf:mode", MODE); } catch (x) { /* */ } }
      location.hash = "#posicoes";
      setTimeout(() => { const a = document.querySelector('section[data-view="posicoes"] [title="' + m + '"]'); const tr = a && a.closest(".pcard, tr");
        if (tr) { tr.scrollIntoView({ behavior: "smooth", block: "center" }); tr.classList.add("flash"); setTimeout(() => tr.classList.remove("flash"), 2500); } else toast("A posição ainda não apareceu; atualiza em alguns segundos."); }, 700);
      return;
    }
    if (t.dataset.buygo) {
      const tg = t.dataset.buygo;
      if (tg !== "sim" && !confirm("Confirmar compra na carteira REAL (dinheiro de verdade)?")) return;
      t.disabled = true;
      const r = await BB.api("/api/pump/manual-buy", { body: { mint: BUY_MINT, target: tg, origem: BUY_ORIG } });
      t.disabled = false; $("buyM").hidden = true;
      toast(r.error ? "Não comprou: " + r.error : "Fictícia: " + r.sim + (r.real ? " · Real: " + r.real : ""));
      await poll(true); markBought(); return;
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
    $("ghSub").textContent = r.since ? "base geral: todas as contas desde " + dt(r.since) + " · cada cópia fictícia também é \"copiada\" por " + (r.variants || []).length + " regras de saída · compare pelo resultado POR TRADE" : "começa a contar na próxima cópia fictícia";
    kpis("ghKpis", [["Suas regras atuais", sg(y.pnl_sol), y.trades + " trades · retorno " + roi(y.roi_pct), "pnl"],
      ["Melhor variante", best ? sg(best.pnl_sol) : "–", best ? esc(best.nome) : "ainda sem trades fechados", "hit"],
      ["Diferença por trade", best && y.trades && best.trades ? sg(best.pnl_sol / best.trades - y.pnl_sol / y.trades) : "–", "melhor variante − suas regras (por trade; a variante soma todas as contas)", "tr"]]);
    const rows = [y].concat(r.variants || []);
    const src = (v) => v.id === "suas" ? '<span class="tag sim">SUA CONTA</span>' : baseTag(v.trades, v.n_sua);
    table("ghTbl", ["Regra de saída", "Trades", "De onde", "Abertas", "Acerto", "Resultado", "Por trade", "Retorno", "Melhor momento (média)"], rows.map((v) => [
      (v.id === "suas" ? "<b>" + esc(v.nome) + "</b>" : esc(v.nome)) + (v.id === r.best ? ' <span class="tag win">melhor</span>' : ""), String(v.trades), src(v), String(v.open), pctW(v.win_rate),
      "<b>" + sg(v.pnl_sol) + "</b>", v.trades ? s4(v.pnl_sol / v.trades) : "–", roi(v.roi_pct), v.avg_best_pct == null ? "–" : "+" + f(v.avg_best_pct, 1) + "%"]), "");
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
  // ---- revisão dos ganhos falsos (0.32.1, pedido do dono): só leitura e marca, nada some dos totais
  async function loadFalseGains(again) {
    $("fgTbl").innerHTML = '<tr><td class="empty">Conferindo na blockchain…</td></tr>';
    const r = await BB.api("/api/pump/false-gains" + (again ? "?check=1&n=" + Date.now() : ""));
    if (r.error) { $("fgTbl").innerHTML = '<tr><td class="empty">' + esc(r.error) + "</td></tr>"; return; }
    $("fgSub").textContent = "todas as contas · conferido " + dt(r.feito) + (r.consultou_precos ? "" : " · sem chave da Solana Tracker: preço de mercado não consultado");
    kpis("fgK", [["Trades de 20×+", String(r.total), "ganho ou melhor momento", "tr"], ["Falsos prováveis", String(r.falsos), "curva em outra moeda ou mercado não subiu", "mon"],
      ["Não confirmados", String(r.nao_confirmados), "sem base para dizer", "hit"], ["Falsos depois da " + esc(r.correcao), String(r.depois_da_correcao), r.depois_da_correcao ? "caso novo: avisar" : "nenhum caso novo", r.depois_da_correcao ? "mon" : "hit"]]);
    const pc = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + f(v, 1) + "%");
    table("fgTbl", ["Fechou", "Conta", "Carteira", "Token", "Registrado", "Melhor", "Veredito", "Verdadeiro", "Versão"], (r.items || []).map((x) => [esc(dt(x.closed_at)), esc(x.conta),
      x.real ? '<span class="tag loss">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>', pfM(x.mint, x.symbol), pc(x.pnl_pct) + "<small>" + sg(x.pnl_sol) + "</small>", pc(x.best_pct),
      '<span class="tag ' + (x.falso === true ? "loss" : x.falso === false ? "win" : "neutral") + '">' + esc(x.veredito) + "</span>",
      pc(x.resultado_verdadeiro_pct) + (x.fonte_verdadeiro ? "<small>" + esc(x.fonte_verdadeiro) + "</small>" : ""), esc(x.versao || "–") + (x.depois_da_correcao ? " <small>depois da correção</small>" : "")]),
      "Nenhum trade de +1.900% ou mais em nenhuma conta.");
    table("fgImp", ["Conta", "Falsos", "Total fictícia", "Só os falsos", "Sem os falsos", "Versões afetadas"], (r.impacto || []).map((m) => [esc(m.conta), String(m.trades), sg(m.total_sol), sg(m.falsos_sol), "<b>" + sg(m.sem_falsos_sol) + "</b>", esc(m.versoes.join(", "))]),
      "Nenhum ganho falso pesando nos totais.");
    $("fgOnde").innerHTML = "<p><b>Onde esses ganhos ainda pesam</b></p>" + (r.onde_pesa || []).map((s) => "<p>" + esc(s) + "</p>").join("");
  }
  document.addEventListener("click", async (e) => {
    if (e.target.closest("#fgRun")) return loadFalseGains(true);
    if (e.target.closest("#fgAi")) return await BB.download("/api/pump/false-gains/ai", "revisao-ganhos-falsos.md");
  });
  // ---- abas de Relatórios (0.31.7): números, PDFs do dia e mudanças da IA
  let REP_TAB = "num";
  async function loadRepTab() {
    $("repNum").hidden = REP_TAB !== "num"; $("repPdf").hidden = REP_TAB !== "pdf"; $("repIa").hidden = REP_TAB !== "ia"; $("repVer").hidden = REP_TAB !== "ver"; $("repFg").hidden = REP_TAB !== "fg";
    if (REP_TAB === "fg") return loadFalseGains(false);
    if (REP_TAB === "ver") {
      const rm = realMode(), r = await BB.api("/api/pump/versions?real=" + (rm ? 1 : 0));
      if (r.error) { $("verTbl").innerHTML = '<tr><td class="empty">' + esc(r.error) + "</td></tr>"; return; }
      const k = rm ? "real" : "sim", VC = { ajudou: "win", piorou: "loss", igual: "neutral", "pouca base": "neutral", "primeira medida": "sim" };
      $("verSub").textContent = "carteira " + (rm ? "REAL" : "fictícia") + " · " + r.versoes.length + " versões · ajudou " + r.ajudou + " · piorou " + r.piorou + " · precisa de " + r.min_trades + " trades por versão para comparar";
      kpis("verK", [["Total fictícia", sg(r.total_sim), "todas as versões", "pnl"], ["Total real", sg(r.total_real), "todas as versões", "pnl"],
        ["Melhor versão", esc(r.melhor || "–"), "maior média por trade", "hit"], ["Pior versão", esc(r.pior || "–"), "menor média por trade", "mon"]]);
      $("verSug").innerHTML = "<p><b>O que ajudou e o que melhorar</b></p>" + (r.sugestoes || []).map((s) => "<p>" + esc(s) + "</p>").join("");
      table("verTbl", ["Versão", "Entrou", "O que mudou", "No ar", "Trades", "Resultado", "Média por trade", "Acerto", "Ajudou?", "Acumulado"],
        r.versoes.slice().reverse().filter((v) => v[k].trades || v === r.versoes[r.versoes.length - 1]).map((v) => [esc(v.versao), esc(dt(v.inicio)), esc(v.titulo), hms(v.horas * 3600), String(v[k].trades),
          sg(v[k].pnl_sol), v[k].media == null ? "–" : sg(v[k].media) + (v.dif_media == null ? "" : "<small>" + (v.dif_media > 0 ? "+" : "") + s4(v.dif_media) + " vs " + esc(v.comparada_com) + "</small>"),
          v[k].acerto == null ? "–" : f(v[k].acerto * 100, 0) + "%", '<span class="tag ' + (VC[v.veredito] || "neutral") + '">' + esc(v.veredito) + "</span>", sg(rm ? v.acumulado_real : v.acumulado_sim)]),
        "Nenhum trade fechado ainda.");
    }
    if (REP_TAB === "pdf") {
      const r = await BB.api("/api/pump/daily");
      if (r.error) { $("pdfTbl").innerHTML = '<tr><td class="empty">' + esc(r.error) + "</td></tr>"; return; }
      const days = [{ dia: r.today, pnl_sol: r.report.pnl_sol, trades: r.report.trades, acerto: r.report.acerto, sugestoes: (r.report.suggestions || []).length, closed: false }]
        .concat((r.days || []).filter((d) => d.dia !== r.today));
      table("pdfTbl", ["Dia", "Resultado", "Trades", "Acerto", "Sugestões", "", ""], days.map((d) => [esc(d.dia.split("-").reverse().join("/")) + (d.dia === r.today ? " <small>em andamento</small>" : ""),
        sg(d.pnl_sol), String(d.trades || 0), d.acerto == null ? "–" : f(d.acerto * 100, 0) + "%", String(d.sugestoes || 0),
        '<button class="btn sm" data-pdfopen="' + esc(d.dia) + '">Abrir PDF</button> <button class="btn sm" data-pdfdl="' + esc(d.dia) + '">Baixar PDF</button>',
        '<button class="btn sm primary" data-aitxt="' + esc(d.dia) + '">Texto para IA</button>']), "Nenhum relatório ainda.");
    }
    if (REP_TAB === "ia") {
      const r = await BB.api("/api/pump/changes");
      const ch = (r.changes || []).filter((c) => !c.erro), tot = ch.reduce((a, c) => a + (c.projecao_sol_dia || 0), 0);
      kpis("iaK", [["Mudanças registradas", String(ch.length), "relatórios das IAs", "tr"], ["Projeção somada", sg(tot) , "SOL por dia, se todas acertarem", "pnl"],
        ["Com resultado medido", String(ch.filter((c) => c.real && c.real.dias_depois).length), "7 dias antes × depois", "hit"]]);
      const pd = (v) => (v == null ? "–" : sg(v) + "<small>/dia</small>");
      table("iaTbl", ["Versão", "Data", "Autor", "Baseado em", "Projeção", "Antes", "Depois", "Diferença real", ""], (r.changes || []).map((c) => c.erro ? [esc(c.nome), "–", "–", '<span class="down">' + esc(c.erro) + "</span>", "–", "–", "–", "–", ""] :
        [esc(c.versao), esc(c.data.split("-").reverse().join("/")), esc(c.autor), esc(c.baseado_em), pd(c.projecao_sol_dia) + "<small>" + esc(c.projecao_texto) + "</small>",
          pd(c.real.antes_sol_dia) + "<small>" + c.real.dias_antes + " dias</small>", pd(c.real.depois_sol_dia) + "<small>" + c.real.dias_depois + " dias</small>", pd(c.real.diferenca_sol_dia),
          '<button class="btn sm" data-chview="' + esc(c.nome) + '">Ver</button> <button class="btn sm" data-chpdf="' + esc(c.nome) + '">PDF</button>']), "Nenhuma mudança registrada ainda.");
    }
  }
  document.addEventListener("click", async (e) => {
    const tb = e.target.closest("#repTabs button");
    if (tb) { REP_TAB = tb.dataset.rt; document.querySelectorAll("#repTabs button").forEach((x) => x.classList.toggle("on", x === tb)); return loadRepTab(); }
    if (e.target.closest("#verAi")) return await BB.download("/api/pump/versions/ai?real=" + (realMode() ? 1 : 0), "resultado-por-versao-para-ia.md");
    const t = e.target, d = t.dataset || {};
    try {
      if (d.pdfopen) return await BB.download("/api/pump/daily/pdf" + dayQ(d.pdfopen), "", true);
      if (d.pdfdl) return await BB.download("/api/pump/daily/pdf" + dayQ(d.pdfdl), "relatorio-" + d.pdfdl + (realMode() ? "-real" : "") + ".pdf");
      if (d.aitxt) return await BB.download("/api/pump/daily/ai" + dayQ(d.aitxt), "relatorio-" + d.aitxt + (realMode() ? "-real" : "") + "-para-ia.md");
      if (d.chpdf) return await BB.download("/api/pump/changes/" + encodeURIComponent(d.chpdf) + "?pdf=1", "mudanca-" + d.chpdf + ".pdf");
      if (d.chview) { const c = await BB.api("/api/pump/changes/" + encodeURIComponent(d.chview)); $("iaTxt").innerHTML = "<p><b>" + esc(c.versao + " · " + c.data) + "</b></p>" + esc(c.texto || c.error || "").split("\n").map((l) => "<p>" + l + "</p>").join(""); }
    } catch (err) { toast("Não abriu: " + err.message); }
  });
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
    const tt = r.traders_today || {}, w = tt.winners || {}, l = tt.losers || {}, mm = hms;
    kpis("apKpis", [["Tokens fechados", String(tt.tokens_closed || 0), (tt.watched || 0) + " carteiras acompanhadas", "tr"],
      ["Com lucro", String(w.n || 0), "seguraram " + mm(w.hold_med_s) + " (mediana)", "hit"],
      ["Market cap na entrada (acertos)", w.mcap_in_med == null ? "–" : f(w.mcap_in_med, 0) + "<small> SOL</small>", "erros: " + (l.mcap_in_med == null ? "–" : f(l.mcap_in_med, 0) + " SOL"), "pnl"]]);
    $("apTtSub").textContent = "carteiras que você copia + top do ranking, vistas pelo monitor · " + (tt.traders || []).length + " negociaram";
    table("apTr", ["Trader", "Tokens", "Acerto", "Resultado dele", "Segurou (mediana)", "Market cap na entrada", "Saldo"], (tt.traders || []).map((x) => [pfW(x.wallet, x) + (x.followed ? ' <span class="tag win">copiando</span>' : ""), String(x.closed),
      f(x.win_rate * 100, 0) + "%", sg(x.pnl_sol), mm(x.hold_med_s), x.mcap_in_med == null ? "–" : f(x.mcap_in_med, 0) + " SOL", x.wallet_usd == null ? "–" : "$" + f(x.wallet_usd, 0)]), "Sem tokens fechados pelos traders nas últimas 24 h.");
    const off = -new Date().getTimezoneOffset() / 60, hrs = (tt.trades_by_hour_utc || []).map((n, h) => ({ h: (h + off + 24) % 24, n }));
    const top = hrs.filter((x) => x.n).sort((a, b) => b.n - a.n).slice(0, 8);
    table("apHr", ["Hora", "Negociações"], top.map((x) => [String(x.h).padStart(2, "0") + "h", String(x.n)]), "Sem negociações registradas.");
    table("apRich", ["Carteira", "Saldo"], (tt.richest || []).map((x) => [pfW(x.wallet, x), "$" + f(x.usd, 0)]), "Saldo das carteiras ainda não consultado.");
    $("apLim").innerHTML = (r.limits || []).map((s) => "<p>" + esc(s) + "</p>").join("");
    const hi = r.history || {};
    $("apHiSub").textContent = r.history_error ? r.history_error : hi.days ? hi.days + " dias guardados desde " + esc(String(hi.first).split("-").reverse().join("/")) + " · consistência vale mais que um dia bom" : "o primeiro dia é guardado em até 30 min";
    table("apHiTr", ["Trader", "Dias com lucro", "Resultado somado", "Tokens"], (hi.traders || []).map((x) => [pfW(x.wallet, x) + (x.followed ? ' <span class="tag win">copiando</span>' : ""), x.days_positive + " de " + x.days_seen, sg(x.pnl_sol), String(x.tokens)]), "Ainda sem dias guardados.");
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
    $("tkCard").hidden = false; busy("tkT", "Carregando o token"); $("tkM").textContent = m; $("tkB").innerHTML = "";
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
      ((r.traders_in || []).length ? "<h3>Seus traders neste token</h3>" + r.traders_in.map((x) => "<div>" + pfW(x.wallet, x) + " · investiu " + s4(x.invested_sol) + " SOL · " + (x.chg_pct == null ? "–" : f(x.chg_pct, 1) + "%") + "</div>").join("") : "") +
      ((r.my_trades || []).length ? "<h3>Suas operações neste token</h3>" + r.my_trades.map((t) => "<div>" + dt(t.closed_at) + " · " + sg(t.pnl_sol) + " · " + esc(t.reason || "") + "</div>").join("") : "") +
      (ME && ME.role === "admin" ? '<h3>Raio-X das negociações</h3><p class="muted small">Primeiras 500 negociações: compras × vendas por minuto, quem comprou primeiro e quanto segurou, e o despejo. Gasta 1 consulta da Solana Tracker (guardado por 6 h).</p><button class="btn sm" data-xray="' + esc(m) + '">Fazer Raio-X</button><div id="xrOut"></div>' : "");
  }
  // 0.31.86 (pedido do dono): Raio-X do token — gráfico de compras × vendas por minuto, primeiros compradores e despejo
  async function showXray(m, btn) {
    if (btn) btn.disabled = true;
    const r = await BB.api("/api/pump/raiox/" + encodeURIComponent(m)); if (btn) btn.disabled = false;
    const out = $("xrOut"); if (!out) return;
    if (r.error) { out.innerHTML = '<p class="muted">' + esc(r.error) + "</p>"; return; }
    if (!r.n) { out.innerHTML = '<p class="muted">Nenhuma negociação encontrada.</p>'; return; }
    const M = (r.minutos || []).slice(0, 90), mx = Math.max(0.0001, ...M.map((b) => Math.max(b.sol_compra, b.sol_venda)));
    const W = 600, H = 160, bw = W / Math.max(M.length, 1);
    const bars = M.map((b, i) => '<rect x="' + (i * bw + 1).toFixed(1) + '" y="' + (80 - b.sol_compra / mx * 76).toFixed(1) + '" width="' + Math.max(1, bw - 2).toFixed(1) + '" height="' + (b.sol_compra / mx * 76).toFixed(1) + '" rx="2" fill="var(--up,#22c55e)"><title>min ' + b.min + ": " + b.compras + " compras, " + f(b.sol_compra, 2) + " SOL</title></rect>" +
      '<rect x="' + (i * bw + 1).toFixed(1) + '" y="82" width="' + Math.max(1, bw - 2).toFixed(1) + '" height="' + (b.sol_venda / mx * 76).toFixed(1) + '" rx="2" fill="var(--down,#ef4444)"><title>min ' + b.min + ": " + b.vendas + " vendas, " + f(b.sol_venda, 2) + " SOL</title></rect>").join("");
    const s = r.sinais || {}, d = r.despejo || {};
    out.innerHTML = '<p class="small"><span class="up">▮ compras (SOL)</span> · <span class="down">▮ vendas (SOL)</span> · cada barra = 1 minuto desde a 1ª negociação · ' + r.n + " negociações" + (r.completo ? "" : " (as primeiras 500)") + "</p>" +
      '<svg viewBox="0 0 ' + W + " " + H + '" style="width:100%;height:auto;display:block" role="img" aria-label="compras e vendas por minuto"><line x1="0" y1="81" x2="' + W + '" y2="81" stroke="var(--line2,#333)"/>' + bars + "</svg>" +
      '<div class="cfgs">' + [["Primeiros que venderam em até 5 min", s.vendas_cedo_pct == null ? "–" : f(s.vendas_cedo_pct, 0) + "%"], ["Compras em bloco no 1º segundo", String(s.bloco_n ?? "–")],
        ["Vendas nos 5 maiores vendedores", s.top5_venda_pct == null ? "–" : f(s.top5_venda_pct, 0) + "%"], ["Primeiros seguraram (mediana)", s.segurou_mediana_min == null ? "–" : f(s.segurou_mediana_min, 1) + " min"],
        ["Maior despejo", "minuto " + d.minuto + ": " + f(d.sol_venda || 0, 2) + " SOL vendidos × " + f(d.sol_compra || 0, 2) + " comprados · " + (d.carteiras || 0) + " carteiras (" + (d.primeiros_no_despejo || 0) + " dos primeiros)"]]
        .map((x) => '<div><span class="k">' + x[0] + '</span><span class="v">' + esc(x[1]) + "</span></div>").join("") + "</div>" +
      '<h4>Primeiros compradores</h4><div class="tbl-wrap"><table id="xrF" class="daytbl"></table></div>';
    table("xrF", ["Carteira", "Entrou", "SOL", "Vendeu", "Segurou", "Resultado", "Perfil"], (r.primeiros || []).map((x) => [pfW(x.wallet), "+" + hms(x.entrou_s), f(x.sol, 3), f(x.vendeu_pct, 0) + "%",
      hms(x.segurou_s), sg(x.lucro_sol), esc(x.perfil)]), "–");
  }
  document.addEventListener("click", (e) => {
    const xb = e.target.closest("[data-xray]"); if (xb) { e.preventDefault(); showXray(xb.dataset.xray, xb); return; }
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
  // 0.31.96 (pedido do dono): compras das carteiras em estudo e ondas guardadas (das calls no banco)
  function renderRadarCalls(r) {
    if (!$("rdBuys") || !r) return;
    const B = r.compras || [], W = r.ondas_guardadas || [], L = r.lista || [];
    // 0.31.97 (pedido do dono): a lista das carteiras, não só o número
    const cp = (x, k) => String(((x.compras || {})[k]) || 0);
    if ($("rdList")) table("rdList", ["Carteira", "Apelido", "Na lista desde", "Online", "Compras 24 h", "48 h", "3 dias", "7 dias", "Última compra"], L.map((x) => [pfW(x.wallet), esc(x.apelido || "–"),
      x.desde ? dt(x.desde) : "–", x.online == null ? "–" : x.online ? '<span class="tag win">online</span>' : '<span class="tag neutral">offline</span>', cp(x, "24h"), cp(x, "48h"), cp(x, "3d"), cp(x, "7d"),
      x.ultima ? pfM(x.ultima.mint, x.ultima.symbol) + "<small>há " + hms(Date.now() / 1000 - x.ultima.t) + (x.ultima.sol != null ? " · " + s4(x.ultima.sol) + " SOL" : "") + "</small>" : '<span class="dim">nenhuma em 7 dias</span>']),
      "Sua lista está vazia: adicione carteiras em Carteiras em estudo.");
    $("rdBuysSub").textContent = B.length + " compras de " + (r.carteiras_n || 0) + " carteiras nas últimas 24 h · guardadas no banco";
    table("rdBuys", ["Quando", "Carteira", "Token", "Pagou", "MC na call", "Desde a entrada", "Pico", "Vendeu"], B.map((x) => [dt(new Date(x.t * 1000).toISOString()),
      pfW(x.wallet) + "<small>" + esc(x.nome || "") + "</small>", pfM(x.mint, x.symbol) + '<div style="margin-top:4px"><button class="btn sm primary" data-buy="' + esc(x.mint) + '" data-sym="' + esc(x.symbol || "") + '">Comprar</button></div>',
      s4(x.sol) + " SOL", x.mcap_sol != null ? f(x.mcap_sol, 0) + " SOL" : "–", x.resultado != null ? pc(x.resultado) + "<small>15 min, com custo</small>" : '<span class="dim">medindo</span>',
      x.pico == null ? "–" : pc(x.pico), x.despejo_s != null ? '<span class="down">despejou em ' + hms(x.despejo_s) + "</span>" : x.venda_s != null ? "vendeu parte" : "–"]),
      (r.carteiras_n ? "Nenhuma das suas carteiras comprou nas últimas 24 h (desde que as calls começaram a ser guardadas, na 0.31.94)." : "Sua lista está vazia: adicione carteiras em Carteiras em estudo."));
    table("rdWaves", ["Token", "Carteiras", "Em quanto tempo", "SOL somado", "Quem"], W.map((w) => [pfM(w.mint, w.symbol), String(w.carteiras.length),
      hms(w.fim - w.inicio) + "<small>" + dt(new Date(w.inicio * 1000).toISOString()) + "</small>", s4(w.sol),
      '<span class="wrapcell">' + w.carteiras.map((c) => esc(c.label || c.wallet.slice(0, 4)) + (c.despejou ? ' <span class="down">(despejou)</span>' : "")).join(", ") + "</span>"]),
      "Nenhuma onda nas últimas 24 h (2+ carteiras suas no mesmo token dentro da janela).");
  }
  function renderRadar() {
    const r = RADAR.data; radarControls(); if (!r) return;
    renderRadarCalls(r);
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
      pfW(x.wallet, x) + (x.apelido ? " <b>" + esc(x.apelido) + "</b>" : ""), "<b>" + sg(x.pnl_30d) + "</b><small>" + x.n_30d + " tokens</small>", sg(x.per_day_7d),
      x.win_rate == null ? "–" : f(x.win_rate * 100, 0) + "%", x.fast_pct == null ? "–" : f(x.fast_pct * 100, 0) + "%", '<span class="tag ' + (VD[x.verdict] || "neutral") + '">' + esc(x.verdict) + "</span>",
      x.followed ? '<span class="tag win">copiando</span>' : '<button class="btn sm" data-stc="' + esc(x.wallet) + '">Copiar</button>']), "Ainda sem tokens fechados suficientes para calcular.");
    $("stSub").textContent = "o sistema acompanha e aprende com a carteira, sem copiar · " + (r.wallets || []).length + " de " + r.limit +
      (r.key ? " · histórico pela Solana Tracker" : " · sem chave da Solana Tracker: só o que o monitor ver daqui em diante");
    const mm = hms;
    table("stList", ["Carteira", "Ganho/hora (24 h)", "Ganho/dia (média 7 d)", "Acerto", "Segura (mediana)", "Tokens fechados", ...FACTS_H, ""], (r.wallets || []).map((x) => { const s = x.summary || {};
      return [pfW(x.wallet, x) + (x.apelido ? " <b>" + esc(x.apelido) + "</b>" : "") + (x.followed ? ' <span class="tag win">copiando</span>' : ""), mny(s.per_hour, s.unit), mny(s.per_day_7d, s.unit),
        s.win_rate == null ? "–" : f(s.win_rate * 100, 0) + "%", mm(s.hold_med_s), s.closed == null ? "–" : String(s.closed), ...factsCells(x.facts),
        '<button class="btn sm" data-stp="' + esc(x.wallet) + '">Perfil</button> <button class="btn sm" data-stai="' + esc(x.wallet) + '" title="Relatório desta carteira com o prompt para o ChatGPT">Relatório + prompt</button> <button class="btn sm" data-sts="' + esc(x.wallet) + '">Compartilhar</button> ' + (x.followed ? "" : '<button class="btn sm" data-stc="' + esc(x.wallet) + '">Copiar</button> ') + '<button class="btn sm" data-str="' + esc(x.wallet) + '">Remover</button>']; }),
      "Nenhuma carteira em estudo. Cole um endereço acima.");
    const sa = r.auto || {}, sc = sa.counts || {}, nAuto = (r.wallets || []).filter((x) => String(x.apelido || "").startsWith(sa.tag || "auto · ")).length;
    $("saSub").textContent = (sa.on ? "LIGADO" : "DESLIGADO") + " · " + nAuto + " de " + (sa.max || 0) + " carteiras automáticas no estudo · última volta " + (sa.last_run ? dt(sa.last_run) : "ainda não rodou (roda a cada 30 min)");
    kpis("saK", [["Adicionadas", String(sc.adicionou || 0), "pela IA, desde o início", "pos"], ["Aprovadas", String(sc.aprovou || 0), "compensa copiar", "hit"], ["Descartadas", String(sc.descartou || 0), "não compensa ou paradas", "mon"]]);
    // 0.32.15 (pedido do dono): clicar no cartão abre a lista das carteiras com a nota
    ["adicionou", "aprovou", "descartou"].forEach((a, i) => { const k = $("saK").children[i]; if (k) { k.dataset.saact = a; k.classList.add("clickable"); k.title = "Clique para ver as carteiras"; } });
    const AC = { adicionou: "neutral", aprovou: "win", descartou: "loss", parou_de_copiar: "loss", sugere_parar: "pause", copiou_lucro: "win" };
    table("saRates", ["Característica", "Aprovadas", "Julgadas", "Chance de compensar (aprendida)"], (sa.rates || []).map((x) => ['<button class="linkbtn" data-sarate="' + esc(x.valor) + '" title="Ver as carteiras com esta característica">' + esc(x.valor) + " ›</button>", String(x.aprovadas), String(x.julgadas), f(x.taxa * 100, 0) + "%"]),
      "Ainda sem carteiras julgadas: a primeira decisão sai quando uma carteira tiver 5 tokens fechados.");
    // 0.32.12 (pedido do dono: "está muito espremida"): uma linha por decisão; o resto abre em "Ver tudo"
    // 0.32.14 (pedido do dono): ordem pela nota (maior primeiro; sem nota no fim, depois a mais recente)
    SA_LOG = (sa.log || []).slice().sort((a, b) => ((b.digest || {}).score ?? -1) - ((a.digest || {}).score ?? -1) || String(b.em).localeCompare(String(a.em)));
    table("saLog", ["Quando", "Carteira", "Decisão", "Nota", "Resumo", "Última operação", "Saldo (US$)", ""], SA_LOG.map((x, i) => { const d = x.digest || {}, fx = x.facts || {};
      const copying = copyState(x.wallet);
      return [dt(x.em), pfW(x.wallet, x), '<span class="tag ' + (AC[x.acao] || "neutral") + '">' + esc(x.acao) + "</span>", scoreTag(d),
        x.digest ? '<span class="nowrap">' + (d.n_acertos || 0) + " acertos · " + (d.n_erros || 0) + " erros" + (d.pump_pct == null ? "" : " · " + d.pump_pct + "% pump.fun") + "</span>" : '<span class="muted">sem histórico ainda</span>',
        d.ultima_op ? hms(Math.max(0, Date.now() / 1000 - d.ultima_op)) + " atrás" : "–", fx.usd == null ? "–" : "$" + f(fx.usd, 0),
        '<span class="nowrap"><button class="btn sm" data-sadet="' + i + '">Ver tudo</button>' + (x.acao === "aprovou" && x.no_estudo ? (copying ? " " + copyTag(copying) : ' <button class="btn sm" data-stc="' + esc(x.wallet) + '" title="Aprovou = continua no estudo. Este botão passa a copiar.">Copiar</button>') : "") + "</span>"]; }),
      "Nenhuma decisão ainda. Clique em Rodar agora ou espere a próxima volta.");
    const mi = r.mine || {}, tt = mi.total || {}, ts = tt.sim || {}, tr = tt.real || {};
    const roi = (v) => (v == null ? "–" : '<span class="' + (v >= 0 ? "up" : "down") + '">' + (v > 0 ? "+" : "") + f(v, 1) + "%</span>");
    kpis("stMineK", [["Fictícia: seu resultado", sg(ts.pnl_sol), (ts.trades || 0) + " trades · acerto " + (ts.win_rate == null ? "–" : f(ts.win_rate * 100, 0) + "%"), "pnl"],
      ["Fictícia: retorno", roi(ts.roi_pct), "sobre o valor investido", "tr"],
      ["Real: seu resultado", sg(tr.pnl_sol), (tr.trades || 0) + " trades" + (tr.trades ? " · retorno " + (tr.roi_pct == null ? "–" : f(tr.roi_pct, 1) + "%") : ""), "wallet"]]);
    const dg = (d) => !d ? "–" : d.buys_seen + " compras vistas · " + d.copied + " copiadas" + (d.top_skips && d.top_skips.length ? "<small>não copiou: " + d.top_skips.map((s) => esc(s.reason) + " (" + s.n + ")").join(" · ") + "</small>" : "");
    // 0.32.17 (pedido do dono): fictícia e real em tabelas separadas; a real diz se copia ou se está "só fictícia (teste)"
    const mrow = (x) => [pfW(x.wallet, x) + (x.apelido ? " <b>" + esc(x.apelido) + "</b>" : "") + (x.followed ? ' <span class="tag win">copiando</span>' : ""),
      dt(x.since), String(x.trades), x.win_rate == null ? "–" : f(x.win_rate * 100, 0) + "%",
      "<b>" + sg(x.pnl_sol) + "</b><small>investiu " + s4(x.invested_sol) + " SOL</small>", roi(x.roi_pct),
      x.open ? x.open + " · " + s4(x.open_sol) + " SOL" + (x.open_chg == null ? "" : " · " + (x.open_chg > 0 ? "+" : "") + f(x.open_chg, 1) + "%") : "–", dt(x.last)];
    const MH = ["Carteira", "Desde", "Trades", "Acerto", "Seu resultado", "Retorno", "Abertas agora", "Último"];
    table("stMine", [...MH, "O que aconteceu"], (mi.rows || []).filter((x) => !x.real).map((x) => [...mrow(x), dg(x.diag)]),
      "Você ainda não copiou nenhuma destas carteiras. Clique em Copiar numa delas e o resultado aparece aqui.");
    table("stMineR", [...MH, "Situação na real"], (mi.rows || []).filter((x) => x.real).map((x) => [...mrow(x),
      x.real_state === "copia na real" ? '<span class="tag real">copia na real</span>' : '<span class="tag sim">' + esc(x.real_state || "–") + "</span>"]),
      "Nenhuma carteira do estudo copiada na real.");
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
    const m = r.main || r.live || {}, u = m.unit, mm = hms;
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
    if (t.dataset.exsh) {
      const part = t.dataset.exsh, r = await BB.api("/api/pump/study/share-targets"), us = r.users || [];
      const NM = { tudo: "toda a configuração do Explorar", filtros: "os filtros de entrada", protecoes: "as proteções das automáticas" };
      $("exShT").textContent = "Compartilhar " + NM[part]; $("exShare").dataset.part = part;
      $("exShU").innerHTML = us.length ? us.map((u) => '<option value="' + esc(u.user_id) + '">' + esc((u.nome || "sem nome") + (u.email ? " · " + u.email : "")) + "</option>").join("")
        : '<option value="">Nenhum outro admin cadastrado</option>';
      $("exShGo").disabled = !us.length; $("exShare").hidden = false;
      $("exShare").scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (t.id === "exShX") { $("exShare").hidden = true; return; }
    if (t.id === "exShGo") {
      const to = $("exShU").value; if (!to) return;
      t.disabled = true;
      const r = await BB.api("/api/pump/explore/share", { body: { to, part: $("exShare").dataset.part } });
      t.disabled = false;
      toast(r.error ? "Não compartilhou: " + r.error : "Convite enviado (" + r.opcoes + " opções). A pessoa decide se aceita.");
      if (!r.error) $("exShare").hidden = true;
      return;
    }
    if (t.dataset.cfsh) {
      // 0.31.18: escolhe uma, várias ou todas as seções da tela (pedido do dono: "enviar todas, não só uma")
      const cards = cfgShareCards(), mine = t.closest(".card");
      $("cfShSecs").innerHTML = '<label><input type="checkbox" id="cfShAll"' + (t.dataset.cfsh === "all" ? " checked" : "") + "> <b>Marcar todas</b></label>" +
        cards.map((c, i) => '<label><input type="checkbox" data-cfsec="' + i + '"' + (t.dataset.cfsh === "all" || c === mine ? " checked" : "") + "> " + esc(((c.querySelector("h2") || {}).textContent || "seção").trim()) + "</label>").join("");
      const r = await BB.api("/api/pump/config/share-targets"), us = r.users || [];
      $("cfShT").textContent = "Compartilhar configurações (marque as seções)";
      $("cfShU").innerHTML = us.length ? us.map((u) => '<option value="' + esc(u.user_id) + '">' + esc((u.nome || "sem nome") + (u.email ? " · " + u.email : "") + (u.admin ? " · admin" : "")) + "</option>").join("")
        : '<option value="">Nenhum outro usuário cadastrado</option>';
      $("cfShGo").disabled = !us.length; $("cfShare").hidden = false;
      $("cfShare").scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (t.id === "cfShX") { $("cfShare").hidden = true; return; }
    if (t.id === "cfShAll") { document.querySelectorAll("[data-cfsec]").forEach((x) => { x.checked = t.checked; }); return; }
    if (t.dataset.cfsec) { const xs = [...document.querySelectorAll("[data-cfsec]")]; $("cfShAll").checked = xs.every((x) => x.checked); return; }
    if (t.id === "cfAllGo") {
      // 0.31.32 (pedido do dono em 2026-10-27): enviar toda a configuração direto do topo, sem abrir o painel de seções
      const to = $("cfAllU").value; if (!to) { toast("Escolha para quem enviar."); return; }
      t.disabled = true;
      const r = await BB.api("/api/pump/config/share", { body: { to, parte: "toda a configuração", all: true, keys: [] } });
      t.disabled = false;
      toast(r.error ? "Não enviou: " + r.error : "Convite enviado com toda a configuração (" + r.opcoes + " opções). A pessoa decide se aceita.");
      return;
    }
    if (t.id === "cfShGo") {
      const to = $("cfShU").value, sh = $("cfShare"); if (!to) return;
      const cards = cfgShareCards(), sel = [...document.querySelectorAll("[data-cfsec]")].filter((x) => x.checked).map((x) => cards[+x.dataset.cfsec]).filter(Boolean);
      if (!sel.length) { toast("Marque pelo menos uma seção."); return; }
      const keys = [];
      sel.forEach((card) => card.querySelectorAll("[data-cfg],[data-toggle],[data-set]").forEach((el) => { const k = el.dataset.cfg || el.dataset.toggle || el.dataset.set; if (k && !keys.includes(k)) keys.push(k); }));
      const all = sel.length === cards.length, parte = all ? "toda a configuração" : "Configurações · " + sel.map((c) => ((c.querySelector("h2") || {}).textContent || "seção").trim()).join(", ");
      t.disabled = true;
      const r = await BB.api("/api/pump/config/share", { body: { to, parte, all, keys } });
      t.disabled = false;
      toast(r.error ? "Não enviou: " + r.error : "Convite enviado (" + r.opcoes + " opções). A pessoa decide se aceita.");
      if (!r.error) sh.hidden = true;
      return;
    }
    if (t.dataset.ofa || t.dataset.ofr) {
      const id = t.dataset.ofa || t.dataset.ofr, ok = !!t.dataset.ofa;
      if (ok && !confirm("Aplicar essa configuração na sua conta? Os valores atuais dessas opções serão trocados.")) return;
      const r = await BB.api("/api/pump/config/offers/" + encodeURIComponent(id), { body: { accept: ok } });
      toast(r.error ? "Não deu: " + r.error : ok ? "Configuração aplicada (" + r.opcoes + " opções)." : "Convite recusado.");
      loadApplied();
      return loadOffers();
    }
    if (t.id === "cmpGo") { runCompare(); return; }
    if (t.id === "cmpSave") {
      const id = $("cmpSel").value; if (!id) return;
      t.disabled = true; const r = await BB.api("/api/pump/compare/" + encodeURIComponent(id) + "/save", { body: {} }); t.disabled = false;
      toast(r.error ? "Não salvou: " + r.error : "Análise salva no banco para a IA estudar."); if (!r.error) loadCompare(); return;
    }
    if (t.id === "cmpCopy") { const id = $("cmpSel").value; if (!id) return; const r = await BB.api("/api/pump/compare/" + encodeURIComponent(id) + "/ai"); if (r.error) { toast(r.error); return; } copyText(r.texto); return; }
    if (t.dataset.cmptxt) { const s = CMP.saved.find((x) => String(x.id) === t.dataset.cmptxt); if (s) copyText(s.texto || ""); return; }
    if (t.dataset.xcf) { XC.f = t.dataset.xcf; renderExCopy(); return; }
    if (t.dataset.utf) { UTR.f = t.dataset.utf; renderUserTrades(); return; }
    if (t.id === "uTrX" || t.id === "uTrades") { $("uTrades").hidden = true; return; }
    if (t.hasAttribute && t.hasAttribute("data-cfgu-ver")) {
      const box = t.closest("[data-cfgusers]"), l = box.querySelector("[data-cfgu-list]");
      l.hidden = !l.hidden; t.textContent = l.hidden ? "Ver usuários" : "Esconder"; return;
    }
    if (t.dataset.cfgsync) {
      // 0.31.35: deixa as opções desta cópia iguais às de quem enviou AGORA (valores atuais dele)
      const o = APPLIED.find((x) => String(x.id) === t.dataset.cfgsync) || {}, quem = o.de || "outro usuário";
      if (!confirm("Deixar a sua configuração idêntica à de " + quem + "?\n\nAs opções que vieram dele passam a ter os valores que ele usa AGORA. Nada da carteira real, chaves ou Telegram.")) return;
      t.disabled = true; const r = await BB.api("/api/pump/config/applied/" + encodeURIComponent(t.dataset.cfgsync) + "/sync", { body: {} }); t.disabled = false;
      toast(r.error ? "Não aplicou: " + r.error : "Pronto: configuração idêntica à de " + quem + " (" + r.opcoes + " opções).");
      if (!r.error) { await poll(true); loadApplied(); }
      return;
    }
    if (t.dataset.cfgdiff) { openCfgDiff(t.dataset.cfgdiff, t.dataset.card); return; }
    if (t.dataset.copydiff) { openCopyDiff(t.dataset.copydiff); return; }
    if (t.id === "apiURef") { loadApiUsage(); return; }
    if (t.id === "cdRef") { loadCopyDiag(); return; }
    if (t.id === "exLogRef") { loadExLog(); return; }
    const ltb = t.closest && t.closest("[data-logtab]"); if (ltb) { LOGTAB = ltb.dataset.logtab; if (VIEW === "logs") { e.preventDefault(); showLogTab(LOGTAB); } return; }
    if (t.dataset.rlh) { const [md, hh] = t.dataset.rlh.split(":"); RLH[md] = +hh; loadRobotLog(md); return; }
    if (t.dataset.exlogh) { EXLOGH = +t.dataset.exlogh; loadExLog(); return; }
    if (t.dataset.evorep) { showEvo(t.dataset.evorep); return; }
    if (t.id === "evoCmp") { compareEvo(); return; }
    if (t.dataset.evoback) {
      if (!confirm("Voltar o cérebro da SUA conta para a evolução E" + t.dataset.evoback + "?\n\nO Explorar passa a usar as faixas bloqueadas daquela evolução, as regras de saída voltam a ser as de antes dos ajustes automáticos feitos depois dela e o Ajuste automático fica parado até você clicar em Voltar ao automático.")) return;
      const r = await BB.api("/api/pump/base/evolucoes/" + t.dataset.evoback + "/voltar", { body: {} });
      toast(r.error || "Cérebro voltou para a E" + t.dataset.evoback + (r.saida_restaurada && r.saida_restaurada.length ? " (regras de saída restauradas)" : "") + ".");
      loadEvo(); poll(true); return;
    }
    if (t.id === "evoAuto") {
      if (!confirm("Voltar ao automático? O cérebro volta a usar o que aprendeu agora e o Ajuste automático volta a funcionar.")) return;
      const r = await BB.api("/api/pump/base/automatico", { body: {} }); toast(r.error || "Cérebro de volta ao automático."); loadEvo(); return;
    }
    if (t.dataset.feedf) { FEEDF = t.dataset.feedf; renderFeed(); return; }
    if (t.id === "trShGo") {
      const to = $("trShU").value; if (!to) { toast("Escolha a pessoa."); return; }
      t.disabled = true; const r = await BB.api("/api/pump/traders/share", { body: { to } }); t.disabled = false;
      toast(r.error || "Lista enviada (" + r.carteiras + " carteiras). A pessoa recebe um convite no topo do painel."); if (!r.error) $("trShBox").hidden = true; return;
    }
    if (t.id === "trShBtn") {
      const box = $("trShBox"); box.hidden = !box.hidden; if (box.hidden) return;
      const r = await BB.api("/api/pump/config/share-targets"), us = (r && r.users) || [];
      $("trShU").innerHTML = us.length ? '<option value="">Escolha a pessoa…</option>' + us.map((u) => '<option value="' + esc(u.user_id) + '">' + esc((u.nome || "sem nome") + (u.email ? " · " + u.email : "")) + "</option>").join("") : '<option value="">Nenhum outro usuário</option>';
      $("trShN").textContent = ((D && D.manual) || []).length + " carteira(s) adicionada(s) à mão serão enviadas como convite: a pessoa aceita ou não.";
      return;
    }
    if (t.id === "eqSave" || t.id === "eqSeed") {
      const ws = t.id === "eqSeed" ? ((EQ && EQ.padrao) || []) : $("eqList").value.split(/[\s,;]+/).filter(Boolean);
      const r = await BB.api("/api/pump/copy-equal", { body: { wallets: ws } });
      toast(r.error || ("Lista salva: " + r.wallets.length + " carteiras" + (r.invalidas && r.invalidas.length ? " · ignorados (não são endereço): " + r.invalidas.length : "")));
      $("eqList").blur(); loadEq(); return;
    }
    if (t.closest && t.closest("#sysBox")) { openSys(); return; }
    if (t.id === "sysMX") { $("sysM").hidden = true; SYS_SUB = null; return; }
    // 0.32.19: Configuração do Trader
    if (t.id === "tcSave") { await poll(true); toast("Configurações gravadas (cada campo já grava ao mudar)."); return; }
    if (t.id === "tcReset") {
      if (!confirm("Restaurar os Padrões Pump.fun na SUA conta?\n\nCompra 0,1 SOL (fictícia e REAL), slippage real 15%, priority 0,005 SOL, stop −25%, stop móvel em +30% saindo 15 pontos abaixo do pico, stop por tempo 180 s, 1º alvo +100% vende 50%, 2º alvo +300% vende 25% (moonbag 25%), sair quando o dev vende, market cap máximo 100 SOL e curva de 0% a 85%.\n\nA compra REAL passa a ser 0,1 SOL.")) return;
      setCfg({ pump_copy_sol: 0.1, pump_real_max_sol: 0.1, pump_real_slippage_pct: 15, pump_priority_sol: 0.005, pump_real_jito_tip_sol: 0.001,
        pump_stop_pct: 25, pump_trail_enabled: true, pump_trail_start_pct: 30, pump_trail_dist_pct: 15, pump_timestop_on: true, pump_timestop_s: 180, pump_timestop_gain_pct: 0,
        pump_tp1_on: true, pump_tp1_pct: 100, pump_tp1_frac_pct: 50, pump_tp2_pct: 300, pump_tp2_frac_pct: 25, pump_tp_pct: 0,
        pump_exit_dev_sell: true, pump_max_mcap_sol: 100, pump_entry_curve_on: true, pump_entry_curve_min: 0, pump_entry_curve_max: 85 });
      toast("Padrões Pump.fun gravados na sua conta."); return;
    }
    const sk = t.closest && t.closest("[data-saact]"); if (sk) { openSaList(sk.dataset.saact); return; }
    if (t.dataset.sarate) { openSaRate(t.dataset.sarate); return; }
    if (t.dataset.sadet) { openSaDet(+t.dataset.sadet); return; }
    if (t.dataset.gomine) { e.preventDefault(); $("saM").hidden = true; const c = $("stMineCard"); if (c) c.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (t.id === "saMX") { $("saM").hidden = true; return; }
    if (t.dataset.rpclog) { openRpcLog(t.dataset.rpclog); return; }
    if (t.dataset.rpcback) { openSys(); return; }
    if (t.id === "flOn" || t.id === "flOff") {
      const uid = t.id === "flOn" ? $("flSel").value : "";
      if (t.id === "flOn" && !uid) { toast("Escolha a conta primeiro."); return; }
      if (t.id === "flOn" && !confirm("A sua conta vai abrir e fechar os mesmos trades dessa conta, na fictícia e — se a sua Execução real estiver ligada — na real, com o valor e os limites da SUA carteira real. Confirmar?")) return;
      const r = await BB.api("/api/pump/follow-user", { body: { user_id: uid } });
      toast(r.error || (uid ? "Copiando os trades de " + r.nome + "." : "Parou de copiar os trades."));
      loadFollow(); return;
    }
    if (t.id === "cfgDiffNo") { $("cfgDiff").hidden = true; return; }
    if (t.dataset.copyapply) {
      const hit = liveCopies().find(([o]) => String(o.id) === String(t.dataset.copyapply)); if (!hit) return;
      const [o, ks] = hit, body = {};
      ks.filter((k) => !cfgEq(cfgNow(k), o.valores[k])).forEach((k) => { body[k] = o.valores[k]; });
      if (!Object.keys(body).length) { $("cfgDiff").hidden = true; return; }
      t.disabled = true;
      await setCfg(body);
      $("cfgDiff").hidden = true; toast("Aplicado: " + Object.keys(body).length + " opção(ões) iguais às de " + (o.de || "outro usuário") + ".");
      return;
    }
    if (t.id === "cfgDiffX" || t.id === "cfgDiff") { $("cfgDiff").hidden = true; return; }
    if (t.dataset.autoFilt) { EX_AUTO.filt = t.dataset.autoFilt; renderAutoTrades(); return; }
    if (t.dataset.realFilt) { EX_AUTO.rfilt = t.dataset.realFilt; renderAutoTrades(); return; }
    if (t.id === "tuRun") {
      t.disabled = true;
      const r = await BB.api("/api/pump/tune/run", { body: {} });
      t.disabled = false;
      toast(r.error ? "Não rodou: " + r.error : !r.ok ? "Ajuste automático: " + (r.motivo || "desligado") : (r.acoes || []).length ? "Ajuste automático: " + r.acoes.join(", ") : r.testando ? "Ajuste automático: regra em teste, ainda sem base para decidir." : "Ajuste automático: nada para mudar agora.");
      return loadTune();
    }
    if (t.id === "saRun") {
      t.disabled = true;
      const r = await BB.api("/api/pump/study/auto/run", { body: {} });
      t.disabled = false;
      toast(r.error ? "Não rodou: " + r.error : !r.ok ? "Estudo automático desligado." : "Estudo automático: " + r.adicionou + " adicionadas, " + r.aprovou + " aprovadas, " + r.descartou + " descartadas.");
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
    // 0.32.65 (pedido do dono): Copiar igual por carteira — pergunta fictícia ou REAL
    if (t.dataset.eqc) { EQ_W = t.dataset.eqc; const real = !!(D && D.real && D.real.enabled);
      $("eqMS").textContent = EQ_W.slice(0, 4) + "…" + EQ_W.slice(-4) + " · copia TODA compra e venda dela, na hora e sem filtros";
      $("eqMB").innerHTML = "<p>Carteira fictícia: <b>" + (cfg().pump_eq_sol || 0.05) + " SOL</b> por compra; vende a mesma parte quando ela vende.</p><p>Carteira REAL: " + (real ? "<b>até " + cfg().pump_real_max_sol + " SOL</b> por compra" : '<span class="down">execução real desligada</span> (o botão REAL fica guardado e só vale quando você ligar)') + "</p>" +
        '<p class="muted small">Só copia o que o monitor VÊ: se o Status do sistema mostra o Solana RPC com erro (429), as compras dela não chegam e nada é copiado.</p>';
      $("eqM").hidden = false; return; }
    if (t.id === "eqMX") { $("eqM").hidden = true; return; }
    // 0.32.70 (pedido do dono): acompanhar o que a carteira copiada está fazendo
    if (t.dataset.eqd || t.id === "eqDR") { if (t.dataset.eqd) EQ_D = t.dataset.eqd; return openEqDetail(); }
    if (t.id === "eqDX") { $("eqD").hidden = true; return; }
    if (t.dataset.eqgo) { const md = t.dataset.eqgo; if (md === "both" && !confirm("Copiar esta carteira também na carteira REAL (dinheiro de verdade)?")) return;
      const r = await BB.api("/api/pump/copy-equal/mode", { body: { wallet: EQ_W, mode: md } }); $("eqM").hidden = true;
      toast(r.error || (md === "off" ? "Parou de copiar esta carteira." : (md === "both" ? "Copiando na fictícia e na REAL" + (r.real_ligada ? "." : " (a REAL só sai quando a Execução real estiver ligada).") : "Copiando na fictícia.") + (r.ligou_modo ? " O Copiar igual foi ligado." : "")));
      poll(true); return loadEq(); }
    // 0.32.38 (pedido do dono): o Copiar do estudo pergunta em qual carteira copiar
    if (t.dataset.stc) { STC_W = t.dataset.stc; const real = !!(D && D.real && D.real.enabled);
      $("stcMS").textContent = STC_W.slice(0, 4) + "…" + STC_W.slice(-4) + " · copia toda compra e venda dela com os filtros de Configurações";
      $("stcMB").innerHTML = "<p>Carteira fictícia: <b>" + (cfg().pump_copy_sol || 0.1) + " SOL</b> por cópia.</p><p>Carteira REAL: " + (real ? "<b>até " + cfg().pump_real_max_sol + " SOL</b> por cópia" : '<span class="down">execução real desligada</span>') + "</p>" +
        '<p class="muted small">A IA acompanha o resultado de verdade: com 8+ trades no prejuízo e acerto abaixo de 40% ela avisa (e para de copiar as que ela mesma aprovou).</p>';
      $("stcBoth").disabled = !real; $("stcM").hidden = false; return; }
    if (t.id === "stcMX") { $("stcM").hidden = true; return; }
    // 0.32.47 (pedido do dono): relatório da carteira em estudo + prompt para o ChatGPT fazer a varredura das transações
    if (t.dataset.stai !== undefined && t.closest("[data-stai]") === t) { STAI_ID = ""; $("staiT").value = "Gerando o relatório…"; $("staiR").value = ""; $("staiRM").textContent = ""; $("staiAn").hidden = true; $("staiM").hidden = false;
      const r = await BB.api("/api/pump/study/ai" + (t.dataset.stai ? "?wallet=" + encodeURIComponent(t.dataset.stai) : ""));
      $("staiT").value = r.error || r.text || "–"; STAI_ID = r.id || "";
      $("staiMT").textContent = "Relatório " + (r.id || "") + " · " + (r.carteiras || 0) + " carteira(s)"; $("staiMS").textContent = "guardado no histórico · copie e mande para o ChatGPT"; loadStudyAi(); return; }
    if (t.dataset.saio) { openStudyAi(t.dataset.saio); return; }
    if (t.id === "saiNewGo") { const b = $("staiM"); STAI_ID = ""; $("staiT").value = "Gerando o relatório das carteiras novas…"; $("staiR").value = ""; $("staiAn").hidden = true; b.hidden = false;
      const r = await BB.api("/api/pump/study/ai/reports/novas", { body: {} }); if (r.error) { $("staiT").value = r.error; return; } openStudyAi(r.id); return; }
    if (t.id === "staiX") { $("staiM").hidden = true; return; }
    if (t.id === "staiCp") { const ta = $("staiT"); ta.select(); try { await navigator.clipboard.writeText(ta.value); } catch (e) { document.execCommand("copy"); }
      if (STAI_ID) { await BB.api("/api/pump/study/ai/reports/" + encodeURIComponent(STAI_ID), { body: { acao: "copiado" } }); $("staiMS").textContent = "copiado · esperando a resposta do ChatGPT para processar"; loadStudyAi(); }
      toast("Copiado e guardado no histórico. Esperando a resposta do ChatGPT."); return; }
    if (t.id === "staiRS") { if (!STAI_ID) return; const r = await BB.api("/api/pump/study/ai/reports/" + encodeURIComponent(STAI_ID), { body: { acao: "resposta", texto: $("staiR").value } });
      if (r.error) { $("staiRM").textContent = r.error; return; }
      // 0.32.53 (pedido do dono): salvou → fecha a janela e o histórico mostra "esperando o Claude analisar"
      $("staiM").hidden = true; toast("Resposta salva (relatório " + STAI_ID + "). Esperando o Claude analisar."); loadStudyAi(); return; }
    if (t.dataset.stcgo) { const tg = t.dataset.stcgo; if (tg === "both" && !confirm("Copiar também na carteira REAL (dinheiro de verdade)?")) return;
      const r = await BB.api("/api/pump/study/copy", { body: { wallet: STC_W, target: tg } }); $("stcM").hidden = true;
      toast(r.error || (tg === "both" ? "Copiando na fictícia e na REAL." : "Copiando só na fictícia.")); poll(true); return loadStudy(); }
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
    $("tNov").innerHTML = "<thead><tr><th>Versão</th><th>Data e hora</th><th>Tipo</th><th>Onde fica</th><th>O que é e o que faz</th></tr></thead><tbody>" +
      rows.map((x) => {
        const recente = hoje - new Date(x.data + "T00:00:00").getTime() < 14 * 86400000;
        return '<tr class="' + (recente ? "nov-recente" : "") + '"><td class="mono">' + esc(x.versao) +
          '</td><td class="mono">' + (x.inicio ? esc(new Date(x.inicio).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })) : esc(x.data.split("-").reverse().join("/"))) + '</td><td><span class="tag ' + (TAG[x.tipo] || "neutral") + '">' + esc(x.tipo) +
          "</span>" + (x.area && x.area.length ? '<div class="novarea">' + x.area.map((a) => '<span class="tag neutral">' + esc(a) + "</span>").join("") + "</div>" : "") +
          "</td><td>" + esc(x.onde) + "</td><td><b>" + esc(x.titulo) + '</b><br><span class="muted">' + esc(x.oque) + "</span>" +
          (x.arquivos && x.arquivos.length ? '<div class="novfiles">Código mexido: ' + x.arquivos.map((f) => "<code>" + esc(f) + "</code>").join(" ") + "</div>" : "") + "</td></tr>";
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
    igual: ["Copiar igual", "toda compra e venda das carteiras da lista, sem filtros e sem espera"], elite: ["Maiores traders", "o que os maiores ganhadores fazem, sinais, estudo e compra automática"], explorar: ["Explorar", "novos, quase graduando, graduados e os que mais sobem"], basegeral: ["Base geral", "o cérebro do robô: o que aprendeu com todas as contas, maturidade e evolução"], logs: ["Logs dos robôs", "o que cada robô analisou, fez e por que não fez · guardado sem prazo"], calls: ["Calls quentes", "compras de quem chama, veredito e nota de cada caller"], bruxo: ["Aba do Bruxo", "top trader comprou moeda nova: entrar junto, sair rápido"], base: ["Base da pump.fun", "a vida de cada token novo, criadores e mercado por hora"], listanegra: ["Lista negra", "criadores e carteiras que ninguém copia"], fantasma: ["Estratégias fantasma", "várias regras de saída testadas ao mesmo tempo, só no simulado"], novas: ["Opções novas de cópia", "em teste: ligue para usar ou deixe desligado para descartar"], estudo: ["Carteiras em estudo", "entender o que as carteiras fazem e quanto ganham"], radar: ["Radar de KOLs", "ondas de compras e primeiras vendas nas carteiras em estudo"], feed: ["Feed ao vivo", "cada movimento dos traders copiados"], real: ["Execução real", "carteira de verdade · começa desligada"],
    tradercfg: ["Configuração do Trader", "compra, stops, alvos e segurança das cópias, fictícia e real"], config: ["Configurações", "regras de cópia, proteções e chaves"], admin: ["Administração", "usuários, sistema e logs"],
    novidades: ["Changelog", "o que foi implementado, onde fica e o que faz"], comparar: ["Comparar config copiada", "usuário X × usuário Y depois de copiar a configuração: ganhos, perdas e o que aconteceu"], ajuda: ["Como funciona", ""] };
  let VIEW = "visao";
  function route() {
    const v = (location.hash || "#visao").slice(1);
    VIEW = TITLES[v] ? v : "visao";
    // Administração e o menu "Usar ou descartar" (0.17.3, pedido do dono em 2026-10-25) são só do admin
    if (["admin", "novidades", "estudo", "radar", "relatorios", "aprendizado", "novas", "fantasma", "listanegra", "base", "explorar", "elite", "igual", "comparar", "basegeral", "logs", "calls", "bruxo"].includes(VIEW) && !(ME && ME.role === "admin")) VIEW = "visao";
    document.querySelectorAll(".view").forEach((s) => (s.hidden = s.dataset.view !== VIEW));
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.v === VIEW));
    if (document.querySelector("#navSub a.on")) { $("navGrp").classList.remove("fechado"); $("navGrpH").setAttribute("aria-expanded", "true"); }
    $("pgTitle").textContent = TITLES[VIEW][0]; $("pgSub").textContent = TITLES[VIEW][1];
    closeDrawer();
    if (VIEW === "visao") { loadDaily(); loadApplied(); buildAllCfg(); loadFollow(); }
    if (VIEW === "config") { buildAllCfg(); loadFollow(); loadSecrets(); loadAudit(); loadApplied(); loadConfigUsers(); }
    if (VIEW === "admin") { loadApiUsage(); loadAdmin(); loadSysKeys(); loadUsers(); loadAAudit(); LOG_AFTER = 0; $("logs").innerHTML = ""; loadLogs(); }
    if (VIEW === "real") { walletLoad(true); loadMirror(); }
    if (VIEW === "novidades") loadNovidades();
    if (VIEW === "relatorios") loadReports();
    if (VIEW === "fantasma") loadGhosts();
    if (VIEW === "listanegra") loadBlacklist();
    if (VIEW === "base") loadBase();
    if (VIEW === "explorar") { loadExplore(); renderAutoTrades(); loadAutoTrades(true); loadApplied(); loadConfigUsers(); }
    if (VIEW === "comparar") loadCompare();
    if (VIEW === "basegeral") loadBaseGeral();
    if (VIEW === "logs") showLogTab(LOGTAB);
    if (VIEW === "calls") loadCalls();
    if (VIEW === "bruxo") loadBruxo();
    if (VIEW === "traders") loadCopyDiag();
    if (VIEW === "elite") { loadElite(); loadSteps(); }
    if (VIEW === "igual") loadEq();
    if (VIEW === "aprendizado") loadLearning();
    if (VIEW === "estudo") { loadStudy(); loadStudyAi(); }
    if (VIEW === "radar") loadRadar(true);
    render();
    window.scrollTo(0, 0);
  }
  function closeDrawer() { $("side").classList.remove("open"); $("scrim").classList.remove("open"); }

  // ------------------------------------------------------------------ notificações (som + aviso)
  let NTF = false, NTF_AT = 0;
  try { NTF = localStorage.getItem("ntf") === "1"; } catch (e) { /* */ }
  // 0.32.52 (pedido do dono): voz em português nos trades que fecham — o próprio navegador fala (speechSynthesis), nada instalado.
  // {pct} vira o % do resultado. As frases ficam só neste navegador.
  const VOZ_PAD = { win: "Deu lucro, porra! Mais {pct} por cento.", loss: "Porra, deu merda! Menos {pct} por cento.", buy: "Opa, comprei umas coisas aqui, vamo ver no que dá!" };
  let VOZ = false, VOZ_F = { ...VOZ_PAD };
  // 0.32.54 (dono: "só bip, a voz não funciona"): a Voz vem LIGADA (antes começava desligada); o navegador só deixa falar depois
  // de um clique na página (destravado no 1º clique); a fala fica guardada numa variável (o Chrome descartava antes de falar)
  try { const v = localStorage.getItem("ntf_voz"); VOZ = v === null ? true : v === "1"; VOZ_F = { ...VOZ_PAD, ...JSON.parse(localStorage.getItem("ntf_voz_f") || "{}") }; } catch (e) { VOZ = true; }
  let VOZES = [], VOZ_OK = false;
  function loadVoices() { try { VOZES = window.speechSynthesis ? window.speechSynthesis.getVoices() : []; } catch (e) { VOZES = []; } }
  try { if (window.speechSynthesis) { loadVoices(); window.speechSynthesis.addEventListener("voiceschanged", loadVoices); } } catch (e) { /* */ }
  function ptVoice() { return VOZES.find((v) => /pt-BR/i.test(v.lang) && /natural|online|google/i.test(v.name)) || VOZES.find((v) => /pt-BR/i.test(v.lang)) || VOZES.find((v) => /^pt/i.test(v.lang)) || null; }
  function unlockVoice() {
    if (VOZ_OK || !window.speechSynthesis) return; VOZ_OK = true;
    try { const u = new SpeechSynthesisUtterance(" "); u.volume = 0; window.speechSynthesis.speak(u); } catch (e) { /* */ }
  }
  ["pointerdown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, unlockVoice, { passive: true }));
  function say(text) {
    try { const S = window.speechSynthesis; if (!S || !text) return false;
      if (!VOZES.length) loadVoices();
      const u = new SpeechSynthesisUtterance(text), v = ptVoice();
      if (v) u.voice = v; u.lang = "pt-BR"; u.rate = 1.05; u.volume = 1;
      (window.__fala = window.__fala || []).push(u); u.onend = u.onerror = () => { window.__fala = (window.__fala || []).filter((x) => x !== u); };
      if (S.paused) S.resume(); S.speak(u); return true; } catch (e) { return false; }
  }
  function sayTrade(k, msg) {
    if (VOZ && /compra (automática|manual)|comprou/i.test(msg || "") && !/NÃO feita|não copiou|pausad/i.test(msg || "")) { say(VOZ_F.buy || VOZ_PAD.buy); return; }
    if (!VOZ || (k !== "win" && k !== "loss")) return;
    const m = /→\s*[+\-−]?[0-9.]+\s*SOL\s*\(([+\-−]?[0-9.]+)%\)/.exec(msg || "");
    const pct = m ? Math.round(Math.abs(Number(m[1].replace("−", "-")))) : "";
    say(String(VOZ_F[k] || "").replace("{pct}", pct));
  }
  // 0.31.51 (pedido do dono): o sino mostra quantas notificações chegaram desde a última vez que você olhou; clicar abre a
  // lista (o que foi, quando). O som e o aviso do navegador ligam e desligam dentro da lista.
  let NTFL = [], NTFU = 0;
  function ntfBtn() {
    const b = $("ntfB");
    b.innerHTML = "🔔 Notificações: " + (NTF ? "ON" : "OFF") + (NTFU ? ' <span class="ntfc">' + (NTFU > 99 ? "99+" : NTFU) + "</span>" : "");
    b.className = "btn tgl ntf " + (NTF ? "on" : "off");
    if ($("ntfS")) { $("ntfS").textContent = "Som e aviso"; $("ntfS").className = "btn sm tgl sw " + (NTF ? "on" : "off"); $("ntfS").setAttribute("role", "switch"); $("ntfS").setAttribute("aria-checked", String(NTF)); }
  }
  function ntfPush(e, unread) {
    NTFL.unshift({ at: e.at, msg: e.msg, k: classify(e.msg), real: /REAL/.test(e.msg) }); NTFL = NTFL.slice(0, 100);
    if (unread) NTFU++;
    ntfBtn(); if (!$("ntfP").hidden) ntfList();
  }
  // 0.32.34 (pedido do dono): clicar numa notificação abre o que aconteceu — a posição aberta, ou o trade fechado com o motivo
  function ntfSymbol(msg) {
    const m = /fechou (\S+) copiado|compra (?:automática|manual)[^:]*: (\S+)|copiou [^:]+: compra (\S+)|\] (\S+): (?:vendendo|trader saiu|saída)|compra (\S+) NÃO feita/i.exec(msg || "");
    return m ? (m[1] || m[2] || m[3] || m[4] || m[5]) : null;
  }
  function openTradeDet(t) {
    const row = (k, v) => "<tr><td><b>" + k + "</b></td><td>" + v + "</td></tr>";
    $("posMT").innerHTML = (t.real ? '<span class="tag real">REAL</span> ' : '<span class="tag sim">FICTÍCIA</span> ') + esc(t.symbol || "") + " · fechada " +
      '<span class="tag ' + ((t.pnl_sol || 0) > 0 ? "win" : "loss") + '">' + ((t.pnl_sol || 0) > 0 ? "LUCRO +" : "PREJUÍZO ") + s4(t.pnl_sol) + " SOL · investiu " + s4(t.sol_in) + " SOL</span>";
    $("posMS").textContent = "abriu " + dt(t.opened_at) + " · fechou " + dt(t.closed_at) + " · origem: " + whoLabel(t);
    $("posMB").innerHTML = '<div class="kpis" style="margin:4px 0 12px">' +
      [["Resultado", sg(t.pnl_sol), (t.pnl_pct == null ? "" : f(t.pnl_pct, 1) + "% do investido, já com taxas")], ["Investido", s4(t.sol_in) + " SOL", ""], ["Recebido", s4(t.sol_out) + " SOL", ""], ["Segurou", hms(t.hold_s), ""]]
        .map(([l, v, s]) => '<div class="kpi"><div class="l">' + l + '</div><div class="v">' + v + '</div><div class="s">' + esc(s) + "</div></div>").join("") + "</div>" +
      (t.entrou_porque ? '<div class="decbox"><b>Por que entrou:</b> ' + esc(t.entrou_porque) + "</div>" : "") +
      '<div class="decbox ' + ((t.pnl_sol || 0) > 0 ? "ok" : "bad") + '"><b>Por que saiu:</b> ' + esc(t.reason || "–") + "</div>" +
      '<div class="tbl-wrap"><table class="systbl"><tbody>' +
      row("Token", pfM(t.mint, t.symbol) + (t.venue ? " · " + esc(t.venue) : "")) +
      row("Origem", pfW(t.wallet, t)) +
      row("Preço de entrada → saída", ex(t.price_in) + " → " + ex(t.price_out)) +
      row("Melhor e pior momento", (t.best_pct == null ? "–" : pc(t.best_pct)) + " · " + (t.worst_pct == null ? "–" : pc(t.worst_pct))) +
      row("Taxas", t.fees_sol == null ? "–" : s4(t.fees_sol) + " SOL") +
      row("Atraso da entrada", t.lag_s == null ? "–" : f(t.lag_s, 1) + " s") +
      row("Vendas", (t.sells || []).length ? (t.sells || []).map((s) => dt(s.at) + " · " + f((s.frac || 0) * 100, 0) + "% · " + s4(s.sol) + " SOL" + (s.why ? " · " + esc(s.why) : "")).join("<br>") : "–") +
      "</tbody></table></div>" + '<p class="muted small" style="margin-top:8px">No Histórico ficam todas as fechadas; em Base geral → Aprendizado das posições, se saiu cedo ou na hora certa (1 h depois de fechar).</p>';
    POS_ID = null; $("posM").hidden = false; $("posMX").focus();
  }
  function openNtf(i) {
    const n = NTFL[i]; if (!n) return;
    const sym = ntfSymbol(n.msg), real = /^\[PUMP REAL\]/.test(n.msg || "");
    if (!sym) { toast(n.msg); return; }
    const same = (x) => String(x.symbol || "").toLowerCase() === sym.toLowerCase() && !!x.real === real;
    const p = (D && D.positions || []).find(same);
    if (p) { POS_DET = POS_DET || { list: D.positions, left: () => "–", soldCell: () => "–", vol: () => "–" }; if (!POS_DET.list.includes(p)) POS_DET.list = D.positions; openPosDet(p.id); return; }
    const t = (D && D.trades || []).find(same) || (D && D.recent_closed || []).find(same);
    if (t) { openTradeDet(t); return; }
    toast("Não achei a operação de " + sym + " (talvez já tenha saído da lista); veja no Histórico.");
  }
  // 0.32.51 (pedido do dono): "deu lucro?" logo de cara — resultado e quanto foi investido (o investido sai do próprio %)
  function ntfMoney(msg) {
    const num = (x) => Number(String(x).replace("−", "-"));
    const m = /→\s*([+\-−]?[0-9.]+)\s*SOL\s*\(([+\-−]?[0-9.]+)%\)/.exec(msg || "");
    if (m) { const pnl = num(m[1]), pct = num(m[2]), inv = pct ? Math.abs(pnl / (pct / 100)) : null, up = pnl > 0;
      return '<div class="ntfmoney ' + (up ? "up" : "down") + '"><b>' + (up ? "LUCRO " : "PREJUÍZO ") + (up ? "+" : "") + s4(pnl) + " SOL</b> (" + (up ? "+" : "") + f(pct, 1) + "%)" +
        (inv ? ' <span class="muted">· investiu ' + s4(inv) + " SOL · recebeu " + s4(inv + pnl) + " SOL</span>" : "") + "</div>"; }
    const b = /compra (?:automática|manual)[^:]*:\s*\S+\s+([0-9.]+)\s*SOL/i.exec(msg || "");
    if (b) return '<div class="ntfmoney"><b>Investiu ' + s4(num(b[1])) + " SOL</b></div>";
    return "";
  }
  // 0.32.56 (pedido do dono): a notificação diz de qual aba veio o trade (Explorar, barrados, Aba do Bruxo, Top traders…)
  function ntfAba(n) {
    const sym = ntfSymbol(n.msg); if (!sym) return "";
    const real = /^\[PUMP REAL\]/.test(n.msg || ""), same = (x) => String(x.symbol || "").toLowerCase() === sym.toLowerCase() && !!x.real === real;
    const x = (D && D.positions || []).find(same) || (D && D.recent_closed || []).find(same) || (D && D.trades || []).find(same);
    return x && x.aba ? ' <span class="tag aba">' + esc(x.aba) + "</span>" : "";
  }
  function ntfList() {
    const KN = { buy: ["Compra", "sim"], win: ["Lucro", "win"], loss: ["Prejuízo", "loss"], sell: ["Venda", "neutral"], alert: ["Aviso", "pause"], error: ["Erro", "loss"], stop: ["Stop", "loss"], trader: ["Traders", "neutral"] };
    // 0.31.58 (pedido do dono): toda notificação diz se é da carteira REAL ou da FICTÍCIA
    $("ntfL").innerHTML = NTFL.length ? NTFL.map((n) => { const kk = /compra autom|comprou|compra manual/i.test(n.msg) && !/NÃO feita|não copiou/i.test(n.msg) && !n.k ? ["Compra", "sim"] : KN[n.k] || ["Aviso", "neutral"];
      const isReal = /^\[PUMP REAL\]/.test(n.msg || ""), mk = mascKind(n.msg);
      const nome = mk ? String(mk[2]).replace(/ \(REAL\)$/, "") : kk[0];
      return '<div class="ntfi" data-ntfi="' + NTFL.indexOf(n) + '" title="Clique para ver o que aconteceu"><span class="tag ' + kk[1] + '">' + esc(nome) + "</span> " + (isReal ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>') + ' <span class="muted">' + esc(n.at ? new Date(n.at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "") + "</span>" + ntfAba(n) + ntfMoney(n.msg) + "<div>" + esc(String(n.msg || "").replace(/^\[PUMP (SIM|REAL)\]\s*/, "")) + "</div></div>"; }).join("")
      : '<p class="muted">Nenhuma notificação ainda.</p>';
  }
  function tone(C, t0, fr, dur, type, vol) { const o = C.createOscillator(), g = C.createGain(); o.type = type; o.frequency.setValueAtTime(fr, t0); g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(vol, t0 + 0.012); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur); o.connect(g); g.connect(C.destination); o.start(t0); o.stop(t0 + dur + 0.02); }
  // 0.31.75: sem isso o som ficava mudo quando "Som e aviso" já vinha ligado (o navegador exige um clique na página)
  function unlockAudio() {
    try { const C = window.__ac || (window.__ac = new (window.AudioContext || window.webkitAudioContext)()); if (C.state === "suspended") C.resume(); } catch (e) { /* sem áudio */ }
  }
  ["pointerdown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, unlockAudio, { passive: true }));
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
    if (/comprou|copiou [^:]*: compra|copiou compra|entrou|\] compra (automática|manual)/i.test(m)) return "buy";   // 0.31.75: automáticas
    if (/PAUSADO|robô/i.test(m)) return "alert";
    return null;
  }
  // 0.31.56 (pedido do dono): notificação (sino, som, aviso) só dos trades da PRÓPRIA conta ([PUMP SIM] / [PUMP REAL]);
  // ranking de traders, Radar, aprendizado e outros avisos não entram
  const OWN_TRADE = /^\[PUMP (SIM|REAL)\]/;
  function onEvent(e) {
    const k = classify(e.msg); const real = /REAL/.test(e.msg);
    mascReact(e.msg);
    if (!OWN_TRADE.test(e.msg || "") || /pausad/i.test(e.msg || "")) return;      // "compra automática pausada" não é trade
    ntfPush(e, true);
    if (real || k === "error") toast(e.msg.slice(0, 180));
    sayTrade(k, e.msg);
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
    if (/\] compra (automática|manual)/i.test(m)) return ["pensativo", "m-pula", (/automática/i.test(m) ? "Compra automática" : "Compra manual") + real];
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
    if (VIEW === "explorar" && EX_AUTO.data && !EX_AUTO.stale && Date.now() - EX_AUTO.updatedAt > 30000) { EX_AUTO.stale = true; renderAutoTrades(); }
    if (BUSY && !force) return; BUSY = true;
    try {
      const r = await BB.api("/api/pump?ev=" + Math.max(EV, 0));
      if (r.error) { $("sysS").textContent = r.error; if (VIEW === "radar") invalidateRadar(r.error); return; }
      D = r;
      const evs = r.events || [];
      if (EV < 0) { EV = evs.length ? evs[evs.length - 1].id : 0; evs.filter((e) => OWN_TRADE.test(e.msg || "") && !/pausad/i.test(e.msg || "")).slice(-30).forEach((e) => ntfPush(e, false)); }
      else evs.forEach((e) => { if (e.id > EV) { EV = e.id; onEvent(e); } });
      render();
    } catch (e) { if (VIEW === "radar") invalidateRadar(e.message || "falha de conexão"); } finally { BUSY = false; }
  }
  async function loadMirror() {
    const r = await BB.api("/api/pump/real/mirror"); if (r.error || !$("rmT")) return;
    const L = r.pairs || [];
    kpis("rmK", [["Trades reais do espelho", String(L.length), "com par na fictícia: " + L.filter((x) => x.sim_pct != null).length, "tr"], ["Resultado real", sg(r.real_sol), "soma dos trades reais acima", "pnl"],
      ["Diferença média", r.media_dif_pct == null ? "–" : (r.media_dif_pct > 0 ? "+" : "") + f(r.media_dif_pct, 1) + " pts", "real − fictícia, em % por trade", "mon"]]);
    table("rmT", ["Fechou", "Token", "Fictícia", "Real", "Diferença", "Atraso", "Saída real / fictícia"], L.map((x) => [esc(dt(x.fechou)), pfM(x.mint || "", x.token),
      x.sim_pct == null ? '<span class="muted">sem par</span>' : sg(x.sim_sol) + "<small>" + pc(x.sim_pct) + "</small>", sg(x.real_sol) + "<small>" + pc(x.real_pct) + "</small>",
      x.dif_pct == null ? "–" : (x.dif_pct > 0 ? '<span class="up">+' : '<span class="down">') + f(x.dif_pct, 1) + " pts</span>", (x.atraso_s == null ? "–" : hms(x.atraso_s)) + (x.lat ? "<small>PumpPortal " + f(x.lat.montar_ms || 0, 0) + " ms · blockchain " + f(x.lat.confirmar_ms || 0, 0) + " ms</small>" : ""), esc((x.motivo_real || "") + (x.motivo_sim ? " / " + x.motivo_sim : ""))]),
      "Nenhum trade real do espelho fechado ainda.");
    const M = r.misses || { lista: [], por_motivo: [] };
    $("rmMissS").hidden = !M.total && r.real_on && r.mirror_on;
    $("rmMissS").textContent = !r.real_on ? "A Execução real está DESLIGADA: nada da fictícia vai para a real." : !r.mirror_on ? "\"Espelhar 100% a carteira fictícia\" está DESLIGADO." :
      M.total + (M.total === 1 ? " trade da fictícia ficou" : " trades da fictícia ficaram") + " sem par na real nas últimas 48 h" + (M.perdido_sol ? " (os que ganharam somaram " + s4(M.perdido_sol) + " SOL na fictícia)" : "") + ". Veja o motivo e a dica abaixo.";
    table("rmMissR", ["Motivo (o que mais aconteceu)", "Vezes", "Resultado na fictícia", "O que fazer"], (M.por_motivo || []).map((g) => [esc(g.motivo), String(g.n), sg(g.sim_sol), esc(g.dica || "")]), "Nenhum: tudo o que a fictícia fez foi para a real.");
    table("rmMiss", ["Fechou", "Token", "Origem", "Fictícia", "Por que não foi para a real"], (M.lista || []).map((x) => [esc(dt(x.fechou)), pfM(x.mint || "", x.token), esc(x.origem), sg(x.sim_sol) + "<small>" + pc(x.sim_pct) + "</small>", '<b style="color:var(--warn)">' + esc(x.motivo) + "</b>" + (x.dica ? "<small>" + esc(x.dica) + "</small>" : "")]), "Nada para mostrar.");
  }
  async function walletLoad(force) { try { W = await BB.api("/api/pump/wallet" + (force ? "?force=1" : "")); if (VIEW === "real") renderReal(); } catch (e) { /* */ } }

  async function setCfg(body) {
    if (Object.keys(body).every(isAutoCfg)) return saveAutoCfg(body);
    const r = await BB.api("/api/pump/settings", { body: body });
    const errs = Object.entries(r.errors || {});
    toast(r.error || (errs.length ? "Não aplicado: " + errs.map((e) => e[0].replace("pump_", "") + " (" + e[1] + ")").join(", ") : "Salvo."));
    poll(true);
  }

  // ------------------------------------------------------------------ render geral
  let SYS_HTML = null;
  function sysDetail(D, RP, PPs, A, RL, up, perH, okb, ago) {
    const row = (k, st, v) => "<tr><td><b>" + k + "</b></td><td>" + st + "</td><td>" + v + "</td></tr>";
    // 0.32.7 (pedido do dono): cada linha do funil abre a lista do que aconteceu
    const open = (k, tipo) => '<button class="linkbtn" data-rpclog="' + tipo + '">' + k + " ›</button>";
    const late = RP.queued ? Math.round((RP.stale || 0) / RP.queued * 100) : 0;
    return '<div class="tbl-wrap"><table class="systbl"><thead><tr><th>Serviço</th><th>Situação</th><th>Detalhe</th></tr></thead><tbody>' +
      row("Solana RPC", okb(RP.ws, RP.error), RP.ws ? (RP.subs || 0) + " carteiras · " + (RP.parsed || 0) + " trades" + perH(RP.parsed) + " · último " + ago(RP.last_event) : esc(RP.error || "aguardando o monitor compartilhado")) +
      row("PumpPortal", okb(PPs.ws, PPs.error), PPs.ws ? "tokens novos " + (PPs.new_tokens || 0) + perH(PPs.new_tokens) + " · último " + ago(PPs.last_event) : esc(PPs.error || "desconectado")) +
      // 0.32.18 (pedido do dono): trades das copiadas pela PumpPortal paga (0,01 SOL a cada 10 mil trades, na carteira da chave do sistema)
      row("Trades das copiadas pela PumpPortal", '<button class="btn sm tgl" data-toggle="pump_pp_copy" data-confirm="Ligar? A PumpPortal cobra 0,01 SOL a cada 10 mil trades recebidos, da carteira ligada à chave PumpPortal do sistema (precisa ter saldo).">…</button>',
        (PPs.acct_subs ? PPs.acct_subs + " carteiras assinadas · " + f(PPs.acct_trades || 0, 0) + " trades recebidos (≈ " + ((PPs.acct_trades || 0) / 1e6).toFixed(4) + " SOL)" + (PPs.acct_last ? " · último " + ago(PPs.acct_last) : "") + (RP.pp_skip ? " · " + f(RP.pp_skip, 0) + " leituras do RPC economizadas" : "")
          : "desligado · ligado, as compras e vendas das carteiras copiadas chegam prontas, sem gastar o RPC (só pump.fun/PumpSwap; cobra 0,01 SOL a cada 10 mil trades da carteira da chave PumpPortal do sistema)")) +
      row("Preços", okb(!RP.price_error, RP.price_error), esc(RP.price_error || "–")) +
      row("Jupiter", okb((A.jupiter || {}).ok !== false, (A.jupiter || {}).error), esc((A.jupiter || {}).error || "–")) +
      row("Solana Tracker", okb((A.solana_tracker || {}).ok, (A.solana_tracker || {}).error || "sem chave"), ((A.solana_tracker || {}).fonte ? "<b>usando: " + esc(A.solana_tracker.fonte) + "</b> · " : "") + esc((A.solana_tracker || {}).error || "–")) +
      row("Banco", okb((A.banco || {}).ok !== false, (A.banco || {}).error), esc((A.banco || {}).error || "–")) +
      row("Carteira real", RL.wallet_configured ? '<span class="up">configurada</span>' : '<span class="down">não configurada</span>', "execução " + (RL.enabled ? "ON" : "OFF")) +
      "</tbody></table></div>" +
      '<h3 style="margin:16px 0 6px;font-size:13px">Transações da Solana (funil)</h3><div class="tbl-wrap"><table class="systbl"><tbody>' +
      row("Avisos recebidos", "", f(RP.notifs || 0, 0)) + row("Foram para leitura", "", f(RP.queued || 0, 0) + (RP.queued_hi ? " · das copiadas " + f(RP.queued_hi, 0) : "")) +
      row(open("Viraram trade", "trade"), "", f(RP.parsed || 0, 0)) + row(open("Não eram trade", "nao_trade"), "", f(RP.not_trade || 0, 0)) +
      row(open("Atrasados (+2 min na fila)", "atrasado"), late >= 20 ? '<span class="down">' + late + "%</span>" : late + "%", f(RP.stale || 0, 0) + (RP.stale_hi ? " · das copiadas " + f(RP.stale_hi, 0) : "")) +
      row(open("Falhas de leitura", "falha"), (RP.tx_errors || 0) > (RP.parsed || 0) ? '<span class="down">mais falhas que trades</span>' : "", f(RP.tx_errors || 0, 0)) + (RP.dropped ? row("Fila cheia", "", f(RP.dropped, 0)) : "") + (RP.limited || RP.skipped_bot ? row("Pulados de propósito", "", f(RP.limited || 0, 0) + " acima de 6/min de carteira não copiada" + (RP.skipped_bot ? " · " + f(RP.skipped_bot, 0) + " de robôs não copiados" : "")) : "") + row("Reconexões", "", f(RP.reconnects || 0, 0)) +
      "</tbody></table></div><p class=\"muted\" style=\"margin-top:8px\">Clique numa linha com › para ver as últimas 300 de cada tipo (motivo, carteira, transação).</p>";
  }
  const RPC_T = { falha: "Falhas de leitura", atrasado: "Atrasados (+2 min na fila)", nao_trade: "Não eram trade", trade: "Viraram trade" };
  const RPC_HELP = {
    falha: "O monitor pediu a transação ao RPC da Solana e não recebeu. HTTP 429 = o RPC público recusou por excesso de pedidos (limite grátis). 'result vazio' = a transação ainda não estava disponível. Cada falha tenta 4 vezes antes de desistir.",
    atrasado: "O aviso esperou mais de 2 minutos na fila antes de ser lido e foi descartado (copiar tão tarde não faz sentido). Se a maioria for de 'estudo / maiores traders', as cópias não são afetadas: elas têm fila própria.",
    nao_trade: "A transação foi lida, mas não era compra ou venda de token (transferência, criação de conta, etc.).",
    trade: "A transação virou compra ou venda. 'lido X s depois do aviso' mostra o atraso até o sistema saber do trade." };
  let SYS_SUB = null;
  async function openRpcLog(tipo) {
    SYS_SUB = tipo;
    $("sysMT").textContent = RPC_T[tipo] || tipo;
    $("sysMB").innerHTML = '<p class="muted">' + BB.loader("Carregando o status do sistema") + "</p>";
    let r; try { r = await BB.api("/api/pump/monitor/leituras?tipo=" + encodeURIComponent(tipo)); } catch (e) { r = { error: String(e) }; }
    if (SYS_SUB !== tipo) return;
    if (!r || r.error) { $("sysMB").innerHTML = '<p class="down">' + esc((r && r.error) || "erro") + '</p><button class="btn sm" data-rpcback="1">‹ Voltar</button>'; return; }
    const tm = (t) => t ? new Date(t * 1000).toLocaleTimeString("pt-BR") : "–";
    const sol = (s) => s ? '<a href="https://solscan.io/tx/' + encodeURIComponent(s) + '" target="_blank" rel="noopener noreferrer">' + esc(s.slice(0, 8)) + "…</a>" : "–";
    $("sysMB").innerHTML = '<div class="row" style="margin-bottom:10px"><button class="btn sm" data-rpcback="1">‹ Voltar ao status</button><button class="btn sm" data-rpclog="' + tipo + '">Atualizar</button></div>' +
      '<div class="help"><p>' + esc(RPC_HELP[tipo] || "") + "</p></div>" +
      '<p class="muted">Na fila agora: ' + r.fila.copiadas + " das copiadas · " + r.fila.outras + " das outras (estudo / maiores traders) · só memória, zera a cada atualização do sistema</p>" +
      '<h3 style="margin:12px 0 6px;font-size:13px">Por motivo (últimas ' + r.linhas.length + ")</h3><div class=\"tbl-wrap\"><table id=\"rlM\" class=\"systbl\"></table></div>" +
      (tipo === "falha" && r.motivos_falha_total.length ? '<h3 style="margin:12px 0 6px;font-size:13px">Cada tentativa que falhou (desde a atualização)</h3><div class="tbl-wrap"><table id="rlW" class="systbl"></table></div>' : "") +
      '<h3 style="margin:12px 0 6px;font-size:13px">Por carteira</h3><div class="tbl-wrap"><table id="rlC" class="systbl"></table></div>' +
      '<h3 style="margin:12px 0 6px;font-size:13px">Últimas leituras</h3><div class="tbl-wrap"><table id="rlL" class="systbl"></table></div>';
    table("rlM", ["Motivo", "Quantas"], r.motivos.map((m) => ['<span class="wrapcell">' + esc(m.motivo) + "</span>", String(m.n)]), "Nada registrado ainda.");
    if ($("rlW")) table("rlW", ["Motivo da tentativa", "Quantas"], r.motivos_falha_total.map((m) => [esc(m.motivo), String(m.n)]), "–");
    table("rlC", ["Carteira", "Tipo", "Quantas"], r.por_carteira.map((c) => [pfW(c.wallet), c.copiada ? '<span class="tag win">copiada</span>' : '<span class="tag neutral">estudo / maiores</span>', String(c.n)]), "–");
    table("rlL", ["Hora", "Carteira", "Copiada", "Motivo", "Detalhe", "Transação"], r.linhas.map((x) => [tm(x.t), pfW(x.wallet), x.copiada ? "sim" : "não",
      '<span class="wrapcell">' + esc(x.motivo) + "</span>", '<span class="wrapcell">' + esc(x.extra || "") + "</span>", sol(x.sig)]), "Nada registrado ainda.");
  }
  function openSys() {
    if (!SYS_HTML) return;
    SYS_SUB = null; $("sysMT").textContent = "Status do sistema";
    $("sysMS").textContent = "contando desde " + ((D && D.started_at) || "–") + " · os números zeram a cada atualização do sistema";
    $("sysMB").innerHTML = SYS_HTML();
    if ($("sysM").hidden) { $("sysM").hidden = false; $("sysMX").focus(); }
  }
  function render() {
    if (!D) return;
    const c = cfg(), R = D.real || {}, RP = D.rpc || {};
    const rm = realMode();
    document.querySelectorAll("#modeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.mode === (rm ? "real" : "sim")));
    document.querySelectorAll("[data-mtag]").forEach((e) => { e.textContent = rm ? "REAL" : "FICTÍCIA"; e.className = "tag " + (rm ? "real" : "sim"); });
    $("nbTr").textContent = (D.followed || []).length || "";
    $("nbPos").textContent = (D.positions || []).filter((p) => !!p.real === rm).length || "";
    $("nbReal").textContent = R.enabled ? "ON" : "";
    $("sysDot").className = "dot " + (RP.ws ? "on" : "off");
    $("sysT").textContent = "Monitor " + (RP.ws ? "ON" : "OFF");
    // 0.31.83 (sugestão do Bruxo): status completo do monitor embaixo do menu
    const PPs = D.status || {}, ago = (t) => t ? "há " + hms(Math.max(0, Date.now() / 1000 - t)) : "–";
    // 0.32.3 (sugestão do Bruxo, comparação com a plataforma antiga): os contadores recomeçam a cada atualização do sistema,
    // então mostra desde quando e por hora; o funil dos avisos da Solana e o estado de cada API (ok / não ok)
    const up = D.uptime_s || 0, perH = (n) => (up > 300 ? " (" + f((n || 0) / up * 3600, 0) + "/h)" : "");
    const okb = (ok, why) => (ok ? '<span class="up">ok</span>' : '<span class="down" title="' + esc(why || "") + '">não ok</span>');
    const A = D.apis || {}, RL = D.real || {};
    // 0.32.4 (pedido do dono: "está horrível ali"): no menu fica só uma linha; o status completo abre numa janela
    const probs = [["Solana RPC", RP.ws], ["PumpPortal", PPs.ws], ["Preços", !RP.price_error], ["Jupiter", (A.jupiter || {}).ok !== false],
      ["Solana Tracker", (A.solana_tracker || {}).ok], ["Banco", (A.banco || {}).ok !== false]].filter((x) => !x[1]).map((x) => x[0]);
    $("sysS").innerHTML = (RP.ws ? (RP.subs || 0) + " carteiras · " : "") + (probs.length ? '<span class="down">' + probs.length + " com problema</span>" : '<span class="up">tudo ok</span>') + " · detalhes";
    $("sysBox").title = probs.length ? "Com problema: " + probs.join(", ") : "Tudo ok · clique para ver o status completo";
    SYS_HTML = () => sysDetail(D, RP, PPs, A, RL, up, perH, okb, ago);
    if (!$("sysM").hidden && !SYS_SUB) openSys();
    // controles de configuração (inputs, liga/desliga)
    document.querySelectorAll("[data-cfg]").forEach((el) => { if (document.activeElement !== el) el.value = (isAutoCfg(el.dataset.cfg) ? autoValue(el.dataset.cfg, c) : c[el.dataset.cfg]) ?? ""; });
    // 0.31.70 (pedido do dono): campo em HORAS para uma opção guardada em minutos (ex.: tempo máximo das automáticas)
    document.querySelectorAll("[data-hcfg]").forEach((el) => { const v = isAutoCfg(el.dataset.hcfg) ? autoValue(el.dataset.hcfg, c) : c[el.dataset.hcfg];
      if (document.activeElement !== el && v != null) el.value = +(v / 60).toFixed(2);
      if (el.id === "exAutoHold" && v != null) $("exAutoHoldN").textContent = "= " + f(v, 0) + " min · máximo 24 h"; });
    document.querySelectorAll("[data-toggle]").forEach((b) => { const on = !!(isAutoCfg(b.dataset.toggle) ? autoValue(b.dataset.toggle, c) : c[b.dataset.toggle]); b.textContent = on ? "Ligado" : "Desligado"; b.classList.add("tgl", "sw"); b.setAttribute("role", "switch"); b.setAttribute("aria-checked", String(on)); b.classList.toggle("on", on); b.classList.toggle("off", !on); if (isAutoCfg(b.dataset.toggle)) b.setAttribute("aria-pressed", String(on)); });
    if (APPLIED.length && (VIEW === "config" || VIEW === "explorar")) { try { renderApplied(); } catch (e) { /* nunca derruba o painel */ } }
    $("delayN").textContent = (c.pump_copy_delay_s > 0 ? "só copia se o trader ainda estiver no token depois de " + c.pump_copy_delay_s + " s (entra no preço de então)" : "copia na hora") + ((D.pending || []).length ? " · " + D.pending.length + " aguardando" : "");
    $("trailN").textContent = "ex.: chegou a +" + c.pump_trail_start_pct + "% líquido → stop móvel ligado; subiu até +50% → sai se voltar a +" + Math.max(50 - c.pump_trail_dist_pct, c.pump_trail_min_lock_pct || 0) + "% (nunca abaixo de +" + (c.pump_trail_min_lock_pct || 0) + "%)";
    if ($("tcMoon")) { const a = c.pump_tp1_on ? +c.pump_tp1_frac_pct || 0 : 0, b = c.pump_tp1_on && +c.pump_tp2_pct ? +c.pump_tp2_frac_pct || 0 : 0;
      $("tcMoon").textContent = Math.max(0, 100 - a - b) + "%" + (c.pump_tp_pct > 0 ? " até o alvo fixo de +" + c.pump_tp_pct + "%" : " · segue no stop móvel"); }
    // 0.32.32 (pedido do dono): por que as automáticas do Explorar entram ou não na REAL
    if ($("exRealDiag") && VIEW === "explorar") {
      const R = D.real || {}, why = [];
      if (!R.wallet_configured) why.push('<span class="down">carteira real não configurada</span>');
      if (!R.enabled) why.push('<span class="down">Execução real desligada</span> (<a href="#real">Execução real</a>)');
      if (!c.pump_ex_real_on) why.push('<span class="down">"Também na carteira REAL" desligado</span>');
      if (c.pump_real_mirror === false && !c.pump_auto_real) why.push('<span class="down">espelho da real desligado</span>');
      const amtR = +c.pump_ar_real_sol > 0 ? Math.min(+c.pump_ar_real_sol, +c.pump_real_max_sol) : +c.pump_real_max_sol;
      const last = (D.feed || []).filter((e) => e.wallet === "manual" && /^REAL/.test(e.action || "")).slice(0, 3);
      $("exRealDiag").innerHTML = (why.length ? "A real NÃO entra agora: " + why.join(" · ") : '<span class="up">A real entra</span> junto com cada entrada automática, com ' + s4(amtR) + " SOL (máx. " + s4(c.pump_real_max_sol) + " por compra, " + (c.pump_real_max_open || 5) + " posições reais).") +
        (last.length ? "<br>Últimas na real: " + last.map((e) => esc((e.symbol || "?") + ": " + e.action + (e.reason ? " — " + e.reason : ""))).join(" · ") : "");
    }
    $("foot").textContent = "versão " + (D.version || "") + (D.started_at ? " · no ar desde " + D.started_at : "") + " · SOL $" + f(D.sol_usd, 2);
    if (VIEW === "visao") { renderOverview(); renderSummary(); if (DAY_MODE !== null && DAY_MODE !== realMode()) loadDaily(); }
    if (VIEW === "explorar" && XC.mode !== undefined && XC.mode !== realMode()) loadExCopy();
    if (VIEW === "config") renderAllCfgCopy();
    else if (VIEW === "traders") renderTraders();
    else if (VIEW === "posicoes") renderPositions();
    else if (VIEW === "historico") { renderHistory(); renderErrs(); }
    else if (VIEW === "relatorios" && (Date.now() - REP_AT > 30000 || REP_MODE !== realMode())) loadReports();
    else if (VIEW === "aprendizado" && (Date.now() - AP_AT > 60000 || AP_MODE !== realMode())) loadLearning();
    else if (VIEW === "radar") loadRadar(false);
    else if (VIEW === "explorar") { renderAutoState(); loadAutoTrades(false); }
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
      out.push({ at: t.closed_at, k, real: !!t.real, t: (t.symbol || "?") + " · " + r, m: "copiado de " + shortW(t.wallet, t), amt: sg(t.pnl_sol) + '<div class="m">' + pc(t.pnl_pct) + "</div>" });
    });
    (D.feed || []).forEach((e) => {
      const a = String(e.action || ""); let k = null;
      if (a === "copiou compra" || a === "REAL comprou") k = "buy"; else if (/falhou/.test(a)) k = "err"; else if (/pausad/.test(String(e.reason || ""))) k = "pause";
      if (k) out.push({ at: e.at, k, real: /REAL/.test(a), t: (e.symbol || "?") + " · " + (k === "buy" ? "copiou " + shortW(e.wallet, e) : e.reason), m: "trader " + shortW(e.wallet, e) + (e.sol != null ? " · ele usou " + s4(e.sol) + " SOL" : ""), amt: "" });
    });
    (D.paused || []).forEach((p) => out.push({ at: p.at, k: "pause", real: false, t: shortW(p.wallet, p) + " · " + (p.reason || "pausado"), m: p.until ? "volta em " + hms(p.until - Date.now() / 1000) : "até você retomar", amt: "" }));
    out.sort((a, b) => new Date(b.at) - new Date(a.at));
    const L = out.slice(0, 9);
    $("ops").innerHTML = L.length ? L.map((o) => '<div class="op"><div style="min-width:0"><div class="t">' + esc(o.t) + '</div><div class="m">há ' + agoIso(o.at) + " · " + esc(o.m) + '</div></div><div><div class="tags">' + opTag(o.k) + (o.real ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>') + '</div><div class="amt">' + o.amt + "</div></div></div>").join("")
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
      ["Compra automática", c.pump_auto_on ? [c.pump_auto_boost ? "boost" : "", c.pump_auto_chance ? "chance alta" : ""].filter(Boolean).join(" + ") || "sem regra" : "desligada", st(!!c.pump_auto_on)],
      ["Lista negra", c.pump_blacklist_on ? "não copia" : "desligada", st(!!c.pump_blacklist_on)], ["Telegram", c.pump_tg_on ? (c.pump_tg_all ? "tudo" : "só importantes") : "desligado", st(!!c.pump_tg_on)],
      ["Sair quando o dev vende", c.pump_exit_dev_sell ? "ligado" : "desligado", st(!!c.pump_exit_dev_sell)], ["Sair quando gradua", c.pump_exit_migrate ? "ligado" : "desligado", st(!!c.pump_exit_migrate)],
      ["Sair com pressão virando", c.pump_exit_pressure_on ? "< " + n(c.pump_exit_pressure_pct) + "%" : "OFF", st(!!c.pump_exit_pressure_on)], ["Sair com outras vendendo", c.pump_exit_kol_on ? n(c.pump_exit_kol_n) + " carteiras" : "OFF", st(!!c.pump_exit_kol_on)],
      ["Nota mínima", c.pump_score_min_on ? n(c.pump_score_min) : "OFF", st(!!c.pump_score_min_on)], ["Valor pela nota", c.pump_size_by_score ? "ligado" : "desligado", st(!!c.pump_size_by_score)],
      ["Pausa por perdas seguidas", c.pump_streak_on ? n(c.pump_streak_n) + " → " + n(c.pump_streak_h) + " h" : "OFF", st(!!c.pump_streak_on)], ["Mercado frio", c.pump_cold_on ? "< " + n(c.pump_cold_wr) + "%" : "OFF", st(!!c.pump_cold_on)],
      ["Posições máx.", "fictício " + n(c.pump_max_open) + " · real " + n(c.pump_real_max_open), ""], ["Perda máx. no dia (real)", n(c.pump_real_daily_loss_sol) + " SOL", st(c.pump_real_daily_loss_sol > 0)], ["Período do top", n(c.pump_lb_days) + " dias", ""]];
    // opções da tela "Opções novas de cópia" (menu Usar ou descartar) só aparecem para o admin (0.17.3)
    const NOVAS = ["Compra automática", "Lista negra", "Telegram", "Sair quando o dev vende", "Sair quando gradua", "Sair com pressão virando", "Sair com outras vendendo", "Nota mínima", "Valor pela nota", "Pausa por perdas seguidas", "Mercado frio", "Venda em partes", "Sair antes da graduação", "Pressão de compra mín.", "Velocidade mín. da curva", "Token já graduado", "Valor conforme o trader", "Preço subiu desde o trader (máx.)", "Risco do token máx."];
    $("cfgS").innerHTML = it.filter((x) => (ME && ME.role === "admin") || !NOVAS.includes(x[0])).map((x) => '<div><span class="k">' + x[0] + '</span><span class="v">' + esc(x[1]) + x[2] + "</span></div>").join("");
  }

  // ------------------------------------------------------------------ top traders
  const ST = { online: '<span class="tag win">● online</span>', inativo: '<span class="tag pause">● inativo</span>', "sem atividade": '<span class="tag neutral">○ sem atividade</span>', robô: '<span class="tag loss">robô</span>' };
  function stat(a, last) {
    a = a || {};
    if (a.status === "sem atividade" && last) { const s = (Date.now() - last) / 1000; return (s < 600 ? ST.online : s < 86400 ? ST.inativo : ST["sem atividade"]) + "<small>último trade há " + hms(s) + "</small>"; }
    return (ST[a.status] || "–") + (a.bot_reason ? "<small>" + esc(a.bot_reason) + "</small>" : a.last ? "<small>tx há " + agoT(a.last) + (a.pump_last ? " · pump há " + agoT(a.pump_last) : "") + "</small>" : "");
  }
  let LBOFF = "copiados";            // quadro "Traders inativos": copiados (padrão) ou todos do ranking
  function renderTraders() {
    const c = cfg(), L = D.leaderboard || [], ls = D.lb_status || {};
    document.querySelectorAll("#lbDays button").forEach((b) => b.classList.toggle("on", +b.dataset.d === +(c.pump_lb_days || 7)));
    $("lbKey").hidden = !!ls.key_set;
    $("lbSub").textContent = ls.key_set ? L.length + " traders · Solana Tracker (app pump.fun)" + (ls.own_key === false ? " · usando a chave do sistema (visualização)" : "") + (ls.at ? " · atualizado há " + agoIso(ls.at) : "") + " · copiando pelo " + (ls.source || "") : "precisa da chave grátis da Solana Tracker";
    // 0.32.43 (pedido do dono): aqui só os traders ATIVOS (online); os inativos ficam no quadro "Traders inativos" mais abaixo
    const lbRow = (r) => [String(r.rank), pfW(r.wallet, r) + (r.name ? "<small>" + esc(r.name) + "</small>" : ""), stat(r.act, r.last_trade),
      r.wallet_usd == null ? '<span class="dim">…</span>' : usd(r.wallet_usd), usdS(r.realized_usd), r.roi == null ? "–" : pc(r.roi, 0), r.winrate == null ? "–" : f(r.winrate, 0) + "%", r.trades == null ? "–" : String(r.trades), r.tokens == null ? "–" : String(r.tokens), r.days_active == null ? "–" : String(r.days_active), r.last_trade ? agoIso(r.last_trade) : "–",
      r.paused ? '<span class="tag pause">Pausado</span>' : r.followed ? '<span class="tag win">Copiando</span>' : r.eligible ? (c.pump_only_online && !r.online ? '<span class="tag pause">Apto · fora (inativo)</span>' : '<span class="tag neutral">Apto</span>') : '<span class="dim" style="white-space:normal;display:block;max-width:260px">' + esc((r.flags || []).join(" · ")) + "</span>",
      r.paused ? btn("Retomar", "w", { a: "resume", w: r.wallet }, "tgl on") : r.followed ? btn("Pausar", "w", { a: "pause", w: r.wallet }) : r.manual ? "" : btn("Copiar", "w", { a: "add", w: r.wallet })];
    const LBCOLS = ["#", "Trader", "Status", "Saldo", "Lucro", "ROI", "Acerto", "Trades", "Tokens", "Dias", "Último trade", "Situação", ""];
    const isOn = (r) => !!r.online && !((r.act || {}).status === "robô");
    const LA = L.filter(isOn), LO = L.filter((r) => !isOn(r));
    table("tLb", LBCOLS, LA.map(lbRow),
      ls.key_set ? (ls.error ? '<span class="down">Erro da Solana Tracker: ' + esc(ls.error) + "</span>" : (L.length ? "Nenhum trader do ranking está ativo agora (negociou nos últimos " + (c.pump_online_min || 10) + " min). Os inativos estão no quadro abaixo; assim que algum voltar a negociar, ele aparece aqui." : BB.loader("Buscando o ranking"))) : "A lista aparece assim que a chave da Solana Tracker for salva.");
    const Fall = D.followed || [], fOff = Fall.filter((r) => ((r.act || {}).status !== "online") && !(L.find((x) => x.wallet === r.wallet && x.online)));
    const topA = LA.filter((r) => r.top_active).length, nTop = c.pump_top_n || 10;
    $("lbAct").innerHTML = '<span class="tag win">● ' + LA.length + " ativos agora</span> " + '<span class="tag neutral">copiando ' + topA + " de " + nTop + " vagas dos top ativos</span> " +
      (LO.length || fOff.length ? '<button class="btn sm chip" data-lboff="1">' + LO.length + " inativos no ranking · " + fOff.length + " copiados inativos ↓</button>" : "") + (c.pump_only_online ? "" : ' <span class="tag pause">"Só copiar traders online" está desligado</span>');
    // quadro dos inativos: copiados que estão inativos (padrão) ou todos os inativos do ranking
    document.querySelectorAll("#lbOffSeg button").forEach((b) => b.classList.toggle("on", b.dataset.off === LBOFF));
    $("lbOffSub").textContent = LBOFF === "copiados" ? fOff.length + " carteiras copiadas sem negociar nos últimos " + (c.pump_online_min || 10) + " min · manuais, do estudo e quem ainda tem posição aberta continuam copiadas" : LO.length + " traders do ranking inativos agora · voltam para a lista de cima quando negociarem";
    if (LBOFF === "copiados") table("tLbOff", ["Carteira", "Origem", "Última transação", "Lucro (top)", "Copiado", "Por que ainda copia", "Ações"], fOff.map((r) => { const a = r.act || {}, lb = r.lb || {}, cp = r.copied, held = (D.positions || []).some((p) => p.wallet === r.wallet);
        return [pfW(r.wallet, r), r.manual ? (r.ia_sim ? '<span class="tag pause">Manual · IA · só fictícia</span>' : '<span class="tag pause">Manual</span>') : '<span class="tag neutral">' + esc(r.source || "") + "</span>",
          a.last ? "há " + agoT(a.last) : '<span class="dim">nenhuma desde a conexão</span>', lb.realized_usd != null ? usdS(lb.realized_usd) : "–", cp ? sg(cp.pnl_sol) + "<small>" + cp.n + " trades</small>" : '<span class="dim">–</span>',
          held ? "tem posição aberta (para copiar a venda)" : r.manual ? "carteira manual (você ou a IA adicionou)" : "–",
          (r.manual ? btn("Tirar", "w", { a: "remove", w: r.wallet }) + " " : "") + btn("Pausar", "w", { a: "pause", w: r.wallet })]; }), "Nenhuma carteira copiada está inativa.");
    else table("tLbOff", LBCOLS, LO.map(lbRow), "Nenhum trader do ranking está inativo.");
    $("lbNote").innerHTML = (ls.error && ls.key_set && L.length ? '<span class="down">Erro da Solana Tracker: ' + esc(ls.error) + "</span><br>" : "") + "Ranking por lucro realizado em US$ no período. Os " + (c.pump_top_n || 10) + " melhores aptos e ATIVOS são copiados, em vagas próprias (as carteiras manuais não tiram essas vagas). Só copia quem tem acerto ACIMA de " + (c.pump_min_winrate || 50) + "% e pelo menos " + (c.pump_lb_min_trades || 0) + " trades no período. Robôs, devs de token e corretoras ficam de fora. " + (c.pump_only_online ? "Só copia quem está ONLINE (negociou nos últimos " + (c.pump_online_min || 10) + " min): a cada 10 min quem ficou inativo sai e entra o melhor do top que estiver online. " : "") + "O ranking é consultado a cada 10 min.";
    const F = (D.followed || []).filter((r) => !fOff.includes(r));
    $("folSub").textContent = F.length + " ativas agora" + (fOff.length ? " · " + fOff.length + " copiadas inativas no quadro Traders inativos" : "") + ((D.paused || []).length ? " · " + D.paused.length + " pausadas" : "") + " · manuais primeiro";
    table("tFol", ["#", "Carteira", "Origem", "Status", "Última transação", "Trades pump.fun", "Fora da pump.fun", "Lucro (top)", "Copiado", "Ações"],
      F.map((r, i) => { const cp = r.copied, a = r.act || {}, lb = r.lb || {}; return [String(i + 1), pfW(r.wallet, r), r.manual ? (r.ia_sim ? '<span class="tag pause" title="Aprovada pelo estudo automático: copiada só na carteira fictícia">Manual · IA · só fictícia</span>' : '<span class="tag pause">Manual</span>') : r.source === "leaderboard" ? '<span class="tag win">Top #' + lb.rank + "</span>" : '<span class="tag neutral">Ranking próprio</span>',
        (ST[a.status] || "–") + (a.bot_reason ? "<small>" + esc(a.bot_reason) + "</small>" : a.tx_min ? "<small>" + a.tx_min + " tx/min</small>" : ""), a.last ? "há " + agoT(a.last) + (a.pump_last ? "<small>pump.fun há " + agoT(a.pump_last) + "</small>" : "") : '<span class="dim">nenhuma desde a conexão</span>',
        String(a.pump || 0), a.other ? a.other + " tx<small>" + (r.other_copied || 0) + " de token · " + (r.ignored || 0) + " ignoradas</small>" : "0", lb.realized_usd != null ? usdS(lb.realized_usd) + "<small>" + (lb.winrate != null ? f(lb.winrate, 0) + "% acerto" : "") + "</small>" : "–",
        cp ? sg(cp.pnl_sol) + "<small>" + cp.n + " trades</small>" : '<span class="dim">–</span>',
        (r.manual ? btn("Tirar", "w", { a: "remove", w: r.wallet }) + " " : "") + btn("Pausar", "w", { a: "pause", w: r.wallet }) + " " + btn("Banir", "w", { a: "ban", w: r.wallet }, "tgl off")]; })
        .concat((D.paused || []).map((r) => { const a = r.act || {}, lb = r.lb || {}, cp = r.copied; return ["–", pfW(r.wallet, r), '<span class="tag pause">⏸ Pausado</span>', ST[a.status] || "–", esc(r.reason || "") + "<small>" + (r.until ? "volta em " + hms(r.until - Date.now() / 1000) : "até você retomar") + "</small>", "–", "–", lb.realized_usd != null ? usdS(lb.realized_usd) : "–", cp ? sg(cp.pnl_sol) : "–", btn("Retomar", "w", { a: "resume", w: r.wallet }, "tgl on")]; })),
      fOff.length ? "Nenhuma carteira copiada está ativa agora. As " + fOff.length + " copiadas inativas estão no quadro Traders inativos, logo abaixo." : "Nenhum trader copiado ainda — salve a chave da Solana Tracker ou adicione uma carteira manual.");
    // monitor
    document.querySelectorAll("#monSeg button").forEach((b) => b.classList.toggle("on", b.dataset.f === MONF));
    const RP = D.rpc || {}, Lv = (D.live || []).filter((e) => MONF === "all" || e.kind === MONF);
    $("monSub").innerHTML = (RP.ws ? '<span class="up">● conectado</span>' : '<span class="down">● desconectado</span>') + " · " + Fall.length + " carteiras · " + (D.live || []).length + " eventos";
    const AC = { entrou: '<span class="tag win">Entrou</span>', aumentou: '<span class="tag win">Aumentou</span>', saiu: '<span class="tag loss">Saiu</span>', "vendeu parte": '<span class="tag pause">Vendeu parte</span>' };
    table("tMon", ["Hora", "Há", "Trader", "Ação", "Token", "SOL", "Preço", "Mcap", "Resultado dele", ""], Lv.map((e) => [dt(e.t * 1000), agoT(e.t), pfW(e.wallet, e), AC[e.action] || esc(e.action), pfM(e.mint, e.symbol), s4(e.sol), ex(e.price), e.mcap_sol == null ? "–" : f(e.mcap_sol, 0) + " SOL",
      e.kind === "sell" ? (e.pnl_pct == null ? '<span class="dim">entrada não vista</span>' : pc(e.pnl_pct)) + (e.sold_pct != null ? "<small>" + e.sold_pct + "% da posição</small>" : "") : '<span class="dim">–</span>', tx(e.signature)]),
      Fall.length ? "Aguardando a próxima compra ou venda dos traders copiados…" : "Nenhum trader copiado ainda.");
    table("tTP", ["Trader", "Token", "Investiu", "Preço médio", "Agora", "Variação", "Valor", "Mcap", "Segurando há"], (D.trader_pos || []).map((p) => [pfW(p.wallet, p), pfM(p.mint, p.symbol) + (p.dev ? ' <span class="tag pause" title="Esta carteira CRIOU o token: o valor é a compra do criador no lançamento. O robô não copia lançamentos, só compras em tokens que já existem.">criou o token</span>' : ""), s4(p.invested_sol) + " SOL", ex(p.avg_price), ex(p.price), pc(p.chg_pct), p.value_sol == null ? "–" : s4(p.value_sol) + " SOL", p.mcap_sol == null ? "–" : f(p.mcap_sol, 0) + " SOL", hms(p.held_s)]),
      "Nenhuma posição aberta vista ainda (aparece quando um trader copiado compra).");
    // ranking próprio
    const rr = D.ranking || [];
    $("rkSub").textContent = rr.length + " carteiras com ≥ " + c.pump_min_closed + " tokens fechados em " + (c.pump_rank_hours || 24) + " h";
    table("tRk", ["Carteira", "Lucro 24h", "Acerto", "Segura", "Trades/h", "Abertos", "Situação", ""], rr.slice(0, 40).map((r) => [pfW(r.wallet, r), sg(r.pnl_sol), f(r.winrate, 0) + "% (" + r.wins + "/" + r.closed + ")", hms(r.hold_s), String(r.trades_h), String(r.open),
      r.followed ? '<span class="tag win">Copiando</span>' : r.eligible ? '<span class="tag neutral">Apta</span>' : '<span class="dim">' + esc((r.flags || []).join(" · ")) + "</span>", r.followed ? "" : btn("Copiar", "w", { a: "add", w: r.wallet })]),
      "O ranking próprio enche com o tempo (ele precisa ver os trades de todos os tokens novos).");
    $("rkNote").innerHTML = (D.paid_stream ? "" : "<b>Sem dados:</b> o ranking próprio precisa ver os trades de todos os tokens novos, e a PumpPortal cobra por isso. Por isso o bot copia pelos Top traders acima. ") + "Filtros: acerto ≥ " + c.pump_min_winrate + "%, segura ≥ " + c.pump_min_hold_s + " s (abaixo disso é robô sniper), até " + c.pump_max_trades_h + " trades/h, sem dev." +
      ((D.banned || []).length ? "<br>Banidas: " + D.banned.map((w) => pfW(w) + " " + btn("liberar", "w", { a: "unban", w: w })).join(" · ") : "");
  }

  // ------------------------------------------------------------------ posições / histórico / feed
  // ------------------------------------------------------------------ card de posição (0.32.40)
  const POS_OPEN = new Set();          // "Mais detalhes" abertos continuam abertos quando a tela atualiza (a cada 2 s)
  document.addEventListener("toggle", (e) => { const d = e.target; if (d && d.classList && d.classList.contains("pc-more")) { if (d.open) POS_OPEN.add(d.dataset.pid); else POS_OPEN.delete(d.dataset.pid); } }, true);
  function posSpark(p) {
    const pts = (p.snaps || []).filter((x) => x.chg != null).map((x) => [x.min, x.chg]);
    const open = p.open_t || (p.opened_at ? new Date(p.opened_at).getTime() / 1000 : null);
    if (open && p.chg_pct != null) pts.push([(Date.now() / 1000 - open) / 60, p.chg_pct]);
    if (pts.length < 2) return "";
    pts.unshift([0, 0]);
    const W = 96, H = 30, x0 = pts[0][0], x1 = pts[pts.length - 1][0] || 1, ys = pts.map((q) => q[1]);
    let lo = Math.min(0, ...ys), hi = Math.max(0, ...ys); if (hi - lo < 1) hi = lo + 1;
    const X = (v) => ((v - x0) / (x1 - x0 || 1)) * (W - 2) + 1, Y = (v) => H - 2 - ((v - lo) / (hi - lo)) * (H - 4);
    const d = pts.map((q, k) => (k ? "L" : "M") + X(q[0]).toFixed(1) + " " + Y(q[1]).toFixed(1)).join(" ");
    return '<svg class="pc-spark ' + ((p.chg_pct || 0) >= 0 ? "up" : "down") + '" viewBox="0 0 ' + W + " " + H + '" aria-hidden="true"><line x1="0" x2="' + W + '" y1="' + Y(0).toFixed(1) + '" y2="' + Y(0).toFixed(1) + '"/><path d="' + d + '"/></svg>';
  }
  function posCard(p, c) {
    const open = p.open_t || (p.opened_at ? new Date(p.opened_at).getTime() / 1000 : null), now = Date.now() / 1000;
    const chg = p.chg_pct, pnl = p.pnl_now_sol, up = (pnl != null ? pnl : chg || 0) >= 0;
    // regras que valem nesta posição (as dela; senão as gerais da conta)
    const stopV = p.stop_pct != null ? p.stop_pct : c.pump_stop_pct, stopOff = !!p.off_stop || !stopV;
    const trOn = (p.trail_on != null ? p.trail_on : c.pump_trail_enabled) && !p.off_trail;
    const trS = p.trail_start != null ? p.trail_start : c.pump_trail_start_pct, trD = p.trail_dist != null ? p.trail_dist : c.pump_trail_dist_pct;
    const tp1 = p.tp1_pct != null ? p.tp1_pct : (c.pump_tp1_on ? c.pump_tp1_pct : null), tp1F = p.tp1_frac != null ? (p.tp1_frac <= 1 ? p.tp1_frac * 100 : p.tp1_frac) : c.pump_tp1_frac_pct;
    const tpV = p.tp_pct != null ? p.tp_pct : c.pump_tp_pct;
    // faixa: stop (esquerda) … 0 … alvo (direita), com o agora e o pico
    const lo = stopOff ? Math.min(-50, (p.worst_pct || 0) * 1.1) : -stopV;
    const hi = Math.max(tpV || 0, tp1 || 0, trS || 0, (p.best_pct || 0) * 1.1, (chg || 0) * 1.1, 30);
    const at = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)).toFixed(1);
    const range = chg == null ? "" : '<div class="pc-range" title="faixa entre o stop de perda e o alvo; ● = agora, ▲ = pico">' +
      '<div class="pc-bar"><span class="pc-zero" style="left:' + at(0) + '%"></span>' +
      (p.trail_exit != null ? '<span class="pc-trx" style="left:' + at(p.trail_exit) + '%" title="stop móvel: sai em +' + f(p.trail_exit, 1) + '%"></span>' : "") +
      (p.best_pct != null ? '<span class="pc-peak" style="left:' + at(p.best_pct) + '%" title="pico ' + f(p.best_pct, 1) + '%"></span>' : "") +
      '<span class="pc-now ' + (chg >= 0 ? "up" : "down") + '" style="left:' + at(chg) + '%"></span></div>' +
      '<div class="pc-rl"><span>' + (stopOff ? "sem stop" : "stop −" + f(stopV, 0) + "%") + "</span><span>" + (tpV ? "alvo +" + f(tpV, 0) + "%" : p.best_pct != null ? "pico " + pc(p.best_pct) : "") + "</span></div></div>";
    // tempo de saída
    const h = p.hold_s, rest = h != null && open ? h - (now - open) : null;
    const leftTxt = h == null || !open ? "–" : h >= 3e8 ? '<b class="up">sem limite</b>' : rest > 0 ? "<b>" + hms(rest) + "</b>" : '<b class="down">vencido · saindo</b>';
    const sw = (regra, off) => btn(off ? "OFF" : "ON", "prule", { id: p.id, regra: regra, on: off ? 1 : 0 }, "tgl sw " + (off ? "off" : "on"));
    const rule = (nome, val, ctl) => '<div class="pc-rule"><div><b>' + nome + "</b><small>" + val + "</small></div>" + ctl + "</div>";
    const tags = (p.real ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>') + (p.hold_profit ? ' <span class="tag pause" title="desde ' + esc(dt(p.hold_since)) + '">Segurando até lucro</span>' : "") + (p.selling ? ' <span class="tag pause">Vendendo…</span>' : "") + (p.trail_peak != null ? ' <span class="tag trail">Stop móvel armado</span>' : "");
    const st = (k, v) => "<div><dt>" + k + "</dt><dd>" + v + "</dd></div>";
    const v = p.vol || {};
    const sells = (p.sells || []).map((x) => "<li>" + dt(x.at) + " · " + f((x.frac || 0) * 100, 0) + "% · " + s4(x.sol) + " SOL" + (x.why ? " · " + esc(x.why) : "") + "</li>").join("");
    const id = String(p.id);
    return '<article class="pcard ' + (up ? "is-up" : "is-down") + (p.real ? " is-real" : "") + '" data-pid="' + esc(id) + '">' +
      '<header class="pc-h"><div class="pc-tk">' + pfM(p.mint, p.symbol) + " " + tags + '</div><button class="btn sm ghost" data-posdet="' + esc(id) + '">Detalhes</button>' +
      '<div class="pc-sub">' + pfW(p.wallet, p) + ' · aberta há <b>' + agoIso(p.opened_at) + "</b></div></header>" +
      '<div class="pc-box"><div><small>Ganho agora</small><b class="pc-big ' + (up ? "up" : "down") + '">' + (pnl == null ? "–" : (pnl > 0 ? "+" : "") + s4(pnl) + " SOL") + "</b><small>" + (p.pnl_now_pct == null ? "" : pc(p.pnl_now_pct) + " do investido") + "</small></div>" +
      '<div class="pc-var"><small>Variação</small><b>' + pc(chg) + "</b>" + posSpark(p) + "</div></div>" + range +
      '<dl class="pc-grid">' + st("Investido", s4(p.sol_in) + " SOL") + st("Vale agora", p.value_sol == null ? "–" : s4(p.value_sol) + " SOL") +
      st("Já vendido", s4(p.proceeds || 0) + " SOL") + st("Melhor / pior", pc(p.best_pct) + " / " + pc(p.worst_pct)) +
      st("Mcap", (p.mcap_in ? f(p.mcap_in, 0) : "–") + " → " + (p.mcap_now ? f(p.mcap_now, 0) : "–") + " SOL") + st("Volume 1 h", v.h1 == null ? "–" : uk(v.h1) + ' <span class="dim">' + (v.buys_h1 || 0) + "c/" + (v.sells_h1 || 0) + "v</span>") + "</dl>" +
      '<div class="pc-sec"><div><small>Sai por tempo em</small>' + leftTxt + (h != null && h < 3e8 ? '<small class="dim">limite ' + hms(h) + "</small>" : "") + "</div>" +
      (p.selling ? "" : '<div class="pc-chips">' + btn("+30 min", "hold", { id: p.id, add: 30 }, "chip") + btn("+1 h", "hold", { id: p.id, add: 60 }, "chip") + btn("Sem limite", "hold", { id: p.id, add: "none" }, "chip") + "</div>") + "</div>" +
      (p.selling ? "" : '<div class="pc-rules">' +
        rule("Stop de perda", stopOff ? "desligado nesta posição" : "sai em −" + f(stopV, 0) + "%", sw("stop", stopOff)) +
        rule("Stop móvel", !trOn ? "desligado nesta posição" : p.trail_peak != null ? "armado · pico " + f(p.trail_peak, 1) + "% · sai em +" + f(p.trail_exit, 1) + "%" : "liga em +" + f(trS, 0) + "% · sai " + f(trD, 0) + " pts abaixo do pico", sw("trail", !trOn)) +
        rule("Venda em partes", p.tp1_done ? "já vendeu " + f(tp1F, 0) + "% em +" + f(tp1, 0) + "%" : tp1 ? "vende " + f(tp1F, 0) + "% em +" + f(tp1, 0) + "%" : "sem venda em partes", p.tp1_done ? '<span class="tag win">feita</span>' : sw("tp1", !!p.off_tp1 || !tp1)) + "</div>") +
      (p.selling ? "" : '<div class="pc-act">' + btn("Vender 25%", "close", { id: p.id, real: p.real ? 1 : 0, frac: 0.25 }, "pill") + btn("Vender 50%", "close", { id: p.id, real: p.real ? 1 : 0, frac: 0.5 }, "pill") +
        btn(p.real ? "Vender tudo" : "Fechar 100%", "close", { id: p.id, real: p.real ? 1 : 0, frac: 1 }, "pill no") + "</div>") +
      (p.sell_error ? '<div class="pc-err down">' + esc(p.sell_error) + "</div>" : "") +
      '<details class="pc-more" data-pid="' + esc(id) + '"' + (POS_OPEN.has(id) ? " open" : "") + "><summary>Mais detalhes</summary>" +
      '<dl class="pc-grid">' + st("Preço de entrada", ex(p.price_in)) + st("Preço agora", ex(p.price_now || p.price_in) + (p.price_at ? ' <span class="dim">há ' + agoT(p.price_at) + "</span>" : "")) +
      st("Taxas pagas", p.fees_sol == null ? "–" : s4(p.fees_sol) + " SOL") + st("Nota da entrada", p.score == null ? "–" : f(p.score, 0) + " / 100") +
      st("Atraso na cópia", p.lag_s == null ? "–" : f(p.lag_s, 1) + " s") + st("Volume 5 min / 24 h", uk(v.m5) + " / " + uk(v.h24)) +
      st("Onde comprou", esc(p.venue_in || "–")) + st("Antes da entrada", p.antes ? f(p.antes.pos_pct, 0) + "% da faixa de 15 min" : "sem dado") + "</dl>" +
      (p.auto && p.auto !== true ? '<p class="pc-why">' + esc(p.auto) + "</p>" : "") +
      (sells ? '<p class="pc-lbl">Vendas parciais</p><ul class="pc-list">' + sells + "</ul>" : "") +
      ((p.snaps || []).length ? '<p class="pc-lbl">Fotos a cada 15 min</p><p class="pc-why">' + p.snaps.map((x) => x.min + " min: " + (x.chg == null ? "–" : (x.chg > 0 ? "+" : "") + f(x.chg, 1) + "%")).join(" · ") + "</p>" : "") +
      "</details></article>";
  }
  function renderPositions() {
    const c = cfg(), rm = realMode(), P = (D.positions || []).filter((p) => !!p.real === rm);
    $("posSub").textContent = (rm ? "REAL · " : "FICTÍCIO · ") + P.length + " de " + (rm ? c.pump_real_max_open : c.pump_max_open) + " · " + s4(rm ? c.pump_real_max_sol : c.pump_copy_sol) + " SOL cada" + (rm ? " (valores medidos na carteira)" : " · slippage extra " + c.pump_extra_slip_pct + "%") + " · variação já líquida de taxas";
    const vol = (p) => { const v = p.vol; if (!v) return '<span class="dim">aguardando</span>'; return "<b>" + uk(v.h1) + '</b> <span class="dim">1 h</span><small>5 min ' + uk(v.m5) + " · 24 h " + uk(v.h24) + "</small><small>" + (v.buys_h1 || 0) + " compras · " + (v.sells_h1 || 0) + " vendas</small>"; };
    // 0.31.69 (sugestão do Bruxo): quanto falta para a saída por tempo máximo e botões para estender esta posição
    const left = (p) => {
      const h = p.hold_s, open = p.open_t || (p.opened_at ? new Date(p.opened_at).getTime() / 1000 : null);
      if (h == null || !open) return "–";
      if (h >= 3e8) return '<span class="tag win">sem limite</span>' + holdBtns(p);
      const rest = h - (Date.now() / 1000 - open);
      const src = p.hold_src === "posição" ? (p.auto ? ' <a href="#explorar">Explorar → Proteções</a>' : " desta posição") : ' <a href="#config">Configurações</a>';
      return (rest > 0 ? "<b>faltam " + hms(rest) + "</b>" : '<b class="down">vencido · saindo</b>') + "<small>limite " + hms(h) + " ·" + src + "</small>" + holdBtns(p);
    };
    // 0.31.87 (Bruxo, áudio de 28/10): desligar stop de perda, stop móvel e venda em partes só desta posição
    const ruleBtn = (p, regra, nome, off) => btn(nome, "prule", { id: p.id, regra: regra, on: off ? 1 : 0 }, off ? "tgl sw off" : "tgl sw on");
    const holdBtns = (p) => p.selling ? "" : '<span class="row" style="gap:4px;margin-top:4px">' + btn("+30 min", "hold", { id: p.id, add: 30 }) + btn("+1 h", "hold", { id: p.id, add: 60 }) + btn("Sem limite", "hold", { id: p.id, add: "none" }) + "</span>" +
      '<span class="row" style="gap:4px;margin-top:4px;flex-wrap:wrap">' + ruleBtn(p, "stop", "Stop de perda", p.off_stop) + ruleBtn(p, "trail", "Stop móvel", p.off_trail) + ruleBtn(p, "tp1", "Venda em partes", p.off_tp1 || p.tp1_done) + "</span>";
    // 0.31.87 (Bruxo): venda parcial aparece na posição (quanto, quando, em quanto de lucro)
    const soldCell = (p) => !(p.sells || []).length ? "–" : s4(p.proceeds) + " SOL" + p.sells.map((s) => "<small>" + dt(s.at) + " · " + f((s.frac || 0) * 100, 0) + "% · " + s4(s.sol) + " SOL" + (s.why ? '<span class="wrapcell"> · ' + esc(s.why) + "</span>" : "") + "</small>").join("");
    // 0.32.28 (pedido do dono: "diminuir a rolagem, deixar só o principal e um botão para abrir o resto"): linha curta com o
    // ganho do momento; o resto (preços, volume, vendas, tempo de saída e regras desta posição) fica na janela Detalhes
    const tags = (p) => (p.trail_peak != null ? '<span class="tag trail" title="pico ' + f(p.trail_peak, 1) + "% · sai em +" + f(p.trail_exit, 1) + '%">Stop móvel</span>' : "") + (p.hold_profit ? '<span class="tag pause" title="desde ' + esc(dt(p.hold_since)) + '">Segurando até lucro</span>' : "") + (p.selling ? '<span class="tag pause">Vendendo…</span>' : "");
    const leftShort = (p) => { const h = p.hold_s, open = p.open_t || (p.opened_at ? new Date(p.opened_at).getTime() / 1000 : null); if (h == null || !open) return "–"; if (h >= 3e8) return "sem limite"; const rest = h - (Date.now() / 1000 - open); return rest > 0 ? "em " + hms(rest) : '<b class="down">saindo</b>'; };
    POS_DET = { list: P, left, soldCell, vol, holdBtns };
    // 0.32.40 (pedido do dono: "no celular fica ruim de ver"): cada posição vira um card com tudo à vista —
    // ganho e variação ao vivo, faixa stop ↔ alvo, tempo de abertura e de saída e os botões de alteração.
    $("posCards").innerHTML = P.length ? P.map((p) => posCard(p, c)).join("") : '<div class="empty">' + (rm ? "Nenhuma posição REAL aberta." : "Nenhuma posição aberta. Quando um trader copiado comprar, a cópia aparece aqui.") + "</div>";
    if (!$("posM").hidden && POS_ID != null) openPosDet(POS_ID, true);
    // 0.32.33 (pedido do dono): as que acabaram de fechar, com o motivo (stop, alvo, tempo…)
    if ($("tClosedNow")) table("tClosedNow", ["Fechou", "Token", "Origem", "Investido", "Resultado", "%", "Segurou", "Motivo"], (D.recent_closed || []).filter((t) => !!t.real === rm).map((t) => [dt(t.closed_at), pfM(t.mint, t.symbol), pfW(t.wallet, t), s4(t.sol_in) + " SOL", "<b>" + sg(t.pnl_sol) + "</b>", pc(t.pnl_pct), hms(t.hold_s),
      '<span class="wrapcell">' + esc(t.reason || "") + "</span>"]), "Nenhuma posição fechou nas últimas 3 h.");
  }
  function renderHistory() {
    const rm = realMode(), T = (D.trades || []).filter((t) => !!t.real === rm);
    $("trSub").textContent = T.length + " trades · líquido = depois de TODAS as taxas (pump.fun/PumpSwap, PumpPortal, rede) e do slippage";
    const fee = (t) => { const fp = t.fee_parts || {}; if (t.fees_sol == null) return "–"; const tip = "pump.fun/PumpSwap: " + s4(fp.platform) + " · PumpPortal: " + s4(fp.portal) + " · rede: " + s4(fp.network) + (fp.slippage ? " · slippage: " + s4(fp.slippage) : ""); return '<span title="' + esc(tip) + '">' + s4(t.fees_sol) + " SOL</span><small>" + (t.sol_in ? f((t.fees_sol / t.sol_in) * 100, 1) + "% do investido" : "") + "</small>"; };
    table("tTr", ["Fechou", "Token", "Aba · origem", "Investido", "Recebido", "Taxas", "Bruto", "Líquido", "%", "Segurou", "Motivo", "Tipo"], T.map((t) => [dt(t.closed_at), pfM(t.mint, t.symbol) + (t.venue ? "<small>" + esc(t.venue) + "</small>" : ""), pfW(t.wallet, t), s4(t.sol_in), s4(t.sol_out), fee(t), sg(t.gross_sol), "<b>" + sg(t.pnl_sol) + "</b>", pc(t.pnl_pct), hms(t.hold_s),
      '<span style="white-space:normal;display:block;max-width:280px">' + esc(t.reason) + "</span>", t.real ? '<span class="tag real">REAL</span>' : '<span class="tag sim">FICTÍCIA</span>']), "Nenhum trade fechado ainda.");
    // 0.31.87 (Bruxo): vendas parciais de posições que ainda estão abertas (antes só apareciam na carteira)
    const PS = []; (D.positions || []).filter((p) => !!p.real === rm).forEach((p) => (p.sells || []).forEach((s) => PS.push([dt(s.at), pfM(p.mint, p.symbol), pfW(p.wallet, p), f((s.frac || 0) * 100, 0) + "%", s4(s.sol) + " SOL",
      '<span class="wrapcell">' + esc(s.why || "") + "</span>", s.signature ? '<a href="https://solscan.io/tx/' + encodeURIComponent(s.signature) + '" target="_blank" rel="noopener">ver ↗</a>' : "–"])));
    if ($("tPart")) table("tPart", ["Quando", "Token", "Trader", "Vendeu", "Recebeu", "Motivo", "Transação"], PS, "Nenhuma venda parcial em posição aberta.");
    const by = {}, byX = {}; T.forEach((t) => { const key = t.wallet === "manual" ? "manual:" + whoLabel(t) : t.wallet; byX[key] = byX[key] || t; const b = (by[key] = by[key] || { n: 0, w: 0, p: 0, pp: 0, po: 0, np: 0, no: 0 }); const isP = String(t.venue || "pump").toLowerCase().indexOf("pump") >= 0; b.n++; b.w += t.pnl_sol > 0; b.p += t.pnl_sol; if (isP) { b.pp += t.pnl_sol; b.np++; } else { b.po += t.pnl_sol; b.no++; } });
    table("tBy", ["Trader", "Trades", "Acerto", "Resultado", "pump.fun", "Fora da pump.fun"], Object.entries(by).sort((a, b) => b[1].p - a[1].p).map(([w, b]) => [pfW(byX[w].wallet, byX[w]), String(b.n), f((b.w / b.n) * 100, 0) + "%", sg(b.p), b.np ? sg(b.pp) + "<small>" + b.np + " trades</small>" : "–", b.no ? sg(b.po) + "<small>" + b.no + " trades</small>" : "–"]), "Sem trades fechados ainda.");
  }
  // 0.31.55 (pedido do dono): no Histórico também aparecem os erros e desistências (compra real recusada, preço suspeito…)
  const ERR_ACT = /^(REAL falhou|REAL não copiou|preço suspeito)$/;
  function renderErrs() {
    const L = (D.feed || []).filter((e) => ERR_ACT.test(String(e.action || "")));
    $("hErrSub").textContent = L.length + " nos registros recentes · o motivo e a dica ficam também no Relatório do dia (modo Real)";
    table("hErr", ["Quando", "Token", "O que houve", "Motivo"], L.map((e) => [dt(e.at), pfM(e.mint || "", e.symbol),
      '<span class="tag ' + (e.action === "preço suspeito" ? "pause" : "loss") + '">' + esc(e.action) + "</span>" + (/^REAL/.test(e.action) || e.real ? ' <span class="tag real">REAL</span>' : ' <span class="tag sim">FICTÍCIA</span>'),
      '<span class="wrapcell">' + esc(e.reason || "") + "</span>"]), "Nenhum erro ou falha nos registros recentes.");
  }
  // 0.31.79 (pedido do dono): o Feed mostra por padrão só o que os TRADERS fizeram; as compras automáticas (Explorar, Base,
  // botão Comprar) ficam no botão "Tudo"
  let FEEDF = "traders";
  function renderFeed() {
    const all = D.feed || [], L = FEEDF === "all" ? all : all.filter((e) => e.wallet && e.wallet !== "manual");
    if ($("feedSub")) $("feedSub").textContent = FEEDF === "all" ? "tudo o que o bot registrou, inclusive compras automáticas" : L.length + " registros de traders · " + (all.length - L.length) + " das compras automáticas ficam em \"Tudo\"";
    document.querySelectorAll("[data-feedf]").forEach((b) => b.classList.toggle("on", b.dataset.feedf === FEEDF));
    table("tFeed", ["Hora", "Trader", "Token", "Trader fez", "SOL", "Mcap", "O bot"], L.map((e) => [dt(e.at), pfW(e.wallet, e), pfM(e.mint, e.symbol), e.kind === "buy" ? '<span class="tag buy">Compra</span>' : '<span class="tag loss">Venda</span>', s4(e.sol), e.mcap_sol == null ? "–" : f(e.mcap_sol, 0) + " SOL",
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
  // 0.31.25: passo a passo de cada chave, para quem nunca fez (pedido do dono em 2026-10-27: "muito usuário sem
  // experiência"). Os nomes dos botões nos sites de fora podem mudar; por isso o texto diz o que procurar.
  const KEY_HOW = {
    solanatracker_api_key: { custo: "Tem plano grátis.", ganha: "Ranking oficial dos top traders, checagem de risco do token e a tela Explorar com a sua própria cota.",
      passos: ["Clique em \"Criar minha chave →\" (abre o site da Solana Tracker).", "Crie a conta (e-mail ou Google) e escolha o plano grátis (Free).",
        "No painel do site, abra Data API. A sua chave (API key) aparece ali.", "Clique para copiar a chave, volte aqui, cole no campo abaixo e clique em Salvar.",
        "Pronto quando aparecer \"Usando: sua chave\" em verde."] },
    pumpportal_api_key: { custo: "Opcional. A chave é grátis, mas os dados extras da PumpPortal são pagos.", ganha: "Dados extras do stream pago da PumpPortal (ranking próprio). Sem ela, o painel funciona normalmente.",
      passos: ["Clique em \"Criar minha chave →\" (abre a PumpPortal).", "Clique para gerar a chave (API key). O site também cria uma carteira junto: guarde tudo que ele mostrar, porque ele não mostra de novo.",
        "Copie só a API key, cole no campo abaixo e clique em Salvar.", "Não cole aqui a chave privada da carteira que a PumpPortal criou."] },
    jupiter_api_key: { custo: "Opcional. Tem plano grátis.", ganha: "Mais cotações por minuto (preço dos tokens) só para você.",
      passos: ["Clique em \"Criar minha chave →\" (abre o portal da Jupiter).", "Entre com a sua conta (e-mail ou Google).",
        "Procure API Keys e clique para criar uma chave nova. Abre a janela \"Create API Key\".",
        "Em Name, dê um nome de 5 a 32 letras (ex.: pumpfuncopy). \"api\" é curto demais.",
        "Escolha \"Server key\" (a da esquerda). É ela que usa o seu limite próprio; quem chama a Jupiter é o nosso servidor.",
        "Não escolha \"Publishable key\": ela usa o mesmo limite de quem não tem chave, então não melhora nada aqui.",
        "Clique em Create e copie a chave na hora (o site pode não mostrar de novo).",
        "Cole no campo abaixo e clique em Salvar. A chave fica criptografada e nunca volta para a tela."] },
    rpc_url: { custo: "Opcional. A Helius tem plano grátis.", ganha: "Leitura da rede Solana mais rápida e sem os limites do servidor público.",
      passos: ["Clique em \"Criar um RPC →\" (abre o painel da Helius).", "Crie a conta (e-mail, Google ou GitHub). O plano grátis basta.",
        "Na tela inicial (ou em RPCs/Endpoints), copie o endereço da Mainnet. Ele começa com https://mainnet.helius-rpc.com/?api-key=",
        "Cole o endereço inteiro no campo abaixo e clique em Salvar.", "Use sempre o da Mainnet, não o da Devnet."] },
    wallet_private_key: { custo: "Grátis. Só é usada no modo real (dinheiro de verdade).", ganha: "Permite o modo real e a troca USDC→SOL. No simulado não precisa.",
      passos: ["NUNCA use a sua carteira principal. Crie uma carteira NOVA só para o bot e coloque nela pouco saldo.",
        "Na Phantom (ou Solflare): clique na conta lá em cima → Adicionar/Criar conta nova.",
        "Na conta nova: Configurações → Gerenciar contas → a conta nova → Mostrar chave privada. Digite a senha da Phantom.",
        "Copie a chave privada, cole no campo abaixo e clique em Salvar. O endereço público aparece aqui para você conferir.",
        "Ninguém do suporte pede essa chave. Cole só aqui no painel, nunca em conversa."] },
    telegram_bot_token: { custo: "Grátis.", ganha: "Avisos do bot no seu Telegram (compras, stops, convites…).",
      passos: ["Clique no link (abre o @BotFather no Telegram) e toque em Iniciar.", "Mande /newbot.",
        "Escolha um nome (ex.: Meu PUMP) e depois um usuário que termine em bot (ex.: meupump123_bot).",
        "O BotFather responde com o token (números:letras). Copie, cole no campo abaixo e clique em Salvar.",
        "Abra o seu bot novo (link na resposta do BotFather) e toque em Iniciar. Sem isso ele não consegue mandar mensagem para você."] },
    telegram_chat_id: { custo: "Grátis.", ganha: "Diz ao bot para quem mandar os avisos.",
      passos: ["Clique no link (abre o @userinfobot no Telegram) e toque em Iniciar.", "Ele responde com o seu Id (só números).",
        "Copie o número, cole no campo abaixo e clique em Salvar.", "Com as duas chaves salvas (token e Id), os avisos podem ser ligados."] },
  };
  function keyHow(k) {
    const h = KEY_HOW[k]; if (!h) return "";
    return '<details class="keyhow"><summary>Como fazer (passo a passo)</summary><div class="hint"><b>Custo:</b> ' + esc(h.custo) + "<br><b>O que melhora:</b> " + esc(h.ganha) + "</div>" +
      "<ol>" + h.passos.map((p) => "<li>" + esc(p) + "</li>").join("") + "</ol></details>";
  }
  const KEY_SHORT = { solanatracker_api_key: "Solana Tracker", pumpportal_api_key: "PumpPortal", wallet_private_key: "Carteira do bot", rpc_url: "RPC",
    jupiter_api_key: "Jupiter", telegram_bot_token: "Bot Telegram", telegram_chat_id: "Id Telegram" };
  const KEY_NEED = { solanatracker_api_key: "Recomendada", wallet_private_key: "Só modo real", pumpportal_api_key: "Opcional", rpc_url: "Opcional",
    jupiter_api_key: "Opcional", telegram_bot_token: "Para avisos", telegram_chat_id: "Para avisos" };
  const KEY_EDIT = {}; let KEY_SAVED = "";
  async function loadSecrets() {
    const r = await BB.api("/api/secrets"); if (r.error) return;
    const w = r.wallet || {};
    // 0.31.27 (pedido do dono em 2026-10-27: "tudo junto, não dá para saber se foi configurado"): cada chave vira um
    // bloco com faixa colorida e estado em uma frase; configurada esconde o campo (botão Trocar), e o resumo fica no topo.
    const ks = Object.entries(r.keys), nOk = ks.filter(([, v]) => v.configured).length;
    const st = (v) => v.configured ? ["ok", "✓ Configurada", "A sua chave está salva e em uso."]
      : v.system ? ["sys", "Usando a chave do sistema", "Funciona só para ver os dados. Cole a sua para ter a sua própria cota."]
      : ["none", "Não configurada", "Nada salvo ainda."];
    $("secretsSum").innerHTML = '<div class="keysum"><b>' + nOk + " de " + ks.length + "</b> chaves configuradas" +
      ks.map(([k, v]) => '<span class="keychip ' + st(v)[0] + '">' + (v.configured ? "✓ " : "") + esc(KEY_SHORT[k] || v.label) + "</span>").join("") + "</div>";
    $("secrets").innerHTML = ks.map(([k, v]) => {
      const [cls, title, sub] = st(v), open = !v.configured || KEY_EDIT[k];
      const extra = (k === "wallet_private_key" && w.address ? '<div class="keyinfo">Endereço público: <span class="mono">' + esc(w.address) + "</span></div>" : "") +
        (k === "rpc_url" && w.rpc_set ? '<div class="keyinfo">Servidor: <span class="mono">' + esc(w.rpc_host || "") + "</span></div>" : "");
      return '<div class="secret key-' + cls + (KEY_SAVED === k ? " just" : "") + '" id="key-' + k + '">' +
        '<div class="keyhead"><div><div class="name">' + esc(v.label) + (KEY_NEED[k] ? ' <span class="keyneed">' + esc(KEY_NEED[k]) + "</span>" : "") + "</div>" +
        '<div class="muted keydesc">' + esc(KEY_HINT[k] || "") + (v.link ? ' <a href="' + esc(v.link) + '" target="_blank" rel="noopener">' + (k === "wallet_private_key" ? "Criar uma carteira nova →" : k === "rpc_url" ? "Criar um RPC →" : "Criar minha chave →") + "</a>" : "") + "</div></div>" +
        '<div class="keystate"><div class="kst">' + title + '</div><div class="muted">' + (KEY_SAVED === k ? "Salva agora há pouco." : sub) + "</div></div></div>" + extra +
        (open ? '<div class="row keyrow"><input class="in" type="password" autocomplete="new-password" spellcheck="false" data-secret="' + k + '" placeholder="' + (v.configured ? "cole a chave nova para trocar" : "cole a sua chave aqui") + '">' +
          btn("Salvar", "secret-save", { k: k }, "primary") + (v.configured ? btn("Cancelar", "secret-edit", { k: k, off: "1" }) : "") + "</div>"
          : '<div class="row keyrow">' + btn("Trocar chave", "secret-edit", { k: k }) + btn("Remover", "secret-del", { k: k }, "tgl off") + "</div>") +
        keyHow(k) + "</div>";
    }).join("");
  }
  async function loadSysKeys() {
    const r = await BB.api("/api/admin/keys"); if (r.error) return;
    $("sysKeys").innerHTML = Object.entries(r.keys).map(([k, v]) => '<div class="secret"><div><div class="name">' + esc(v.label) + '</div><div class="muted" style="font-size:12.5px">' + esc(KEY_HINT[k] || "") +
      (v.link ? ' <a href="' + esc(v.link) + '" target="_blank" rel="noopener">Onde criar →</a>' : "") + (v.updated_at ? "<br>Atualizada em " + dt(v.updated_at) : "") + "</div>" + keyHow(k) + "</div>" +
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
      ["Jupiter", j && j.on ? "ok " + (j.latency_ms || "") + " ms" : (j && j.error) || "–"], ["Preço do SOL", m.sol_usd ? "$" + f(m.sol_usd, 2) : "–"], ["Chaves do sistema", Object.entries(A.system_keys || {}).filter((x) => x[1]).map((x) => ({ solanatracker_api_key: "Solana Tracker", pumpportal_api_key: "PumpPortal", jupiter_api_key: "Jupiter", rpc_url: "RPC próprio" }[x[0]])).join(", ") || "nenhuma"], ["No ar há", hms(A.uptime_s)],
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
  // 0.31.33: trades da carteira fictícia de um usuário (Admin → Usuários → Ver trades ganhos)
  let UTR = { uid: "", list: [], f: "win" };
  async function openUserTrades(uid, filt) {
    const u = USERS.find((x) => x.user_id === uid) || {};
    UTR = { uid, list: [], f: filt || "win" };
    $("uTrT").textContent = "Trades de " + (u.nome || u.email || "usuário"); busy("uTrS", "Carregando os trades da carteira fictícia");
    $("uTrTbl").innerHTML = ""; $("uTrK").innerHTML = ""; $("uTrades").hidden = false;
    const r = await BB.api("/api/admin/users/" + encodeURIComponent(uid) + "/trades");
    if (r.error) { $("uTrS").textContent = r.error; return; }
    UTR.list = r.trades || []; renderUserTrades();
  }
  function renderUserTrades() {
    const L = UTR.list, W = L.filter((x) => (x.pnl_sol || 0) > 0), P = L.filter((x) => (x.pnl_sol || 0) <= 0);
    const sum = (a) => a.reduce((s, x) => s + (x.pnl_sol || 0), 0);
    document.querySelectorAll("#uTrF button").forEach((b) => b.classList.toggle("on", b.dataset.utf === UTR.f));
    $("uTrS").textContent = "carteira fictícia · " + L.length + " trades fechados · acerto " + (L.length ? f(W.length / L.length * 100, 0) + "%" : "–");
    kpis("uTrK", [["Ganhos", W.length, sg(sum(W))], ["Perdas", P.length, sg(sum(P))], ["Resultado", sg(sum(L)), L.length + " trades"]]);
    const rows = (UTR.f === "win" ? W : UTR.f === "loss" ? P : L).slice().sort((a, b) => UTR.f === "loss" ? (a.pnl_sol || 0) - (b.pnl_sol || 0) : UTR.f === "win" ? (b.pnl_sol || 0) - (a.pnl_sol || 0) : String(b.fechado).localeCompare(String(a.fechado)));
    table("uTrTbl", ["Fechou", "Token", "Origem", "Entrou", "Resultado", "Melhor momento", "Duração", "Motivo"], rows.map((x) => [esc(dt(x.fechado)), pfM(x.mint || "", x.token), esc(x.origem || ""),
      x.sol_in == null ? "–" : f(x.sol_in, 3) + " SOL", sg(x.pnl_sol) + (x.pnl_pct == null ? "" : "<small>" + (x.pnl_pct > 0 ? "+" : "") + f(x.pnl_pct, 1) + "%</small>"),
      x.melhor_pct == null ? "–" : (x.melhor_pct > 0 ? "+" : "") + f(x.melhor_pct, 1) + "%", x.hold_s == null ? "–" : hms(x.hold_s), esc(x.motivo || "")]),
      UTR.f === "win" ? "Nenhum trade ganho ainda." : UTR.f === "loss" ? "Nenhuma perda." : "Nenhum trade fechado.");
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
        u.stats ? sg(S.pnl_sol) + "<small>" + S.trades + " trades · " + S.open + " abertas" + (S.win_rate != null ? " · " + f(S.win_rate * 100, 0) + "%" : "") + "</small>" +
          (S.trades ? btn("Ver trades ganhos", "u-trades", { uid: u.user_id }) : "") : "–",
        u.stats ? st(S.real_enabled, 1) + (S.real_trades ? " " + sg(S.real_pnl_sol) : "") + "<small>" + (S.wallet ? "carteira configurada" : "sem carteira") + "</small>" : "–",
        u.stats ? '<div class="keys">' + key(k.solanatracker_api_key, "Tracker") + key(k.wallet_private_key, "Carteira") + key(k.rpc_url, "RPC") + "</div>" + (S.db_error ? '<small class="down">banco: ' + esc(S.db_error) + "</small>" : "") : '<span class="dim">–</span>',
        '<div style="display:flex;flex-direction:column;gap:4px;align-items:stretch">' + (mine ? "" : u.bloqueado ? btn("Desbloquear", "u-block", { uid: u.user_id, v: "0" }, "tgl on") : btn("Bloquear", "u-block", { uid: u.user_id, v: "1" }, "tgl off")) +
          (S.real_enabled ? btn("Desligar real", "u-realoff", { uid: u.user_id }, "tgl off") : "") + (mine ? "" : btn("Visualizar tela", "u-view", { uid: u.user_id }) + btn("Copiar config", "u-copycfg", { uid: u.user_id })) + btn("Registro", "u-audit", { uid: u.user_id }) + "</div>"];
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
      (D.followed || []).forEach((r) => add({ key: "w" + r.wallet, label: shortW(r.wallet, r) + (r.lb && r.lb.name ? " · " + r.lb.name : ""), tag: "Copiando", url: "https://pump.fun/profile/" + r.wallet, hay: (r.wallet + " " + ((r.lb || {}).name || "")).toLowerCase() }));
      (D.leaderboard || []).forEach((r) => add({ key: "w" + r.wallet, label: "#" + r.rank + " " + shortW(r.wallet, r) + (r.name ? " · " + r.name : ""), tag: "Top", url: "https://pump.fun/profile/" + r.wallet, hay: (r.wallet + " " + (r.name || "")).toLowerCase() }));
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
    if (t.dataset.autoPreset && AUTO_PRESETS[t.dataset.autoPreset]) { setCfg({ ...AUTO_PRESETS[t.dataset.autoPreset] }); return; }
    if (t.dataset.autoDays && [7, 30, 90].includes(+t.dataset.autoDays)) {
      if (+t.dataset.autoDays === EX_AUTO.days) return;
      EX_AUTO.days = +t.dataset.autoDays; EX_AUTO.revision++; EX_AUTO.data = null; EX_AUTO.error = "";
      renderAutoTrades(); loadAutoTrades(true); return;
    }
    if (t.dataset.toggle) { const k = t.dataset.toggle, on = !cfg()[k]; if (on && t.dataset.confirm && !confirm(t.dataset.confirm)) return; setCfg({ [k]: on }); if (k === "pump_base_hide_trash") setTimeout(loadBase, 700); return; }
    if (t.dataset.set) { setCfg({ [t.dataset.set]: +t.dataset.val }); return; }
    if (t.dataset.mode) { MODE = t.dataset.mode; try { localStorage.setItem("pf:mode", MODE); } catch (e) { /* */ } render(); return; }
    if (t.dataset.r) { RANGE = +t.dataset.r; try { localStorage.setItem("pf:range", RANGE); } catch (e) { /* */ } render(); return; }
    if (t.dataset.f) { MONF = t.dataset.f; render(); return; }
    if (t.dataset.off && t.closest("#lbOffSeg")) { LBOFF = t.dataset.off; render(); return; }
    if (t.dataset.lboff) { const k = $("lbOffCard"); if (k) k.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (t.dataset.d && t.closest("#lbDays")) { toast("Buscando top traders (" + t.dataset.d + " dias)…"); const r = await BB.api("/api/pump/leaderboard", { body: { days: +t.dataset.d } }); toast(r.error ? "Leaderboard: " + r.error : "Leaderboard atualizado: " + (r.count || 0) + " traders"); poll(true); return; }
    if (t.dataset.goto) { $("menu").hidden = true; location.hash = t.dataset.goto; return; }
    const a = t.dataset.act; if (!a) return;
    if (a === "w") return wallet(t.dataset.a, t.dataset.w);
    if (a === "prule") {
      const on = t.dataset.on === "1", nome = { stop: "o stop de perda", trail: "o stop móvel", tp1: "a venda em partes" }[t.dataset.regra];
      if (!on && !confirm("Desligar " + nome + " só desta posição (e do par REAL/FICTÍCIA)?" + (t.dataset.regra === "stop" ? "\n\nSem stop de perda a posição pode cair até zero; ela só sai pelo tempo máximo, alvo ou se você fechar." : ""))) return;
      t.disabled = true;
      const r = await BB.api("/api/pump/positions/rule", { body: { id: t.dataset.id, regra: t.dataset.regra, on: on } });
      toast(r.error || (nome.charAt(2).toUpperCase() + nome.slice(3) + (on ? " ligado" : " desligado") + " nesta posição."));
      poll(true); return;
    }
    if (a === "hold") {
      const none = t.dataset.add === "none";
      if (none && !confirm("Tirar o limite de tempo desta posição? Ela só sai pelas outras regras (stop, alvo, stop móvel) ou se você fechar.")) return;
      t.disabled = true;
      const r = await BB.api("/api/pump/positions/hold", { body: { id: t.dataset.id, add_min: none ? "none" : +t.dataset.add } });
      toast(r.error || (none ? "Posição sem limite de tempo." : "Tempo estendido: +" + t.dataset.add + " min."));
      poll(true); return;
    }
    if (a === "u-block") { const blk = t.dataset.v === "1", u = USERS.find((x) => x.user_id === t.dataset.uid) || {};
      if (!confirm((blk ? "Bloquear " : "Desbloquear ") + (u.email || "este usuário") + "?" + (blk ? "\n\nA conta para de copiar na hora, a execução real dele desliga e ele não consegue mais entrar no painel." : ""))) return;
      return adminUser(t.dataset.uid, { bloqueado: blk }); }
    if (a === "u-realoff") { if (!confirm("Desligar a execução REAL deste usuário agora?")) return; return adminUser(t.dataset.uid, { real_off: true }, "Execução real do usuário desligada."); }
    if (a === "u-view") {
      // 0.31.36 (pedido do dono em 2026-10-27): ver a tela do usuário como ele vê, só leitura e sem registrar
      try { sessionStorage.setItem("pf_viewas", t.dataset.uid); } catch (e) { toast("O navegador bloqueou a visualização."); return; }
      location.hash = "#visao"; location.reload(); return;
    }
    if (a === "u-copycfg") {
      // 0.31.33 (pedido do dono em 2026-10-27): copiar toda a configuração do usuário para a sua conta
      const u = USERS.find((x) => x.user_id === t.dataset.uid) || {}, nome = u.nome || u.email || "este usuário";
      if (!confirm("Copiar TODA a configuração de " + nome + " para a SUA conta?\n\nOs seus valores atuais dessas opções serão trocados. Não vai nada da carteira real, chaves ou Telegram, e a conta de " + nome + " não muda.\nDepois, em Configurações e Explorar, o botão \"Ver o que mudou\" mostra antes × agora.")) return;
      t.disabled = true; const r = await BB.api("/api/admin/users/" + encodeURIComponent(t.dataset.uid) + "/copy-config", { body: {} }); t.disabled = false;
      toast(r.error ? "Não copiou: " + r.error : "Configuração de " + nome + " copiada para a sua conta (" + r.opcoes + " opções).");
      if (!r.error) { poll(true); loadApplied(); }
      return;
    }
    if (a === "u-trades") return openUserTrades(t.dataset.uid, "win");
    if (a === "u-audit") { $("aAudUser").value = t.dataset.uid; loadAAudit(); $("tAAudit").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (a === "addw") return wallet("add", $("addW").value);
    if (a === "close") {
      const fr = +(t.dataset.frac || 1), pct = Math.round(fr * 100), real = t.dataset.real === "1";
      const q = fr >= 1 ? (real ? "VENDER de verdade esta posição REAL agora (100%)?" : "Fechar esta posição fictícia agora no preço atual?")
        : (real ? "VENDER de verdade " + pct + "% desta posição REAL agora?" : "Vender " + pct + "% desta posição fictícia agora no preço atual?" + "\n\nSe ela tem par na carteira REAL, a real não vende junto (só vende junto ao fechar 100%).");
      if (!confirm(q)) return;
      t.disabled = true;
      const r = await BB.api("/api/pump/close", { body: { id: t.dataset.id, frac: fr } }); toast(r.error || r.msg || (fr >= 1 ? "Fechada." : "Vendido " + pct + "%.")); return poll(true);
    }
    if (a === "reset") { if (!confirm("Zerar a carteira fictícia? Apaga posições e histórico simulados.")) return; const r = await BB.api("/api/pump/reset", { body: {} }); toast(r.error || "Carteira fictícia zerada."); return poll(true); }
    if (a === "swap") return swap(t);
    if (a === "swapmax") { $("cvU").value = Math.floor(((W && W.usdc) || 0) * 100) / 100; return conv("u"); }
    if (a === "secret-save") {
      const k = t.dataset.k, inp = document.querySelector('[data-secret="' + k + '"]'), v = (inp.value || "").trim(); if (!v) { toast("Cole a chave no campo primeiro."); return; }
      t.disabled = true; const r = await BB.api("/api/secrets", { body: { name: k, value: v } }); inp.value = ""; t.disabled = false;
      toast(r.error ? "Não salvou: " + r.error : "Chave salva (criptografada)." + (r.count != null ? " " + r.count + " top traders carregados." : "") + (r.address ? " Carteira " + shortW(r.address) : ""));
      if (!r.error) { KEY_EDIT[k] = false; KEY_SAVED = k; setTimeout(() => { if (KEY_SAVED === k) { KEY_SAVED = ""; loadSecrets(); } }, 8000); }
      loadSecrets(); loadAudit(); poll(true); walletLoad(true); return;
    }
    if (a === "syskey-save") {
      const k = t.dataset.k, inp = document.querySelector('[data-syskey="' + k + '"]'), v = (inp.value || "").trim(); if (!v) { toast("Cole a chave no campo primeiro."); return; }
      t.disabled = true; const r = await BB.api("/api/admin/keys", { body: { name: k, value: v } }); inp.value = ""; t.disabled = false;
      toast(r.error ? "Não salvou: " + r.error : "Chave do sistema salva (criptografada). Quem não tem chave própria já usa ela para visualizar.");
      loadSysKeys(); loadAdmin(); loadAAudit(); poll(true); return;
    }
    if (a === "syskey-del") { if (!confirm("Remover esta chave do sistema? Quem não tem chave própria deixa de ver o que depende dela.")) return; const r = await BB.api("/api/admin/keys/remove", { body: { name: t.dataset.k } }); toast(r.error || "Chave do sistema removida."); loadSysKeys(); loadAdmin(); loadAAudit(); poll(true); return; }
    if (a === "secret-edit") { KEY_EDIT[t.dataset.k] = !t.dataset.off; await loadSecrets(); const i = document.querySelector('[data-secret="' + t.dataset.k + '"]'); if (i) i.focus(); return; }
    if (a === "secret-del") { if (!confirm("Remover esta chave? Ela será apagada do banco.")) return; const r = await BB.api("/api/secrets/remove", { body: { name: t.dataset.k } }); toast(r.error || "Chave removida."); loadSecrets(); loadAudit(); poll(true); return; }
  });
  document.addEventListener("change", (ev) => {
    const el = ev.target; if (!el.dataset) return;
    if (el.dataset.cfg) {
      if (isAutoCfg(el.dataset.cfg) && (!el.value.trim() || !el.checkValidity())) { el.reportValidity(); toast("Confira o limite desse campo antes de salvar."); return; }
      setCfg({ [el.dataset.cfg]: +el.value });
    }
    if (el.dataset.hcfg) {
      const h = +el.value;
      if (!(h > 0) || h > 24) { toast("Use de 0,02 a 24 horas."); return; }
      setCfg({ [el.dataset.hcfg]: Math.max(1, Math.round(h * 60)) });
    }
    if (el.dataset.urole) { const u = USERS.find((x) => x.user_id === el.dataset.urole) || {}, role = el.value;
      if (!confirm("Mudar " + (u.email || "este usuário") + " para " + (role === "admin" ? "ADMIN (vê o status geral, logs e gerencia usuários)" : "USUÁRIO comum") + "?")) { el.value = u.role; return; }
      adminUser(el.dataset.urole, { role: role }); }
    if (el.id === "aAudUser") loadAAudit();
  });

  // ------------------------------------------------------------------ início
  async function boot() {
    document.querySelectorAll("[data-logo]").forEach((e) => (e.innerHTML = BB.logo));
    $("boot").innerHTML = BB.loader("Carregando o painel", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
    const bootFail = (m) => { BB.loaderEnd($("boot"), "error"); $("boot").insertAdjacentHTML("beforeend", '<p class="muted" style="margin-top:14px;text-align:center">' + esc(m) + "</p>"); };
    let s;
    try { s = await BB.session(); } catch (e) { bootFail(e.message || String(e)); return; }
    if (!s) { location.href = "/"; return; }
    if (location.search) history.replaceState(null, "", location.pathname + location.hash);
    ME = await BB.api("/api/me");
    if (ME.error) { bootFail(ME.error); return; }
    BB.loaderEnd($("boot"), "done");
    $("boot").hidden = true; $("shell").hidden = false;
    if (ME.view_by) {
      // 0.31.36: faixa "você está vendo a tela de X" + painel só leitura (o servidor recusa qualquer alteração)
      document.body.classList.add("viewas");
      $("viewBar").hidden = false;
      $("viewBar").innerHTML = '<div class="viewbar"><span>👁 Você está vendo a tela de <b>' + esc(ME.nome || ME.email || "usuário") + "</b>" + (ME.email ? " · " + esc(ME.email) : "") +
        ' — somente visualização: nada pode ser alterado e as chaves não aparecem.</span><button class="btn sm primary" id="viewExit">Sair da visualização</button></div>';
      $("viewExit").onclick = () => { try { sessionStorage.removeItem("pf_viewas"); } catch (e) { /* */ } location.hash = "#admin"; location.reload(); };
    }
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
    $("ntfB").onclick = () => { const p = $("ntfP"); p.hidden = !p.hidden; if (!p.hidden) { NTFU = 0; ntfList(); } ntfBtn(); };
    $("ntfX").onclick = () => { $("ntfP").hidden = true; };
    // 0.32.51 (pedido do dono): clicar no fundo escuro de qualquer janela (fora da caixa) ou Esc fecha a janela
    document.addEventListener("mousedown", (ev) => { const m = ev.target; if (m && m.classList && m.classList.contains("modal") && !m.hidden) { m.hidden = true; if (m.id === "posM") POS_ID = null; } });
    document.addEventListener("keydown", (ev) => { if (ev.key !== "Escape") return; const open = [...document.querySelectorAll(".modal")].filter((m) => !m.hidden);
      if (open.length) { const m = open[open.length - 1]; m.hidden = true; if (m.id === "posM") POS_ID = null; } });
    // 0.32.45 (pedido do dono): clicar fora do quadro (ou Esc) fecha as notificações; clique numa janela aberta por ele não fecha
    document.addEventListener("click", (ev) => { const p = $("ntfP"); if (!p || p.hidden) return;
      if (ev.target.closest("#ntfP, #ntfB, .modal") || !document.body.contains(ev.target)) return; p.hidden = true; });
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && $("ntfP") && !$("ntfP").hidden) $("ntfP").hidden = true; });
    $("ntfC").onclick = () => { NTFL = []; NTFU = 0; ntfList(); ntfBtn(); };
    $("ntfL").addEventListener("click", (ev) => { const it = ev.target.closest("[data-ntfi]"); if (it && !ev.target.closest("a")) openNtf(+it.dataset.ntfi); });
    // 0.32.52: botão e frases da voz
    const vozBtn = () => { const b = $("ntfV"); if (!b) return; b.className = "btn sm tgl sw " + (VOZ ? "on" : "off"); b.setAttribute("role", "switch"); b.setAttribute("aria-checked", String(VOZ)); $("ntfVF").hidden = !VOZ; };
    if ($("ntfV")) { $("ntfVw").value = VOZ_F.win; $("ntfVl").value = VOZ_F.loss; $("ntfVb").value = VOZ_F.buy || VOZ_PAD.buy; vozBtn();
      $("ntfV").onclick = () => { VOZ = !VOZ; try { localStorage.setItem("ntf_voz", VOZ ? "1" : "0"); } catch (e) { /* */ } vozBtn(); if (VOZ) say(VOZ_F.win.replace("{pct}", "28")); };
      $("ntfVT").onclick = () => { loadVoices(); const v = ptVoice(), ok = say(VOZ_F.win.replace("{pct}", "28"));
        $("ntfVI").textContent = !window.speechSynthesis || !ok ? "Este navegador não fala. Use o Chrome ou o Edge."
          : v ? "Voz: " + v.name : (VOZES.length ? "Sem voz em português neste navegador (fala com sotaque). No Chrome ou no Edge tem voz em português." : "O navegador ainda não carregou as vozes; clique de novo."); };
      ["ntfVw", "ntfVl", "ntfVb"].forEach((id) => $(id).addEventListener("change", () => { VOZ_F = { win: $("ntfVw").value || VOZ_PAD.win, loss: $("ntfVl").value || VOZ_PAD.loss, buy: $("ntfVb").value || VOZ_PAD.buy };
        try { localStorage.setItem("ntf_voz_f", JSON.stringify(VOZ_F)); } catch (e) { /* */ } say(VOZ_F[{ ntfVw: "win", ntfVl: "loss", ntfVb: "buy" }[id]].replace("{pct}", "30")); })); }
    $("ntfS").onclick = () => { NTF = !NTF; try { localStorage.setItem("ntf", NTF ? "1" : "0"); } catch (e) { /* */ } ntfBtn(); if (NTF) { play("buy", 0.4); try { if (window.Notification && Notification.permission === "default") Notification.requestPermission(); } catch (e) { /* */ } } toast("Notificações " + (NTF ? "LIGADAS" : "DESLIGADAS")); };
    ntfBtn();
    $("realB").onclick = realToggle;
    $("navAdmin").hidden = ME.role !== "admin";
    $("navNov").hidden = ME.role !== "admin";
    $("navGrp").hidden = ME.role !== "admin";
    $("navExp").hidden = ME.role !== "admin";
    $("navBaseG").hidden = ME.role !== "admin";
    if ($("navLogs")) $("navLogs").hidden = ME.role !== "admin";
    if ($("navCalls")) $("navCalls").hidden = ME.role !== "admin";
    if ($("navBruxo")) $("navBruxo").hidden = ME.role !== "admin";
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
    cfgShareButtons();
    sanfona();
    loadOffers();
    setInterval(loadOffers, 30000);
    setInterval(() => poll(false), 2000);
    setInterval(() => walletLoad(false), 20000);
    setInterval(() => { if (VIEW === "admin" && LOG_LIVE) loadLogs(); }, 4000);
    setInterval(() => { if (VIEW === "admin") { loadUsers(); loadAdmin(); } }, 30000);
  }
  boot();
})();
