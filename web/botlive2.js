// 0.32.336 (pedido do dono, 13/11): BOT LIVE — roda DEPOIS de sala.js. Liga a gaveta de configuração, o título na tela, o link do
// OBS e a música lo-fi. A música é gerada aqui mesmo com o WebAudio (acordes de piano elétrico, baixo, bateria com swing e chiado de
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

  // ------------------------------------------------------------------ aplicar a configuração
  const TG = { cMus: "musica", cSfx: "sfx", cBal: "baloes", cPriv: "privado", cPan: "painel", cClean: "limpa" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function obsLink() {
    const o = Object.assign({}, cfg); delete o.botlive; delete o.mkey;
    return location.origin + "/botlive?cfg=" + encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(o)))));
  }
  function apply() {
    $("ovt").innerHTML = (cfg.titulo ? "<b>" + esc(cfg.titulo) + "</b>" : "") + (cfg.sub ? "<small>" + esc(cfg.sub) + "</small>" : "");
    document.body.classList.toggle("nopanel", !cfg.painel);
    document.body.classList.toggle("clean", !!cfg.limpa);
    Object.entries(TG).forEach(([id, k]) => { const b = $(id); b.classList.toggle("on", !!cfg[k]); b.textContent = cfg[k] ? "ON" : "OFF"; });
    $("mus").textContent = "LO-FI: " + (cfg.musica ? "ON" : "OFF"); $("mus").classList.toggle("on", !!cfg.musica);
    $("lofiTag").hidden = !cfg.musica;
    if (cfg.musica) Lofi.start(); else Lofi.stop();
    Lofi.vol(cfg.vol);
    if (window.SALA) { window.SALA.setSound(cfg.sfx); window.SALA.rerender(); }
    $("cLink").textContent = obsLink();
    $("pnLink").href = cfg.rede === "hood" ? "/hood" : "/app";
  }
  function fill() {
    $("cRede").value = cfg.rede; $("cCart").value = cfg.carteira; $("cNome").value = cfg.nome || ""; $("cTit").value = cfg.titulo || "";
    $("cSub").value = cfg.sub || ""; $("cCeu").value = cfg.ceu || ""; $("cVol").value = cfg.vol;
  }
  const set = (k, v) => { cfg[k] = v; save(); apply(); };

  $("cfgOpen").addEventListener("click", () => $("drawer").classList.add("open"));
  $("cfgClose").addEventListener("click", () => $("drawer").classList.remove("open"));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("drawer").classList.remove("open"); });
  $("cRede").addEventListener("change", (e) => { cfg.rede = e.target.value; save(); location.href = "/botlive"; });   // a rede muda a fonte dos dados: recarrega
  $("cCart").addEventListener("change", (e) => { cfg.carteira = e.target.value; save(); if (window.SALA) window.SALA.setMode(cfg.carteira === "real"); apply(); });
  ["mSim", "mReal"].forEach((id) => $(id).addEventListener("click", () => { cfg.carteira = id === "mReal" ? "real" : "sim"; save(); fill(); apply(); }));
  [["cNome", "nome"], ["cTit", "titulo"], ["cSub", "sub"]].forEach(([id, k]) => $(id).addEventListener("input", (e) => set(k, e.target.value.slice(0, 60))));
  $("cCeu").addEventListener("change", (e) => set("ceu", e.target.value));
  $("cVol").addEventListener("input", (e) => set("vol", +e.target.value));
  Object.entries(TG).forEach(([id, k]) => $(id).addEventListener("click", () => set(k, !cfg[k])));
  $("mus").addEventListener("click", () => set("musica", !cfg.musica));
  $("snd").addEventListener("click", () => { cfg.sfx = !!(window.SALA && window.SALA.state.sound); save(); fill(); apply(); });
  $("cCopy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(obsLink()); $("cCopy").textContent = "COPIADO!"; } catch (e) { $("cCopy").textContent = "SELECIONE E COPIE"; }
    setTimeout(() => { $("cCopy").textContent = "COPIAR LINK DO OBS"; }, 2000);
  });
  $("cReset").addEventListener("click", () => { const r = cfg.rede; Object.assign(cfg, DEF, { rede: r }); save(); fill(); apply(); });
  // o navegador só deixa tocar som depois de um clique: o primeiro clique na página destrava a música
  document.addEventListener("pointerdown", () => { if (cfg.musica) Lofi.resume(); }, { passive: true });
  setInterval(() => {
    $("lofiMood").textContent = Lofi.blocked() ? "CLIQUE PARA TOCAR" : Lofi.mood() === "tensa" ? "TENSO" : "CHILL";
  }, 1500);

  fill(); apply();
})();
