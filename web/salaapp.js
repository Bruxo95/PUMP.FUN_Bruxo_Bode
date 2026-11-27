// 0.32.479 (pedido do dono): Sala no celular em formato de app — barra de baixo com AO VIVO, ABERTAS, HISTÓRICO, LOG e MENU,
// telas que rolam, histórico completo com filtros e janela de detalhes. Mesmo visual pixel da Sala. Só liga no celular em pé
// (no PC e no celular deitado a Sala continua igual). Lê os mesmos dados que o sala.js já busca (window.SALA.state); não chama API.
(function () {
  "use strict";
  const SA = () => window.SALA;
  if (!SA()) return;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MQ = window.matchMedia("(max-width:700px),(max-width:980px) and (orientation:portrait)");
  const TABS = [["vivo", "AO VIVO", "rocket"], ["abertas", "ABERTAS", "coin"], ["hist", "HISTÓRICO", "trophy"], ["log", "LOG", "bot"], ["menu", "MENU", "plant"]];
  const KT = "sala_app_tab", KF = "sala_app_hf";
  let TAB = "vivo", HF = { p: "tudo", r: "todas", q: "", n: 50 }, LF = "todos", SIG = {};
  try { TAB = localStorage.getItem(KT) || "vivo"; Object.assign(HF, JSON.parse(localStorage.getItem(KF) || "{}")); HF.n = 50; } catch (e) { /* */ }
  if (!TABS.some((t) => t[0] === TAB)) TAB = "vivo";

  const S = () => SA().state;
  const U = () => SA().unit;
  const tms = (s) => (s ? (typeof s === "number" ? (s < 1e11 ? s * 1000 : s) : Date.parse(s)) || 0 : 0);
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "flat");
  const pct = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(1) + "%");
  const usdOf = (v) => { const r = +(S().wallet || {}).sol_usd || 0; return SA().forex ? null : r ? v * r : null; };
  const usd = (v, sign) => { if (v == null) return "–"; const a = Math.abs(v); return (sign ? (v > 0 ? "+" : v < 0 ? "-" : "") : v < 0 ? "-" : "") + "$" + a.toFixed(a >= 100 ? 0 : 2); };
  const amt = (v, sign) => {                                         // valor na moeda da rede + dólar embaixo
    if (v == null) return "–";
    if (SA().forex) return usd(v, sign);
    const d = SA().dec, n = (sign && v > 0 ? "+" : "") + Number(v).toFixed(d + 1) + " " + U(), u = usdOf(v);
    return n + (u == null ? "" : ' <small class="sau">' + usd(u, sign) + "</small>");
  };
  const hm = (t) => (t ? new Date(t).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "–");
  const dur = (s) => { s = Math.max(0, Math.round(s)); return s < 60 ? s + " s" : s < 3600 ? Math.floor(s / 60) + " min" : Math.floor(s / 3600) + " h " + Math.floor((s % 3600) / 60) + " min"; };
  const dayLab = (t) => {
    const d = new Date(t), h = new Date(); h.setHours(0, 0, 0, 0);
    const k = new Date(t); k.setHours(0, 0, 0, 0);
    const n = Math.round((h - k) / 86400000);
    return n === 0 ? "HOJE" : n === 1 ? "ONTEM" : d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" }).toUpperCase();
  };
  const sy = (x) => esc(x.symbol || (x.mint || "").slice(0, 6) || "?");
  const ic = (n, sc) => SA().icon(n, sc || 2);
  const box = (title, ico, body, extra) => '<section class="sabox"><h3 class="pf">' + (ico ? ic(ico, 2) : "") + "<span>" + title + "</span>" + (extra || "") +
    '<i class="dots"><b></b><b></b><b></b></i></h3><div class="sabd">' + body + "</div></section>";
  const kpi = (l, v, c) => '<div class="sak"><small>' + l + '</small><b class="' + (c || "") + '">' + v + "</b></div>";
  const chips = (name, opts, cur) => '<div class="sachips" role="group">' + opts.map(([k, l]) =>
    '<button type="button" class="pf' + (k === cur ? " on" : "") + '" data-sa' + name + '="' + k + '" aria-pressed="' + (k === cur) + '">' + l + "</button>").join("") + "</div>";

  // ------------------------------------------------------------------ estrutura
  const shell = document.createElement("div");
  shell.className = "sapages";
  shell.innerHTML = '<div id="saKpi" class="sakpis"></div>' +
    TABS.filter((t) => t[0] !== "vivo").map((t) => '<main class="sapg" data-pg="' + t[0] + '" id="pg_' + t[0] + '"></main>').join("");
  const grid = document.querySelector(".grid");
  grid.insertAdjacentElement("afterend", shell);
  const bar = document.createElement("nav");
  bar.className = "sbar"; bar.setAttribute("aria-label", "Menu da Sala");
  bar.innerHTML = TABS.map(([k, l, i]) => '<button type="button" data-satab="' + k + '">' + ic(i, 2) + '<span class="pf">' + l + '</span><em id="sb_' + k + '" hidden></em></button>').join("");
  document.body.appendChild(bar);
  const sheet = document.createElement("div");
  sheet.className = "sasheet"; sheet.hidden = true;
  sheet.innerHTML = '<div class="sashd" data-saclose></div><div class="sasp" role="dialog" aria-modal="true"><h3 class="pf"><span id="saShT"></span><button type="button" class="pf" data-saclose aria-label="Fechar">X</button></h3><div class="sasb" id="saShB"></div></div>';
  document.body.appendChild(sheet);
  const DET = {};                                                    // id → item, para abrir a janela de detalhes

  function apply() {
    const on = MQ.matches;
    document.documentElement.classList.toggle("sapp", on);
    document.body.setAttribute("data-tab", TAB);
    bar.querySelectorAll("[data-satab]").forEach((b) => { const a = b.getAttribute("data-satab") === TAB; b.classList.toggle("on", a); b.setAttribute("aria-current", a ? "page" : "false"); });
    SIG = {};
    if (on) draw(true);
  }
  function go(t) {
    TAB = t; try { localStorage.setItem(KT, t); } catch (e) { /* */ }
    apply(); window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------------ AO VIVO: números da carteira embaixo da cena
  function drawKpi() {
    const s = S(), w = s.wallet || {}, P = s.positions || [];
    let inv = 0, now = 0;
    P.forEach((p) => { inv += +p.sol_in || 0; now += +p.pnl_now_sol || 0; });
    const sig = [w.pnl_sol, w.win_rate, w.count, P.length, now.toFixed(6), s.real].join("|");
    if (SIG.kpi === sig) return; SIG.kpi = sig;
    $("saKpi").innerHTML = kpi("CARTEIRA", s.real ? "REAL" : "FICTÍCIA", s.real ? "rl" : "fc") +
      kpi("RESULTADO", amt(+w.pnl_sol || 0, true), cls(+w.pnl_sol || 0)) +
      kpi("ACERTO", w.win_rate == null ? "–" : Math.round(w.win_rate * 100) + "%") +
      kpi("ABERTAS", P.length + (P.length ? ' <small class="' + cls(now) + '">' + pct(inv ? now / inv * 100 : 0) + "</small>" : ""));
  }

  // ------------------------------------------------------------------ ABERTAS
  function drawAbertas() {
    const s = S(), P = (s.positions || []).slice().sort((a, b) => (b.pnl_now_pct || 0) - (a.pnl_now_pct || 0));
    const sig = P.map((p) => SA().pid(p) + ":" + (p.pnl_now_pct || 0).toFixed(1)).join(",") + "|" + s.real + "|" + Math.floor(Date.now() / 15000);
    if (SIG.ab === sig) return; SIG.ab = sig;
    let inv = 0, now = 0;
    P.forEach((p) => { inv += +p.sol_in || 0; now += +p.pnl_now_sol || 0; });
    const head = '<div class="sakpis in">' + kpi("ABERTAS", P.length) + kpi("INVESTIDO", amt(inv)) + kpi("AGORA", amt(now, true), cls(now)) +
      kpi("%", pct(inv ? now / inv * 100 : null), cls(now)) + "</div>";
    const list = !P.length ? '<p class="saempty">Nenhuma posição aberta agora na carteira ' + (s.real ? "REAL" : "FICTÍCIA") + ".</p>" :
      P.map((p) => {
        const id = "p" + SA().pid(p); DET[id] = { k: "pos", x: p };
        const t = tms(p.opened_at), ins = +p.sol_in || 0;
        return '<button type="button" class="sacard ' + cls(p.pnl_now_pct) + '" data-sadet="' + esc(id) + '"><span class="sct"><b>' + sy(p) + "</b>" +
          (p.aba ? '<em class="saab">' + esc(p.aba) + "</em>" : "") + '</span><span class="scp ' + cls(p.pnl_now_pct) + '">' + pct(p.pnl_now_pct) + "</span>" +
          '<span class="scl">entrou ' + hm(t) + " · há " + dur((Date.now() - t) / 1000) + "</span>" +
          '<span class="scv">' + amt(ins) + ' → <span class="' + cls(p.pnl_now_sol) + '">' + amt(ins + (+p.pnl_now_sol || 0)) + "</span></span></button>";
      }).join("");
    $("pg_abertas").innerHTML = box("POSIÇÕES ABERTAS", "coin", head + '<div class="salist">' + list + "</div>");
    badge("abertas", P.length);
  }

  // ------------------------------------------------------------------ HISTÓRICO completo
  const PER = [["1h", "1 H", 3600], ["6h", "6 H", 21600], ["24h", "24 H", 86400], ["7d", "7 DIAS", 604800], ["tudo", "TUDO", 0]];
  function histRows() {
    const s = S(), lim = (PER.find((p) => p[0] === HF.p) || PER[4])[2], now = Date.now(), q = HF.q.trim().toLowerCase();
    return (s.trades || []).filter((t) => {
      if (String(t.motivo || "").toLowerCase().indexOf("desfeita") >= 0) return false;
      const ct = tms(t.closed_at);
      if (lim && now - ct > lim * 1000) return false;
      const pl = +t.pnl_sol || 0;
      if (HF.r === "ganhou" && !(pl > 0)) return false;
      if (HF.r === "perdeu" && !(pl <= 0)) return false;
      if (q && (String(t.symbol || "") + " " + (t.mint || "") + " " + (t.aba || "")).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }
  function drawHist(force) {
    const s = S(), R = histRows();
    const sig = R.length + "|" + (R[0] ? SA().tid(R[0]) : "") + "|" + JSON.stringify(HF) + "|" + s.real + "|" + ((s.wallet || {}).periodos ? 1 : 0);
    if (!force && SIG.hi === sig) return; SIG.hi = sig;
    let pnl = 0, inv = 0, win = 0, best = null, worst = null;
    R.forEach((t) => { const v = +t.pnl_sol || 0; pnl += v; inv += +t.sol_in || 0; if (v > 0) win++;
      if (best == null || (t.pnl_pct || 0) > best) best = t.pnl_pct || 0; if (worst == null || (t.pnl_pct || 0) < worst) worst = t.pnl_pct || 0; });
    const head = chips("hp", PER.map((p) => [p[0], p[1]]), HF.p) + chips("hr", [["todas", "TODAS"], ["ganhou", "GANHOU"], ["perdeu", "PERDEU"]], HF.r) +
      '<input class="saq" id="saQ" type="search" placeholder="buscar moeda ou aba…" aria-label="Buscar moeda ou aba" value="' + esc(HF.q) + '">' +
      '<div class="sakpis in">' + kpi("TRADES", R.length) + kpi("RESULTADO", amt(pnl, true), cls(pnl)) +
      kpi("ACERTO", R.length ? Math.round(win / R.length * 100) + "%" : "–") + kpi("% SOBRE INVESTIDO", pct(inv ? pnl / inv * 100 : null), cls(pnl)) +
      kpi("MELHOR", pct(best), cls(best)) + kpi("PIOR", pct(worst), cls(worst)) + "</div>";
    let html = "", day = "";
    R.slice(0, HF.n).forEach((t) => {
      const ct = tms(t.closed_at), dl = dayLab(ct);
      if (dl !== day) { day = dl; html += '<div class="saday pf">' + dl + "</div>"; }
      const id = "t" + SA().tid(t); DET[id] = { k: "trade", x: t };
      const ins = +t.sol_in || 0;
      html += '<button type="button" class="sacard ' + cls(t.pnl_sol) + '" data-sadet="' + esc(id) + '"><span class="sct"><b>' + sy(t) + "</b>" +
        (t.aba ? '<em class="saab">' + esc(t.aba) + "</em>" : "") + '</span><span class="scp ' + cls(t.pnl_pct) + '">' + pct(t.pnl_pct) + "</span>" +
        '<span class="scl">' + hm(tms(t.opened_at)) + " → " + hm(ct) + (t.motivo ? " · " + esc(String(t.motivo).slice(0, 60)) : "") + "</span>" +
        '<span class="scv">' + (ins ? amt(ins) + " · " : "") + '<span class="' + cls(t.pnl_sol) + '">' + amt(+t.pnl_sol || 0, true) + "</span></span></button>";
    });
    if (!R.length) html = '<p class="saempty">Nenhum trade fechado com esse filtro.</p>';
    else if (R.length > HF.n) html += '<button type="button" class="sabtn pf" data-samore>MOSTRAR MAIS (' + (R.length - HF.n) + ")</button>";
    // totais de TODOS os trades fechados (o motor conta todos, não só os que a tela recebe)
    const per = (s.wallet || {}).periodos;
    const tot = !per || !per.length ? "" : box("TOTAL DE TODOS OS TRADES", "trophy", '<div class="sakpis in">' + per.map((p) =>
      kpi(p.horas + " H · " + p.trades + " trades", amt(+p.saldo_sol || 0, true), cls(+p.saldo_sol || 0))).join("") + "</div>");
    const painel = SA().forex ? "/forex" : SA().hood ? "/hood#historico" : "/app#historico";
    const foot = '<p class="sanote">A lista mostra os últimos ' + (s.trades || []).length + ' trades que a Sala recebe. O histórico inteiro, com todos os filtros, fica no painel.</p>' +
      '<a class="sabtn pf" href="' + painel + '">ABRIR HISTÓRICO COMPLETO NO PAINEL</a>';
    const focus = document.activeElement && document.activeElement.id === "saQ";
    $("pg_hist").innerHTML = box("HISTÓRICO", "trophy", head + '<div class="salist">' + html + "</div>") + tot + foot;
    if (focus) { const q = $("saQ"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  }

  // ------------------------------------------------------------------ LOG completo
  const LK = { todos: null, compra: ["ok"], venda: ["sell"], nao: ["no", "wait"], real: ["real", "bad"] };
  function drawLog() {
    const L = (S().log || []).filter((x) => { const k = LK[LF]; return !k || k.indexOf(SA().logKind(x.a)) >= 0; });
    const sig = L.length + "|" + (L[0] ? L[0].k : "") + "|" + LF;
    if (SIG.lg === sig) return; SIG.lg = sig;
    const rows = L.slice(0, 300).map((x) => { const k = SA().logKind(x.a);
      return '<div class="sall ' + k + '"><span class="lt">' + esc(x.h) + "</span> <b>" + esc(String(x.a || "").toUpperCase()) + "</b> " + esc(x.s || "") +
        (x.r ? '<span class="lr">' + esc(String(x.r).slice(0, 160)) + "</span>" : "") + "</div>"; }).join("");
    $("pg_log").innerHTML = box("LOG DO ROBÔ", "bot", chips("lf", [["todos", "TUDO"], ["compra", "COMPRAS"], ["venda", "VENDAS"], ["nao", "NÃO COPIOU"], ["real", "REAL / ERROS"]], LF) +
      '<div class="salog">' + (rows || '<p class="saempty">Sem decisões com esse filtro.</p>') + '<div class="cur">&gt; _</div></div>');
  }

  // ------------------------------------------------------------------ MENU
  function drawMenu() {
    const s = S(), snd = $("snd"), sndOn = snd && snd.classList.contains("on");
    const curBtns = Array.from(document.querySelectorAll("#cur [data-cur]"));
    const sig = [s.real, sndOn, curBtns.map((b) => b.className + b.disabled).join()].join("|");
    if (SIG.mn === sig) return; SIG.mn = sig;
    const painel = (document.querySelector('.ctl a[href]') || {}).getAttribute ? document.querySelector(".ctl a[href]").getAttribute("href") : "/app";
    const realOk = !$("mReal") || !$("mReal").hidden;
    $("pg_menu").innerHTML = box("CARTEIRA", "coin", '<div class="saseg">' +
        '<button type="button" class="pf' + (!s.real ? " on" : "") + '" data-samode="sim">FICTÍCIA</button>' +
        (realOk ? '<button type="button" class="pf real' + (s.real ? " on" : "") + '" data-samode="real">REAL</button>' : "") + "</div>" +
        '<p class="sanote">A Sala só mostra; trocar aqui não liga nem desliga nada no robô.</p>') +
      box("SOM E MOEDA", "up", '<div class="saseg"><button type="button" class="pf' + (sndOn ? " on" : "") + '" data-sasnd>SOM: ' + (sndOn ? "LIGADO" : "DESLIGADO") + "</button></div>" +
        (curBtns.length ? '<div class="saseg">' + curBtns.map((b) => '<button type="button" class="pf' + (b.classList.contains("on") ? " on" : "") + '" data-sacur="' + esc(b.getAttribute("data-cur")) + '"' +
          (b.disabled ? " disabled" : "") + ">" + esc(b.textContent) + "</button>").join("") + "</div>" : "")) +
      box("IR PARA", "rocket", '<div class="sagrid">' +
        '<button type="button" class="sabtn pf" data-satab="hist">' + ic("trophy", 2) + " HISTÓRICO</button>" +
        '<button type="button" class="sabtn pf" data-satab="log">' + ic("bot", 2) + " LOG DO ROBÔ</button>" +
        '<a class="sabtn pf" href="' + esc(painel) + '">' + ic("coin", 2) + " PAINEL</a>" +
        '<a class="sabtn pf" href="/entrar">' + ic("rocket", 2) + " TROCAR REDE</a>" +
        (document.fullscreenEnabled ? '<button type="button" class="sabtn pf" data-safull>' + ic("up", 2) + " TELA CHEIA</button>" : "") +
        '<button type="button" class="sabtn pf" data-sareload>' + ic("plant", 2) + " RECARREGAR</button></div>");
  }

  // ------------------------------------------------------------------ detalhes
  function openDet(id) {
    const d = DET[id]; if (!d) return;
    const x = d.x, pos = d.k === "pos", mint = x.mint || "";
    const ins = +x.sol_in || 0, pl = pos ? +x.pnl_now_sol || 0 : +x.pnl_sol || 0, pp = pos ? x.pnl_now_pct : x.pnl_pct;
    const row = (l, v) => '<div class="sadr"><small>' + l + "</small><span>" + v + "</span></div>";
    const sol = !SA().hood && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(mint);
    $("saShT").textContent = (pos ? "ABERTA · " : "FECHADA · ") + (x.symbol || mint.slice(0, 6) || "?");
    $("saShB").innerHTML = '<div class="sabig ' + cls(pp) + '">' + pct(pp) + "<small>" + amt(pl, true) + "</small></div>" +
      row("Carteira", x.real ? "REAL" : "FICTÍCIA") + (x.aba ? row("Aba", esc(x.aba)) : "") +
      row("Investido", amt(ins)) + row(pos ? "Vale agora" : "Voltou", amt(ins + pl)) +
      row("Entrou", tms(x.opened_at) ? new Date(tms(x.opened_at)).toLocaleString("pt-BR") : "–") +
      (pos ? row("Aberta há", dur((Date.now() - tms(x.opened_at)) / 1000)) :
        row("Saiu", new Date(tms(x.closed_at)).toLocaleString("pt-BR")) + row("Durou", dur((tms(x.closed_at) - tms(x.opened_at)) / 1000))) +
      (!pos && x.motivo ? row("Por que saiu", esc(x.motivo)) : "") +
      (x.wallet && x.wallet !== "manual" ? row("Trader copiado", esc(String(x.wallet).slice(0, 6) + "…" + String(x.wallet).slice(-4))) : "") +
      (mint ? row("Token", '<code>' + esc(mint.slice(0, 6) + "…" + mint.slice(-6)) + "</code>") : "") +
      (sol ? '<div class="sagrid"><a class="sabtn pf" target="_blank" rel="noopener" href="https://pump.fun/coin/' + encodeURIComponent(mint) + '">PUMP.FUN</a>' +
        '<a class="sabtn pf" target="_blank" rel="noopener" href="https://dexscreener.com/solana/' + encodeURIComponent(mint) + '">DEXSCREENER</a></div>' : "");
    sheet.hidden = false; document.body.classList.add("sashow");
    const b = sheet.querySelector("button[data-saclose]"); if (b) b.focus();
  }
  function closeDet() { sheet.hidden = true; document.body.classList.remove("sashow"); }

  function badge(k, n) { const e = $("sb_" + k); if (!e) return; e.hidden = !n; e.textContent = n > 99 ? "99+" : String(n || ""); }

  function draw(force) {
    if (!MQ.matches || !S()) return;
    if (force) SIG = {};
    badge("abertas", (S().positions || []).length);
    if (TAB === "vivo") drawKpi();
    else if (TAB === "abertas") drawAbertas();
    else if (TAB === "hist") drawHist();
    else if (TAB === "log") drawLog();
    else if (TAB === "menu") drawMenu();
  }

  // ------------------------------------------------------------------ cliques
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-satab],[data-sadet],[data-saclose],[data-sahp],[data-sahr],[data-salf],[data-samore],[data-samode],[data-sasnd],[data-sacur],[data-safull],[data-sareload]");
    if (!t) return;
    if (t.hasAttribute("data-satab")) return go(t.getAttribute("data-satab"));
    if (t.hasAttribute("data-sadet")) return openDet(t.getAttribute("data-sadet"));
    if (t.hasAttribute("data-saclose")) return closeDet();
    const saveHF = () => { try { localStorage.setItem(KF, JSON.stringify({ p: HF.p, r: HF.r })); } catch (x) { /* */ } };
    if (t.hasAttribute("data-sahp")) { HF.p = t.getAttribute("data-sahp"); HF.n = 50; saveHF(); return drawHist(true); }
    if (t.hasAttribute("data-sahr")) { HF.r = t.getAttribute("data-sahr"); HF.n = 50; saveHF(); return drawHist(true); }
    if (t.hasAttribute("data-samore")) { HF.n += 50; return drawHist(true); }
    if (t.hasAttribute("data-salf")) { LF = t.getAttribute("data-salf"); SIG.lg = ""; return drawLog(); }
    if (t.hasAttribute("data-samode")) { SA().setMode(t.getAttribute("data-samode") === "real"); SIG = {}; setTimeout(() => draw(true), 50); return; }
    if (t.hasAttribute("data-sasnd")) { const b = $("snd"); if (b) b.click(); SIG.mn = ""; return drawMenu(); }
    if (t.hasAttribute("data-sacur")) { const b = document.querySelector('#cur [data-cur="' + t.getAttribute("data-sacur") + '"]'); if (b) b.click(); SIG = {}; return draw(true); }
    if (t.hasAttribute("data-safull")) { const r = document.documentElement.requestFullscreen; if (r) r.call(document.documentElement).catch(() => {}); return; }
    if (t.hasAttribute("data-sareload")) return location.reload();
  });
  document.addEventListener("input", (e) => { if (e.target && e.target.id === "saQ") { HF.q = e.target.value; HF.n = 50; drawHist(true); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !sheet.hidden) closeDet(); });

  (MQ.addEventListener ? MQ.addEventListener("change", apply) : MQ.addListener(apply));
  apply();
  setInterval(() => draw(false), 1000);
})();
