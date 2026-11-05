/* Comum às duas páginas: configuração pública, cliente do Supabase (login Google) e chamadas à API. */
(function () {
  "use strict";
  const BB = (window.BB = { cfg: null, sb: null });
  const LOGO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/><path d="M15.2 11.5l-2 3h2.6l-2 3"/></svg>';
  BB.logo = LOGO;

  BB.init = async function () {
    if (BB.sb) return BB.sb;
    const r = await fetch("/api/public-config", { cache: "no-store" });
    BB.cfg = await r.json();
    if (!BB.cfg.configured) throw new Error("O servidor ainda não tem SUPABASE_URL / SUPABASE_ANON_KEY no .env.");
    if (!window.supabase) throw new Error("Não consegui carregar a biblioteca de login (sem internet?).");
    BB.sb = window.supabase.createClient(BB.cfg.supabase_url, BB.cfg.supabase_anon_key, {
      auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
    return BB.sb;
  };

  BB.login = async function () {
    const sb = await BB.init();
    const base = (BB.cfg.base_url || location.origin).replace(/\/$/, "");
    const { error } = await sb.auth.signInWithOAuth({ provider: "google", options: { redirectTo: base + "/app" } });
    if (error) throw error;
  };

  BB.session = async function () {
    const sb = await BB.init();
    const { data } = await sb.auth.getSession();
    return data && data.session;
  };

  BB.logout = async function () {
    try { await (await BB.init()).auth.signOut(); } catch (e) { /* segue */ }
    location.href = "/";
  };

  /* 0.31.36: admin vendo a tela de um usuário (só leitura). Fica só nesta aba (sessionStorage). */
  BB.viewAs = function () {
    let v = ""; try { v = sessionStorage.getItem("pf_viewas") || ""; } catch (e) { /* */ }
    return v ? { "X-View-As": v } : {};
  };

  /* Chamada à API com o token do usuário. 401 → volta para a página inicial. */
  const NET = { pend: 0, fail: false, show: null, hide: null };
  function netStart(post) {
    const el = document.getElementById("netLoad"); if (!el) return;
    NET.pend++;
    if (NET.pend === 1) {
      NET.fail = false; clearTimeout(NET.hide);
      NET.show = setTimeout(() => { el.classList.remove("saindo"); el.innerHTML = BB.loader(post ? "Salvando" : "Carregando", { key: "net" + Date.now() }); el.hidden = false; }, 400);
    }
  }
  function netEnd(ok) {
    const el = document.getElementById("netLoad"); if (!el) return;
    NET.pend = Math.max(0, NET.pend - 1); if (!ok) NET.fail = true;
    if (NET.pend) return;
    clearTimeout(NET.show);
    if (el.hidden) return;
    BB.loaderEnd(el, NET.fail ? "error" : "done");
    NET.hide = setTimeout(() => { el.classList.add("saindo"); NET.hide = setTimeout(() => { el.hidden = true; el.classList.remove("saindo"); }, 260); }, NET.fail ? 1800 : 900);
  }

  BB.api = async function (path, opts) {
    opts = opts || {};
    const watch = !opts.quiet && !/^\/api\/pump\?ev=/.test(path);
    if (!watch) return BB._api(path, opts);
    netStart(opts.body !== undefined || (opts.method && opts.method !== "GET"));
    let ok = false;
    try { const js = await BB._api(path, opts); ok = !js.error; return js; } finally { netEnd(ok); }
  };
  BB._api = async function (path, opts) {
    opts = opts || {};
    const s = await BB.session();
    if (!s) { location.href = "/"; throw new Error("sem sessão"); }
    const h = Object.assign({ Authorization: "Bearer " + s.access_token }, BB.viewAs(), opts.headers || {});
    let body = opts.body;
    if (body !== undefined && typeof body !== "string") { body = JSON.stringify(body); h["Content-Type"] = "application/json"; }
    const r = await fetch(path, { method: opts.method || (body !== undefined ? "POST" : "GET"), headers: h, body: body, cache: "no-store" });
    if (r.status === 401) { location.href = "/?sessao=expirada"; throw new Error("sessão expirada"); }
    let js = {};
    try { js = await r.json(); } catch (e) { js = { error: "resposta inválida do servidor" }; }
    if (!r.ok && !js.error) js.error = "erro " + r.status;
    return js;
  };

  /* Baixa (ou abre) um arquivo da API com o token do usuário (0.31.7: PDFs dos relatórios). */
  BB.download = async function (path, filename, open) {
    const s = await BB.session();
    if (!s) { location.href = "/"; return; }
    const r = await fetch(path, { headers: Object.assign({ Authorization: "Bearer " + s.access_token }, BB.viewAs()), cache: "no-store" });
    if (!r.ok) throw new Error("erro " + r.status);
    const url = URL.createObjectURL(await r.blob());
    if (open) { window.open(url, "_blank", "noopener"); } else {
      const a = document.createElement("a"); a.href = url; a.download = filename || "arquivo"; document.body.appendChild(a); a.click(); a.remove();
    }
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  };

  /* ---------------------------------------------------------------- indicador "Carregando" (0.32.39)
     Grade de pontos que acende em onda + verbo + cronômetro; ao terminar vira ✓ "Pronto em 1.2s" ou ✗ "Falhou após".
     Adaptado do LatticeLoader (React Bits) para JS puro. Uso: el.innerHTML = BB.loader("Carregando o radar");
     BB.loaderEnd(el, "done" | "error", "texto opcional"). No HTML: <div data-ll="Carregando…"></div>. */
  const LL_PAT = {
    orbit: { 3: { cells: [0, 1, 2, 7, null, 3, 6, 5, 4], loop: 8, scale: 1.2 }, 4: { cells: [0, 1, 2, 3, 11, null, null, 4, 10, null, null, 5, 9, 8, 7, 6], loop: 6, scale: 1.2, lit: 0.45 } },
    ripple: { 3: { cells: [2, 1, 2, 1, 0, 1, 2, 1, 2], loop: 4.8, scale: 1.5 } },
    snake: { 3: { cells: [0, 1, 2, 5, 4, 3, 6, 7, 8], loop: 9, scale: 1, lit: 0.35 } },
    sweep: { 4: { cells: [0, 1, 2, 3, 1, 2, 3, 4, 2, 3, 4, 5, 3, 4, 5, 6], loop: 5, scale: 1, lit: 0.45 } },
    pulse: { 4: { cells: [2, 1, 1, 2, 1, 0, 0, 1, 1, 0, 0, 1, 2, 1, 1, 2], loop: 2.4, scale: 2.5, lit: 0.45 } },
  };
  const LL_MARK = { 3: { done: [2, 3, 5, 7], error: [0, 2, 4, 6, 8] }, 4: { done: [7, 8, 10, 13], error: [0, 3, 5, 6, 9, 10, 12, 15] } };
  const llFmt = (ds) => (ds < 600 ? (ds / 10).toFixed(1) + "s" : Math.floor(ds / 600) + "m " + ((ds % 600) / 10).toFixed(1) + "s").replace(".", ",");
  let llTick = null;
  function llRun() {
    const live = document.querySelectorAll('.lattice-loader[data-status="working"] .lattice-loader__timer');
    if (!live.length) { clearInterval(llTick); llTick = null; return; }
    const now = Date.now();
    live.forEach((t) => { const t0 = +t.parentNode.dataset.t0 || now; t.textContent = llFmt(Math.floor((now - t0) / 100)); });
  }
  const LLT = {};                       // relógio por rótulo: redesenhar a tela não zera o cronômetro nem pula a onda
  BB.loader = function (label, o) {
    o = o || {};
    const n = o.grid === 4 ? 4 : 3, P = (LL_PAT[o.pattern] && LL_PAT[o.pattern][n]) || LL_PAT[n === 4 ? "sweep" : "orbit"][n];
    const d = (o.step || 90) * P.scale, cyc = Math.round(P.loop * d), lit = P.lit && P.lit !== 0.62 ? Math.round(P.lit * 100) : "";
    const key = o.key || label || "Carregando", now = Date.now(), rec = LLT[key];
    if (!rec || now - rec.last > 3000) LLT[key] = { t0: now, last: now }; else rec.last = now;
    const t0 = LLT[key].t0, fase = (now - t0) % cyc;
    const st = "--ll-n:" + n + ";--ll-cell:" + (o.cell || 6) + "px;--ll-gap:" + (o.gap == null ? 2 : o.gap) + "px;--ll-font:" + (o.font || 13) + "px;--ll-cycle:" + cyc + "ms" + (o.color ? ";--ll-color:" + o.color + ";--ll-glow:" + o.color : "");
    const run = P.cells.map((u) => '<span class="lattice-loader__cell"' + (u == null ? " data-hole" : (lit ? ' data-lit="' + lit + '"' : "") + ' style="animation-delay:' + Math.round(u * d - fase) + 'ms"') + "></span>").join("");
    const mark = P.cells.map((_, i) => '<span class="lattice-loader__cell" data-i="' + i + '"></span>').join("");
    const L = BB.esc(label || "Carregando");
    setTimeout(() => { if (!llTick) llTick = setInterval(llRun, 100); }, 0);     // o cronômetro anda enquanto houver um na tela
    return '<span class="lattice-loader' + (o.cls ? " " + o.cls : "") + '" role="status" data-status="working" data-shape="round" data-n="' + n + '"' + (o.glow ? " data-glow" : "") + ' data-t0="' + t0 + '" data-lbl="' + L + '" style="' + st + '">' +
      '<span class="lattice-loader__grid" aria-hidden="true"><span class="lattice-loader__layer lattice-loader__run">' + run + '</span><span class="lattice-loader__layer lattice-loader__mark">' + mark + "</span></span>" +
      '<span class="lattice-loader__label" style="animation-delay:-' + ((now - t0) % 2200) + 'ms">' + L + "</span>" + (o.timer === false ? "" : '<span class="lattice-loader__timer" aria-hidden="true">' + llFmt(Math.floor((now - t0) / 100)) + "</span>") + "</span>";
  };
  /* Termina o indicador: congela o cronômetro e mostra ✓ (done) ou ✗ (error). Devolve o tempo em segundos. */
  BB.loaderEnd = function (root, status, label) {
    const el = root && (root.classList && root.classList.contains("lattice-loader") ? root : root.querySelector(".lattice-loader"));
    if (!el || el.dataset.status !== "working") return 0;
    const secs = (Date.now() - (+el.dataset.t0 || Date.now())) / 1000, ok = status !== "error";
    el.dataset.status = ok ? "done" : "error";
    const on = LL_MARK[+el.dataset.n === 4 ? 4 : 3][ok ? "done" : "error"];
    el.querySelectorAll(".lattice-loader__mark .lattice-loader__cell").forEach((c) => c.toggleAttribute("data-on", on.includes(+c.dataset.i)));
    const t = el.querySelector(".lattice-loader__timer"); if (t) t.textContent = llFmt(Math.floor(secs * 10));
    const l = el.querySelector(".lattice-loader__label"); if (l) l.textContent = label || (ok ? "Pronto em" : "Falhou após");
    return secs;
  };
  BB.loaderScan = function (root) {
    (root || document).querySelectorAll("[data-ll]").forEach((e) => { if (!e.querySelector(".lattice-loader")) e.innerHTML = BB.loader(e.dataset.ll); });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => BB.loaderScan()); else setTimeout(() => BB.loaderScan(), 0);

  BB.esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // 0.32.217 (pedido do dono): o botão Trocar rede abre um menu logo abaixo com as redes, sem passar pela página /entrar.
  const NETS = [
    ["pump", "/app", "#5fd38d", "Solana", "PUMP FUN", '<svg viewBox="0 0 126 126" aria-hidden="true"><g transform="rotate(-45 63 63)"><rect x="16" y="42" width="94" height="42" rx="21" fill="#f4f4f5"/><path d="M37 42h26v42H37a21 21 0 0 1 0-42z" fill="#5fd38d"/><rect x="16" y="42" width="94" height="42" rx="21" fill="none" stroke="#0a0a0a" stroke-width="6"/><path d="M63 42v42" stroke="#0a0a0a" stroke-width="6"/></g></svg>'],
    ["bnb", "/bnb", "#f0b90b", "BNB Chain", "BNB · FOUR.MEME", '<svg viewBox="0 0 126 126" aria-hidden="true"><g fill="#f0b90b"><path d="M63 14l35 35-9.5 9.5L63 33 37.5 58.5 28 49z"/><path d="M63 112l35-35-9.5-9.5L63 93 37.5 67.5 28 77z"/><path d="M16 63l12-12 12 12-12 12z"/><path d="M86 63l12-12 12 12-12 12z"/><path d="M51 63l12-12 12 12-12 12z"/></g></svg>'],
    ["hood", "/hood", "#c3f53c", "Robinhood Chain", "ROBINHOOD", '<svg viewBox="0 0 126 126" aria-hidden="true"><path d="M63 12l44 25v52l-44 25-44-25V37z" fill="none" stroke="#c3f53c" stroke-width="9" stroke-linejoin="round"/><path d="M63 40l20 11.5v23L63 86 43 74.5v-23z" fill="#c3f53c"/></svg>'],
  ];
  let netPop = null;
  const netClose = () => { if (netPop) { netPop.remove(); netPop = null; } };
  function netOpen(btn) {
    netClose();
    const here = location.pathname.replace(/\/+$/, "") || "/app";
    const d = document.createElement("div");
    d.className = "netpop"; d.setAttribute("role", "menu");
    d.innerHTML = '<div class="netpop-h">Trocar rede</div>' + NETS.map(([k, href, cor, chain, nome, svg]) => {
      const on = here === href;
      return '<a role="menuitem" href="' + href + '" data-net="' + k + '" class="' + (on ? "on" : "") + '" style="--nc:' + cor + '">' + svg +
        '<span><b>' + nome + '</b><small>' + chain + '</small></span>' + (on ? '<i>você está aqui</i>' : '') + '</a>';
    }).join("");
    document.body.appendChild(d);
    const r = btn.getBoundingClientRect(), w = d.offsetWidth, vw = document.documentElement.clientWidth;
    d.style.top = Math.round(r.bottom + 6) + "px";
    d.style.left = Math.round(Math.max(8, Math.min(r.left, vw - w - 8))) + "px";
    d.querySelectorAll("[data-net]").forEach((a) => a.addEventListener("click", (e) => {
      if (a.classList.contains("on")) { e.preventDefault(); netClose(); return; }
      try { sessionStorage.setItem("pf_hub", a.dataset.net); } catch (err) { /* segue */ }
    }));
    netPop = d;
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".hubbtn");
    if (btn) { e.preventDefault(); if (netPop) netClose(); else netOpen(btn); return; }
    if (netPop && !netPop.contains(e.target)) netClose();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") netClose(); });
  window.addEventListener("resize", netClose);
  window.addEventListener("scroll", netClose, true);
})();
