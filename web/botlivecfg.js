// 0.32.337 (pedido do dono, 13/11): configuração simples do BOT LIVE (/botlive). Grava em localStorage (botlive_cfg, a mesma que a SALA
// LIVE lê) e monta o link do OBS, que leva a configuração inteira (o OBS tem navegador próprio, sem o que ficou salvo aqui).
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const cfg = window.SALA_CFG, DEF = window.BOTLIVE_DEF, KEY = window.BOTLIVE_KEY;
  const TG = { cMus: "musica", cSfx: "sfx", cBal: "baloes", cPriv: "privado", cPan: "painel", cClean: "limpa" };
  let savedT = null;
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (e) { /* sem armazenamento */ }
    $("cSaved").textContent = "salvo ✓"; clearTimeout(savedT); savedT = setTimeout(() => { $("cSaved").textContent = ""; }, 1500);
    paint();
  }
  // 0.32.347: o link leva um código só de leitura para abrir sem login, e o formato: "h" = WEB horizontal 1920×1080, "v" = celular
  // vertical 1080×1920.
  // 0.32.363 (pedido do dono): um link fixo para cada formato, guardado no servidor: qualquer PC mostra o MESMO link e nada é
  // trocado sozinho. Só muda quando a pessoa clica em "Renovar" daquele formato (o outro continua valendo).
  const OBS = { web: "", mob: "", antigo: false, err: "" };
  async function loadKeys() {
    try {
      const r = await BB.api("/api/botlive/obs-links");
      if (!r || !r.ok) throw new Error((r && r.error) || "não consegui ler os links");
      OBS.web = r.web || ""; OBS.mob = r.mob || ""; OBS.antigo = !!r.antigo; OBS.err = "";
    } catch (e) { OBS.err = String(e.message || e); }
    try { localStorage.removeItem("botlive_obs_k"); } catch (e) { /* o código antigo deste navegador não é mais usado */ }
    paint();
  }
  async function renew(slot) {
    const r = await BB.api("/api/botlive/obs-link", { method: "POST", body: { formato: slot } });
    if (!r || !r.ok) throw new Error((r && r.error) || "não consegui renovar o link");
    if (slot === "antigo") OBS.antigo = false; else OBS[slot] = r[slot] || "";
    paint();
  }
  function obsLink(layout) {
    const k = layout === "v" ? OBS.mob : OBS.web;
    if (!k) return "";
    const o = Object.assign({}, cfg); delete o.botlive; delete o.mkey; delete o.api; delete o.obs;
    o.k = k; o.layout = layout === "v" ? "v" : "h";
    return location.origin + "/botlive/sala?cfg=" + encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(o)))));
  }
  function paint() {
    Object.entries(TG).forEach(([id, k]) => {
      const b = $(id), on = !!cfg[k];
      b.classList.toggle("on", on); b.classList.toggle("off", !on); b.textContent = on ? "Ligado" : "Desligado"; b.setAttribute("aria-checked", on ? "true" : "false");
    });
    $("cVolN").textContent = "· " + cfg.vol + "%";
    const wait = OBS.err ? "erro: " + OBS.err : "carregando o link…";
    $("cLink").textContent = obsLink("h") || wait;
    $("cLinkV").textContent = obsLink("v") || wait;
    $("cOld").hidden = !OBS.antigo;
  }
  function fill() {
    $("cNome").value = cfg.nome || ""; $("cTit").value = cfg.titulo || "";
    $("cSub").value = cfg.sub || ""; $("cCeu").value = cfg.ceu || ""; $("cVol").value = cfg.vol;
    paint();
  }
  [["cCeu", "ceu"]].forEach(([id, k]) => $(id).addEventListener("change", (e) => { cfg[k] = e.target.value; save(); }));
  [["cNome", "nome"], ["cTit", "titulo"], ["cSub", "sub"]].forEach(([id, k]) => $(id).addEventListener("input", (e) => { cfg[k] = e.target.value.slice(0, 60); save(); }));
  $("cVol").addEventListener("input", (e) => { cfg.vol = +e.target.value; save(); });
  Object.entries(TG).forEach(([id, k]) => $(id).addEventListener("click", () => { cfg[k] = !cfg[k]; save(); }));
  [["cCopy", "h", "Copiar link WEB"], ["cCopyV", "v", "Copiar link vertical"]].forEach(([id, lay, txt]) => $(id).addEventListener("click", async () => {
    try { if (!obsLink(lay)) await loadKeys(); await navigator.clipboard.writeText(obsLink(lay)); $(id).textContent = "Copiado!"; }
    catch (e) { $(id).textContent = "Selecione o link e copie"; }
    setTimeout(() => { $(id).textContent = txt; }, 2000);
  }));
  // renovar: só aquele formato; o link que está no OBS desse formato para de abrir na hora
  [["cNewW", "web", "Renovar link WEB", "Renovar o link WEB? O link WEB que está no OBS para de abrir na hora (o link vertical continua valendo)."],
   ["cNewV", "mob", "Renovar link vertical", "Renovar o link vertical? O link vertical que está no OBS/TikTok para de abrir na hora (o link WEB continua valendo)."],
   ["cOldOff", "antigo", "Desligar link antigo", "Desligar o link antigo (de antes desta versão)? Se ele ainda estiver em algum OBS, para de abrir."]].forEach(([id, slot, txt, q]) =>
    $(id).addEventListener("click", async () => {
      if (!window.confirm(q)) return;
      try { await renew(slot); $(id).textContent = slot === "antigo" ? "Desligado ✓" : "Renovado ✓ — copie o link novo"; }
      catch (e) { $(id).textContent = String(e.message || e); }
      setTimeout(() => { $(id).textContent = txt; }, 3000);
    }));
  loadKeys();

  $("cReset").addEventListener("click", () => { Object.assign(cfg, DEF); save(); fill(); });
  // ------------------------------------------------------------------ carteira do BOT (0.32.338): /api/botlive/*
  const n = (v, d) => (v == null || isNaN(v) ? "–" : Number(v).toFixed(d == null ? 4 : d));
  const sg = (v) => (v > 0 ? "+" : "");
  let W = null, zeroArm = 0;
  function walPaint(p) {
    const w = (p && p.carteira) || {}, c = (p && p.cfg_sim) || {};
    W = c;
    const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
    $("wal").innerHTML = [
      ["Total agora", n(w.total) + " ETH"], ["Resultado", '<span class="' + cls(w.resultado) + '">' + sg(w.resultado) + n(w.resultado) + " ETH · " + sg(w.resultado_pct) + n(w.resultado_pct, 2) + "%</span>"],
      ["Acerto", w.acerto == null ? "–" : n(w.acerto, 1) + "% de " + (w.fechadas || 0)], ["Abertas", String(w.abertas || 0)],
    ].map(([k, v]) => "<div><small>" + k + "</small><b>" + v + "</b></div>").join("");
    const on = !!c.on;
    $("wOn").classList.toggle("on", on); $("wOn").classList.toggle("off", !on); $("wOn").textContent = on ? "Ligado" : "Desligado"; $("wOn").setAttribute("aria-checked", on ? "true" : "false");
    if (document.activeElement !== $("wIni")) $("wIni").value = c.saldo_inicial;
    if (document.activeElement !== $("wBuy")) $("wBuy").value = c.eth_por_compra;
    if (document.activeElement !== $("wMax")) $("wMax").value = c.max_abertas;
    [["wStop", "stop_pct"], ["wTa", "trail_ativa_pct"], ["wTd", "trail_dist_pct"], ["wHold", "max_hold_h"]].forEach(([id, k]) => { if (document.activeElement !== $(id)) $(id).value = c[k]; });
  }
  async function walLoad() {
    const p = await BB.api("/api/botlive/painel", { quiet: true });
    if (!p || p.error || p.ligado === false) { $("wal").innerHTML = '<span class="muted">' + BB.esc((p && (p.error || p.motivo)) || "carteira indisponível") + "</span>"; return; }
    walPaint(p);
  }
  async function walSave(raw, msg) {
    const r = await BB.api("/api/botlive/carteira", { method: "POST", body: raw });
    $("wMsg").textContent = r && r.ok ? msg : "Não salvou: " + ((r && (r.error || r.motivo)) || "erro");
    await walLoad();
  }
  $("wOn").addEventListener("click", () => walSave({ on: !(W && W.on) }, W && W.on ? "BOT parado: não abre posições novas." : "BOT operando."));
  $("wSave").addEventListener("click", () => walSave({ saldo_inicial: +$("wIni").value, eth_por_compra: +$("wBuy").value, max_abertas: +$("wMax").value,
    stop_pct: +$("wStop").value, trail_ativa_pct: +$("wTa").value, trail_dist_pct: +$("wTd").value, max_hold_h: +$("wHold").value }, "Carteira salva."));
  $("wZero").addEventListener("click", async () => {
    if (Date.now() - zeroArm > 4000) { zeroArm = Date.now(); $("wZero").textContent = "Clique de novo para zerar"; setTimeout(() => { $("wZero").textContent = "Zerar carteira"; }, 4000); return; }
    zeroArm = 0; $("wZero").textContent = "Zerar carteira";
    const r = await BB.api("/api/botlive/zerar", { method: "POST", body: {} });
    $("wMsg").textContent = r && r.ok ? "Carteira zerada: começa do saldo inicial, sem histórico." : "Não zerou: " + ((r && r.error) || "erro");
    await walLoad();
  });

  $("boot").innerHTML = BB.loader("Carregando", { grid: 4, pattern: "sweep", font: 15, cell: 7, glow: true });
  (async function () {
    let s = null;
    try { s = await BB.session(); } catch (e) { /* sem sessão */ }
    if (!s) { location.href = "/"; return; }
    fill();
    $("boot").hidden = true; $("bl").hidden = false;
    walLoad(); setInterval(walLoad, 15000);
  })();

  // 0.32.349 (pedido do dono): compras do BOT no chat da live do YouTube. As chaves vão para o cofre do servidor (criptografadas);
  // a tela só recebe "configurada: sim/não".
  let YT = null;
  function ytPaint(st) {
    if (st && st.ok !== undefined) YT = st;
    if (!YT) return;
    const on = !!YT.ligado;
    $("ytOn").classList.toggle("on", on); $("ytOn").classList.toggle("off", !on); $("ytOn").textContent = on ? "Ligado" : "Desligado"; $("ytOn").setAttribute("aria-checked", on ? "true" : "false");
    const ro = !!(YT.sala && YT.sala.on);
    $("ytRoom").classList.toggle("on", ro); $("ytRoom").classList.toggle("off", !ro); $("ytRoom").textContent = ro ? "Ligado" : "Desligado"; $("ytRoom").setAttribute("aria-checked", ro ? "true" : "false");
    if (YT.sala) {
      const sl = YT.sala, quando = sl.t ? new Date(sl.t * 1000).toLocaleTimeString("pt-BR") : "ainda não leu";
      $("ytRoomSt").textContent = "a cada 10 min o personagem fala no balão (em inglês) com quem escreveu no chat · última leitura: " + quando +
        (sl.live ? " · " + (sl.names.length ? sl.names.length + " nome(s) no chat" : "ninguém escreveu ainda") + (sl.viewers != null ? " · " + sl.viewers + " assistindo" : "") : " · sem live no ar") +
        (YT.sala_erro ? " · erro: " + YT.sala_erro : "");
    }
    $("ytCidS").textContent = YT.client_id ? "configurada: sim" : "configurada: não";
    $("ytSecS").textContent = YT.client_secret ? "configurada: sim" : "configurada: não";
    $("ytRet").textContent = YT.retorno || "";
    const u = YT.ultima;
    $("ytSt").textContent = (YT.conectado ? "canal conectado" : "canal não conectado") + (YT.live ? " · live: " + YT.live : "") +
      " · " + (YT.enviadas_hoje || 0) + "/" + (YT.limite_dia || 400) + " hoje" +
      (u ? " · última: " + (u.ok ? "enviada" + (u.info ? " (" + u.info + ")" : "") : "falhou: " + (u.erro || "")) : "");
  }
  async function ytCall(path, body, msg) {
    try {
      const r = await BB.api(path, body === undefined ? {} : { method: "POST", body: body });
      if (r && r.error) throw new Error(r.error);
      ytPaint(r); if (msg) $("ytMsg").textContent = msg;
      return r;
    } catch (e) { $("ytMsg").textContent = String(e.message || e); return null; }
  }
  $("ytOn").addEventListener("click", () => ytCall("/api/botlive/youtube/ligar", { on: !(YT && YT.ligado) }, ""));
  $("ytRoom").addEventListener("click", () => ytCall("/api/botlive/youtube/sala", { on: !(YT && YT.sala && YT.sala.on) }, ""));
  $("ytSave").addEventListener("click", async () => {
    const cid = $("ytCid").value.trim(), sec = $("ytSec").value.trim();
    if (!cid && !sec) { $("ytMsg").textContent = "cole o Client ID e o Client Secret"; return; }
    if (cid) await ytCall("/api/botlive/youtube/chave", { nome: "client_id", valor: cid });
    if (sec) await ytCall("/api/botlive/youtube/chave", { nome: "client_secret", valor: sec });
    $("ytCid").value = ""; $("ytSec").value = ""; $("ytMsg").textContent = "chaves salvas ✓";
  });
  $("ytCon").addEventListener("click", async () => {
    const r = await ytCall("/api/botlive/youtube/conectar");
    if (r && r.url) location.href = r.url;
  });
  $("ytTest").addEventListener("click", async () => {
    $("ytMsg").textContent = "enviando…";
    const r = await ytCall("/api/botlive/youtube/teste", {});
    if (r) $("ytMsg").textContent = r.ok ? "mensagem enviada ✓ (confira o chat)" : "não enviou: " + ((r.ultima && r.ultima.erro) || "veja o status");
  });
  $("ytDel").addEventListener("click", () => {
    if (!confirm("Remover as chaves e a autorização do YouTube?")) return;
    ytCall("/api/botlive/youtube/remover", {}, "removido ✓");
  });
  (function () {
    const q = new URLSearchParams(location.search);
    if (q.get("yt") === "ok") $("ytMsg").textContent = "YouTube conectado ✓";
    if (q.get("yt") === "erro") $("ytMsg").textContent = "não conectou: " + (q.get("msg") || "");
    if (q.get("yt")) { try { history.replaceState(null, "", "/botlive"); } catch (e) { /* */ } }
    ytCall("/api/botlive/youtube");
    setInterval(() => ytCall("/api/botlive/youtube"), 30000);
  })();

  // 0.32.351 (pedido do dono): músicas lofi de verdade, 4 playlists por horário. O arquivo vai direto para o servidor (corpo cru,
  // com o token do login); o servidor confere se é MP3/OGG e guarda num bucket privado.
  let MU = null;
  const esc = (x) => String(x == null ? "" : x).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  function muPaint(j) {
    if (j && j.periodos) MU = j;
    if (!MU) return;
    const P = MU.periodos || {}, keys = Object.keys(P);
    if (!$("muPer").options.length) $("muPer").innerHTML = keys.map((k) => '<option value="' + k + '">' + esc(P[k].nome) + "</option>").join("");
    const gen = !!MU.so_gerada;
    $("muGen").classList.toggle("on", gen); $("muGen").classList.toggle("off", !gen);
    $("muGen").setAttribute("aria-checked", String(gen)); $("muGen").textContent = gen ? "Ligado" : "Desligado";
    const tz = { timeZone: "Europe/Berlin", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" };
    $("muPlayed").innerHTML = (MU.tocou || []).length ? (MU.tocou || []).slice(0, 30).map((x) =>
      '<div class="murow"><span><b>' + esc(new Date(x.t * 1000).toLocaleString("pt-BR", tz)) + "</b> · " + esc(x.titulo) + (x.artista ? " · " + esc(x.artista) : "") + "</span></div>").join("")
      : '<div class="muted" style="font-size:12px">nada ainda</div>';
    $("muList").innerHTML = keys.map((k) => {
      const fx = (MU.todas || MU.faixas || []).filter((x) => x.periodo === k);
      return '<div class="mubox"><h3>' + esc(P[k].nome) + '</h3><div class="h">' + String(P[k].de).padStart(2, "0") + ":00–" + String(P[k].ate % 24).padStart(2, "0") + ":00 · " + fx.length + " música(s)</div>" +
        (fx.length ? fx.map((x) => '<div class="murow' + (x.off ? " muoff" : "") + '"><span>' + (x.off ? '<b class="mutag">PAUSADA</b> ' : "") + esc(x.titulo) + (x.artista ? " · " + esc(x.artista) : "") +
          (x.fonte && /^https:\/\//.test(x.fonte) ? ' · <a href="' + esc(x.fonte) + '" target="_blank" rel="noopener">origem</a>' : "") + '</span><button class="btn" type="button" data-mupause="' + x.id + '" data-off="' + (x.off ? 1 : 0) + '">' + (x.off ? "Voltar a tocar" : "Pausar") + '</button><select class="in" data-mumv="' + x.id + '">' +
          keys.map((o) => '<option value="' + o + '"' + (o === k ? " selected" : "") + ">" + esc(P[o].nome.split(" · ")[0]) + "</option>").join("") +
          '</select><button class="btn" type="button" data-murm="' + x.id + '">Remover</button></div>').join("") : '<div class="muted" style="font-size:12px">nenhuma ainda (toca as de outro horário)</div>') + "</div>";
    }).join("");
  }
  async function muLoad() { try { muPaint(await BB._api("/api/botlive/musicas")); } catch (e) { $("muList").textContent = "não consegui ler a lista de músicas"; } }
  $("muFile").addEventListener("change", async (ev) => {
    const files = Array.from(ev.target.files || []); ev.target.value = "";
    const s = await BB.session(); if (!s) return;
    let ok = 0, fail = [];
    for (const f of files) {
      $("muMsg").textContent = "enviando " + f.name + "…";
      const base = f.name.replace(/\.[^.]+$/, ""), parts = base.split(" - ");
      try {
        const r = await fetch("/api/botlive/musicas", { method: "POST", body: f, headers: { Authorization: "Bearer " + s.access_token,
          "Content-Type": f.type || "audio/mpeg", "X-Periodo": $("muPer").value, "X-Titulo": encodeURIComponent(parts[0].trim()),
          "X-Artista": encodeURIComponent((parts[1] || "").trim()), "X-Fonte": encodeURIComponent(f.name) } });
        const j = await r.json(); if (!r.ok || j.error) throw new Error(j.error || ("erro " + r.status));
        muPaint(j); ok++;
      } catch (e) { fail.push(f.name + ": " + (e.message || e)); }
    }
    $("muMsg").textContent = (ok ? ok + " enviada(s) ✓" : "") + (fail.length ? " · falhou: " + fail.join("; ") : "");
  });
  $("muGen").addEventListener("click", async () => {
    const on = !(MU && MU.so_gerada);
    const r = await BB.api("/api/botlive/musicas/so-gerada", { method: "POST", body: { on } });
    if (r && !r.error) { muPaint(r); $("muMsg").textContent = on ? "a live passa a tocar só a música gerada (em até 10 min ou ao recarregar a SALA LIVE) ✓" : "faixas voltaram ✓"; }
    else $("muMsg").textContent = (r && r.error) || "erro";
  });
  $("muList").addEventListener("click", async (ev) => {
    const p = ev.target.closest("[data-mupause]");
    if (p) {
      const r = await BB.api("/api/botlive/musicas/pausar", { method: "POST", body: { id: p.dataset.mupause, off: p.dataset.off !== "1" } });
      if (r && !r.error) { muPaint(r); $("muMsg").textContent = p.dataset.off !== "1" ? "pausada ✓" : "voltou ✓"; } else $("muMsg").textContent = (r && r.error) || "erro";
      return;
    }
    const b = ev.target.closest("[data-murm]"); if (!b) return;
    if (!confirm("Remover esta música?")) return;
    const r = await BB.api("/api/botlive/musicas/remover", { method: "POST", body: { id: b.dataset.murm } });
    if (r && !r.error) muPaint(r); else $("muMsg").textContent = (r && r.error) || "erro";
  });
  $("muList").addEventListener("change", async (ev) => {
    const sel = ev.target.closest("[data-mumv]"); if (!sel) return;
    const r = await BB.api("/api/botlive/musicas/periodo", { method: "POST", body: { id: sel.dataset.mumv, periodo: sel.value } });
    if (r && !r.error) { muPaint(r); $("muMsg").textContent = "movida ✓"; } else $("muMsg").textContent = (r && r.error) || "erro";
  });
  muLoad();
  setInterval(muLoad, 60000);
})();
