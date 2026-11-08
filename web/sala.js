// 0.32.266 (pedido do dono, 08/11): Sala ao vivo. Um trader em pixel art, desenhado aqui mesmo (sem imagem de fora), reage às
// compras e vendas da conta (FICTÍCIA ou REAL): procura gems parado, comemora no lucro, sua frio no prejuízo e aperta o botão
// gigante a cada compra/venda. Em volta: no telão a posição com o melhor e a com o pior resultado (0.32.268; sem posição, o
// gráfico da carteira), alertas, posições abertas com o % ao vivo e o letreiro dos últimos trades. Feita para capturar a janela numa live (OBS). Só lê /api/pump; não manda ordem nenhuma.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const W = 320, H = 180;
  const cv = $("scene"), g = cv.getContext("2d");
  g.imageSmoothingEnabled = false;

  // ------------------------------------------------------------------ estado
  const S = {
    real: false, base: "idle", action: null, actionUntil: 0, frame: 0, t0: Date.now(),
    curve: [], positions: [], trades: [], wallet: {}, seenPos: null, seenTr: null, hist: {}, parts: [], sound: false,
    openPct: null, ok: false,
  };
  try {
    const q = new URLSearchParams(location.search).get("modo");
    S.real = q ? q === "real" : localStorage.getItem("sala_modo") === "real";
  } catch (e) { /* sem armazenamento: começa na fictícia */ }

  // ------------------------------------------------------------------ desenho (pixels)
  const R = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); };
  const TXT = (s, x, y, c, size) => { g.fillStyle = c; g.font = (size || 8) + 'px "Press Start 2P", monospace'; g.textBaseline = "top"; g.fillText(s, x, y); };

  function room(f) {
    for (let y = 0; y < 128; y += 4) R(0, y, W, 4, y % 8 ? "#121c3f" : "#0f1836");
    R(0, 128, W, 52, "#1a1426");
    // pôster do foguete
    R(10, 16, 36, 46, "#22305e"); R(12, 18, 32, 42, "#0b1430");
    const ry = 40 - (S.base === "pump" ? (f % 6) : 0);
    R(25, ry, 6, 12, "#e8e8f0"); R(26, ry - 3, 4, 3, "#ff4d5e"); R(23, ry + 8, 2, 4, "#ff4d5e"); R(31, ry + 8, 2, 4, "#ff4d5e");
    if (S.base === "pump") { R(26, ry + 12, 4, 3 + (f % 3), "#ffd23f"); }
    TXT("MOON", 12, 50, "#3df2c4", 8);
    // pôster HODL
    R(54, 10, 40, 22, "#3a1d5e"); R(56, 12, 36, 18, "#1a0d33"); TXT("HODL", 58, 16, "#ffd23f", 8);
    // relógio
    R(104, 12, 16, 16, "#2a3c6b"); R(106, 14, 12, 12, "#e8f0ff"); R(111, 16, 2, 5, "#111"); R(111, 20, 4, 1, "#111");
    // monitor lateral com velas
    R(8, 74, 50, 36, "#2b2f3a"); R(10, 76, 46, 30, "#04121f");
    for (let i = 0; i < 7; i++) {
      const up = (i + Math.floor(f / 6)) % 3 !== 0;
      const h = 4 + ((i * 7 + Math.floor(f / 6)) % 13);
      R(13 + i * 6, 100 - h, 3, h, up ? "#3ee66b" : "#ff4d5e");
    }
    R(30, 110, 6, 8, "#2b2f3a");
  }

  // 0.32.268 (pedido do dono): no telão, a posição aberta com o melhor e a com o pior resultado agora, com o % ao vivo
  function sparkPx(arr, x0, y0, w, h) {
    if (!arr || arr.length < 2) return;
    const lo = Math.min(0, ...arr), hi = Math.max(0, ...arr), sp = hi - lo || 1;
    R(x0, y0 + h - Math.round((0 - lo) / sp * h), w, 1, "#1d3a4f");
    let px = null, py = null;
    arr.forEach((v, i) => {
      const x = x0 + Math.round(i * (w - 1) / (arr.length - 1)), y = y0 + h - Math.round((v - lo) / sp * h);
      const c = v >= 0 ? "#3ee66b" : "#ff4d5e";
      if (px !== null) { const st = Math.max(Math.abs(x - px), Math.abs(y - py), 1); for (let k = 0; k <= st; k++) R(px + (x - px) * k / st, py + (y - py) * k / st, 1, 1, c); }
      px = x; py = y;
    });
  }
  function slot(p, label, y, col, f) {
    const v = +p.pnl_now_pct || 0, t = (v > 0 ? "+" : "") + v.toFixed(1) + "%";
    R(176, y, 132, 41, "#06141f");
    TXT(label, 179, y + 3, col, 8);
    g.font = '8px "Press Start 2P", monospace';
    const tw = g.measureText(t).width;
    TXT(t, 305 - tw, y + 3, v >= 0 ? "#3ee66b" : "#ff4d5e", 8);
    TXT(String(p.symbol || (p.mint || "").slice(0, 6)).slice(0, 12).toUpperCase(), 179, y + 14, f % 10 < 8 ? "#e8f0ff" : "#8fa3d1", 8);
    sparkPx(S.hist[(p.id || (p.mint + "|" + p.opened_at))] || [], 179, y + 25, 126, 13);
  }
  function bigMonitor(f) {
    R(172, 18, 140, 96, "#2b2f3a"); R(175, 21, 134, 86, "#030c16");
    const P = S.positions.slice().sort((a, b) => (+b.pnl_now_pct || 0) - (+a.pnl_now_pct || 0));
    if (P.length) {
      if (P.length === 1) { slot(P[0], "ABERTA", 22, "#ffd23f", f); TXT("SO 1 POSICAO", 179, 72, "#8fa3d1", 8); }
      else { slot(P[0], "MELHOR", 22, "#3ee66b", f); slot(P[P.length - 1], "PIOR", 65, "#ff4d5e", f); }
      R(232, 114, 12, 10, "#2b2f3a");
      return;
    }
    TXT("CARTEIRA AO VIVO", 178, 24, "#3df2c4", 8);
    for (let x = 178; x < 307; x += 10) R(x, 33, 1, 72, "#0b2233");
    for (let y = 40; y < 105; y += 10) R(176, y, 132, 1, "#0b2233");
    const pts = S.curve.slice(-80).map((p) => +p[1]);
    if (pts.length > 1) {
      const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1;
      const up = pts[pts.length - 1] >= pts[0];
      const col = up ? "#3ee66b" : "#ff4d5e";
      let px = null, py = null;
      pts.forEach((v, i) => {
        const x = 178 + Math.round(i * 128 / (pts.length - 1)), y = 102 - Math.round((v - lo) / span * 62);
        if (px !== null) { const steps = Math.max(Math.abs(x - px), Math.abs(y - py), 1); for (let k = 0; k <= steps; k++) R(px + (x - px) * k / steps, py + (y - py) * k / steps, 1, 1, col); }
        px = x; py = y;
      });
      if (f % 8 < 5) R(px - 1, py - 1, 3, 3, "#ffffff");
      const last = S.trades[0];
      if (last) {
        const win = (last.pnl_sol || 0) > 0;
        R(px - 36, Math.max(36, py - 14), 34, 10, win ? "#3ee66b" : "#ff4d5e"); TXT(win ? "WIN" : "LOSS", px - 35, Math.max(37, py - 13), "#04121f", 8);
      }
    } else {
      TXT("SEM TRADES AINDA", 178, 64, "#8fa3d1", 8);
    }
    R(232, 114, 12, 10, "#2b2f3a");
  }

  function desk(f) {
    R(0, 128, W, 6, "#7a5230"); R(0, 134, W, 46, "#4a2f1c");
    for (let x = 0; x < W; x += 16) R(x, 136, 1, 44, "#3e2717");
    R(104, 122, 64, 7, "#3a3f4d"); for (let i = 0; i < 9; i++) R(107 + i * 7, 124, 5, 2, (S.base === "idle" && (i + f) % 4 === 0) ? "#9fb3ff" : "#5d6475");
    R(172, 124, 8, 5, "#3a3f4d");
    // copo gigante de café
    R(70, 98, 20, 30, "#e8e8f0"); R(70, 104, 20, 6, "#ff4d5e"); R(90, 106, 4, 12, "#e8e8f0");
    for (let i = 0; i < 3; i++) { const sy = 92 - ((f * 2 + i * 7) % 18); R(74 + i * 6, sy, 2, 4, "rgba(220,230,255,.5)"); }
    // botão gigante
    const act = S.action && Date.now() < S.actionUntil;
    const buy = act && S.action === "buy";
    const col = act ? (buy ? "#3ee66b" : "#ff4d5e") : "#a81f2d";
    R(196, 118, 34, 6, "#222"); R(198, act && f % 4 < 2 ? 116 : 113, 30, 6, col);
    TXT(act ? (buy ? "PUMP" : "DUMP") : "PUMP", 197, 126, act ? col : "#ff4d5e", 8);
  }

  function trader(f) {
    const st = S.action && Date.now() < S.actionUntil ? "act" : S.base;
    const bob = st === "pump" ? (f % 4 < 2 ? -2 : 0) : (st === "idle" ? (f % 16 < 8 ? 0 : 1) : 0);
    const x = 112, y = 58 + bob;
    R(104, 66, 52, 62, "#7a1d2b"); R(108, 70, 44, 54, "#962536");               // cadeira
    R(x, y + 36, 36, 34, "#3a4560"); R(x + 14, y + 36, 8, 6, "#2c3550");        // moletom
    R(x + 15, y + 42, 1, 6, "#cfd6e6"); R(x + 20, y + 42, 1, 6, "#cfd6e6");
    R(x + 6, y + 6, 24, 26, "#f2c28b"); R(x + 4, y + 16, 2, 6, "#e3ad73"); R(x + 30, y + 16, 2, 6, "#e3ad73"); // cabeça
    R(x + 4, y + 2, 28, 8, "#1d2433"); R(x + 2, y + 9, 34, 3, "#141a26"); R(x + 14, y + 3, 6, 3, "#3df2c4"); // boné
    R(x + 7, y + 14, 22, 6, "#000"); R(x + 18, y + 15, 1, 2, "#000");             // óculos
    if (st === "pump") { // olhos de cifrão
      ["#ffd23f"].forEach((c) => { R(x + 10, y + 15, 3, 1, c); R(x + 10, y + 17, 3, 1, c); R(x + 11, y + 14, 1, 6, c); R(x + 22, y + 15, 3, 1, c); R(x + 22, y + 17, 3, 1, c); R(x + 23, y + 14, 1, 6, c); });
    } else { R(x + 9, y + 15, 3, 1, "#5b6b8f"); R(x + 21, y + 15, 3, 1, "#5b6b8f"); }
    if (st === "dump") { R(x + 13, y + 26, 10, 2, "#7a2b2b"); R(x + 12, y + 27, 2, 2, "#7a2b2b"); R(x + 22, y + 27, 2, 2, "#7a2b2b"); }
    else if (st === "pump" || st === "act") { R(x + 11, y + 24, 14, 4, "#5a1414"); R(x + 13, y + 24, 10, 1, "#fff"); }
    else { R(x + 13, y + 25, 10, 2, "#9c5a3c"); }
    R(x + 15, y + 30, 6, 4, "#f2c28b");                                             // pescoço
    // braços
    const skin = "#f2c28b", sleeve = "#3a4560";
    if (st === "pump") {
      const a = f % 6 < 3 ? 0 : 3;
      R(x - 6, y + 10 + a, 6, 30, sleeve); R(x - 6, y + 4 + a, 6, 6, skin);
      R(x + 36, y + 13 - a, 6, 30, sleeve); R(x + 36, y + 7 - a, 6, 6, skin);
    } else if (st === "dump") {
      R(x - 2, y + 12, 8, 28, sleeve); R(x + 2, y + 2, 7, 7, skin);
      R(x + 30, y + 12, 8, 28, sleeve); R(x + 27, y + 2, 7, 7, skin);
    } else if (st === "act") {
      R(x - 4, y + 40, 6, 22, sleeve); R(x - 4, y + 62, 6, 4, skin);
      R(x + 34, y + 44, 52, 6, sleeve); R(x + 84, y + 50 + (f % 4 < 2 ? 0 : 2), 8, 6, skin);
    } else {
      const k = f % 4 < 2 ? 0 : 2;
      R(x - 4, y + 40, 6, 22, sleeve); R(x - 2, y + 60 + k, 8, 4, skin);
      R(x + 34, y + 40, 6, 22, sleeve); R(x + 30, y + 62 - k, 8, 4, skin);
    }
    if (st === "dump") {                                                            // suor e lágrimas
      for (let i = 0; i < 2; i++) { const dy = (f * 2 + i * 9) % 22; R(x + 9 + i * 16, y + 20 + dy, 2, 3, "#6fd3ff"); }
      R(x + 5, y + 4 + (f % 10), 2, 3, "#6fd3ff");
    }
  }

  function fx(f) {
    const now = Date.now();
    if (S.base === "pump" && f % 3 === 0) S.parts.push({ x: 120 + Math.random() * 40, y: 60, vx: (Math.random() - .5) * 3, vy: -2 - Math.random() * 2, c: "#3ee66b", w: 6, h: 3, g: .18, life: 40 });
    if (S.base === "dump" && f % 4 === 0) S.parts.push({ x: Math.random() * W, y: -8, vx: 0, vy: 2 + Math.random() * 2, c: "#ff4d5e", w: 3, h: 6 + Math.random() * 8, g: 0, life: 60 });
    S.parts = S.parts.filter((p) => p.life-- > 0 && p.y < H + 10);
    S.parts.forEach((p) => { p.vy += p.g; p.x += p.vx; p.y += p.vy; R(p.x, p.y, p.w, p.h, p.c); if (p.c === "#3ee66b" && p.w === 6) R(p.x + 2, p.y + 1, 2, 1, "#1b6e33"); });
    if (S.base === "dump") {                                                        // mesa pegando fogo
      for (let i = 0; i < 10; i++) { const h = 6 + ((i * 5 + f * 3) % 9); R(20 + i * 28, 128 - h, 8, h, (i + f) % 2 ? "#ff7b1c" : "#ffd23f"); }
      if (f % 10 < 5) { R(0, 0, W, 2, "#ff4d5e"); R(0, H - 2, W, 2, "#ff4d5e"); }
    }
    if (S.base === "pump") { TXT("TO THE MOON!", 10, 132, f % 6 < 3 ? "#3ee66b" : "#ffd23f", 8); }
    if (S.base === "idle") {                                                         // radar procurando gems
      const a = (now / 600) % (Math.PI * 2);
      R(14, 140, 28, 28, "#06221b"); g.strokeStyle = "#3df2c4"; g.beginPath(); g.moveTo(28, 154); g.lineTo(28 + Math.cos(a) * 13, 154 + Math.sin(a) * 13); g.stroke();
      if (f % 20 < 10) R(34, 146, 2, 2, "#ffd23f");
      TXT("GEMS?", 46, 150, "#3df2c4", 8);
    }
  }

  function draw() {
    const f = S.frame++;
    room(f); bigMonitor(f); trader(f); desk(f); fx(f);
  }
  setInterval(draw, 83);

  // ------------------------------------------------------------------ som 8 bits
  let AC = null;
  function beep(seq, type) {
    if (!S.sound) return;
    try {
      AC = AC || new (window.AudioContext || window.webkitAudioContext)();
      let t = AC.currentTime;
      seq.forEach(([fq, d]) => {
        const o = AC.createOscillator(), v = AC.createGain();
        o.type = type || "square"; o.frequency.value = fq; v.gain.value = .06;
        o.connect(v); v.connect(AC.destination); o.start(t); o.stop(t + d); t += d;
      });
    } catch (e) { /* sem áudio */ }
  }
  const SFX = {
    buy: () => beep([[523, .07], [659, .07], [784, .07], [1046, .12]]),
    win: () => beep([[988, .08], [1319, .2]]),
    loss: () => beep([[440, .18], [330, .18], [440, .18], [330, .25]], "sawtooth"),
  };

  // ------------------------------------------------------------------ alertas, reações e letreiro
  let alertT = null;
  function alertBox(title, body, win) {
    $("aT").textContent = title; $("aB").innerHTML = body;
    $("alert").classList.toggle("win", !!win); $("alert").classList.add("show");
    const fl = $("flash"); fl.style.background = win ? "#3ee66b" : "#ff4d5e"; fl.classList.remove("go"); void fl.offsetWidth; fl.classList.add("go");
    clearTimeout(alertT); alertT = setTimeout(() => $("alert").classList.remove("show"), 5000);
  }
  const sym = (x) => esc(x.symbol || (x.mint || "").slice(0, 6));
  const pct = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(1) + "%");
  const sol = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(4) + " SOL");
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "flat");

  function act(kind) { S.action = kind; S.actionUntil = Date.now() + 2600; }

  function onBuy(p) {
    act("buy"); SFX.buy();
    alertBox("COMPRA!", "PUMP IT! <b>" + sym(p) + "</b><br>" + Number(p.sol_in || 0).toFixed(3) + " SOL", true);
  }
  function onSell(t) {
    act("sell");
    const v = t.pnl_sol || 0;
    if (v > 0) {
      SFX.win();
      alertBox("VENDA COM LUCRO", "<b>" + sym(t) + "</b> " + pct(t.pnl_pct) + "<br>" + sol(v) + " · TO THE MOON 🚀", true);
    } else {
      SFX.loss();
      alertBox("R.I.P. STOP LOSS", "<b>" + sym(t) + "</b> " + pct(t.pnl_pct) + "<br>" + sol(v) + " · vaga na lanchonete aberta 🍔", false);
    }
  }

  // ------------------------------------------------------------------ dados
  const pid = (p) => p.id || (p.mint + "|" + p.opened_at);
  const tid = (t) => t.id || ((t.pos_id || t.mint) + "|" + t.closed_at);
  const tms = (s) => { const v = Date.parse(s || ""); return isNaN(v) ? 0 : v; };

  function spark(c, arr) {
    const x = c.getContext("2d"); x.imageSmoothingEnabled = false;
    const w = c.width = 120, h = c.height = 28; x.clearRect(0, 0, w, h);
    if (arr.length < 2) return;
    const lo = Math.min(0, ...arr), hi = Math.max(0, ...arr), sp = hi - lo || 1;
    const zy = h - 2 - Math.round((0 - lo) / sp * (h - 4)); x.fillStyle = "#2a3c6b"; x.fillRect(0, zy, w, 1);
    arr.forEach((v, i) => {
      const px = Math.round(i * (w - 2) / (arr.length - 1)), py = h - 2 - Math.round((v - lo) / sp * (h - 4));
      x.fillStyle = v >= 0 ? "#3ee66b" : "#ff4d5e"; x.fillRect(px, py, 2, 2);
    });
  }

  function render() {
    const P = S.positions, w = S.wallet || {};
    let inv = 0, now = 0;
    P.forEach((p) => { inv += +p.sol_in || 0; now += +p.pnl_now_sol || 0; });
    S.openPct = inv ? now / inv * 100 : null;
    const recent = S.trades[0], recentT = recent ? tms(recent.closed_at) : 0;
    if (S.openPct != null) S.base = S.openPct > 2 ? "pump" : S.openPct < 0 ? "dump" : "idle";
    else if (recent && Date.now() - recentT < 120000) S.base = (recent.pnl_sol || 0) > 0 ? "pump" : "dump";
    else S.base = "idle";
    const hud = $("hud");
    if (S.openPct == null) hud.innerHTML = '<b class="flat">PROCURANDO GEMS…</b>';
    else if (S.openPct > 0) hud.innerHTML = 'PUMPING NOW! <b class="up">' + pct(S.openPct) + "</b>";
    else hud.innerHTML = 'DUMPING… <b class="down">' + pct(S.openPct) + "</b>";
    const res = +w.pnl_sol || 0;
    $("stats").innerHTML = [
      ["Carteira", (S.real ? "REAL" : "FICTÍCIA")],
      ["Resultado", '<span class="' + cls(res) + '">' + sol(res) + "</span>"],
      ["Acerto", w.win_rate == null ? "–" : Math.round(w.win_rate * 100) + "%"],
      ["Trades", String(w.count || 0)], ["Abertas", String(P.length)],
    ].map(([k, v]) => '<div class="st"><small>' + k + "</small> " + v + "</div>").join("");
    $("posN").textContent = P.length ? "(" + P.length + ")" : "";
    const box = $("pos");
    if (!P.length) { box.innerHTML = '<div class="empty">nenhuma posição aberta agora</div>'; }
    else {
      const sorted = P.slice().sort((a, b) => (b.pnl_now_pct || 0) - (a.pnl_now_pct || 0));
      box.innerHTML = sorted.map((p, i) => '<div class="pr"><span class="sy">' + sym(p) + '</span><span class="pc ' + cls(p.pnl_now_pct) + '">' + pct(p.pnl_now_pct) +
        '</span><canvas class="px" data-i="' + i + '"></canvas><small>' + Number(p.sol_in || 0).toFixed(3) + " SOL · " + sol(p.pnl_now_sol) + "</small></div>").join("");
      box.querySelectorAll("canvas").forEach((c) => spark(c, S.hist[pid(sorted[+c.dataset.i])] || []));
    }
    const items = S.trades.slice(0, 8).map((t) => ({ t: tms(t.closed_at), h: '<span class="' + cls(t.pnl_sol) + '">SELL ' + sym(t) + " " + pct(t.pnl_pct) + " (" + sol(t.pnl_sol) + ")</span>" }))
      .concat(P.slice(0, 8).map((p) => ({ t: tms(p.opened_at), h: '<span class="up">BUY ' + sym(p) + " " + Number(p.sol_in || 0).toFixed(3) + " SOL</span>" })))
      .sort((a, b) => b.t - a.t).slice(0, 12);
    $("run").innerHTML = items.length ? items.map((x) => x.h).join("") : '<span class="flat">HOLD! HODL! HODL!</span>';
  }

  async function load() {
    try {
      const js = await BB._api("/api/pump?ev=999999999999");
      if (js.error) throw new Error(js.error);
      const real = S.real;
      const P = (js.positions || []).filter((p) => !!p.real === real);
      const T = (js.trades || []).filter((t) => !!t.real === real).sort((a, b) => tms(b.closed_at) - tms(a.closed_at));
      if (S.seenPos) {
        P.filter((p) => !S.seenPos.has(pid(p))).forEach(onBuy);
        T.filter((t) => !S.seenTr.has(tid(t))).slice(0, 3).forEach(onSell);
      }
      S.seenPos = new Set(P.map(pid)); S.seenTr = new Set(T.map(tid));
      P.forEach((p) => { const k = pid(p), a = (S.hist[k] = S.hist[k] || []); a.push(+p.pnl_now_pct || 0); if (a.length > 60) a.shift(); });
      S.ok = true;
      S.positions = P; S.trades = T; S.wallet = real ? js.real_wallet : js.wallet; S.curve = (real ? js.real_curve : js.curve) || [];
      $("sub").textContent = "dados da sua conta · carteira " + (real ? "REAL" : "FICTÍCIA") + " · atualizado " + new Date().toLocaleTimeString("pt-BR");
      $("err").hidden = true;
      render();
    } catch (e) {
      $("err").textContent = "Não consegui ler os dados: " + (e.message || e) + " (tentando de novo)"; $("err").hidden = false;
    }
  }

  // ------------------------------------------------------------------ controles
  function setMode(real) {
    S.real = real; S.seenPos = null; S.seenTr = null; S.hist = {}; S.ok = false;
    try { localStorage.setItem("sala_modo", real ? "real" : "sim"); } catch (e) { /* */ }
    $("mSim").classList.toggle("on", !real); $("mReal").classList.toggle("on", real);
    load();
  }
  $("mSim").addEventListener("click", () => setMode(false));
  $("mReal").addEventListener("click", () => setMode(true));
  $("snd").addEventListener("click", () => { S.sound = !S.sound; $("snd").textContent = "SOM: " + (S.sound ? "ON" : "OFF"); $("snd").classList.toggle("on", S.sound); if (S.sound) SFX.buy(); });
  let hideT = null;
  const wake = () => { $("ctl").classList.remove("hide"); clearTimeout(hideT); hideT = setTimeout(() => $("ctl").classList.add("hide"), 5000); };
  ["mousemove", "touchstart", "keydown"].forEach((ev) => document.addEventListener(ev, wake, { passive: true }));
  wake();

  (async function start() {
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão */ }
    if (!s) { location.href = "/"; return; }
    $("mSim").classList.toggle("on", !S.real); $("mReal").classList.toggle("on", S.real);
    await load();
    setInterval(load, 2000);                         // 0.32.268: % das posições ao vivo
  })();
})();
