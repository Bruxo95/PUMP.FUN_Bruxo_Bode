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
  // 0.32.347: o link leva um código só de leitura (gerado no servidor, que guarda só o hash) para abrir sem login, e o formato:
  // "h" = WEB horizontal 1920×1080, "v" = celular vertical 1080×1920. O código fica só neste navegador.
  const OBSK = "botlive_obs_k";
  let obsK = ""; try { obsK = localStorage.getItem(OBSK) || ""; } catch (e) { /* sem armazenamento */ }
  async function newKey() {
    const r = await BB.api("/api/botlive/obs-link", { method: "POST", body: {} });
    if (!r || !r.k) throw new Error((r && r.error) || "não consegui gerar o link");
    obsK = r.k; try { localStorage.setItem(OBSK, obsK); } catch (e) { /* */ }
    paint();
  }
  function obsLink(layout) {
    if (!obsK) return "";
    const o = Object.assign({}, cfg); delete o.botlive; delete o.mkey; delete o.api; delete o.obs;
    o.k = obsK; o.layout = layout === "v" ? "v" : "h";
    return location.origin + "/botlive/sala?cfg=" + encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(o)))));
  }
  function paint() {
    Object.entries(TG).forEach(([id, k]) => {
      const b = $(id), on = !!cfg[k];
      b.classList.toggle("on", on); b.classList.toggle("off", !on); b.textContent = on ? "Ligado" : "Desligado"; b.setAttribute("aria-checked", on ? "true" : "false");
    });
    $("cVolN").textContent = "· " + cfg.vol + "%";
    $("cLink").textContent = obsLink("h") || "clique em Copiar para criar o link (vale para os dois formatos)";
    $("cLinkV").textContent = obsLink("v") || "clique em Copiar para criar o link (vale para os dois formatos)";
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
    try { if (!obsK) await newKey(); await navigator.clipboard.writeText(obsLink(lay)); $(id).textContent = "Copiado!"; }
    catch (e) { $(id).textContent = "Selecione o link e copie"; }
    setTimeout(() => { $(id).textContent = txt; }, 2000);
  }));
  $("cNew").addEventListener("click", async () => {
    try { await newKey(); $("cNew").textContent = "Links novos ✓ (os antigos pararam)"; } catch (e) { $("cNew").textContent = String(e.message || e); }
    setTimeout(() => { $("cNew").textContent = "Gerar links novos"; }, 3000);
  });

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
})();
