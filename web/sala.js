// 0.32.266 (pedido do dono, 08/11): Sala ao vivo. Feita para capturar a janela numa live (OBS). Só lê /api/pump (ou
// /api/hood/painel com ?rede=hood); não manda ordem nenhuma.
// 0.32.333 (pedido do dono, 13/11, com referências de pixel art de escritório, ícones de trading, balões e painéis): a sala virou
// um escritório de trading em pixel art. Tudo é desenhado aqui mesmo (sprites em texto, sem imagem de fora): o trader de camisa
// e gravata com headset, o BOT assistente que leva cada compra ao telão, janela com a cidade (dia e noite pela hora local),
// quadro branco com o resultado dos últimos trades, relógio de LED, bebedouro e planta. Balões de fala reagem a cada compra e
// venda; o painel ao lado ganhou janelas retrô com ícones e o LOG DO ROBÔ (as decisões da cópia, ao vivo).
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
    openPct: null, ok: false, say: null, botSay: null, bot: { mode: "idle", t0: 0, sym: "" }, log: [], seenLog: null,
  };
  // 0.32.293 (pedido do dono: "faça uma sala igual à do Pump para o hood"): /sala?rede=hood usa a cópia da Robinhood Chain
  // (/api/hood/painel, em ETH); a cena, os alertas e o letreiro são os mesmos.
  // 0.32.336 (pedido do dono): a mesma cena serve a página BOT LIVE (/botlive), que define window.SALA_CFG antes deste arquivo
  // (rede, carteira, nome do bot, balões, céu, modo privado). C() é lido a cada quadro: mudar a configuração muda a cena na hora.
  const C = () => window.SALA_CFG || {};
  const HOOD = C().rede ? C().rede === "hood" : new URLSearchParams(location.search).get("rede") === "hood";
  const U = HOOD ? "ETH" : "SOL", MKEY = C().mkey || (HOOD ? "sala_modo_hood" : "sala_modo");
  const PRIV = () => !!C().privado;
  // 0.32.340 (pedido do dono): no BOT LIVE os horários são em UTC (horário global, para quem assiste de qualquer lugar)
  const TZO = () => (C().botlive ? { timeZone: "UTC" } : {});
  const hms = (d, o) => new Date(d).toLocaleTimeString("pt-BR", Object.assign({}, o || {}, TZO()));                 // modo privado: esconde saldo e valores (só %), para a live
  try {
    const q = new URLSearchParams(location.search).get("modo");
    S.real = C().carteira ? C().carteira === "real" : q ? q === "real" : localStorage.getItem(MKEY) === "real";
    if (C().sfx) S.sound = true;
  } catch (e) { /* sem armazenamento: começa na fictícia */ }

  // ------------------------------------------------------------------ desenho (pixels)
  const R = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); };
  const TXT = (s, x, y, c, size) => { g.fillStyle = c; g.font = (size || 8) + 'px "Press Start 2P", monospace'; g.textBaseline = "top"; g.fillText(s, x, y); };
  const TW = (s, size) => { g.font = (size || 8) + 'px "Press Start 2P", monospace'; return g.measureText(s).width; };
  const K = "#140c1c";

  // Paleta e sprites (cada letra = uma cor; "." = transparente). Compilados uma vez em canvas e desenhados sem suavizar.
  const PAL = {
    k: K, s: "#f2c28b", S: "#d9935a", h: "#5a3418", H: "#86512a", w: "#ffffff", b: "#4b8fe2", B: "#2f69b5", t: "#c9372c",
    y: "#ffd23f", Y: "#d99a00", o: "#ff9f1c", r: "#ff4d5e", R: "#a81f2d", n: "#3ee66b", N: "#1b8f3f", v: "#9b5cff", V: "#5b2bbf",
    c: "#6fd3ff", C: "#2a8fbf", l: "#c8d0e0", L: "#8a94a8", d: "#5d6475", D: "#3a3f4d", x: "#a8743f", X: "#6e4523", G: "#3df2c4",
  };
  const SPR = {
    head: [
      "...k.kkk.kk.k...",
      "..khkhhhkhhkhk..",
      ".khhhhhhhhhhhhk.",
      "khhHhhhhhhhHhhhk",
      "khhhhhhhhhhhhhhk",
      "khhhshhhhhhshhhk",
      "khhsssssssssshhk",
      "khsssssssssssshk",
      "kssssssssssssssk",
      "kssssssssssssssk",
      "kSssssssssssssSk",
      ".kssssssssssssk.",
      ".kSssssssssssSk.",
      "..kSssssssssSk..",
      "...kkSssssSkk...",
      ".....kkkkkk.....",
    ],
    bot: [
      "......GG......",
      "......kk......",
      "..kkkkkkkkkk..",
      ".kllllllllllk.",
      ".klDDDDDDDDlk.",
      ".klDDDDDDDDlk.",
      ".klDDDDDDDDlk.",
      ".klDDDDDDDDlk.",
      ".kllllllllllk.",
      "..kkkkkkkkkk..",
      "...kLLLLLLk...",
      "..kLllllllLk..",
      "...kLLLLLLk...",
      "....kk..kk....",
    ],
    coin: [
      "..kkkkkk..",
      ".kyyyyyyk.",
      "kyywyyyyYk",
      "kywyyyyyYk",
      "kyyyyyyyYk",
      "kyyyyyyyYk",
      "kyyyyyyyYk",
      "kYyyyyyYYk",
      ".kYYYYYYk.",
      "..kkkkkk..",
    ],
    rocket: [
      "....k....",
      "...kwk...",
      "..kwwwk..",
      "..kwcwk..",
      "..kwwwk..",
      "..kwwwk..",
      ".kkwwwkk.",
      "krkwwwkrk",
      "krrkkkrrk",
      "kk.kok.kk",
      "...kyk...",
      "....y....",
    ],
    trophy: [
      "kkkkkkkkkk",
      "kyyyyywyyk",
      ".kyyyyyyk.",
      ".kyyyyyyk.",
      "..kyyyyk..",
      "...kyyk...",
      "....kk....",
      "...kYYk...",
      "..kYYYYk..",
      "..kkkkkk..",
    ],
    skull: [
      "..kkkkk..",
      ".kwwwwwk.",
      "kwwwwwwwk",
      "kwkkwkkwk",
      "kwkkwkkwk",
      "kwwwkwwwk",
      ".kwwwwwk.",
      ".kwkwkwk.",
      "..kkkkk..",
    ],
    up: [
      "...k...",
      "..knk..",
      ".knnnk.",
      "knnnnnk",
      "kknnnkk",
      "..knk..",
      "..kkk..",
    ],
    down: [
      "..kkk..",
      "..krk..",
      "kkrrrkk",
      "krrrrrk",
      ".krrrk.",
      "..krk..",
      "...k...",
    ],
    plant: [
      "....nn......",
      "...nNn..n...",
      "..nNn..nNn..",
      ".nNn..nNn...",
      "..nNnnNn.nn.",
      "....nNNnNNn.",
      "..nn.nNNn...",
      ".nNNn.Nn....",
      "..nNNnN.....",
      "....nN......",
      "..kkkkkkkk..",
      "..kxxxxxxk..",
      "...kxxxxk...",
      "...kxXxxk...",
      "...kxxxxk...",
      "....kkkk....",
    ],
    cooler: [
      "...kkkkkk...",
      "..kcwccccck.",
      "..kcwccccck.",
      "..kcwccccck.",
      "..kcwccccck.",
      "..kcccccccck",
      "...kkkkkk...",
      "....kddk....",
      ".kkkkkkkkkk.",
      ".kllllllllk.",
      ".kllrllcllk.",
      ".kllkllkllk.",
      ".kllllllllk.",
      ".kllllllllk.",
      ".kllllllllk.",
      ".kLLLLLLLLk.",
      ".kllllllllk.",
      ".kllllllllk.",
      ".kLLLLLLLLk.",
      ".kkkkkkkkkk.",
    ],
  };
  SPR.cooler[5] = "..kcccccck..";
  const CACHE = {};
  function sprite(name) {
    if (CACHE[name]) return CACHE[name];
    const rows = SPR[name], c = document.createElement("canvas");
    c.width = Math.max(...rows.map((r) => r.length)); c.height = rows.length;
    const x = c.getContext("2d");
    rows.forEach((row, j) => { for (let i = 0; i < row.length; i++) { const p = PAL[row[i]]; if (p) { x.fillStyle = p; x.fillRect(i, j, 1, 1); } } });
    return (CACHE[name] = c);
  }
  function spr(name, x, y, sc, flip) {
    const c = sprite(name), s = sc || 1;
    if (flip) { g.save(); g.translate(Math.round(x) + c.width * s, Math.round(y)); g.scale(-1, 1); g.drawImage(c, 0, 0, c.width * s, c.height * s); g.restore(); }
    else g.drawImage(c, Math.round(x), Math.round(y), c.width * s, c.height * s);
  }
  // ícones do painel ao lado (as mesmas figuras da cena, em imagem)
  const ICON = {};
  function icon(name, sc) {
    const k = name + (sc || 2);
    if (!ICON[k]) {
      const c = sprite(name), o = document.createElement("canvas"), s = sc || 2;
      o.width = c.width * s; o.height = c.height * s;
      const x = o.getContext("2d"); x.imageSmoothingEnabled = false; x.drawImage(c, 0, 0, o.width, o.height);
      ICON[k] = o.toDataURL();
    }
    return '<img class="px ico" alt="" src="' + ICON[k] + '">';
  }
  // linha grossa em pixels (braços)
  function seg(x1, y1, x2, y2, w, c) {
    const st = Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1), 1);
    for (let k = 0; k <= st; k++) R(x1 + (x2 - x1) * k / st - w / 2, y1 + (y2 - y1) * k / st - w / 2, w, w, c);
  }
  const HOOD_C = "#e4572e", HOOD_D = "#b23a1c";
  function arm(x1, y1, x2, y2) { seg(x1, y1, x2, y2, 8, K); seg(x1, y1, x2, y2, 6, HOOD_C); hand(x2, y2); }
  function hand(x, y) { R(x - 4, y - 4, 8, 8, K); R(x - 3, y - 3, 6, 6, "#f2c28b"); R(x - 3, y + 1, 6, 2, "#d9935a"); }

  // ------------------------------------------------------------------ cenário
  const BLD = [[0, 30, 10], [11, 22, 12], [24, 38, 9], [34, 18, 14], [49, 34, 10], [60, 26, 12], [73, 40, 8], [82, 28, 6]];
  function windowView(f) {
    const ceu = C().ceu, x0 = 6, y0 = 8, w = 88, h = 62;
    const hr = ceu === "dia" ? 12 : ceu === "tarde" ? 19 : ceu === "noite" ? 23 : new Date().getHours();
    const day = hr >= 7 && hr < 18, dusk = hr >= 18 && hr < 20;
    R(x0 - 3, y0 - 3, w + 6, h + 6, K); R(x0 - 2, y0 - 2, w + 4, h + 4, "#d7dceb");
    const sky = day ? ["#7cc4ff", "#9ad3ff", "#b9e2ff"] : dusk ? ["#ff7b54", "#ffb26b", "#ffd56b"] : ["#0a1030", "#121a44", "#1b2456"];
    for (let i = 0; i < 3; i++) R(x0, y0 + i * (h / 3), w, h / 3 + 1, sky[i]);
    if (!day && !dusk) for (let i = 0; i < 12; i++) if ((i * 7 + Math.floor(f / 10)) % 9) R(x0 + (i * 23) % w, y0 + (i * 13) % 26, 1, 1, "#ffffff");
    if (day) { R(x0 + 60, y0 + 6, 10, 10, "#fff3a0"); R(x0 + 62, y0 + 4, 6, 14, "#fff3a0"); }
    else if (!dusk) { R(x0 + 60, y0 + 6, 8, 8, "#e8f0ff"); R(x0 + 63, y0 + 6, 5, 6, sky[0]); }
    if (S.base === "pump") {                                              // foguete cruzando o céu
      const p = (f % 60) / 60;
      spr("rocket", x0 + 6 + p * 60, y0 + h - 14 - p * 50, 1);
    }
    BLD.forEach(([bx, bh, bw], i) => {
      R(x0 + bx, y0 + h - bh, bw, bh, day ? "#5d6a8f" : "#20284a");
      for (let yy = y0 + h - bh + 3; yy < y0 + h - 2; yy += 5) for (let xx = x0 + bx + 2; xx < x0 + bx + bw - 2; xx += 4)
        if (((xx * 3 + yy + i) % 7) > (day ? 4 : 2)) R(xx, yy, 2, 2, day ? "#a9c4ff" : "#ffd96b");
    });
    if (S.base === "dump") for (let i = 0; i < 10; i++) { const rx = x0 + (i * 9 + f * 3) % w, ry = y0 + (i * 17 + f * 5) % h; R(rx, ry, 1, 4, "#9fc3ff"); }
    R(x0 + w / 2 - 1, y0, 2, h, "#d7dceb"); R(x0, y0 + h / 2 - 1, w, 2, "#d7dceb");          // caixilho
    R(x0 - 4, y0 + h + 2, w + 8, 4, "#8a94a8");                                          // parapeito
  }
  // quadro branco: resultado dos últimos trades (verde = lucro, vermelho = perda)
  function board(f) {
    const x0 = 104, y0 = 8, w = 62, h = 48;
    R(x0 - 2, y0 - 2, w + 4, h + 4, K); R(x0 - 1, y0 - 1, w + 2, h + 2, "#8a94a8"); R(x0, y0, w, h, "#f4f6fb");
    TXT("PNL", x0 + 3, y0 + 3, "#2f69b5", 8);
    const T = S.trades.slice(0, 11).reverse(), mid = y0 + 30;
    R(x0 + 3, mid, w - 6, 1, "#c8d0e0");
    T.forEach((t, i) => {
      const v = +t.pnl_pct || 0, hh = Math.min(16, Math.round(Math.abs(v) / 4) + 1), bx = x0 + 5 + i * 5;
      if (v >= 0) R(bx, mid - hh, 4, hh, "#3ee66b"); else R(bx, mid + 1, 4, hh, "#ff4d5e");
    });
    if (!T.length) TXT("...", x0 + 22, y0 + 24, "#8a94a8", 8);
    const wins = T.filter((t) => (+t.pnl_sol || 0) > 0).length;
    if (T.length) TXT(wins + "/" + T.length, x0 + w - 3 - TW(wins + "/" + T.length), y0 + 3, wins * 2 >= T.length ? "#1b8f3f" : "#a81f2d", 8);
    R(x0 + 10, y0 + h + 2, 30, 3, "#8a94a8"); R(x0 + 14, y0 + h + 1, 6, 2, "#ff4d5e"); R(x0 + 24, y0 + h + 1, 6, 2, "#2f69b5");
  }
  function room(f) {
    for (let y = 0; y < 128; y += 4) R(0, y, W, 4, y % 8 ? "#17224a" : "#141e42");
    for (let x = 0; x < W; x += 40) R(x, 0, 1, 124, "#1b2752");
    R(0, 120, W, 8, "#0f1734");                                                         // rodapé
    windowView(f); board(f);
    spr("cooler", 4, 86, 2);                                                            // bebedouro (fica atrás da mesa)
    if (f % 90 < 6) R(24, 98, 2, 2, "#ffffff");
    spr("plant", 40, 96, 2);
    // relógio de LED e cotação em cima do telão
    R(174, 3, 136, 12, K); R(175, 4, 134, 10, "#05140c");
    // 0.32.340: o relógio fica sozinho no LED (antes a cotação encostava nos segundos); a cotação foi para a barra do telão
    const hhmm = hms(Date.now(), { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + (C().botlive ? " UTC" : "");
    TXT(hhmm, 242 - TW(hhmm) / 2, 5, "#3ee66b", 8);
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
    R(178, y, 128, 40, "#06141f");
    spr(v >= 0 ? "up" : "down", 180, y + 2, 1);
    TXT(label, 190, y + 3, col, 8);
    TXT(t, 304 - TW(t), y + 3, v >= 0 ? "#3ee66b" : "#ff4d5e", 8);
    TXT((p.risco ? "! " : "") + String(p.symbol || (p.mint || "").slice(0, 6)).slice(0, 12).toUpperCase(), 180, y + 14, p.risco ? (f % 10 < 8 ? "#facc15" : "#a16207") : f % 10 < 8 ? "#e8f0ff" : "#8fa3d1", 8);
    sparkPx(S.hist[(p.id || (p.mint + "|" + p.opened_at))] || [], 180, y + 25, 124, 13);
  }
  // 0.32.342 (pedido do dono: "pode preencher esse espaço"): no BOT LIVE sem trades, o telão vira o RADAR do BOT — quantos top traders
  // ele copia e as últimas decisões (horário, token e NC/COMPRA/VENDA), com uma linha de varredura passando.
  function radar(f) {
    R(176, 42, 132, 70, "#030c16");
    TXT("RADAR · " + (S.seguindo || 0) + " TOP", 178, 43, "#ffd23f", 8);
    const L = [];
    S.log.filter((x) => x.k !== "bl-status").forEach((x) => {
      const last = L[L.length - 1];
      if (!last || last.s !== x.s || logCode(last.a) !== logCode(x.a)) L.push(x);
    });
    L.splice(6);
    if (!L.length) TXT("AGUARDANDO COMPRA", 178, 70, "#8fa3d1", 8);
    L.forEach((x, i) => {
      const y = 55 + i * 9, code = logCode(x.a), col = code === "NC" ? "#8fa3d1" : code === "VENDA" ? "#ff9f1c" : "#3ee66b";
      TXT(String(x.h || "").slice(0, 5), 178, y, "#4f7a5e", 8);
      TXT(String(x.s || "?").toUpperCase().slice(0, 7), 222, y, "#f5d0fe", 8);
      TXT(code === "COMPRA" ? "C" : code === "VENDA" ? "V" : "NC", 306 - TW(code === "COMPRA" ? "C" : code === "VENDA" ? "V" : "NC"), y, col, 8);
    });
    const sy = 52 + (f * 2) % 58;
    R(176, sy, 132, 1, "rgba(61,242,196,.25)");
  }
  function bigMonitor(f) {
    R(170, 17, 144, 100, K); R(171, 18, 142, 98, "#2b2f3a");
    R(174, 21, 136, 8, "#2a3c6b"); TXT("TELAO", 177, 21, "#e8f0ff", 8);                // barra de título da janela
    const u = +(S.wallet || {}).sol_usd || 0;
    if (u) { const s = U + " $" + (u >= 1000 ? Math.round(u) : u.toFixed(0)); TXT(s, 307 - TW(s), 21, "#ffd23f", 8); }
    else { R(296, 23, 4, 4, "#ffd23f"); R(302, 23, 4, 4, "#ff4d5e"); }
    R(174, 29, 136, 84, "#030c16");
    for (let y = 30; y < 113; y += 2) R(174, y, 136, 1, "rgba(255,255,255,.02)");       // linhas de TV antiga
    const P = S.positions.slice().sort((a, b) => (+b.pnl_now_pct || 0) - (+a.pnl_now_pct || 0));
    if (P.length) {
      if (P.length === 1) { slot(P[0], "ABERTA", 31, "#ffd23f", f); TXT("SO 1 POSICAO", 180, 80, "#8fa3d1", 8); }
      else { slot(P[0], "MELHOR", 31, "#3ee66b", f); slot(P[P.length - 1], "PIOR", 72, "#ff4d5e", f); }
    } else {
      TXT("CARTEIRA AO VIVO", 178, 32, "#3df2c4", 8);
      for (let x = 178; x < 307; x += 10) R(x, 42, 1, 68, "#0b2233");
      for (let y = 48; y < 110; y += 10) R(176, y, 132, 1, "#0b2233");
      const pts = S.curve.slice(-80).map((p) => +p[1]);
      if (pts.length > 1) {
        const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1;
        const col = pts[pts.length - 1] >= pts[0] ? "#3ee66b" : "#ff4d5e";
        let px = null, py = null;
        pts.forEach((v, i) => {
          const x = 178 + Math.round(i * 128 / (pts.length - 1)), y = 108 - Math.round((v - lo) / span * 58);
          if (px !== null) { const steps = Math.max(Math.abs(x - px), Math.abs(y - py), 1); for (let k = 0; k <= steps; k++) R(px + (x - px) * k / steps, py + (y - py) * k / steps, 1, 1, col); }
          px = x; py = y;
        });
        if (f % 8 < 5) R(px - 1, py - 1, 3, 3, "#ffffff");
      } else if (C().botlive) radar(f);
      else TXT("SEM TRADES AINDA", 180, 70, "#8fa3d1", 8);
    }
    R(234, 117, 16, 8, "#2b2f3a"); R(226, 124, 32, 3, "#2b2f3a");                      // pé do monitor
  }

  // ------------------------------------------------------------------ personagens
  // 0.32.334 (pedido do dono: "troque o personagem por um mais casual; ele tem que se mexer como quem trabalha e reagir conforme o
  // mercado melhora ou piora: nervoso, feliz, atento, dedicado"): dev casual de moletom com capuz, fone grande, óculos e cabelo
  // bagunçado. O humor (S.mood) vem do resultado das posições abertas e da tendência dos últimos 20 s:
  //   euforia (≥ +10%) · feliz (≥ +2%) · atento (entre −3% e +2%, ou sem posição) · dedicado (até −10%) · nervoso (abaixo de −10%).
  // Em cada humor ele alterna atividades de trabalho (digitar, mexer no mouse, pensar, tomar café, olhar o telão…).
  const MOODS = {
    euforia: ["festa", "festa", "danca", "festa"],
    feliz: ["digita", "musica", "cafe", "espreguica"],
    atento: ["digita", "mouse", "pensa", "olha", "cafe"],
    dedicado: ["rapido", "rapido", "mouse", "limpa", "rapido"],
    nervoso: ["unha", "cabeca", "rapido", "unha", "cabeca"],
  };
  function face(hx, hy, ex, f, look) {
    const P = (x, y, w, h, c) => R(hx + x * 2, hy + y * 2, w * 2, h * 2, c);
    const lk = look || 0;                                                     // pupilas para o lado (olhando o telão)
    // óculos redondos
    const glass = (x) => { P(x, 7, 4, 1, K); P(x, 10, 4, 1, K); P(x - 1, 8, 1, 2, K); P(x + 4, 8, 1, 2, K); P(x, 8, 4, 2, "rgba(170,220,255,.35)"); };
    const eyes = (h) => { P(3 + lk, 8, 1, h, K); P(10 + lk, 8, 1, h, K); };
    if (ex === "happy") {
      glass(2); glass(9); P(6, 8, 3, 1, K);
      P(2 + 1, 9, 1, 1, K); P(3 + 1, 8, 1, 1, K); P(4 + 1, 9, 1, 1, K); P(9 + 1, 9, 1, 1, K); P(10 + 1, 8, 1, 1, K); P(11 + 1, 9, 1, 1, K);
      P(5, 12, 6, 1, K); P(6, 13, 4, 1, "#9c2f3a"); P(1, 11, 2, 1, "#ff9a9a"); P(13, 11, 2, 1, "#ff9a9a");
      return;
    }
    glass(2); glass(9); P(6, 8, 3, 1, K);
    if (ex === "panic") {
      P(3, 8, 2, 2, "#ffffff"); P(10, 8, 2, 2, "#ffffff"); P(3 + (f % 2), 8, 1, 1, K); P(10 + (f % 2), 8, 1, 1, K);
      P(2, 5, 3, 1, K); P(10, 5, 3, 1, K); P(7, 12, 2, 2, K);
    } else if (ex === "worried") {
      P(2, 6, 1, 1, K); P(3, 5, 2, 1, K); P(12, 6, 1, 1, K); P(10, 5, 2, 1, K); eyes(2); P(6, 13, 4, 1, K); P(5, 12, 1, 1, K); P(10, 12, 1, 1, K);
    } else if (ex === "focus") {
      P(2, 6, 3, 1, K); P(10, 6, 3, 1, K); P(3 + lk, 9, 2, 1, K); P(10 + lk, 9, 2, 1, K); P(6, 13, 4, 1, K);
    } else if (ex === "bite") {
      P(2, 6, 1, 1, K); P(3, 5, 2, 1, K); P(12, 6, 1, 1, K); P(10, 5, 2, 1, K); eyes(2); P(7, 12, 2, 1, "#ffffff");
    } else if (ex === "shout") {
      eyes(2); P(5, 11, 6, 3, K); P(6, 12, 4, 1, "#ff4d5e");
    } else if (ex === "sad") {
      P(3, 9, 2, 1, K); P(10, 9, 2, 1, K); P(6, 13, 4, 1, K); P(5, 12, 1, 1, K); P(10, 12, 1, 1, K); P(13, 10, 1, 2, "#6fd3ff");
    } else if (ex === "smile") {
      eyes(2); P(5, 12, 1, 1, K); P(6, 13, 4, 1, K); P(10, 12, 1, 1, K);
    } else if (ex === "think") {
      P(10, 5, 3, 1, K); eyes(2); P(7, 13, 3, 1, K);
    } else {
      if (f % 46 === 0) { P(3, 9, 1, 1, K); P(10, 9, 1, 1, K); } else eyes(2);
      P(6, 13, 4, 1, "#9c5a3c");
    }
  }
  function phones(hx, hy, f, beat) {
    const by = beat ? -1 : 0;
    R(hx - 1, hy - 4 + by, 34, 4, K); R(hx + 1, hy - 3 + by, 30, 2, "#2b2f3a");                         // arco
    R(hx - 6, hy + 8, 9, 16, K); R(hx - 5, hy + 9, 7, 14, "#ff9f1c"); R(hx - 5, hy + 12, 3, 8, "#d97706");
    R(hx + 29, hy + 8, 9, 16, K); R(hx + 30, hy + 9, 7, 14, "#ff9f1c"); R(hx + 34, hy + 12, 3, 8, "#d97706");
  }
  function trader(f) {
    const now = Date.now(), act = S.action && now < S.actionUntil ? S.action : null;
    const mood = S.mood || "atento", list = MOODS[mood] || MOODS.atento;
    const task = act || list[Math.floor(f / 48) % list.length];
    const jitter = mood === "nervoso" && !act ? (f % 3 === 0 ? -1 : f % 3 === 1 ? 1 : 0) : 0;
    const lean = (task === "rapido" || mood === "dedicado") && !act ? 4 : task === "espreguica" ? -3 : 0;
    const beat = task === "musica" && f % 8 < 4;
    let bob = 0;
    if (task === "festa" || act === "win") bob = -Math.abs(Math.round(Math.sin(f / 2.5) * 4));
    else if (task === "danca") bob = (f % 8 < 4 ? -2 : 0);
    else if (beat) bob = 1;
    else bob = f % 24 < 12 ? 0 : 1;
    const sway = task === "danca" ? (f % 16 < 8 ? -3 : 3) : 0;
    const hx = 112 + jitter + sway + (lean > 0 ? 2 : 0), hy = 46 + bob + lean;
    // cadeira gamer
    R(100 + jitter, 54, 60, 74, K); R(102 + jitter, 56, 56, 70, "#2b2d42"); R(108 + jitter, 60, 44, 62, "#3a3d5c"); R(126 + jitter, 60, 8, 62, "#e4572e");
    // tronco: moletom com capuz, camiseta escura por baixo, cordões e bolso canguru
    const bx = hx - 4, by = hy + 30;
    R(bx - 2, by - 4, 44, 8, K); R(bx, by - 3, 40, 6, HOOD_D);                                         // capuz atrás do pescoço
    R(bx, by, 40, 36, K); R(bx + 1, by + 1, 38, 35, HOOD_C); R(bx + 1, by + 1, 3, 35, HOOD_D); R(bx + 36, by + 1, 3, 35, HOOD_D);
    R(bx + 14, by + 1, 12, 7, "#26263a"); R(bx + 16, by + 8, 8, 2, "#26263a");                         // gola em V
    R(bx + 13, by + 4, 1, 12, "#ffffff"); R(bx + 26, by + 4, 1, 12, "#ffffff"); R(bx + 12, by + 16, 3, 2, "#ffffff"); R(bx + 25, by + 16, 3, 2, "#ffffff");
    R(bx + 8, by + 24, 24, 9, HOOD_D); R(bx + 9, by + 25, 22, 1, K);                                  // bolso
    R(hx + 12, hy + 28, 8, 4, "#d9935a");
    // braços e expressão por atividade
    const L = [bx + 3, by + 6], Rr = [bx + 37, by + 6];
    let expr = "neutral", look = 1, mugAt = null, extra = null;
    const type = (fast) => { const a = fast ? (f % 2 ? 0 : 3) : (f % 4 < 2 ? 0 : 2); arm(L[0], L[1], 120, 118 + a); arm(Rr[0], Rr[1], 144, 120 - a); };
    switch (task) {
      case "buy": expr = "shout"; arm(L[0], L[1], bx - 4, by + 30); arm(Rr[0], Rr[1], 212, f % 4 < 2 ? 114 : 116); break;
      case "win": expr = "happy"; arm(L[0], L[1], bx - 10, by - 20 + (f % 6 < 3 ? 0 : 3)); arm(Rr[0], Rr[1], bx + 50, by - 20 + (f % 6 < 3 ? 3 : 0)); break;
      case "loss": expr = "sad"; look = 0; arm(L[0], L[1], hx + 10, hy + 20); arm(Rr[0], Rr[1], bx + 30, by + 32); break;   // mão na testa
      case "festa": expr = "happy"; arm(L[0], L[1], bx - 10, by - 18 + (f % 4 < 2 ? 0 : 4)); arm(Rr[0], Rr[1], bx + 50, by - 18 + (f % 4 < 2 ? 4 : 0)); extra = "confete"; break;
      case "danca": expr = "happy"; arm(L[0], L[1], bx - 8, by + (f % 8 < 4 ? -14 : 4)); arm(Rr[0], Rr[1], bx + 48, by + (f % 8 < 4 ? 4 : -14)); extra = "nota"; break;
      case "musica": expr = "smile"; type(false); extra = "nota"; break;
      case "espreguica": expr = "happy"; arm(L[0], L[1], hx + 2, hy - 2); arm(Rr[0], Rr[1], hx + 30, hy - 2); break;   // mãos atrás da cabeça
      case "cafe": expr = mood === "feliz" ? "smile" : "neutral"; arm(L[0], L[1], 120, 118); arm(Rr[0], Rr[1], hx + 34, hy + 30); mugAt = [hx + 30, hy + 18]; break;
      case "mouse": expr = mood === "dedicado" ? "focus" : "neutral"; look = 2; arm(L[0], L[1], 122, 119); arm(Rr[0], Rr[1], 176 + (f % 12 < 6 ? 0 : 3), 124 - (f % 8 < 4 ? 0 : 1)); break;
      case "pensa": expr = "think"; look = 2; arm(L[0], L[1], 122, 119); arm(Rr[0], Rr[1], hx + 22, hy + 30); extra = "?"; break;   // mão no queixo
      case "olha": expr = "neutral"; look = 2; arm(L[0], L[1], 122, 119); arm(Rr[0], Rr[1], 146, 120); break;
      case "rapido": expr = mood === "nervoso" ? "worried" : "focus"; look = 2; type(true); extra = "risco"; break;
      case "limpa": expr = "worried"; arm(L[0], L[1], 122, 119); arm(Rr[0], Rr[1], hx + 28 - (f % 6 < 3 ? 0 : 6), hy + 6); extra = "suor"; break;   // enxuga a testa
      case "unha": expr = "bite"; look = 0; arm(L[0], L[1], 122, 119); arm(Rr[0], Rr[1], hx + 16 + (f % 2), hy + 26); extra = "suor"; break;   // roendo a unha
      case "cabeca": expr = "panic"; look = 0; arm(L[0], L[1], hx - 2, hy + 4); arm(Rr[0], Rr[1], hx + 34, hy + 4); extra = "suor"; break; // mãos na cabeça
      default: expr = mood === "feliz" ? "smile" : "neutral"; type(false);
    }
    spr("head", hx, hy, 2);
    face(hx, hy, expr, f, look);
    phones(hx, hy, f, beat);
    if (mugAt) { mug(mugAt[0], mugAt[1], f); hand(hx + 34, hy + 30); }
    if (task === "unha") hand(hx + 16 + (f % 2), hy + 26);
    if (task === "pensa") hand(hx + 22, hy + 30);
    // efeitos de cada humor
    if (extra === "suor" || mood === "nervoso") for (let i = 0; i < 2; i++) { const dy = (f * 2 + i * 9) % 16; R(hx - 6 + i * 42, hy + 2 + dy, 2, 3, "#6fd3ff"); }
    if (extra === "risco") for (let i = 0; i < 3; i++) R(bx + 46 + (f * 3 + i * 5) % 10, by + 18 + i * 4, 6, 1, "#ffd23f");          // linhas de velocidade
    if (extra === "nota" && f % 24 < 18) { const ny = hy - 6 - (f % 24); R(hx + 40, ny, 2, 7, "#c084fc"); R(hx + 38, ny + 6, 4, 3, "#c084fc"); R(hx + 42, ny, 3, 2, "#c084fc"); }
    if (extra === "?" && f % 20 < 14) TXT("?", hx + 36, hy - 6, "#ffd23f", 8);
    if (extra === "confete" && f % 2 === 0) S.parts.push({ x: hx + Math.random() * 32, y: hy - 6, vx: (Math.random() - .5) * 3, vy: -2 - Math.random() * 2, c: ["#3ee66b", "#ffd23f", "#c084fc", "#6fd3ff"][f % 4], w: 3, h: 3, g: .15, life: 30 });
    if (mood === "nervoso" && !act && f % 10 < 5) { R(hx + 40, hy - 4, 3, 9, "#ff4d5e"); R(hx + 40, hy + 7, 3, 3, "#ff4d5e"); }      // "!"
    if (mood === "dedicado" && !act) { const t = (f % 30) / 30; R(hx + 6, hy - 8 - t * 6, 2, 2, "rgba(220,230,255,.5)"); R(hx + 24, hy - 6 - t * 6, 2, 2, "rgba(220,230,255,.5)"); }  // "fumacinha" de concentração
  }
  function mug(x, y, f) {
    R(x - 1, y - 1, 12, 14, K); R(x, y, 10, 12, "#e8e8f0"); R(x, y + 3, 10, 3, "#ff4d5e"); R(x + 10, y + 3, 3, 6, K); R(x + 11, y + 4, 1, 4, "#e8e8f0");
    for (let i = 0; i < 2; i++) { const sy = y - 4 - ((f + i * 6) % 10); R(x + 2 + i * 4, sy, 2, 3, "rgba(220,230,255,.6)"); }
  }
  // o BOT assistente: flutua perto da mesa, leva cada compra até o telão e reage às vendas
  function botDraw(f) {
    const now = Date.now(), b = S.bot, age = now - b.t0;
    let x = 66, y = 74 + (f % 20 < 10 ? 0 : 2), eye = "#3df2c4", flip = false;
    if (b.mode === "buy" && age < 3200) {
      const p = age < 1400 ? age / 1400 : age < 2200 ? 1 : 1 - (age - 2200) / 1000;
      x = 66 + p * 150; y = 74 - p * 40 + Math.sin(age / 90) * 2; flip = age > 2200;
      spr("coin", x + 8, y - 14, 1);
      if (b.sym) { const s = b.sym.slice(0, 8); const w = TW(s) + 6; R(x + 14 - w / 2, y - 26, w, 11, K); R(x + 15 - w / 2, y - 25, w - 2, 9, "#ffd23f"); TXT(s, x + 17 - w / 2, y - 24, K, 8); }
    } else if (b.mode === "win" && age < 3000) {
      y = 70 - Math.abs(Math.sin(age / 160)) * 10; flip = Math.floor(age / 200) % 2 === 1; eye = "#ffd23f";
      if (f % 3 === 0) S.parts.push({ x: x + 14, y: y, vx: (Math.random() - .5) * 3, vy: -2 - Math.random() * 2, c: "#ffd23f", w: 3, h: 3, g: .15, life: 30 });
    } else if (b.mode === "loss" && age < 3000) {
      x += (f % 2 ? 2 : -2); eye = "#ff4d5e";
      if (f % 6 < 3) { R(x + 30, y - 6, 3, 8, "#ff4d5e"); R(x + 30, y + 4, 3, 3, "#ff4d5e"); }
    } else if (S.base === "dump") eye = f % 8 < 4 ? "#ff4d5e" : "#ffd23f";
    else if (S.base === "pump") eye = "#3ee66b";
    spr("bot", x, y, 2, flip);
    const blink = f % 50 === 0;
    if (!blink) { R(x + 6 + 2, y + 10, 4, 4, eye); R(x + 16 + 2, y + 10, 4, 4, eye); } else { R(x + 8, y + 12, 4, 1, eye); R(x + 18, y + 12, 4, 1, eye); }
    R(x + 10, y + 16, 8, 1, eye);
    if (f % 10 < 5) R(x + 12, y, 4, 2, "#ffffff");                                       // antena piscando
    // propulsor
    if (f % 4 < 2) { R(x + 10, y + 28, 3, 3, "#ff9f1c"); R(x + 16, y + 28, 3, 3, "#ff9f1c"); }
    const nm = String(C().nome || "").toUpperCase().slice(0, 10);
    if (nm) { const tw = TW(nm) + 6; R(x + 14 - tw / 2, y + 33, tw, 11, K); R(x + 15 - tw / 2, y + 34, tw - 2, 9, "#3df2c4"); TXT(nm, x + 17 - tw / 2, y + 35, K, 8); }
    return { x, y };
  }

  // ------------------------------------------------------------------ balões de fala
  function wrap(t, n) {
    const words = String(t).toUpperCase().split(" "), out = [];
    let cur = "";
    words.forEach((w) => { if ((cur + " " + w).trim().length > n) { if (cur) out.push(cur); cur = w.slice(0, n); } else cur = (cur + " " + w).trim(); });
    if (cur) out.push(cur);
    return out.slice(0, 2);
  }
  // balão de diálogo em pixel: borda preta com cantos cortados, sombra e rabinho apontando para quem fala.
  // left=true: o balão fica à esquerda do ponto (o do trader fica sobre a janela, sem cobrir o quadro e o telão)
  function balloon(text, ax, ay, col, small, left) {
    const lines = wrap(text, small ? 10 : 11), lw = Math.max(...lines.map((l) => l.length)) * 8;
    const w = lw + 10, h = lines.length * 10 + 7;
    let x = Math.round(left ? ax - w + 8 : ax - w / 2), y = Math.round(ay - h - 7);
    x = Math.max(2, Math.min(W - w - 2, x)); y = Math.max(2, y);
    R(x + 2, y + 2, w, h, "rgba(0,0,0,.35)");
    R(x + 1, y, w - 2, h, K); R(x, y + 1, w, h - 2, K); R(x + 1, y + 1, w - 2, h - 2, "#ffffff");
    const tx = Math.max(x + 4, Math.min(x + w - 10, ax - 3));
    R(tx, y + h - 1, 7, 3, K); R(tx + 1, y + h - 1, 5, 2, "#ffffff"); R(tx + 2, y + h + 2, 3, 2, K); R(tx + 3, y + h + 1, 1, 2, "#ffffff"); R(tx + 3, y + h + 4, 1, 2, K);
    lines.forEach((l, i) => TXT(l, x + 5, y + 4 + i * 10, col || K, 8));
  }
  const LINES = {
    euforia: ["VOANDO!!!", "TO THE MOON!", "QUE DIA!", "HODL HODL!"],
    feliz: ["TA SUBINDO", "DEIXA CORRER", "CAFEZIN TOP", "BOA BOA"],
    atento: ["OLHANDO...", "CACANDO GEMS", "HMM...", "BORA?"],
    dedicado: ["FOCO!", "CALMA...", "AJUSTANDO", "SEGURA ESSA"],
    nervoso: ["AI AI AI", "VAI VOLTAR?", "SEGURA!!", "RESPIRA..."],
  };
  const BOTL = { atento: ["BEEP", "SCAN...", "ZZZ"], feliz: ["LUCRO!", "UP!"], euforia: ["MOON!", "WOW!"], dedicado: ["FOCO!", "..."], nervoso: ["ALERTA", "!!!"] };
  function say(text, ms, col) { S.say = { text, until: Date.now() + (ms || 4000), col }; }
  function botSay(text, ms) { S.botSay = { text, until: Date.now() + (ms || 3000) }; }
  function speech(f, bp) {
    const now = Date.now();
    if (C().baloes === false) return;
    if (S.say && now < S.say.until) balloon(S.say.text, 116, 52, S.say.col, false, true);
    else {
      const md = S.mood || "atento", list = LINES[md] || LINES.atento, k = Math.floor(f / 60) % list.length;
      const col = md === "nervoso" ? "#a81f2d" : md === "dedicado" ? "#b45309" : md === "atento" ? K : "#1b8f3f";
      if (S.trendSay && now < S.trendSay.until) balloon(S.trendSay.text, 116, 52, S.trendSay.col, false, true);
      else if (f % 60 < 42) balloon(list[k], 116, 52, col, false, true);
    }
    if (S.botSay && now < S.botSay.until) balloon(S.botSay.text, bp.x + 14, bp.y, "#2f69b5", true);
    else if (f % 120 > 90) { const l = BOTL[S.mood] || BOTL.atento; balloon(l[Math.floor(f / 120) % l.length], bp.x + 14, bp.y, "#2f69b5", true); }
  }

  function desk(f) {
    R(0, 127, W, 2, K); R(0, 128, W, 6, "#a8743f"); R(0, 134, W, 46, "#6e4523");
    for (let x = 0; x < W; x += 16) R(x, 136, 1, 44, "#5a381c");
    R(104, 121, 64, 8, K); R(105, 122, 62, 6, "#3a3f4d"); for (let i = 0; i < 9; i++) R(107 + i * 7, 124, 5, 2, (S.base === "idle" && (i + f) % 4 === 0) ? "#9fb3ff" : "#5d6475");
    R(172, 123, 10, 6, K); R(173, 124, 8, 4, "#3a3f4d");                                   // mouse
    if (S.base !== "pump") mug(80, 112, f);
    if (S.base === "dump") { for (let i = 0; i < 4; i++) R(258 + i, 125 - i * 3, 22, 3, i % 2 ? "#e8e8f0" : "#cfd6e6"); }
    // botão gigante
    const act = S.action && Date.now() < S.actionUntil;
    const buy = act && S.action === "buy";
    const col = act ? (buy ? "#3ee66b" : S.action === "win" ? "#ffd23f" : "#ff4d5e") : "#a81f2d";
    // 0.32.345: botão com o nome escrito nele, em cima da mesa (como o teclado), entre o mouse e o pé do monitor (antes o texto ficava solto na beira da mesa)
    const down = act && f % 4 < 2, lab = buy ? "BUY" : act ? "SELL" : "PUMP";
    R(186, 121, 38, 11, K); R(187, 130, 36, 1, act ? "#5a1018" : "#4a0d14");
    R(187, down ? 123 : 122, 36, 8, col);
    TXT(lab, Math.round(205 - TW(lab) / 2), down ? 123 : 122, act ? K : "#ffe3e6", 8);
  }

  function fx(f) {
    const now = Date.now();
    if (S.base === "pump" && f % 9 === 0) S.parts.push({ x: 120 + Math.random() * 40, y: 50, vx: (Math.random() - .5) * 2, vy: -1.5 - Math.random(), c: "#3ee66b", w: 6, h: 3, g: .12, life: 40 });
    if (S.base === "dump" && f % 6 === 0) S.parts.push({ x: 258 + Math.random() * 20, y: 112, vx: 1 + Math.random() * 2, vy: -2 - Math.random() * 2, c: "#e8e8f0", w: 5, h: 4, g: .15, life: 40 });
    S.parts = S.parts.filter((p) => p.life-- > 0 && p.y < H + 10);
    S.parts.forEach((p) => { p.vy += p.g; p.x += p.vx; p.y += p.vy; R(p.x, p.y, p.w, p.h, p.c); if (p.c === "#3ee66b" && p.w === 6) R(p.x + 2, p.y + 1, 2, 1, "#1b6e33"); });
    if (S.base === "dump") {                                                        // giroflex no teto
      const on = f % 8 < 4;
      R(150, 0, 20, 6, "#5a1414"); R(152, 1, 16, 4, on ? "#ff4d5e" : "#7a1d2b");
      if (on) { g.fillStyle = "rgba(255,77,94,.08)"; g.fillRect(0, 0, W, H); }
    }
    // faixa de status no chão (na BOT LIVE com título, o letreiro da live ocupa esse lugar)
    if (C().botlive && (C().titulo || C().sub)) { R(4, 138, 164, 38, K); R(5, 139, 162, 36, "#140a2e"); return; }
    R(4, 138, 164, 18, K); R(5, 139, 162, 16, "#0b1430");
    if (S.base === "dump") { spr("skull", 8, 142, 1); TXT("CONSERTANDO", 20, 143, f % 6 < 3 ? "#ffd23f" : "#ff7b1c", 8); }
    else if (S.base === "pump") { spr("rocket", 8, 141, 1); TXT("TO THE MOON!", 20, 143, f % 6 < 3 ? "#3ee66b" : "#ffd23f", 8); }
    else {
      const a = (now / 600) % (Math.PI * 2);
      R(8, 140, 12, 12, "#06221b"); g.strokeStyle = "#3df2c4"; g.beginPath(); g.moveTo(14, 146); g.lineTo(14 + Math.cos(a) * 6, 146 + Math.sin(a) * 6); g.stroke();
      TXT("CACANDO GEMS", 24, 143, "#3df2c4", 8);
    }
    // placar do dia na mesa
    const w = S.wallet || {}, n = +w.count || 0;
    R(4, 160, 164, 16, K); R(5, 161, 162, 14, "#0b1430");
    spr("trophy", 8, 163, 1);
    TXT((w.win_rate == null ? "--" : Math.round(w.win_rate * 100) + "%") + " ACERTO", 22, 164, "#e8f0ff", 8);
    TXT(String(n), 160 - TW(String(n)), 164, "#8fa3d1", 8);
  }

  // 0.32.305 (pedido do dono: "na parte consertando, a evolução da carteira: valor que começou, % de lucro e valor em dólar")
  function money(v) {
    if (PRIV()) return "•••";
    const u = +(S.wallet || {}).sol_usd || 0;
    if (u) { const d = v * u; return "$" + (Math.abs(d) >= 1000 ? Math.round(d).toString() : d.toFixed(2)); }
    return Number(v).toFixed(HOOD ? 4 : 3);
  }
  function evo(f) {
    const w = S.wallet || {}, st = w.start_sol, eq = w.equity_sol, pnl = +w.pnl_sol || 0;
    if (!S.ok) return;
    const pctv = w.pnl_pct != null ? +w.pnl_pct : st ? pnl / st * 100 : null;
    const col = pnl > 0 ? "#3ee66b" : pnl < 0 ? "#ff4d5e" : "#ffd23f";
    R(174, 138, 142, 38, K); R(175, 139, 140, 36, "#04121f");
    spr("coin", 178, 142, 1);
    TXT(C().botlive ? "CARTEIRA" : S.real ? "REAL" : "FICTICIA", 192, 143, S.real ? "#ffd23f" : "#3df2c4", 8);
    const l1 = st && !PRIV() ? money(st) + ">" + money(eq) : "CARTEIRA";
    TXT(l1.slice(0, 17), 178, 154, "#e8f0ff", 8);
    const l2 = (pctv == null ? "" : (pctv > 0 ? "+" : "") + pctv.toFixed(1) + "% ") + (PRIV() ? "" : (pnl > 0 ? "+" : pnl < 0 ? "-" : "") + money(Math.abs(pnl)));
    TXT(l2.slice(0, 17), 178, 165, f % 20 < 17 ? col : "#8fa3d1", 8);
  }
  function draw() {
    const f = S.frame++;
    room(f); bigMonitor(f); trader(f); desk(f); const bp = botDraw(f); fx(f); evo(f); speech(f, bp);
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
  function alertBox(title, body, win, ic) {
    $("aT").innerHTML = (ic ? icon(ic, 2) : "") + esc(title); $("aB").innerHTML = body;
    $("alert").classList.toggle("win", !!win); $("alert").classList.add("show");
    const fl = $("flash"); fl.style.background = win ? "#3ee66b" : "#ff4d5e"; fl.classList.remove("go"); void fl.offsetWidth; fl.classList.add("go");
    clearTimeout(alertT); alertT = setTimeout(() => $("alert").classList.remove("show"), 5000);
  }
  // 0.32.314 (pedido do dono): token em que o criador pode travar a venda (Robinhood) aparece em amarelo, com ⚠
  const sym = (x) => (x.risco ? '<span class="risk" title="' + esc(x.risco) + '">⚠ ' : "") + esc(x.symbol || (x.mint || "").slice(0, 6)) + (x.risco ? "</span>" : "");
  const symTxt = (x) => String(x.symbol || (x.mint || "").slice(0, 6)).toUpperCase();
  const pct = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(1) + "%");
  const sol = (v) => (v == null ? "–" : PRIV() ? "•••" : (v > 0 ? "+" : "") + Number(v).toFixed(HOOD ? 5 : 4) + " " + U);
  const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "flat");

  function act(kind) { S.action = kind; S.actionUntil = Date.now() + 2600; }

  function onBuy(p) {
    act("buy"); SFX.buy();
    S.bot = { mode: "buy", t0: Date.now(), sym: symTxt(p) };
    say("COMPREI " + symTxt(p) + "!", 3500, "#1b8f3f"); botSay("NO TELAO!", 2500);
    alertBox("COMPRA!", "PUMP IT! <b>" + sym(p) + "</b><br>" + (PRIV() ? "nova posição" : Number(p.sol_in || 0).toFixed(HOOD ? 4 : 3) + " " + U), true, "coin");
  }
  function onSell(t) {
    const v = t.pnl_sol || 0;
    if (v > 0) {
      act("win"); SFX.win(); S.bot = { mode: "win", t0: Date.now(), sym: symTxt(t) };
      say(pct(t.pnl_pct) + " NO BOLSO!", 4000, "#1b8f3f"); botSay("LUCRO!", 2500);
      alertBox("VENDA COM LUCRO", "<b>" + sym(t) + "</b> " + pct(t.pnl_pct) + "<br>" + sol(v) + " · TO THE MOON", true, "trophy");
    } else {
      act("loss"); SFX.loss(); S.bot = { mode: "loss", t0: Date.now(), sym: symTxt(t) };
      say("STOP. PROXIMA!", 4000, "#a81f2d"); botSay("R.I.P.", 2500);
      alertBox("R.I.P. STOP LOSS", "<b>" + sym(t) + "</b> " + pct(t.pnl_pct) + "<br>" + sol(v) + " · vaga na lanchonete aberta", false, "skull");
    }
  }

  // ------------------------------------------------------------------ dados
  const pid = (p) => p.id || (p.mint + "|" + p.opened_at);
  const tid = (t) => t.id || ((t.pos_id || t.mint) + "|" + t.closed_at);
  const tms = (s) => { const v = Date.parse(s || ""); return isNaN(v) ? 0 : v; };

  // LOG DO ROBÔ: as decisões da cópia (copiou, não copiou e por quê, REAL), como num terminal
  function logKind(a) {
    a = String(a || "").toLowerCase();
    if (a.indexOf("falhou") >= 0) return "bad";
    if (a.indexOf("real") >= 0) return "real";
    if (a.indexOf("não") >= 0 || a.indexOf("nao") >= 0 || a.indexOf("barr") >= 0) return "no";
    if (a.indexOf("aguard") >= 0) return "wait";
    if (a.indexOf("vend") >= 0 || a.indexOf("fech") >= 0 || a.indexOf("saiu") >= 0) return "sell";
    return "ok";
  }
  // 0.32.341 (pedido do dono): no BOT LIVE cada linha do log mostra horário (UTC), nome do token, rede, a decisão e o motivo em texto
  // curto, sem cortar; linhas iguais seguidas viram uma só com "×N".
  const MOTIVOS = [
    [/pool deste trade não é da Uniswap V4 pago em ETH/i, "pool fora da Uniswap V4 em ETH"],
    [/já tem (a )?posição/i, "já tem posição neste token"],
    [/sem saldo|saldo insuficiente/i, "sem saldo na carteira do BOT"],
    [/máximo de .*abertas|limite de .*abertas/i, "limite de posições abertas"],
    [/venda .*recus|honeypot|não deixa vender/i, "o pool não deixa vender (golpe)"],
    [/atrasad|velho|antigo/i, "trade antigo, chegou tarde"],
  ];
  const motivo = (r) => {
    r = String(r || "");
    for (const [re, t] of MOTIVOS) if (re.test(r)) return t;
    return r.replace(/^token barrado:\s*/i, "").replace(/\s*\(.*$/, "");
  };
  // 0.32.342 (pedido do dono): uma linha por decisão — horário, token e o código (NC = não copiou, COMPRA, VENDA); o motivo fica na
  // dica do mouse. Repetidas seguidas viram uma com ×N.
  function logCode(a) {
    const k = logKind(a);
    return k === "sell" ? "VENDA" : k === "ok" ? "COMPRA" : "NC";
  }
  function renderBotLog(L, box) {
    const G = [];
    L.forEach((x) => {
      const last = G[G.length - 1], c = logCode(x.a);
      if (last && last.c === c && last.s === x.s) last.n++;
      else G.push(Object.assign({}, x, { c, n: 1 }));
    });
    const one = box.classList.contains("logline");                 // 0.32.343: faixa de uma linha só (a decisão mais nova)
    box.innerHTML = G.slice(0, one ? 1 : 40).map((x, i) => {
      const k = x.c === "NC" ? "no" : x.c === "VENDA" ? "sell" : "ok";
      return '<div class="ll one ' + k + (i === 0 && x.fresh ? " new" : "") + '" title="' + esc((x.a || "") + (x.r ? " · " + motivo(x.r) : "")) + '">' +
        '<span class="lt">' + esc(x.h) + '</span><span class="tk">' + esc(x.s || "?") + '</span><b>' + x.c + "</b>" +
        (x.n > 1 ? '<span class="nx">×' + x.n + "</span>" : "") + (one && x.r ? '<span class="lmot">· ' + esc(motivo(x.r)) + "</span>" : "") + "</div>";
    }).join("") + '<div class="cur">&gt; _</div>';
  }
  function renderLog() {
    const L = S.log.slice(0, 40), box = $("log");
    $("logN").textContent = L.length ? "(" + L.length + ")" : "";
    if (!L.length) { box.innerHTML = '<div class="empty">sem decisões recentes</div>'; return; }
    if (C().botlive) { renderBotLog(L, box); return; }
    box.innerHTML = L.map((x, i) => {
      const k = logKind(x.a);
      const ic = k === "ok" ? icon("up", 1) : k === "sell" ? icon("down", 1) : "";
      return '<div class="ll ' + k + (i === 0 && x.fresh ? " new" : "") + '" title="' + esc(x.r || "") + '"><span class="lt">' + esc(x.h) + "</span>" + ic +
        '<b>' + esc(String(x.a || "").toUpperCase()) + "</b> " + esc(x.s || "") + (x.r ? ' <span class="lr">· ' + esc(String(x.r).slice(0, 90)) + "</span>" : "") + "</div>";
    }).join("") + '<div class="cur">&gt; _</div>';
  }
  function setLog(items) {
    const keys = items.map((x) => x.k);
    const fresh = S.seenLog && keys.length && !S.seenLog.has(keys[0]);
    S.seenLog = new Set(keys);
    S.log = items.map((x, i) => Object.assign(x, { fresh: i === 0 && fresh }));
    renderLog();
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
    // humor do personagem: nível do resultado aberto + tendência dos últimos ~20 s (melhorando ou piorando)
    const op = S.openPct;
    S.mood = op == null ? (S.base === "pump" ? "feliz" : S.base === "dump" ? "dedicado" : "atento")
      : op >= 10 ? "euforia" : op >= 2 ? "feliz" : op > -3 ? "atento" : op > -10 ? "dedicado" : "nervoso";
    const tnow = Date.now();
    S.pctHist = (S.pctHist || []).filter((x) => tnow - x[0] < 25000);
    if (op != null) S.pctHist.push([tnow, op]);
    const old = S.pctHist.length > 3 ? S.pctHist[0][1] : null;
    if (old != null && op != null && (!S.trendSay || tnow > S.trendSay.until + 15000)) {
      if (op - old >= 3) S.trendSay = { text: "MELHORANDO!", col: "#1b8f3f", until: tnow + 3000 };
      else if (op - old <= -3) S.trendSay = { text: "PIOROU... ATENCAO", col: "#a81f2d", until: tnow + 3000 };
    }
    const hud = $("hud");
    const MH = { euforia: "EUFÓRICO", feliz: "FELIZ", atento: "ATENTO", dedicado: "DEDICADO", nervoso: "NERVOSO" };
    $("mood").textContent = "HUMOR: " + (MH[S.mood] || "ATENTO"); $("mood").className = "hud pf mood m-" + (S.mood || "atento");
    if (S.openPct == null) hud.innerHTML = '<b class="flat">PROCURANDO GEMS…</b>';
    else if (S.openPct > 0) hud.innerHTML = 'PUMPING NOW! <b class="up">' + pct(S.openPct) + "</b>";
    else hud.innerHTML = 'DUMPING… <b class="down">' + pct(S.openPct) + "</b>";
    hud.className = "hud pf " + (S.openPct == null ? "flat" : S.openPct > 0 ? "up" : "down");
    const res = +w.pnl_sol || 0;
    $("stats").innerHTML = [
      ["Carteira", C().botlive ? "do BOT" : (S.real ? "REAL" : "FICTÍCIA")],
      ["Resultado", '<span class="' + cls(res) + '">' + sol(res) + "</span>"],
      ["Acerto", w.win_rate == null ? "–" : Math.round(w.win_rate * 100) + "%"],
      ["Trades", String(w.count || 0)], ["Abertas", String(P.length)],
    ].map(([k, v]) => '<div class="st"><small>' + k + "</small> " + v + "</div>").join("");
    $("posN").textContent = P.length ? "(" + P.length + ")" : "";
    // 0.32.269 (pedido do dono): lista compacta — moeda, valor de entrada e valor atual em dólares e o %
    const box = $("pos"), usd = +w.sol_usd || 0;
    const $v = (solv) => (PRIV() ? "•••" : usd ? "$" + (solv * usd).toFixed(solv * usd >= 100 ? 0 : 2) : Number(solv).toFixed(HOOD ? 4 : 3) + " " + U);
    if (!P.length) { box.innerHTML = '<div class="empty">nenhuma posição aberta agora</div>'; }
    else {
      const sorted = P.slice().sort((a, b) => (b.pnl_now_pct || 0) - (a.pnl_now_pct || 0));
      // 0.32.300 (pedido do dono): coluna Hora com o horário de entrada
      const hr = (p) => { const t = tms(p.opened_at); return t ? hms(t, { hour: "2-digit", minute: "2-digit" }) : "–"; };
      box.innerHTML = '<div class="ph"><span>Moeda</span><span>Hora</span><span>Entrada</span><span>Agora</span><span>%</span></div>' +
        sorted.map((p) => { const ins = +p.sol_in || 0, nowv = ins + (+p.pnl_now_sol || 0);
          return '<div class="pr"><span>' + sym(p) + '</span><span class="hr" title="entrou às ' + esc(new Date(tms(p.opened_at) || 0).toLocaleString("pt-BR")) + '">' + hr(p) + "</span><span>" + $v(ins) + '</span><span class="' + cls(p.pnl_now_sol) + '">' + $v(nowv) +
            '</span><span class="pc ' + cls(p.pnl_now_pct) + '">' + pct(p.pnl_now_pct) + "</span></div>"; }).join("");
    }
    // 0.32.305 (pedido do dono): Histórico das posições fechadas embaixo das abertas
    const hb = $("his"), HS = S.trades.slice(0, 40);
    $("hisN").textContent = S.trades.length ? "(" + S.trades.length + ")" : "";
    const hm = (s) => { const t = tms(s); return t ? hms(t, { hour: "2-digit", minute: "2-digit" }) : "–"; };
    hb.innerHTML = !HS.length ? '<div class="empty">nenhuma posição fechada ainda</div>' :
      '<div class="ph"><span>Moeda</span><span>Saiu</span><span>Entrada</span><span>Saída</span><span>%</span></div>' +
      HS.map((t) => { const ins = +t.sol_in || 0, out = ins + (+t.pnl_sol || 0);
        return '<div class="pr" title="' + esc((t.motivo || "") + " · entrou " + hm(t.opened_at) + ", saiu " + hm(t.closed_at)) + '"><span>' + sym(t) + '</span><span class="hr">' + hm(t.closed_at) +
          "</span><span>" + (ins ? $v(ins) : "–") + '</span><span class="' + cls(t.pnl_sol) + '">' + (ins ? $v(out) : sol(t.pnl_sol)) + '</span><span class="pc ' + cls(t.pnl_pct) + '">' + pct(t.pnl_pct) + "</span></div>"; }).join("");
    const items = S.trades.slice(0, 8).map((t) => ({ t: tms(t.closed_at), h: '<span class="' + cls(t.pnl_sol) + '">' + icon((t.pnl_sol || 0) > 0 ? "trophy" : "skull", 1) + "SELL " + sym(t) + " " + pct(t.pnl_pct) + " (" + sol(t.pnl_sol) + ")</span>" }))
      .concat(P.slice(0, 8).map((p) => ({ t: tms(p.opened_at), h: '<span class="up">' + icon("coin", 1) + "BUY " + sym(p) + (PRIV() ? "" : " " + Number(p.sol_in || 0).toFixed(HOOD ? 4 : 3) + " " + U) + "</span>" })))
      .sort((a, b) => b.t - a.t).slice(0, 12);
    $("run").innerHTML = items.length ? items.map((x) => x.h).join("") : '<span class="flat">HOLD! HODL! HODL!</span>';
  }

  // Robinhood: posições e trades da cópia em ETH no formato que a cena já usa
  const iso = (t) => (t ? new Date(t * 1000).toISOString() : "");
  async function hoodData(real) {
    const p = await BB._api(C().api ? C().api : "/api/hood/painel" + (real ? "?real=1" : ""));
    if (p.error) return p;
    if (p.ligado === false) return { error: p.motivo || "leitura da Robinhood desligada no servidor" };
    const sy = (x) => x.simbolo || x.nome || (x.token || "").slice(0, 8);
    const rk = p.riscos || {}, nm = p.nomes || {};
    const pos = (p.posicoes || []).map((x) => ({ id: x.id, real, mint: x.token, symbol: sy(x), risco: rk[x.token], sol_in: x.eth_in, pnl_now_sol: x.pnl_eth,
      pnl_now_pct: x.pnl_pct, opened_at: iso(x.open_t) }));
    const tr = (p.trades || []).map((x) => ({ id: x.id, real, mint: x.token, symbol: sy(x), risco: rk[x.token], pnl_sol: x.pnl_eth, pnl_pct: x.pnl_pct, closed_at: iso(x.close_t),
      opened_at: iso(x.open_t), sol_in: x.eth_in, motivo: x.motivo }));
    const w = p.carteira || {};
    let acc = 0;
    const curve = tr.slice().sort((a, b) => tms(a.closed_at) - tms(b.closed_at)).map((t) => { acc += +t.pnl_sol || 0; return [t.closed_at, acc]; });
    const wal = { pnl_sol: w.resultado, win_rate: w.acerto == null ? null : w.acerto / 100, count: w.fechadas, sol_usd: p.eth_usd,
      start_sol: w.inicial == null ? null : w.inicial, equity_sol: w.total == null ? null : w.total, pnl_pct: w.resultado_pct };
    const nmOf = (tk) => { const v = nm[tk]; return (v && (v.simbolo || v.nome || v.symbol)) || (typeof v === "string" ? v : tk ? tk.slice(0, 6) + "…" + tk.slice(-4) : ""); };
    const log = (p.eventos || []).map((e) => ({ k: e.t + "|" + e.token + "|" + e.acao, h: e.t ? hms(e.t * 1000) : "", a: e.acao, s: nmOf(e.token), r: e.motivo }));
    // 0.32.339: BOT LIVE recém-ligado ainda sem decisões — mostra que está trabalhando e quantos traders acompanha
    if (C().botlive && !log.length) log.push({ k: "bl-status", h: hms(Date.now()), a: (p.cfg_sim && p.cfg_sim.on === false) ? "BOT parado" : "BOT operando",
      s: "", r: "copiando os " + (p.seguindo || 0) + " top traders da Robinhood · compra quando um deles comprar" });
    S.seguindo = p.seguindo || 0;
    return { positions: pos, trades: tr, wallet: wal, real_wallet: wal, curve, real_curve: curve, _log: log };
  }

  async function load() {
    try {
      const js = HOOD ? await hoodData(S.real) : await BB._api("/api/pump?ev=999999999999");
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
      const log = HOOD ? (js._log || []) : (js.feed || []).filter((x) => !real || /real/i.test(String(x.action || "")) || x.sim_id != null)
        .map((x) => ({ k: (x.at || "") + "|" + (x.mint || "") + "|" + (x.action || ""), h: x.at ? new Date(tms(x.at)).toLocaleTimeString("pt-BR") : "",
          a: x.action, s: x.symbol || (x.mint || "").slice(0, 6), r: x.reason }));
      setLog(log);
      $("sub").textContent = (C().botlive ? "carteira do BOT · estratégia da Robinhood" : "dados da sua conta · carteira " + (real ? "REAL" : "FICTÍCIA")) + " · atualizado " + hms(Date.now()) + (C().botlive ? " UTC" : "");
      $("err").hidden = true;
      render();
    } catch (e) {
      $("err").textContent = "Não consegui ler os dados: " + (e.message || e) + " (tentando de novo)"; $("err").hidden = false;
    }
  }

  // ------------------------------------------------------------------ controles
  function setMode(real) {
    S.real = real; S.seenPos = null; S.seenTr = null; S.seenLog = null; S.hist = {}; S.ok = false;
    try { localStorage.setItem(MKEY, real ? "real" : "sim"); } catch (e) { /* */ }
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
  window.SALA = { state: S, setSound: (v) => { S.sound = !!v; $("snd").textContent = "SOM: " + (S.sound ? "ON" : "OFF"); $("snd").classList.toggle("on", S.sound); },
    setMode, rerender: () => { if (S.ok) render(); renderLog(); } };
  // ícones nos títulos das janelas do painel
  document.querySelectorAll("[data-ico]").forEach((el) => { el.insertAdjacentHTML("afterbegin", icon(el.getAttribute("data-ico"), 2)); });

  (async function start() {
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão */ }
    if (!s) { location.href = "/"; return; }
    $("mSim").classList.toggle("on", !S.real); $("mReal").classList.toggle("on", S.real);
    if (HOOD && !C().botlive) {
      document.title = "Sala ao vivo — Robinhood";
      document.querySelector(".brand").textContent = "ROBINHOOD · SALA";
      const pn = document.querySelector('.ctl a[href="/app"]'); if (pn) pn.href = "/hood";
    }
    await load();
    setInterval(load, 2000);                         // 0.32.268: % das posições ao vivo
  })();
})();
