// 0.32.336 (pedido do dono, 13/11): BOT LIVE — roda DEPOIS de sala.js na SALA LIVE (/botlive/sala). Aplica a configuração da
// live (feita em /botlive): título na tela, painel, música lo-fi e efeitos. 0.32.337: a configuração saiu desta tela. A música é gerada aqui mesmo com o WebAudio (acordes de piano elétrico, baixo, bateria com swing e chiado de
// vinil), sem arquivo de fora e sem direitos autorais; quando o humor do BOT fica tenso (dedicado/nervoso) a harmonia vira menor.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const cfg = window.SALA_CFG, DEF = window.BOTLIVE_DEF, KEY = window.BOTLIVE_KEY;
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) { /* sem armazenamento */ } };

  // ------------------------------------------------------------------ música lo-fi
  const Lofi = (function () {
    let ac = null, master = null, timer = null, next = 0, step = 0, on = false, crackleSrc = null;
    const BPM = 74, E8 = 60 / BPM / 2;
    const PROG = {
      calma: [[50, 57, 60, 64], [55, 59, 62, 65], [48, 55, 59, 64], [45, 52, 55, 60]],   // Dm7 · G7 · Cmaj7 · Am7
      tensa: [[45, 52, 55, 60], [41, 48, 52, 57], [50, 57, 60, 65], [52, 56, 59, 62]],   // Am7 · Fmaj7 · Dm7 · E7
    };
    const PENTA = [69, 72, 74, 76, 79, 81];
    const hz = (m) => 440 * Math.pow(2, (m - 69) / 12);
    let noiseBuf = null;
    function noise() {
      if (noiseBuf) return noiseBuf;
      noiseBuf = ac.createBuffer(1, ac.sampleRate, ac.sampleRate);
      const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      return noiseBuf;
    }
    function env(g, t, a, peak, dec) { g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + a); g.gain.exponentialRampToValueAtTime(0.0001, t + a + dec); }
    function keys(notes, t, dur, lvl) {
      notes.forEach((m, i) => {
        const g = ac.createGain(); g.connect(master);
        env(g, t + i * 0.012, 0.03, lvl, dur);
        const o1 = ac.createOscillator(), o2 = ac.createOscillator(), g2 = ac.createGain();
        o1.type = "sine"; o1.frequency.value = hz(m); o1.detune.value = (Math.random() - .5) * 8;
        o2.type = "triangle"; o2.frequency.value = hz(m) * 2; g2.gain.value = 0.18;
        o1.connect(g); o2.connect(g2); g2.connect(g);
        o1.start(t); o2.start(t); o1.stop(t + dur + .2); o2.stop(t + dur + .2);
      });
    }
    function bass(m, t, dur) {
      const g = ac.createGain(), o = ac.createOscillator(); o.type = "sine"; o.frequency.value = hz(m - 24);
      env(g, t, 0.02, 0.32, dur); o.connect(g); g.connect(master); o.start(t); o.stop(t + dur + .1);
    }
    function kick(t) {
      const g = ac.createGain(), o = ac.createOscillator();
      o.frequency.setValueAtTime(120, t); o.frequency.exponentialRampToValueAtTime(42, t + .12);
      env(g, t, 0.004, 0.55, 0.28); o.connect(g); g.connect(master); o.start(t); o.stop(t + .4);
    }
    function snare(t) {
      const s = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
      s.buffer = noise(); f.type = "bandpass"; f.frequency.value = 1700; f.Q.value = .8;
      env(g, t, 0.003, 0.22, 0.16); s.connect(f); f.connect(g); g.connect(master); s.start(t, Math.random() * .5, .3);
    }
    function hat(t, lvl) {
      const s = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
      s.buffer = noise(); f.type = "highpass"; f.frequency.value = 7000;
      env(g, t, 0.002, lvl, 0.04); s.connect(f); f.connect(g); g.connect(master); s.start(t, Math.random() * .5, .1);
    }
    function crackle() {
      const len = ac.sampleRate * 3, b = ac.createBuffer(1, len, ac.sampleRate), d = b.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = (Math.random() < 0.0008 ? (Math.random() * 2 - 1) * .9 : 0) + (Math.random() * 2 - 1) * .012;
      const s = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
      s.buffer = b; s.loop = true; f.type = "lowpass"; f.frequency.value = 4500; g.gain.value = .35;
      s.connect(f); f.connect(g); g.connect(master); s.start(); return s;
    }
    function mood() { const m = window.SALA && window.SALA.state && window.SALA.state.mood; return m === "nervoso" || m === "dedicado" ? "tensa" : "calma"; }
    function play(st, t) {
      const b8 = st % 8, bar = Math.floor(st / 8) % 4, chord = PROG[mood()][bar];
      if (b8 === 0) { keys(chord, t, E8 * 7, .07); bass(chord[0], t, E8 * 3); kick(t); }
      if (b8 === 3 && Math.random() < .5) kick(t);
      if (b8 === 5) { bass(chord[0] + (Math.random() < .5 ? 7 : 0), t, E8 * 2); kick(t); }
      if (b8 === 2 || b8 === 6) snare(t);
      if (Math.random() < .9) hat(t, b8 % 2 ? .025 : .045);
      if ((b8 === 3 || b8 === 7) && Math.random() < .35) keys([PENTA[Math.floor(Math.random() * PENTA.length)] - (mood() === "tensa" ? 1 : 0)], t, E8 * 2, .035);
    }
    function sched() {
      while (next < ac.currentTime + 0.25) { play(step, next); next += E8 * (step % 2 ? 0.86 : 1.14); step++; }
    }
    return {
      start() {
        if (on) return;
        try {
          ac = ac || new (window.AudioContext || window.webkitAudioContext)();
          if (!master) {
            const f = ac.createBiquadFilter(); f.type = "lowpass"; f.frequency.value = 2200; f.Q.value = .4;
            master = ac.createGain(); master.gain.value = (cfg.vol / 100) * .7; master.connect(f); f.connect(ac.destination);
          }
          ac.resume();
          crackleSrc = crackle(); next = ac.currentTime + .1; step = 0; on = true;
          timer = setInterval(sched, 25);
        } catch (e) { on = false; }
      },
      stop() { if (!on) return; on = false; clearInterval(timer); try { crackleSrc && crackleSrc.stop(); } catch (e) { /* */ } },
      vol(v) { if (master) master.gain.value = (v / 100) * .7; },
      blocked() { return !!ac && ac.state === "suspended"; },
      resume() { if (ac) ac.resume(); },
      isOn() { return on; },
      mood,
    };
  })();

  // ------------------------------------------------------------------ 0.32.351: músicas lofi de verdade, 4 playlists por horário
  // Horário do computador que transmite: 0–6 madrugada (dormir), 6–12 manhã (café), 12–18 trabalho (foco), 18–24 noite (relax).
  // As faixas vêm de /api/botlive/musicas (enviadas em /botlive). Sem nenhuma faixa, toca a música gerada (Lofi, acima).
  const Radio = (function () {
    let list = [], pers = {}, a = null, on = false, cur = null, blocked = false, loadedT = 0;
    const last = {};
    const period = () => { const h = new Date().getHours(); return h < 6 ? "madrugada" : h < 12 ? "manha" : h < 18 ? "trabalho" : "noite"; };
    async function load() {
      try {
        // 0.32.351: no OBS a lista vem com o código do link; logado, pela rota do admin. Cada faixa traz um link assinado (6 h).
        const j = cfg.obs ? await (await fetch("/api/botlive/obs/musicas?k=" + encodeURIComponent(cfg.k), { cache: "no-store" })).json()
          : await BB._api("/api/botlive/musicas");
        if (j && !j.error) { list = j.faixas || []; pers = j.periodos || {}; loadedT = Date.now(); }
      } catch (e) { /* sem lista agora: tenta de novo depois */ }
    }
    function pick() {
      const p = period();
      let pool = list.filter((x) => x.periodo === p);
      if (!pool.length) pool = list.slice();
      if (!pool.length) return null;
      const not = pool.filter((x) => x.id !== last[p]), from = not.length ? not : pool;
      const it = from[Math.floor(Math.random() * from.length)];
      last[p] = it.id;
      return it;
    }
    const vol = () => Math.max(0, Math.min(1, (cfg.vol == null ? 45 : cfg.vol) / 100));
    function fade(el, to, ms, done) {
      const from = el.volume, t0 = performance.now();
      const step = (now) => { const k = Math.min(1, (now - t0) / ms); el.volume = from + (to - from) * k; if (k < 1) requestAnimationFrame(step); else if (done) done(); };
      requestAnimationFrame(step);
    }
    function next() {
      if (!on) return;
      const it = pick();
      if (!it) { Radio.stop(); Lofi.start(); return; }
      const old = a;
      a = new Audio(it.src || ("/botlive/musica/" + encodeURIComponent(it.id)));
      a.preload = "auto"; a.volume = 0; cur = it;
      a.addEventListener("ended", next);
      a.addEventListener("error", () => setTimeout(async () => { await load(); next(); }, 3000));   // link vencido: relê a lista
      a.play().then(() => { blocked = false; fade(a, vol(), 2500); }).catch(() => { blocked = true; });
      if (old) fade(old, 0, 2500, () => { try { old.pause(); } catch (e) { /* */ } });
    }
    return {
      async start() {
        if (on) return true;
        if (!list.length || Date.now() - loadedT > 600000) await load();
        if (!list.length) return false;
        on = true; Lofi.stop(); next(); return true;
      },
      stop() { on = false; if (a) { const o = a; a = null; fade(o, 0, 800, () => { try { o.pause(); } catch (e) { /* */ } }); } cur = null; },
      vol() { if (a) a.volume = vol(); },
      resume() { if (on && a && blocked) a.play().then(() => { blocked = false; fade(a, vol(), 1500); }).catch(() => {}); },
      blocked: () => on && blocked,
      isOn: () => on,
      label() { const p = pers[period()] || {}; return (p.en || "LO-FI") + (cur ? " · " + String(cur.titulo || "").toUpperCase().slice(0, 28) : ""); },
      // troca de período: a faixa atual dá lugar à da nova playlist (só se faltar mais de 30 s para acabar)
      checkPeriod() { if (on && cur && cur.periodo !== period() && list.some((x) => x.periodo === period()) && a && a.duration && a.duration - a.currentTime > 30) next(); },
      reload: load,
    };
  })();

  // ------------------------------------------------------------------ aplicar a configuração
  const TG = { cMus: "musica", cSfx: "sfx", cBal: "baloes", cPriv: "privado", cPan: "painel", cClean: "limpa" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function obsLink() {
    const o = Object.assign({}, cfg); delete o.botlive; delete o.mkey;
    return location.origin + "/botlive/sala?cfg=" + encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(o)))));
  }
  function apply() {
    $("ovt").innerHTML = (cfg.titulo ? "<b>" + esc(cfg.titulo) + "</b>" : "") + (cfg.sub ? "<small>" + esc(cfg.sub) + "</small>" : "");
    document.body.classList.toggle("nopanel", !cfg.painel);
    document.body.classList.toggle("clean", !!cfg.limpa);
    Object.entries(TG).forEach(([id, k]) => { const b = $(id); if (b) { b.classList.toggle("on", !!cfg[k]); b.textContent = cfg[k] ? "ON" : "OFF"; } });
    $("mus").textContent = "LO-FI: " + (cfg.musica ? "ON" : "OFF"); $("mus").classList.toggle("on", !!cfg.musica);
    $("lofiTag").hidden = !cfg.musica;
    if (cfg.musica) { Radio.start().then((ok) => { if (!ok && cfg.musica) Lofi.start(); }); } else { Radio.stop(); Lofi.stop(); }
    Lofi.vol(cfg.vol); Radio.vol();
    if (window.SALA) { window.SALA.setSound(cfg.sfx); window.SALA.rerender(); }
    if ($("cLink")) $("cLink").textContent = obsLink();
    $("pnLink").href = "/entrar"; $("pnLink").textContent = "PROJECTS";
  }
  const set = (k, v) => { cfg[k] = v; save(); apply(); };

  // a carteira escolhida nos botões FICTÍCIA/REAL fica salva na configuração da live
  ["mSim", "mReal"].forEach((id) => $(id).addEventListener("click", () => { cfg.carteira = id === "mReal" ? "real" : "sim"; save(); }));
  $("mus").addEventListener("click", () => set("musica", !cfg.musica));
  $("snd").addEventListener("click", () => { cfg.sfx = !!(window.SALA && window.SALA.state.sound); save(); apply(); });
  // o navegador só deixa tocar som depois de um clique: o primeiro clique na página destrava a música
  document.addEventListener("pointerdown", () => { if (cfg.musica) { Lofi.resume(); Radio.resume(); } }, { passive: true });
  setInterval(() => {
    if (Radio.isOn()) { $("lofiMood").textContent = Radio.blocked() ? "CLICK TO PLAY" : Radio.label(); return; }
    $("lofiMood").textContent = Lofi.blocked() ? "CLICK TO PLAY" : Lofi.mood() === "tensa" ? "TENSE" : "CHILL";
  }, 1500);
  // 0.32.351: a cada 10 min confere se a lista de músicas mudou e se o período do dia trocou
  setInterval(async () => { if (!cfg.musica) return; await Radio.reload(); if (!Radio.isOn()) { if (await Radio.start()) return; } else Radio.checkPeriod(); }, 600000);

  // 0.32.344: o painel da direita acompanha a altura da cena (a cena é 16:9 e fica centralizada)
  const stage = document.querySelector(".stage");
  if (stage && window.ResizeObserver) {
    new ResizeObserver(() => { document.documentElement.style.setProperty("--sth", Math.round(stage.getBoundingClientRect().height) + "px"); }).observe(stage);
    // 0.32.345: a coluna da cena tem a largura da própria cena (16:9) e Posições/Histórico ocupam o resto, sem faixa vazia.
    // Se a janela for mais alta que a cena (cena limitada pela largura), a linha encolhe para a altura da cena e o log
    // e os últimos trades ficam logo abaixo dela, sem espaço vazio no meio. Recalculado só ao mudar o tamanho da janela.
    const wrap = stage.parentElement, grid = wrap && wrap.parentElement;
    const VERT = document.documentElement.classList.contains("vert");            // 0.32.347: link Mobile vertical
    const DESK = window.matchMedia("(min-width:981px),(orientation:landscape) and (min-width:701px)");
    const fit = () => {
      if (!wrap || !grid) return;
      grid.style.flex = ""; grid.style.gridTemplateRows = ""; grid.classList.remove("fit");
      if (VERT) { document.documentElement.style.setProperty("--vs", (innerWidth / 540).toFixed(4)); return; }
      if (!DESK.matches || document.body.classList.contains("nopanel")) return;
      const cs = getComputedStyle(grid), rowH = wrap.getBoundingClientRect().height;
      const sideMin = Math.min(340, Math.max(230, innerWidth * 0.22)), gap = parseFloat(cs.columnGap) || 12;
      const wMax = grid.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - gap - sideMin;
      const h = Math.floor(Math.min(rowH, (wMax - 6) * 9 / 16 + 6));
      if (h <= 0) return;
      document.documentElement.style.setProperty("--gh", h + "px"); grid.classList.add("fit");
      if (h < rowH - 2) { grid.style.flex = "0 0 auto"; grid.style.gridTemplateRows = h + "px"; }
    };
    let ft = 0; const refit = () => { clearTimeout(ft); ft = setTimeout(fit, 60); };
    addEventListener("resize", refit); if (document.fonts && document.fonts.ready) document.fonts.ready.then(refit);
    refit(); setTimeout(refit, 800);
  }
  apply();
})();
